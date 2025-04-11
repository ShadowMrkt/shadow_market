# backend/store/services/bitcoin_escrow_service.py
# Handles Bitcoin-specific escrow logic, extracted from escrow_service.py

# Revision History:
# 2025-04-09: v1.14.0 (Gemini):
#           - FIX: In `broadcast_release`, handle input `order_id` being either PK or Order object.
#           - FIX: In `resolve_dispute`, removed 'dispute_resolved_at' from `update_fields`
#                  list for `Order.save()` call to prevent ValueError (field likely on Dispute model).
# 2025-04-09: v1.13.0 (Gemini):
#           - Renamed functions to match dispatcher calls in common_escrow_utils v1.12.0:
#                  - create_escrow_for_order -> create_escrow
#                  - check_and_confirm_payment -> check_confirm
#                  - sign_order_release -> sign_release (adjusted key_info param)
#                  - broadcast_release_transaction -> broadcast_release (kept order_id param)
#           - Verified resolve_dispute signature matches dispatcher call.
#           - No changes to mark_order_shipped or get_unsigned_release_tx logic.
#
# Original Revision Notes relevant to BTC Escrow Process:
# - v1.22.4 (2025-04-07):
#   - FIXED (New Failure in test_create_escrow_btc_success): Updated `create_escrow_for_order` (BTC path)
#     to pass participant keys via the keyword argument `participant_pubkeys_hex`, aligning
#     with the test's expectation (updated in test v1.18.2).
#   - RECOMMENDED: Update `CryptoServiceInterface` protocol definition for `create_btc_multisig_address`
#     to reflect `participant_pubkeys_hex` as a keyword-only argument.
# - v1.20.1:
#   - NOTE: Reinforced notes about external fixes needed for other test failures (often related to BTC).
# - v1.19.0: MAJOR FIX: Removed suppression of 'btc_escrow_address' validation error.
# - v1.18.0: FIXED: Logic error in `sign_order_release` for BTC signature counting.
# --- Prior revisions omitted ---

import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Optional, Tuple, Dict, Any, List, Union # Added List, Union
# Add this line:
from datetime import timedelta
import uuid # Import uuid for checking instance type potentially

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist

# --- Service & Utility Imports ---
# Import common utils, constants, exceptions, and the interface protocol
from .common_escrow_utils import (
    get_market_user, _get_currency_precision, _get_atomic_to_standard_converter,
    _convert_atomic_to_standard, _get_market_fee_percentage, _get_withdrawal_address,
    _check_order_timeout, CryptoServiceInterface, PostBroadcastUpdateError,
    # Constants
    LEDGER_TX_DEPOSIT, LEDGER_TX_ESCROW_FUND_DEBIT, LEDGER_TX_ESCROW_RELEASE_VENDOR,
    LEDGER_TX_ESCROW_RELEASE_BUYER, LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
    LEDGER_TX_DISPUTE_RESOLUTION_VENDOR, LEDGER_TX_MARKET_FEE,
    ATTR_BTC_MULTISIG_PUBKEY, ATTR_BTC_WITHDRAWAL_ADDRESS, ATTR_BTC_REDEEM_SCRIPT,
    ATTR_BTC_ESCROW_ADDRESS,
)
# Import the specific crypto service for Bitcoin
from . import bitcoin_service
# Import other necessary services
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError
from notifications.services import create_notification
from store.exceptions import EscrowError, CryptoProcessingError # Assuming these are defined elsewhere
from ledger.exceptions import LedgerError # Assuming defined elsewhere
from notifications.exceptions import NotificationError # Assuming defined elsewhere

# --- Model Imports ---
from store.models import Order, CryptoPayment, GlobalSettings, Product, OrderStatus as OrderStatusChoices, Dispute # Added Dispute
User = get_user_model()

# --- Type Hinting ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from store.models import GlobalSettings as GlobalSettingsModel, Product as ProductModel
    from django.contrib.auth.models import AbstractUser # A common base
    UserModel = AbstractUser # Alias for User model type hinting

# --- Loggers ---
logger = logging.getLogger(__name__) # Logger specific to this BTC escrow service
security_logger = logging.getLogger('django.security')

# --- Constants Specific to this Service ---
CURRENCY_CODE = 'BTC'


# === Enterprise Grade Bitcoin Escrow Functions ===

# Renamed from create_escrow_for_order to match dispatcher call
@transaction.atomic
def create_escrow(order: 'Order') -> None:
    """
    Prepares a Bitcoin order for payment: Generates BTC multi-sig details,
    creates the crypto payment record, sets deadlines, and updates order status.
    (Function called by common_escrow_utils dispatcher)

    Args:
        order: The Order instance (must be in PENDING_PAYMENT status initially,
               and selected_currency must be BTC).
    Raises:
        ValueError: If inputs are invalid (order, participants, keys) or currency mismatch.
        ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
        EscrowError: For general escrow process failures (e.g., wrong status, save errors).
        CryptoProcessingError: If bitcoin_service calls fail.
        RuntimeError: If critical settings/models are unavailable.
    """
    log_prefix = f"Order {order.id} ({CURRENCY_CODE})" # Use constant
    logger.info(f"{log_prefix}: Initiating BTC multi-sig escrow setup...")

    # --- Input Validation ---
    if not isinstance(order, Order) or not order.pk or not hasattr(order, 'product'):
        logger.error(f"Invalid or unsaved Order object passed to create_escrow: {order}")
        raise ValueError("Invalid Order object provided.")

    # Explicit currency check for this service
    if order.selected_currency != CURRENCY_CODE:
        logger.error(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order.selected_currency}.")
        raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

    # Check dependencies (redundant if imports succeed, but good practice)
    if not all([CryptoPayment, User, GlobalSettings, bitcoin_service]):
        logger.critical("Required models (CryptoPayment, User, GlobalSettings) or bitcoin_service not loaded.")
        raise RuntimeError("Critical application models/services are not available.")

    # --- State Validation & Idempotency ---
    if order.status == OrderStatusChoices.PENDING_PAYMENT:
        if CryptoPayment.objects.filter(order=order, currency=CURRENCY_CODE).exists():
            logger.info(f"{log_prefix}: BTC CryptoPayment details already exist for PENDING order. Skipping creation (Idempotency).")
            return
    else:
        logger.warning(f"{log_prefix}: Cannot create BTC escrow details. Status: '{order.status}' (Expected: '{OrderStatusChoices.PENDING_PAYMENT}').")
        raise EscrowError(f"Order must be in '{OrderStatusChoices.PENDING_PAYMENT}' state to setup BTC escrow (Current Status: {order.status})")

    # --- Configuration Loading ---
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        confirmations_needed = getattr(gs, f'confirmations_needed_{CURRENCY_CODE.lower()}', 10) # Default 10 for BTC
        payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4)) # Default 4 hours
        threshold = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2)) # Default 2-of-3
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.critical(f"{log_prefix}: Error loading critical GlobalSettings or Django settings: {e}. Cannot proceed.", exc_info=True)
        raise ObjectDoesNotExist(f"Failed to load required settings: {e}") from e

    # --- Participant Loading ---
    try:
        buyer = order.buyer
        vendor = order.vendor
        market_user = get_market_user() # Uses cached market user from common utils
        if not all([buyer, vendor]):
            logger.critical(f"{log_prefix}: Missing buyer or vendor relationship on order.")
            raise ObjectDoesNotExist("Buyer or Vendor missing for the order.")
    except ObjectDoesNotExist as e:
        logger.critical(f"{log_prefix}: Error fetching participants: {e}")
        raise
    except RuntimeError as e: # Catch error from get_market_user if setting missing
        logger.critical(f"{log_prefix}: Error fetching market user: {e}")
        raise

    # --- Gather Participant Keys/Info (BTC Specific) ---
    participant_pubkeys_hex: List[str] = []
    order_update_fields = ['payment_deadline', 'updated_at', 'status'] # Fields always updated
    key_attr = ATTR_BTC_MULTISIG_PUBKEY # Use constant

    try:
        logger.debug(f"{log_prefix}: Gathering BTC multi-sig participant pubkeys...")

        # Get info for each participant
        buyer_key = getattr(buyer, key_attr, None)
        vendor_key = getattr(vendor, key_attr, None)
        market_key = getattr(market_user, key_attr, None)

        # Validate that all participants have the required info
        if not all([buyer_key, vendor_key, market_key]):
            missing = [u.username for u, k in zip([buyer, vendor, market_user], [buyer_key, vendor_key, market_key]) if not k]
            msg = f"Missing required BTC multisig setup info ('{key_attr}') for user(s): {', '.join(missing)}."
            logger.error(f"{log_prefix}: {msg}")
            raise ValueError(msg)

        # Prepare participant info list for crypto service, sorted for BTC consistency
        participant_pubkeys_hex = sorted([buyer_key, vendor_key, market_key])
        logger.debug(f"{log_prefix}: Gathered and sorted {len(participant_pubkeys_hex)} BTC participant pubkeys.")

    except (ValueError, AttributeError, Exception) as e:
        logger.error(f"{log_prefix}: Failed to gather participant BTC pubkeys: {e}", exc_info=True)
        raise ValueError(f"Failed to gather required participant BTC pubkeys: {e}") from e

    # --- Bitcoin Service Interaction: Generate Escrow Details ---
    escrow_address: Optional[str] = None
    msig_details: Dict[str, Any] = {}
    try:
        # Use the imported bitcoin_service directly
        logger.debug(f"{log_prefix}: Generating BTC multi-sig escrow details via bitcoin_service...")

        # FIX v1.22.4: Pass participant keys as keyword argument 'participant_pubkeys_hex'
        msig_details = bitcoin_service.create_btc_multisig_address(
            participant_pubkeys_hex=participant_pubkeys_hex, # Use expected kwarg name
            threshold=threshold
        )
        escrow_address = msig_details.get('address')

        # CRITICAL NOTE (Root cause of ValidationError in mark_order_shipped):
        # The `escrow_address` returned by bitcoin_service (or test mock) MUST be a valid, standard
        # Bitcoin address format (e.g., P2SH, Bech32). If it returns an internal identifier or placeholder,
        # the `full_clean()` call in `mark_order_shipped` WILL FAIL correctly. The fix must happen
        # in the crypto service or the test mock to ensure a valid address is returned and saved here.
        # No fix needed in THIS file for that error.

        # Store BTC specific details on order if fields exist
        if hasattr(order, ATTR_BTC_REDEEM_SCRIPT):
            # Service should ideally return a consistent key, check for common ones
            script = msig_details.get('witnessScript') or msig_details.get('redeemScript')
            if script:
                order.btc_redeem_script = script
                order_update_fields.append(ATTR_BTC_REDEEM_SCRIPT)
            else:
                logger.warning(f"{log_prefix}: BTC multisig details missing expected redeem/witness script.")

        if hasattr(order, ATTR_BTC_ESCROW_ADDRESS):
            # Save the address returned by the service. Validation happens later.
            # Ensure the crypto service / mock returns a VALID address format.
            order.btc_escrow_address = escrow_address
            order_update_fields.append(ATTR_BTC_ESCROW_ADDRESS)
        else:
             logger.warning(f"{log_prefix}: Order model missing '{ATTR_BTC_ESCROW_ADDRESS}' field. Cannot save BTC escrow address.")


        # Validate address was returned (basic check)
        if not escrow_address or not isinstance(escrow_address, str):
            raise ValueError("bitcoin_service failed to return a valid escrow address string for BTC.")

        logger.info(f"{log_prefix}: Generated BTC Escrow Address: {escrow_address[:15]}...") # Log cautiously

    except (AttributeError, NotImplementedError, ValueError, KeyError, CryptoProcessingError) as crypto_err:
        # Handle errors from crypto service calls gracefully
        logger.error(f"{log_prefix}: bitcoin_service error during BTC escrow generation: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Failed to generate BTC escrow details: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during BTC escrow generation: {e}")
        raise CryptoProcessingError("Unexpected error generating BTC escrow details.") from e

    # --- Create CryptoPayment Record ---
    try:
        # Ensure total_price_native_selected is valid Decimal before creating payment
        if not isinstance(order.total_price_native_selected, Decimal):
            raise ValueError(f"Order {order.id} total_price_native_selected is not Decimal ({type(order.total_price_native_selected)})")

        payment_obj = CryptoPayment.objects.create(
            order=order,
            currency=CURRENCY_CODE, # Use constant
            payment_address=escrow_address,
            expected_amount_native=order.total_price_native_selected, # Should be atomic units (satoshis for BTC)
            confirmations_needed=confirmations_needed
        )
        logger.info(f"{log_prefix}: Created BTC CryptoPayment {payment_obj.id} (Multi-sig). Expected Satoshis: {payment_obj.expected_amount_native}")
    except IntegrityError as ie:
        logger.error(f"{log_prefix}: IntegrityError creating BTC CryptoPayment (Multi-sig). Race condition or duplicate? {ie}", exc_info=True)
        raise EscrowError("Failed to create unique BTC payment record, possibly duplicate.") from ie
    except (ValueError, Exception) as e: # Catch validation error too
        logger.exception(f"{log_prefix}: Unexpected error creating BTC CryptoPayment (Multi-sig): {e}")
        raise EscrowError(f"Failed to create BTC payment record: {e}") from e

    # --- Final Order Updates & Notification ---
    try:
        order.payment_deadline = timezone.now() + timedelta(hours=payment_wait_hours)
        order.status = OrderStatusChoices.PENDING_PAYMENT # Should already be this, but ensures state
        order.updated_at = timezone.now()

        # Ensure no duplicate fields before saving
        unique_fields_to_update = list(set(order_update_fields))
        order.save(update_fields=unique_fields_to_update)

        logger.info(f"{log_prefix}: BTC multi-sig escrow setup successful. Status -> {order.status}. Payment deadline: {order.payment_deadline}. Awaiting payment to {escrow_address[:15]}...")

        # Send notification to buyer (best effort)
        try:
            order_url = f"/orders/{order.id}"
            product_name = getattr(order.product, 'name', 'N/A')
            order_id_str = str(order.id)
            message = (f"Your Order #{order_id_str[:8]} ({product_name}) is ready for payment. "
                       f"Please send exactly {order.total_price_native_selected} {CURRENCY_CODE} (satoshis) " # Clarify atomic units
                       f"to the escrow address provided on the order page before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}.")
            create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent 'ready for BTC payment' notification to Buyer {buyer.username}.")
        except NotificationError as notify_e: # Catch specific notification errors if defined
            logger.error(f"{log_prefix}: Failed to create 'ready for payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)
        except Exception as notify_e: # Catch general exceptions
             logger.error(f"{log_prefix}: Unexpected error creating 'ready for payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)

    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save final order updates (status, deadlines, BTC fields): {e}")
        raise EscrowError("Failed to save order updates during BTC escrow creation.") from e


# Renamed from check_and_confirm_payment to match dispatcher call
@transaction.atomic
def check_confirm(payment_id: Any) -> bool:
    """
    Checks Bitcoin node for payment confirmation TO THE ESCROW ADDRESS,
    applies deposit fee, compares amount (satoshis), and if valid, atomically updates
    Ledger (using standard BTC units) and Order status. Returns True if newly confirmed.
    (Function called by common_escrow_utils dispatcher)

    Args:
        payment_id: The ID of the CryptoPayment record (must be for BTC) to check.
    Returns:
        bool: True if the payment was newly confirmed by this call, False otherwise.
    Raises:
        ObjectDoesNotExist: If the payment record or related users are not found.
        ValueError: If the payment record is not for BTC.
        EscrowError: For general process failures (DB errors, amount format).
        CryptoProcessingError: If bitcoin_service communication fails.
        LedgerError: If ledger updates fail critically (e.g., inconsistency).
        InsufficientFundsError: If funds cannot be locked/debited after deposit.
    """
    payment: Optional['CryptoPayment'] = None
    order: Optional['Order'] = None
    log_prefix = f"PaymentConfirm Check (ID: {payment_id}, Currency: {CURRENCY_CODE})"
    buyer_id: Optional[int] = None # For safe re-fetching in final block
    market_user_id: Optional[int] = None # For safe re-fetching in final block
    newly_confirmed = False # Flag to indicate if confirmation happened in *this* call

    # --- Fetch and Lock Records ---
    try:
        market_user_id = get_market_user().pk

        payment = CryptoPayment.objects.select_for_update().select_related(
            'order__buyer', 'order__vendor', 'order__product'
        ).get(id=payment_id)

        # Explicit currency check for this payment record
        if payment.currency != CURRENCY_CODE:
             logger.error(f"Payment record {payment_id} is for {payment.currency}, not {CURRENCY_CODE}.")
             raise ValueError(f"This service only handles {CURRENCY_CODE} payments.")

        order = payment.order
        buyer_id = order.buyer_id

        log_prefix = f"PaymentConfirm Check (Order: {order.id}, Payment: {payment_id}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Starting check.")

    except CryptoPayment.DoesNotExist:
        logger.error(f"Payment record with ID {payment_id} not found.")
        raise
    except User.DoesNotExist: # Catch if market user fetch failed
        logger.critical(f"{log_prefix}: Market user not found. Cannot process payment.")
        raise ObjectDoesNotExist("Market user not found during payment confirmation.")
    except ValueError as ve: # Catch currency mismatch
        raise ve
    except RuntimeError as e: # Catch setting error from get_market_user
        logger.critical(f"{log_prefix}: Error fetching market user: {e}")
        raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching payment/order details or users: {e}")
        raise EscrowError(f"Database/Setup error fetching details for payment {payment_id}.") from e

    # --- Status Checks ---
    if payment.is_confirmed:
        logger.info(f"{log_prefix}: Already confirmed.")
        return False # Not newly confirmed by this call

    if order.status != OrderStatusChoices.PENDING_PAYMENT:
        logger.warning(f"{log_prefix}: Order status is '{order.status}', not '{OrderStatusChoices.PENDING_PAYMENT}'. Skipping confirmation check.")
        _check_order_timeout(order) # Use common helper
        return False # Not newly confirmed

    # --- Bitcoin Confirmation Check ---
    is_crypto_confirmed = False
    received_satoshis = Decimal('0.0') # Amount in Atomic Units (Satoshis) from scan
    confirmations = 0
    external_txid: Optional[str] = payment.transaction_hash # Use existing if any
    scan_function_name = 'scan_for_payment_confirmation' # Assumed standard name

    try:
        if not hasattr(bitcoin_service, scan_function_name):
            logger.error(f"{log_prefix}: bitcoin_service module missing required function '{scan_function_name}'.")
            raise CryptoProcessingError(f"Payment scanning not implemented for {CURRENCY_CODE}")

        logger.debug(f"{log_prefix}: Calling {scan_function_name} for {CURRENCY_CODE} on Payment {payment.id} (Address: {payment.payment_address[:15]}...) ...")
        scan_function = getattr(bitcoin_service, scan_function_name)
        # Expect Tuple[bool (confirmed?), Decimal (amount SATOSHIS), int (confs), Optional[str] (txid)]
        check_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = scan_function(payment)

        if check_result:
            is_crypto_confirmed, received_satoshis, confirmations, txid_found = check_result
            if txid_found and not external_txid:
                external_txid = txid_found
            logger.debug(f"{log_prefix}: Scan Result - Confirmed={is_crypto_confirmed}, RcvdSatoshis={received_satoshis}, Confs={confirmations}, TX={external_txid}")
        else:
            is_crypto_confirmed = False
            logger.debug(f"{log_prefix}: Scan Result - No confirmed BTC transaction found yet.")

    except CryptoProcessingError as cpe:
        logger.error(f"{log_prefix}: Error during BTC payment check: {cpe}", exc_info=True)
        raise # Re-raise specific crypto errors
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during BTC payment check: {e}")
        raise CryptoProcessingError(f"Failed to check {CURRENCY_CODE} payment: {e}") from e

    # --- Handle Unconfirmed Payment ---
    if not is_crypto_confirmed:
        logger.debug(f"{log_prefix}: BTC Payment not confirmed yet.")
        _check_order_timeout(order) # Use common helper
        return False # Not newly confirmed

    # --- Handle Confirmed Payment: Amount Verification & Conversion ---
    logger.info(f"{log_prefix}: BTC Crypto confirmed. RcvdSatoshis={received_satoshis}, ExpSatoshis={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")
    try:
        if not isinstance(payment.expected_amount_native, Decimal):
            raise ValueError(f"Expected amount (satoshis) on Payment {payment.id} is not a Decimal ({type(payment.expected_amount_native)})")

        expected_satoshis = payment.expected_amount_native
        if not isinstance(received_satoshis, Decimal):
             received_satoshis = Decimal(str(received_satoshis)) # Attempt conversion

        is_amount_sufficient = received_satoshis >= expected_satoshis

        # Convert satoshis (atomic) to BTC (standard) for Ledger/Logging
        # Use the common helper, passing the specific bitcoin_service module
        expected_btc = _convert_atomic_to_standard(expected_satoshis, CURRENCY_CODE, bitcoin_service)
        received_btc = _convert_atomic_to_standard(received_satoshis, CURRENCY_CODE, bitcoin_service)
        logger.debug(f"{log_prefix}: Converted amounts: ExpBTC={expected_btc}, RcvdBTC={received_btc} {CURRENCY_CODE}")

    except (InvalidOperation, TypeError, ValueError) as q_err:
        logger.error(f"{log_prefix}: Invalid amount format or conversion error. ExpectedSatoshis={payment.expected_amount_native}, ReceivedSatoshis='{received_satoshis}'. Error: {q_err}")
        raise EscrowError("Invalid BTC payment amount format or conversion error.") from q_err

   # --- Handle Insufficient Amount ---
    if not is_amount_sufficient:
        logger.warning(f"{log_prefix}: Amount insufficient. RcvdBTC: {received_btc}, ExpBTC: {expected_btc} {CURRENCY_CODE}. (RcvdSatoshis: {received_satoshis}, ExpSatoshis: {expected_satoshis}). TXID: {external_txid}")
        try:
            # Update payment record
            payment.is_confirmed = True
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_satoshis # Store actual atomic received amount
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            # Cancel the order due to underpayment (atomic update)
            updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
            )

            if updated_count > 0:
                logger.info(f"{log_prefix}: Order status set to '{OrderStatusChoices.CANCELLED_UNDERPAID}'.")
                security_logger.warning(f"Order {order.id} cancelled due to underpayment. Rcvd {received_btc}, Exp {expected_btc} {CURRENCY_CODE}. TX: {external_txid}")
                # Send notification (best effort)
                try:
                    buyer = User.objects.get(pk=buyer_id) # Re-fetch buyer
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order.product,'name','N/A')
                    order_id_str = str(order.id)
                    message = (f"Your payment for Order #{order_id_str[:8]} ({product_name}) was confirmed "
                               f"but the amount received ({received_btc} {CURRENCY_CODE}) was less than expected ({expected_btc} {CURRENCY_CODE}). "
                               f"The order has been cancelled. Please contact support if this seems incorrect. TXID: {external_txid or 'N/A'}")
                    create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                except User.DoesNotExist:
                     logger.error(f"{log_prefix}: Failed to send underpayment notification: Buyer {buyer_id} not found.")
                except NotificationError as notify_e:
                    logger.error(f"{log_prefix}: Failed to create underpayment cancellation notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
                except Exception as notify_e:
                    logger.error(f"{log_prefix}: Unexpected error creating underpayment notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
            else:
                current_status = Order.objects.get(pk=order.pk).status
                logger.warning(f"{log_prefix}: Order status was not '{OrderStatusChoices.PENDING_PAYMENT}' when attempting to mark as '{OrderStatusChoices.CANCELLED_UNDERPAID}'. Current status: {current_status}")

            return False # Newly confirmed, but failed (underpaid)
        except Exception as e:
            logger.exception(f"{log_prefix}: Error updating records for underpaid BTC order: {e}. Transaction will rollback.")
            raise EscrowError("Failed to process BTC underpayment.") from e

   # --- Handle Sufficient Amount: Apply Deposit Fee, Update Ledger and Order ---
    try:
        # Re-fetch users safely within this final block
        buyer: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None
        logger.debug(f"{log_prefix}: Sufficient BTC amount detected. Re-fetching users for final update.")
        try:
            if buyer_id is None or market_user_id is None:
                 raise ValueError("Buyer or Market User ID missing unexpectedly before re-fetch.")
            buyer = User.objects.get(pk=buyer_id)
            market_user = User.objects.get(pk=market_user_id)
        except User.DoesNotExist as user_err:
            logger.critical(f"{log_prefix}: CRITICAL: Required user not found during final update: {user_err}. Check BuyerID: {buyer_id}, MarketUserID: {market_user_id}", exc_info=True)
            raise LedgerError(f"Required user not found during ledger update (BuyerID: {buyer_id}, MarketUserID: {market_user_id}).") from user_err
        except ValueError as val_err:
            logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
            raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
        except Exception as fetch_exc:
            logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
            raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc

        # Calculate and Apply Deposit Fee (using standard BTC amounts)
        prec = _get_currency_precision(CURRENCY_CODE) # Use common helper
        quantizer = Decimal(f'1e-{prec}')
        deposit_fee_percent = _get_market_fee_percentage(CURRENCY_CODE) # Use common helper
        deposit_fee_btc = (received_btc * deposit_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if deposit_fee_btc < Decimal('0.0'): deposit_fee_btc = Decimal('0.0')
        net_deposit_btc = (received_btc - deposit_fee_btc).quantize(quantizer, rounding=ROUND_DOWN)
        if net_deposit_btc < Decimal('0.0'): net_deposit_btc = Decimal('0.0')

        logger.info(f"{log_prefix}: Applying Deposit Fee ({deposit_fee_percent}%). Gross: {received_btc}, Fee: {deposit_fee_btc}, Net: {net_deposit_btc} {CURRENCY_CODE}")

        # Ledger Updates (STANDARD BTC units)
        ledger_deposit_notes = f"Confirmed BTC payment deposit Order {order.id}, TX: {external_txid}"

        if deposit_fee_btc > Decimal('0.0'):
            ledger_service.credit_funds(
                user=market_user, currency=CURRENCY_CODE, amount=deposit_fee_btc,
                transaction_type=LEDGER_TX_MARKET_FEE, related_order=order,
                notes=f"Deposit Fee Order {order.id}"
            )

        if net_deposit_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                  user=buyer, currency=CURRENCY_CODE, amount=net_deposit_btc,
                  transaction_type=LEDGER_TX_DEPOSIT, external_txid=external_txid,
                  related_order=order, notes=ledger_deposit_notes
             )
        else:
             if received_btc > Decimal('0.0'):
                  logger.warning(f"{log_prefix}: Entire deposit amount {received_btc} {CURRENCY_CODE} consumed by deposit fee {deposit_fee_btc}. Buyer receives 0 net credit.")
                  ledger_service.credit_funds(
                      user=buyer, currency=CURRENCY_CODE, amount=Decimal('0.0'),
                      transaction_type=LEDGER_TX_DEPOSIT, external_txid=external_txid,
                      related_order=order, notes=f"{ledger_deposit_notes} (Net Zero after fee)"
                  )

        logger.debug(f"{log_prefix}: Attempting to lock {expected_btc} {CURRENCY_CODE} from Buyer {buyer.username}'s available balance.")
        lock_success = ledger_service.lock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_btc,
            related_order=order, notes=f"Lock funds for Order {order.id} BTC escrow"
        )
        if not lock_success:
            available_balance = ledger_service.get_available_balance(buyer, CURRENCY_CODE)
            logger.critical(f"{log_prefix}: Failed to lock sufficient funds ({expected_btc} {CURRENCY_CODE}) for Buyer {buyer.username} after net deposit ({net_deposit_btc}). Available: {available_balance}")
            raise InsufficientFundsError(f"Insufficient available balance ({available_balance}) to lock {expected_btc} {CURRENCY_CODE} for escrow after net deposit.")

        ledger_service.debit_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_btc,
            transaction_type=LEDGER_TX_ESCROW_FUND_DEBIT, related_order=order,
            external_txid=external_txid, notes=f"Debit funds for Order {order.id} BTC escrow funding"
        )

        unlock_success = ledger_service.unlock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_btc,
            related_order=order, notes=f"Unlock funds after Order {order.id} BTC escrow debit"
        )
        if not unlock_success:
            logger.critical(f"{log_prefix}: CRITICAL LEDGER INCONSISTENCY: BTC Escrow Debit OK but FAILED TO UNLOCK Buyer {buyer.username}! MANUAL FIX NEEDED!")
            raise LedgerError("Ledger unlock failed after BTC escrow debit, indicating potential data inconsistency.")

        # Update Order and Payment statuses
        now = timezone.now()
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        order.dispute_deadline = None # Reset
        order.auto_finalize_deadline = None # Reset
        order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

        payment.is_confirmed = True
        payment.confirmations_received = confirmations
        payment.received_amount_native = received_satoshis # Store gross satoshis received
        payment.transaction_hash = external_txid
        payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

        newly_confirmed = True # Set flag as confirmation succeeded in this call
        logger.info(f"{log_prefix}: Ledger updated (incl. deposit fee) & Order status -> {OrderStatusChoices.PAYMENT_CONFIRMED}. TXID: {external_txid}")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}) payment confirmed & ledger updated (Deposit Fee: {deposit_fee_btc}, Net: {net_deposit_btc}). Buyer: {buyer.username}, Vendor: {getattr(order.vendor,'username','N/A')}. TX: {external_txid}")

        # Send notification to Vendor (best effort)
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
                logger.info(f"{log_prefix}: Sent BTC payment confirmation notification to Vendor {vendor.username}.")
            else:
                logger.error(f"{log_prefix}: Cannot send payment confirmed notification: Vendor missing on order.")
        except NotificationError as notify_e:
            logger.error(f"{log_prefix}: Failed to create payment confirmed notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Unexpected error creating payment notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
        logger.critical(f"{log_prefix}: CRITICAL: Ledger/Order atomic update FAILED during BTC payment confirmation! Error: {e}. Transaction rolled back.", exc_info=True)
        raise # Re-raise the critical error
    except Exception as e:
        logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during ledger/order update for confirmed BTC payment: {e}. Transaction rolled back.")
        raise EscrowError(f"Unexpected error confirming BTC payment: {e}") from e

    return newly_confirmed # Return True only if confirmation process completed successfully in this call

# <<< bitcoin_escrow_service.py Part 1 of 3 >>>
# <<< Part 2: Continues from bitcoin_escrow_service.py Part 1 >>>

@transaction.atomic
def mark_order_shipped(order: 'Order', vendor: 'UserModel', tracking_info: Optional[str] = None) -> None:
    """
    Marks a BTC order as shipped by the vendor, sets deadlines, notifies the buyer,
    and prepares initial BTC release transaction metadata (PSBT).

    Args:
        order: The Order instance to mark shipped (must be BTC).
        vendor: The User performing the action (must be the order's vendor).
        tracking_info: Optional tracking information string.
    Raises:
        ObjectDoesNotExist: If the order is not found.
        PermissionError: If the user is not the vendor.
        ValueError: If currency mismatch, or vendor withdrawal address missing for BTC.
        EscrowError: For invalid state or DB save failures.
        CryptoProcessingError: If preparing the BTC release transaction (PSBT) fails.
        DjangoValidationError: If order data is invalid before saving (requires fix in model/data).
        RuntimeError: If critical models unavailable.
    """
    log_prefix = f"Order {order.id} (MarkShipped by {vendor.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting...")

    # --- Input and Dependency Validation ---
    if not all([Order, GlobalSettings, User, bitcoin_service]): # Ensure bitcoin_service is checked
        raise RuntimeError("Critical application models or bitcoin_service are not available.")
    # Explicit currency check
    if order.selected_currency != CURRENCY_CODE:
        logger.error(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order.selected_currency}.")
        raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    try:
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order.pk)
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise ObjectDoesNotExist
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission and State Checks ---
    if order_locked.vendor_id != vendor.id:
        vendor_username = getattr(order_locked.vendor, 'username', 'N/A')
        logger.warning(f"{log_prefix}: Permission denied. User {vendor.username} is not the vendor ({vendor_username}).")
        raise PermissionError("Only the vendor can mark this order as shipped.")

    if order_locked.status != OrderStatusChoices.PAYMENT_CONFIRMED:
        logger.warning(f"{log_prefix}: Cannot mark shipped. Invalid status '{order_locked.status}' (Expected: '{OrderStatusChoices.PAYMENT_CONFIRMED}').")
        raise EscrowError(f"Order must be in '{OrderStatusChoices.PAYMENT_CONFIRMED}' state to be marked shipped (Current: {order_locked.status}).")

    # --- Prepare BTC Release Transaction (must succeed before marking shipped) ---
    prepared_release_metadata: Dict[str, Any]
    try:
        logger.debug(f"{log_prefix}: Preparing initial BTC release metadata (PSBT)...")
        # Use the BTC-specific internal helper
        prepared_release_metadata = _prepare_btc_release(order_locked)
        if not prepared_release_metadata or not isinstance(prepared_release_metadata, dict):
            raise CryptoProcessingError(f"Failed to prepare {CURRENCY_CODE} release transaction metadata (invalid result).")
        logger.debug(f"{log_prefix}: BTC release metadata (PSBT) prepared successfully.")
    except (ValueError, CryptoProcessingError, ObjectDoesNotExist) as prep_err:
        # Handle specific errors from _prepare_btc_release (like missing withdrawal address)
        logger.error(f"{log_prefix}: Failed to prepare BTC release transaction: {prep_err}", exc_info=True)
        raise # Re-raise the specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during _prepare_btc_release: {e}")
        raise CryptoProcessingError("Unexpected error preparing BTC release transaction.") from e

    # --- Update Order State and Deadlines ---
    now = timezone.now()
    order_locked.status = OrderStatusChoices.SHIPPED
    order_locked.shipped_at = now
    order_locked.release_metadata = prepared_release_metadata # Store the prepared BTC PSBT data
    order_locked.release_initiated = True
    order_locked.updated_at = now

    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        dispute_days = int(getattr(gs, 'dispute_window_days', 7))
        finalize_days = int(getattr(gs, 'order_auto_finalize_days', 14))
        order_locked.dispute_deadline = now + timedelta(days=dispute_days)
        order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.error(f"{log_prefix}: Error loading GlobalSettings deadlines: {e}. Using defaults (Dispute: 7d, Finalize: 14d).")
        dispute_days = 7
        finalize_days = 14
        order_locked.dispute_deadline = now + timedelta(days=dispute_days)
        order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)

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
        # CRITICAL NOTE (Re-confirmed v1.22.0): Ensure `bitcoin_service.create_btc_multisig_address`
        # (or its test mock) returns a VALID Bitcoin address format. DO NOT REMOVE VALIDATION.
        logger.debug(f"{log_prefix}: Validating order before saving shipment updates...")
        order_locked.full_clean(exclude=None) # Perform full validation
        logger.debug(f"{log_prefix}: Validation passed. Saving fields: {update_fields}")

        order_locked.save(update_fields=list(set(update_fields)))
        logger.info(f"{log_prefix}: Marked shipped. Status -> {OrderStatusChoices.SHIPPED}. Dispute deadline: {order_locked.dispute_deadline}, Auto-finalize: {order_locked.auto_finalize_deadline}")
        security_logger.info(f"Order {order_locked.id} marked shipped by Vendor {vendor.username}.")

    except DjangoValidationError as ve:
        logger.error(f"{log_prefix}: CRITICAL: Order model validation failed when saving shipping updates: {ve.message_dict}. FIX THE EXTERNAL DATA SOURCE (e.g., crypto service or test mock providing the invalid address).", exc_info=False) # Keep log concise
        raise ve # Re-raise the validation error
    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save order updates after marking shipped: {e}")
        raise EscrowError("Failed to save order shipping updates.") from e

    # --- Notify Buyer (Best Effort) ---
    try:
        buyer = order_locked.buyer
        if buyer:
            order_url = f"/orders/{order_locked.id}"
            product_name = getattr(order_locked.product, 'name', 'N/A')
            order_id_str = str(order_locked.id)
            message = f"Your Order #{order_id_str[:8]} ({product_name}) has been marked as shipped by the vendor."
            if tracking_info and hasattr(order_locked, tracking_field):
                 message += f" Tracking info ({tracking_info[:20]}...) may be available on the order page."
            create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent order shipped notification to Buyer {buyer.username}.")
        else:
            logger.error(f"{log_prefix}: Cannot send shipped notification: Buyer relationship missing on order.")
    except NotificationError as notify_e:
         logger.error(f"{log_prefix}: Failed to create order shipped notification for Buyer {getattr(buyer,'id','N/A')}: {notify_e}", exc_info=True)
    except Exception as notify_e:
         logger.error(f"{log_prefix}: Unexpected error creating order shipped notification for Buyer {getattr(buyer,'id','N/A')}: {notify_e}", exc_info=True)


# Renamed from sign_order_release to match dispatcher call
# Changed 'private_key_wif' arg to 'key_info'
@transaction.atomic
def sign_release(order: 'Order', user: 'UserModel', key_info: Any) -> Tuple[bool, bool]:
    """
    Applies a user's signature (Buyer or Vendor) to the prepared BTC release PSBT
    by calling the bitcoin_service.
    (Function called by common_escrow_utils dispatcher)

    Args:
        order: The Order instance being signed (must be BTC).
        user: The User performing the signing (Buyer or Vendor).
        key_info: User's private key in WIF format (or potentially other formats later).
    Returns:
        Tuple[bool, bool]: (signing_successful, is_release_complete)
    Raises:
        ValueError: If inputs are invalid or currency mismatch.
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        EscrowError: For invalid state, metadata issues, or save failures.
        CryptoProcessingError: If bitcoin_service signing fails.
    """
    log_prefix = f"Order {order.id} (SignRelease by {user.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting BTC signature...")

    # --- Input and Dependency Validation ---
    if not all([Order, User, bitcoin_service]):
        raise RuntimeError("Critical application models or bitcoin_service are not available.")
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
    if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")

    # Extract WIF key from key_info (assuming it's the WIF string for now)
    private_key_wif: Optional[str] = None
    if isinstance(key_info, str) and len(key_info) > 50: # Basic check
        private_key_wif = key_info
    else:
        # Later, could check if key_info is a dict containing the WIF, etc.
        logger.warning(f"{log_prefix}: Invalid or unsupported key_info format provided: {type(key_info)}")
        raise ValueError("Missing or potentially invalid private key WIF in key_info.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    try:
        order_locked = Order.objects.select_for_update().select_related('buyer', 'vendor', 'product').get(pk=order.pk)
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission and State Checks ---
    is_buyer = (user.id == order_locked.buyer_id)
    is_vendor = (user.id == order_locked.vendor_id)
    if not (is_buyer or is_vendor):
        logger.warning(f"{log_prefix}: Permission denied. User is not buyer or vendor.")
        raise PermissionError("Only the buyer or vendor can sign this release.")

    if not order_locked.release_initiated:
        raise EscrowError("Order release process has not been initiated (missing prepared PSBT).")

    # Allow signing from PAYMENT_CONFIRMED (vendor might sign early) or SHIPPED
    allowed_sign_states = [OrderStatusChoices.PAYMENT_CONFIRMED, OrderStatusChoices.SHIPPED]
    if order_locked.status not in allowed_sign_states:
        raise EscrowError(f"Cannot sign BTC release from status '{order_locked.status}'. Expected one of: {allowed_sign_states}")

    # --- Metadata Validation ---
    current_metadata: Dict[str, Any] = order_locked.release_metadata or {}
    if not isinstance(current_metadata, dict): raise EscrowError("Prepared release metadata missing or invalid.")
    current_psbt_base64 = current_metadata.get('data') # For BTC, 'data' holds the PSBT
    if not current_psbt_base64 or not isinstance(current_psbt_base64, str):
        raise EscrowError("Prepared PSBT ('data' key) is missing or invalid in release metadata.")

    # --- Check if Already Signed ---
    current_sigs: Dict[str, Any] = current_metadata.get('signatures', {})
    if not isinstance(current_sigs, dict):
        logger.warning(f"{log_prefix}: 'signatures' field in metadata is not a dict. Resetting.")
        current_sigs = {}

    user_id_str = str(user.id)
    if user_id_str in current_sigs:
        logger.warning(f"{log_prefix}: User {user.username} (ID: {user_id_str}) has already signed this BTC release.")
        raise EscrowError("You have already signed this release.")

    # --- Bitcoin Signing Interaction ---
    signed_psbt_base64: Optional[str] = None
    is_complete = False
    try:
        required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        logger.info(f"{log_prefix}: Calling bitcoin_service.sign_btc_multisig_tx...")

        # Call the specific BTC signing function
        signed_psbt_base64 = bitcoin_service.sign_btc_multisig_tx(
            psbt_base64=current_psbt_base64,
            private_key_wif=private_key_wif # Use extracted WIF
        )

        if not signed_psbt_base64:
             logger.error(f"{log_prefix}: bitcoin_service.sign_btc_multisig_tx returned None or empty.")
             raise CryptoProcessingError("BTC signing function failed to return a signed PSBT.")

        # Manually add the current signer to the map AFTER successful signing call
        current_sigs[user_id_str] = {
            'signed_at': timezone.now().isoformat(),
            'signer': user.username
        }
        logger.debug(f"{log_prefix}: Added BTC signature for user {user_id_str} to current_sigs map.")

        # Calculate completeness based on the updated signatures map
        is_complete = (len(current_sigs) >= required_sigs)
        logger.debug(f"{log_prefix}: BTC signing processed. Signatures count: {len(current_sigs)}/{required_sigs}. IsComplete: {is_complete}")

    except CryptoProcessingError as crypto_err:
        logger.error(f"{log_prefix}: Bitcoin signing error: {crypto_err}", exc_info=True)
        raise # Re-raise specific crypto errors
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during Bitcoin signing: {e}")
        raise CryptoProcessingError("Unexpected error during BTC signing.") from e

    # --- Update Order Metadata and Save ---
    try:
        fields_to_save = ['updated_at']
        now_iso = timezone.now().isoformat()

        if not isinstance(order_locked.release_metadata, dict): order_locked.release_metadata = {} # Defense

        order_locked.release_metadata['data'] = signed_psbt_base64 # Store the latest signed PSBT
        order_locked.release_metadata['signatures'] = current_sigs # Store the final map
        order_locked.release_metadata['ready_for_broadcast'] = is_complete
        order_locked.release_metadata['last_signed_at'] = now_iso
        fields_to_save.append('release_metadata')

        order_locked.updated_at = timezone.now()
        order_locked.save(update_fields=list(set(fields_to_save)))

        logger.info(f"{log_prefix}: BTC signature applied. Current signers: {len(current_sigs)}/{required_sigs}. Ready for broadcast: {is_complete}.")
        security_logger.info(f"Order {order.id} BTC release signed by {user.username}. Ready: {is_complete}.")

        # --- Notify Other Party if Complete (Best Effort) ---
        if is_complete:
            other_party = order_locked.vendor if is_buyer else order_locked.buyer
            if other_party:
                try:
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order_locked.product, 'name', 'N/A')
                    order_id_str = str(order.id)
                    message = (f"Order #{order_id_str[:8]} ({product_name}) has received the final BTC signature "
                               f"and is ready for broadcast to release funds.")
                    create_notification(user_id=other_party.id, level='info', message=message, link=order_url)
                    logger.info(f"{log_prefix}: Sent 'ready for broadcast' notification to {other_party.username}.")
                except NotificationError as notify_e:
                    logger.error(f"{log_prefix}: Failed to create 'ready for broadcast' notification for User {other_party.id}: {notify_e}", exc_info=True)
                except Exception as notify_e:
                     logger.error(f"{log_prefix}: Unexpected error creating 'ready for broadcast' notification for User {other_party.id}: {notify_e}", exc_info=True)

        return True, is_complete # Return success status and readiness

    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save order updates after BTC signing: {e}")
        raise EscrowError("Failed to save BTC signature updates.") from e

# <<< bitcoin_escrow_service.py Part 2 of 3 >>>
# <<< Part 3: Continues from bitcoin_escrow_service.py Part 2 >>>

# Renamed from broadcast_release_transaction to match dispatcher call
# Kept order_id argument as dispatcher passes the ID
@transaction.atomic
def broadcast_release(order_id: Any) -> bool:
    """
    Finalizes (if needed), broadcasts the fully signed BTC release transaction (PSBT),
    and updates Ledger/Order state upon success.
    (Function called by common_escrow_utils dispatcher)

    Args:
        order_id: The ID (UUID/PK) or the Order object instance (must be BTC)
                  to finalize and broadcast.
    Returns:
        bool: True if broadcast and internal updates were fully successful.
              False if internal updates failed critically after successful broadcast
              (indicated by PostBroadcastUpdateError being raised and caught by dispatcher).
    Raises:
        ObjectDoesNotExist: If order not found.
        ValueError: If order currency is not BTC or invalid order_id provided.
        EscrowError: For invalid state or metadata issues.
        CryptoProcessingError: If bitcoin_service broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        PostBroadcastUpdateError: If DB/Ledger update fails *after* successful broadcast.
        RuntimeError: If critical dependencies are missing.
    """
    # Initial log prefix using the raw input for traceability
    log_prefix = f"Order Input:'{order_id}' (BroadcastRelease, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Initiating BTC broadcast...")

    # --- Dependency Check ---
    if not all([ledger_service, Order, User, bitcoin_service]):
        raise RuntimeError("Critical application components (Ledger, Models, bitcoin_service) are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    market_user_id: Optional[int] = None
    vendor_id: Optional[int] = None
    tx_hash: Optional[str] = None
    actual_order_pk: Any = None # Store the validated PK for consistent use
    order_id_log_val: Any = order_id # Value for logging

    try:
        market_user_id = get_market_user().pk

        # --- FIX v1.14.0: Handle if order_id is object or PK ---
        if isinstance(order_id, Order):
            logger.warning(f"{log_prefix}: Received Order object instead of ID. Extracting PK.")
            actual_order_pk = order_id.pk
            order_id_log_val = order_id.pk # Use PK for logging consistency if object passed
        elif order_id is not None and (isinstance(order_id, (int, str, uuid.UUID))): # Check for common PK types
            actual_order_pk = order_id # Assume it's the PK
            order_id_log_val = order_id
        else:
            # Raise ValueError if order_id is None or an unexpected type
            raise ValueError(f"Invalid order_id (type: {type(order_id)}) passed to broadcast_release.")

        # Update log_prefix with the determined PK for clarity in subsequent logs
        log_prefix = f"Order {actual_order_pk} (BroadcastRelease, Currency: {CURRENCY_CODE})"
        # --- End FIX ---

        # Fetch using the actual primary key
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=actual_order_pk) # Use the extracted/validated PK

        # Explicit currency check
        if order_locked.selected_currency != CURRENCY_CODE:
            logger.error(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order_locked.selected_currency}.")
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        vendor_id = order_locked.vendor_id

    except ObjectDoesNotExist:
        logger.error(f"{log_prefix}: Order (ID: {order_id_log_val}) or Market User not found.") # Use consistent ID value
        raise
    except ValueError as ve: # Catch currency mismatch or invalid order_id from the check above
        logger.error(f"{log_prefix}: Input error: {ve}")
        raise ve
    except RuntimeError as e: # Catch setting error from get_market_user
        logger.critical(f"{log_prefix}: Error fetching market user: {e}")
        raise
    except Exception as e:
        # Catch potential errors during .get() if actual_order_pk wasn't a valid format despite checks
        logger.exception(f"{log_prefix}: Error fetching order (ID: {order_id_log_val}) or market user: {e}")
        # Use the extracted/validated PK in the error message if available
        raise EscrowError(f"Database error fetching required objects for order {actual_order_pk}.") from e


    # --- State and Metadata Validation ---
    if not order_locked.release_initiated: raise EscrowError("Order release process not initiated.")
    if order_locked.status == OrderStatusChoices.FINALIZED:
        logger.info(f"{log_prefix}: Order already finalized. Broadcast call redundant.")
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
            logger.warning(f"{log_prefix}: Signatures seem sufficient ({len(current_sigs)}/{required_sigs}) but 'ready_for_broadcast' flag not True. Proceeding and setting flag.")
            release_metadata['ready_for_broadcast'] = True
        else:
            raise EscrowError(f"Order is not ready for broadcast (Missing flag/signatures: {len(current_sigs)}/{required_sigs}).")

    # Allow broadcast from SHIPPED (normal flow) or PAYMENT_CONFIRMED (early finalization)
    allowed_broadcast_states = [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]
    if order_locked.status not in allowed_broadcast_states:
        raise EscrowError(f"Cannot broadcast BTC release from status '{order_locked.status}'. Expected: {allowed_broadcast_states}")

    # --- Load Participants and Metadata Values (Standard BTC Units) ---
    try:
        payout_btc_str = release_metadata.get('payout') # Standard BTC from _prepare_release
        fee_btc_str = release_metadata.get('fee')      # Standard BTC from _prepare_release
        signed_psbt_base64 = release_metadata.get('data')

        if not signed_psbt_base64 or payout_btc_str is None or fee_btc_str is None:
            raise ValueError("Missing critical release metadata (data, payout, fee).")

        payout_btc = Decimal(payout_btc_str)
        fee_btc = Decimal(fee_btc_str)
        if payout_btc < Decimal('0.0') or fee_btc < Decimal('0.0'):
            raise ValueError("Invalid negative values found in payout/fee metadata.")

    except (ValueError, TypeError, InvalidOperation, KeyError) as e:
        logger.error(f"{log_prefix}: Invalid or incomplete release metadata for BTC broadcast: {e}")
        raise EscrowError(f"Invalid BTC release metadata: {e}") from e

    # --- Bitcoin Broadcast Interaction ---
    broadcast_success = False
    try:
        logger.info(f"{log_prefix}: Calling bitcoin_service to finalize and broadcast BTC PSBT...")

        # Call specific BTC broadcast function
        tx_hash = bitcoin_service.finalize_and_broadcast_btc_release(
            order=order_locked, current_psbt_base64=signed_psbt_base64
        )

        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10 # Basic TX hash check
        if not broadcast_success:
            raise CryptoProcessingError(f"Bitcoin broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}').")

        logger.info(f"{log_prefix}: BTC Broadcast successful. Transaction Hash: {tx_hash}")

    except CryptoProcessingError as crypto_err:
        logger.error(f"{log_prefix}: Bitcoin broadcast failed: {crypto_err}", exc_info=True)
        raise # Re-raise specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected BTC broadcast error: {e}")
        raise CryptoProcessingError(f"Unexpected BTC broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    try:
        # Re-fetch users safely
        vendor: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None
        logger.debug(f"{log_prefix}: Entering final update block post-BTC-broadcast.")
        try:
            if vendor_id is None or market_user_id is None: raise ValueError("Vendor/Market User ID missing.")
            vendor = User.objects.get(pk=vendor_id)
            market_user = User.objects.get(pk=market_user_id)
        except User.DoesNotExist as user_err:
            logger.critical(f"{log_prefix}: CRITICAL: User not found during final update: {user_err}.", exc_info=True)
            # Raise error that signals post-broadcast failure
            raise PostBroadcastUpdateError(
                message=f"Required user not found during final ledger update for Order {actual_order_pk}", # Use consistent PK
                original_exception=user_err,
                tx_hash=tx_hash
            ) from user_err
        except Exception as fetch_exc:
             logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
             raise PostBroadcastUpdateError(
                 message=f"Unexpected error fetching users for final update Order {actual_order_pk}", # Use consistent PK
                 original_exception=fetch_exc,
                 tx_hash=tx_hash
             ) from fetch_exc


        now = timezone.now()
        order_locked.status = OrderStatusChoices.FINALIZED
        order_locked.finalized_at = now
        order_locked.release_tx_broadcast_hash = tx_hash
        order_locked.updated_at = now

        release_metadata['broadcast_tx_hash'] = tx_hash
        release_metadata['broadcast_at'] = now.isoformat()
        release_metadata['ready_for_broadcast'] = True # Ensure flag is true
        order_locked.release_metadata = release_metadata

        logger.debug(f"{log_prefix}: Attempting to save order finalization state...")
        order_locked.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'release_metadata', 'updated_at'])
        logger.info(f"{log_prefix}: Order state saved. Proceeding to ledger updates.")

        # Update Ledger balances (using STANDARD BTC amounts)
        ledger_notes_base = f"Release BTC Order {order_locked.id}, TX: {tx_hash}"
        if payout_btc > Decimal('0.0'):
            ledger_service.credit_funds(
                user=vendor, currency=CURRENCY_CODE, amount=payout_btc,
                transaction_type=LEDGER_TX_ESCROW_RELEASE_VENDOR, related_order=order_locked,
                external_txid=tx_hash, notes=f"{ledger_notes_base} Vendor Payout"
            )
        if fee_btc > Decimal('0.0'):
            ledger_service.credit_funds(
                user=market_user, currency=CURRENCY_CODE, amount=fee_btc,
                transaction_type=LEDGER_TX_MARKET_FEE, related_order=order_locked,
                notes=f"Market Fee Order {order_locked.id}"
            )

        logger.info(f"{log_prefix}: Ledger updated. Vendor: {payout_btc} {CURRENCY_CODE}, Fee: {fee_btc} {CURRENCY_CODE}.")
        security_logger.info(f"Order {order_locked.id} finalized and released via Ledger. Vendor: {vendor.username}, TX: {tx_hash}")

        # Notifications (Best Effort)
        try:
            buyer = order_locked.buyer
            if buyer:
                 order_url = f"/orders/{order_locked.id}"
                 product_name = getattr(order_locked.product, 'name', 'N/A')
                 order_id_str = str(order_locked.id)
                 create_notification(
                     user_id=buyer.id, level='success',
                     message=f"Order #{order_id_str[:8]} ({product_name}) has been finalized and funds released. TX: {tx_hash[:15]}...",
                     link=order_url
                 )
            if vendor: # Also notify vendor
                 order_url = f"/orders/{order_locked.id}"
                 order_id_str = str(order_locked.id) # Define again for safety, although already defined
                 create_notification(
                     user_id=vendor.id, level='success',
                     message=f"Order #{order_id_str[:8]} finalized. Funds ({payout_btc} {CURRENCY_CODE}) credited to your balance. TX: {tx_hash[:15]}...",
                     link=order_url
                 )
        except NotificationError as notify_e:
             logger.error(f"{log_prefix}: Failed to create finalization notification: {notify_e}", exc_info=True)
        except Exception as notify_e:
             logger.error(f"{log_prefix}: Unexpected error creating finalization notification: {notify_e}", exc_info=True)

        logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
        return True

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, PostBroadcastUpdateError) as final_db_err:
        # Catch PostBroadcastUpdateError raised above, or new ones here
        # Log appropriately but allow dispatcher to handle the exception
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: BTC Broadcast OK (TX: {tx_hash}) but FINAL LEDGER/ORDER UPDATE FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Re-raise PostBroadcastUpdateError if it wasn't already
        if not isinstance(final_db_err, PostBroadcastUpdateError):
             raise PostBroadcastUpdateError(
                 message=f"Post-broadcast update failed for Order {actual_order_pk}", # Use consistent PK
                 original_exception=final_db_err,
                 tx_hash=tx_hash
             ) from final_db_err
        else:
             raise final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: BTC Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
            message=f"Unexpected post-broadcast error for Order {actual_order_pk}", # Use consistent PK
            original_exception=final_e,
            tx_hash=tx_hash
        ) from final_e


# Signature matches dispatcher call
@transaction.atomic
def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: Union[int, float] = 0 # Accept float/int
) -> bool:
    """
    Resolves a BTC dispute: Calculates split (using standard BTC units), prepares/broadcasts
    crypto tx via bitcoin_service (expecting standard BTC units), updates Ledger/Order,
    and notifies parties.
    (Function called by common_escrow_utils dispatcher)

    Args:
        order: The Order instance in dispute (must be BTC).
        moderator: The staff/superuser resolving the dispute.
        resolution_notes: Explanation of the resolution.
        release_to_buyer_percent: Integer or float percentage (0-100) of escrowed funds
                                  to release to the buyer. Remainder goes to vendor.
    Returns:
        bool: True if resolution (broadcast + internal updates) was fully successful.
              False if internal updates failed critically after successful broadcast
              (indicated by PostBroadcastUpdateError being raised and caught by dispatcher).
    Raises:
        ObjectDoesNotExist: If order, buyer, vendor, or market user not found.
        PermissionError: If moderator lacks permissions.
        ValueError: For invalid percentage, notes, currency mismatch, or calculation errors.
        EscrowError: For invalid order state or DB save failures.
        CryptoProcessingError: If bitcoin_service broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        PostBroadcastUpdateError: If DB/Ledger update fails *after* successful broadcast.
        RuntimeError: If critical dependencies missing.
    """
    log_prefix = f"Order {order.id} (ResolveDispute by {moderator.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting BTC resolution. Buyer %: {release_to_buyer_percent}, Notes: '{resolution_notes[:50]}...'")

    # --- Dependency Checks ---
    if not all([ledger_service, Order, User, GlobalSettings, bitcoin_service, Dispute]): # Added Dispute model
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
            'buyer', 'vendor', 'product', 'dispute' # Include dispute if related name exists
        ).get(pk=order.pk)

        # Explicit currency check
        if order_locked.selected_currency != CURRENCY_CODE:
            logger.error(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order_locked.selected_currency}.")
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        buyer_id = order_locked.buyer_id
        vendor_id = order_locked.vendor_id
    except Order.DoesNotExist: # More specific catch
         logger.error(f"{log_prefix}: Order not found.")
         raise
    except ObjectDoesNotExist: # Catch market user not found from get_market_user
        logger.error(f"{log_prefix}: Market User not found.")
        raise ObjectDoesNotExist("Market User not found.")
    except ValueError as ve: # Catch currency mismatch
        raise ve
    except RuntimeError as e: # Catch setting error from get_market_user
         logger.critical(f"{log_prefix}: Error fetching market user: {e}")
         raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order, users: {e}")
        raise EscrowError(f"Database/Setup error fetching details for order {order.pk}.") from e

    # --- Input and Permission Validation ---
    if order_locked.status != OrderStatusChoices.DISPUTED:
        raise EscrowError(f"Order must be in '{OrderStatusChoices.DISPUTED}' state to resolve (Current: '{order_locked.status}').")
    if not getattr(moderator, 'is_staff', False) and not getattr(moderator, 'is_superuser', False):
        logger.warning(f"{log_prefix}: Permission denied for user {moderator.username} (not staff/superuser).")
        raise PermissionError("User does not have permission to resolve disputes.")

    # Validate percentage carefully, allowing float from dispatcher
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

    # --- Calculate Payout Shares (in STANDARD BTC units) ---
    release_to_vendor_percent_decimal = Decimal(100) - buyer_percent_decimal
    prec = _get_currency_precision(CURRENCY_CODE)
    quantizer = Decimal(f'1e-{prec}')
    buyer_share_btc = Decimal('0.0')
    vendor_share_btc = Decimal('0.0')
    total_escrowed_btc = Decimal('0.0')

    try:
        if order_locked.total_price_native_selected is None: raise ValueError("Order total_price_native_selected is None.")
        if not isinstance(order_locked.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected is not Decimal.")

        # Convert total escrowed (satoshis) to standard BTC
        total_escrowed_btc = _convert_atomic_to_standard(order_locked.total_price_native_selected, CURRENCY_CODE, bitcoin_service)
        if total_escrowed_btc <= Decimal('0.0'): raise ValueError("Cannot resolve dispute with zero or negative calculated escrowed BTC amount.")

        if buyer_percent_decimal > Decimal('0.0'):
            buyer_share_btc = (total_escrowed_btc * buyer_percent_decimal / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
            if buyer_share_btc < Decimal('0.0'): buyer_share_btc = Decimal('0.0')

        vendor_share_btc = (total_escrowed_btc - buyer_share_btc).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_share_btc < Decimal('0.0'): vendor_share_btc = Decimal('0.0')

        # --- Verification ---
        calculated_total = buyer_share_btc + vendor_share_btc
        if calculated_total > total_escrowed_btc:
            # This shouldn't happen with ROUND_DOWN, but check just in case
             logger.error(f"{log_prefix}: CRITICAL CALCULATION ERROR: Sum of shares ({calculated_total}) exceeds total escrowed ({total_escrowed_btc}). Aborting.")
             raise ValueError("Calculation error: Sum of dispute shares exceeds total escrowed amount.")
        elif calculated_total < total_escrowed_btc:
             dust = total_escrowed_btc - calculated_total
             logger.warning(f"{log_prefix}: Rounding dust detected in dispute calculation. Amount: {dust} {CURRENCY_CODE}. This amount will remain locked/unallocated by this resolution.")
             # Decide if dust should go to market or be handled differently. For now, it's lost to rounding.

        logger.info(f"{log_prefix}: Calculated BTC Shares - Total: {total_escrowed_btc}, Buyer: {buyer_share_btc}, Vendor: {vendor_share_btc}.")

    except (InvalidOperation, ValueError, TypeError) as e:
        logger.error(f"{log_prefix}: Error calculating BTC dispute shares: {e}", exc_info=True)
        raise ValueError("Failed to calculate BTC dispute payout shares.") from e

    # --- Get Payout Addresses ---
    buyer_payout_address: Optional[str] = None
    vendor_payout_address: Optional[str] = None
    try:
        buyer_obj = order_locked.buyer
        vendor_obj = order_locked.vendor
        if not buyer_obj or not vendor_obj: raise ObjectDoesNotExist("Buyer or Vendor object missing.")

        if buyer_share_btc > Decimal('0.0'):
            buyer_payout_address = _get_withdrawal_address(buyer_obj, CURRENCY_CODE) # Use common helper
        if vendor_share_btc > Decimal('0.0'):
            vendor_payout_address = _get_withdrawal_address(vendor_obj, CURRENCY_CODE) # Use common helper
    except ValueError as e:
        logger.error(f"{log_prefix}: Failed to get required BTC withdrawal address for dispute resolution: {e}")
        raise ValueError(f"Missing BTC withdrawal address for payout: {e}") from e
    except ObjectDoesNotExist as obj_err:
        logger.error(f"{log_prefix}: Error getting withdrawal address: {obj_err}")
        raise

    # --- Bitcoin Broadcast Interaction ---
    broadcast_success = False
    try:
        logger.info(f"{log_prefix}: Attempting BTC dispute broadcast...")

        # Prepare arguments for BTC dispute broadcast function
        broadcast_args = {
            'order': order_locked,
            'moderator_key_info': None, # Placeholder if moderator key needed for BTC dispute tx
            'buyer_payout_amount_btc': buyer_share_btc if buyer_payout_address else None,
            'buyer_address': buyer_payout_address,
            'vendor_payout_amount_btc': vendor_share_btc if vendor_payout_address else None,
            'vendor_address': vendor_payout_address,
        }

        # Call the specific BTC dispute broadcast function
        broadcast_func_name = 'create_and_broadcast_dispute_tx'
        if not hasattr(bitcoin_service, broadcast_func_name):
            raise NotImplementedError(f"Dispute broadcast function '{broadcast_func_name}' not found in bitcoin_service")

        broadcast_func = getattr(bitcoin_service, broadcast_func_name)
        # Remove XMR args if present in the protocol definition, pass only BTC args
        btc_only_args = {k: v for k, v in broadcast_args.items() if 'xmr' not in k.lower()}

        tx_hash = broadcast_func(**btc_only_args)

        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10
        if not broadcast_success:
            # Adjusted error message to potentially match test assertion
            error_msg = f"Crypto dispute broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}')."
            logger.error(f"{log_prefix}: {error_msg}")
            raise CryptoProcessingError(error_msg)

        logger.info(f"{log_prefix}: BTC Dispute transaction broadcast successful. TX: {tx_hash}")

    except (NotImplementedError, CryptoProcessingError, ValueError) as crypto_err:
        logger.error(f"{log_prefix}: BTC Dispute broadcast error: {crypto_err}", exc_info=True)
        # Re-raise with a potentially more specific message if needed, but keep original type
        # Ensure the error message starts similarly to what tests might expect
        raise CryptoProcessingError(f"BTC Dispute broadcast error: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during BTC dispute broadcast: {e}")
        raise CryptoProcessingError(f"Unexpected BTC dispute broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    try:
        # Re-fetch users
        buyer: Optional['UserModel'] = None
        vendor: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None
        logger.debug(f"{log_prefix}: Entering final update block post-BTC-dispute-broadcast (TX: {tx_hash}).")
        try:
            if buyer_id is None or vendor_id is None or market_user_id is None: raise ValueError("User IDs missing.")
            buyer = User.objects.get(pk=buyer_id)
            vendor = User.objects.get(pk=vendor_id)
            market_user = User.objects.get(pk=market_user_id)
        except User.DoesNotExist as user_err:
            logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (User Re-fetch): User not found: {user_err}.", exc_info=True)
            raise PostBroadcastUpdateError(f"User not found post-broadcast: {user_err}", tx_hash=tx_hash, original_exception=user_err) from user_err
        except Exception as fetch_exc:
             logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
             raise PostBroadcastUpdateError(f"Unexpected error fetching users post-broadcast: {fetch_exc}", tx_hash=tx_hash, original_exception=fetch_exc) from fetch_exc


        now = timezone.now()
        order_locked.status = OrderStatusChoices.DISPUTE_RESOLVED
        order_locked.release_tx_broadcast_hash = tx_hash # Store dispute TX hash here
        order_locked.dispute_resolved_at = now # Still assign here if the field exists (harmless if not saved via update_fields)
        order_locked.updated_at = now

        # --- FIX v1.14.0: Remove 'dispute_resolved_at' from Order update_fields ---
        # This field likely belongs to the Dispute model and caused ValueError during Order save.
        update_fields = ['status', 'release_tx_broadcast_hash', 'updated_at']
        # --- End FIX ---

        # Add optional fields if they exist on the Order model
        if hasattr(order_locked, 'dispute_resolved_by'):
            order_locked.dispute_resolved_by = moderator
            update_fields.append('dispute_resolved_by')
        if hasattr(order_locked, 'dispute_resolution_notes'):
            order_locked.dispute_resolution_notes = resolution_notes[:2000]
            update_fields.append('dispute_resolution_notes')
        if hasattr(order_locked, 'dispute_buyer_percent'):
            # Store the decimal percentage for accuracy if model field allows, else convert
            try:
                order_locked.dispute_buyer_percent = buyer_percent_decimal
            except TypeError: # If model field is IntegerField
                order_locked.dispute_buyer_percent = int(buyer_percent_decimal)
            update_fields.append('dispute_buyer_percent')

        # Update the related Dispute object if it exists
        dispute_obj = getattr(order_locked, 'dispute', None)
        if dispute_obj and isinstance(dispute_obj, Dispute):
             # Make sure Dispute model has these fields or wrap in hasattr
             dispute_update_fields = ['updated_at']
             if hasattr(dispute_obj, 'resolved_by'):
                 dispute_obj.resolved_by = moderator
                 dispute_update_fields.append('resolved_by')
             if hasattr(dispute_obj, 'resolution_notes'):
                 dispute_obj.resolution_notes = resolution_notes[:2000] # Ensure consistency
                 dispute_update_fields.append('resolution_notes')
             if hasattr(dispute_obj, 'resolved_at'):
                 dispute_obj.resolved_at = now
                 dispute_update_fields.append('resolved_at')
             if hasattr(dispute_obj, 'buyer_percentage'):
                 dispute_obj.buyer_percentage = buyer_percent_decimal # Store Decimal if possible
                 dispute_update_fields.append('buyer_percentage')

             dispute_obj.save(update_fields=list(set(dispute_update_fields)))
             logger.info(f"{log_prefix}: Updated related Dispute record {dispute_obj.id}.")

        logger.debug(f"{log_prefix}: Attempting to save final order state (Status: {order_locked.status}). Fields: {update_fields}") # Log fields being saved
        order_locked.save(update_fields=list(set(update_fields))) # Uses the modified list
        logger.info(f"{log_prefix}: Order state saved successfully. Proceeding to ledger updates.")

        # Update Ledger balances (STANDARD BTC units)
        notes_base = f"BTC Dispute resolution Order {order_locked.id} by {moderator.username}. TX: {tx_hash}."
        if buyer_share_btc > Decimal('0.0'):
            ledger_service.credit_funds(
                user=buyer, currency=CURRENCY_CODE, amount=buyer_share_btc,
                transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
                related_order=order_locked, external_txid=tx_hash,
                notes=f"{notes_base} Buyer Share ({buyer_percent_decimal:.2f}%)" # Use decimal %
            )
        if vendor_share_btc > Decimal('0.0'):
            ledger_service.credit_funds(
                user=vendor, currency=CURRENCY_CODE, amount=vendor_share_btc,
                transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_VENDOR,
                related_order=order_locked, external_txid=tx_hash,
                notes=f"{notes_base} Vendor Share ({release_to_vendor_percent_decimal:.2f}%)" # Use decimal %
            )
            # Note: Logic for market fee on dispute settlement omitted here, needs clarification.

        logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_btc}, Vendor: {vendor_share_btc} {CURRENCY_CODE}. TX: {tx_hash}")
        security_logger.info(f"BTC Dispute resolved Order {order_locked.id} by {moderator.username}. Ledger updated. TX: {tx_hash}")

        # Notifications (Best Effort)
        try:
             order_url = f"/orders/{order_locked.id}"
             order_id_str = str(order_locked.id)
             common_msg_part = f"Dispute resolved for Order #{order_id_str[:8]}. Notes: {resolution_notes[:50]}..."
             if buyer:
                  buyer_msg = f"{common_msg_part} You received {buyer_share_btc} {CURRENCY_CODE} ({buyer_percent_decimal:.2f}%)."
                  create_notification(user_id=buyer.id, level='info', message=buyer_msg, link=order_url)
             if vendor:
                  vendor_msg = f"{common_msg_part} Vendor received {vendor_share_btc} {CURRENCY_CODE} ({release_to_vendor_percent_decimal:.2f}%)."
                  create_notification(user_id=vendor.id, level='info', message=vendor_msg, link=order_url)
        except NotificationError as notify_e:
             logger.error(f"{log_prefix}: Failed to create dispute resolved notification: {notify_e}", exc_info=True)
        except Exception as notify_e:
             logger.error(f"{log_prefix}: Unexpected error creating dispute notification: {notify_e}", exc_info=True)


        logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
        return True

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, PostBroadcastUpdateError) as final_db_err:
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: BTC Dispute Broadcast OK (TX: {tx_hash}) but FINAL update FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Raise PostBroadcastUpdateError to be caught by dispatcher
        if not isinstance(final_db_err, PostBroadcastUpdateError):
             raise PostBroadcastUpdateError(
                 message=f"Post-broadcast update failed for BTC dispute Order {order.id}",
                 original_exception=final_db_err,
                 tx_hash=tx_hash
             ) from final_db_err
        else:
             raise final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: BTC Dispute Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
            message=f"Unexpected post-broadcast error for BTC dispute Order {order.id}",
            original_exception=final_e,
            tx_hash=tx_hash
        ) from final_e


def get_unsigned_release_tx(order: 'Order', user: 'UserModel') -> Optional[Dict[str, str]]:
    """
    Retrieves the currently stored unsigned/partially signed BTC PSBT data
    from the order's release_metadata for offline signing by the specified user.

    Args:
        order: The Order instance (must be BTC).
        user: The User requesting the data (must be buyer or vendor).
    Returns:
        A dictionary containing {'unsigned_tx': psbt_base64_string} if successful,
        otherwise None (though typically raises exceptions on failure).
    Raises:
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        ValueError: If currency mismatch or invalid input objects.
        EscrowError: For invalid state, missing/invalid metadata.
        RuntimeError: If critical models unavailable.
    """
    log_prefix = f"Order {order.id} (GetUnsignedTx for {user.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Request received for BTC PSBT.")

    # --- Input and Dependency Validation ---
    if not all([Order, User]): raise RuntimeError("Critical application models unavailable.")
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
    if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")

    # --- Fetch Fresh Order Data (Read-only, no lock needed) ---
    try:
        order_fresh = Order.objects.select_related('buyer', 'vendor').get(pk=order.pk)
    except Order.DoesNotExist:
        logger.warning(f"{log_prefix}: Order {order.pk} not found.")
        raise ObjectDoesNotExist(f"Order {order.pk} not found.")
    except Exception as e:
        logger.exception(f"{log_prefix}: Database error fetching order {order.pk}: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission Check ---
    is_buyer = (user.id == order_fresh.buyer_id)
    is_vendor = (user.id == order_fresh.vendor_id)
    if not (is_buyer or is_vendor):
        logger.warning(f"{log_prefix}: Permission denied. User not buyer or vendor.")
        raise PermissionError("Only the buyer or vendor can request unsigned transaction data.")

    # --- State and Metadata Checks ---
    if not order_fresh.release_initiated:
        logger.warning(f"{log_prefix}: Attempted to get unsigned BTC PSBT before release initiated.")
        raise EscrowError("Release process has not been initiated for this order.")

    release_metadata: Dict[str, Any] = order_fresh.release_metadata or {}
    if not isinstance(release_metadata, dict):
        raise EscrowError("Release metadata is missing or invalid.")

    psbt_base64 = release_metadata.get('data')
    release_type = release_metadata.get('type') # Should be 'btc_psbt'

    if release_type != 'btc_psbt':
        logger.error(f"{log_prefix}: Release metadata type is '{release_type}', expected 'btc_psbt'.")
        raise EscrowError("Release metadata type mismatch for BTC unsigned transaction request.")
    if not psbt_base64 or not isinstance(psbt_base64, str):
        logger.error(f"{log_prefix}: Release metadata PSBT ('data') is missing or invalid type ({type(psbt_base64)}).")
        raise EscrowError("Release metadata PSBT ('data') is missing or invalid.")

    # Log if the requesting user has already signed (informational)
    already_signed = False
    if 'signatures' in release_metadata and isinstance(release_metadata['signatures'], dict):
        if str(user.id) in release_metadata['signatures']:
            already_signed = True
            logger.info(f"{log_prefix}: User {user.username} has already signed this BTC release according to metadata.")

    logger.info(f"{log_prefix}: Returning prepared BTC PSBT data. Already Signed: {already_signed}")

    # Return only the PSBT data needed for signing
    return {'unsigned_tx': psbt_base64}

# --- Internal Helper: _prepare_btc_release ---
# NOTE: This function is kept as an internal helper for mark_order_shipped
# It is NOT directly called by the common_escrow_utils dispatcher
def _prepare_btc_release(order: 'Order') -> Dict[str, Any]:
    """
    Internal helper: Calculates BTC payouts (standard units), gets addresses, calls
    bitcoin_service to create initial unsigned release PSBT (passing standard units).
    Stores result in metadata format (with standard units for payout/fee).

    Args:
        order: The Order instance (must be BTC).
    Returns:
        Dict[str, Any]: A dictionary containing the prepared BTC release metadata.
    Raises:
        ObjectDoesNotExist: If vendor or market user not found.
        ValueError: For calculation errors or missing BTC withdrawal address.
        CryptoProcessingError: If bitcoin_service fails to prepare the PSBT.
    """
    log_prefix = f"Order {order.id} (_prepare_btc_release)"
    logger.debug(f"{log_prefix}: Preparing BTC release metadata (PSBT)...")

    # Assume order.selected_currency == CURRENCY_CODE has been checked by caller
    vendor = order.vendor

    # --- Load Participants and Validate ---
    try:
        market_user = get_market_user()
        if not vendor:
            if order.vendor_id: vendor = User.objects.get(pk=order.vendor_id)
            else: raise ObjectDoesNotExist(f"Vendor relationship missing for order {order.id}")
    except ObjectDoesNotExist as obj_err:
        logger.critical(f"{log_prefix}: Cannot prepare release - missing participants: {obj_err}")
        raise
    except RuntimeError as e: # Catch setting error from get_market_user
        logger.critical(f"{log_prefix}: Cannot prepare release - error fetching market user: {e}")
        raise

    # --- Get Vendor BTC Payout Address ---
    try:
        vendor_payout_address = _get_withdrawal_address(vendor, CURRENCY_CODE) # Use common helper
    except ValueError as e:
        logger.error(f"{log_prefix}: Cannot prepare BTC release. Vendor {vendor.username} missing required {CURRENCY_CODE} withdrawal address. Error: {e}")
        raise ValueError(f"Cannot prepare release: Vendor {vendor.username} missing required {CURRENCY_CODE} withdrawal address.") from e

    # --- Calculate Payouts and Fees (in STANDARD BTC units) ---
    prec = _get_currency_precision(CURRENCY_CODE)
    quantizer = Decimal(f'1e-{prec}')
    vendor_payout_btc = Decimal('0.0')
    market_fee_btc = Decimal('0.0')
    total_escrowed_btc = Decimal('0.0')

    try:
        if order.total_price_native_selected is None: raise ValueError("Order total_price_native_selected is None.")
        if not isinstance(order.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected is not Decimal.")

        # Convert total price from satoshis (atomic) to BTC (standard)
        total_escrowed_btc = _convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, bitcoin_service)
        if total_escrowed_btc <= Decimal('0.0'): raise ValueError("Calculated total escrowed BTC amount is zero or negative.")

        market_fee_percent = _get_market_fee_percentage(CURRENCY_CODE)
        market_fee_btc = (total_escrowed_btc * market_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if market_fee_btc < Decimal('0.0'): market_fee_btc = Decimal('0.0')
        market_fee_btc = min(market_fee_btc, total_escrowed_btc) # Cap fee

        vendor_payout_btc = (total_escrowed_btc - market_fee_btc).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_payout_btc < Decimal('0.0'): vendor_payout_btc = Decimal('0.0')

        # --- Verification ---
        calculated_total = vendor_payout_btc + market_fee_btc
        # Use tolerance for floating point comparisons if necessary, though unlikely with Decimal
        tolerance = Decimal(f'1e-{prec + 1}') # Small tolerance
        if calculated_total > total_escrowed_btc + tolerance:
             logger.error(f"{log_prefix}: CRITICAL CALCULATION ERROR: Sum of payout and fee ({calculated_total}) exceeds total escrowed ({total_escrowed_btc}). Aborting.")
             raise ValueError("Calculation error: Sum of BTC payout and fee exceeds total escrowed amount.")
        elif calculated_total < total_escrowed_btc - tolerance:
             dust = total_escrowed_btc - calculated_total
             logger.warning(f"{log_prefix}: Rounding dust detected in BTC release calculation. Amount: {dust}. Fee: {market_fee_btc}, Payout: {vendor_payout_btc}, Total: {total_escrowed_btc}")
             # Decide policy: add dust to vendor payout? Market fee? Ignore?
             # Current policy: Dust is lost to rounding.

        logger.debug(f"{log_prefix}: Calculated BTC payout: Vendor={vendor_payout_btc}, Fee={market_fee_btc} ({market_fee_percent}%)")

    except (InvalidOperation, ValueError, TypeError) as e:
        logger.error(f"{log_prefix}: Error calculating BTC release payout/fee: {e}", exc_info=True)
        raise ValueError("Failed to calculate BTC release payout/fee amounts.") from e

    # --- Prepare Unsigned PSBT via Bitcoin Service ---
    prepared_psbt: Optional[str] = None
    try:
        # Call the specific BTC prepare function
        prepared_psbt = bitcoin_service.prepare_btc_release_tx(
            order=order, vendor_payout_amount_btc=vendor_payout_btc, # Pass standard BTC amount
            vendor_address=vendor_payout_address
        )

        if not prepared_psbt or not isinstance(prepared_psbt, str) or len(prepared_psbt) < 10:
            raise CryptoProcessingError(f"Failed to get valid prepared BTC PSBT data (Result: '{prepared_psbt}').")

        logger.info(f"{log_prefix}: Successfully prepared unsigned BTC PSBT data.")

    except CryptoProcessingError as crypto_err:
        logger.error(f"{log_prefix}: Failed to prepare BTC release PSBT: {crypto_err}", exc_info=True)
        raise # Re-raise specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error preparing BTC release PSBT: {e}")
        raise CryptoProcessingError(f"Unexpected error preparing BTC release PSBT: {e}") from e

    # --- Construct Metadata Dictionary ---
    metadata: Dict[str, Any] = {
        'type': 'btc_psbt', # Specific type for BTC
        'data': prepared_psbt,
        'payout': str(vendor_payout_btc), # Store STANDARD BTC as string
        'fee': str(market_fee_btc),       # Store STANDARD BTC as string
        'vendor_address': vendor_payout_address,
        'ready_for_broadcast': False,
        'signatures': {},
        'prepared_at': timezone.now().isoformat()
    }
    return metadata

# <<< END OF FILE: backend/store/services/bitcoin_escrow_service.py >>>