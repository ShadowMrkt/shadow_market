# backend/store/services/simple_monero_escrow_service.py
"""
Service implementing the 'BASIC' (Simple/Centralized) escrow logic for Monero (XMR).

This service handles orders where the market controls the funds during escrow.
It interacts with the market_wallet_service for XMR operations and the
ledger_service for internal accounting.
"""

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING, Union, Final

# Django Imports
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist
from datetime import timedelta

# Local Imports
from . import market_wallet_service # Service handling market wallet crypto ops
from . import common_escrow_utils # Shared helpers and constants
# Import specific validators if needed, or rely on common_escrow_utils calling them
from ..validators import validate_monero_address
# Import monero_service for unit conversion helper potentially
from . import monero_service
from ..models import Order, CryptoPayment, User, GlobalSettings, Product, Dispute # Core models
# Use the inner class for status choices for clarity
from ..models import OrderStatus as OrderStatusChoices, EscrowType # Import EscrowType
from ..exceptions import EscrowError, CryptoProcessingError, PostBroadcastUpdateError # Custom exceptions
# Import ledger service and exceptions
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError
from ledger.exceptions import LedgerError

# --- Import Notification Service ---
try:
    from notifications.services import create_notification
    from notifications.exceptions import NotificationError
    NOTIFICATIONS_ENABLED = True
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.warning("Notifications app not found or 'create_notification'/'NotificationError' not available. Notifications will be skipped.")
    NOTIFICATIONS_ENABLED = False
    class NotificationError(Exception): pass
    def create_notification(*args, **kwargs): pass
# --- End Notification Service Import ---


if TYPE_CHECKING:
    from ..models import GlobalSettings as GlobalSettingsModel
    from django.contrib.auth.models import AbstractUser
    UserModel = AbstractUser

# --- Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Constants ---
CURRENCY_CODE: Final = 'XMR'


# === Simple Monero Escrow Functions ===

@transaction.atomic
def create_escrow(order: 'Order') -> None:
    """
    Prepares a BASIC escrow Monero order for payment:
    Generates a unique market-controlled XMR deposit address via market_wallet_service,
    creates the crypto payment record, sets deadlines, updates order status, and sends notification.

    Args:
        order: The Order instance (must be PENDING_PAYMENT, currency XMR, escrow BASIC).

    Raises:
        ValueError: If inputs are invalid (order, currency mismatch, escrow type mismatch).
        ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
        EscrowError: For general escrow process failures (e.g., wrong status, save errors).
        CryptoProcessingError: If market_wallet_service address generation fails.
        RuntimeError: If critical settings/models are unavailable.
    """
    log_prefix = f"Order {order.id} ({CURRENCY_CODE}-Simple)"
    logger.info(f"{log_prefix}: Initiating BASIC XMR escrow setup...")

    # --- Input Validation ---
    if not isinstance(order, Order) or not order.pk:
        raise ValueError("Invalid or unsaved Order object provided.")
    if order.selected_currency != CURRENCY_CODE:
        raise ValueError(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order.selected_currency}.")
    if order.escrow_type != EscrowType.BASIC:
        raise ValueError(f"{log_prefix}: Escrow type mismatch. Expected BASIC, got {order.escrow_type}.")
    if not order.total_price_native_selected or order.total_price_native_selected <= 0:
        raise ValueError(f"{log_prefix}: Order total price is invalid ({order.total_price_native_selected}).")

    # --- State Validation & Idempotency ---
    if order.status == OrderStatusChoices.PENDING_PAYMENT:
        if CryptoPayment.objects.filter(order=order, currency=CURRENCY_CODE).exists():
            logger.info(f"{log_prefix}: XMR CryptoPayment details already exist. Skipping creation (Idempotency).")
            return
        if order.simple_escrow_deposit_address:
             logger.warning(f"{log_prefix}: simple_escrow_deposit_address already set for PENDING order. Reusing? Check previous failure.")
             # Consider raising EscrowError("Simple escrow address already exists...") here if reuse is not desired
    else:
        logger.warning(f"{log_prefix}: Cannot create BASIC escrow. Invalid status: '{order.status}'.")
        raise EscrowError(f"Order must be in PENDING_PAYMENT state (Current: {order.status})")

    # --- Configuration Loading ---
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        confirmations_needed = getattr(gs, f'confirmations_needed_{CURRENCY_CODE.lower()}', 10) # Default 10 for XMR
        payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4))
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.critical(f"{log_prefix}: Error loading critical GlobalSettings: {e}.", exc_info=True)
        raise ObjectDoesNotExist(f"Failed to load required GlobalSettings: {e}") from e

    # --- Generate Market Deposit Address ---
    deposit_address: Optional[str] = None
    try:
        logger.debug(f"{log_prefix}: Generating unique XMR market deposit address via market_wallet_service...")
        deposit_address = market_wallet_service.generate_deposit_address(
            currency=CURRENCY_CODE,
            order_id=str(order.id)
        )
        validate_monero_address(deposit_address) # Validate address format
        if not deposit_address:
             raise CryptoProcessingError("market_wallet_service returned an empty XMR address.")

        logger.info(f"{log_prefix}: Generated simple escrow XMR deposit address: {deposit_address}")

    except (NotImplementedError, CryptoProcessingError, ValueError, DjangoValidationError) as crypto_err:
        logger.error(f"{log_prefix}: Failed to generate or validate market XMR deposit address: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Failed to generate/validate market XMR deposit address: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during market address generation: {e}")
        raise CryptoProcessingError("Unexpected error generating market deposit address.") from e

    # --- Create CryptoPayment Record ---
    try:
        payment_obj = CryptoPayment.objects.create(
            order=order,
            currency=CURRENCY_CODE,
            payment_address=deposit_address, # Store the generated market address here
            expected_amount_native=order.total_price_native_selected, # Atomic units (piconeros)
            confirmations_needed=confirmations_needed
            # payment_id_monero might not be needed/used for simple escrow market addresses
        )
        logger.info(f"{log_prefix}: Created XMR CryptoPayment {payment_obj.id} (Simple Escrow). Expected Piconeros: {payment_obj.expected_amount_native}")
    except IntegrityError as ie:
        logger.error(f"{log_prefix}: IntegrityError creating CryptoPayment: {ie}", exc_info=True)
        raise EscrowError("Failed to create unique payment record, possibly duplicate.") from ie
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error creating CryptoPayment: {e}")
        raise EscrowError(f"Failed to create payment record: {e}") from e

    # --- Final Order Updates & Notification ---
    try:
        order.payment_deadline = timezone.now() + timedelta(hours=payment_wait_hours)
        order.simple_escrow_deposit_address = deposit_address # Store on Order as well
        order.status = OrderStatusChoices.PENDING_PAYMENT # Ensure status
        order.updated_at = timezone.now()

        order.save(update_fields=['payment_deadline', 'simple_escrow_deposit_address', 'status', 'updated_at'])

        logger.info(f"{log_prefix}: Simple XMR escrow setup successful. Status -> {order.status}. Awaiting payment to {deposit_address}.")

        # --- Send notification to buyer ---
        if NOTIFICATIONS_ENABLED:
            try:
                buyer = order.buyer
                if not buyer or not buyer.pk:
                     logger.error(f"{log_prefix}: Cannot send notification, buyer not found on order.")
                else:
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order.product, 'name', 'N/A') if order.product else 'N/A'
                    message = (
                        f"Order #{str(order.id)[:8]} ({product_name}) is ready for payment. "
                        f"Please send exactly {order.total_price_native_selected} {CURRENCY_CODE} (piconeros) "
                        f"to the unique deposit address: {deposit_address} "
                        f"before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}."
                        # Monero might not need Payment ID for simple market addresses
                    )
                    create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
                    logger.info(f"{log_prefix}: Sent 'ready for payment' notification to Buyer {buyer.username}.")
            except NotificationError as notify_e:
                logger.error(f"{log_prefix}: Failed to create 'ready for payment' notification: {notify_e}", exc_info=True)
            except Exception as notify_e:
                logger.error(f"{log_prefix}: Unexpected error sending 'ready for payment' notification: {notify_e}", exc_info=True)
        else:
            logger.info(f"{log_prefix}: Notification sending is disabled or unavailable.")
        # --- End notification ---

    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save final order updates: {e}")
        raise EscrowError("Failed to save order updates during simple escrow creation.") from e


@transaction.atomic
def check_confirm(payment_id: Any) -> bool:
    """
    Checks market wallet for XMR payment confirmation to the simple escrow address,
    applies deposit fee (optional), compares amount, updates Ledger (crediting buyer,
    holding escrow), and Order status.

    Args:
        payment_id: The ID or instance of the CryptoPayment record (must be for BASIC XMR).

    Returns:
        bool: True if the payment was newly confirmed by this call, False otherwise.

    Raises:
        ObjectDoesNotExist: If the payment record or related users are not found.
        ValueError: If the payment record is not for BASIC XMR.
        EscrowError: For general process failures (DB errors, amount format).
        CryptoProcessingError: If market_wallet_service scanning fails.
        LedgerError: If ledger updates fail critically.
        InsufficientFundsError: If funds cannot be moved in ledger after deposit.
    """
    payment: Optional['CryptoPayment'] = None
    order: Optional['Order'] = None
    log_prefix = f"PaymentConfirm Check (ID: {payment_id}, {CURRENCY_CODE}-Simple)"
    buyer_id: Optional[int] = None
    market_user_id: Optional[int] = None # Needed if applying deposit fee
    newly_confirmed = False

    # --- Fetch and Lock Records ---
    try:
        # market_user_id = common_escrow_utils.get_market_user().pk # Uncomment if deposit fee applies

        if isinstance(payment_id, CryptoPayment):
            payment = payment_id
        else:
            payment = CryptoPayment.objects.select_for_update().select_related(
                'order__buyer', 'order__vendor', 'order__product'
            ).get(id=payment_id)

        if payment.currency != CURRENCY_CODE:
             raise ValueError(f"Payment record {payment.id} is for {payment.currency}, not {CURRENCY_CODE}.")

        order = payment.order
        if order.escrow_type != EscrowType.BASIC:
            raise ValueError(f"Payment record {payment.id} linked to Order {order.id} with wrong escrow type: {order.escrow_type}")

        buyer_id = order.buyer_id
        log_prefix = f"PaymentConfirm Check (Order: {order.id}, Payment: {payment.id}, {CURRENCY_CODE}-Simple)"
        logger.info(f"{log_prefix}: Starting check.")

    except CryptoPayment.DoesNotExist:
        logger.error(f"Payment record with ID {payment_id} not found.")
        raise
    except ObjectDoesNotExist as e:
        logger.critical(f"{log_prefix}: Required related object not found: {e}")
        raise
    except ValueError as ve:
        raise ve
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching payment/order details: {e}")
        raise EscrowError(f"Database error fetching details for payment {payment_id}.") from e

    # --- Status Checks ---
    if payment.is_confirmed:
        logger.info(f"{log_prefix}: Already confirmed.")
        return False

    if order.status != OrderStatusChoices.PENDING_PAYMENT:
        logger.warning(f"{log_prefix}: Order status is '{order.status}', not PENDING_PAYMENT. Skipping check.")
        common_escrow_utils._check_order_timeout(order)
        return False

    # --- Check Market Wallet for Deposit ---
    scan_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = None
    try:
        if not payment.payment_address:
            raise EscrowError("Payment record is missing the deposit address.")

        scan_result = market_wallet_service.scan_for_deposit(
            currency=CURRENCY_CODE,
            deposit_address=payment.payment_address,
            expected_amount_atomic=payment.expected_amount_native,
            confirmations_needed=payment.confirmations_needed
        )
    except (NotImplementedError, CryptoProcessingError) as crypto_err:
        logger.error(f"{log_prefix}: Error scanning market wallet: {crypto_err}", exc_info=True)
        raise
    except EscrowError as ee:
         logger.error(f"{log_prefix}: Escrow error during scan setup: {ee}")
         raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during market wallet scan: {e}")
        raise CryptoProcessingError(f"Failed to check market {CURRENCY_CODE} deposit: {e}") from e

    # --- Handle Unconfirmed Payment ---
    if not scan_result or not scan_result[0]:
        logger.debug(f"{log_prefix}: Payment not confirmed yet via market_wallet_service.")
        common_escrow_utils._check_order_timeout(order)
        return False

    # --- Handle Confirmed Payment ---
    is_crypto_confirmed, received_piconeros, confirmations, external_txid = scan_result
    external_txid = external_txid or payment.transaction_hash
    logger.info(f"{log_prefix}: XMR Crypto confirmed via market wallet. RcvdPiconeros={received_piconeros}, ExpPiconeros={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")

    # --- Amount Verification & Conversion ---
    try:
        if not isinstance(payment.expected_amount_native, Decimal):
            raise ValueError(f"Expected amount (pico) on Payment {payment.id} is not Decimal.")
        expected_piconeros = payment.expected_amount_native
        if not isinstance(received_piconeros, Decimal):
             received_piconeros = Decimal(str(received_piconeros))

        is_amount_sufficient = received_piconeros >= expected_piconeros

        # Convert piconeros to standard XMR (requires monero_service with converter)
        expected_xmr = common_escrow_utils._convert_atomic_to_standard(expected_piconeros, CURRENCY_CODE, monero_service)
        received_xmr = common_escrow_utils._convert_atomic_to_standard(received_piconeros, CURRENCY_CODE, monero_service)
        logger.debug(f"{log_prefix}: Converted amounts: ExpXMR={expected_xmr}, RcvdXMR={received_xmr} {CURRENCY_CODE}")

    except (ValueError, TypeError) as conv_err:
        logger.error(f"{log_prefix}: Invalid amount format/conversion error: {conv_err}", exc_info=True)
        raise EscrowError("Invalid payment amount format or conversion error.") from conv_err

    # --- Handle Insufficient Amount ---
    if not is_amount_sufficient:
        logger.warning(f"{log_prefix}: Amount insufficient. RcvdXMR: {received_xmr}, ExpXMR: {expected_xmr}.")
        try:
            payment.is_confirmed = True
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_piconeros
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
            )

            if updated_count > 0:
                logger.info(f"{log_prefix}: Order status set to CANCELLED_UNDERPAID.")
                security_logger.warning(f"Order {order.id} ({CURRENCY_CODE}-Simple) cancelled due to underpayment. Rcvd {received_xmr}, Exp {expected_xmr}. TX: {external_txid}")
                if NOTIFICATIONS_ENABLED:
                     try:
                          buyer = User.objects.get(pk=buyer_id)
                          order_url = f"/orders/{order.id}"
                          product_name = getattr(order.product, 'name', 'N/A')
                          message = (f"Payment for Order #{str(order.id)[:8]} ({product_name}) confirmed "
                                     f"but amount {received_xmr} {CURRENCY_CODE} was less than expected {expected_xmr} {CURRENCY_CODE}. "
                                     f"Order cancelled. Contact support. TXID: {external_txid or 'N/A'}")
                          create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                     except User.DoesNotExist: logger.error(f"{log_prefix}: Cannot send underpayment note: Buyer {buyer_id} not found.")
                     except NotificationError as notify_e: logger.error(f"{log_prefix}: Failed notification for underpayment: {notify_e}", exc_info=True)
            else:
                 current_status = Order.objects.get(pk=order.pk).status
                 logger.warning(f"{log_prefix}: Failed to mark order as underpaid. Status was already '{current_status}'.")
            return False
        except Exception as e:
            logger.exception(f"{log_prefix}: Error updating records for underpaid order: {e}")
            raise EscrowError("Failed to process simple escrow underpayment.") from e

    # --- Handle Sufficient Amount: Update Ledger and Order ---
    try:
        buyer: Optional['UserModel'] = User.objects.get(pk=buyer_id)
        # market_user: Optional['UserModel'] = User.objects.get(pk=market_user_id) # If using market user

        # --- Ledger Updates (STANDARD XMR units) ---
        # TODO: Implement Deposit Fee logic if applicable
        net_deposit_xmr = received_xmr
        expected_order_xmr = expected_xmr

        ledger_deposit_notes = f"Confirmed {CURRENCY_CODE}-Simple deposit Order {order.id}, TX: {external_txid}"

        # 1. Credit Buyer
        if net_deposit_xmr > Decimal('0.0'):
             ledger_service.credit_funds(
                  user=buyer, currency=CURRENCY_CODE, amount=net_deposit_xmr,
                  transaction_type=common_escrow_utils.LEDGER_TX_DEPOSIT,
                  external_txid=external_txid, related_order=order, notes=ledger_deposit_notes
             )

        # 3. Lock Funds
        logger.debug(f"{log_prefix}: Locking {expected_order_xmr} {CURRENCY_CODE} from Buyer {buyer.username}")
        lock_success = ledger_service.lock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_xmr,
            related_order=order, notes=f"Lock funds for Order {order.id} Simple XMR escrow"
        )
        if not lock_success:
            available_balance = ledger_service.get_available_balance(buyer, CURRENCY_CODE)
            raise InsufficientFundsError(f"Insufficient available balance ({available_balance}) to lock {expected_order_xmr} for escrow.")

        # 4. Debit Buyer (Move to logical escrow)
        logger.debug(f"{log_prefix}: Debiting {expected_order_xmr} {CURRENCY_CODE} from Buyer {buyer.username}")
        ledger_service.debit_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_xmr,
            transaction_type=common_escrow_utils.LEDGER_TX_ESCROW_FUND_DEBIT,
            related_order=order, external_txid=external_txid,
            notes=f"Debit funds for Order {order.id} Simple XMR escrow funding"
        )

        # 5. Unlock Funds
        unlock_success = ledger_service.unlock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_xmr,
            related_order=order, notes=f"Unlock funds after Order {order.id} Simple XMR escrow debit"
        )
        if not unlock_success:
            raise LedgerError("Ledger unlock failed after escrow debit, indicating potential data inconsistency.")

        # --- Update Order and Payment statuses ---
        now = timezone.now()
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        order.dispute_deadline = None # Set in mark_shipped
        order.auto_finalize_deadline = None # Set in mark_shipped
        order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

        payment.is_confirmed = True
        payment.confirmations_received = confirmations
        payment.received_amount_native = received_piconeros
        payment.transaction_hash = external_txid
        payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

        newly_confirmed = True
        logger.info(f"{log_prefix}: Ledger updated & Order status -> PAYMENT_CONFIRMED. TXID: {external_txid}")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}-Simple) payment confirmed & ledger updated. Buyer: {buyer.username}, Vendor: {getattr(order.vendor,'username','N/A')}. TX: {external_txid}")

        # Send notification to Vendor
        if NOTIFICATIONS_ENABLED:
            try:
                vendor = order.vendor
                if vendor and vendor.pk:
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order.product, 'name', 'N/A')
                    message = f"Payment confirmed for Order #{str(order.id)[:8]} ({product_name}). Please prepare for shipment."
                    create_notification(user_id=vendor.id, level='success', message=message, link=order_url)
                    logger.info(f"{log_prefix}: Sent payment confirmed notification to Vendor {vendor.username}.")
                else: logger.error(f"{log_prefix}: Cannot send payment confirmed note: Vendor not found.")
            except NotificationError as notify_e: logger.error(f"{log_prefix}: Failed payment confirmation notification: {notify_e}", exc_info=True)
            except Exception as notify_e: logger.error(f"{log_prefix}: Unexpected error sending payment confirmed notification: {notify_e}", exc_info=True)

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
        logger.critical(f"{log_prefix}: CRITICAL: Final update FAILED! Error: {e}. Rolled back.", exc_info=True)
        raise
    except Exception as e:
        logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during final update. Rolled back.")
        raise EscrowError(f"Unexpected error confirming payment: {e}") from e

    return newly_confirmed


@transaction.atomic
def broadcast_release(order_id: Any) -> bool:
    """
    Handles the release of funds for a completed BASIC XMR escrow order.
    Calls market_wallet_service to send funds from the market wallet to the vendor.
    Updates ledger and order status. **No multi-sig signing involved.**

    Args:
        order_id: The ID or instance of the Order (must be BASIC XMR, ready for release).

    Returns:
        bool: True if release withdrawal and internal updates were successful.

    Raises:
        ObjectDoesNotExist: If order not found.
        ValueError: If order currency/escrow type mismatch or invalid state.
        EscrowError: For internal processing errors.
        CryptoProcessingError: If market_wallet_service withdrawal fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        PostBroadcastUpdateError: If DB/Ledger update fails *after* successful withdrawal broadcast.
    """
    log_prefix = f"Order {order_id} (Release {CURRENCY_CODE}-Simple)"
    logger.info(f"{log_prefix}: Initiating BASIC release...")
    order: Optional['Order'] = None

    try:
        if isinstance(order_id, Order): order_pk = order_id.pk; order = order_id
        else: order_pk = order_id; order = Order.objects.select_for_update().select_related('buyer', 'vendor', 'product').get(pk=order_pk)
        log_prefix = f"Order {order.id} (Release {CURRENCY_CODE}-Simple)"

        # --- Validation ---
        if order.selected_currency != CURRENCY_CODE: raise ValueError("Currency mismatch.")
        if order.escrow_type != EscrowType.BASIC: raise ValueError("Escrow type mismatch.")
        if order.status == OrderStatusChoices.FINALIZED: logger.info(f"{log_prefix}: Already finalized."); return True
        if order.status not in [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]: raise EscrowError(f"Order status '{order.status}' not valid for simple release.")

        vendor = order.vendor; market_user = common_escrow_utils.get_market_user()
        if not vendor: raise ObjectDoesNotExist("Vendor not found on order.")

        # --- Calculate Payouts (Standard XMR units) ---
        total_escrowed_xmr = common_escrow_utils._convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, monero_service)
        fee_percent = common_escrow_utils._get_market_fee_percentage(CURRENCY_CODE)
        prec = common_escrow_utils._get_currency_precision(CURRENCY_CODE)
        quantizer = Decimal(f'1e-{prec}')
        market_fee_xmr = max(Decimal('0.0'), (total_escrowed_xmr * fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN))
        vendor_payout_xmr = max(Decimal('0.0'), (total_escrowed_xmr - market_fee_xmr).quantize(quantizer, rounding=ROUND_DOWN))

        tx_hash = None
        if vendor_payout_xmr > Decimal('0.0'):
            try:
                vendor_address = common_escrow_utils._get_withdrawal_address(vendor, CURRENCY_CODE)
            except ValueError as e: raise EscrowError(f"Vendor {vendor.username} missing {CURRENCY_CODE} withdrawal address.") from e
            logger.info(f"{log_prefix}: Requesting withdrawal of {vendor_payout_xmr} {CURRENCY_CODE} to {vendor_address} via market_wallet_service.")
            tx_hash = market_wallet_service.initiate_market_withdrawal(currency=CURRENCY_CODE, target_address=vendor_address, amount_standard=vendor_payout_xmr)
            if not tx_hash: raise CryptoProcessingError("Market withdrawal failed to return TX hash.")
            logger.info(f"{log_prefix}: Market withdrawal initiated. TXID: {tx_hash}")
        else:
            logger.warning(f"{log_prefix}: Vendor payout is zero. Skipping withdrawal.")

        # --- Final DB/Ledger Update ---
        now = timezone.now()
        order.status = OrderStatusChoices.FINALIZED; order.finalized_at = now
        order.release_tx_broadcast_hash = tx_hash; order.updated_at = now
        order.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'updated_at'])

        # --- Ledger Updates ---
        notes_base = f"Release Simple {CURRENCY_CODE} Order {order.id}" + (f", TX: {tx_hash}" if tx_hash else " (Zero Payout)")
        # TODO: Implement precise ledger debit (from where?) and credits
        # ledger_service.debit_funds(???)
        if vendor_payout_xmr > Decimal('0.0'): ledger_service.credit_funds(user=vendor, currency=CURRENCY_CODE, amount=vendor_payout_xmr, transaction_type=common_escrow_utils.LEDGER_TX_ESCROW_RELEASE_VENDOR, related_order=order, external_txid=tx_hash, notes=f"{notes_base} Vendor Payout")
        if market_fee_xmr > Decimal('0.0'): ledger_service.credit_funds(user=market_user, currency=CURRENCY_CODE, amount=market_fee_xmr, transaction_type=common_escrow_utils.LEDGER_TX_MARKET_FEE, related_order=order, notes=f"{notes_base} Market Fee")
        logger.info(f"{log_prefix}: Ledger updated. Vendor: {vendor_payout_xmr}, Fee: {market_fee_xmr}. Order finalized.")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}-Simple) finalized. Vendor: {vendor.username}. TX: {tx_hash or 'N/A'}")

        # --- Notifications ---
        if NOTIFICATIONS_ENABLED:
             try:
                  if vendor: create_notification(user_id=vendor.id, level='success', message=f"Funds released Order #{str(order.id)[:8]}. Payout: {vendor_payout_xmr} {CURRENCY_CODE}. TX: {tx_hash or 'N/A'}", link=f"/orders/{order.id}")
                  buyer = order.buyer
                  if buyer: create_notification(user_id=buyer.id, level='success', message=f"Order #{str(order.id)[:8]} ({getattr(order.product, 'name', '')}) finalized.", link=f"/orders/{order.id}")
             except NotificationError as notify_e: logger.error(f"{log_prefix}: Failed finalization notification: {notify_e}", exc_info=True)
             except Exception as notify_e: logger.error(f"{log_prefix}: Unexpected error sending finalization notification: {notify_e}", exc_info=True)
        return True

    except (ObjectDoesNotExist, ValueError, EscrowError) as e: logger.error(f"{log_prefix}: Pre-withdrawal validation failed: {e}", exc_info=True); raise
    except CryptoProcessingError as e: logger.error(f"{log_prefix}: Market withdrawal failed: {e}", exc_info=True); raise
    except (InsufficientFundsError, LedgerError, IntegrityError, DjangoValidationError) as final_db_err:
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: Simple release withdrawal potentially OK but FINAL update FAILED! Error: {final_db_err}. MANUAL INTERVENTION LIKELY NEEDED!", exc_info=True)
        raise PostBroadcastUpdateError(message=f"Post-withdrawal update failed Order {getattr(order,'id','N/A')}", original_exception=final_db_err, tx_hash=getattr(order, 'release_tx_broadcast_hash', None)) from final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR during final update: Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(message=f"Unexpected post-withdrawal error Order {getattr(order,'id','N/A')}", original_exception=final_e, tx_hash=getattr(order, 'release_tx_broadcast_hash', None)) from final_e


@transaction.atomic
def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: Union[int, float]
) -> bool:
    """
    Resolves a BASIC XMR escrow dispute by initiating withdrawals from the market wallet
    to the buyer and/or vendor based on the resolution percentage. Updates ledger/status.

    Args:
        order: The Order instance in dispute (must be BASIC XMR).
        moderator: The staff user resolving the dispute.
        resolution_notes: Explanation of the resolution.
        release_to_buyer_percent: Percentage (0-100) of escrowed funds for the buyer.

    Returns:
        bool: True if resolution withdrawals and internal updates were successful.

    Raises:
        ObjectDoesNotExist, PermissionError, ValueError, EscrowError, CryptoProcessingError,
        LedgerError, InsufficientFundsError, PostBroadcastUpdateError.
    """
    log_prefix = f"Order {order.id} (ResolveDispute {CURRENCY_CODE}-Simple)"
    logger.info(f"{log_prefix}: Attempting BASIC resolution. Buyer %: {release_to_buyer_percent}")

    # --- Validation ---
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order.")
    if not isinstance(moderator, User) or not moderator.pk: raise ValueError("Invalid Moderator.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError("Currency mismatch.")
    if order.escrow_type != EscrowType.BASIC: raise ValueError("Escrow type mismatch.")
    if order.status != OrderStatusChoices.DISPUTED: raise EscrowError(f"Order not DISPUTED.")
    if not getattr(moderator, 'is_staff', False): raise PermissionError("User cannot resolve.")
    try:
        buyer_percent_decimal = Decimal(str(release_to_buyer_percent))
        if not (Decimal('0.0') <= buyer_percent_decimal <= Decimal('100.0')): raise ValueError("Percent out of range.")
    except ValueError as e: raise ValueError(f"Invalid percentage: {release_to_buyer_percent}") from e
    if not resolution_notes or len(resolution_notes.strip()) < 5: raise ValueError("Notes too short.")

    buyer = order.buyer; vendor = order.vendor
    if not buyer or not vendor: raise ObjectDoesNotExist("Buyer or Vendor missing.")

    # --- Calculate Payout Shares (Standard XMR) ---
    total_escrowed_xmr = common_escrow_utils._convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, monero_service)
    prec = common_escrow_utils._get_currency_precision(CURRENCY_CODE); quantizer = Decimal(f'1e-{prec}')
    buyer_share_xmr = max(Decimal('0.0'), (total_escrowed_xmr * buyer_percent_decimal / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN))
    vendor_share_xmr = max(Decimal('0.0'), (total_escrowed_xmr - buyer_share_xmr).quantize(quantizer, rounding=ROUND_DOWN))
    release_to_vendor_percent_decimal = 100 - buyer_percent_decimal # For logging
    if (buyer_share_xmr + vendor_share_xmr).quantize(quantizer) > total_escrowed_xmr.quantize(quantizer): raise ValueError("Shares exceed total.")
    logger.info(f"{log_prefix}: Shares - Buyer: {buyer_share_xmr}, Vendor: {vendor_share_xmr} {CURRENCY_CODE}.")

    # --- Initiate Withdrawals ---
    buyer_tx_hash: Optional[str] = None; vendor_tx_hash: Optional[str] = None
    withdrawal_failed = False
    try:
        if buyer_share_xmr > Decimal('0.0'):
            try:
                buyer_address = common_escrow_utils._get_withdrawal_address(buyer, CURRENCY_CODE)
                logger.info(f"{log_prefix}: Withdrawing buyer share {buyer_share_xmr} to {buyer_address}")
                buyer_tx_hash = market_wallet_service.initiate_market_withdrawal(currency=CURRENCY_CODE, target_address=buyer_address, amount_standard=buyer_share_xmr)
                if not buyer_tx_hash: raise CryptoProcessingError("Buyer withdrawal failed.")
                logger.info(f"{log_prefix}: Buyer TX: {buyer_tx_hash}")
            except Exception as e: logger.error(f"{log_prefix}: Buyer withdrawal failed: {e}", exc_info=True); withdrawal_failed = True

        if not withdrawal_failed and vendor_share_xmr > Decimal('0.0'):
            try:
                vendor_address = common_escrow_utils._get_withdrawal_address(vendor, CURRENCY_CODE)
                logger.info(f"{log_prefix}: Withdrawing vendor share {vendor_share_xmr} to {vendor_address}")
                vendor_tx_hash = market_wallet_service.initiate_market_withdrawal(currency=CURRENCY_CODE, target_address=vendor_address, amount_standard=vendor_share_xmr)
                if not vendor_tx_hash: raise CryptoProcessingError("Vendor withdrawal failed.")
                logger.info(f"{log_prefix}: Vendor TX: {vendor_tx_hash}")
            except Exception as e: logger.error(f"{log_prefix}: Vendor withdrawal failed: {e}", exc_info=True); withdrawal_failed = True

        if withdrawal_failed: raise CryptoProcessingError("One or more withdrawals failed.")

    except (ValueError, CryptoProcessingError, EscrowError, NotImplementedError) as e: logger.error(f"{log_prefix}: Withdrawal phase failed: {e}", exc_info=True); raise

    # --- Final DB/Ledger Update ---
    combined_tx_hash = ",".join(filter(None, [buyer_tx_hash, vendor_tx_hash])) or None
    try:
        now = timezone.now()
        order.status = OrderStatusChoices.DISPUTE_RESOLVED
        order.release_tx_broadcast_hash = combined_tx_hash; order.updated_at = now
        update_fields = ['status', 'release_tx_broadcast_hash', 'updated_at']
        if hasattr(order, 'dispute_resolved_by'): order.dispute_resolved_by = moderator; update_fields.append('dispute_resolved_by')
        if hasattr(order, 'dispute_resolution_notes'): order.dispute_resolution_notes = resolution_notes[:2000]; update_fields.append('dispute_resolution_notes')
        if hasattr(order, 'dispute_buyer_percent'): order.dispute_buyer_percent = buyer_percent_decimal; update_fields.append('dispute_buyer_percent')
        order.save(update_fields=list(set(update_fields)))

        # Update Dispute object
        try:
             dispute = Dispute.objects.get(order=order)
             dispute.status = Dispute.StatusChoices.RESOLVED; dispute.resolved_by = moderator
             dispute.resolution_notes = resolution_notes[:2000]; dispute.resolved_at = now
             dispute.buyer_percentage = buyer_percent_decimal
             dispute.save(update_fields=['status', 'resolved_by', 'resolution_notes', 'resolved_at', 'buyer_percentage', 'updated_at'])
        except Dispute.DoesNotExist: logger.error(f"{log_prefix}: Related Dispute object not found.")

        # --- Ledger Updates ---
        notes_base = f"Resolve Simple {CURRENCY_CODE} Order {order.id} by {moderator.username}."
        # TODO: Implement precise ledger debit (from where?) and credits
        # ledger_service.debit_funds(???)
        if buyer_share_xmr > Decimal('0.0'): ledger_service.credit_funds(user=buyer, currency=CURRENCY_CODE, amount=buyer_share_xmr, transaction_type=common_escrow_utils.LEDGER_TX_DISPUTE_RESOLUTION_BUYER, related_order=order, external_txid=buyer_tx_hash, notes=f"{notes_base} Buyer Share ({buyer_percent_decimal:.2f}%)")
        if vendor_share_xmr > Decimal('0.0'): ledger_service.credit_funds(user=vendor, currency=CURRENCY_CODE, amount=vendor_share_xmr, transaction_type=common_escrow_utils.LEDGER_TX_DISPUTE_RESOLUTION_VENDOR, related_order=order, external_txid=vendor_tx_hash, notes=f"{notes_base} Vendor Share ({release_to_vendor_percent_decimal:.2f}%)")
        logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_xmr}, Vendor: {vendor_share_xmr}. Dispute resolved.")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}-Simple) dispute resolved by {moderator.username}. Buyer%: {buyer_percent_decimal:.2f}. TXs: {combined_tx_hash or 'N/A'}")

        # --- Notifications ---
        if NOTIFICATIONS_ENABLED:
            try:
                order_url = f"/orders/{order.id}"; common_msg = f"Dispute resolved Order #{str(order.id)[:8]}. Notes: {resolution_notes[:50]}..."
                if buyer: create_notification(user_id=buyer.id, level='info', message=f"{common_msg} You received {buyer_share_xmr} {CURRENCY_CODE}.", link=order_url)
                if vendor: create_notification(user_id=vendor.id, level='info', message=f"{common_msg} Vendor received {vendor_share_xmr} {CURRENCY_CODE}.", link=order_url)
            except NotificationError as notify_e: logger.error(f"{log_prefix}: Failed dispute resolved notification: {notify_e}", exc_info=True)
            except Exception as notify_e: logger.error(f"{log_prefix}: Unexpected error sending dispute resolved notification: {notify_e}", exc_info=True)
        return True

    except (InsufficientFundsError, LedgerError, IntegrityError, DjangoValidationError) as final_db_err:
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: Simple dispute withdrawal(s) potentially OK but FINAL update FAILED! Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(message=f"Post-withdrawal DB/Ledger update failed Order {order.id}", original_exception=final_db_err, tx_hash=combined_tx_hash) from final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR during final update: Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(message=f"Unexpected post-withdrawal error Order {order.id}", original_exception=final_e, tx_hash=combined_tx_hash) from final_e