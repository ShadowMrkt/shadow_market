# backend/store/tasks.py
# --- Revision History ---
# [Rev 1.7 - 2025-04-12] Gemini
#   - FIXED: Potential Bandit parsing error by correcting the definition of the
#     dummy `GlobalSettings` class in the `except ImportError` block to define
#     `DoesNotExist` in the class body.
# [Rev 1.6 - 2025-04-13] Gemini
#   - FIXED: Potential Bandit parsing error by correcting the type hint for
#     `scan_service_func` in `_perform_deposit_check` from lowercase `callable`
#     to `typing.Callable`. Ensured `Callable` is imported.
# [Rev 1.5 - 2025-04-13] Gemini
#   - FIXED: Potential Bandit parsing error by simplifying complex conditional
#     exception handling in `get_last_checked_block` function.
# [Rev 1.4 - 2025-04-13] Gemini
#   - FIXED: Bandit parsing error by simplifying dummy class/constant definitions
#     within the `except ImportError` block for better AST compatibility.
# [Rev 1.3 - 2025-04-12] Gemini
#   - FIXED: Bandit parsing error by commenting out call to undefined function `log_audit_event`
#     in `_perform_deposit_check`. Added FIXME comment advising user to import/define it correctly.
# [Rev 1.2 - 2025-04-10] Gemini
#   - IMPLEMENTED: Detailed logic within `_perform_deposit_check`...
# [Rev 1.1 - 2025-04-09] The Void
#   - ADDED: `update_exchange_rates_task`...
# [Rev 1.0 - 2025-04-07] The Void
#   - Added Distributed Locking...
# ------------------------

"""
Celery tasks for the store application.
# ... (rest of docstring remains the same) ...
"""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation # Ensure Decimal is imported
from functools import wraps
# Import Callable for type hinting
from typing import Optional, Dict, Any, List, Callable

from celery import shared_task, Task
from celery.exceptions import Ignore
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist
from django.db import transaction, IntegrityError, DatabaseError
from django.utils import timezone

# --- Third-Party Imports ---
try:
    import redis_lock
except ImportError:
    redis_lock = None

try:
    import requests
    CONNECTION_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
except ImportError:
    CONNECTION_ERRORS = ()

TRANSIENT_DB_ERRORS = (DatabaseError,) # Add other relevant DB errors if needed

# --- Constants ---
# ... (Constants remain the same) ...
CURRENCY_XMR = 'XMR'
CURRENCY_BTC = 'BTC'
CURRENCY_ETH = 'ETH'
DEFAULT_SUPPORTED_CURRENCIES = [CURRENCY_XMR, CURRENCY_BTC, CURRENCY_ETH]
LEDGER_TRANSACTION_TYPE_DEPOSIT = 'DEPOSIT'
LEDGER_TRANSACTION_TYPE_ESCROW_FUND = 'ESCROW_FUND'
SETTING_KEY_LAST_CHECKED_BLOCK_PATTERN = "last_checked_{currency}_height"
SETTING_KEY_SUPPORTED_CURRENCIES = "SUPPORTED_CURRENCIES"
SETTING_BTC_CONFS_NEEDED = 'BITCOIN_CONFIRMATIONS_NEEDED'
SETTING_XMR_CONFS_NEEDED = 'MONERO_CONFIRMATIONS_NEEDED'
SETTING_ETH_CONFS_NEEDED = 'ETHEREUM_CONFIRMATIONS_NEEDED'
TASK_DEFAULT_TIME_LIMIT = 600
TASK_DEFAULT_SOFT_TIME_LIMIT = 580
TASK_DEPOSIT_CHECK_TIME_LIMIT = 300
TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT = 290
TASK_REPUTATION_TIME_LIMIT = 1800
TASK_REPUTATION_SOFT_TIME_LIMIT = 1780
TASK_EXCHANGE_RATE_TIME_LIMIT = 120
TASK_EXCHANGE_RATE_SOFT_TIME_LIMIT = 110
TASK_RETRY_DELAY = 60
TASK_MAX_RETRIES = 3
LOCK_ACQUIRE_TIMEOUT = 10
LOCK_EXPIRY_BUFFER = 60
DEPOSIT_LOCK_EXPIRY = TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT + LOCK_EXPIRY_BUFFER
DEPOSIT_LOCK_KEY_PATTERN = "lock_check_{currency}_deposits"
RATES_LOCK_EXPIRY = TASK_EXCHANGE_RATE_SOFT_TIME_LIMIT + LOCK_EXPIRY_BUFFER
RATES_LOCK_KEY = "lock_update_exchange_rates"
ATOMIC_FACTOR = {
    'BTC': Decimal('100000000'),
    'ETH': Decimal('1000000000000000000'),
    'XMR': Decimal('1000000000000'),
}


# --- Logging Setup ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Import Application Modules ---
try:
    from store.models import (
        CryptoPayment, Order, User, GlobalSettings, VendorApplication, Currency,
        ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PAYMENT_CONFIRMED, # Order statuses
        VENDOR_APP_STATUS_PENDING_BOND, VENDOR_APP_STATUS_PENDING_REVIEW, # App statuses
        # Import missing Order statuses used in auto_finalize_paid_orders
        ORDER_STATUS_SHIPPED, ORDER_STATUS_DISPUTED, ORDER_STATUS_FINALIZED,
        ORDER_STATUS_CANCELLED_TIMEOUT, ORDER_STATUS_CANCELLED_BUYER,
        ORDER_STATUS_CANCELLED_VENDOR, ORDER_STATUS_CANCELLED_UNDERPAID,
        ORDER_STATUS_REFUNDED,
    )
    # Correct way to access StatusChoices if defined within the model
    # OrderStatusChoices = Order.StatusChoices
    # VendorAppStatusChoices = VendorApplication.StatusChoices

    from ledger.models import LedgerTransaction
    from store.services import (
        monero_service, bitcoin_service, ethereum_service,
        escrow_service, reputation_service, exchange_rate_service
    )
    from ledger import services as ledger_service
    from ledger.services import InsufficientFundsError
    # Import notification service
    from notifications import services as notification_service
    # If log_audit_event is defined elsewhere, import it here:
    # from common.audit import log_audit_event # FIXME: Uncomment and adjust path

    _required_services = {
        "monero_service": monero_service, "bitcoin_service": bitcoin_service,
        "ethereum_service": ethereum_service, "escrow_service": escrow_service,
        "reputation_service": reputation_service, "ledger_service": ledger_service,
        "exchange_rate_service": exchange_rate_service,
        "notification_service": notification_service, # Now required for app notifications
    }
    for name, service in _required_services.items():
        if service is None:
            raise ImportError(f"Service '{name}' is None or not imported correctly.")

    MODELS_SERVICES_LOADED = True
except ImportError as e:
    logger.critical(
        f"CRITICAL IMPORT ERROR in store/tasks.py: {e}. "
        f"Tasks depending on these imports will fail.",
        exc_info=True
    )
    MODELS_SERVICES_LOADED = False
    # Define simpler dummies for parsing if imports fail
    class VendorApplication: pass
    class Order: pass
    class CryptoPayment: pass
    # --- Corrected Dummy GlobalSettings (Rev 1.7) ---
    class GlobalSettings:
        # Define DoesNotExist within the class body if needed by other logic in this block
        DoesNotExist = ObjectDoesNotExist
        @staticmethod
        def load():
             return None
    # --- End Corrected Dummy ---
    class Currency: pass
    class LedgerTransaction: pass
    class User: pass # Add User dummy if needed

    # Dummy constants
    VENDOR_APP_STATUS_PENDING_BOND = 'pending_bond'
    VENDOR_APP_STATUS_PENDING_REVIEW = 'pending_review'
    ORDER_STATUS_PENDING_PAYMENT = 'pending_payment'
    ORDER_STATUS_PAYMENT_CONFIRMED = 'payment_confirmed'
    ORDER_STATUS_SHIPPED = 'shipped'
    ORDER_STATUS_DISPUTED = 'disputed'
    ORDER_STATUS_FINALIZED = 'finalized'
    ORDER_STATUS_CANCELLED_TIMEOUT = 'cancelled_timeout'
    ORDER_STATUS_CANCELLED_BUYER = 'cancelled_buyer'
    ORDER_STATUS_CANCELLED_VENDOR = 'cancelled_vendor'
    ORDER_STATUS_CANCELLED_UNDERPAID = 'cancelled_underpaid'
    ORDER_STATUS_REFUNDED = 'refunded'

    # Dummy services
    bitcoin_service = None; monero_service = None; ethereum_service = None
    escrow_service = None; reputation_service = None; exchange_rate_service = None
    ledger_service = None; notification_service = None
    InsufficientFundsError = Exception
    # Define dummy audit log function to prevent NameError during parsing
    def log_audit_event(*args, **kwargs): pass


# --- Helper Functions ---

def get_last_checked_block(currency_code: str) -> int:
    """ Safely retrieves the last checked block height for a currency. """
    if not MODELS_SERVICES_LOADED: return 0 # Cannot proceed if imports failed
    setting_name = SETTING_KEY_LAST_CHECKED_BLOCK_PATTERN.format(
        currency=currency_code.lower()
    )
    try:
        gs = GlobalSettings.load()
        if not gs:
            # If load() returns None or raises its own error handled below
            raise GlobalSettings.DoesNotExist("GlobalSettings not loaded")

        height = getattr(gs, setting_name, 0)
        return int(height) if height is not None else 0

    # --- Simplified Exception Handling (Rev 1.5) ---
    except GlobalSettings.DoesNotExist: # Explicitly catch DoesNotExist if defined
        logger.warning(f"GlobalSettings record not found. Cannot get last checked block for {currency_code}. Returning 0.")
        return 0
    except AttributeError: # Catch if gs is None or missing the height field
         logger.error(f"Error accessing GlobalSettings or attribute '{setting_name}' for {currency_code}.", exc_info=True)
         return 0
    except (TypeError, ValueError) as e: # Catch parsing errors
        logger.error(
            f"Error parsing setting '{setting_name}' for {currency_code}: {e}. Returning 0.",
            exc_info=True
        )
        return 0
    except Exception as e: # Catch any other unexpected errors
        logger.exception(f"Unexpected error getting last checked block for {currency_code}: {e}")
        return 0

def set_last_checked_block(currency_code: str, height: Optional[int]):
    """ Atomically sets the last checked block height, ensuring it only increases. """
    if not MODELS_SERVICES_LOADED: return # Cannot proceed if imports failed
    if height is None:
        logger.warning(f"Attempted to set last checked block for {currency_code} with None height. Skipping.")
        return
    try:
        height = int(height)
        if height < 0:
            logger.warning(f"Attempted to set invalid negative block height ({height}) for {currency_code}. Skipping.")
            return
    except (ValueError, TypeError):
        logger.error(f"Invalid non-integer height '{height}' provided for {currency_code}. Cannot set.")
        return

    setting_name = SETTING_KEY_LAST_CHECKED_BLOCK_PATTERN.format(
        currency=currency_code.lower()
    )

    try:
        with transaction.atomic():
            gs = GlobalSettings.objects.select_for_update().first() # Use first() assuming singleton
            if not gs:
                logger.error(f"GlobalSettings record not found. Cannot set last checked block for {currency_code}.")
                return # Fail if cannot create or find

            if not hasattr(gs, setting_name):
                logger.error(f"GlobalSettings model instance is missing the field '{setting_name}'. Cannot set last checked block for {currency_code}.")
                return

            current_height = getattr(gs, setting_name, 0) or 0

            if height >= current_height:
                setattr(gs, setting_name, height)
                gs.save(update_fields=[setting_name])
                logger.info(f"Updated last checked block for {currency_code}: {current_height} -> {height}")
            else:
                logger.info(f"No update needed for {currency_code} block height (New: {height} <= Current: {current_height})")

    except Exception as e:
        logger.exception(f"Error setting last checked block {currency_code} to {height}: {e}")


# --- Decorator for Task Dependency Checks ---
def check_dependencies(*services_to_check):
    """ Decorator to check if required services/modules are available. """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            task_instance = args[0] if args and isinstance(args[0], Task) else None
            task_id = task_instance.request.id if task_instance and hasattr(task_instance, 'request') else 'N/A'

            # Check overall import status first
            if not MODELS_SERVICES_LOADED:
                error_msg = f"Task {func.__name__} ({task_id}) aborted: Critical imports failed during module load. Check logs."
                logger.critical(error_msg)
                return "Task Aborted: Critical imports failed."

            missing = []
            for service_name in services_to_check:
                if service_name == 'redis_lock' and redis_lock is None:
                    missing.append("redis_lock (python library 'django-redis-lock' likely not installed)")
                    continue
                # Check if service exists and is not None in the global scope of this module
                service_obj = globals().get(service_name)
                is_dummy_service = service_name in ['bitcoin_service', 'monero_service', 'ethereum_service', 'escrow_service', 'reputation_service', 'exchange_rate_service', 'ledger_service', 'notification_service'] and service_obj is None
                is_dummy_model_class = isinstance(service_obj, type) and service_obj.__module__ == __name__ # Checks if class defined in this file (likely a dummy)

                # Mark as missing if it's a required service that didn't load, or a critical model/class that is just a dummy placeholder
                if is_dummy_service or (service_name in ['Order', 'VendorApplication', 'GlobalSettings', 'CryptoPayment', 'LedgerTransaction', 'User'] and is_dummy_model_class):
                     missing.append(f"{service_name} (not loaded/dummy)")

            if missing:
                error_msg = f"Task {func.__name__} ({task_id}) aborted: Missing critical dependencies: {', '.join(missing)}."
                logger.critical(error_msg)
                return f"Task Aborted: Missing dependencies ({', '.join(missing)})"
            return func(*args, **kwargs)
        return wrapper
    return decorator


# --- Celery Tasks ---

@shared_task(
    name="auto_finalize_paid_orders",
    time_limit=TASK_DEFAULT_TIME_LIMIT,
    soft_time_limit=TASK_DEFAULT_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5,
    retry_jitter=True
)
@check_dependencies('Order', 'escrow_service')
def auto_finalize_paid_orders(self: Task):
    """
    Auto-finalizes orders past their deadline via the escrow service.
    Retries on transient errors. Logs errors per order but completes task unless critical error occurs.
    """
    task_id = self.request.id
    log_prefix = f"[AutoFinalize:{task_id}]"
    logger.info(f"{log_prefix} Starting task.")
    now = timezone.now()

    # Use imported constants
    shipped_status = ORDER_STATUS_SHIPPED
    excluded_statuses = [
        ORDER_STATUS_DISPUTED, ORDER_STATUS_FINALIZED,
        ORDER_STATUS_CANCELLED_TIMEOUT, ORDER_STATUS_CANCELLED_BUYER,
        ORDER_STATUS_CANCELLED_VENDOR, ORDER_STATUS_CANCELLED_UNDERPAID,
        ORDER_STATUS_REFUNDED,
    ]

    eligible_orders = Order.objects.filter(
        status=shipped_status,
        auto_finalize_deadline__isnull=False,
        auto_finalize_deadline__lte=now
    ).exclude(status__in=excluded_statuses)

    order_count = 0
    processed_success_count = 0
    broadcast_success_count = 0
    failed_initiation_count = 0
    failed_broadcast_count = 0
    needs_review_sig_count = 0
    unexpected_error_count = 0

    for order in eligible_orders.iterator():
        order_count += 1
        logger.info(f"{log_prefix} Processing Order {order.id}...")
        try:
            order_finalized_in_run = False

            # Assuming escrow_service.finalize_order handles the logic of
            # preparing, signing (if needed by market), and broadcasting atomically
            # or flags the order for later broadcast if signatures are missing.
            if not order.release_initiated: # Check if already started
                logger.info(f"{log_prefix} Initiating release for Order {order.id}...")
                # Call service, expect it to handle preparing tx, adding market sig if needed
                finalize_result = escrow_service.finalize_order(order, user=None, is_auto_finalize=True)
                # Service should return True on success (even if broadcast pending sigs), False on state error, raise on system error
                if not finalize_result:
                    logger.error(f"{log_prefix} Failed to initiate/prepare release for Order {order.id}. Check status or previous logs.")
                    failed_initiation_count += 1
                    continue
                order.refresh_from_db() # Get latest state after service call

            # Now check if it's ready for broadcast (might have been finalized by service)
            # Need a reliable way to check if TX is ready and not yet broadcast
            # Use constants for status checks
            if order.status == ORDER_STATUS_FINALIZED and not order.release_txid: # Example check
                logger.warning(f"{log_prefix} Order {order.id} is FINALIZED but missing release_txid. Requires review.")
                # This state should ideally be handled by the service or broadcast task
                failed_broadcast_count += 1 # Or a different counter?
            elif order.release_initiated and not order.release_txid: # Check if ready for broadcast
                # Check signature status if applicable (depends on escrow_service design)
                # Assuming escrow_service handles checking/broadcasting if ready
                logger.info(f"{log_prefix} Order {order.id} release initiated, checking broadcast status...")
                broadcast_successful = escrow_service.broadcast_release_transaction(order) # Service attempts broadcast if ready
                if broadcast_successful:
                    logger.info(f"{log_prefix} Successfully broadcast release for Order {order.id}.")
                    broadcast_success_count += 1
                    order_finalized_in_run = True
                else:
                    # Service logs why broadcast failed (e.g., missing sigs, RPC error)
                    logger.warning(f"{log_prefix} Broadcast attempt failed or not ready for Order {order.id}. Service logs should have details.")
                    # Count based on whether it *should* have been ready
                    # This part needs refinement based on escrow_service capabilities
                    if order.status != ORDER_STATUS_FINALIZED: # Assuming FINALIZED means TX sent/confirmed
                        needs_review_sig_count += 1 # Assume missing sigs if not FINALIZED
                    else:
                        failed_broadcast_count +=1 # Assume broadcast failure if FINALIZED but no TXID

            elif order.status == ORDER_STATUS_FINALIZED and order.release_txid:
                logger.info(f"{log_prefix} Order {order.id} already finalized and broadcast.")
                # Don't count as success *in this run*, but it's okay.
            else:
                logger.warning(f"{log_prefix} Order {order.id} in unexpected state for auto-finalize. Status: {order.status}, Release Initiated: {order.release_initiated}, TXID: {order.release_txid}")
                unexpected_error_count +=1 # Count as unexpected state

            if order_finalized_in_run:
                processed_success_count += 1

        except (*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS) as transient_err:
            logger.warning(f"{log_prefix} Transient error processing Order {order.id}: {transient_err}. Task will retry if attempts remain.")
            raise transient_err
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error processing Order {order.id}: {e}")
            unexpected_error_count += 1

    summary_parts = [
        f"Auto-finalize task ({task_id}) finished.",
        f"Checked: {order_count}.",
        f"Successfully Broadcast/Finalized: {broadcast_success_count}.", # Renamed counter
    ]
    if failed_initiation_count > 0: summary_parts.append(f"Failed Initiations: {failed_initiation_count}.")
    if failed_broadcast_count > 0: summary_parts.append(f"Failed Broadcasts: {failed_broadcast_count}.")
    if needs_review_sig_count > 0: summary_parts.append(f"Needs Review (Not Ready): {needs_review_sig_count}.")
    if unexpected_error_count > 0: summary_parts.append(f"Unexpected Errors/States: {unexpected_error_count}.")

    summary = " ".join(summary_parts)
    if failed_initiation_count > 0 or failed_broadcast_count > 0 or needs_review_sig_count > 0 or unexpected_error_count > 0:
        logger.warning(f"{log_prefix} {summary} - ATTENTION NEEDED FOR FAILURES/REVIEWS.")
    else:
        logger.info(f"{log_prefix} {summary}")
    return summary


@shared_task(
    name="check_all_deposits",
    time_limit=TASK_DEFAULT_TIME_LIMIT,
    soft_time_limit=TASK_DEFAULT_SOFT_TIME_LIMIT,
    bind=True
)
def check_all_deposits(self: Task):
    """ Meta-task triggering individual deposit checks for supported currencies. """
    if not MODELS_SERVICES_LOADED: return "Task Failed: Critical imports failed."

    task_id = self.request.id
    log_prefix = f"[CheckAllDeposits:{task_id}]"
    logger.info(f"{log_prefix} Triggering deposit checks...")

    currencies_to_check = getattr(settings, SETTING_KEY_SUPPORTED_CURRENCIES, DEFAULT_SUPPORTED_CURRENCIES)
    results: Dict[str, str] = {}

    logger.info(f"{log_prefix} Will queue checks for: {', '.join(currencies_to_check)}")

    for currency in currencies_to_check:
        currency_lower = currency.lower()
        # Standardize task naming convention
        specific_task_name = f"store.tasks.check_{currency_lower}_deposits"
        try:
            # Get task signature by name
            task_signature = shared_task(name=specific_task_name)
            # Queue the task instance
            async_result = task_signature.delay() # Use delay() for simplicity
            results[currency] = f"Task Queued (ID: {async_result.id})"
            logger.info(f"{log_prefix} Queued task '{specific_task_name}' with ID: {async_result.id}")
        except Exception as e:
            error_msg = f"Failed to queue task '{specific_task_name}'"
            logger.exception(f"{log_prefix} {error_msg}: {e}")
            results[currency] = f"Task Queueing Failed ({type(e).__name__})"

    summary = f"Deposit check tasks queuing process finished. Status: {results}"
    logger.info(f"{log_prefix} {summary}")
    return summary


# --- Individual Currency Deposit Check Task Function (Helper) ---
def _perform_deposit_check(
    task_instance: Task,
    currency_code: str,
    scan_service_func: Callable # Use typing.Callable
):
    """
    Internal helper to perform deposit check logic with distributed locking.
    Processes both Order and Vendor Bond deposits based on payment_type.
    """
    task_id = task_instance.request.id
    log_prefix = f"[Check{currency_code.upper()}Deposits:{task_id}]"

    if not MODELS_SERVICES_LOADED:
        logger.critical(f"{log_prefix} Aborting: Models/Services not loaded.")
        return # Abort gracefully

    if redis_lock is None:
        logger.critical(f"{log_prefix} Aborting task: 'django-redis-lock' library not available.")
        return # Abort gracefully

    lock_key = DEPOSIT_LOCK_KEY_PATTERN.format(currency=currency_code.lower())
    lock = None

    try:
        logger.info(f"{log_prefix} Attempting to acquire lock: {lock_key}")
        lock = redis_lock.Lock(
            _redis=None, name=lock_key, expire=DEPOSIT_LOCK_EXPIRY, id=task_id, auto_renewal=False
        )

        if not lock.acquire(blocking=False):
            logger.warning(f"{log_prefix} Lock '{lock_key}' already held. Waiting up to {LOCK_ACQUIRE_TIMEOUT}s...")
            if not lock.acquire(blocking=True, timeout=LOCK_ACQUIRE_TIMEOUT):
                logger.warning(f"{log_prefix} Could not acquire lock '{lock_key}' after waiting. Skipping this run.")
                raise Ignore()

        logger.info(f"{log_prefix} Successfully acquired lock: {lock_key}")

        # --- Core Deposit Check Logic (inside the lock) ---
        logger.info(f"{log_prefix} Starting deposit check logic.")
        new_max_height_processed = 0
        processed_orders = 0
        processed_bonds = 0
        skipped_existing = 0
        skipped_invalid = 0
        failed_processing = 0

        try:
            new_payments: List[Dict[str, Any]] = scan_service_func()
            logger.info(f"{log_prefix} Scan function returned {len(new_payments)} potential deposits.")

            for payment_info in new_payments:
                txid = payment_info.get('txid')
                address = payment_info.get('address')
                amount_atomic_val = payment_info.get('amount_atomic')
                payment_type = payment_info.get('payment_type')
                related_id = payment_info.get('related_id')
                confirmations = payment_info.get('confirmations', 0)

                # --- Basic Validation ---
                if not all([txid, address, amount_atomic_val is not None, payment_type, related_id is not None]):
                    logger.warning(f"{log_prefix} Incomplete payment info skipped: {payment_info}")
                    skipped_invalid += 1
                    continue
                try:
                    amount_atomic = int(amount_atomic_val)
                    if amount_atomic <= 0:
                        logger.info(f"{log_prefix} Skipping zero/negative atomic amount: {payment_info}")
                        skipped_invalid += 1
                        continue
                except (ValueError, TypeError):
                    logger.warning(f"{log_prefix} Invalid atomic amount format ('{amount_atomic_val}') skipped: {payment_info}")
                    skipped_invalid += 1
                    continue

                height = payment_info.get('block_height')
                if height is not None and height > new_max_height_processed:
                   new_max_height_processed = height

                # --- Process based on Payment Type ---
                if payment_type == 'vendor_bond':
                    app_id = related_id
                    app_log_prefix = f"{log_prefix}[App:{app_id}|TX:{txid[:8]}]"
                    try:
                        with transaction.atomic():
                            try:
                                app = VendorApplication.objects.select_for_update().get(pk=app_id)
                            except VendorApplication.DoesNotExist:
                                logger.info(f"{app_log_prefix} VendorApplication not found. Skipping.")
                                continue

                            if txid in getattr(app, 'payment_txids', []):
                                logger.info(f"{app_log_prefix} TXID already processed for this application. Skipping.")
                                skipped_existing += 1
                                continue

                            if app.status != VENDOR_APP_STATUS_PENDING_BOND:
                                logger.info(f"{app_log_prefix} Application not in PENDING_BOND status ({app.status}). Skipping.")
                                continue

                            required_atomic: Optional[int] = None
                            try:
                                if app.bond_amount_crypto and app.bond_currency_chosen == currency_code:
                                    factor = ATOMIC_FACTOR.get(currency_code)
                                    if factor:
                                        required_atomic = int((app.bond_amount_crypto * factor).to_integral_value())
                            except Exception as conv_err:
                                logger.error(f"{app_log_prefix} Error converting stored bond amount {app.bond_amount_crypto} to atomic: {conv_err}")

                            if required_atomic is None or required_atomic <= 0:
                                logger.warning(f"{app_log_prefix} Required bond amount not found/convertible/valid on App model ({required_atomic}). Cannot verify payment.")
                                failed_processing += 1
                                continue

                            min_confs_needed = getattr(settings, SETTING_BTC_CONFS_NEEDED, 1)
                            if confirmations < min_confs_needed:
                                logger.info(f"{app_log_prefix} Deposit has {confirmations}/{min_confs_needed} confirmations. Waiting.")
                                continue

                            if amount_atomic >= required_atomic:
                                if amount_atomic > required_atomic:
                                    overpaid = amount_atomic - required_atomic
                                    logger.warning(f"{app_log_prefix} Overpayment detected by {overpaid} atomic units.")

                                app.status = VENDOR_APP_STATUS_PENDING_REVIEW
                                app.bond_paid_atomic = amount_atomic
                                app.bond_paid_txid = txid
                                app.bond_paid_confirmations = confirmations
                                app.paid_at = timezone.now()
                                if hasattr(app, 'payment_txids') and isinstance(app.payment_txids, list):
                                    app.payment_txids.append(txid)
                                else:
                                    app.payment_txids = [txid]
                                app.save()
                                processed_bonds += 1
                                logger.info(f"{app_log_prefix} Bond payment sufficient ({amount_atomic}/{required_atomic}). Status updated to PENDING_REVIEW.")
                                security_logger.info(f"VENDOR BOND PAID: AppID:{app.id}, User:{app.user.username}, Amount:{amount_atomic}sats, TXID:{txid}")

                                # FIXME: Uncomment the line below and import/define `log_audit_event` correctly.
                                # log_audit_event(None, app.user, 'vendor_app_bond_paid', target_application=app, details=f"TX:{txid} Amt:{amount_atomic}sats")

                                try:
                                    if notification_service:
                                        notification_service.create_notification(
                                            level='info',
                                            message=f"Vendor Application #{app.id} from '{app.user.username}' paid bond ({amount_atomic/1e8:.8f} BTC) and requires review."
                                        )
                                        logger.info(f"{app_log_prefix} Sent admin review notification.")
                                except Exception as notify_err:
                                    logger.error(f"{app_log_prefix} Failed to send admin notification: {notify_err}", exc_info=True)
                            else: # Underpayment
                                underpaid = required_atomic - amount_atomic
                                logger.warning(f"{app_log_prefix} Underpayment detected by {underpaid} atomic units ({amount_atomic}/{required_atomic}).")
                                if hasattr(app, 'payment_txids') and isinstance(app.payment_txids, list):
                                    app.payment_txids.append(txid)
                                else:
                                    app.payment_txids = [txid]
                                app.save(update_fields=['payment_txids', 'updated_at'])

                    except (DatabaseError, IntegrityError, DjangoValidationError) as db_err:
                        logger.exception(f"{app_log_prefix} DB/Validation error updating VendorApplication: {db_err}")
                        failed_processing += 1
                    except Exception as e:
                        logger.exception(f"{app_log_prefix} Unexpected error processing vendor bond: {e}")
                        failed_processing += 1

                elif payment_type == 'order':
                    order_id = related_id
                    order_log_prefix = f"{log_prefix}[Order:{order_id}|TX:{txid[:8]}]"
                    try:
                        with transaction.atomic():
                            try:
                                order = Order.objects.select_related('payment', 'vendor', 'buyer').select_for_update().get(pk=order_id)
                                try:
                                    payment = order.payment
                                except (CryptoPayment.DoesNotExist, ObjectDoesNotExist): # Catch generic ObjectDoesNotExist if CryptoPayment is dummy
                                    payment = None
                                if not payment:
                                    payment = CryptoPayment.objects.filter(order=order, currency=currency_code).first()
                                if not payment:
                                    logger.error(f"{order_log_prefix} No CryptoPayment record found for Order. Skipping.")
                                    continue
                            except Order.DoesNotExist:
                                logger.info(f"{order_log_prefix} Order not found. Skipping.")
                                continue

                            if LedgerTransaction.objects.filter(
                                external_txid=txid,
                                transaction_type__in=[LEDGER_TRANSACTION_TYPE_DEPOSIT, LEDGER_TRANSACTION_TYPE_ESCROW_FUND],
                                user=order.buyer,
                                currency=currency_code
                            ).exists():
                                logger.info(f"{order_log_prefix} TXID already processed in ledger for this buyer/currency. Skipping.")
                                skipped_existing += 1
                                continue

                            payment_status_attr = getattr(payment, 'status', 'unknown')
                            if order.status != ORDER_STATUS_PENDING_PAYMENT or payment_status_attr not in ['pending', 'unconfirmed']:
                                logger.info(f"{order_log_prefix} Order/Payment not in pending state ({order.status}/{payment_status_attr}). Skipping.")
                                continue

                            required_atomic: Optional[int] = None
                            try:
                                if payment.expected_amount_native and payment.currency == currency_code:
                                     required_atomic = int(payment.expected_amount_native)
                            except Exception as conv_err:
                                logger.error(f"{order_log_prefix} Error getting stored order amount {payment.expected_amount_native} as atomic: {conv_err}")

                            if required_atomic is None or required_atomic <= 0:
                                logger.error(f"{order_log_prefix} Could not determine valid required atomic amount for order payment. Skipping.")
                                failed_processing += 1
                                continue

                            min_confs_needed = payment.confirmations_needed or getattr(settings, f"{currency_code.upper()}_CONFIRMATIONS_NEEDED", 1)
                            if confirmations < min_confs_needed:
                                logger.info(f"{order_log_prefix} Deposit has {confirmations}/{min_confs_needed} confirmations. Waiting.")
                                continue

                            if amount_atomic >= required_atomic:
                                if amount_atomic > required_atomic:
                                    overpaid = amount_atomic - required_atomic
                                    logger.warning(f"{order_log_prefix} Overpayment detected by {overpaid} atomic units.")

                                # Update Payment record (adapt field names as needed)
                                payment.status = 'confirmed'
                                payment.received_amount_atomic = amount_atomic # Assume this field exists
                                payment.received_confirmations = confirmations # Assume this field exists
                                payment.paid_txid = txid # Assume this field exists
                                payment.paid_at = timezone.now() # Assume this field exists
                                payment.save()

                                # Update Order status
                                order.status = ORDER_STATUS_PAYMENT_CONFIRMED
                                order.save(update_fields=['status', 'updated_at'])

                                # Credit Ledger (using standard units)
                                amount_standard = Decimal(str(amount_atomic)) / ATOMIC_FACTOR.get(currency_code, Decimal('1'))
                                ledger_service.credit_funds(
                                    user=order.buyer, currency=currency_code, amount=amount_standard,
                                    transaction_type=LEDGER_TRANSACTION_TYPE_DEPOSIT,
                                    external_txid=txid, related_order_id=order.id,
                                    notes=f"Confirmed Order {order.id} Deposit"
                                )

                                processed_orders += 1
                                logger.info(f"{order_log_prefix} Order payment sufficient ({amount_atomic}/{required_atomic}). Status updated to {ORDER_STATUS_PAYMENT_CONFIRMED}. Ledger credited.")
                                security_logger.info(f"ORDER PAYMENT CONFIRMED: OrderID:{order.id}, Buyer:{order.buyer.username}, Amount:{amount_standard} {currency_code} ({amount_atomic} atomic), TXID:{txid}")
                                # FIXME: Uncomment and import/define log_audit_event if needed
                                # log_audit_event(None, order.buyer, 'order_payment_confirm', target_order=order, details=f"TX:{txid} Amt:{amount_standard} {currency_code}")

                                try:
                                    if notification_service:
                                        notification_service.create_notification(
                                            user_id=order.vendor.id, level='info',
                                            message=f"Payment received for Order #{order.id} ({order.product.name[:30]}...). Please prepare for shipping."
                                        )
                                        notification_service.create_notification(
                                            user_id=order.buyer.id, level='success',
                                            message=f"Your payment for Order #{order.id} ({order.product.name[:30]}...) has been confirmed."
                                        )
                                        logger.info(f"{order_log_prefix} Sent payment confirmation notifications.")
                                except Exception as notify_err:
                                    logger.error(f"{order_log_prefix} Failed sending payment notifications: {notify_err}", exc_info=True)
                            else: # Underpayment
                                underpaid = required_atomic - amount_atomic
                                logger.warning(f"{order_log_prefix} Underpayment detected by {underpaid} atomic units ({amount_atomic}/{required_atomic}).")

                    except (DatabaseError, IntegrityError, DjangoValidationError) as db_err:
                        logger.exception(f"{order_log_prefix} DB/Validation error processing order payment: {db_err}")
                        failed_processing += 1
                    except InsufficientFundsError as ife:
                        logger.critical(f"{order_log_prefix} CRITICAL: Ledger credit failed (InsufficientFundsError) for ORDER DEPOSIT! TXID:{txid}. Error: {ife}", exc_info=True)
                        failed_processing += 1
                    except Exception as e:
                        logger.exception(f"{order_log_prefix} Unexpected error processing order payment: {e}")
                        failed_processing += 1
                else:
                    logger.warning(f"{log_prefix} Unknown payment type '{payment_type}' skipped: {payment_info}")
                    skipped_invalid += 1
                    continue

            # --- Update Last Checked Height --- (Removed)

        except Ignore:
            raise
        except Exception as e:
            logger.exception(f"{log_prefix} Error during deposit check execution: {e}")
            raise

        finally:
            # --- Log Summary ---
            summary = (
                f"{currency_code.upper()} deposit check ({task_id}) finished. "
                f"Processed Orders: {processed_orders}, "
                f"Processed Bonds: {processed_bonds}, "
                f"Skipped (Existing): {skipped_existing}, "
                f"Skipped (Invalid): {skipped_invalid}, "
                f"Failed Processing: {failed_processing}. "
            )
            logger.info(f"{log_prefix} {summary}")
            if failed_processing > 0:
                logger.critical(f"{log_prefix} ATTENTION: {failed_processing} critical processing failures occurred.")

    except Ignore:
        logger.info(f"{log_prefix} Task ignored due to lock contention or explicit request.")
    except Exception as e:
        logger.exception(f"{log_prefix} Unhandled exception in deposit check task wrapper: {e}")
        raise
    finally:
        if lock and lock.locked():
            try:
                lock.release()
                logger.info(f"{log_prefix} Released lock: {lock_key}")
            except Exception as release_err:
                logger.error(f"{log_prefix} Failed to release lock '{lock_key}': {release_err}", exc_info=True)


@shared_task(
    name="store.tasks.check_xmr_deposits", # Ensure name matches trigger task
    ignore_result=True,
    time_limit=TASK_DEPOSIT_CHECK_TIME_LIMIT,
    soft_time_limit=TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5,
    retry_jitter=True
)
@check_dependencies(
    'User', 'LedgerTransaction', 'ledger_service', 'monero_service',
    'GlobalSettings', 'VendorApplication', 'Order', 'CryptoPayment', # Added Order/CryptoPayment
    'redis_lock', 'notification_service' # Added notification service
)
def check_xmr_deposits(self: Task):
    """ Checks XMR deposits (Orders & Vendor Bonds), credits ledger/updates apps. """
    # NOTE: Vendor bonds are currently BTC only, so XMR service should only return 'order' type.
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_XMR,
        scan_service_func=monero_service.scan_for_new_deposits,
    )

@shared_task(
    name="store.tasks.check_btc_deposits", # Ensure name matches trigger task
    ignore_result=True,
    time_limit=TASK_DEPOSIT_CHECK_TIME_LIMIT,
    soft_time_limit=TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5,
    retry_jitter=True
)
@check_dependencies(
    'User', 'LedgerTransaction', 'ledger_service', 'bitcoin_service',
    'GlobalSettings', 'VendorApplication', 'Order', 'CryptoPayment', # Added Order/CryptoPayment
    'redis_lock', 'notification_service', 'exchange_rate_service' # Added exchange_rate for fallback calc
)
def check_btc_deposits(self: Task):
    """ Checks BTC deposits (Orders & Vendor Bonds), credits ledger/updates apps. """
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_BTC,
        scan_service_func=bitcoin_service.scan_for_new_deposits,
    )

@shared_task(
    name="store.tasks.check_eth_deposits", # Ensure name matches trigger task
    ignore_result=True,
    time_limit=TASK_DEPOSIT_CHECK_TIME_LIMIT,
    soft_time_limit=TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5,
    retry_jitter=True
)
@check_dependencies(
    'User', 'LedgerTransaction', 'ledger_service', 'ethereum_service',
    'GlobalSettings', 'VendorApplication', 'Order', 'CryptoPayment', # Added Order/CryptoPayment
    'redis_lock', 'notification_service' # Added notification service
)
def check_eth_deposits(self: Task):
    """ Checks ETH deposits (Orders & Vendor Bonds), credits ledger/updates apps. """
    # NOTE: Vendor bonds are currently BTC only, so ETH service should only return 'order' type.
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_ETH,
        scan_service_func=ethereum_service.scan_for_new_deposits,
    )


@shared_task(
    name="update_all_vendor_reputations_task",
    time_limit=TASK_REPUTATION_TIME_LIMIT,
    soft_time_limit=TASK_REPUTATION_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 10,
    retry_jitter=True
)
@check_dependencies('reputation_service')
def update_all_vendor_reputations_task(self: Task):
    """ Periodically updates vendor reputations via service, with retries. """
    if not MODELS_SERVICES_LOADED: return "Task Failed: Critical imports failed."
    task_id = self.request.id
    log_prefix = f"[VendorReputationUpdate:{task_id}]"
    logger.info(f"{log_prefix} Starting periodic vendor reputation update task.")

    if not hasattr(reputation_service, 'update_all_vendor_reputations'):
       error_msg = f"{log_prefix} CRITICAL: Service function 'update_all_vendor_reputations' missing."
       logger.critical(error_msg)
       return "Task Aborted: Service function missing."

    try:
        result_summary = reputation_service.update_all_vendor_reputations()
        success_msg = f"{log_prefix} Periodic vendor reputation update task completed successfully."
        if result_summary: logger.info(f"{success_msg} Service summary: {result_summary}")
        else: logger.info(success_msg)
        return f"Reputation update cycle finished. Task ID: {task_id}"

    except Exception as e:
        logger.exception(f"{log_prefix} Error during periodic vendor reputation update after potential retries: {e}")
        logger.critical(f"{log_prefix} Vendor reputation update failed permanently after retries or due to non-transient error.")
        # Re-raise to mark task as failed after retries are exhausted
        raise


# --- NEW: Task to update exchange rates ---
@shared_task(
    name="update_exchange_rates_task",
    time_limit=TASK_EXCHANGE_RATE_TIME_LIMIT,
    soft_time_limit=TASK_EXCHANGE_RATE_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS), # Retry on network/DB errors
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 2,
    retry_jitter=True
)
@check_dependencies('GlobalSettings', 'exchange_rate_service', 'redis_lock') # Added redis_lock
def update_exchange_rates_task(self: Task):
    """ Periodically fetches exchange rates and updates GlobalSettings. """
    if not MODELS_SERVICES_LOADED: return "Task Failed: Critical imports failed."
    task_id = self.request.id
    log_prefix = f"[UpdateExchangeRates:{task_id}]"

    # Optional: Use a lock to prevent multiple workers updating rates simultaneously
    lock = None # Initialize lock variable
    if redis_lock is None:
        logger.warning(f"{log_prefix} Skipping lock check: 'django-redis-lock' library not available.")
    else:
        try:
            lock = redis_lock.Lock(_redis=None, name=RATES_LOCK_KEY, expire=RATES_LOCK_EXPIRY, id=task_id, auto_renewal=False)
            if not lock.acquire(blocking=False):
                logger.info(f"{log_prefix} Could not acquire lock '{RATES_LOCK_KEY}'. Another update likely in progress. Skipping.")
                raise Ignore() # Skip this run gracefully
            logger.info(f"{log_prefix} Acquired lock '{RATES_LOCK_KEY}'.")
        except Ignore:
            raise # Propagate Ignore
        except Exception as lock_err:
            logger.error(f"{log_prefix} Error acquiring lock '{RATES_LOCK_KEY}': {lock_err}. Proceeding without lock.", exc_info=True)
            lock = None # Ensure lock is None if acquisition failed

    logger.info(f"{log_prefix} Starting exchange rate update.")
    try:
        # Fetch rates using the service
        # Assume service handles internal errors/retries appropriately or raises exceptions
        rates_data = exchange_rate_service.get_current_rates(fetch_fresh=True) # Add fetch_fresh if needed

        if not rates_data:
            logger.error(f"{log_prefix} Failed to get current rates from exchange_rate_service. Aborting update.")
            # No retry here at task level if service failed after its own retries.
            return "Update Failed: Could not retrieve rates."

        # Update GlobalSettings atomically
        try:
            with transaction.atomic():
                gs = GlobalSettings.objects.select_for_update().first()
                if not gs:
                    logger.error(f"{log_prefix} GlobalSettings record not found. Cannot store rates.")
                    return "Update Failed: GlobalSettings not found."

                update_fields = []
                # Map fetched rates (structure depends on exchange_rate_service)
                # Example assuming rates_data = {'BTC_USD': Decimal(...), 'BTC_EUR': ..., 'ETH_USD': ...}
                rate_fields = [f.name for f in GlobalSettings._meta.get_fields() if f.name.endswith('_rate')]

                for field_name in rate_fields:
                    # Parse crypto/fiat from field name, e.g., 'btc_usd_rate' -> 'BTC', 'USD'
                    parts = field_name.split('_')
                    if len(parts) == 3 and parts[2] == 'rate':
                        crypto_code = parts[0].upper()
                        fiat_code = parts[1].upper()
                        rate_key = f"{crypto_code}_{fiat_code}" # Key format used by service?
                        rate_value = rates_data.get(rate_key)

                        if rate_value is not None:
                            try:
                                # Validate and set
                                validated_rate = Decimal(str(rate_value))
                                if validated_rate > 0:
                                    setattr(gs, field_name, validated_rate)
                                    update_fields.append(field_name)
                                else:
                                    logger.warning(f"{log_prefix} Ignoring non-positive rate for {rate_key}: {rate_value}")
                            except (InvalidOperation, TypeError, ValueError) as e:
                                logger.warning(f"{log_prefix} Invalid rate format for {rate_key} ('{rate_value}'): {e}")
                        # else: Rate not found in fetched data

                if update_fields:
                    gs.rates_last_updated = timezone.now()
                    update_fields.append('rates_last_updated')
                    gs.save(update_fields=update_fields)
                    logger.info(f"{log_prefix} Successfully updated exchange rates in GlobalSettings. Fields: {', '.join(update_fields)}")
                else:
                    logger.warning(f"{log_prefix} No applicable exchange rate fields found or updated in GlobalSettings based on fetched data.")

        except (DatabaseError, IntegrityError) as db_err:
            logger.exception(f"{log_prefix} Database error saving exchange rates to GlobalSettings: {db_err}")
            # Re-raise to potentially trigger retry
            raise db_err
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error saving exchange rates: {e}")
            raise # Re-raise non-transient errors

        return f"Exchange rates updated successfully. Task ID: {task_id}"

    except Ignore:
        raise # Propagate Ignore from lock acquisition
    except Exception as e:
        # Catch errors from exchange_rate_service call or other unexpected issues
        logger.exception(f"{log_prefix} Failed to update exchange rates: {e}")
        # Let Celery handle retry/failure based on autoretry_for
        raise
    finally:
        # Release lock if acquired
        if lock and lock.locked():
            try:
                lock.release()
                logger.info(f"{log_prefix} Released lock '{RATES_LOCK_KEY}'.")
            except Exception as release_err:
                logger.error(f"{log_prefix} Failed to release lock '{RATES_LOCK_KEY}': {release_err}", exc_info=True)


# --- Celery Beat Schedule Reminder ---
# Ensure the following (or similar) configuration exists in your Django settings
# (e.g., settings/base.py, settings/celery.py, or wherever CELERY_BEAT_SCHEDULE is defined)
# from celery.schedules import crontab, timedelta # Added timedelta
#
# CELERY_BEAT_SCHEDULE = {
#     'update-exchange-rates-every-few-minutes': { # NEW TASK SCHEDULE
#         'task': 'store.tasks.update_exchange_rates_task',
#         'schedule': timedelta(minutes=5), # Adjust frequency based on API limits and needs
#         'options': {'expires': 100.0},
#     },
#     'check-all-deposits-every-few-minutes': {
#         'task': 'store.tasks.check_all_deposits',
#         'schedule': timedelta(minutes=3), # Adjust frequency as needed
#         'options': {'expires': 150.0},
#     },
#     'auto-finalize-orders-hourly': {
#         'task': 'store.tasks.auto_finalize_paid_orders',
#         'schedule': timedelta(hours=1),
#         'options': {'expires': 3500.0},
#     },
#     'update-vendor-reputations-daily': {
#         'task': 'store.tasks.update_all_vendor_reputations_task',
#         'schedule': crontab(hour=4, minute=30), # Example: Run daily at 4:30 AM UTC
#         'options': {'expires': 7200.0},
#     },
#     # Include schedules for other important tasks, like ledger reconciliation
#     'reconcile-ledger-balances-daily': {
#         'task': 'ledger.tasks.reconcile_ledger_balances', # Assuming task exists in ledger app
#         'schedule': crontab(hour=3, minute=0),
#     },
# }

# --- END OF FILE ---