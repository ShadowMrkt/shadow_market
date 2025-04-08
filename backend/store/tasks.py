# backend/store/tasks.py
# --- Revision History ---
# [Rev 1.0 - 2025-04-07]
#   - Added Distributed Locking: Implemented Redis-based distributed locks for deposit check tasks
#     (`_perform_deposit_check`) to prevent race conditions between concurrent workers processing
#     the same currency. Requires `django-redis-lock` library.
#   - Added Explicit Retries: Incorporated Celery's `autoretry_for` mechanism for deposit checks,
#     auto-finalize, and reputation tasks to automatically retry on specific transient errors
#     (guessed common ones like connection/DB errors - adjust based on actual service exceptions).
#   - Improved Error Handling & Logging:
#     - Enhanced logging in deposit checks, clearly differentiating critical failures.
#     - Made `auto_finalize_paid_orders` log a clearer summary of failures needing review.
#     - Made `update_all_vendor_reputations_task` use the retry mechanism.
#   - Minor Refinements: Added constants for lock keys/timeouts, slightly improved comments.
#   - Dependency Check: Added `redis_lock` to relevant dependency checks.
# ------------------------

"""
Celery tasks for the store application.

Includes tasks for:
- Auto-finalizing shipped orders past their deadline.
- Checking for new cryptocurrency deposits (XMR, BTC, ETH) and crediting user ledgers.
- Periodically updating vendor reputation metrics.
"""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Optional, Dict, Any, List

from celery import shared_task, Task
from celery.exceptions import Ignore # <<< CHANGE [Rev 1.0] Added Ignore for lock handling
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError, DatabaseError # <<< CHANGE [Rev 1.0] Added DatabaseError for retry
from django.utils import timezone

# --- Third-Party Imports ---
# Attempt to import redis_lock, provide guidance if missing
try:
    import redis_lock
except ImportError:
    redis_lock = None # <<< CHANGE [Rev 1.0] Handle missing redis_lock gracefully initially

# <<< CHANGE [Rev 1.0] Import common potentially transient errors for retries
# Adjust these based on the actual exceptions raised by your crypto/DB libraries
try:
    import requests # Assuming services might use requests
    CONNECTION_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
except ImportError:
    CONNECTION_ERRORS = () # No requests library

# Database errors that might be transient (adjust based on your DB engine)
TRANSIENT_DB_ERRORS = (DatabaseError,) # Example, might need refinement (e.g., OperationalError for psycopg2)
# <<< END CHANGE [Rev 1.0]

# --- Constants ---
CURRENCY_XMR = 'XMR'
CURRENCY_BTC = 'BTC'
CURRENCY_ETH = 'ETH'
DEFAULT_SUPPORTED_CURRENCIES = [CURRENCY_XMR, CURRENCY_BTC, CURRENCY_ETH]

LEDGER_TRANSACTION_TYPE_DEPOSIT = 'DEPOSIT'

# Settings Keys
SETTING_KEY_LAST_CHECKED_BLOCK_PATTERN = "last_checked_{currency}_height"
SETTING_KEY_SUPPORTED_CURRENCIES = "SUPPORTED_CURRENCIES"

# Task Configuration Defaults
TASK_DEFAULT_TIME_LIMIT = 600   # 10 minutes
TASK_DEFAULT_SOFT_TIME_LIMIT = 580
TASK_DEPOSIT_CHECK_TIME_LIMIT = 300 # 5 minutes
TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT = 290
TASK_REPUTATION_TIME_LIMIT = 1800 # 30 minutes
TASK_REPUTATION_SOFT_TIME_LIMIT = 1780
TASK_RETRY_DELAY = 60 # Default delay in seconds for retries
TASK_MAX_RETRIES = 3 # Default max retries

# <<< CHANGE [Rev 1.0] Constants for Distributed Locking
LOCK_ACQUIRE_TIMEOUT = 10 # Seconds to wait for lock acquisition
LOCK_EXPIRY_BUFFER = 60 # Seconds buffer for lock expiry beyond soft time limit
DEPOSIT_LOCK_EXPIRY = TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT + LOCK_EXPIRY_BUFFER
DEPOSIT_LOCK_KEY_PATTERN = "lock_check_{currency}_deposits"
# <<< END CHANGE [Rev 1.0]


# --- Logging Setup ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Import Application Modules ---
try:
    from store.models import CryptoPayment, Order, User, GlobalSettings
    from ledger.models import LedgerTransaction
    from store.services import (
        monero_service, bitcoin_service, ethereum_service,
        escrow_service, reputation_service
    )
    from ledger import services as ledger_service
    from ledger.services import InsufficientFundsError

    _required_services = {
        "monero_service": monero_service, "bitcoin_service": bitcoin_service,
        "ethereum_service": ethereum_service, "escrow_service": escrow_service,
        "reputation_service": reputation_service, "ledger_service": ledger_service,
    }
    for name, service in _required_services.items():
        if service is None:
            raise ImportError(f"Service '{name}' is None or not imported correctly.")

except ImportError as e:
    logger.critical(
        f"CRITICAL IMPORT ERROR in store/tasks.py: {e}. "
        f"Tasks depending on these imports will fail.",
        exc_info=True
    )
    # Consider raising the error to prevent worker start if imports are critical
    # raise e


# --- Helper Functions ---

def get_last_checked_block(currency_code: str) -> int:
    """ Safely retrieves the last checked block height for a currency. """
    setting_name = SETTING_KEY_LAST_CHECKED_BLOCK_PATTERN.format(
        currency=currency_code.lower()
    )
    try:
        # Using .first() is slightly more robust than get(pk=1) if pk isn't guaranteed
        gs = GlobalSettings.objects.first()
        if not gs:
             raise GlobalSettings.DoesNotExist # Raise standard exception for consistent handling
        height = getattr(gs, setting_name, 0)
        return int(height) if height is not None else 0
    except GlobalSettings.DoesNotExist:
        logger.warning(f"GlobalSettings record not found. Cannot get last checked block for {currency_code}. Returning 0.")
        return 0
    except (AttributeError, TypeError, ValueError) as e:
        logger.error(
            f"Error retrieving or parsing setting '{setting_name}' for {currency_code}: {e}. Returning 0.",
            exc_info=True
        )
        return 0
    except Exception as e:
        logger.exception(f"Unexpected error getting last checked block for {currency_code}: {e}")
        return 0

def set_last_checked_block(currency_code: str, height: Optional[int]):
    """ Atomically sets the last checked block height, ensuring it only increases. """
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
            # Lock the row to prevent race conditions during the update itself
            # Using .first() again for consistency
            gs = GlobalSettings.objects.select_for_update().first()
            if not gs:
                 raise GlobalSettings.DoesNotExist

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

    except GlobalSettings.DoesNotExist:
        logger.error(f"GlobalSettings record not found. Cannot set last checked block for {currency_code}.")
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

            missing = []
            for service_name in services_to_check:
                # <<< CHANGE [Rev 1.0] Special check for redis_lock
                if service_name == 'redis_lock' and redis_lock is None:
                     missing.append("redis_lock (python library 'django-redis-lock' likely not installed)")
                     continue
                # <<< END CHANGE [Rev 1.0]
                if service_name not in globals() or globals()[service_name] is None:
                    missing.append(service_name)

            if missing:
                error_msg = f"Task {func.__name__} ({task_id}) aborted: Missing critical dependencies: {', '.join(missing)}."
                logger.critical(error_msg)
                # Add monitoring/alerting here if needed
                return f"Task Aborted: Missing dependencies ({', '.join(missing)})"
            return func(*args, **kwargs)
        return wrapper
    return decorator


# --- Celery Tasks ---

# <<< CHANGE [Rev 1.0] Added autoretry_for
@shared_task(
    name="auto_finalize_paid_orders",
    time_limit=TASK_DEFAULT_TIME_LIMIT,
    soft_time_limit=TASK_DEFAULT_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS), # Retry on network/DB issues
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5, # Max delay between retries
    retry_jitter=True
)
# <<< END CHANGE [Rev 1.0]
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

    excluded_statuses = ['disputed', 'finalized', 'cancelled_timeout', 'refunded']

    # Consider adding select_related('buyer', 'vendor', 'escrow_details') if service needs them
    eligible_orders = Order.objects.filter(
        status='shipped',
        auto_finalize_deadline__isnull=False,
        auto_finalize_deadline__lte=now
    ).exclude(status__in=excluded_statuses)

    order_count = 0 # Count actual items iterated over
    processed_success_count = 0
    broadcast_success_count = 0
    failed_initiation_count = 0
    failed_broadcast_count = 0
    needs_review_sig_count = 0
    unexpected_error_count = 0

    # Use iterator for memory efficiency with potentially large querysets
    for order in eligible_orders.iterator():
        order_count += 1
        logger.info(f"{log_prefix} Processing Order {order.id}...")
        try:
            order_finalized_in_run = False

            # --- Step 1: Initiate Release (if needed) ---
            if not order.release_initiated:
                logger.info(f"{log_prefix} Initiating release for Order {order.id}...")
                # Pass user=None for automated process
                # Assuming finalize_order handles its own atomicity/state changes
                init_success = escrow_service.finalize_order(order, user=None, is_auto_finalize=True)
                if not init_success:
                    logger.error(f"{log_prefix} Failed to prepare/initiate release for Order {order.id}. Requires review.")
                    failed_initiation_count += 1
                    continue # Move to the next order
                order.refresh_from_db() # Reload state after potential modification

            # --- Step 2: Check Signatures and Broadcast (if ready) ---
            # Use hasattr for safety if fields might not always exist (adapt field names)
            buyer_sig_present = hasattr(order, 'release_signature_buyer') and bool(order.release_signature_buyer)
            vendor_sig_present = hasattr(order, 'release_signature_vendor') and bool(order.release_signature_vendor)

            if buyer_sig_present and vendor_sig_present:
                logger.info(f"{log_prefix} Order {order.id} has signatures, attempting broadcast...")
                # escrow_service.broadcast_release_transaction should be idempotent
                # and handle finalization status + ledger updates.
                broadcast_successful = escrow_service.broadcast_release_transaction(order)
                if broadcast_successful:
                    logger.info(f"{log_prefix} Successfully finalized (broadcast initiated/confirmed) for Order {order.id}.")
                    broadcast_success_count += 1
                    order_finalized_in_run = True
                else:
                    logger.error(f"{log_prefix} Broadcast attempt failed for signed Order {order.id}. Requires review.")
                    failed_broadcast_count += 1
            elif order.release_initiated: # Only log as needs review if initiation happened but sigs missing
                logger.warning(f"{log_prefix} Order {order.id} past deadline but missing required signatures "
                               f"(Buyer: {buyer_sig_present}, Vendor: {vendor_sig_present}). Requires review.")
                needs_review_sig_count += 1

            if order_finalized_in_run:
                processed_success_count += 1

        except (ConnectionError, DatabaseError) as transient_err: # <<< CHANGE [Rev 1.0] Catch specific retryable errors
             logger.warning(f"{log_prefix} Transient error processing Order {order.id}: {transient_err}. Task will retry if attempts remain.")
             # Re-raise to trigger Celery's autoretry mechanism
             raise transient_err # <<< END CHANGE [Rev 1.0]
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error processing Order {order.id}: {e}")
            unexpected_error_count += 1
            # Continue processing other orders, but log this critical failure

    # --- Task Summary ---
    summary_parts = [
        f"Auto-finalize task ({task_id}) finished.",
        f"Checked: {order_count}.",
        f"Successfully Finalized/Broadcast: {broadcast_success_count}.",
    ]
    # <<< CHANGE [Rev 1.0] More detailed failure summary
    if failed_initiation_count > 0:
        summary_parts.append(f"Failed Initiations: {failed_initiation_count}.")
    if failed_broadcast_count > 0:
        summary_parts.append(f"Failed Broadcasts: {failed_broadcast_count}.")
    if needs_review_sig_count > 0:
         summary_parts.append(f"Needs Review (Missing Sigs): {needs_review_sig_count}.")
    if unexpected_error_count > 0:
        summary_parts.append(f"Unexpected Errors (per order): {unexpected_error_count}.")

    summary = " ".join(summary_parts)
    if failed_initiation_count > 0 or failed_broadcast_count > 0 or needs_review_sig_count > 0 or unexpected_error_count > 0:
         logger.warning(f"{log_prefix} {summary} - ATTENTION NEEDED FOR FAILURES/REVIEWS.")
         # Consider adding alerting hook here (e.g., Sentry, PagerDuty)
    else:
         logger.info(f"{log_prefix} {summary}")
    # <<< END CHANGE [Rev 1.0]
    return summary


@shared_task(
    name="check_all_deposits",
    time_limit=TASK_DEFAULT_TIME_LIMIT,
    soft_time_limit=TASK_DEFAULT_SOFT_TIME_LIMIT,
    bind=True
)
def check_all_deposits(self: Task):
    """ Meta-task triggering individual deposit checks for supported currencies. """
    task_id = self.request.id
    log_prefix = f"[CheckAllDeposits:{task_id}]"
    logger.info(f"{log_prefix} Triggering deposit checks...")

    currencies_to_check = getattr(settings, SETTING_KEY_SUPPORTED_CURRENCIES, DEFAULT_SUPPORTED_CURRENCIES)
    results: Dict[str, str] = {}

    logger.info(f"{log_prefix} Will queue checks for: {', '.join(currencies_to_check)}")

    for currency in currencies_to_check:
        currency_lower = currency.lower()
        specific_task_name = f"store.tasks.check_{currency_lower}_deposits"
        try:
            # Use .si() for immutable signature (no args needed here)
            task_signature = shared_task(name=specific_task_name).si()
            async_result = task_signature.apply_async()
            results[currency] = f"Task Queued (ID: {async_result.id})"
            logger.info(f"{log_prefix} Queued task '{specific_task_name}' with ID: {async_result.id}")
        except Exception as e:
            # Catch potential errors during task queuing (e.g., broker connection issues)
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
    scan_service_func: callable,
    amount_field: str
):
    """ Internal helper to perform deposit check logic with distributed locking. """
    task_id = task_instance.request.id
    log_prefix = f"[Check{currency_code.upper()}Deposits:{task_id}]"

    # <<< CHANGE [Rev 1.0] Implement Distributed Lock
    if redis_lock is None:
        logger.critical(f"{log_prefix} Aborting task: 'django-redis-lock' library not available.")
        # Optional: Raise an exception to mark task as failed permanently if lock is mandatory
        # raise ImportError("django-redis-lock is required for deposit checking")
        return # Or simply abort

    lock_key = DEPOSIT_LOCK_KEY_PATTERN.format(currency=currency_code.lower())
    lock = None # Initialize lock variable

    try:
        logger.info(f"{log_prefix} Attempting to acquire lock: {lock_key}")
        # Use `id=task_id` for better lock ownership tracking in Redis if needed
        # `expire` sets the lock's TTL in Redis
        # `auto_renewal=True` can keep the lock alive if the task runs longer than expected (use cautiously)
        lock = redis_lock.Lock(
            _redis=None, # Uses the default Redis connection from settings
            name=lock_key,
            expire=DEPOSIT_LOCK_EXPIRY,
            id=task_id,
            auto_renewal=False # Keep renewal off unless strictly necessary and understood
        )

        if not lock.acquire(blocking=False): # Use non-blocking initially
             # If non-blocking fails, try blocking for a short period
            logger.warning(f"{log_prefix} Lock '{lock_key}' already held. Waiting up to {LOCK_ACQUIRE_TIMEOUT}s...")
            if not lock.acquire(blocking=True, timeout=LOCK_ACQUIRE_TIMEOUT):
                 logger.warning(f"{log_prefix} Could not acquire lock '{lock_key}' after waiting. "
                                f"Another task instance is likely running. Skipping this run.")
                 # Use Celery's Ignore exception to prevent task from being marked as failed/retried
                 # when skipping due to lock contention.
                 raise Ignore()

        logger.info(f"{log_prefix} Successfully acquired lock: {lock_key}")

        # --- Core Deposit Check Logic (inside the lock) ---
        logger.info(f"{log_prefix} Starting deposit check logic.")
        last_height = get_last_checked_block(currency_code)
        logger.info(f"{log_prefix} Last checked block height: {last_height}")
        new_max_height_processed = last_height
        processed_count = 0
        skipped_existing_count = 0
        skipped_invalid_data_count = 0
        failed_credit_count = 0

        try:
            # --- Scan for New Deposits ---
            # This service call might raise transient errors caught by autoretry_for
            new_payments: List[Dict[str, Any]] = scan_service_func(last_checked_block=last_height)
            logger.info(f"{log_prefix} Found {len(new_payments)} potential new deposits.")

            for payment_info in new_payments:
                # --- Validation ---
                user = payment_info.get('user')
                txid = payment_info.get('txid')
                amount_str = payment_info.get(amount_field)
                height = payment_info.get('block_height')
                related_order = payment_info.get('order')
                payment_id = payment_info.get('payment_id')
                address = payment_info.get('address')

                if not all([user, txid, amount_str]):
                    logger.warning(f"{log_prefix} Incomplete payment info skipped: {payment_info}")
                    skipped_invalid_data_count += 1
                    continue
                if not isinstance(user, User):
                    logger.warning(f"{log_prefix} Invalid user object type ({type(user)}) skipped: {payment_info}")
                    skipped_invalid_data_count += 1
                    continue

                try:
                    amount = Decimal(str(amount_str))
                    if amount <= Decimal('0.0'):
                        logger.info(f"{log_prefix} Skipping zero/negative amount: {payment_info}")
                        skipped_invalid_data_count += 1
                        continue
                except (InvalidOperation, ValueError, TypeError):
                    logger.warning(f"{log_prefix} Invalid amount format ('{amount_str}') skipped: {payment_info}")
                    skipped_invalid_data_count += 1
                    continue

                # --- Idempotency Check ---
                try:
                    # This DB query should be quick
                    if LedgerTransaction.objects.filter(
                        external_txid=txid,
                        transaction_type=LEDGER_TRANSACTION_TYPE_DEPOSIT,
                        user=user,
                        currency=currency_code
                    ).exists():
                        logger.info(f"{log_prefix} Deposit TXID {txid} for User {user.username} already credited. Skipping.")
                        skipped_existing_count += 1
                        if height is not None and height > new_max_height_processed:
                            new_max_height_processed = height
                        continue
                except DatabaseError as db_err: # Catch potential transient DB errors here too
                    logger.exception(f"{log_prefix} DB error checking existing ledger entry for TXID {txid}. Skipping credit. Error: {db_err}")
                    failed_credit_count += 1
                    # Re-raise to potentially trigger retry for the whole task if needed
                    # Or just log and continue to next payment? Decide based on severity.
                    # For now, log as failure and continue.
                    continue
                except Exception as db_err: # Catch unexpected errors
                     logger.exception(f"{log_prefix} Unexpected error checking existing ledger entry for TXID {txid}. Skipping credit. Error: {db_err}")
                     failed_credit_count += 1
                     continue


                # --- Credit User via Ledger Service ---
                try:
                    notes_parts = [f"Confirmed {currency_code} Deposit"]
                    if payment_id: notes_parts.append(f"PayID: {payment_id}")
                    if address: notes_parts.append(f"Addr: {address}")
                    if height is not None: notes_parts.append(f"Block: {height}")
                    notes = " ".join(notes_parts)

                    # Ledger service handles its own atomicity
                    ledger_service.credit_funds(
                        user=user, currency=currency_code, amount=amount,
                        transaction_type=LEDGER_TRANSACTION_TYPE_DEPOSIT,
                        external_txid=txid, related_order=related_order, notes=notes
                    )

                    security_logger.info(
                        f"DEPOSIT Credited: Task:{task_id}, User:{user.username}, "
                        f"Amount:{amount:.8f}, Cur:{currency_code}, TXID:{txid}"
                    )
                    processed_count += 1

                    # Optional: Update related CryptoPayment record (consider service call)
                    # ... (existing commented-out code) ...

                except InsufficientFundsError as ife: # Should NOT happen for credit
                    logger.critical(f"{log_prefix} CRITICAL: Ledger credit failed (InsufficientFundsError) for DEPOSIT! "
                                    f"User:{user.username}, Amount:{amount:.8f}, TXID:{txid}. Error: {ife}", exc_info=True)
                    failed_credit_count += 1
                except (DjangoValidationError, IntegrityError) as ve: # DB/Validation errors
                    logger.critical(f"{log_prefix} CRITICAL: Ledger credit failed (Validation/Integrity). "
                                    f"User:{user.username}, Amount:{amount:.8f}, TXID:{txid}. Error: {ve}", exc_info=True)
                    failed_credit_count += 1
                except DatabaseError as dbe: # Potential transient DB error during credit
                     logger.critical(f"{log_prefix} CRITICAL: Ledger credit failed (DatabaseError). "
                                    f"User:{user.username}, Amount:{amount:.8f}, TXID:{txid}. Error: {dbe}", exc_info=True)
                     failed_credit_count += 1
                     # Re-raise to potentially trigger task retry? Or just mark failed? For now, mark failed.
                except Exception as e: # Other unexpected errors
                    logger.critical(f"{log_prefix} CRITICAL: Unexpected failure during ledger credit. "
                                    f"User:{user.username}, Amount:{amount:.8f}, TXID:{txid}. Error: {e}", exc_info=True)
                    failed_credit_count += 1

                # --- Update Max Processed Height ---
                if height is not None and height > new_max_height_processed:
                    new_max_height_processed = height

            # --- Update Last Checked Height in DB (after loop, inside lock) ---
            # Only update if the scan completed and we didn't encounter critical errors
            # preventing progress (though individual credit failures are logged above).
            if new_max_height_processed >= last_height:
                set_last_checked_block(currency_code, new_max_height_processed)
            else:
                logger.warning(
                    f"{log_prefix} Not updating last checked block. "
                    f"Max processed height ({new_max_height_processed}) "
                    f"is not >= last checked ({last_height})."
                )

        except Ignore: # Propagate Ignore exception if raised intentionally (e.g., by nested call)
             raise
        except Exception as e:
            # Catch errors during the main scan or processing loop (e.g., service call failure)
            # This will be caught by Celery's autoretry if applicable, or mark task as failed
            logger.exception(f"{log_prefix} Error during deposit check execution: {e}")
            # Do *not* update last_checked_block on general task failure within the lock
            raise # Re-raise to allow Celery retry/failure handling

        finally:
            # --- Log Summary ---
            summary = (
                f"{currency_code.upper()} deposit check ({task_id}) finished. "
                f"Successfully Credited: {processed_count}, "
                f"Skipped (Already Credited): {skipped_existing_count}, "
                f"Skipped (Invalid Data): {skipped_invalid_data_count}, "
                f"Failed Credits: {failed_credit_count}. "
                f"Highest Block Processed: {new_max_height_processed}"
            )
            logger.info(f"{log_prefix} {summary}")
            if failed_credit_count > 0:
                 logger.critical(f"{log_prefix} ATTENTION: {failed_credit_count} critical ledger credit failures occurred.")
                 # Add alerting hook here

    except Ignore: # Catch Ignore exception raised due to lock contention
         logger.info(f"{log_prefix} Task ignored due to lock contention or explicit request.")
         # Task run is skipped gracefully
    except Exception as e:
         # Catch errors acquiring/releasing lock or unexpected issues
         logger.exception(f"{log_prefix} Unhandled exception in deposit check task wrapper: {e}")
         # Re-raise ensures Celery knows the task ultimately failed if not Ignored
         raise
    finally:
        # --- Release Lock ---
        if lock and lock.locked():
            try:
                lock.release()
                logger.info(f"{log_prefix} Released lock: {lock_key}")
            except Exception as release_err:
                # Log error if release fails, though lock will eventually expire in Redis
                logger.error(f"{log_prefix} Failed to release lock '{lock_key}': {release_err}", exc_info=True)
    # <<< END CHANGE [Rev 1.0]


# <<< CHANGE [Rev 1.0] Added autoretry_for and adjusted checks
@shared_task(
    name="check_xmr_deposits",
    ignore_result=True,
    time_limit=TASK_DEPOSIT_CHECK_TIME_LIMIT,
    soft_time_limit=TASK_DEPOSIT_CHECK_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS), # Retry on network/DB issues from service/helpers
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 5,
    retry_jitter=True
)
@check_dependencies('User', 'LedgerTransaction', 'ledger_service', 'monero_service', 'GlobalSettings', 'redis_lock')
def check_xmr_deposits(self: Task):
    """ Checks XMR deposits, credits ledger. Includes locking and retries. """
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_XMR,
        scan_service_func=monero_service.scan_for_new_deposits,
        amount_field='amount_xmr'
    )

@shared_task(
    name="check_btc_deposits",
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
@check_dependencies('User', 'LedgerTransaction', 'ledger_service', 'bitcoin_service', 'GlobalSettings', 'redis_lock')
def check_btc_deposits(self: Task):
    """ Checks BTC deposits, credits ledger. Includes locking and retries. """
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_BTC,
        scan_service_func=bitcoin_service.scan_for_new_deposits,
        amount_field='amount_btc'
    )

@shared_task(
    name="check_eth_deposits",
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
@check_dependencies('User', 'LedgerTransaction', 'ledger_service', 'ethereum_service', 'GlobalSettings', 'redis_lock')
def check_eth_deposits(self: Task):
    """ Checks ETH deposits, credits ledger. Includes locking and retries. """
    _perform_deposit_check(
        task_instance=self, currency_code=CURRENCY_ETH,
        scan_service_func=ethereum_service.scan_for_new_deposits,
        amount_field='amount_eth'
    )
# <<< END CHANGE [Rev 1.0]


# <<< CHANGE [Rev 1.0] Added autoretry_for, uncommented retry logic
@shared_task(
    name="update_all_vendor_reputations_task",
    time_limit=TASK_REPUTATION_TIME_LIMIT,
    soft_time_limit=TASK_REPUTATION_SOFT_TIME_LIMIT,
    bind=True,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS), # Retry on network/DB issues from service
    retry_kwargs={'max_retries': TASK_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RETRY_DELAY * 10, # Longer delay potentially acceptable here
    retry_jitter=True
)
@check_dependencies('reputation_service')
def update_all_vendor_reputations_task(self: Task):
    """ Periodically updates vendor reputations via service, with retries. """
    task_id = self.request.id
    log_prefix = f"[VendorReputationUpdate:{task_id}]"
    logger.info(f"{log_prefix} Starting periodic vendor reputation update task.")

    if not hasattr(reputation_service, 'update_all_vendor_reputations'):
         error_msg = f"{log_prefix} CRITICAL: Service function 'update_all_vendor_reputations' missing."
         logger.critical(error_msg)
         return "Task Aborted: Service function missing."

    try:
        # Call service, assuming it might raise transient errors handled by autoretry
        result_summary = reputation_service.update_all_vendor_reputations()
        success_msg = f"{log_prefix} Periodic vendor reputation update task completed successfully."
        if result_summary:
            logger.info(f"{success_msg} Service summary: {result_summary}")
        else:
            logger.info(success_msg)
        return f"Reputation update cycle finished. Task ID: {task_id}"

    except Exception as e:
        # Catch non-retryable or unexpected errors after retries fail
        logger.exception(f"{log_prefix} Error during periodic vendor reputation update after potential retries: {e}")
        # Ensure Celery knows the task failed permanently after exhausting retries
        # The exception will be re-raised by Celery's mechanism if not caught here after retries.
        # Log it critically here for visibility.
        logger.critical(f"{log_prefix} Vendor reputation update failed permanently after retries or due to non-transient error.")
        # Depending on Celery config, this might raise MaxRetriesExceededError or the original exception.
        # No need to explicitly return "Task Failed" here if exception is raised.
        raise # Re-raise the final exception
# <<< END CHANGE [Rev 1.0]


# --- Celery Beat Schedule Reminder ---
# (Keep the reminder comment as it's useful context)
# ... existing comment ...
# --- Celery Beat Schedule Reminder ---
# Ensure the following (or similar) configuration exists in your Django settings
# (e.g., settings/base.py, settings/celery.py, or wherever CELERY_BEAT_SCHEDULE is defined)
# from celery.schedules import crontab
#
# CELERY_BEAT_SCHEDULE = {
#     'check-all-deposits-every-few-minutes': {
#         'task': 'store.tasks.check_all_deposits',
#         'schedule': timedelta(minutes=3), # Adjust frequency as needed
#         'options': {'expires': 150.0}, # Example: Task expires if not started in 150s
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
#          'task': 'ledger.tasks.reconcile_ledger_balances', # Assuming task exists in ledger app
#          'schedule': crontab(hour=3, minute=0),
#      },
# }