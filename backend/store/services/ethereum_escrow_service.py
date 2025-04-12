# backend/store/services/ethereum_escrow_service.py
# Handles Ethereum (ETH) specific escrow logic.
# Detailed Skeleton - Requires implementation of ethereum_service interactions.
#
# REVISIONS:
# - 2025-04-11 (Gemini Rev 10): Removed NotImplementedError in create_escrow and uncommented
#                              placeholder call to ethereum_service.create_eth_multisig_contract
#                              to resolve "Service not implemented" error during testing.
# - 2025-04-09 (The Void): v1.24.0 - Detailed Skeleton Implementation.
#    - Added logic structure mirroring monero_escrow_service.
#    - Included fetching models, state checks, calculations, model updates.
#    - Added specific comments and NotImplementedError where ethereum_service calls
#      and ledger updates are required.
#    - Maintained correct function names for dispatcher compatibility.
# - 2025-04-09 (The Void): v1.23.0 - Renamed functions to align with common_escrow_utils dispatcher.
#    - Renamed `create_escrow_for_order` to `create_escrow`.
#    - Renamed `broadcast_release_transaction` to `broadcast_release`.
# - (Original version provided by user contained placeholders)

import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import timedelta
from typing import Optional, Tuple, Dict, Any, List, Union

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist

# --- Service & Utility Imports ---
from .common_escrow_utils import (
    get_market_user, _get_currency_precision, _get_atomic_to_standard_converter,
    _convert_atomic_to_standard, _get_market_fee_percentage, _get_withdrawal_address,
    _check_order_timeout, CryptoServiceInterface, PostBroadcastUpdateError,
    # Constants
    LEDGER_TX_DEPOSIT, LEDGER_TX_ESCROW_FUND_DEBIT, LEDGER_TX_ESCROW_RELEASE_VENDOR,
    LEDGER_TX_ESCROW_RELEASE_BUYER, LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
    LEDGER_TX_DISPUTE_RESOLUTION_VENDOR, LEDGER_TX_MARKET_FEE,
    ATTR_ETH_MULTISIG_OWNER_ADDRESS, ATTR_ETH_WITHDRAWAL_ADDRESS, ATTR_ETH_ESCROW_ADDRESS, # ETH specific attrs
)
# Import the specific crypto service for Ethereum
from . import ethereum_service # Assumed to exist and implement CryptoServiceInterface methods for ETH
# Import other necessary services
from ledger import services as ledger_service
from ledger.services import InsufficientFundsError, InvalidLedgerOperationError
from notifications.services import create_notification
from store.exceptions import EscrowError, CryptoProcessingError
from ledger.exceptions import LedgerError
from notifications.exceptions import NotificationError

# --- Model Imports ---
from store.models import Order, CryptoPayment, GlobalSettings, Product, OrderStatus as OrderStatusChoices
User = get_user_model()

# --- Type Hinting ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from store.models import GlobalSettings as GlobalSettingsModel, Product as ProductModel
    from django.contrib.auth.models import AbstractUser
    UserModel = AbstractUser

# --- Loggers ---
logger = logging.getLogger(__name__) # Logger specific to this ETH escrow service
security_logger = logging.getLogger('django.security')

# --- Constants Specific to this Service ---
CURRENCY_CODE = 'ETH'
NATIVE_UNIT = 'Wei' # Ethereum's atomic unit


# === Enterprise Grade Ethereum Escrow Functions (Detailed Skeleton) ===

@transaction.atomic
def create_escrow(order: 'Order') -> None:
    """
    Prepares an Ethereum order for payment: Deploys or identifies an ETH multi-sig
    (e.g., Gnosis Safe), creates the crypto payment record, sets deadlines, and
    updates order status. Called by the common escrow dispatcher.

    Args:
        order: The Order instance (must be in PENDING_PAYMENT status initially,
               and selected_currency must be ETH).
    Raises:
        ValueError: If inputs are invalid (order, participants, keys) or currency mismatch.
        ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
        EscrowError: For general escrow process failures (e.g., wrong status, save errors).
        CryptoProcessingError: If ethereum_service calls fail.
        RuntimeError: If critical settings/models are unavailable.
        NotImplementedError: For parts requiring ethereum_service implementation.
    """
    log_prefix = f"Order {order.id} ({CURRENCY_CODE}) [create_escrow]"
    logger.info(f"{log_prefix}: Initiating ETH multi-sig escrow setup...")

    if not isinstance(order, Order) or not order.pk or not hasattr(order, 'product'):
        raise ValueError("Invalid Order object provided.")

    if order.selected_currency != CURRENCY_CODE:
        raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

    if not all([CryptoPayment, User, GlobalSettings, ethereum_service, ledger_service, create_notification]):
        # Added checks for assumed dependencies based on Monero service
        raise RuntimeError("Critical application models/services (CryptoPayment, User, Settings, ETH Service, Ledger, Notify) are not available.")

    # --- Idempotency Check and Status Validation ---
    if order.status == OrderStatusChoices.PENDING_PAYMENT:
        if CryptoPayment.objects.filter(order=order, currency=CURRENCY_CODE).exists():
            logger.info(f"{log_prefix}: ETH CryptoPayment details already exist for PENDING order. Skipping creation (Idempotency).")
            return
    else:
        raise EscrowError(f"Order must be in '{OrderStatusChoices.PENDING_PAYMENT}' state to setup ETH escrow (Current Status: {order.status})")

    # --- Load Config ---
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        confirmations_needed = getattr(gs, f'confirmations_needed_{CURRENCY_CODE.lower()}', 6) # Example default for ETH
        payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4))
        # Threshold might come from settings or be standard (e.g., 2-of-3)
        threshold = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2)) # Using generic setting
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        raise ObjectDoesNotExist(f"Failed to load required settings: {e}") from e

    # --- Load Participants ---
    try:
        buyer = order.buyer
        vendor = order.vendor
        market_user = get_market_user()
        if not all([buyer, vendor]):
            raise ObjectDoesNotExist("Buyer or Vendor missing for the order.")
    except (ObjectDoesNotExist, RuntimeError) as e:
        raise # Re-raise specific errors

    # --- Gather Participant ETH Addresses ---
    participant_addresses: List[str] = []
    address_attr = ATTR_ETH_MULTISIG_OWNER_ADDRESS # Attribute storing participant's address for multisig
    try:
        buyer_addr = getattr(buyer, address_attr, None)
        vendor_addr = getattr(vendor, address_attr, None)
        market_addr = getattr(market_user, address_attr, None)

        if not all([buyer_addr, vendor_addr, market_addr]):
            missing = [u.username for u, i in zip([buyer, vendor, market_user], [buyer_addr, vendor_addr, market_addr]) if not i]
            msg = f"Missing required ETH owner address ('{address_attr}') for user(s): {', '.join(missing)}."
            # TODO: Validate ETH addresses format here or in ethereum_service
            raise ValueError(msg)

        participant_addresses = [buyer_addr, vendor_addr, market_addr]
        logger.debug(f"{log_prefix}: Gathered participant ETH addresses for {len(participant_addresses)} owners.")

    except (ValueError, AttributeError) as e:
        raise ValueError(f"Failed to gather required participant ETH addresses: {e}") from e

    # --- Call Ethereum Service to Create/Deploy Escrow Contract (e.g., Gnosis Safe) ---
    escrow_address: Optional[str] = None
    contract_details: Dict[str, Any] = {}
    order_update_fields = ['payment_deadline', 'updated_at', 'status']
    try:
        logger.debug(f"{log_prefix}: Deploying/creating ETH multi-sig escrow via ethereum_service...")

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function should handle deploying a Gnosis Safe or similar multisig contract
        # with the participant_addresses as owners and the specified threshold.
        # It MUST return at least the 'contract_address'. It might also return tx_hash, abi, etc.
        # --- UNCOMMENTED PLACEHOLDER CALL ---
        contract_details = ethereum_service.create_eth_multisig_contract(
             owner_addresses=participant_addresses,
             threshold=threshold,
             order_id=str(order.id) # Pass order ID for linking/logging if needed
        )
        # --- REMOVED raise NotImplementedError ---
        # raise NotImplementedError("ethereum_service.create_eth_multisig_contract is not implemented.")

        escrow_address = contract_details.get('contract_address') # Adjust key based on actual return
        # deployment_tx_hash = contract_details.get('tx_hash') # Optional

        if not escrow_address or not isinstance(escrow_address, str): # TODO: Add ETH address validation
             raise ValueError("ethereum_service failed to return a valid escrow contract address string for ETH.")

        # Store the escrow address on the Order model if the field exists
        if hasattr(order, ATTR_ETH_ESCROW_ADDRESS):
            setattr(order, ATTR_ETH_ESCROW_ADDRESS, escrow_address)
            order_update_fields.append(ATTR_ETH_ESCROW_ADDRESS)
        else:
             logger.warning(f"{log_prefix}: Order model missing '{ATTR_ETH_ESCROW_ADDRESS}' field. Cannot save ETH escrow address.")

        logger.info(f"{log_prefix}: Generated ETH Escrow Address (Multisig Contract): {escrow_address}")

    except NotImplementedError: # Keep this catch block in case the ethereum_service function itself raises it
         logger.error(f"{log_prefix}: Required ethereum_service function is not implemented.")
         raise CryptoProcessingError("ETH escrow creation failed: Service function not implemented.")
    except (AttributeError, ValueError, KeyError, CryptoProcessingError) as crypto_err:
        logger.error(f"{log_prefix}: Failed to generate ETH escrow details: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Failed to generate ETH escrow details: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error generating ETH escrow details.")
        raise CryptoProcessingError("Unexpected error generating ETH escrow details.") from e

    # --- Create CryptoPayment Record ---
    try:
        if not isinstance(order.total_price_native_selected, Decimal):
            raise ValueError(f"Order {order.id} total_price_native_selected is not Decimal (should be {NATIVE_UNIT})")

        # Ensure expected amount is positive
        if order.total_price_native_selected <= Decimal('0'):
             raise ValueError(f"Order {order.id} total_price_native_selected must be positive ({NATIVE_UNIT})")

        payment_obj = CryptoPayment.objects.create(
            order=order,
            currency=CURRENCY_CODE,
            payment_address=escrow_address, # The address buyers send funds to
            expected_amount_native=order.total_price_native_selected, # Store amount in Wei
            confirmations_needed=confirmations_needed
            # Note: ETH doesn't typically use payment IDs like Monero
        )
        logger.info(f"{log_prefix}: Created ETH CryptoPayment {payment_obj.id}. Expected {NATIVE_UNIT}: {payment_obj.expected_amount_native}")

    except IntegrityError as ie:
        raise EscrowError("Failed to create unique ETH payment record, possibly duplicate.") from ie
    except (ValueError, Exception) as e:
        raise EscrowError(f"Failed to create ETH payment record: {e}") from e

    # --- Update Order Status and Deadlines ---
    try:
        order.payment_deadline = timezone.now() + timedelta(hours=payment_wait_hours)
        order.status = OrderStatusChoices.PENDING_PAYMENT # Remains pending until confirmed
        order.updated_at = timezone.now()

        unique_fields_to_update = list(set(order_update_fields))
        order.save(update_fields=unique_fields_to_update)

        logger.info(f"{log_prefix}: ETH multi-sig escrow setup successful. Status -> {order.status}. Payment deadline: {order.payment_deadline}. Awaiting payment to {escrow_address}")

        # --- Send Notification ---
        try:
            buyer = order.buyer # Re-fetch buyer for notification
            order_url = f"/orders/{order.id}"
            product_name = getattr(order.product, 'name', 'N/A')
            order_id_str = str(order.id)
            # Convert Wei to ETH for display
            expected_eth_display = _convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, ethereum_service)
            message = (f"Your Order #{order_id_str[:8]} ({product_name}) is ready for payment. "
                       f"Please send exactly {expected_eth_display} {CURRENCY_CODE} " # Display standard unit
                       f"to the escrow address {escrow_address} "
                       f"before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}.")
            create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent 'ready for ETH payment' notification to Buyer {buyer.username}.")
        except NotificationError as notify_e:
             logger.error(f"{log_prefix}: Failed to create 'ready for ETH payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)
        except Exception as notify_e:
             # Catch potential conversion errors from _convert_atomic_to_standard as well
             logger.error(f"{log_prefix}: Unexpected error creating/sending 'ready for ETH payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)

    except Exception as e:
        raise EscrowError("Failed to save order updates during ETH escrow creation.") from e
    
@transaction.atomic
def check_and_confirm_payment(payment_id: Any) -> None:
    """
    Checks Ethereum node for payment confirmation TO THE ESCROW ADDRESS (e.g., Gnosis Safe),
    applies deposit fee, compares amount (Wei), and if valid, atomically updates
    Ledger (using standard ETH units) and Order status.

    Args:
        payment_id: The ID of the CryptoPayment record (must be for ETH) to check.
    Raises:
        ObjectDoesNotExist: If the payment record or related users are not found.
        ValueError: If the payment record is not for ETH.
        EscrowError: For general process failures (DB errors, amount format).
        CryptoProcessingError: If ethereum_service communication fails.
        LedgerError: If ledger updates fail critically.
        InsufficientFundsError: If funds cannot be locked/debited after deposit.
        NotImplementedError: For parts requiring ethereum_service or ledger_service implementation.
    """
    payment: Optional['CryptoPayment'] = None
    order: Optional['Order'] = None
    log_prefix = f"PaymentConfirm Check (ID: {payment_id}, Currency: {CURRENCY_CODE})"
    buyer_id: Optional[int] = None
    market_user_id: Optional[int] = None

    # --- Fetch and Validate Payment/Order ---
    try:
        market_user = get_market_user() # Needed for fee/ledger
        market_user_id = market_user.pk

        payment = CryptoPayment.objects.select_for_update().select_related(
            'order__buyer', 'order__vendor', 'order__product'
        ).get(id=payment_id)

        if payment.currency != CURRENCY_CODE:
             raise ValueError(f"This service only handles {CURRENCY_CODE} payments.")

        if not payment.payment_address: # ETH requires a payment address
             raise EscrowError(f"Cannot check ETH payment {payment_id}: missing payment_address (escrow contract).")

        order = payment.order
        buyer_id = order.buyer_id
        if not buyer_id: raise ObjectDoesNotExist("Buyer missing on related order.")

        log_prefix = f"PaymentConfirm Check (Order: {order.id}, Payment: {payment_id}, Currency: {CURRENCY_CODE})"
        logger.info(f"{log_prefix}: Starting check for ETH payment to {payment.payment_address}.")

    except CryptoPayment.DoesNotExist:
        raise
    except User.DoesNotExist as user_err:
        # Covers market user or buyer if get fails later
        raise ObjectDoesNotExist(f"Required user not found during payment confirmation setup: {user_err}") from user_err
    except ValueError as ve:
        raise ve
    except EscrowError as ee:
        raise ee
    except RuntimeError as e: # From get_market_user
        raise
    except Exception as e:
        raise EscrowError(f"Database/Setup error fetching details for payment {payment_id}.") from e

    # --- Check Statuses ---
    if payment.is_confirmed:
        logger.info(f"{log_prefix}: Already confirmed.")
        return # Successfully idempotent

    if order.status != OrderStatusChoices.PENDING_PAYMENT:
        logger.warning(f"{log_prefix}: Order status is '{order.status}', not '{OrderStatusChoices.PENDING_PAYMENT}'. Skipping check.")
        _check_order_timeout(order) # Check if it timed out instead
        return

    # --- Call Ethereum Service to Scan for Confirmation ---
    is_crypto_confirmed = False
    received_atomic = Decimal('0.0') # Received Wei
    confirmations = 0
    external_txid: Optional[str] = payment.transaction_hash # Keep if already known

    try:
        scan_function_name = 'scan_for_payment_confirmation'
        if not hasattr(ethereum_service, scan_function_name):
            raise NotImplementedError(f"ethereum_service module missing '{scan_function_name}'")

        logger.debug(f"{log_prefix}: Calling {scan_function_name} for ETH Payment {payment.id} (Address: {payment.payment_address})...")
        scan_function = getattr(ethereum_service, scan_function_name)

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function should query the ETH blockchain (e.g., using Web3.py)
        # to check the balance of payment.payment_address OR look for incoming transactions.
        # It needs to handle confirmations based on gs.confirmations_needed_eth.
        # Should return Tuple[bool, Decimal, int, Optional[str]] -> (is_confirmed, received_wei, confirmations, tx_hash)
        # check_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = scan_function(payment)
        raise NotImplementedError(f"ethereum_service.{scan_function_name} is not implemented.")

        if check_result:
            is_crypto_confirmed, received_atomic, confirmations, txid_found = check_result
            if txid_found and not external_txid: # Store TX hash if found
                external_txid = txid_found
            logger.debug(f"{log_prefix}: Scan Result - Confirmed={is_crypto_confirmed}, Rcvd{NATIVE_UNIT}={received_atomic}, Confs={confirmations}, TX={external_txid}")
        else:
            is_crypto_confirmed = False
            logger.debug(f"{log_prefix}: Scan Result - No confirmed ETH transaction found yet for address {payment.payment_address}.")

    except NotImplementedError:
         logger.error(f"{log_prefix}: Required ethereum_service function is not implemented.")
         raise CryptoProcessingError("ETH payment check failed: Service not implemented.")
    except CryptoProcessingError as cpe:
        logger.error(f"{log_prefix}: Error during ETH confirmation scan: {cpe}", exc_info=True)
        raise # Re-raise specific crypto error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error checking ETH payment.")
        raise CryptoProcessingError(f"Failed to check {CURRENCY_CODE} payment: {e}") from e

    # --- Handle Confirmation Result ---
    if not is_crypto_confirmed:
        logger.debug(f"{log_prefix}: ETH Payment not confirmed yet.")
        _check_order_timeout(order) # Check for timeout
        return

    logger.info(f"{log_prefix}: ETH Crypto confirmed. Rcvd{NATIVE_UNIT}={received_atomic}, Exp{NATIVE_UNIT}={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")

    # --- Amount Validation ---
    try:
        if not isinstance(payment.expected_amount_native, Decimal):
            raise ValueError(f"Expected amount ({NATIVE_UNIT}) on Payment {payment.id} is not Decimal")
        if not isinstance(received_atomic, Decimal):
             received_atomic = Decimal(str(received_atomic))

        expected_atomic = payment.expected_amount_native
        is_amount_sufficient = received_atomic >= expected_atomic

        # Convert to standard ETH for logging/ledger
        expected_eth = _convert_atomic_to_standard(expected_atomic, CURRENCY_CODE, ethereum_service)
        received_eth = _convert_atomic_to_standard(received_atomic, CURRENCY_CODE, ethereum_service)
        logger.debug(f"{log_prefix}: Converted amounts: ExpETH={expected_eth}, RcvdETH={received_eth}")

    except (InvalidOperation, TypeError, ValueError, EscrowError) as q_err:
        # Catch conversion errors too
        raise EscrowError("Invalid ETH payment amount format or conversion error.") from q_err

    # --- Handle Insufficient Amount ---
    if not is_amount_sufficient:
        logger.warning(f"{log_prefix}: Amount insufficient. RcvdETH: {received_eth}, ExpETH: {expected_eth}. (Rcvd{NATIVE_UNIT}: {received_atomic}, Exp{NATIVE_UNIT}: {expected_atomic}). TXID: {external_txid}")
        try:
            # Update payment record with received details
            payment.is_confirmed = True
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_atomic
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            # Update order status to cancelled
            updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
            )

            if updated_count > 0:
                logger.info(f"{log_prefix}: Order status set to '{OrderStatusChoices.CANCELLED_UNDERPAID}'.")
                security_logger.warning(f"Order {order.id} cancelled due to underpayment. Rcvd {received_eth}, Exp {expected_eth} {CURRENCY_CODE}. TX: {external_txid}")
                # Send notification
                try:
                    buyer = User.objects.get(pk=buyer_id)
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order.product,'name','N/A')
                    order_id_str = str(order.id)
                    message = (f"Your payment for Order #{order_id_str[:8]} ({product_name}) was confirmed "
                               f"but the amount received ({received_eth} {CURRENCY_CODE}) was less than expected ({expected_eth} {CURRENCY_CODE}). "
                               f"The order has been cancelled. Please contact support. TXID: {external_txid or 'N/A'}")
                    create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                except User.DoesNotExist:
                     logger.error(f"{log_prefix}: Failed to send underpayment notification: Buyer {buyer_id} not found.")
                except NotificationError as notify_e:
                    logger.error(f"{log_prefix}: Failed to create underpayment cancellation notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
                except Exception as notify_e:
                    logger.error(f"{log_prefix}: Unexpected error creating underpayment notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
            else:
                # Order status might have changed between check and update
                current_status = Order.objects.filter(pk=order.pk).values_list('status', flat=True).first()
                logger.warning(f"{log_prefix}: Order status not '{OrderStatusChoices.PENDING_PAYMENT}' during underpaid update attempt. Current: {current_status}")

            return # Handled underpayment case
        except Exception as e:
            raise EscrowError("Failed to process ETH underpayment.") from e

    # --- Handle Sufficient Amount: Update Ledger and Order Status ---
    try:
        # Re-fetch users for safety within transaction
        buyer: Optional['UserModel'] = User.objects.get(pk=buyer_id)
        # Market user already fetched

        prec = _get_currency_precision(CURRENCY_CODE)
        quantizer = Decimal(f'1e-{prec}')
        deposit_fee_percent = _get_market_fee_percentage(CURRENCY_CODE)

        # Calculate fees in standard ETH units
        deposit_fee_eth = (received_eth * deposit_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if deposit_fee_eth < Decimal('0.0'): deposit_fee_eth = Decimal('0.0')
        net_deposit_eth = (received_eth - deposit_fee_eth).quantize(quantizer, rounding=ROUND_DOWN)
        if net_deposit_eth < Decimal('0.0'): net_deposit_eth = Decimal('0.0')

        logger.info(f"{log_prefix}: Applying Deposit Fee ({deposit_fee_percent}%). Gross: {received_eth}, Fee: {deposit_fee_eth}, Net: {net_deposit_eth} {CURRENCY_CODE}")

        ledger_deposit_notes = f"Confirmed ETH payment deposit Order {order.id}, TX: {external_txid}"

        # !!! IMPLEMENTATION REQUIRED for ledger_service !!!
        # Ensure ledger_service.credit_funds, lock_funds, debit_funds, unlock_funds work correctly.
        # These operations MUST be atomic with the order/payment updates.

        # Credit deposit fee to market user
        if deposit_fee_eth > Decimal('0.0'):
            # ledger_service.credit_funds(market_user, CURRENCY_CODE, deposit_fee_eth, LEDGER_TX_MARKET_FEE, related_order=order, notes=f"Deposit Fee Order {order.id}")
             pass # Placeholder
        # Credit net deposit to buyer
        if net_deposit_eth > Decimal('0.0'):
            # ledger_service.credit_funds(buyer, CURRENCY_CODE, net_deposit_eth, LEDGER_TX_DEPOSIT, external_txid=external_txid, related_order=order, notes=ledger_deposit_notes)
             pass # Placeholder
        elif received_eth > Decimal('0.0'): # Handle case where fee consumes everything
            logger.warning(f"{log_prefix}: Entire deposit {received_eth} ETH consumed by fee {deposit_fee_eth}. Buyer receives 0 net credit.")
            # ledger_service.credit_funds(buyer, CURRENCY_CODE, Decimal('0.0'), LEDGER_TX_DEPOSIT, external_txid=external_txid, related_order=order, notes=f"{ledger_deposit_notes} (Net Zero after fee)")
            pass # Placeholder

        # Lock funds required for escrow (using expected standard amount)
        # lock_success = ledger_service.lock_funds(buyer, CURRENCY_CODE, expected_eth, related_order=order, notes=f"Lock funds for Order {order.id} ETH escrow")
        lock_success = False # Placeholder
        if not lock_success:
             available = Decimal('0.0') # Placeholder: ledger_service.get_available_balance(buyer, CURRENCY_CODE)
             raise InsufficientFundsError(f"Insufficient available balance ({available}) to lock {expected_eth} ETH for escrow.")

        # Debit locked funds for escrow
        # ledger_service.debit_funds(buyer, CURRENCY_CODE, expected_eth, LEDGER_TX_ESCROW_FUND_DEBIT, related_order=order, external_txid=external_txid, notes=f"Debit funds for Order {order.id} ETH escrow funding")

        # Unlock funds immediately after successful debit
        # unlock_success = ledger_service.unlock_funds(buyer, CURRENCY_CODE, expected_eth, related_order=order, notes=f"Unlock funds after Order {order.id} ETH escrow debit")
        unlock_success = False # Placeholder
        if not unlock_success:
            # This is critical - funds debited but not unlocked, requires manual fix or better atomicity
            raise LedgerError("CRITICAL: Ledger unlock failed after ETH escrow debit.")

        # Raise NotImplementedError if ledger parts are placeholders
        raise NotImplementedError("Ledger updates for ETH payment confirmation are not implemented.")
        # !!! END IMPLEMENTATION REQUIRED for ledger_service !!!


        # Update Order status
        now = timezone.now()
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        # Reset deadlines that start after shipping
        order.dispute_deadline = None
        order.auto_finalize_deadline = None
        order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

        # Update Payment status
        payment.is_confirmed = True
        payment.confirmations_received = confirmations
        payment.received_amount_native = received_atomic # Store Wei
        payment.transaction_hash = external_txid
        payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

        logger.info(f"{log_prefix}: Ledger updated (incl. deposit fee) & Order status -> {OrderStatusChoices.PAYMENT_CONFIRMED}. TXID: {external_txid}")
        security_logger.info(f"Order {order.id} ({CURRENCY_CODE}) payment confirmed & ledger updated (Deposit Fee: {deposit_fee_eth}, Net: {net_deposit_eth}). Buyer: {buyer.username}, Vendor: {getattr(order.vendor,'username','N/A')}. TX: {external_txid}")

        # --- Notify Vendor ---
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
                logger.info(f"{log_prefix}: Sent ETH payment confirmation notification to Vendor {vendor.username}.")
            else:
                logger.error(f"{log_prefix}: Cannot send payment confirmed notification: Vendor missing on order.")
        except NotificationError as notify_e:
             logger.error(f"{log_prefix}: Failed to create payment confirmed notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Unexpected error creating payment notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)

    except NotImplementedError:
        logger.error(f"{log_prefix}: Ledger service calls are not implemented for ETH confirmation.")
        raise EscrowError("Ledger update failed: Service not implemented.")
    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
        logger.critical(f"{log_prefix}: CRITICAL: Ledger/Order atomic update FAILED during ETH payment confirmation! Error: {e}. Transaction potentially rolled back by decorator.", exc_info=True)
        # The @transaction.atomic should handle rollback
        raise # Re-raise the specific critical error
    except Exception as e:
        logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during ledger/order update for confirmed ETH payment: {e}. Transaction potentially rolled back.")
        raise EscrowError(f"Unexpected error confirming ETH payment: {e}") from e

# --- End of Part 1 of Skeleton ---
# <<< Part 2: Continues from ethereum_escrow_service.py Skeleton Part 1 >>>
# REVISIONS:
# - 2025-04-09 (The Void): v1.24.0 - Detailed Skeleton Implementation.
#   - Added detailed structure to mark_order_shipped, sign_order_release, _prepare_eth_release.
#   - Pinpointed ethereum_service/ledger calls needed.
# - ... (Previous revisions omitted) ...

@transaction.atomic
def mark_order_shipped(order: 'Order', vendor: 'UserModel', tracking_info: Optional[str] = None) -> None:
    """
    Marks an ETH order as shipped by the vendor, sets deadlines, notifies the buyer,
    and prepares initial ETH release transaction metadata (e.g., Gnosis Safe Tx parameters)
    by calling _prepare_eth_release.

    Args:
        order: The Order instance to mark shipped (must be ETH).
        vendor: The User performing the action (must be the order's vendor).
        tracking_info: Optional tracking information string.
    Raises:
        ObjectDoesNotExist: If the order is not found.
        PermissionError: If the user is not the vendor.
        ValueError: If currency mismatch, or vendor withdrawal address missing for ETH.
        EscrowError: For invalid state or DB save failures.
        CryptoProcessingError: If preparing the ETH release transaction metadata fails.
        DjangoValidationError: If order data is invalid before saving.
        RuntimeError: If critical models unavailable.
        NotImplementedError: If _prepare_eth_release or its dependencies are not implemented.
    """
    log_prefix = f"Order {order.id} (MarkShipped by {vendor.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting...")

    # --- Input and Dependency Validation ---
    if not all([Order, GlobalSettings, User, ethereum_service, create_notification]): # Added dependencies
        raise RuntimeError("Critical application models or services are not available.")
    if order.selected_currency != CURRENCY_CODE:
        raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")
    if not isinstance(vendor, User) or not vendor.pk:
        raise ValueError("Invalid vendor user object provided.")

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

    # --- Prepare ETH Release Transaction Metadata ---
    prepared_release_metadata: Dict[str, Any]
    try:
        logger.debug(f"{log_prefix}: Preparing initial ETH release metadata...")
        # Call the internal helper which contains the call to ethereum_service
        prepared_release_metadata = _prepare_eth_release(order_locked)

        # Basic validation of the returned metadata structure
        if not isinstance(prepared_release_metadata, dict):
             raise CryptoProcessingError("Internal helper _prepare_eth_release returned invalid data type.")
        if not prepared_release_metadata.get('data'): # 'data' should contain the unsigned tx parameters
             raise CryptoProcessingError("Prepared ETH release metadata is missing the 'data' field.")

        logger.debug(f"{log_prefix}: ETH release metadata prepared successfully.")

    except NotImplementedError:
        logger.error(f"{log_prefix}: Failed to prepare ETH release transaction: Service not implemented.", exc_info=True)
        raise CryptoProcessingError("Failed to prepare ETH release: Service not implemented.")
    except (ValueError, CryptoProcessingError, ObjectDoesNotExist) as prep_err:
        # Catch errors from _prepare_eth_release (like missing addresses)
        logger.error(f"{log_prefix}: Failed to prepare ETH release transaction: {prep_err}", exc_info=True)
        raise # Re-raise specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error preparing ETH release transaction.")
        raise CryptoProcessingError("Unexpected error preparing ETH release transaction.") from e

    # --- Update Order State and Deadlines ---
    now = timezone.now()
    order_locked.status = OrderStatusChoices.SHIPPED
    order_locked.shipped_at = now
    order_locked.release_metadata = prepared_release_metadata # Store the prepared ETH tx params/data
    order_locked.release_initiated = True # Mark that preparation is done
    order_locked.updated_at = now

    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        dispute_days = int(getattr(gs, 'dispute_window_days', 7))
        finalize_days = int(getattr(gs, 'order_auto_finalize_days', 14))
        order_locked.dispute_deadline = now + timedelta(days=dispute_days)
        order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.error(f"{log_prefix}: Error loading GlobalSettings deadlines: {e}. Using defaults.")
        # Use hardcoded defaults if settings fail
        order_locked.dispute_deadline = now + timedelta(days=7)
        order_locked.auto_finalize_deadline = now + timedelta(days=14)

    update_fields = [
        'status', 'shipped_at', 'updated_at', 'dispute_deadline',
        'auto_finalize_deadline', 'release_metadata', 'release_initiated'
    ]

    # Handle tracking info
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
        # Exclude fields that might have complex objects if validation causes issues,
        # but full_clean is generally safer.
        order_locked.full_clean(exclude=None)
        logger.debug(f"{log_prefix}: Validation passed. Saving fields: {update_fields}")

        order_locked.save(update_fields=list(set(update_fields))) # Use set to avoid duplicates
        logger.info(f"{log_prefix}: Marked shipped. Status -> {OrderStatusChoices.SHIPPED}.")
        security_logger.info(f"Order {order_locked.id} marked shipped by Vendor {vendor.username}.")

    except DjangoValidationError as ve:
        logger.error(f"{log_prefix}: Order model validation failed when saving shipping updates: {ve.message_dict}.", exc_info=False)
        raise ve
    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save order shipping updates.")
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
def sign_order_release(order: 'Order', user: 'UserModel', private_key_info: str) -> Tuple[bool, bool]:
    """
    Applies a user's signature (Buyer or Vendor) to the prepared ETH release transaction
    (e.g., signing a Gnosis Safe transaction hash) by calling the ethereum_service.

    Args:
        order: The Order instance being signed (must be ETH).
        user: The User performing the signing (Buyer or Vendor).
        private_key_info: User's private key or reference to a signing mechanism
                          (format specific to ethereum_service, could be WIF, Keystore ref, etc.).
    Returns:
        Tuple[bool, bool]: (signing_successful, is_release_complete)
    Raises:
        ValueError: If inputs are invalid or currency mismatch.
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        EscrowError: For invalid state, metadata issues, or save failures.
        CryptoProcessingError: If ethereum_service signing fails.
        NotImplementedError: If ethereum_service signing function is not implemented.
    """
    log_prefix = f"Order {order.id} (SignRelease by {user.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting ETH signature...")

    # --- Input and Dependency Validation ---
    if not all([Order, User, ethereum_service, create_notification]): # Added dependencies
        raise RuntimeError("Critical application models or services are not available.")
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
    if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")
    # Basic check for key info - real validation depends on ethereum_service needs
    if not private_key_info or not isinstance(private_key_info, str) or len(private_key_info) < 10: # Example check
        raise ValueError("Missing or potentially invalid private key information for ETH.")

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
        raise EscrowError("Order release process has not been initiated (missing prepared tx data).")

    # Allow signing if shipped or even if only confirmed (early finalization)
    allowed_sign_states = [OrderStatusChoices.PAYMENT_CONFIRMED, OrderStatusChoices.SHIPPED]
    if order_locked.status not in allowed_sign_states:
        raise EscrowError(f"Cannot sign ETH release from status '{order_locked.status}'. Expected: {allowed_sign_states}")

    # --- Metadata Validation ---
    current_metadata: Dict[str, Any] = order_locked.release_metadata or {}
    if not isinstance(current_metadata, dict): raise EscrowError("Prepared release metadata missing or invalid.")
    # 'data' might be a dict of params or hash to sign for ETH multisig like Gnosis
    unsigned_tx_data = current_metadata.get('data')
    if not unsigned_tx_data: # Check if it exists and is not empty/None
        raise EscrowError("Prepared transaction data ('data' key) is missing or invalid in release metadata.")

    # --- Check if Already Signed ---
    # Gnosis Safe signatures are typically collected off-chain and submitted together.
    # The 'signatures' map might store who provided their signature data.
    current_sigs: Dict[str, Any] = current_metadata.get('signatures', {})
    if not isinstance(current_sigs, dict): current_sigs = {}

    user_addr_attr = ATTR_ETH_MULTISIG_OWNER_ADDRESS
    user_eth_address = getattr(user, user_addr_attr, None)
    if not user_eth_address:
         # This shouldn't happen if create_escrow worked, but check anyway
         raise EscrowError(f"User {user.username} missing required ETH address ('{user_addr_attr}') for signing.")

    # Use ETH address as key for signatures map
    if user_eth_address in current_sigs:
        # Depending on the flow, re-signing might be allowed to update a signature,
        # or it might indicate an error. Assuming it's not allowed for simplicity here.
        raise EscrowError("You have already signed this release.")

    # --- Ethereum Signing Interaction ---
    # Result structure depends heavily on the multisig implementation (e.g., Gnosis Safe)
    updated_metadata_data: Any = None # Could be updated tx params or just the signature
    is_complete = False
    signature_data: Any = None # What the crypto service returns as proof of signing

    try:
        required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        logger.info(f"{log_prefix}: Calling ethereum_service.sign_eth_multisig_tx...")

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function needs to:
        # 1. Take the unsigned_tx_data (params/hash).
        # 2. Use the user's private_key_info (e.g., private key, keystore access) to generate a signature
        #    valid for the multisig contract (e.g., EIP-712 signature for Gnosis Safe).
        # 3. Return the signature data itself and potentially an updated transaction context if needed.
        # 4. It might determine if the required threshold is met based on other stored signatures (if any).
        # Example return: {'signature': '0x...', 'is_complete': False}
        # sign_result: Dict[str, Any] = ethereum_service.sign_eth_multisig_tx(
        #     multisig_address=getattr(order_locked, ATTR_ETH_ESCROW_ADDRESS), # Pass the contract address
        #     transaction_data=unsigned_tx_data, # The hash or params to sign
        #     private_key_info=private_key_info, # User's key material
        #     # Potentially pass other signatures if needed for completion check inside service:
        #     # existing_signatures=current_sigs
        # )
        raise NotImplementedError("ethereum_service.sign_eth_multisig_tx is not implemented.")

        if not isinstance(sign_result, dict):
            raise CryptoProcessingError("ETH signing function returned invalid result type.")

        signature_data = sign_result.get('signature') # The actual signature generated
        is_complete = sign_result.get('is_complete', False) # Did service determine completion?
        # updated_metadata_data = sign_result.get('updated_tx_data') # Optional: if tx data itself changed

        if not signature_data: # Basic check
             raise CryptoProcessingError("ETH signing function did not return valid signature data.")

        # Store the signature keyed by the user's ETH address
        current_sigs[user_eth_address] = signature_data # Store the signature

        # Recalculate completeness based on the count in our map (defense-in-depth)
        is_complete_calculated = (len(current_sigs) >= required_sigs)
        if is_complete != is_complete_calculated:
            logger.warning(f"{log_prefix}: Discrepancy between ethereum_service completion flag ({is_complete}) and calculated ({is_complete_calculated}). Using calculated.")
            is_complete = is_complete_calculated

        logger.debug(f"{log_prefix}: ETH signing processed. Signatures count: {len(current_sigs)}/{required_sigs}. IsComplete: {is_complete}")

    except NotImplementedError:
        logger.error(f"{log_prefix}: Required ethereum_service signing function is not implemented.")
        raise CryptoProcessingError("ETH signing failed: Service not implemented.")
    except CryptoProcessingError as crypto_err:
        logger.error(f"{log_prefix}: Ethereum signing error: {crypto_err}", exc_info=True)
        raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during Ethereum signing.")
        raise CryptoProcessingError("Unexpected error during ETH signing.") from e

    # --- Update Order Metadata and Save ---
    try:
        fields_to_save = ['updated_at']
        now_iso = timezone.now().isoformat()

        if not isinstance(order_locked.release_metadata, dict): order_locked.release_metadata = {}

        # Update 'data' only if the signing service returned modified tx data
        if updated_metadata_data:
             order_locked.release_metadata['data'] = updated_metadata_data
        # Always update signatures map
        order_locked.release_metadata['signatures'] = current_sigs
        order_locked.release_metadata['ready_for_broadcast'] = is_complete
        order_locked.release_metadata['last_signed_at'] = now_iso
        fields_to_save.append('release_metadata')

        order_locked.updated_at = timezone.now()
        order_locked.save(update_fields=list(set(fields_to_save)))

        logger.info(f"{log_prefix}: ETH signature applied. Current signers: {len(current_sigs)}/{required_sigs}. Ready for broadcast: {is_complete}.")
        security_logger.info(f"Order {order.id} ETH release signed by {user.username} ({user_eth_address}). Ready: {is_complete}.")

        # --- Notify Other Party if Complete (Best Effort) ---
        if is_complete:
             other_party_user: Optional['UserModel'] = None
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
                                f"for ETH release/broadcast. Check the order details.")
                     create_notification(user_id=other_party_user.id, level='info', message=message, link=order_url)
                     logger.info(f"{log_prefix}: Sent 'ready for broadcast' notification to {other_party_role} {other_party_user.username}.")
                 except NotificationError as notify_e:
                     logger.error(f"{log_prefix}: Failed to create 'ready for broadcast' notification for {other_party_role} {other_party_user.id}: {notify_e}", exc_info=True)
                 except Exception as notify_e:
                     logger.error(f"{log_prefix}: Unexpected error creating 'ready for broadcast' notification for {other_party_role} {other_party_user.id}: {notify_e}", exc_info=True)

        return True, is_complete # Return success and readiness

    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save ETH signature updates.")
        raise EscrowError("Failed to save ETH signature updates.") from e


# --- Internal Helper: _prepare_eth_release (Detailed Skeleton) ---
def _prepare_eth_release(order: 'Order') -> Dict[str, Any]:
    """
    Internal helper: Calculates ETH payouts (standard units), gets addresses, calls
    ethereum_service to create initial unsigned release transaction parameters
    (e.g., parameters for a Gnosis Safe `execTransaction` call).
    Stores result in metadata format.

    Args:
        order: The Order instance (must be ETH).
    Returns:
        Dict[str, Any]: A dictionary containing the prepared ETH release metadata.
    Raises:
        ObjectDoesNotExist: If vendor or market user not found.
        ValueError: For calculation errors or missing ETH withdrawal address.
        CryptoProcessingError: If ethereum_service fails to prepare the tx parameters.
        NotImplementedError: If ethereum_service function is not implemented.
    """
    log_prefix = f"Order {order.id} (_prepare_eth_release)"
    logger.debug(f"{log_prefix}: Preparing ETH release metadata (tx parameters)...")

    if order.selected_currency != CURRENCY_CODE:
         raise ValueError("Invalid order currency for _prepare_eth_release.")

    # --- Fetch Participants ---
    vendor = order.vendor
    try:
        market_user = get_market_user()
        if not vendor:
            if order.vendor_id: vendor = User.objects.get(pk=order.vendor_id)
            else: raise ObjectDoesNotExist(f"Vendor relationship missing for order {order.id}")
        if not market_user: raise RuntimeError("Market user cannot be found.")
    except (ObjectDoesNotExist, RuntimeError) as e:
        logger.critical(f"{log_prefix}: Cannot prepare release - participants error: {e}")
        raise

    # --- Get Vendor Withdrawal Address ---
    try:
        # Use the common helper, assumes vendor has ATTR_ETH_WITHDRAWAL_ADDRESS set
        vendor_payout_address = _get_withdrawal_address(vendor, CURRENCY_CODE)
        # TODO: Add validation for ETH address format if not done in _get_withdrawal_address
    except ValueError as e:
        # Raised by _get_withdrawal_address if missing/invalid
        raise ValueError(f"Cannot prepare release: Vendor {vendor.username} missing required {CURRENCY_CODE} withdrawal address.") from e

    # --- Calculate Payouts in Standard ETH ---
    prec = _get_currency_precision(CURRENCY_CODE) # Should be 18 for ETH
    quantizer = Decimal(f'1e-{prec}')
    vendor_payout_eth = Decimal('0.0')
    market_fee_eth = Decimal('0.0')
    total_escrowed_eth = Decimal('0.0')

    try:
        if order.total_price_native_selected is None: raise ValueError("Order total_price_native_selected (Wei) is None.")
        if not isinstance(order.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected (Wei) is not Decimal.")

        # Convert total escrowed (Wei) to standard ETH
        total_escrowed_eth = _convert_atomic_to_standard(order.total_price_native_selected, CURRENCY_CODE, ethereum_service)
        if total_escrowed_eth <= Decimal('0.0'): raise ValueError("Calculated total escrowed ETH amount is zero or negative.")

        # Calculate market fee based on standard ETH amount
        market_fee_percent = _get_market_fee_percentage(CURRENCY_CODE)
        market_fee_eth = (total_escrowed_eth * market_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if market_fee_eth < Decimal('0.0'): market_fee_eth = Decimal('0.0')
        market_fee_eth = min(market_fee_eth, total_escrowed_eth) # Fee cannot exceed total

        # Calculate vendor payout
        vendor_payout_eth = (total_escrowed_eth - market_fee_eth).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_payout_eth < Decimal('0.0'): vendor_payout_eth = Decimal('0.0')

        # Verification Step (optional but recommended)
        sum_check = vendor_payout_eth + market_fee_eth
        tolerance = Decimal(f'1e-{prec-1}') # Allow small rounding diff
        if abs(sum_check - total_escrowed_eth) > tolerance:
             logger.warning(f"{log_prefix}: Payout ({vendor_payout_eth}) + Fee ({market_fee_eth}) = {sum_check} != Total ({total_escrowed_eth}). Check precision/rounding.")

        logger.debug(f"{log_prefix}: Calculated ETH payout: Vendor={vendor_payout_eth}, Fee={market_fee_eth} ({market_fee_percent}%)")

    except (InvalidOperation, ValueError, TypeError, EscrowError) as e:
         # Catch conversion errors too
        raise ValueError("Failed to calculate ETH release payout/fee amounts.") from e

    # --- Call Ethereum Service to Prepare Transaction Parameters ---
    prepared_tx_data: Optional[Dict[str, Any]] = None
    try:
        prepare_func_name = 'prepare_eth_release_tx'
        if not hasattr(ethereum_service, prepare_func_name):
             raise NotImplementedError(f"ethereum_service module missing '{prepare_func_name}'")

        prepare_func = getattr(ethereum_service, prepare_func_name)

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function needs to:
        # 1. Take the order details (especially escrow contract address from order.eth_escrow_address).
        # 2. Take the calculated vendor payout amount (vendor_payout_eth) and address.
        # 3. Construct the transaction parameters necessary for the multisig contract's release function
        #    (e.g., for Gnosis Safe `execTransaction`: `to`, `value`, `data`, `operation`, `safeTxGas`, etc.).
        # 4. It should NOT sign the transaction here.
        # 5. Return a dictionary containing these parameters, suitable for later signing.
        # Example:
        # prepared_tx_data = prepare_func(
        #     multisig_address=getattr(order, ATTR_ETH_ESCROW_ADDRESS),
        #     vendor_payout_amount_eth=vendor_payout_eth, # Pass standard ETH
        #     vendor_address=vendor_payout_address
        #     # Potentially market_fee_eth and market address if fee taken on-chain
        # )
        raise NotImplementedError(f"ethereum_service.{prepare_func_name} is not implemented.")


        if not prepared_tx_data or not isinstance(prepared_tx_data, dict):
            raise CryptoProcessingError(f"Failed to get valid prepared ETH transaction parameters (Result: '{prepared_tx_data}').")

        logger.info(f"{log_prefix}: Successfully prepared ETH transaction parameters.")

    except NotImplementedError:
        logger.error(f"{log_prefix}: Required ethereum_service preparation function is not implemented.")
        raise CryptoProcessingError("ETH release preparation failed: Service not implemented.")
    except CryptoProcessingError as crypto_err:
        raise # Re-raise specific crypto error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error preparing ETH release tx parameters.")
        raise CryptoProcessingError(f"Unexpected error preparing ETH release tx parameters: {e}") from e

    # --- Construct Metadata Dictionary ---
    metadata: Dict[str, Any] = {
        'type': 'eth_multisig_tx_params', # Specific type for ETH (e.g., Gnosis Safe)
        'data': prepared_tx_data, # The dictionary of parameters returned by ethereum_service
        'payout': str(vendor_payout_eth), # Store STANDARD ETH as string
        'fee': str(market_fee_eth),       # Store STANDARD ETH as string
        'vendor_address': vendor_payout_address,
        'ready_for_broadcast': False, # Becomes true after enough signatures
        'signatures': {}, # Store signatures keyed by signer's ETH address
        'prepared_at': timezone.now().isoformat()
    }
    return metadata

# --- End of Part 2 of Skeleton ---
# <<< Part 3: Continues from ethereum_escrow_service.py Skeleton Part 2 >>>
# REVISIONS:
# - 2025-04-09 (The Void): v1.24.0 - Detailed Skeleton Implementation.
#   - Added detailed structure to broadcast_release, resolve_dispute, get_unsigned_release_tx.
#   - Pinpointed ethereum_service/ledger calls needed.
# - ... (Previous revisions omitted) ...

@transaction.atomic
def broadcast_release(order_id: Any) -> bool:
    """
    Finalizes (if needed), broadcasts the fully signed ETH release transaction
    (e.g., executes Gnosis Safe transaction using collected signatures), and updates
    Ledger/Order state upon success. Called by the common escrow dispatcher.

    Args:
        order_id: The ID of the Order (must be ETH) to finalize and broadcast.
    Returns:
        bool: True if broadcast and internal updates were fully successful.
              False if internal updates failed critically after successful broadcast.
    Raises:
        ObjectDoesNotExist: If order not found.
        ValueError: If order currency is not ETH.
        EscrowError: For invalid state or metadata issues.
        CryptoProcessingError: If ethereum_service broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        RuntimeError: If critical dependencies are missing.
        NotImplementedError: If ethereum_service or ledger functions are not implemented.
        PostBroadcastUpdateError: If DB/Ledger updates fail AFTER successful broadcast.
    """
    log_prefix = f"Order {order_id} (BroadcastRelease, Currency: {CURRENCY_CODE}) [broadcast_release]"
    logger.info(f"{log_prefix}: Initiating ETH broadcast...")

    # --- Dependency Check ---
    if not all([ledger_service, Order, User, ethereum_service, create_notification]): # Added deps
        raise RuntimeError("Critical application components are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    market_user_id: Optional[int] = None
    vendor_id: Optional[int] = None
    tx_hash: Optional[str] = None

    try:
        market_user = get_market_user() # Needed for ledger fee update
        market_user_id = market_user.pk
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order_id)

        if order_locked.selected_currency != CURRENCY_CODE:
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        vendor_id = order_locked.vendor_id
        if not vendor_id: raise ObjectDoesNotExist("Vendor missing on order.")

    except ObjectDoesNotExist:
        logger.error(f"{log_prefix}: Order or required related user not found.")
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

    # Check readiness flag (should have been set by the last signer)
    metadata_ready = release_metadata.get('ready_for_broadcast') is True
    if not metadata_ready:
        # Double-check signature count as a fallback
        current_sigs: Dict[str, Any] = release_metadata.get('signatures', {})
        if not isinstance(current_sigs, dict): current_sigs = {}
        required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        has_enough_sigs = len(current_sigs) >= required_sigs
        if has_enough_sigs:
            logger.warning(f"{log_prefix}: Signatures sufficient but 'ready_for_broadcast' flag not True. Proceeding cautiously.")
            release_metadata['ready_for_broadcast'] = True # Correct the flag
        else:
            raise EscrowError(f"Order not ready for broadcast (Flag={metadata_ready}, Sigs={len(current_sigs)}/{required_sigs}).")

    # Check allowed states for broadcasting
    allowed_broadcast_states = [OrderStatusChoices.SHIPPED, OrderStatusChoices.PAYMENT_CONFIRMED]
    if order_locked.status not in allowed_broadcast_states:
        raise EscrowError(f"Cannot broadcast ETH release from status '{order_locked.status}'. Expected: {allowed_broadcast_states}")

    # --- Load Metadata Values (Standard ETH Units) & Transaction Data ---
    try:
        payout_eth_str = release_metadata.get('payout') # Standard ETH from _prepare_eth_release
        fee_eth_str = release_metadata.get('fee')       # Standard ETH from _prepare_eth_release
        # 'data' holds the prepared tx parameters, 'signatures' holds the collected sigs
        tx_params = release_metadata.get('data')
        signatures = release_metadata.get('signatures')

        if tx_params is None or signatures is None or payout_eth_str is None or fee_eth_str is None:
             # Check signatures type as well if needed
            raise ValueError("Missing critical release metadata (data, signatures, payout, fee).")

        payout_eth = Decimal(payout_eth_str)
        fee_eth = Decimal(fee_eth_str)
        if payout_eth < Decimal('0.0') or fee_eth < Decimal('0.0'):
            raise ValueError("Invalid negative values found in payout/fee metadata.")

    except (ValueError, TypeError, InvalidOperation, KeyError) as e:
        raise EscrowError(f"Invalid ETH release metadata format: {e}") from e

    # --- Ethereum Broadcast Interaction ---
    broadcast_success = False
    try:
        logger.info(f"{log_prefix}: Calling ethereum_service to finalize and broadcast ETH tx...")
        broadcast_func_name = 'finalize_and_broadcast_eth_release'
        if not hasattr(ethereum_service, broadcast_func_name):
             raise NotImplementedError(f"ethereum_service module missing '{broadcast_func_name}'")

        broadcast_func = getattr(ethereum_service, broadcast_func_name)

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function needs to:
        # 1. Take the multisig contract address (from order_locked).
        # 2. Take the transaction parameters (`tx_params`).
        # 3. Take the collected signatures (`signatures`).
        # 4. Assemble these into a valid transaction call for the multisig contract
        #    (e.g., Gnosis Safe `execTransaction`).
        # 5. Sign this final transaction with the market's key (if the market is the executor).
        # 6. Broadcast the transaction to the Ethereum network.
        # 7. Wait for confirmation (or handle async confirmation).
        # 8. Return the transaction hash upon successful broadcast and confirmation.
        # Example:
        # tx_hash = broadcast_func(
        #     multisig_address=getattr(order_locked, ATTR_ETH_ESCROW_ADDRESS),
        #     transaction_params=tx_params,
        #     signatures=signatures
        #     # Potentially executor key info if needed
        # )
        raise NotImplementedError(f"ethereum_service.{broadcast_func_name} is not implemented.")


        # Basic check on the returned transaction hash
        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and tx_hash.startswith('0x') and len(tx_hash) == 66
        if not broadcast_success:
            raise CryptoProcessingError(f"Ethereum broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}').")

        logger.info(f"{log_prefix}: ETH Broadcast successful. Transaction Hash: {tx_hash}")

    except NotImplementedError:
         logger.error(f"{log_prefix}: Required ethereum_service broadcast function is not implemented.")
         raise CryptoProcessingError("ETH broadcast failed: Service not implemented.")
    except CryptoProcessingError as crypto_err:
        # Service explicitly indicated a broadcast failure
        logger.error(f"{log_prefix}: Ethereum broadcast failed: {crypto_err}", exc_info=True)
        raise # Re-raise specific crypto error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during ETH broadcast.")
        raise CryptoProcessingError(f"Unexpected ETH broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    try:
        # Re-fetch users for safety
        vendor: Optional['UserModel'] = User.objects.get(pk=vendor_id)
        # market_user already fetched

        now = timezone.now()
        order_locked.status = OrderStatusChoices.FINALIZED
        order_locked.finalized_at = now
        order_locked.release_tx_broadcast_hash = tx_hash # Store the broadcast hash
        order_locked.updated_at = now

        # Update metadata with broadcast info
        release_metadata['broadcast_tx_hash'] = tx_hash
        release_metadata['broadcast_at'] = now.isoformat()
        release_metadata['ready_for_broadcast'] = True # Should already be true, but ensure it
        order_locked.release_metadata = release_metadata

        logger.debug(f"{log_prefix}: Attempting to save order finalization state...")
        order_locked.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'release_metadata', 'updated_at'])
        logger.info(f"{log_prefix}: Order state saved. Proceeding to ledger updates.")

        # --- Update Ledger balances (using STANDARD ETH amounts) ---
        ledger_notes_base = f"Release ETH Order {order_locked.id}, TX: {tx_hash}"

        # !!! IMPLEMENTATION REQUIRED for ledger_service !!!
        # Ensure ledger_service.credit_funds works correctly and atomically.
        if payout_eth > Decimal('0.0'):
            # ledger_service.credit_funds(
            #     user=vendor, currency=CURRENCY_CODE, amount=payout_eth,
            #     transaction_type=LEDGER_TX_ESCROW_RELEASE_VENDOR, related_order=order_locked,
            #     external_txid=tx_hash, notes=f"{ledger_notes_base} Vendor Payout"
            # )
             pass # Placeholder
        if fee_eth > Decimal('0.0'):
            # ledger_service.credit_funds(
            #     user=market_user, currency=CURRENCY_CODE, amount=fee_eth,
            #     transaction_type=LEDGER_TX_MARKET_FEE, related_order=order_locked,
            #     notes=f"Market Fee Order {order_locked.id}" # No ext TXID needed for fee part
            # )
            pass # Placeholder

        # Raise if ledger is placeholder
        raise NotImplementedError("Ledger updates for ETH release are not implemented.")
        # !!! END IMPLEMENTATION REQUIRED for ledger_service !!!

        logger.info(f"{log_prefix}: Ledger updated. Vendor: {payout_eth} {CURRENCY_CODE}, Fee: {fee_eth} {CURRENCY_CODE}.")
        security_logger.info(f"Order {order_locked.id} finalized and released via Ledger. Vendor: {vendor.username}, TX: {tx_hash}")

        # --- Notifications (Best Effort) ---
        try:
            # Notify Vendor
            if vendor:
                order_url = f"/orders/{order_locked.id}"
                product_name = getattr(order_locked.product, 'name', 'N/A')
                order_id_str = str(order_locked.id)
                message = f"Funds released for Order #{order_id_str[:8]} ({product_name}). Payout: {payout_eth} {CURRENCY_CODE}. TX: {tx_hash}"
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

    except NotImplementedError:
         logger.error(f"{log_prefix}: Ledger service calls are not implemented for ETH release.")
         # Raise PostBroadcastUpdateError because broadcast succeeded but ledger failed
         raise PostBroadcastUpdateError(
             message=f"Post-broadcast ledger update failed for ETH release Order {order.id}: Service not implemented.",
             tx_hash=tx_hash
         )
    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as final_db_err:
        # Catch errors during the final user fetch or ledger/order save
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: ETH Broadcast OK (TX: {tx_hash}) but FINAL update FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Raise specific error to signal post-broadcast failure
        raise PostBroadcastUpdateError(
            message=f"Post-broadcast update failed for ETH release Order {order.id}",
            original_exception=final_db_err, tx_hash=tx_hash
        ) from final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: ETH Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Raise specific error to signal post-broadcast failure
        raise PostBroadcastUpdateError(
            message=f"Unexpected post-broadcast error for ETH release Order {order.id}",
            original_exception=final_e, tx_hash=tx_hash
        ) from final_e


@transaction.atomic
def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: int = 0 # Expect int 0-100
) -> bool:
    """
    Resolves an ETH dispute: Calculates split (standard ETH units), prepares/broadcasts
    a multisig transaction via ethereum_service reflecting the split, updates Ledger/Order.

    Args:
        order: The Order instance in dispute (must be ETH).
        moderator: The staff/superuser resolving the dispute.
        resolution_notes: Explanation of the resolution.
        release_to_buyer_percent: Integer percentage (0-100) of escrowed funds
                                  to release to the buyer. Remainder goes to vendor.
    Returns:
        bool: True if resolution (broadcast + internal updates) was fully successful.
              False if internal updates failed critically after successful broadcast.
    Raises:
        ObjectDoesNotExist: If order, buyer, vendor, or market user not found.
        PermissionError: If moderator lacks permissions.
        ValueError: For invalid percentage, notes, currency mismatch, or calculation errors.
        EscrowError: For invalid order state or DB save failures.
        CryptoProcessingError: If ethereum_service broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        RuntimeError: If critical dependencies missing.
        NotImplementedError: If ethereum_service or ledger functions are not implemented.
        PostBroadcastUpdateError: If DB/Ledger updates fail AFTER successful broadcast.
    """
    log_prefix = f"Order {order.id} (ResolveDispute by {moderator.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Attempting ETH resolution. Buyer %: {release_to_buyer_percent}, Notes: '{resolution_notes[:50]}...'")

    # --- Dependency Checks ---
    if not all([ledger_service, Order, User, GlobalSettings, ethereum_service, create_notification]): # Added deps
        raise RuntimeError("Critical application components are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    buyer_id: Optional[int] = None
    vendor_id: Optional[int] = None
    market_user_id: Optional[int] = None
    tx_hash: Optional[str] = None

    try:
        market_user = get_market_user() # Needed for potential fee or ledger ops
        market_user_id = market_user.pk
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order.pk)

        if order_locked.selected_currency != CURRENCY_CODE:
            raise ValueError(f"This service only handles {CURRENCY_CODE} orders.")

        buyer_id = order_locked.buyer_id
        vendor_id = order_locked.vendor_id
        if not buyer_id or not vendor_id: raise ObjectDoesNotExist("Buyer or Vendor missing on order.")

    except (ObjectDoesNotExist, ValueError, RuntimeError) as e:
         raise e # Re-raise specific errors
    except Exception as e:
        raise EscrowError(f"Database/Setup error fetching details for order {order.pk}.") from e


    # --- Input and Permission Validation ---
    if order_locked.status != OrderStatusChoices.DISPUTED:
        raise EscrowError(f"Order must be in '{OrderStatusChoices.DISPUTED}' state to resolve (Current: '{order_locked.status}').")
    if not getattr(moderator, 'is_staff', False) and not getattr(moderator, 'is_superuser', False):
        raise PermissionError("User does not have permission to resolve disputes.")
    if not isinstance(release_to_buyer_percent, int) or not (0 <= release_to_buyer_percent <= 100):
         # Allow int only based on signature
        raise ValueError("Percentage must be an integer between 0 and 100.")
    if not resolution_notes or not isinstance(resolution_notes, str) or len(resolution_notes.strip()) < 5:
        raise ValueError("Valid resolution notes (minimum 5 characters) are required.")
    resolution_notes = resolution_notes.strip()

    # --- Calculate Payout Shares (in STANDARD ETH units) ---
    release_to_vendor_percent = 100 - release_to_buyer_percent
    prec = _get_currency_precision(CURRENCY_CODE)
    quantizer = Decimal(f'1e-{prec}')
    buyer_share_eth = Decimal('0.0')
    vendor_share_eth = Decimal('0.0')
    total_escrowed_eth = Decimal('0.0')

    try:
        if order_locked.total_price_native_selected is None: raise ValueError("Order total_price_native_selected (Wei) is None.")
        if not isinstance(order_locked.total_price_native_selected, Decimal): raise ValueError("Order total_price_native_selected (Wei) is not Decimal.")

        # Convert total escrowed (Wei) to standard ETH
        total_escrowed_eth = _convert_atomic_to_standard(order_locked.total_price_native_selected, CURRENCY_CODE, ethereum_service)
        if total_escrowed_eth <= Decimal('0.0'): raise ValueError("Cannot resolve dispute with zero or negative calculated escrowed ETH amount.")

        # Calculate shares based on percentages
        if release_to_buyer_percent > 0:
            buyer_share_eth = (total_escrowed_eth * Decimal(release_to_buyer_percent) / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
            if buyer_share_eth < Decimal('0.0'): buyer_share_eth = Decimal('0.0')

        # Remainder goes to vendor
        vendor_share_eth = (total_escrowed_eth - buyer_share_eth).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_share_eth < Decimal('0.0'): vendor_share_eth = Decimal('0.0')

        # Verification Step - Ensure sum matches total escrowed, handle potential dust if necessary
        sum_check = buyer_share_eth + vendor_share_eth
        tolerance = Decimal(f'1e-{prec-1}')
        if abs(sum_check - total_escrowed_eth) > tolerance:
            logger.warning(f"{log_prefix}: Dispute Share Calc: Buyer({buyer_share_eth}) + Vendor({vendor_share_eth}) = {sum_check} != Total({total_escrowed_eth}). Dust likely. Adjust logic if needed.")
            # Depending on policy, assign dust to market, vendor, or burn? For now, proceed.

        logger.info(f"{log_prefix}: Calculated ETH Shares - Total: {total_escrowed_eth}, Buyer: {buyer_share_eth}, Vendor: {vendor_share_eth}.")

    except (InvalidOperation, ValueError, TypeError, EscrowError) as e:
        # Catch conversion errors too
        raise ValueError("Failed to calculate ETH dispute payout shares.") from e

    # --- Get Payout Addresses ---
    buyer_payout_address: Optional[str] = None
    vendor_payout_address: Optional[str] = None
    try:
        buyer_obj = order_locked.buyer
        vendor_obj = order_locked.vendor
        if not buyer_obj or not vendor_obj: raise ObjectDoesNotExist("Buyer or Vendor object missing.")

        if buyer_share_eth > Decimal('0.0'):
            buyer_payout_address = _get_withdrawal_address(buyer_obj, CURRENCY_CODE)
        if vendor_share_eth > Decimal('0.0'):
            vendor_payout_address = _get_withdrawal_address(vendor_obj, CURRENCY_CODE)
        # TODO: Validate address formats
    except (ValueError, ObjectDoesNotExist) as e:
        raise ValueError(f"Missing required ETH withdrawal address for dispute payout: {e}") from e

    # --- Ethereum Broadcast Interaction ---
    broadcast_success = False
    try:
        logger.info(f"{log_prefix}: Attempting ETH dispute broadcast...")
        broadcast_func_name = 'create_and_broadcast_dispute_tx'
        if not hasattr(ethereum_service, broadcast_func_name):
             raise NotImplementedError(f"ethereum_service module missing '{broadcast_func_name}'")

        broadcast_func = getattr(ethereum_service, broadcast_func_name)

        # !!! IMPLEMENTATION REQUIRED in ethereum_service !!!
        # This function needs to:
        # 1. Take the multisig contract address.
        # 2. Take the buyer/vendor share amounts (standard ETH) and addresses.
        # 3. Construct the necessary transaction parameters for the multisig contract to execute this split payout.
        #    This might involve multiple transfers or a specific dispute function on the contract.
        # 4. The moderator (or market key) likely needs to sign/authorize this transaction.
        #    The mechanism depends heavily on the multisig contract implementation (e.g., could require moderator signature + threshold).
        # 5. Broadcast the transaction.
        # 6. Return the transaction hash.
        # Example call structure:
        # tx_hash = broadcast_func(
        #     multisig_address=getattr(order_locked, ATTR_ETH_ESCROW_ADDRESS),
        #     moderator_key_info=None, # Pass moderator signing key/info if needed by service
        #     buyer_payout_amount_eth=buyer_share_eth if buyer_payout_address else None,
        #     buyer_address=buyer_payout_address,
        #     vendor_payout_amount_eth=vendor_share_eth if vendor_payout_address else None,
        #     vendor_address=vendor_payout_address
        # )
        raise NotImplementedError(f"ethereum_service.{broadcast_func_name} is not implemented.")

        # Basic check on the returned transaction hash
        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and tx_hash.startswith('0x') and len(tx_hash) == 66
        if not broadcast_success:
            raise CryptoProcessingError(f"Ethereum dispute broadcast failed for Order {order_locked.id} (service returned invalid tx_hash: '{tx_hash}').")

        logger.info(f"{log_prefix}: ETH Dispute transaction broadcast successful. TX: {tx_hash}")

    except NotImplementedError:
        logger.error(f"{log_prefix}: Required ethereum_service dispute broadcast function is not implemented.")
        raise CryptoProcessingError("ETH dispute broadcast failed: Service not implemented.")
    except (CryptoProcessingError, ValueError) as crypto_err: # Catch value errors from service too
        logger.error(f"{log_prefix}: ETH Dispute broadcast error: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"ETH Dispute broadcast error: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during ETH dispute broadcast.")
        raise CryptoProcessingError(f"Unexpected ETH dispute broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    try:
        # Re-fetch users
        buyer: Optional['UserModel'] = User.objects.get(pk=buyer_id)
        vendor: Optional['UserModel'] = User.objects.get(pk=vendor_id)
        # market_user already fetched

        logger.debug(f"{log_prefix}: Entering final update block post-ETH-dispute-broadcast (TX: {tx_hash}).")

        now = timezone.now()
        order_locked.status = OrderStatusChoices.DISPUTE_RESOLVED
        order_locked.release_tx_broadcast_hash = tx_hash # Store the dispute TX hash here
        order_locked.dispute_resolved_at = now
        order_locked.updated_at = now

        update_fields = ['status', 'release_tx_broadcast_hash', 'dispute_resolved_at', 'updated_at']
        # Store resolution details if model fields exist
        if hasattr(order_locked, 'dispute_resolved_by'):
            order_locked.dispute_resolved_by = moderator
            update_fields.append('dispute_resolved_by')
        if hasattr(order_locked, 'dispute_resolution_notes'):
            order_locked.dispute_resolution_notes = resolution_notes[:2000] # Limit length
            update_fields.append('dispute_resolution_notes')
        if hasattr(order_locked, 'dispute_buyer_percent'):
            order_locked.dispute_buyer_percent = release_to_buyer_percent
            update_fields.append('dispute_buyer_percent')

        logger.debug(f"{log_prefix}: Attempting to save final order state (Status: {order_locked.status})...")
        order_locked.save(update_fields=list(set(update_fields)))
        logger.info(f"{log_prefix}: Order state saved successfully. Proceeding to ledger updates.")

        # --- Update Ledger balances (STANDARD ETH units) ---
        notes_base = f"ETH Dispute resolution Order {order_locked.id} by {moderator.username}. TX: {tx_hash}."

        # !!! IMPLEMENTATION REQUIRED for ledger_service !!!
        # Ensure ledger_service.credit_funds works correctly and atomically.
        if buyer_share_eth > Decimal('0.0'):
            # ledger_service.credit_funds(
            #     user=buyer, currency=CURRENCY_CODE, amount=buyer_share_eth,
            #     transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
            #     related_order=order_locked, external_txid=tx_hash,
            #     notes=f"{notes_base} Buyer Share ({release_to_buyer_percent}%)"
            # )
             pass # Placeholder
        if vendor_share_eth > Decimal('0.0'):
            # ledger_service.credit_funds(
            #     user=vendor, currency=CURRENCY_CODE, amount=vendor_share_eth,
            #     transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_VENDOR,
            #     related_order=order_locked, external_txid=tx_hash,
            #     notes=f"{notes_base} Vendor Share ({release_to_vendor_percent}%)"
            # )
             pass # Placeholder
        # Note: Market fee during dispute resolution? Depends on policy. Add if needed.

        # Raise if ledger is placeholder
        raise NotImplementedError("Ledger updates for ETH dispute resolution are not implemented.")
        # !!! END IMPLEMENTATION REQUIRED for ledger_service !!!

        logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_eth}, Vendor: {vendor_share_eth} {CURRENCY_CODE}. TX: {tx_hash}")
        security_logger.info(f"ETH Dispute resolved Order {order_locked.id} by {moderator.username}. Ledger updated. TX: {tx_hash}")

        # --- Notifications (Best Effort) ---
        try:
             # Notify Buyer
             if buyer:
                 order_url = f"/orders/{order_locked.id}"
                 product_name = getattr(order_locked.product,'name','N/A')
                 message = (f"Dispute resolved for Order #{str(order_locked.id)[:8]} ({product_name}). "
                            f"Resolution: {resolution_notes[:100]}... Your share: {buyer_share_eth} {CURRENCY_CODE}. TX: {tx_hash}")
                 create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
             # Notify Vendor
             if vendor:
                 order_url = f"/orders/{order_locked.id}"
                 product_name = getattr(order_locked.product,'name','N/A')
                 message = (f"Dispute resolved for Order #{str(order_locked.id)[:8]} ({product_name}). "
                            f"Resolution: {resolution_notes[:100]}... Your share: {vendor_share_eth} {CURRENCY_CODE}. TX: {tx_hash}")
                 create_notification(user_id=vendor.id, level='info', message=message, link=order_url)
        except NotificationError as notify_e:
            logger.error(f"{log_prefix}: Failed to send dispute resolution notification: {notify_e}", exc_info=True)
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Unexpected error sending dispute resolution notification: {notify_e}", exc_info=True)

        logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
        return True

    except NotImplementedError:
         logger.error(f"{log_prefix}: Ledger service calls are not implemented for ETH dispute resolution.")
         # Raise PostBroadcastUpdateError because broadcast succeeded but ledger failed
         raise PostBroadcastUpdateError(
             message=f"Post-broadcast ledger update failed for ETH dispute resolution Order {order.id}: Service not implemented.",
             tx_hash=tx_hash
         )
    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as final_db_err:
        # Catch errors during final user fetch or ledger/order save
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: ETH Dispute Broadcast OK (TX: {tx_hash}) but FINAL update FAILED. Error: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
            message=f"Post-broadcast update failed for ETH dispute resolution Order {order.id}",
            original_exception=final_db_err, tx_hash=tx_hash
        ) from final_db_err
    except Exception as final_e:
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: ETH Dispute Broadcast OK (TX: {tx_hash}) but unexpected error during final update. Error: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        raise PostBroadcastUpdateError(
             message=f"Unexpected post-broadcast error for ETH dispute resolution Order {order.id}",
             original_exception=final_e, tx_hash=tx_hash
        ) from final_e


def get_unsigned_release_tx(order: 'Order', user: 'UserModel') -> Optional[Dict[str, Any]]:
    """
    Retrieves the currently stored unsigned/partially signed ETH transaction data
    (e.g., Gnosis Safe transaction parameters or hash to sign) from the order's
    release_metadata for offline signing by the specified user.

    Args:
        order: The Order instance (must be ETH).
        user: The User requesting the data (must be buyer or vendor).
    Returns:
        A dictionary containing {'unsigned_tx': tx_data} if successful, where tx_data
        is the parameters or hash needed for signing. Returns None if no data found (or raises).
    Raises:
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        ValueError: If currency mismatch or invalid input objects.
        EscrowError: For invalid state, missing/invalid metadata.
        RuntimeError: If critical models unavailable.
    """
    log_prefix = f"Order {order.id} (GetUnsignedTx for {user.username}, Currency: {CURRENCY_CODE})"
    logger.info(f"{log_prefix}: Request received for ETH unsigned transaction data.")

    # --- Input and Dependency Validation ---
    if not all([Order, User]): raise RuntimeError("Critical application models unavailable.")
    if not isinstance(order, Order) or not order.pk: raise ValueError("Invalid Order object.")
    if not isinstance(user, User) or not user.pk: raise ValueError("Invalid User object.")
    if order.selected_currency != CURRENCY_CODE: raise ValueError(f"Order currency is not {CURRENCY_CODE}.")

    # --- Fetch Fresh Order Data ---
    try:
        # No need to lock for read-only operation
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
        raise EscrowError("Release process has not been initiated for this order (no prepared data).")

    release_metadata: Dict[str, Any] = order_fresh.release_metadata or {}
    if not isinstance(release_metadata, dict):
        raise EscrowError("Release metadata is missing or invalid.")

    # Extract the data prepared for signing
    unsigned_tx_data = release_metadata.get('data')
    release_type = release_metadata.get('type') # e.g., 'eth_multisig_tx_params'

    # Validate type and data existence
    expected_type = 'eth_multisig_tx_params' # Match the type set in _prepare_eth_release
    if release_type != expected_type:
        logger.error(f"{log_prefix}: Release metadata type is '{release_type}', expected '{expected_type}'.")
        raise EscrowError("Release metadata type mismatch for ETH unsigned transaction request.")

    if not unsigned_tx_data: # Check for None or empty
        logger.error(f"{log_prefix}: Release metadata unsigned transaction data ('data') is missing or empty.")
        raise EscrowError("Release metadata unsigned transaction data ('data') is missing or invalid.")

    # Log if the requesting user has already signed
    already_signed = False
    user_eth_address = getattr(user, ATTR_ETH_MULTISIG_OWNER_ADDRESS, None)
    if 'signatures' in release_metadata and isinstance(release_metadata['signatures'], dict):
         if user_eth_address and user_eth_address in release_metadata['signatures']:
             already_signed = True
             logger.info(f"{log_prefix}: User {user.username} ({user_eth_address}) has already signed this ETH release according to metadata.")

    logger.info(f"{log_prefix}: Returning prepared ETH transaction data for signing. Already Signed: {already_signed}")

    # Return the data needed for signing (could be a dict, hash string, etc.)
    return {'unsigned_tx': unsigned_tx_data}


# <<< END OF FILE: backend/store/services/ethereum_escrow_service.py >>>