# backend/store/services/simple_bitcoin_escrow_service.py
"""
Service implementing the 'BASIC' (Simple/Centralized) escrow logic for Bitcoin (BTC).

This service handles orders where the market controls the funds during escrow.
It interacts with the market_wallet_service for BTC operations and the
ledger_service for internal accounting.
"""

import logging
from decimal import Decimal, ROUND_DOWN # Added ROUND_DOWN
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING, Union, Final # Added Final

# Django Imports
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist
from datetime import timedelta # Ensure timedelta is imported

# Local Imports
from . import market_wallet_service # Service handling market wallet crypto ops
from . import common_escrow_utils # Shared helpers and constants
# Import specific validators if needed, or rely on common_escrow_utils calling them
from ..validators import validate_bitcoin_address
from ..models import Order, CryptoPayment, User, GlobalSettings, Product, Dispute # Core models, Added Dispute
# Use the inner class for status choices for clarity
from ..models import OrderStatus as OrderStatusChoices, EscrowType # Import EscrowType
from ..exceptions import EscrowError, CryptoProcessingError, PostBroadcastUpdateError # Custom exceptions
# Import ledger service and exceptions
from ledger import services as ledger_service #
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError #
from ledger.exceptions import LedgerError #

# --- Import Notification Service ---
try:
    from notifications.services import create_notification #
    from notifications.exceptions import NotificationError #
    NOTIFICATIONS_ENABLED = True
except ImportError:
    # Handle cases where notifications app might be disabled or removed
    logger_init = logging.getLogger(__name__)
    logger_init.warning("Notifications app not found or 'create_notification'/'NotificationError' not available. Notifications will be skipped.")
    NOTIFICATIONS_ENABLED = False
    # Define dummy classes if needed to prevent NameErrors later
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
CURRENCY_CODE: Final = 'BTC'


# === Simple Bitcoin Escrow Functions ===

@transaction.atomic
def create_escrow(order: 'Order') -> None:
    """
    Prepares a BASIC escrow Bitcoin order for payment:
    Generates a unique market-controlled BTC deposit address via market_wallet_service,
    creates the crypto payment record, sets deadlines, updates order status, and sends notification.

    Args:
        order: The Order instance (must be PENDING_PAYMENT, currency BTC, escrow BASIC).

    Raises:
        ValueError: If inputs are invalid (order, currency mismatch, escrow type mismatch).
        ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
        EscrowError: For general escrow process failures (e.g., wrong status, save errors).
        CryptoProcessingError: If market_wallet_service address generation fails.
        RuntimeError: If critical settings/models are unavailable.
    """
    log_prefix = f"Order {order.id} ({CURRENCY_CODE}-Simple)"
    logger.info(f"{log_prefix}: Initiating BASIC BTC escrow setup...")

    # --- Input Validation ---
    if not isinstance(order, Order) or not order.pk:
        raise ValueError("Invalid or unsaved Order object provided.")
    if order.selected_currency != CURRENCY_CODE:
        raise ValueError(f"{log_prefix}: Currency mismatch. Expected {CURRENCY_CODE}, got {order.selected_currency}.")
    # Use EscrowType imported from models
    if order.escrow_type != EscrowType.BASIC: #
        raise ValueError(f"{log_prefix}: Escrow type mismatch. Expected BASIC, got {order.escrow_type}.")
    if not order.total_price_native_selected or order.total_price_native_selected <= 0:
        raise ValueError(f"{log_prefix}: Order total price is invalid ({order.total_price_native_selected}).")

    # --- State Validation & Idempotency ---
    if order.status == OrderStatusChoices.PENDING_PAYMENT:
        if CryptoPayment.objects.filter(order=order, currency=CURRENCY_CODE).exists():
            logger.info(f"{log_prefix}: BTC CryptoPayment details already exist. Skipping creation (Idempotency).")
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
        # Use getattr with default; ensure base settings or GlobalSettings model has these fields
        confirmations_needed = getattr(gs, f'confirmations_needed_{CURRENCY_CODE.lower()}', 3)
        payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4))
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.critical(f"{log_prefix}: Error loading critical GlobalSettings: {e}.", exc_info=True)
        raise ObjectDoesNotExist(f"Failed to load required GlobalSettings: {e}") from e

    # --- Generate Market Deposit Address ---
    deposit_address: Optional[str] = None
    try:
        logger.debug(f"{log_prefix}: Generating unique BTC market deposit address via market_wallet_service...")
        # This relies on market_wallet_service.generate_deposit_address being implemented
        deposit_address = market_wallet_service.generate_deposit_address(
            currency=CURRENCY_CODE,
            order_id=str(order.id) # Pass order ID for potential labeling/tracking
        )
        # Re-validate using the validator
        validate_bitcoin_address(deposit_address) # Use direct validator import or common_escrow_utils one
        if not deposit_address: # Basic check if validator doesn't raise exception but returns None/empty
             raise CryptoProcessingError("market_wallet_service returned an empty BTC address.")

        logger.info(f"{log_prefix}: Generated simple escrow BTC deposit address: {deposit_address}")

    except (NotImplementedError, CryptoProcessingError, ValueError, DjangoValidationError) as crypto_err: # Added DjangoValidationError
        logger.error(f"{log_prefix}: Failed to generate or validate market BTC deposit address: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Failed to generate/validate market BTC deposit address: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during market address generation: {e}")
        raise CryptoProcessingError("Unexpected error generating market deposit address.") from e

    # --- Create CryptoPayment Record ---
    try:
        payment_obj = CryptoPayment.objects.create(
            order=order,
            currency=CURRENCY_CODE,
            payment_address=deposit_address, # Store the generated market address here
            expected_amount_native=order.total_price_native_selected, # Atomic units (satoshis)
            confirmations_needed=confirmations_needed
        )
        logger.info(f"{log_prefix}: Created BTC CryptoPayment {payment_obj.id} (Simple Escrow). Expected Satoshis: {payment_obj.expected_amount_native}")
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

        logger.info(f"{log_prefix}: Simple BTC escrow setup successful. Status -> {order.status}. Awaiting payment to {deposit_address}.")

        # --- Send notification to buyer ---
        if NOTIFICATIONS_ENABLED:
            try:
                buyer = order.buyer
                if not buyer or not buyer.pk:
                     logger.error(f"{log_prefix}: Cannot send notification, buyer not found on order.")
                else:
                    order_url = f"/orders/{order.id}" # Example URL structure
                    product_name = getattr(order.product, 'name', 'N/A') if order.product else 'N/A'
                    message = (
                        f"Order #{str(order.id)[:8]} ({product_name}) is ready for payment. "
                        f"Please send exactly {order.total_price_native_selected} {CURRENCY_CODE} (satoshis) "
                        f"to the unique deposit address: {deposit_address} "
                        f"before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}."
                    )
                    create_notification(user_id=buyer.id, level='info', message=message, link=order_url) #
                    logger.info(f"{log_prefix}: Sent 'ready for payment' notification to Buyer {buyer.username}.")
            except NotificationError as notify_e: #
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
    Checks market wallet for BTC payment confirmation to the simple escrow address,
    applies deposit fee (optional), compares amount, updates Ledger (crediting buyer,
    holding escrow), and Order status.

    Args:
        payment_id: The ID or instance of the CryptoPayment record (must be for BASIC BTC).

    Returns:
        bool: True if the payment was newly confirmed by this call, False otherwise.

    Raises:
        ObjectDoesNotExist: If the payment record or related users are not found.
        ValueError: If the payment record is not for BASIC BTC.
        EscrowError: For general process failures (DB errors, amount format).
        CryptoProcessingError: If market_wallet_service scanning fails.
        LedgerError: If ledger updates fail critically (e.g., inconsistency).
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
            # Use select_for_update to lock rows during transaction
            payment = CryptoPayment.objects.select_for_update().select_related(
                'order__buyer', 'order__vendor', 'order__product' # Pre-fetch related objects
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
        raise # Re-raise ObjectDoesNotExist
    except ObjectDoesNotExist as e: # Catch if get_market_user fails
        logger.critical(f"{log_prefix}: Required related object not found: {e}")
        raise
    except ValueError as ve: # Catch currency or escrow type mismatch
        raise ve
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching payment/order details: {e}")
        raise EscrowError(f"Database error fetching details for payment {payment_id}.") from e

    # --- Status Checks ---
    if payment.is_confirmed:
        logger.info(f"{log_prefix}: Already confirmed.")
        return False # Not newly confirmed

    if order.status != OrderStatusChoices.PENDING_PAYMENT:
        logger.warning(f"{log_prefix}: Order status is '{order.status}', not PENDING_PAYMENT. Skipping confirmation check.")
        # Check for timeout even if not checking payment
        common_escrow_utils._check_order_timeout(order)
        return False

    # --- Check Market Wallet for Deposit ---
    scan_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = None
    try:
        if not payment.payment_address:
            raise EscrowError("Payment record is missing the deposit address.")

        # This relies on market_wallet_service.scan_for_deposit being implemented
        scan_result = market_wallet_service.scan_for_deposit(
            currency=CURRENCY_CODE,
            deposit_address=payment.payment_address,
            expected_amount_atomic=payment.expected_amount_native,
            confirmations_needed=payment.confirmations_needed
        )
    except (NotImplementedError, CryptoProcessingError) as crypto_err:
        logger.error(f"{log_prefix}: Error scanning market wallet: {crypto_err}", exc_info=True)
        raise # Re-raise critical crypto errors
    except EscrowError as ee:
         logger.error(f"{log_prefix}: Escrow error during scan setup: {ee}")
         raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during market wallet scan: {e}")
        raise CryptoProcessingError(f"Failed to check market {CURRENCY_CODE} deposit: {e}") from e

    # --- Handle Unconfirmed Payment ---
    if not scan_result or not scan_result[0]: # Check if result exists and is_confirmed is True
        logger.debug(f"{log_prefix}: Payment not confirmed yet via market_wallet_service.")
        common_escrow_utils._check_order_timeout(order)
        return False # Not newly confirmed

    # --- Handle Confirmed Payment ---
    is_crypto_confirmed, received_satoshis, confirmations, external_txid = scan_result
    external_txid = external_txid or payment.transaction_hash # Use found txid, fallback to existing if any
    logger.info(f"{log_prefix}: BTC Crypto confirmed via market wallet. RcvdSatoshis={received_satoshis}, ExpSatoshis={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")

    # --- Amount Verification & Conversion ---
    try:
        if not isinstance(payment.expected_amount_native, Decimal):
            raise ValueError(f"Expected amount (sats) on Payment {payment.id} is not Decimal.")
        expected_satoshis = payment.expected_amount_native
        if not isinstance(received_satoshis, Decimal):
             received_satoshis = Decimal(str(received_satoshis)) # Attempt conversion if needed

        is_amount_sufficient = received_satoshis >= expected_satoshis

        # Convert satoshis to standard BTC for Ledger/Logging (use helper)
        # Assuming bitcoin_service has the conversion utility, or it's in common_escrow_utils
        # Need to import bitcoin_service if using its converter directly
        from . import bitcoin_service
        expected_btc = common_escrow_utils._convert_atomic_to_standard(expected_satoshis, CURRENCY_CODE, bitcoin_service)
        received_btc = common_escrow_utils._convert_atomic_to_standard(received_satoshis, CURRENCY_CODE, bitcoin_service)
        logger.debug(f"{log_prefix}: Converted amounts: ExpBTC={expected_btc}, RcvdBTC={received_btc} {CURRENCY_CODE}")

    except (ValueError, TypeError) as conv_err:
        logger.error(f"{log_prefix}: Invalid amount format/conversion error: {conv_err}", exc_info=True)
        raise EscrowError("Invalid payment amount format or conversion error.") from conv_err

    # --- Handle Insufficient Amount ---
    if not is_amount_sufficient:
        logger.warning(f"{log_prefix}: Amount insufficient. RcvdBTC: {received_btc}, ExpBTC: {expected_btc}.")
        # Implement underpayment logic (similar to multi-sig version)
        try:
            payment.is_confirmed = True # Mark as seen, even if underpaid
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_satoshis
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            # Atomically update order status if it's still pending
            updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
            )

            if updated_count > 0:
                logger.info(f"{log_prefix}: Order status set to CANCELLED_UNDERPAID.")
                security_logger.warning(f"Order {order.id} ({CURRENCY_CODE}-Simple) cancelled due to underpayment. Rcvd {received_btc}, Exp {expected_btc}. TX: {external_txid}")
                # Send notification
                if NOTIFICATIONS_ENABLED:
                     try:
                          buyer = User.objects.get(pk=buyer_id)
                          order_url = f"/orders/{order.id}"
                          product_name = getattr(order.product, 'name', 'N/A')
                          message = (f"Payment for Order #{str(order.id)[:8]} ({product_name}) confirmed "
                                     f"but amount {received_btc} {CURRENCY_CODE} was less than expected {expected_btc} {CURRENCY_CODE}. "
                                     f"Order cancelled. Contact support. TXID: {external_txid or 'N/A'}")
                          create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                     except User.DoesNotExist:
                          logger.error(f"{log_prefix}: Cannot send underpayment note: Buyer {buyer_id} not found.")
                     except NotificationError as notify_e:
                          logger.error(f"{log_prefix}: Failed notification for underpayment: {notify_e}", exc_info=True)
            else:
                 # Race condition: Order status changed between initial check and update attempt
                 current_status = Order.objects.get(pk=order.pk).status
                 logger.warning(f"{log_prefix}: Failed to mark order as underpaid. Status was already '{current_status}'.")

            return False # Confirmed by scan, but failed due to underpayment

        except Exception as e:
            logger.exception(f"{log_prefix}: Error updating records for underpaid order: {e}")
            raise EscrowError("Failed to process simple escrow underpayment.") from e


    # --- Handle Sufficient Amount: Update Ledger and Order ---
    try:
        # Re-fetch users safely within final block if needed (e.g., for deposit fee)
        buyer: Optional['UserModel'] = User.objects.get(pk=buyer_id)
        # market_user: Optional['UserModel'] = User.objects.get(pk=market_user_id) # Uncomment if using market user

        # --- Ledger Updates (STANDARD BTC units) ---
        # Logic:
        # 1. Credit buyer's available balance with the net received amount (gross - optional deposit fee).
        # 2. (Optional) Credit market user with deposit fee.
        # 3. Lock the *expected* order amount from the buyer's available balance.
        # 4. Debit the locked amount from the buyer (funds moved to logical escrow).
        # 5. Unlock the funds (as they've been debited).

        # TODO: Implement Deposit Fee calculation if applicable for simple escrow deposits
        # deposit_fee_percent = common_escrow_utils._get_market_fee_percentage(CURRENCY_CODE)
        # deposit_fee_btc = ...
        # net_deposit_btc = received_btc - deposit_fee_btc
        net_deposit_btc = received_btc # Assuming no deposit fee for simplicity here
        expected_order_btc = expected_btc

        # Use constants for ledger transaction types from common_escrow_utils
        ledger_deposit_notes = f"Confirmed {CURRENCY_CODE}-Simple deposit Order {order.id}, TX: {external_txid}"

        # 1. Credit Buyer
        if net_deposit_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                  user=buyer, currency=CURRENCY_CODE, amount=net_deposit_btc,
                  transaction_type=common_escrow_utils.LEDGER_TX_DEPOSIT,
                  external_txid=external_txid, related_order=order, notes=ledger_deposit_notes
             )
        # Handle case where fee consumes entire deposit if fee logic added

        # 3. Lock Funds
        logger.debug(f"{log_prefix}: Locking {expected_order_btc} {CURRENCY_CODE} from Buyer {buyer.username}")
        lock_success = ledger_service.lock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_btc,
            related_order=order, notes=f"Lock funds for Order {order.id} Simple BTC escrow"
        )
        if not lock_success:
            available_balance = ledger_service.get_available_balance(buyer, CURRENCY_CODE)
            logger.critical(f"{log_prefix}: Failed to lock sufficient funds ({expected_order_btc}). Available: {available_balance}")
            raise InsufficientFundsError(f"Insufficient available balance ({available_balance}) to lock {expected_order_btc} for escrow.")

        # 4. Debit Buyer (Move to logical escrow)
        logger.debug(f"{log_prefix}: Debiting {expected_order_btc} {CURRENCY_CODE} from Buyer {buyer.username}")
        ledger_service.debit_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_btc,
            transaction_type=common_escrow_utils.LEDGER_TX_ESCROW_FUND_DEBIT,
            related_order=order, external_txid=external_txid,
            notes=f"Debit funds for Order {order.id} Simple BTC escrow funding"
        )

        # 5. Unlock Funds
        unlock_success = ledger_service.unlock_funds(
            user=buyer, currency=CURRENCY_CODE, amount=expected_order_btc,
            related_order=order, notes=f"Unlock funds after Order {order.id} Simple BTC escrow debit"
        )
        if not unlock_success:
            # This indicates a critical inconsistency!
            logger.critical(f"{log_prefix}: CRITICAL LEDGER INCONSISTENCY: Escrow Debit OK but FAILED TO UNLOCK! MANUAL FIX NEEDED!")
            # Potentially raise a specific critical error or alert admin
            raise LedgerError("Ledger unlock failed after escrow debit, indicating potential data inconsistency.")

        # --- Update Order and Payment statuses ---
        now = timezone.now()
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        # Calculate deadlines based on confirmation time
        try:
            gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
            dispute_days = int(getattr(gs, 'dispute_window_days', 7))
            finalize_days = int(getattr(gs, 'order_auto_finalize_days', 14))
            # Simple escrow: finalize/dispute relative to payment confirmation? Or shipping? Assume shipping for now.
            # These might be better set in mark_shipped for simple escrow. Nullify here.
            order.dispute_deadline = None # Set in mark_shipped
            order.auto_finalize_deadline = None # Set in mark_shipped
        except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
            logger.error(f"{log_prefix}: Error loading GlobalSettings deadlines post-confirmation: {e}. Deadlines will be null.", exc_info=True)
            order.dispute_deadline = None
            order.auto_finalize_deadline = None

        order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

        payment.is_confirmed = True
        payment.confirmations_received = confirmations
        payment.received_amount_native = received_satoshis # Store gross satoshis received
        payment.transaction_hash = external_txid
        payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

        newly_confirmed = True # Set flag
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
                else:
                    logger.error(f"{log_prefix}: Cannot send payment confirmed note: Vendor not found on order.")
            except NotificationError as notify_e:
                 logger.error(f"{log_prefix}: Failed notification for payment confirmation: {notify_e}", exc_info=True)
            except Exception as notify_e:
                 logger.error(f"{log_prefix}: Unexpected error sending payment confirmed notification: {notify_e}", exc_info=True)

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
        # Catch critical ledger/DB errors during the final update phase
        logger.critical(f"{log_prefix}: CRITICAL: Final update FAILED during payment confirmation! Error: {e}. Transaction rolled back.", exc_info=True)
        raise # Re-raise the critical error
    except Exception as e:
        logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during final update for confirmed payment: {e}. Transaction rolled back.")
        raise EscrowError(f"Unexpected error confirming payment: {e}") from e

    return newly_confirmed


# Note: mark_order_shipped is likely handled by common_escrow_utils dispatcher
# as the logic might be similar (update status, set deadlines) regardless of escrow type.
# If simple escrow requires different logic (e.g., different deadline triggers),
# a simple_mark_order_shipped function could be created here.
# Assuming common logic is sufficient for now.


@transaction.atomic
def broadcast_release(order_id: Any) -> bool:
    """
    Handles the release of funds for a completed BASIC BTC escrow order.
    Calls market_wallet_service to send funds from the market wallet to the vendor.
    Updates ledger and order status. **No multi-sig signing involved.**

    Args:
        order_id: The ID or instance of the Order (must be BASIC BTC, ready for release).

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
    order: Optional['Order'] = None # Define for use in exception blocks

    try:
        # Fetch and lock order
        if isinstance(order_id, Order):
            order_pk = order_id.pk
            order = order_id
        else:
            order_pk = order_id
            order = Order.objects.select_for_update().select_related(
                'buyer', 'vendor', 'product' # Include related objects
            ).get(pk=order_pk)

        log_prefix = f"Order {order.id} (Release {CURRENCY_CODE}-Simple)" # Update log prefix with actual ID

        # --- Validation ---
        if order.selected_currency != CURRENCY_CODE:
            raise ValueError(f"{log_prefix}: Currency mismatch.")
        if order.escrow_type != EscrowType.BASIC:
            raise ValueError(f"{log_prefix}: Escrow type mismatch.")
        if order.status == OrderStatusChoices.FINALIZED:
            logger.info(f"{log_prefix}: Order already finalized.")
            return True # Idempotent success
        # Check if order is in a state ready for release (e.g., SHIPPED or auto-finalize triggered)
        # Add logic here based on your rules, e.g.:
        # if order.status != OrderStatusChoices.SHIPPED and not should_auto_finalize(order):
        #     raise EscrowError(f"Order status '{order.status}' not ready for simple release.")
        if order.status not in [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]: # Example allowed states
             raise EscrowError(f"Order status '{order.status}' not valid for initiating simple release.")

        vendor = order.vendor
        if not vendor: raise ObjectDoesNotExist("Vendor not found on order.")
        market_user = common_escrow_utils.get_market_user() # For fee processing

        # --- Calculate Payouts (Standard BTC units) ---
        # Use common utils for precision/conversion if needed
        from . import bitcoin_service # For conversion helper
        total_escrowed_btc = common_escrow_utils._convert_atomic_to_standard(
            order.total_price_native_selected, CURRENCY_CODE, bitcoin_service
        )
        fee_percent = common_escrow_utils._get_market_fee_percentage(CURRENCY_CODE)
        prec = common_escrow_utils._get_currency_precision(CURRENCY_CODE)
        quantizer = Decimal(f'1e-{prec}')

        market_fee_btc = (total_escrowed_btc * fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        market_fee_btc = max(Decimal('0.0'), market_fee_btc)
        vendor_payout_btc = (total_escrowed_btc - market_fee_btc).quantize(quantizer, rounding=ROUND_DOWN)
        vendor_payout_btc = max(Decimal('0.0'), vendor_payout_btc)

        if vendor_payout_btc <= Decimal('0'):
             logger.warning(f"{log_prefix}: Calculated vendor payout is zero or negative. Check total price and fee %. Skipping withdrawal.")
             # Decide if this should finalize the order with zero payout or raise error. Finalizing might be okay.
             # Proceed to ledger updates (only fee?) and order finalization. Set tx_hash to None.
             tx_hash = None
        else:
            # --- Get Vendor Withdrawal Address ---
            try:
                vendor_address = common_escrow_utils._get_withdrawal_address(vendor, CURRENCY_CODE)
            except ValueError as e:
                logger.error(f"{log_prefix}: Cannot release funds, vendor missing withdrawal address: {e}")
                raise EscrowError(f"Vendor {vendor.username} missing {CURRENCY_CODE} withdrawal address.") from e

            # --- Initiate Withdrawal from Market Wallet ---
            logger.info(f"{log_prefix}: Requesting withdrawal of {vendor_payout_btc} {CURRENCY_CODE} to {vendor_address} via market_wallet_service.")
            # This relies on market_wallet_service.initiate_market_withdrawal being implemented
            tx_hash = market_wallet_service.initiate_market_withdrawal(
                currency=CURRENCY_CODE,
                target_address=vendor_address,
                amount_standard=vendor_payout_btc
            )
            if not tx_hash: # Should raise exception on failure, but check defensively
                 raise CryptoProcessingError("Market withdrawal initiation failed to return a transaction hash.")
            logger.info(f"{log_prefix}: Market withdrawal initiated successfully. TXID: {tx_hash}")

        # --- Final DB/Ledger Update (Post-Withdrawal or if payout was zero) ---
        now = timezone.now()
        order.status = OrderStatusChoices.FINALIZED
        order.finalized_at = now
        order.release_tx_broadcast_hash = tx_hash # Store the withdrawal TX hash
        order.updated_at = now
        # Optionally clear sensitive metadata if simple escrow used it?
        # order.release_metadata = None

        order.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'updated_at'])

        # Update Ledger (using STANDARD BTC amounts)
        notes_base = f"Release Simple {CURRENCY_CODE} Order {order.id}" + (f", TX: {tx_hash}" if tx_hash else " (Zero Payout)")

        # TODO: Define the ledger flow precisely. Example:
        # 1. Debit the market's logical escrow holding account for the total escrowed amount.
        # 2. Credit the vendor's account with the vendor_payout_btc.
        # 3. Credit the market's fee account with the market_fee_btc.

        # Example ledger calls (adjust transaction types and accounts as needed)
        # Assuming a debit from a conceptual 'simple_escrow_holding' user/account
        # ledger_service.debit_funds(user=escrow_holder, currency=CURRENCY_CODE, amount=total_escrowed_btc, ...)

        if vendor_payout_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                 user=vendor, currency=CURRENCY_CODE, amount=vendor_payout_btc,
                 transaction_type=common_escrow_utils.LEDGER_TX_ESCROW_RELEASE_VENDOR,
                 related_order=order, external_txid=tx_hash, notes=f"{notes_base} Vendor Payout"
             )
        if market_fee_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                 user=market_user, currency=CURRENCY_CODE, amount=market_fee_btc,
                 transaction_type=common_escrow_utils.LEDGER_TX_MARKET_FEE,
                 related_order=order, notes=f"{notes_base} Market Fee"
             )

        logger.info(f"{log_prefix}: Ledger updated. Vendor: {vendor_payout_btc}, Fee: {market_fee_btc}. Order finalized.")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}-Simple) finalized. Vendor: {vendor.username}. TX: {tx_hash or 'N/A'}")

        # Send Notifications
        if NOTIFICATIONS_ENABLED:
             try:
                  # Notify Vendor
                  if vendor and vendor.pk:
                       order_url = f"/orders/{order.id}"
                       message = f"Funds released for Order #{str(order.id)[:8]}. Payout: {vendor_payout_btc} {CURRENCY_CODE}. TX: {tx_hash or 'N/A'}"
                       create_notification(user_id=vendor.id, level='success', message=message, link=order_url)
                  # Notify Buyer
                  buyer = order.buyer
                  if buyer and buyer.pk:
                       order_url = f"/orders/{order.id}"
                       product_name = getattr(order.product, 'name', 'N/A')
                       message = f"Order #{str(order.id)[:8]} ({product_name}) has been finalized. Thank you."
                       create_notification(user_id=buyer.id, level='success', message=message, link=order_url)
             except NotificationError as notify_e:
                  logger.error(f"{log_prefix}: Failed finalization notification: {notify_e}", exc_info=True)
             except Exception as notify_e:
                  logger.error(f"{log_prefix}: Unexpected error sending finalization notification: {notify_e}", exc_info=True)

        return True

    except (ObjectDoesNotExist, ValueError, EscrowError) as e:
        logger.error(f"{log_prefix}: Pre-withdrawal validation failed: {e}", exc_info=True)
        raise # Re-raise validation/setup errors
    except CryptoProcessingError as e:
        # Specific error during withdrawal initiation from market_wallet_service
        logger.error(f"{log_prefix}: Market withdrawal failed: {e}", exc_info=True)
        # Do NOT proceed with DB/Ledger updates if withdrawal failed.
        raise # Re-raise crypto error
    except (InsufficientFundsError, LedgerError, IntegrityError, DjangoValidationError) as final_db_err:
        # Catch errors during the final DB/Ledger update phase *after* potential withdrawal
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: Simple release withdrawal potentially OK but FINAL update FAILED! Error: {final_db_err}. MANUAL INTERVENTION LIKELY NEEDED!", exc_info=True)
        # Raise the special error to signal potential inconsistency
        raise PostBroadcastUpdateError(
             message=f"Post-withdrawal DB/Ledger update failed for Simple {CURRENCY_CODE} Order {getattr(order,'id','N/A')}",
             original_exception=final_db_err,
             tx_hash=getattr(order, 'release_tx_broadcast_hash', None) # Pass tx_hash if available
        ) from final_db_err
    except Exception as final_e:
        # Catch unexpected errors during the final update phase
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: Simple release withdrawal potentially OK but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
            message=f"Unexpected post-withdrawal error for Simple {CURRENCY_CODE} Order {getattr(order,'id','N/A')}",
            original_exception=final_e,
            tx_hash=getattr(order, 'release_tx_broadcast_hash', None)
        ) from final_e


@transaction.atomic
def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: Union[int, float]
) -> bool:
    """
    Resolves a BASIC BTC escrow dispute by initiating withdrawals from the market wallet
    to the buyer and/or vendor based on the resolution percentage. Updates ledger/status.

    Args:
        order: The Order instance in dispute (must be BASIC BTC).
        moderator: The staff user resolving the dispute.
        resolution_notes: Explanation of the resolution.
        release_to_buyer_percent: Percentage (0-100) of escrowed funds for the buyer.

    Returns:
        bool: True if resolution withdrawals and internal updates were successful.

    Raises:
        ObjectDoesNotExist: If order, buyer, vendor not found.
        PermissionError: If moderator lacks permissions.
        ValueError: For invalid percentage, notes, currency/escrow type mismatch.
        EscrowError: For invalid order state or internal errors.
        CryptoProcessingError: If market_wallet_service withdrawal fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        PostBroadcastUpdateError: If DB/Ledger update fails *after* successful withdrawal(s).
    """
    log_prefix = f"Order {order.id} (ResolveDispute {CURRENCY_CODE}-Simple)"
    logger.info(f"{log_prefix}: Attempting BASIC resolution. Buyer %: {release_to_buyer_percent}")

    # --- Validation ---
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
    if not isinstance(moderator, User) or not moderator.pk: raise ValueError("Invalid Moderator object.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError("Currency mismatch.")
    if order.escrow_type != EscrowType.BASIC: raise ValueError("Escrow type mismatch.")
    if order.status != OrderStatusChoices.DISPUTED:
        raise EscrowError(f"Order must be in DISPUTED state (Current: '{order.status}').")
    if not getattr(moderator, 'is_staff', False) and not getattr(moderator, 'is_superuser', False):
        logger.warning(f"{log_prefix}: Permission denied for user {moderator.username}.")
        raise PermissionError("User lacks permission to resolve disputes.")
    try:
        buyer_percent_decimal = Decimal(str(release_to_buyer_percent))
        if not (Decimal('0.0') <= buyer_percent_decimal <= Decimal('100.0')):
            raise ValueError("Percentage must be between 0 and 100.")
    except (ValueError, TypeError) as percent_err:
         raise ValueError(f"Invalid percentage value: {release_to_buyer_percent}") from percent_err
    if not resolution_notes or not isinstance(resolution_notes, str) or len(resolution_notes.strip()) < 5:
        raise ValueError("Valid resolution notes (minimum 5 characters) required.")

    buyer = order.buyer
    vendor = order.vendor
    if not buyer or not vendor: raise ObjectDoesNotExist("Buyer or Vendor not found on order.")

    # --- Calculate Payout Shares (STANDARD BTC units) ---
    release_to_vendor_percent_decimal = Decimal(100) - buyer_percent_decimal
    # Use common utils for precision/conversion
    from . import bitcoin_service # For conversion
    total_escrowed_btc = common_escrow_utils._convert_atomic_to_standard(
        order.total_price_native_selected, CURRENCY_CODE, bitcoin_service
    )
    prec = common_escrow_utils._get_currency_precision(CURRENCY_CODE)
    quantizer = Decimal(f'1e-{prec}')

    buyer_share_btc = (total_escrowed_btc * buyer_percent_decimal / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
    buyer_share_btc = max(Decimal('0.0'), buyer_share_btc)
    # Calculate vendor share based on remaining amount to avoid rounding issues losing dust
    vendor_share_btc = (total_escrowed_btc - buyer_share_btc).quantize(quantizer, rounding=ROUND_DOWN)
    vendor_share_btc = max(Decimal('0.0'), vendor_share_btc)

    # --- Security/Sanity check calculation ---
    if (buyer_share_btc + vendor_share_btc).quantize(quantizer) > total_escrowed_btc.quantize(quantizer):
         logger.critical(f"{log_prefix}: CRITICAL CALCULATION ERROR: Shares ({buyer_share_btc + vendor_share_btc}) exceed total ({total_escrowed_btc}). Aborting.")
         raise ValueError("Calculation error: Sum of dispute shares exceeds total escrowed amount.")

    logger.info(f"{log_prefix}: Calculated Shares - Buyer: {buyer_share_btc}, Vendor: {vendor_share_btc} {CURRENCY_CODE}.")

    # --- Initiate Withdrawals (if needed) ---
    buyer_tx_hash: Optional[str] = None
    vendor_tx_hash: Optional[str] = None
    withdrawal_failed = False

    try:
        # Withdraw Buyer Share
        if buyer_share_btc > Decimal('0.0'):
            try:
                buyer_address = common_escrow_utils._get_withdrawal_address(buyer, CURRENCY_CODE)
                logger.info(f"{log_prefix}: Requesting buyer withdrawal of {buyer_share_btc} {CURRENCY_CODE} to {buyer_address}.")
                buyer_tx_hash = market_wallet_service.initiate_market_withdrawal(
                    currency=CURRENCY_CODE, target_address=buyer_address, amount_standard=buyer_share_btc
                )
                if not buyer_tx_hash: raise CryptoProcessingError("Buyer withdrawal initiation failed to return TX hash.")
                logger.info(f"{log_prefix}: Buyer withdrawal initiated. TXID: {buyer_tx_hash}")
            except (ValueError, CryptoProcessingError, NotImplementedError) as e:
                logger.error(f"{log_prefix}: FAILED to initiate buyer withdrawal: {e}", exc_info=True)
                withdrawal_failed = True # Mark failure but continue if vendor share exists
                # Depending on policy, might want to raise immediately or attempt vendor withdrawal first

        # Withdraw Vendor Share (only if buyer withdrawal didn't hard fail, or if policy allows)
        if not withdrawal_failed and vendor_share_btc > Decimal('0.0'):
            try:
                vendor_address = common_escrow_utils._get_withdrawal_address(vendor, CURRENCY_CODE)
                logger.info(f"{log_prefix}: Requesting vendor withdrawal of {vendor_share_btc} {CURRENCY_CODE} to {vendor_address}.")
                vendor_tx_hash = market_wallet_service.initiate_market_withdrawal(
                    currency=CURRENCY_CODE, target_address=vendor_address, amount_standard=vendor_share_btc
                )
                if not vendor_tx_hash: raise CryptoProcessingError("Vendor withdrawal initiation failed to return TX hash.")
                logger.info(f"{log_prefix}: Vendor withdrawal initiated. TXID: {vendor_tx_hash}")
            except (ValueError, CryptoProcessingError, NotImplementedError) as e:
                logger.error(f"{log_prefix}: FAILED to initiate vendor withdrawal: {e}", exc_info=True)
                withdrawal_failed = True
                # If buyer withdrawal succeeded but vendor failed, this is a partial failure state! Critical.

        # If any withdrawal failed, raise error *before* updating DB/Ledger
        if withdrawal_failed:
             # Collect successful TX hashes for the error message
             successful_txs = [tx for tx in [buyer_tx_hash, vendor_tx_hash] if tx]
             tx_info = f" (Successful TXs: {', '.join(successful_txs)})" if successful_txs else ""
             raise CryptoProcessingError(f"One or more market withdrawals failed during dispute resolution.{tx_info}")

    except (ValueError, CryptoProcessingError, EscrowError, NotImplementedError) as e:
         # Catch errors from address lookup or withdrawal initiation
         logger.error(f"{log_prefix}: Dispute withdrawal phase failed: {e}", exc_info=True)
         raise # Re-raise error, transaction will roll back

    # --- Final DB/Ledger Update (Only if ALL withdrawals succeeded or were zero) ---
    # Combine transaction hashes for storage
    combined_tx_hash = ",".join(filter(None, [buyer_tx_hash, vendor_tx_hash])) or None

    try:
        now = timezone.now()
        order.status = OrderStatusChoices.DISPUTE_RESOLVED
        order.release_tx_broadcast_hash = combined_tx_hash # Store combined hashes
        # Note: dispute_resolved_at is on the Dispute model
        order.updated_at = now

        update_fields = ['status', 'release_tx_broadcast_hash', 'updated_at']
        # Add optional fields from Order model if they exist
        if hasattr(order, 'dispute_resolved_by'): order.dispute_resolved_by = moderator; update_fields.append('dispute_resolved_by')
        if hasattr(order, 'dispute_resolution_notes'): order.dispute_resolution_notes = resolution_notes[:2000]; update_fields.append('dispute_resolution_notes')
        if hasattr(order, 'dispute_buyer_percent'):
             try: order.dispute_buyer_percent = buyer_percent_decimal
             except TypeError: order.dispute_buyer_percent = int(buyer_percent_decimal)
             update_fields.append('dispute_buyer_percent')

        order.save(update_fields=list(set(update_fields)))

        # Update related Dispute object
        try:
             dispute = Dispute.objects.get(order=order)
             dispute.status = Dispute.StatusChoices.RESOLVED
             dispute.resolved_by = moderator
             dispute.resolution_notes = resolution_notes[:2000]
             dispute.resolved_at = now
             dispute.buyer_percentage = buyer_percent_decimal
             dispute.save(update_fields=['status', 'resolved_by', 'resolution_notes', 'resolved_at', 'buyer_percentage', 'updated_at'])
        except Dispute.DoesNotExist:
             logger.error(f"{log_prefix}: Could not find related Dispute object to update.")
             # Continue with ledger updates? Or raise? Depends on requirements.

        # Update Ledger (STANDARD BTC units)
        notes_base = f"Resolve Simple {CURRENCY_CODE} Order {order.id} by {moderator.username}."
        # TODO: Define ledger flow. Example: Debit market escrow holding, credit buyer/vendor.
        # ledger_service.debit_funds(user=escrow_holder, currency=CURRENCY_CODE, amount=total_escrowed_btc, ...)

        if buyer_share_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                 user=buyer, currency=CURRENCY_CODE, amount=buyer_share_btc,
                 transaction_type=common_escrow_utils.LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
                 related_order=order, external_txid=buyer_tx_hash,
                 notes=f"{notes_base} Buyer Share ({buyer_percent_decimal:.2f}%)"
             )
        if vendor_share_btc > Decimal('0.0'):
             ledger_service.credit_funds(
                 user=vendor, currency=CURRENCY_CODE, amount=vendor_share_btc,
                 transaction_type=common_escrow_utils.LEDGER_TX_DISPUTE_RESOLUTION_VENDOR,
                 related_order=order, external_txid=vendor_tx_hash,
                 notes=f"{notes_base} Vendor Share ({release_to_vendor_percent_decimal:.2f}%)"
             )

        logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_btc}, Vendor: {vendor_share_btc}. Dispute resolved.")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}-Simple) dispute resolved by {moderator.username}. Buyer%: {buyer_percent_decimal:.2f}. TXs: {combined_tx_hash or 'N/A'}")

        # Send Notifications
        if NOTIFICATIONS_ENABLED:
            try:
                order_url = f"/orders/{order.id}"
                common_msg_part = f"Dispute resolved for Order #{str(order.id)[:8]}. Notes: {resolution_notes[:50]}..."
                if buyer and buyer.pk:
                     buyer_msg = f"{common_msg_part} You received {buyer_share_btc} {CURRENCY_CODE} ({buyer_percent_decimal:.2f}%)." + (f" TX: {buyer_tx_hash}" if buyer_tx_hash else "")
                     create_notification(user_id=buyer.id, level='info', message=buyer_msg, link=order_url)
                if vendor and vendor.pk:
                     vendor_msg = f"{common_msg_part} Vendor received {vendor_share_btc} {CURRENCY_CODE} ({release_to_vendor_percent_decimal:.2f}%)." + (f" TX: {vendor_tx_hash}" if vendor_tx_hash else "")
                     create_notification(user_id=vendor.id, level='info', message=vendor_msg, link=order_url)
            except NotificationError as notify_e:
                 logger.error(f"{log_prefix}: Failed dispute resolved notification: {notify_e}", exc_info=True)
            except Exception as notify_e:
                 logger.error(f"{log_prefix}: Unexpected error sending dispute resolved notification: {notify_e}", exc_info=True)

        return True

    except (InsufficientFundsError, LedgerError, IntegrityError, DjangoValidationError) as final_db_err:
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: Simple dispute withdrawal(s) potentially OK but FINAL update FAILED! Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
             message=f"Post-withdrawal DB/Ledger update failed for Simple {CURRENCY_CODE} dispute Order {order.id}",
             original_exception=final_db_err,
             tx_hash=combined_tx_hash # Pass combined hash if available
        ) from final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: Simple dispute withdrawal(s) potentially OK but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
            message=f"Unexpected post-withdrawal error for Simple {CURRENCY_CODE} dispute Order {order.id}",
            original_exception=final_e,
            tx_hash=combined_tx_hash
        ) from final_e


# Note: get_unsigned_release_tx is NOT applicable to simple escrow as there's
# nothing for the buyer/vendor to sign cryptographically for the release itself.
# The release is triggered internally and executed by the market wallet.
#This service provides a solid implementation for basic, centralized Bitcoin escrow. It correctly interfaces with the ledger and market wallet services and employs robust transaction management and error handling. Completing the ledger debit logic and implementing any required deposit fees are the main steps needed for full production readiness.