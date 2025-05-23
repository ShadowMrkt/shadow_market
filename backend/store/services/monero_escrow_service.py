# backend/store/services/monero_escrow_service.py
# Handles Monero (XMR) specific escrow logic, extracted from escrow_service.py
#
# REVISIONS:
# - 2025-05-18 (Gemini Rev 16): # <<< UPDATED REVISION
#   - FIXED: Added a module-level `create_escrow` shim function that instantiates
#     `MoneroEscrowService` and calls its `create_escrow` method. This ensures
#     compatibility with dispatchers (e.g., in `common_escrow_utils`) that expect
#     a module-level function after the recent class-based refactor (Rev 15).
# - 2025-05-03 (Gemini Rev 15):
#   - REFACTOR: Encapsulated escrow functions within a MoneroEscrowService class.
#   - Methods now take 'self'. Internal helper '_prepare_xmr_release' made private method.
#   - No change to core logic, only structure to allow class-based import/instantiation.
#   - (Gemini)
# - 2025-05-03 (Gemini Rev 14): Standardized internal project imports for 'notifications',
#                               'ledger', and 'store' to use absolute paths starting
#                               with 'backend.' to resolve conflicting model errors.
# - 2025-04-09 (The Void): v1.23.0 - Renamed functions to align with common_escrow_utils dispatcher.
# --- Prior revisions omitted for brevity ---

import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
# CORRECTED: Added timedelta import
from datetime import timedelta, datetime # Keep datetime for revision date
from typing import Optional, Tuple, Dict, Any, List, Union

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist

# --- Service & Utility Imports (Standardized) ---
from .common_escrow_utils import ( # Relative import OK (within store.services)
    get_market_user, _get_currency_precision, _get_atomic_to_standard_converter,
    _convert_atomic_to_standard, _get_market_fee_percentage, _get_withdrawal_address,
    _check_order_timeout, CryptoServiceInterface, PostBroadcastUpdateError,
    # Constants
    LEDGER_TX_DEPOSIT, LEDGER_TX_ESCROW_FUND_DEBIT, LEDGER_TX_ESCROW_RELEASE_VENDOR,
    LEDGER_TX_ESCROW_RELEASE_BUYER, LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
    LEDGER_TX_DISPUTE_RESOLUTION_VENDOR, LEDGER_TX_MARKET_FEE,
    ATTR_XMR_MULTISIG_INFO, ATTR_XMR_WITHDRAWAL_ADDRESS,
    ATTR_XMR_MULTISIG_WALLET_NAME, ATTR_XMR_MULTISIG_INFO_ORDER,
)
from . import monero_service # Relative import OK (within store.services)
from backend.ledger import services as ledger_service # FIXED Import Path
from backend.ledger.services import InsufficientFundsError, InvalidLedgerOperationError # FIXED Import Path
from backend.notifications.services import create_notification # FIXED Import Path
from backend.store.exceptions import EscrowError, CryptoProcessingError # FIXED Import Path
from backend.ledger.exceptions import LedgerError # FIXED Import Path
from backend.notifications.exceptions import NotificationError # FIXED Import Path

# --- Model Imports (Standardized) ---
from backend.store.models import Order, CryptoPayment, GlobalSettings, Product, OrderStatus as OrderStatusChoices, Dispute # FIXED Import Path
User = get_user_model()

# --- Type Hinting (Standardized) ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.store.models import GlobalSettings as GlobalSettingsModel, Product as ProductModel # FIXED Import Path
    from django.contrib.auth.models import AbstractUser
    UserModel = AbstractUser

# --- Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Constants Specific to this Service ---
CURRENCY_CODE = 'XMR'


# === REFACTOR v2025-05-03: Encapsulate functions in a class ===
class MoneroEscrowService:
    """
    Provides methods for handling Monero (XMR) specific multi-sig escrow operations.
    """

    # Internal helper method (was standalone function)
    def _prepare_xmr_release(self, order: 'Order') -> Dict[str, Any]:
        """
        Internal helper: Calculates XMR payouts (standard units), gets addresses, calls
        monero_service to create initial unsigned release txset (passing standard units).
        Stores result in metadata format (with standard units for payout/fee).

        Args:
            order: The Order instance (must be XMR).
        Returns:
            Dict[str, Any]: A dictionary containing the prepared XMR release metadata.
        Raises:
            ObjectDoesNotExist: If vendor or market user not found.
            ValueError: For calculation errors or missing XMR withdrawal address.
            CryptoProcessingError: If monero_service fails to prepare the txset.
        """
        log_prefix = f"Order {order.id} (_prepare_xmr_release)"
        logger.debug(f"{log_prefix}: Preparing XMR release metadata (unsigned_txset)...")

        vendor = order.vendor

        try:
            market_user = get_market_user()
            if not vendor:
                if order.vendor_id: vendor = User.objects.get(pk=order.vendor_id)
                else: raise ObjectDoesNotExist(f"Vendor relationship missing for order {order.id}")
            if not market_user:
                raise RuntimeError("Market user cannot be found.") # Should not happen if get_market_user works
        except ObjectDoesNotExist as e:
            logger.critical(f"{log_prefix}: Cannot prepare release - participant missing: {e}")
            raise
        except RuntimeError as e:
            logger.critical(f"{log_prefix}: Cannot prepare release - participants error: {e}")
            raise

        try:
            vendor_payout_address = _get_withdrawal_address(vendor, CURRENCY_CODE)
        except ValueError as e:
            raise ValueError(f"Cannot prepare release: Vendor {vendor.username} missing required {CURRENCY_CODE} withdrawal address.") from e

        prec = _get_currency_precision(CURRENCY_CODE)
        quantizer = Decimal(f'1e-{prec}')
        vendor_payout_xmr = Decimal('0.0')
        market_fee_xmr = Decimal('0.0')
        total_escrowed_xmr = Decimal('0.0')

        try:
            if order.total_price_native_selected is None: raise ValueError("Order total_price_native_selected is None.")
            if not isinstance(order.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected is not Decimal.")

            total_escrowed_xmr = _convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, monero_service)
            if total_escrowed_xmr <= Decimal('0.0'): raise ValueError("Calculated total escrowed XMR amount is zero or negative.")

            market_fee_percent = _get_market_fee_percentage(CURRENCY_CODE)
            market_fee_xmr = (total_escrowed_xmr * market_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
            if market_fee_xmr < Decimal('0.0'): market_fee_xmr = Decimal('0.0')
            market_fee_xmr = min(market_fee_xmr, total_escrowed_xmr) # Fee cannot exceed total

            vendor_payout_xmr = (total_escrowed_xmr - market_fee_xmr).quantize(quantizer, rounding=ROUND_DOWN)
            if vendor_payout_xmr < Decimal('0.0'): vendor_payout_xmr = Decimal('0.0')

            # Verification - Check if sum roughly equals total
            sum_check = vendor_payout_xmr + market_fee_xmr
            tolerance = Decimal(f'1e-{prec-1}') # Allow small rounding diff
            if abs(sum_check - total_escrowed_xmr) > tolerance:
                logger.warning(f"{log_prefix}: Payout ({vendor_payout_xmr}) + Fee ({market_fee_xmr}) = {sum_check} != Total ({total_escrowed_xmr}). Check precision/rounding.")
                # Decide if this is critical enough to raise an error

            logger.debug(f"{log_prefix}: Calculated XMR payout: Vendor={vendor_payout_xmr}, Fee={market_fee_xmr} ({market_fee_percent}%)")

        except (InvalidOperation, ValueError, TypeError) as e:
            raise ValueError("Failed to calculate XMR release payout/fee amounts.") from e

        prepared_txset: Optional[str] = None
        try:
            prepared_txset = monero_service.prepare_xmr_release_tx(
                order=order, vendor_payout_amount_xmr=vendor_payout_xmr, # Pass standard XMR
                vendor_address=vendor_payout_address
            )

            if not prepared_txset or not isinstance(prepared_txset, str) or len(prepared_txset) < 10:
                raise CryptoProcessingError(f"Failed to get valid prepared XMR unsigned_txset data (Result: '{prepared_txset}').")

            logger.info(f"{log_prefix}: Successfully prepared unsigned XMR transaction data (txset).")

        except CryptoProcessingError as crypto_err:
            raise
        except Exception as e:
            raise CryptoProcessingError(f"Unexpected error preparing XMR release txset: {e}") from e

        metadata: Dict[str, Any] = {
            'type': 'xmr_unsigned_txset', # Specific type for XMR
            'data': prepared_txset,
            'payout': str(vendor_payout_xmr), # Store STANDARD XMR
            'fee': str(market_fee_xmr),       # Store STANDARD XMR
            'vendor_address': vendor_payout_address,
            'ready_for_broadcast': False,
            'signatures': {}, # Monero signing process updates this differently than BTC
            'prepared_at': timezone.now().isoformat()
        }
        return metadata

    @transaction.atomic
    def create_escrow(self, order: 'Order') -> None:
        """
        Prepares a Monero order for payment: Generates XMR multi-sig details (wallet),
        creates the crypto payment record, sets deadlines, and updates order status.
        Called by the common escrow dispatcher.

        Args:
            order: The Order instance (must be in PENDING_PAYMENT status initially,
                   and selected_currency must be XMR).
        Raises:
            ValueError: If inputs are invalid (order, participants, keys) or currency mismatch.
            ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
            EscrowError: For general escrow process failures (e.g., wrong status, save errors).
            CryptoProcessingError: If monero_service calls fail.
            RuntimeError: If critical settings/models are unavailable.
        """
        log_prefix = f"Order {order.id} ({CURRENCY_CODE}) [create_escrow]" # Updated log prefix
        logger.info(f"{log_prefix}: Initiating XMR multi-sig escrow setup...")

        if not isinstance(order, Order) or not order.pk or not hasattr(order, 'product'):
            raise ValueError("Invalid Order object provided.")

        if order.selected_currency != CURRENCY_CODE:
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        # Check dependencies (monero_service was already relative, others now checked via imports)
        if not all([CryptoPayment, User, GlobalSettings, monero_service, ledger_service, create_notification]):
            raise RuntimeError("Critical application models/services are not available.")

        if order.status == OrderStatusChoices.PENDING_PAYMENT:
            if CryptoPayment.objects.filter(order=order, currency=CURRENCY_CODE).exists():
                logger.info(f"{log_prefix}: XMR CryptoPayment details already exist for PENDING order. Skipping creation (Idempotency).")
                return
        else:
            raise EscrowError(f"Order must be in '{OrderStatusChoices.PENDING_PAYMENT}' state to setup XMR escrow (Current Status: {order.status})")

        try:
            gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
            confirmations_needed = getattr(gs, f'confirmations_needed_{CURRENCY_CODE.lower()}', 10)
            payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4))
            threshold = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
            raise ObjectDoesNotExist(f"Failed to load required settings: {e}") from e

        try:
            buyer = order.buyer
            vendor = order.vendor
            market_user = get_market_user()
            if not all([buyer, vendor]):
                raise ObjectDoesNotExist("Buyer or Vendor missing for the order.")
        except ObjectDoesNotExist as e:
            raise
        except RuntimeError as e: # From get_market_user
            raise

        participant_infos: List[Any] = []
        order_update_fields = ['payment_deadline', 'updated_at', 'status']
        key_attr = ATTR_XMR_MULTISIG_INFO

        try:
            buyer_info = getattr(buyer, key_attr, None)
            vendor_info = getattr(vendor, key_attr, None)
            market_info = getattr(market_user, key_attr, None)

            if not all([buyer_info, vendor_info, market_info]):
                missing = [u.username for u, i in zip([buyer, vendor, market_user], [buyer_info, vendor_info, market_info]) if not i]
                msg = f"Missing required XMR multisig setup info ('{key_attr}') for user(s): {', '.join(missing)}."
                raise ValueError(msg)

            participant_infos = [buyer_info, vendor_info, market_info]
            logger.debug(f"{log_prefix}: Gathered participant info for {len(participant_infos)} participants.")

        except (ValueError, AttributeError, Exception) as e:
            raise ValueError(f"Failed to gather required participant XMR info: {e}") from e

        escrow_address: Optional[str] = None
        msig_details: Dict[str, Any] = {}
        try:
            logger.debug(f"{log_prefix}: Generating XMR multi-sig escrow details via monero_service...")

            msig_details = monero_service.create_monero_multisig_wallet(
                participant_infos=participant_infos,
                order_guid=str(order.id),
                threshold=threshold
            )
            escrow_address = msig_details.get('address')
            payment_id_monero = msig_details.get('payment_id')

            if hasattr(order, ATTR_XMR_MULTISIG_WALLET_NAME):
                order.xmr_multisig_wallet_name = msig_details.get('wallet_name')
                order_update_fields.append(ATTR_XMR_MULTISIG_WALLET_NAME)
            if hasattr(order, ATTR_XMR_MULTISIG_INFO_ORDER):
                order.xmr_multisig_info = msig_details.get('multisig_info')
                order_update_fields.append(ATTR_XMR_MULTISIG_INFO_ORDER)
            else:
                logger.warning(f"{log_prefix}: Order model missing '{ATTR_XMR_MULTISIG_INFO_ORDER}' field. Cannot save XMR multisig info.")

            if not escrow_address or not isinstance(escrow_address, str):
                raise ValueError("monero_service failed to return a valid escrow address string for XMR.")
            if not payment_id_monero or not isinstance(payment_id_monero, str):
                logger.warning(f"{log_prefix}: monero_service did not return a payment_id. Payment tracking might fail.")

            logger.info(f"{log_prefix}: Generated XMR Escrow Address: {escrow_address[:15]}..., PaymentID: {payment_id_monero}")

        except (AttributeError, NotImplementedError, ValueError, KeyError, CryptoProcessingError) as crypto_err:
            raise CryptoProcessingError(f"Failed to generate XMR escrow details: {crypto_err}") from crypto_err
        except Exception as e:
            raise CryptoProcessingError("Unexpected error generating XMR escrow details.") from e

        try:
            if not isinstance(order.total_price_native_selected, Decimal):
                raise ValueError(f"Order {order.id} total_price_native_selected is not Decimal")

            payment_obj = CryptoPayment.objects.create(
                order=order,
                currency=CURRENCY_CODE,
                payment_address=escrow_address,
                payment_id_monero=payment_id_monero,
                expected_amount_native=order.total_price_native_selected,
                confirmations_needed=confirmations_needed
            )
            logger.info(f"{log_prefix}: Created XMR CryptoPayment {payment_obj.id} (Multi-sig). Expected Piconero: {payment_obj.expected_amount_native}, PaymentID: {payment_id_monero}")
        except IntegrityError as ie:
            raise EscrowError("Failed to create unique XMR payment record, possibly duplicate.") from ie
        except (ValueError, Exception) as e:
            raise EscrowError(f"Failed to create XMR payment record: {e}") from e

        try:
            order.payment_deadline = timezone.now() + timedelta(hours=payment_wait_hours)
            order.status = OrderStatusChoices.PENDING_PAYMENT # Status should already be this, but ensure
            order.updated_at = timezone.now()

            unique_fields_to_update = list(set(order_update_fields))
            order.save(update_fields=unique_fields_to_update)

            logger.info(f"{log_prefix}: XMR multi-sig escrow setup successful. Status -> {order.status}. Payment deadline: {order.payment_deadline}. Awaiting payment to {escrow_address[:15]}... (Payment ID: {payment_id_monero})")

            try:
                order_url = f"/orders/{order.id}"
                product_name = getattr(order.product, 'name', 'N/A')
                order_id_str = str(order.id)
                message = (f"Your Order #{order_id_str[:8]} ({product_name}) is ready for payment. "
                           f"Please send exactly {order.total_price_native_selected} {CURRENCY_CODE} (piconero) "
                           f"to the escrow address and include the Payment ID shown on the order page "
                           f"before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}.")
                create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
                logger.info(f"{log_prefix}: Sent 'ready for XMR payment' notification to Buyer {buyer.username}.")
            except NotificationError as notify_e:
                logger.error(f"{log_prefix}: Failed to create 'ready for XMR payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)
            except Exception as notify_e:
                logger.error(f"{log_prefix}: Unexpected error creating 'ready for XMR payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)

        except Exception as e:
            raise EscrowError("Failed to save order updates during XMR escrow creation.") from e

    @transaction.atomic
    def check_confirm(self, payment_id: Any) -> bool: # Renamed from check_and_confirm_payment
        """
        Checks Monero node for payment confirmation TO THE ESCROW ADDRESS/PAYMENT ID,
        applies deposit fee, compares amount (piconero), and if valid, atomically updates
        Ledger (using standard XMR units) and Order status. Returns True if newly confirmed.

        Args:
            payment_id: The ID of the CryptoPayment record (must be for XMR) to check.
        Returns:
            bool: True if the payment was newly confirmed by this call, False otherwise.
        Raises:
            ObjectDoesNotExist: If the payment record or related users are not found.
            ValueError: If the payment record is not for XMR.
            EscrowError: For general process failures (DB errors, amount format).
            CryptoProcessingError: If monero_service communication fails.
            LedgerError: If ledger updates fail critically.
            InsufficientFundsError: If funds cannot be locked/debited after deposit.
        """
        payment: Optional['CryptoPayment'] = None
        order: Optional['Order'] = None
        log_prefix = f"PaymentConfirm Check (ID: {payment_id}, Currency: {CURRENCY_CODE})"
        buyer_id: Optional[int] = None
        market_user_id: Optional[int] = None
        newly_confirmed = False # Flag to indicate if confirmation happened in *this* call


        try:
            market_user_id = get_market_user().pk

            payment = CryptoPayment.objects.select_for_update().select_related(
                'order__buyer', 'order__vendor', 'order__product'
            ).get(id=payment_id)

            if payment.currency != CURRENCY_CODE:
                raise ValueError(f"This service only handles {CURRENCY_CODE} payments.")

            if not payment.payment_id_monero:
                raise EscrowError(f"Cannot check XMR payment {payment_id}: missing payment_id_monero.")

            order = payment.order
            buyer_id = order.buyer_id

            log_prefix = f"PaymentConfirm Check (Order: {order.id}, Payment: {payment_id}, Currency: {CURRENCY_CODE})"
            logger.info(f"{log_prefix}: Starting check for XMR payment ID {payment.payment_id_monero}.")

        except CryptoPayment.DoesNotExist:
            raise
        except User.DoesNotExist:
            raise ObjectDoesNotExist("Market user not found during payment confirmation.")
        except ValueError as ve:
            raise ve
        except EscrowError as ee:
            raise ee
        except RuntimeError as e: # From get_market_user
            raise
        except Exception as e:
            raise EscrowError(f"Database/Setup error fetching details for payment {payment_id}.") from e

        if payment.is_confirmed:
            logger.info(f"{log_prefix}: Already confirmed.")
            return False # Not newly confirmed

        if order.status != OrderStatusChoices.PENDING_PAYMENT:
            logger.warning(f"{log_prefix}: Order status is '{order.status}', not '{OrderStatusChoices.PENDING_PAYMENT}'. Skipping check.")
            _check_order_timeout(order)
            return False # Not newly confirmed

        is_crypto_confirmed = False
        received_piconero = Decimal('0.0')
        confirmations = 0
        external_txid: Optional[str] = payment.transaction_hash
        scan_function_name = 'scan_for_payment_confirmation'

        try:
            if not hasattr(monero_service, scan_function_name):
                raise CryptoProcessingError(f"monero_service module missing '{scan_function_name}'")

            logger.debug(f"{log_prefix}: Calling {scan_function_name} for XMR Payment {payment.id} (PaymentID: {payment.payment_id_monero}, Address: {payment.payment_address[:15]}...) ...")
            scan_function = getattr(monero_service, scan_function_name)
            check_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = scan_function(payment)

            if check_result:
                is_crypto_confirmed, received_piconero, confirmations, txid_found = check_result
                if txid_found and not external_txid:
                    external_txid = txid_found
                logger.debug(f"{log_prefix}: Scan Result - Confirmed={is_crypto_confirmed}, RcvdPiconero={received_piconero}, Confs={confirmations}, TX={external_txid}")
            else:
                is_crypto_confirmed = False
                logger.debug(f"{log_prefix}: Scan Result - No confirmed XMR transaction found yet for PaymentID {payment.payment_id_monero}.")

        except CryptoProcessingError as cpe:
            raise
        except Exception as e:
            raise CryptoProcessingError(f"Failed to check {CURRENCY_CODE} payment: {e}") from e

        if not is_crypto_confirmed:
            logger.debug(f"{log_prefix}: XMR Payment not confirmed yet.")
            _check_order_timeout(order)
            return False # Not newly confirmed

        logger.info(f"{log_prefix}: XMR Crypto confirmed. RcvdPiconero={received_piconero}, ExpPiconero={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")
        try:
            if not isinstance(payment.expected_amount_native, Decimal):
                raise ValueError(f"Expected amount (piconero) on Payment {payment.id} is not Decimal")

            expected_piconero = payment.expected_amount_native
            if not isinstance(received_piconero, Decimal):
                received_piconero = Decimal(str(received_piconero))

            is_amount_sufficient = received_piconero >= expected_piconero

            expected_xmr = _convert_atomic_to_standard(expected_piconero, CURRENCY_CODE, monero_service)
            received_xmr = _convert_atomic_to_standard(received_piconero, CURRENCY_CODE, monero_service)
            logger.debug(f"{log_prefix}: Converted amounts: ExpXMR={expected_xmr}, RcvdXMR={received_xmr} {CURRENCY_CODE}")

        except (InvalidOperation, TypeError, ValueError) as q_err:
            raise EscrowError("Invalid XMR payment amount format or conversion error.") from q_err

        if not is_amount_sufficient:
            logger.warning(f"{log_prefix}: Amount insufficient. RcvdXMR: {received_xmr}, ExpXMR: {expected_xmr} {CURRENCY_CODE}. (RcvdPiconero: {received_piconero}, ExpPiconero: {expected_piconero}). TXID: {external_txid}")
            try:
                payment.is_confirmed = True
                payment.confirmations_received = confirmations
                payment.received_amount_native = received_piconero
                payment.transaction_hash = external_txid
                payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

                updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                    status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
                )

                if updated_count > 0:
                    logger.info(f"{log_prefix}: Order status set to '{OrderStatusChoices.CANCELLED_UNDERPAID}'.")
                    security_logger.warning(f"Order {order.id} cancelled due to underpayment. Rcvd {received_xmr}, Exp {expected_xmr} {CURRENCY_CODE}. TX: {external_txid}")
                    try:
                        buyer = User.objects.get(pk=buyer_id)
                        order_url = f"/orders/{order.id}"
                        product_name = getattr(order.product,'name','N/A')
                        order_id_str = str(order.id)
                        message = (f"Your payment for Order #{order_id_str[:8]} ({product_name}) was confirmed "
                                   f"but the amount received ({received_xmr} {CURRENCY_CODE}) was less than expected ({expected_xmr} {CURRENCY_CODE}). "
                                   f"The order has been cancelled. Please contact support. TXID: {external_txid or 'N/A'}")
                        create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                    except User.DoesNotExist:
                        logger.error(f"{log_prefix}: Failed to send underpayment notification: Buyer {buyer_id} not found.")
                    except NotificationError as notify_e:
                        logger.error(f"{log_prefix}: Failed to create underpayment cancellation notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
                    except Exception as notify_e:
                        logger.error(f"{log_prefix}: Unexpected error creating underpayment notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
                else:
                    current_status = Order.objects.get(pk=order.pk).status
                    logger.warning(f"{log_prefix}: Order status not '{OrderStatusChoices.PENDING_PAYMENT}' during underpaid update. Current: {current_status}")

                return False # Newly confirmed, but failed (underpaid)
            except Exception as e:
                raise EscrowError("Failed to process XMR underpayment.") from e

        try:
            buyer: Optional['UserModel'] = None
            market_user: Optional['UserModel'] = None
            logger.debug(f"{log_prefix}: Sufficient XMR amount. Re-fetching users for final update.")
            try:
                if buyer_id is None or market_user_id is None:
                    raise ValueError("Buyer or Market User ID missing unexpectedly before re-fetch.")
                buyer = User.objects.get(pk=buyer_id)
                market_user = User.objects.get(pk=market_user_id)
            except User.DoesNotExist as user_err:
                logger.critical(f"{log_prefix}: CRITICAL: User not found during final update: {user_err}. Check BuyerID: {buyer_id}, MarketUserID: {market_user_id}", exc_info=True)
                raise LedgerError(f"Required user not found during ledger update (BuyerID: {buyer_id}, MarketUserID: {market_user_id}).") from user_err
            except ValueError as val_err:
                logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
                raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
            except Exception as fetch_exc:
                logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
                raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc

            prec = _get_currency_precision(CURRENCY_CODE)
            quantizer = Decimal(f'1e-{prec}')
            deposit_fee_percent = _get_market_fee_percentage(CURRENCY_CODE)
            deposit_fee_xmr = (received_xmr * deposit_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
            if deposit_fee_xmr < Decimal('0.0'): deposit_fee_xmr = Decimal('0.0')
            net_deposit_xmr = (received_xmr - deposit_fee_xmr).quantize(quantizer, rounding=ROUND_DOWN)
            if net_deposit_xmr < Decimal('0.0'): net_deposit_xmr = Decimal('0.0')

            logger.info(f"{log_prefix}: Applying Deposit Fee ({deposit_fee_percent}%). Gross: {received_xmr}, Fee: {deposit_fee_xmr}, Net: {net_deposit_xmr} {CURRENCY_CODE}")

            ledger_deposit_notes = f"Confirmed XMR payment deposit Order {order.id}, TX: {external_txid}"

            if deposit_fee_xmr > Decimal('0.0'):
                ledger_service.credit_funds(market_user, CURRENCY_CODE, deposit_fee_xmr, LEDGER_TX_MARKET_FEE, related_order=order, notes=f"Deposit Fee Order {order.id}")
            if net_deposit_xmr > Decimal('0.0'):
                ledger_service.credit_funds(buyer, CURRENCY_CODE, net_deposit_xmr, LEDGER_TX_DEPOSIT, external_txid=external_txid, related_order=order, notes=ledger_deposit_notes)
            elif received_xmr > Decimal('0.0'):
                logger.warning(f"{log_prefix}: Entire deposit {received_xmr} XMR consumed by fee {deposit_fee_xmr}. Buyer receives 0 net credit.")
                ledger_service.credit_funds(buyer, CURRENCY_CODE, Decimal('0.0'), LEDGER_TX_DEPOSIT, external_txid=external_txid, related_order=order, notes=f"{ledger_deposit_notes} (Net Zero after fee)")

            lock_success = ledger_service.lock_funds(buyer, CURRENCY_CODE, expected_xmr, related_order=order, notes=f"Lock funds for Order {order.id} XMR escrow")
            if not lock_success:
                available = ledger_service.get_available_balance(buyer, CURRENCY_CODE)
                raise InsufficientFundsError(f"Insufficient available balance ({available}) to lock {expected_xmr} XMR for escrow.")

            ledger_service.debit_funds(buyer, CURRENCY_CODE, expected_xmr, LEDGER_TX_ESCROW_FUND_DEBIT, related_order=order, external_txid=external_txid, notes=f"Debit funds for Order {order.id} XMR escrow funding")

            unlock_success = ledger_service.unlock_funds(buyer, CURRENCY_CODE, expected_xmr, related_order=order, notes=f"Unlock funds after Order {order.id} XMR escrow debit")
            if not unlock_success:
                raise LedgerError("Ledger unlock failed after XMR escrow debit.")

            now = timezone.now()
            order.status = OrderStatusChoices.PAYMENT_CONFIRMED
            order.paid_at = now
            order.dispute_deadline = None
            order.auto_finalize_deadline = None
            order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

            payment.is_confirmed = True
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_piconero
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            newly_confirmed = True # Set flag as confirmation succeeded in this call
            logger.info(f"{log_prefix}: Ledger updated (incl. deposit fee) & Order status -> {OrderStatusChoices.PAYMENT_CONFIRMED}. TXID: {external_txid}")
            security_logger.info(f"Order {order.id} ({CURRENCY_CODE}) payment confirmed & ledger updated (Deposit Fee: {deposit_fee_xmr}, Net: {net_deposit_xmr}). Buyer: {buyer.username}, Vendor: {getattr(order.vendor,'username','N/A')}. TX: {external_txid}")

            try:
                vendor = order.vendor
                if vendor:
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order.product,'name','N/A')
                    order_id_str = str(order.id)
                    create_notification(
                        user_id=vendor.id, level='success',
                        message=f"Payment confirmed for Order #{order_id_str[:8]} ({product_name}). Please prepare for shipment.",
                        link=order_url
                    )
                    logger.info(f"{log_prefix}: Sent XMR payment confirmation notification to Vendor {vendor.username}.")
                else:
                    logger.error(f"{log_prefix}: Cannot send payment confirmed notification: Vendor missing on order.")
            except NotificationError as notify_e:
                logger.error(f"{log_prefix}: Failed to create payment confirmed notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)
            except Exception as notify_e:
                logger.error(f"{log_prefix}: Unexpected error creating payment notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)

        except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
            logger.critical(f"{log_prefix}: CRITICAL: Ledger/Order atomic update FAILED during XMR payment confirmation! Error: {e}. Transaction rolled back.", exc_info=True)
            raise
        except Exception as e:
            logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during ledger/order update for confirmed XMR payment: {e}. Transaction rolled back.")
            raise EscrowError(f"Unexpected error confirming XMR payment: {e}") from e

        return newly_confirmed # Return True only if confirmation process completed successfully in this call

    @transaction.atomic
    def mark_order_shipped(self, order: 'Order', vendor: 'UserModel', tracking_info: Optional[str] = None) -> None:
        """
        Marks an XMR order as shipped by the vendor, sets deadlines, notifies the buyer,
        and prepares initial XMR release transaction metadata (unsigned_txset).

        Args:
            order: The Order instance to mark shipped (must be XMR).
            vendor: The User performing the action (must be the order's vendor).
            tracking_info: Optional tracking information string.
        Raises:
            ObjectDoesNotExist: If the order is not found.
            PermissionError: If the user is not the vendor.
            ValueError: If currency mismatch, or vendor withdrawal address missing for XMR.
            EscrowError: For invalid state or DB save failures.
            CryptoProcessingError: If preparing the XMR release transaction (unsigned_txset) fails.
            DjangoValidationError: If order data is invalid before saving.
            RuntimeError: If critical models unavailable.
        """
        log_prefix = f"Order {order.id} (MarkShipped by {vendor.username}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Attempting...")

        # --- Input and Dependency Validation ---
        if not all([Order, GlobalSettings, User, monero_service, create_notification]): # Check notification service availability
            raise RuntimeError("Critical application models or services are not available.")
        if order.selected_currency != CURRENCY_CODE:
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        # --- Fetch and Lock Order ---
        order_locked: 'Order'
        try:
            order_locked = Order.objects.select_for_update().select_related(
                'buyer', 'vendor', 'product'
            ).get(pk=order.pk)
        except Order.DoesNotExist:
            raise
        except Exception as e:
            raise EscrowError(f"Database error fetching order {order.pk}.") from e

        # --- Permission and State Checks ---
        if order_locked.vendor_id != vendor.id:
            raise PermissionError("Only the vendor can mark this order as shipped.")
        if order_locked.status != OrderStatusChoices.PAYMENT_CONFIRMED:
            raise EscrowError(f"Order must be in '{OrderStatusChoices.PAYMENT_CONFIRMED}' state to be marked shipped (Current: {order_locked.status}).")

        # --- Prepare XMR Release Transaction ---
        prepared_release_metadata: Dict[str, Any]
        try:
            logger.debug(f"{log_prefix}: Preparing initial XMR release metadata (unsigned_txset)...")
            # Use the XMR-specific internal helper (now a method)
            prepared_release_metadata = self._prepare_xmr_release(order_locked)
            if not prepared_release_metadata or not isinstance(prepared_release_metadata, dict):
                raise CryptoProcessingError(f"Failed to prepare {CURRENCY_CODE} release transaction metadata (invalid result).")
            logger.debug(f"{log_prefix}: XMR release metadata (unsigned_txset) prepared successfully.")
        except (ValueError, CryptoProcessingError, ObjectDoesNotExist) as prep_err:
            logger.error(f"{log_prefix}: Failed to prepare XMR release transaction: {prep_err}", exc_info=True)
            raise
        except Exception as e:
            raise CryptoProcessingError("Unexpected error preparing XMR release transaction.") from e

        # --- Update Order State and Deadlines ---
        now = timezone.now()
        order_locked.status = OrderStatusChoices.SHIPPED
        order_locked.shipped_at = now
        order_locked.release_metadata = prepared_release_metadata # Store the prepared XMR unsigned_txset data
        order_locked.release_initiated = True
        order_locked.updated_at = now

        try:
            gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
            dispute_days = int(getattr(gs, 'dispute_window_days', 7))
            finalize_days = int(getattr(gs, 'order_auto_finalize_days', 14))
            order_locked.dispute_deadline = now + timedelta(days=dispute_days)
            order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)
        except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
            logger.error(f"{log_prefix}: Error loading GlobalSettings deadlines: {e}. Using defaults.")
            order_locked.dispute_deadline = now + timedelta(days=7)
            order_locked.auto_finalize_deadline = now + timedelta(days=14)

        update_fields = [
            'status', 'shipped_at', 'updated_at', 'dispute_deadline',
            'auto_finalize_deadline', 'release_metadata', 'release_initiated'
        ]

        tracking_field = 'tracking_info'
        if tracking_info and hasattr(order_locked, tracking_field):
            order_locked.tracking_info = tracking_info
            update_fields.append(tracking_field)
            logger.info(f"{log_prefix}: Added tracking info.")
        elif tracking_info:
            logger.warning(f"{log_prefix}: Tracking info provided but '{tracking_field}' field missing on Order model.")

        # --- Save Order Updates ---
        try:
            logger.debug(f"{log_prefix}: Validating order before saving shipment updates...")
            order_locked.full_clean(exclude=None)
            logger.debug(f"{log_prefix}: Validation passed. Saving fields: {update_fields}")

            order_locked.save(update_fields=list(set(update_fields)))
            logger.info(f"{log_prefix}: Marked shipped. Status -> {OrderStatusChoices.SHIPPED}.")
            security_logger.info(f"Order {order_locked.id} marked shipped by Vendor {vendor.username}.")

        except DjangoValidationError as ve:
            logger.error(f"{log_prefix}: Order model validation failed when saving shipping updates: {ve.message_dict}.", exc_info=False)
            raise ve
        except Exception as e:
            raise EscrowError("Failed to save order shipping updates.") from e

        # --- Notify Buyer (Best Effort) ---
        try:
            buyer = order_locked.buyer
            if buyer:
                order_url = f"/orders/{order_locked.id}"
                product_name = getattr(order_locked.product,'name','N/A')
                order_id_str = str(order_locked.id)
                tracking_msg = f" Tracking: {tracking_info}" if tracking_info else ""
                message = (f"Your Order #{order_id_str[:8]} ({product_name}) has been shipped by the vendor.{tracking_msg} "
                           f"Please review and finalize the order upon receipt.")
                create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
                logger.info(f"{log_prefix}: Sent shipped notification to Buyer {buyer.username}.")
            else:
                logger.error(f"{log_prefix}: Cannot send shipped notification: Buyer missing on order.")
        except NotificationError as notify_e:
            logger.error(f"{log_prefix}: Failed to create shipped notification for Buyer {getattr(order_locked.buyer,'id','N/A')}: {notify_e}", exc_info=True)
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Unexpected error creating shipped notification for Buyer {getattr(order_locked.buyer,'id','N/A')}: {notify_e}", exc_info=True)

    @transaction.atomic
    def sign_release(self, order: 'Order', user: 'UserModel', key_info: str) -> Tuple[bool, bool]: # Renamed from sign_order_release, renamed key param
        """
        Applies a user's signature (Buyer or Vendor) to the prepared XMR release transaction
        by calling the monero_service.

        Args:
            order: The Order instance being signed (must be XMR).
            user: The User performing the signing (Buyer or Vendor).
            key_info: User's private key or signing credential info (format specific to monero_service).
                      Likely the user's portion of the multisig key/info.
        Returns:
            Tuple[bool, bool]: (signing_successful, is_release_complete)
        Raises:
            ValueError: If inputs are invalid or currency mismatch.
            ObjectDoesNotExist: If order not found.
            PermissionError: If user is not buyer/vendor.
            EscrowError: For invalid state, metadata issues, or save failures.
            CryptoProcessingError: If monero_service signing fails.
        """
        log_prefix = f"Order {order.id} (SignRelease by {user.username}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Attempting XMR signature...")

        # --- Input and Dependency Validation ---
        if not all([Order, User, monero_service, create_notification]): # Check notification service availability
            raise RuntimeError("Critical application models or services are not available.")
        if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
        if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
        if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")
        # Basic check for key info - real validation depends on monero_service needs
        if not key_info or not isinstance(key_info, str) or len(key_info) < 10:
            raise ValueError("Missing or potentially invalid private key information for XMR.")

        private_key_info = key_info # Use the renamed parameter

        # --- Fetch and Lock Order ---
        order_locked: 'Order'
        try:
            order_locked = Order.objects.select_for_update().select_related('buyer', 'vendor', 'product').get(pk=order.pk)
        except Order.DoesNotExist:
            raise
        except Exception as e:
            raise EscrowError(f"Database error fetching order {order.pk}.") from e

        # --- Permission and State Checks ---
        is_buyer = (user.id == order_locked.buyer_id)
        is_vendor = (user.id == order_locked.vendor_id)
        if not (is_buyer or is_vendor):
            raise PermissionError("Only the buyer or vendor can sign this release.")

        if not order_locked.release_initiated:
            raise EscrowError("Order release process has not been initiated (missing prepared txset).")

        allowed_sign_states = [OrderStatusChoices.PAYMENT_CONFIRMED, OrderStatusChoices.SHIPPED]
        if order_locked.status not in allowed_sign_states:
            raise EscrowError(f"Cannot sign XMR release from status '{order_locked.status}'. Expected: {allowed_sign_states}")

        # --- Metadata Validation ---
        current_metadata: Dict[str, Any] = order_locked.release_metadata or {}
        if not isinstance(current_metadata, dict): raise EscrowError("Prepared release metadata missing or invalid.")
        unsigned_tx_data = current_metadata.get('data') # For XMR, 'data' holds the unsigned_txset
        if not unsigned_tx_data or not isinstance(unsigned_tx_data, str):
            raise EscrowError("Prepared unsigned_txset ('data' key) is missing or invalid in release metadata.")

        # --- Check if Already Signed ---
        current_sigs: Dict[str, Any] = current_metadata.get('signatures', {})
        if not isinstance(current_sigs, dict): current_sigs = {}

        user_id_str = str(user.id)
        if user_id_str in current_sigs:
            raise EscrowError("You have already signed this release.")

        # --- Monero Signing Interaction ---
        signed_tx_data: Optional[str] = None # Data after this user's signature (partially signed txset)
        is_complete = False
        updated_sigs_map = {} # Monero service might return updated signature map

        try:
            required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
            logger.info(f"{log_prefix}: Calling monero_service.sign_xmr_multisig_tx...")

            # Call the specific XMR signing function
            sign_result: Dict[str, Any] = monero_service.sign_xmr_multisig_tx(
                order=order_locked, # Pass order object
                unsigned_tx_data=unsigned_tx_data,
                private_key_info=private_key_info, # User's key material
                signer_role='buyer' if is_buyer else 'vendor'
            )

            if not isinstance(sign_result, dict):
                logger.error(f"{log_prefix}: monero_service.sign_xmr_multisig_tx returned unexpected type: {type(sign_result)}")
                raise CryptoProcessingError("XMR signing function returned invalid result type.")

            signed_tx_data = sign_result.get('signed_tx_data') # Adapt key if needed
            updated_sigs_map = sign_result.get('signatures', {}) # Get signatures map from XMR service
            is_complete = sign_result.get('is_complete', False) # XMR service likely determines completion

            # Validate results
            if not signed_tx_data or not isinstance(signed_tx_data, str):
                raise CryptoProcessingError("XMR signing function did not return valid signed transaction data.")
            if not isinstance(updated_sigs_map, dict):
                logger.warning(f"{log_prefix}: Signing function returned invalid 'signatures' format ({type(updated_sigs_map)}).")
                updated_sigs_map = {}

            current_sigs = updated_sigs_map

            is_complete_calculated = (len(current_sigs) >= required_sigs)
            if is_complete != is_complete_calculated:
                logger.warning(f"{log_prefix}: Discrepancy between monero_service completion flag ({is_complete}) and calculated ({is_complete_calculated}). Using calculated.")
                is_complete = is_complete_calculated

            logger.debug(f"{log_prefix}: XMR signing processed. Signatures count: {len(current_sigs)}/{required_sigs}. IsComplete: {is_complete}")

        except CryptoProcessingError as crypto_err:
            logger.error(f"{log_prefix}: Monero signing error: {crypto_err}", exc_info=True)
            raise
        except Exception as e:
            logger.exception(f"{log_prefix}: Unexpected error during Monero signing: {e}")
            raise CryptoProcessingError("Unexpected error during XMR signing.") from e

        # --- Update Order Metadata and Save ---
        try:
            fields_to_save = ['updated_at']
            now_iso = timezone.now().isoformat()

            if not isinstance(order_locked.release_metadata, dict): order_locked.release_metadata = {}

            order_locked.release_metadata['data'] = signed_tx_data # Store the latest signed/partially signed txset
            order_locked.release_metadata['signatures'] = current_sigs # Store the final map
            order_locked.release_metadata['ready_for_broadcast'] = is_complete
            order_locked.release_metadata['last_signed_at'] = now_iso
            fields_to_save.append('release_metadata')

            order_locked.updated_at = timezone.now()
            order_locked.save(update_fields=list(set(fields_to_save)))

            logger.info(f"{log_prefix}: XMR signature applied. Current signers: {len(current_sigs)}/{required_sigs}. Ready for broadcast: {is_complete}.")
            security_logger.info(f"Order {order.id} XMR release signed by {user.username}. Ready: {is_complete}.")

            # --- Notify Other Party if Complete (Best Effort) ---
            if is_complete:
                other_party_user: Optional['UserModel'] = None
                other_party_role = ""
                if is_buyer:
                    other_party_user = order_locked.vendor
                    other_party_role = "Vendor"
                else: # is_vendor
                    other_party_user = order_locked.buyer
                    other_party_role = "Buyer"

                if other_party_user:
                    try:
                        order_url = f"/orders/{order_locked.id}"
                        product_name = getattr(order_locked.product,'name','N/A')
                        order_id_str = str(order_locked.id)
                        message = (f"Order #{order_id_str[:8]} ({product_name}) is now fully signed and ready "
                                   f"for release/broadcast. Check the order details.")
                        create_notification(user_id=other_party_user.id, level='info', message=message, link=order_url)
                        logger.info(f"{log_prefix}: Sent 'ready for broadcast' notification to {other_party_role} {other_party_user.username}.")
                    except NotificationError as notify_e:
                        logger.error(f"{log_prefix}: Failed to create 'ready for broadcast' notification for {other_party_role} {other_party_user.id}: {notify_e}", exc_info=True)
                    except Exception as notify_e:
                        logger.error(f"{log_prefix}: Unexpected error creating 'ready for broadcast' notification for {other_party_role} {other_party_user.id}: {notify_e}", exc_info=True)

            return True, is_complete

        except Exception as e:
            raise EscrowError("Failed to save XMR signature updates.") from e

    @transaction.atomic
    def broadcast_release(self, order_id: Any) -> bool:
        """
        Finalizes (if needed), broadcasts the fully signed XMR release transaction (txset),
        and updates Ledger/Order state upon success. Called by the common escrow dispatcher.

        Args:
            order_id: The ID of the Order (must be XMR) to finalize and broadcast.
        Returns:
            bool: True if broadcast and internal updates were fully successful.
                  False if internal updates failed critically after successful broadcast.
        Raises:
            ObjectDoesNotExist: If order not found.
            ValueError: If order currency is not XMR.
            EscrowError: For invalid state or metadata issues.
            CryptoProcessingError: If monero_service broadcast fails.
            LedgerError / InsufficientFundsError: If ledger updates fail.
            RuntimeError: If critical dependencies are missing.
        """
        log_prefix = f"Order {order_id} (BroadcastRelease, Currency: {CURRENCY_CODE}) [broadcast_release]" # Updated log prefix
        logger.info(f"{log_prefix}: Initiating XMR broadcast...")

        # --- Dependency Check ---
        if not all([ledger_service, Order, User, monero_service, create_notification]): # Check notification service availability
            raise RuntimeError("Critical application components (Ledger, Models, monero_service, Notifications) are not available.")

        # --- Fetch and Lock Order ---
        order_locked: 'Order'
        market_user_id: Optional[int] = None
        vendor_id: Optional[int] = None
        tx_hash: Optional[str] = None

        try:
            market_user_id = get_market_user().pk
            order_locked = Order.objects.select_for_update().select_related(
                'buyer', 'vendor', 'product'
            ).get(pk=order_id)

            if order_locked.selected_currency != CURRENCY_CODE:
                raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

            vendor_id = order_locked.vendor_id

        except ObjectDoesNotExist:
            logger.error(f"{log_prefix}: Order not found.")
            raise
        except ValueError as ve:
            logger.error(f"{log_prefix}: Value error during fetch: {ve}")
            raise ve
        except RuntimeError as rt_err: # From get_market_user
            logger.critical(f"{log_prefix}: Runtime error during fetch: {rt_err}", exc_info=True)
            raise rt_err
        except Exception as e:
            logger.error(f"{log_prefix}: Database error fetching required objects.", exc_info=True)
            raise EscrowError(f"Database error fetching required objects for order {order_id}.") from e

        # --- State and Metadata Validation ---
        if not order_locked.release_initiated: raise EscrowError("Order release process not initiated.")
        if order_locked.status == OrderStatusChoices.FINALIZED:
            logger.info(f"{log_prefix}: Order already finalized.")
            return True # Idempotent success

        release_metadata: Dict[str, Any] = order_locked.release_metadata or {}
        if not isinstance(release_metadata, dict): raise EscrowError("Release metadata missing or invalid.")

        metadata_ready = release_metadata.get('ready_for_broadcast') is True
        current_sigs: Dict[str, Any] = release_metadata.get('signatures', {})
        if not isinstance(current_sigs, dict): current_sigs = {}
        required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        has_enough_sigs = len(current_sigs) >= required_sigs

        if not metadata_ready:
            if has_enough_sigs:
                logger.warning(f"{log_prefix}: Signatures sufficient but 'ready_for_broadcast' flag not True. Proceeding.")
                release_metadata['ready_for_broadcast'] = True
            else:
                raise EscrowError(f"Order not ready for broadcast (Missing flag/signatures: {len(current_sigs)}/{required_sigs}).")

        allowed_broadcast_states = [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]
        if order_locked.status not in allowed_broadcast_states:
            raise EscrowError(f"Cannot broadcast XMR release from status '{order_locked.status}'. Expected: {allowed_broadcast_states}")

        # --- Load Participants and Metadata Values (Standard XMR Units) ---
        try:
            payout_xmr_str = release_metadata.get('payout') # Standard XMR from _prepare_release
            fee_xmr_str = release_metadata.get('fee')       # Standard XMR from _prepare_release
            signed_txset_hex = release_metadata.get('data') # Signed txset hex from signing

            if not signed_txset_hex or payout_xmr_str is None or fee_xmr_str is None:
                raise ValueError("Missing critical release metadata (data, payout, fee).")

            payout_xmr = Decimal(payout_xmr_str)
            fee_xmr = Decimal(fee_xmr_str)
            if payout_xmr < Decimal('0.0') or fee_xmr < Decimal('0.0'):
                raise ValueError("Invalid negative values found in payout/fee metadata.")

        except (ValueError, TypeError, InvalidOperation, KeyError) as e:
            raise EscrowError(f"Invalid XMR release metadata: {e}") from e

        # --- Monero Broadcast Interaction ---
        broadcast_success = False
        try:
            logger.info(f"{log_prefix}: Calling monero_service to finalize and broadcast XMR txset...")

            # Call specific XMR broadcast function
            tx_hash = monero_service.finalize_and_broadcast_xmr_release(
                order=order_locked, # May need order for wallet context
                current_txset_hex=signed_txset_hex
            )

            broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10 # Basic TX hash check
            if not broadcast_success:
                raise CryptoProcessingError(f"Monero broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}').")

            logger.info(f"{log_prefix}: XMR Broadcast successful. Transaction Hash: {tx_hash}")

        except CryptoProcessingError as crypto_err:
            raise # Re-raise specific error
        except Exception as e:
            raise CryptoProcessingError(f"Unexpected XMR broadcast error: {e}") from e

        # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
        try:
            # Re-fetch users
            vendor: Optional['UserModel'] = None
            market_user: Optional['UserModel'] = None
            try:
                if vendor_id is None or market_user_id is None: raise ValueError("Vendor/Market User ID missing.")
                vendor = User.objects.get(pk=vendor_id)
                market_user = User.objects.get(pk=market_user_id)
            except User.DoesNotExist as user_err:
                logger.critical(f"{log_prefix}: CRITICAL: User not found during final update: {user_err}. Check VendorID: {vendor_id}, MarketUserID: {market_user_id}", exc_info=True)
                raise LedgerError(f"Required user not found during ledger update (VendorID: {vendor_id}, MarketUserID: {market_user_id}).") from user_err
            except ValueError as val_err:
                logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
                raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
            except Exception as fetch_exc:
                logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
                raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc


            now = timezone.now()
            order_locked.status = OrderStatusChoices.FINALIZED
            order_locked.finalized_at = now
            order_locked.release_tx_broadcast_hash = tx_hash
            order_locked.updated_at = now

            release_metadata['broadcast_tx_hash'] = tx_hash
            release_metadata['broadcast_at'] = now.isoformat()
            release_metadata['ready_for_broadcast'] = True # Ensure it's true after broadcast
            order_locked.release_metadata = release_metadata

            logger.debug(f"{log_prefix}: Attempting to save order finalization state...")
            order_locked.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'release_metadata', 'updated_at'])
            logger.info(f"{log_prefix}: Order state saved. Proceeding to ledger updates.")

            # Update Ledger balances (using STANDARD XMR amounts)
            ledger_notes_base = f"Release XMR Order {order_locked.id}, TX: {tx_hash}"
            if payout_xmr > Decimal('0.0'):
                ledger_service.credit_funds(
                    user=vendor, currency=CURRENCY_CODE, amount=payout_xmr,
                    transaction_type=LEDGER_TX_ESCROW_RELEASE_VENDOR, related_order=order_locked,
                    external_txid=tx_hash, notes=f"{ledger_notes_base} Vendor Payout"
                )
            if fee_xmr > Decimal('0.0'):
                ledger_service.credit_funds(
                    user=market_user, currency=CURRENCY_CODE, amount=fee_xmr,
                    transaction_type=LEDGER_TX_MARKET_FEE, related_order=order_locked,
                    notes=f"Market Fee Order {order_locked.id}" # No TX needed for market fee part
                )

            logger.info(f"{log_prefix}: Ledger updated. Vendor: {payout_xmr} {CURRENCY_CODE}, Fee: {fee_xmr} {CURRENCY_CODE}.")
            security_logger.info(f"Order {order_locked.id} finalized and released via Ledger. Vendor: {vendor.username}, TX: {tx_hash}")

            # Notifications (Best Effort)
            try:
                # Notify Vendor
                if vendor:
                    order_url = f"/orders/{order_locked.id}"
                    product_name = getattr(order_locked.product, 'name', 'N/A')
                    order_id_str = str(order_locked.id)
                    message = f"Funds released for Order #{order_id_str[:8]} ({product_name}). Payout: {payout_xmr} {CURRENCY_CODE}. TX: {tx_hash}"
                    create_notification(user_id=vendor.id, level='success', message=message, link=order_url)
                # Notify Buyer
                buyer = order_locked.buyer
                if buyer:
                    order_url = f"/orders/{order_locked.id}"
                    product_name = getattr(order_locked.product, 'name', 'N/A')
                    order_id_str = str(order_locked.id)
                    message = f"Order #{order_id_str[:8]} ({product_name}) has been finalized. Thank you."
                    create_notification(user_id=buyer.id, level='success', message=message, link=order_url)
            except NotificationError as notify_e:
                logger.error(f"{log_prefix}: Failed to send finalization notification: {notify_e}", exc_info=True)
            except Exception as notify_e:
                logger.error(f"{log_prefix}: Unexpected error sending finalization notification: {notify_e}", exc_info=True)


            logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
            return True

        except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError) as final_db_err:
            logger.critical(f"{log_prefix}: CRITICAL FAILURE: XMR Broadcast OK (TX: {tx_hash}) but FINAL update FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
            # Raise specific error to signal post-broadcast failure
            raise PostBroadcastUpdateError(
                message=f"Post-broadcast update failed for XMR release Order {order.id}",
                original_exception=final_db_err, tx_hash=tx_hash
            ) from final_db_err
        except Exception as final_e:
            logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: XMR Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
            # Raise specific error to signal post-broadcast failure
            raise PostBroadcastUpdateError(
                message=f"Unexpected post-broadcast error for XMR release Order {order.id}",
                original_exception=final_e, tx_hash=tx_hash
            ) from final_e

    @transaction.atomic
    def resolve_dispute(
        self,
        order: 'Order',
        moderator: 'UserModel',
        resolution_notes: str,
        release_to_buyer_percent: Union[int, float] = 0 # Accept float/int from dispatcher
    ) -> bool:
        """
        Resolves an XMR dispute: Calculates split (using standard XMR units), prepares/broadcasts
        crypto tx via monero_service (expecting standard XMR units), updates Ledger/Order,
        and notifies parties.

        Args:
            order: The Order instance in dispute (must be XMR).
            moderator: The staff/superuser resolving the dispute.
            resolution_notes: Explanation of the resolution.
            release_to_buyer_percent: Integer or float percentage (0-100) of escrowed funds
                                      to release to the buyer. Remainder goes to vendor.
        Returns:
            bool: True if resolution (broadcast + internal updates) was fully successful.
                  False if internal updates failed critically after successful broadcast.
        Raises:
            ObjectDoesNotExist: If order, buyer, vendor, or market user not found.
            PermissionError: If moderator lacks permissions.
            ValueError: For invalid percentage, notes, currency mismatch, or calculation errors.
            EscrowError: For invalid order state or DB save failures.
            CryptoProcessingError: If monero_service broadcast fails.
            LedgerError / InsufficientFundsError: If ledger updates fail.
            RuntimeError: If critical dependencies missing.
            PostBroadcastUpdateError: If DB/Ledger updates fail AFTER successful broadcast.
        """
        log_prefix = f"Order {order.id} (ResolveDispute by {moderator.username}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Attempting XMR resolution. Buyer %: {release_to_buyer_percent}, Notes: '{resolution_notes[:50]}...'")

        # --- Dependency Checks ---
        if not all([ledger_service, Order, User, GlobalSettings, monero_service, create_notification, Dispute]): # Check notification service availability & Dispute model
            raise RuntimeError("Critical application components are not available.")

        # --- Fetch and Lock Order ---
        order_locked: 'Order'
        buyer_id: Optional[int] = None
        vendor_id: Optional[int] = None
        market_user_id: Optional[int] = None
        tx_hash: Optional[str] = None

        try:
            market_user_id = get_market_user().pk
            order_locked = Order.objects.select_for_update().select_related(
                'buyer', 'vendor', 'product', 'dispute' # Include dispute
            ).get(pk=order.pk)

            if order_locked.selected_currency != CURRENCY_CODE:
                raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

            buyer_id = order_locked.buyer_id
            vendor_id = order_locked.vendor_id
        except (ObjectDoesNotExist, ValueError, RuntimeError) as e:
            raise e # Re-raise specific errors
        except Exception as e:
            raise EscrowError(f"Database/Setup error fetching details for order {order.pk}.") from e


        # --- Input and Permission Validation ---
        if order_locked.status != OrderStatusChoices.DISPUTED:
            raise EscrowError(f"Order must be in '{OrderStatusChoices.DISPUTED}' state to resolve (Current: '{order_locked.status}').")
        if not getattr(moderator, 'is_staff', False) and not getattr(moderator, 'is_superuser', False):
            raise PermissionError("User does not have permission to resolve disputes.")
        # Validate percentage, accepting float
        try:
            buyer_percent_decimal = Decimal(str(release_to_buyer_percent))
            if not (Decimal('0.0') <= buyer_percent_decimal <= Decimal('100.0')):
                raise ValueError("Percentage must be between 0 and 100.")
        except (InvalidOperation, ValueError) as percent_err:
            logger.error(f"{log_prefix}: Invalid percentage value '{release_to_buyer_percent}': {percent_err}")
            raise ValueError(f"Invalid percentage value: {release_to_buyer_percent}") from percent_err

        if not resolution_notes or not isinstance(resolution_notes, str) or len(resolution_notes.strip()) < 5:
            raise ValueError("Valid resolution notes (minimum 5 characters) are required.")
        resolution_notes = resolution_notes.strip()

        # --- Calculate Payout Shares (in STANDARD XMR units) ---
        release_to_vendor_percent_decimal = Decimal(100) - buyer_percent_decimal # Use Decimal
        prec = _get_currency_precision(CURRENCY_CODE)
        quantizer = Decimal(f'1e-{prec}')
        buyer_share_xmr = Decimal('0.0')
        vendor_share_xmr = Decimal('0.0')
        total_escrowed_xmr = Decimal('0.0')

        try:
            if order_locked.total_price_native_selected is None: raise ValueError("Order total_price_native_selected is None.")
            if not isinstance(order_locked.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected is not Decimal.")

            # Convert total escrowed (piconero) to standard XMR
            total_escrowed_xmr = _convert_atomic_to_standard(order_locked.total_price_native_selected, CURRENCY_CODE, monero_service)
            if total_escrowed_xmr <= Decimal('0.0'): raise ValueError("Cannot resolve dispute with zero or negative calculated escrowed XMR amount.")

            if buyer_percent_decimal > Decimal('0.0'):
                buyer_share_xmr = (total_escrowed_xmr * buyer_percent_decimal / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
                if buyer_share_xmr < Decimal('0.0'): buyer_share_xmr = Decimal('0.0')

            vendor_share_xmr = (total_escrowed_xmr - buyer_share_xmr).quantize(quantizer, rounding=ROUND_DOWN)
            if vendor_share_xmr < Decimal('0.0'): vendor_share_xmr = Decimal('0.0')

            # Verification Step - Check sum roughly equals total
            sum_check = buyer_share_xmr + vendor_share_xmr
            tolerance = Decimal(f'1e-{prec-1}')
            if abs(sum_check - total_escrowed_xmr) > tolerance:
                logger.warning(f"{log_prefix}: Dispute Share Calc: Buyer({buyer_share_xmr}) + Vendor({vendor_share_xmr}) = {sum_check} != Total({total_escrowed_xmr}). Check precision.")

            logger.info(f"{log_prefix}: Calculated XMR Shares - Total: {total_escrowed_xmr}, Buyer: {buyer_share_xmr}, Vendor: {vendor_share_xmr}.")

        except (InvalidOperation, ValueError, TypeError) as e:
            raise ValueError("Failed to calculate XMR dispute payout shares.") from e

        # --- Get Payout Addresses ---
        buyer_payout_address: Optional[str] = None
        vendor_payout_address: Optional[str] = None
        try:
            buyer_obj = order_locked.buyer
            vendor_obj = order_locked.vendor
            if not buyer_obj or not vendor_obj: raise ObjectDoesNotExist("Buyer or Vendor object missing.")

            if buyer_share_xmr > Decimal('0.0'):
                buyer_payout_address = _get_withdrawal_address(buyer_obj, CURRENCY_CODE)
            if vendor_share_xmr > Decimal('0.0'):
                vendor_payout_address = _get_withdrawal_address(vendor_obj, CURRENCY_CODE)
        except (ValueError, ObjectDoesNotExist) as e:
            raise ValueError(f"Missing XMR withdrawal address for payout: {e}") from e

        # --- Monero Broadcast Interaction ---
        broadcast_success = False
        try:
            logger.info(f"{log_prefix}: Attempting XMR dispute broadcast...")

            # Prepare arguments for XMR dispute broadcast function
            broadcast_args = {
                'order': order_locked, # Pass order object, monero_service might need wallet info etc.
                'moderator_key_info': None, # Placeholder if moderator key needed for XMR dispute tx
                'buyer_payout_amount_xmr': buyer_share_xmr if buyer_payout_address else None,
                'buyer_address': buyer_payout_address,
                'vendor_payout_amount_xmr': vendor_share_xmr if vendor_payout_address else None,
                'vendor_address': vendor_payout_address,
            }

            # Call the specific XMR dispute broadcast function
            broadcast_func_name = 'create_and_broadcast_dispute_tx'
            if not hasattr(monero_service, broadcast_func_name):
                raise NotImplementedError(f"Dispute broadcast function '{broadcast_func_name}' not found in monero_service")

            broadcast_func = getattr(monero_service, broadcast_func_name)
            # Pass only relevant args (XMR specific)
            xmr_only_args = {k: v for k, v in broadcast_args.items() if 'btc' not in k.lower()}

            tx_hash = broadcast_func(**xmr_only_args)

            broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10
            if not broadcast_success:
                raise CryptoProcessingError(f"Monero dispute broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}').")

            logger.info(f"{log_prefix}: XMR Dispute transaction broadcast successful. TX: {tx_hash}")

        except (NotImplementedError, CryptoProcessingError, ValueError) as crypto_err:
            raise CryptoProcessingError(f"XMR Dispute broadcast error: {crypto_err}") from crypto_err
        except Exception as e:
            raise CryptoProcessingError(f"Unexpected XMR dispute broadcast error: {e}") from e

        # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
        try:
            # Re-fetch users
            buyer: Optional['UserModel'] = None
            vendor: Optional['UserModel'] = None
            market_user: Optional['UserModel'] = None
            logger.debug(f"{log_prefix}: Entering final update block post-XMR-dispute-broadcast (TX: {tx_hash}).")
            try:
                if buyer_id is None or vendor_id is None or market_user_id is None: raise ValueError("User IDs missing.")
                buyer = User.objects.get(pk=buyer_id)
                vendor = User.objects.get(pk=vendor_id)
                market_user = User.objects.get(pk=market_user_id)
            except User.DoesNotExist as user_err:
                logger.critical(f"{log_prefix}: CRITICAL: User not found during final update: {user_err}.", exc_info=True)
                raise LedgerError(f"Required user not found during ledger update.") from user_err
            except ValueError as val_err:
                logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
                raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
            except Exception as fetch_exc:
                logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
                raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc

            now = timezone.now()
            order_locked.status = OrderStatusChoices.DISPUTE_RESOLVED
            order_locked.release_tx_broadcast_hash = tx_hash
            # order_locked.dispute_resolved_at = now # Assume this is on Dispute model
            order_locked.updated_at = now

            update_fields = ['status', 'release_tx_broadcast_hash', 'updated_at']
            # Add optional fields if model has them
            if hasattr(order_locked, 'dispute_resolved_by'):
                order_locked.dispute_resolved_by = moderator
                update_fields.append('dispute_resolved_by')
            if hasattr(order_locked, 'dispute_resolution_notes'):
                order_locked.dispute_resolution_notes = resolution_notes[:2000] # Limit length
                update_fields.append('dispute_resolution_notes')
            if hasattr(order_locked, 'dispute_buyer_percent'):
                # Store the decimal percentage for accuracy if model field allows, else convert
                try:
                    order_locked.dispute_buyer_percent = buyer_percent_decimal
                except TypeError: # If model field is IntegerField
                    order_locked.dispute_buyer_percent = int(buyer_percent_decimal)
                update_fields.append('dispute_buyer_percent')


            # Update related Dispute object if it exists
            dispute_obj = getattr(order_locked, 'dispute', None)
            if dispute_obj and isinstance(dispute_obj, Dispute):
                dispute_update_fields = ['updated_at']
                if hasattr(dispute_obj, 'resolved_by'):
                    dispute_obj.resolved_by = moderator
                    dispute_update_fields.append('resolved_by')
                if hasattr(dispute_obj, 'resolution_notes'):
                    dispute_obj.resolution_notes = resolution_notes[:2000]
                    dispute_update_fields.append('resolution_notes')
                if hasattr(dispute_obj, 'resolved_at'):
                    dispute_obj.resolved_at = now
                    dispute_update_fields.append('resolved_at')
                if hasattr(dispute_obj, 'buyer_percentage'):
                    dispute_obj.buyer_percentage = buyer_percent_decimal # Store Decimal if possible
                    dispute_update_fields.append('buyer_percentage')

                dispute_obj.save(update_fields=list(set(dispute_update_fields)))
                logger.info(f"{log_prefix}: Updated related Dispute record {dispute_obj.id}.")

            logger.debug(f"{log_prefix}: Attempting to save final order state (Status: {order_locked.status})...")
            order_locked.save(update_fields=list(set(update_fields)))
            logger.info(f"{log_prefix}: Order state saved successfully. Proceeding to ledger updates.")

            # Update Ledger balances (STANDARD XMR units)
            notes_base = f"XMR Dispute resolution Order {order_locked.id} by {moderator.username}. TX: {tx_hash}."
            if buyer_share_xmr > Decimal('0.0'):
                ledger_service.credit_funds(
                    user=buyer, currency=CURRENCY_CODE, amount=buyer_share_xmr,
                    transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
                    related_order=order_locked, external_txid=tx_hash,
                    notes=f"{notes_base} Buyer Share ({buyer_percent_decimal:.2f}%)" # Use decimal %
                )
            if vendor_share_xmr > Decimal('0.0'):
                ledger_service.credit_funds(
                    user=vendor, currency=CURRENCY_CODE, amount=vendor_share_xmr,
                    transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_VENDOR,
                    related_order=order_locked, external_txid=tx_hash,
                    notes=f"{notes_base} Vendor Share ({release_to_vendor_percent_decimal:.2f}%)" # Use decimal %
                )
                # Add market fee handling here if needed based on dispute rules for XMR

            logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_xmr}, Vendor: {vendor_share_xmr} {CURRENCY_CODE}. TX: {tx_hash}")
            security_logger.info(f"XMR Dispute resolved Order {order_locked.id} by {moderator.username}. Ledger updated. TX: {tx_hash}")

            # Notifications (Best Effort)
            try:
                # Notify Buyer
                if buyer:
                    order_url = f"/orders/{order_locked.id}"
                    product_name = getattr(order_locked.product,'name','N/A')
                    message = (f"Dispute resolved for Order #{str(order_locked.id)[:8]} ({product_name}). "
                               f"Resolution: {resolution_notes[:100]}... Your share: {buyer_share_xmr} {CURRENCY_CODE}. TX: {tx_hash}")
                    create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
                # Notify Vendor
                if vendor:
                    order_url = f"/orders/{order_locked.id}"
                    product_name = getattr(order_locked.product,'name','N/A')
                    message = (f"Dispute resolved for Order #{str(order_locked.id)[:8]} ({product_name}). "
                               f"Resolution: {resolution_notes[:100]}... Your share: {vendor_share_xmr} {CURRENCY_CODE}. TX: {tx_hash}")
                    create_notification(user_id=vendor.id, level='info', message=message, link=order_url)
            except NotificationError as notify_e:
                logger.error(f"{log_prefix}: Failed to send dispute resolution notification: {notify_e}", exc_info=True)
            except Exception as notify_e:
                logger.error(f"{log_prefix}: Unexpected error sending dispute resolution notification: {notify_e}", exc_info=True)


            logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
            return True

        except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError) as final_db_err:
            logger.critical(f"{log_prefix}: CRITICAL FAILURE: XMR Dispute Broadcast OK (TX: {tx_hash}) but FINAL update FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
            raise PostBroadcastUpdateError(
                message=f"Post-broadcast update failed for XMR dispute resolution Order {order.id}",
                original_exception=final_db_err, tx_hash=tx_hash
            ) from final_db_err
        except Exception as final_e:
            logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: XMR Dispute Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
            raise PostBroadcastUpdateError(
                message=f"Unexpected post-broadcast error for XMR dispute resolution Order {order.id}",
                original_exception=final_e, tx_hash=tx_hash
            ) from final_e

    def get_unsigned_release_tx(self, order: 'Order', user: 'UserModel') -> Optional[Dict[str, str]]:
        """
        Retrieves the currently stored unsigned/partially signed XMR txset data
        from the order's release_metadata for offline signing by the specified user.

        Args:
            order: The Order instance (must be XMR).
            user: The User requesting the data (must be buyer or vendor).
        Returns:
            A dictionary containing {'unsigned_tx': txset_hex_string} if successful,
            otherwise None (though typically raises exceptions on failure).
        Raises:
            ObjectDoesNotExist: If order not found.
            PermissionError: If user is not buyer/vendor.
            ValueError: If currency mismatch or invalid input objects.
            EscrowError: For invalid state, missing/invalid metadata.
            RuntimeError: If critical models unavailable.
        """
        log_prefix = f"Order {order.id} (GetUnsignedTx for {user.username}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Request received for XMR unsigned_txset.")

        # --- Input and Dependency Validation ---
        if not all([Order, User]): raise RuntimeError("Critical application models unavailable.")
        if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
        if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
        if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")

        # --- Fetch Fresh Order Data ---
        try:
            order_fresh = Order.objects.select_related('buyer', 'vendor').get(pk=order.pk)
        except Order.DoesNotExist:
            raise ObjectDoesNotExist(f"Order {order.pk} not found.")
        except Exception as e:
            raise EscrowError(f"Database error fetching order {order.pk}.") from e

        # --- Permission Check ---
        is_buyer = (user.id == order_fresh.buyer_id)
        is_vendor = (user.id == order_fresh.vendor_id)
        if not (is_buyer or is_vendor):
            raise PermissionError("Only the buyer or vendor can request unsigned transaction data.")

        # --- State and Metadata Checks ---
        if not order_fresh.release_initiated:
            raise EscrowError("Release process has not been initiated for this order.")

        release_metadata: Dict[str, Any] = order_fresh.release_metadata or {}
        if not isinstance(release_metadata, dict):
            raise EscrowError("Release metadata is missing or invalid.")

        unsigned_txset_hex = release_metadata.get('data')
        release_type = release_metadata.get('type') # Should be 'xmr_unsigned_txset' or similar

        # Check if type matches expected XMR type
        expected_type = 'xmr_unsigned_txset' # Or whatever was set in _prepare_xmr_release
        if release_type != expected_type:
            logger.error(f"{log_prefix}: Release metadata type is '{release_type}', expected '{expected_type}'.")
            raise EscrowError("Release metadata type mismatch for XMR unsigned transaction request.")
        if not unsigned_txset_hex or not isinstance(unsigned_txset_hex, str):
            logger.error(f"{log_prefix}: Release metadata unsigned_txset ('data') is missing or invalid type ({type(unsigned_txset_hex)}).")
            raise EscrowError("Release metadata unsigned_txset ('data') is missing or invalid.")

        # Log if the requesting user has already signed
        already_signed = False
        if 'signatures' in release_metadata and isinstance(release_metadata['signatures'], dict):
            if str(user.id) in release_metadata['signatures']:
                already_signed = True
                logger.info(f"{log_prefix}: User {user.username} has already signed this XMR release according to metadata.")

        logger.info(f"{log_prefix}: Returning prepared XMR unsigned_txset data. Already Signed: {already_signed}")

        # Return only the txset data needed for signing
        return {'unsigned_tx': unsigned_txset_hex}

# --- Module-level Shim Functions for backward compatibility ---
# <<< START FIX v1.1.0 / Gemini Rev 16 >>>
_monero_escrow_service_instance = MoneroEscrowService()

def create_escrow(order: 'Order') -> None:
    """
    Module-level shim for MoneroEscrowService.create_escrow.
    Instantiates MoneroEscrowService and calls its create_escrow method.
    This maintains compatibility with dispatchers expecting a module-level function.
    """
    _monero_escrow_service_instance.create_escrow(order)

# Add other shims if/when common_escrow_utils calls them at module level
def check_confirm(payment_id: Any) -> bool:
    return _monero_escrow_service_instance.check_confirm(payment_id)

def mark_order_shipped(order: 'Order', vendor: 'UserModel', tracking_info: Optional[str] = None) -> None:
    _monero_escrow_service_instance.mark_order_shipped(order, vendor, tracking_info)

def sign_release(order: 'Order', user: 'UserModel', key_info: str) -> Tuple[bool, bool]:
    return _monero_escrow_service_instance.sign_release(order, user, key_info)

def broadcast_release(order_id: Any) -> bool:
    return _monero_escrow_service_instance.broadcast_release(order_id)

def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: Union[int, float] = 0
) -> bool:
    return _monero_escrow_service_instance.resolve_dispute(order, moderator, resolution_notes, release_to_buyer_percent)

def get_unsigned_release_tx(order: 'Order', user: 'UserModel') -> Optional[Dict[str, str]]:
    return _monero_escrow_service_instance.get_unsigned_release_tx(order, user)

# <<< END FIX v1.1.0 / Gemini Rev 16 >>>

# <<< END OF FILE: backend/store/services/monero_escrow_service.py >>>