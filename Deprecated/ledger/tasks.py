# backend/ledger/tasks.py
# --- Revision History ---
# [Rev 1.0 - 2025-04-07]
#   - Added Explicit Retries: Incorporated Celery's `autoretry_for` to handle transient errors
#     during node balance fetching (e.g., ConnectionError) or DB aggregation (e.g., DatabaseError).
#   - Added Distributed Locking: Implemented optional Redis-based distributed lock to ensure
#     only one instance of the reconciliation task runs at a time, preventing redundant checks
#     and potential log/alert noise. Requires `django-redis-lock`.
#   - Enhanced Error Handling: Clarified logging for different error types within the loop.
#   - Added Reminders: Included explicit comments reminding the user to implement the
#     `_trigger_alert` function with a real alerting system and to ensure proper DB indexing
#     on UserBalance model.
#   - Configuration: Made `CURRENCY_CONFIG` loading slightly more robust.
# ------------------------

import logging
from decimal import Decimal, InvalidOperation, getcontext
from typing import Dict, List, Optional, Any, Tuple

from celery import shared_task, Task # <<< CHANGE [Rev 1.0] Import Task for bind=True
from celery.exceptions import Ignore

from django.conf import settings
from django.db import models
from django.db.utils import OperationalError, DatabaseError # Catch specific DB errors

# --- Third-Party Imports ---
try:
    import redis_lock
except ImportError:
    redis_lock = None

# <<< CHANGE [Rev 1.0] Import common potentially transient errors for retries
try:
    import requests
    CONNECTION_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
except ImportError:
    CONNECTION_ERRORS = () # Define empty tuple if requests not used/installed

TRANSIENT_DB_ERRORS = (OperationalError, DatabaseError) # Errors during DB query execution
# <<< END CHANGE [Rev 1.0]


# --- Configuration ---
# getcontext().prec = 28 # Example: Uncomment if needed

logger = logging.getLogger(__name__)
# Use a dedicated security logger for sensitive financial discrepancies
# Ensure 'finance.security' is configured in settings.LOGGING
security_logger = logging.getLogger('finance.security')

# <<< CHANGE [Rev 1.0] Define constants for lock/retry
TASK_RECONCILE_TIME_LIMIT = 1800 # 30 minutes (adjust as needed)
TASK_RECONCILE_SOFT_TIME_LIMIT = 1780
TASK_RECONCILE_RETRY_DELAY = 120 # Seconds between retries
TASK_RECONCILE_MAX_RETRIES = 2 # Fewer retries might be suitable for reconciliation
RECONCILE_LOCK_KEY = "lock_ledger_reconciliation"
RECONCILE_LOCK_ACQUIRE_TIMEOUT = 15 # Seconds to wait for lock
RECONCILE_LOCK_EXPIRY = TASK_RECONCILE_SOFT_TIME_LIMIT + 60 # Lock expiry buffer
# <<< END CHANGE [Rev 1.0]

# --- Service and Model Imports ---
_dependencies_loaded = False
UserBalance = None
monero_service = None
bitcoin_service = None
ethereum_service = None
CURRENCY_CONFIG: Dict[str, Dict[str, Any]] = {}

try:
    from ledger.models import UserBalance
    from store.services import monero_service, bitcoin_service, ethereum_service

    # --- Currency Configuration ---
    # Move definition inside try block to ensure services are loaded first
    CURRENCY_CONFIG = {
        'XMR': {
            'service': monero_service,
            'balance_func_name': 'get_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'],
            'precision': 12,
        },
        'BTC': {
            'service': bitcoin_service,
            'balance_func_name': 'get_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'],
            'precision': 8,
        },
        'ETH': {
            'service': ethereum_service,
            'balance_func_name': 'get_market_hot_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'],
            'precision': 18,
            # 'relevant_address': settings.ETH_MARKET_HOT_WALLET_ADDRESS, # If needed
        },
    }

    # Basic check for critical components
    if not UserBalance or not all(cfg.get('service') for cfg in CURRENCY_CONFIG.values()):
         raise ImportError("UserBalance model or one or more configured services failed to import/load.")

    _dependencies_loaded = True

except ImportError as e:
    logger.critical(f"CRITICAL IMPORT ERROR in ledger/tasks.py: {e}. Reconciliation task cannot run correctly.")
    # Placeholders remain None or empty


# --- Alerting Placeholder ---

def _trigger_alert(level: str, summary: str, details: str):
    """
    *** PLACEHOLDER - IMPLEMENTATION REQUIRED ***
    This function MUST be implemented to trigger real external alerts
    (e.g., PagerDuty, Sentry custom event, Email, Slack) for production use.
    The current implementation only logs intensely.
    """
    log_message = f"ALERT [{level.upper()}] Required: {summary} - Details: {details}"
    if level.lower() == 'critical':
        security_logger.critical(log_message)
    elif level.lower() == 'error':
        logger.error(log_message, exc_info=True if level.lower()=='error' else False) # Include stack trace for errors
    else:
        logger.warning(log_message)

    # --- !!! REPLACE WITH YOUR ACTUAL ALERTING CODE BELOW !!! ---
    # Example:
    # try:
    #   import your_alerting_system
    #   your_alerting_system.send(...)
    # except Exception as alert_err:
    #   logger.error(f"Failed to send external alert via custom system: {alert_err}")
    # --- End Alerting Placeholder ---
    pass


# --- Helper Function ---

def _get_decimal_places(precision: int) -> str:
    """ Creates a format string for Decimal precision. """
    # Basic validation for precision value
    if not isinstance(precision, int) or precision < 0:
        logger.warning(f"Invalid precision '{precision}' provided, defaulting to 8 decimal places.")
        precision = 8
    return f".{precision}f"


# --- Main Reconciliation Task ---

# <<< CHANGE [Rev 1.0] Added bind=True, time limits, autoretry_for
@shared_task(
    name="ledger.reconcile_balances",
    bind=True, # Bind self for task context (needed for retry/request info)
    time_limit=TASK_RECONCILE_TIME_LIMIT,
    soft_time_limit=TASK_RECONCILE_SOFT_TIME_LIMIT,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS), # Retry on network/DB issues
    retry_kwargs={'max_retries': TASK_RECONCILE_MAX_RETRIES},
    retry_backoff=True,
    retry_backoff_max=TASK_RECONCILE_RETRY_DELAY * 2, # Max delay between retries
    retry_jitter=True
)
# <<< END CHANGE [Rev 1.0]
def reconcile_ledger_balances(self: Task): # Add self: Task type hint
    """
    Compares external node/wallet balances against internal ledger totals.
    Uses distributed locking for singleton execution and retries on transient errors.
    Triggers CRITICAL alerts via _trigger_alert for any discrepancies.

    *** REMINDER: Ensure appropriate DB indexes exist on UserBalance(currency, balance, locked_balance) ***
    """
    task_id = self.request.id # Get task ID for logging
    log_prefix = f"[ReconcileLedger:{task_id}]"

    # --- Initial Dependency Check ---
    if not _dependencies_loaded:
        message = f"{log_prefix} Task Aborted: Critical dependencies (models/services) failed to load during startup."
        logger.critical(message)
        # Alert immediately if dependencies are missing, as task cannot run.
        _trigger_alert("critical", "Ledger Reconciliation Aborted", message)
        # No retry needed here, this is a startup/config issue.
        return {"status": "FATAL", "reason": "Missing dependencies"}

    # --- Distributed Lock Acquisition --- # <<< CHANGE [Rev 1.0] Add Lock
    if redis_lock is None:
        logger.critical(f"{log_prefix} Aborting task: 'django-redis-lock' library not available. Cannot ensure singleton execution.")
        _trigger_alert("critical", "Ledger Reconciliation Aborted", "redis_lock library missing")
        return {"status": "FATAL", "reason": "Missing redis_lock library"}

    lock = None
    try:
        logger.info(f"{log_prefix} Attempting to acquire lock: {RECONCILE_LOCK_KEY}")
        lock = redis_lock.Lock(
             _redis=None, name=RECONCILE_LOCK_KEY,
             expire=RECONCILE_LOCK_EXPIRY, id=task_id
        )
        # Try non-blocking first
        if not lock.acquire(blocking=False):
            logger.warning(f"{log_prefix} Lock '{RECONCILE_LOCK_KEY}' already held. Waiting up to {RECONCILE_LOCK_ACQUIRE_TIMEOUT}s...")
            if not lock.acquire(blocking=True, timeout=RECONCILE_LOCK_ACQUIRE_TIMEOUT):
                 logger.warning(f"{log_prefix} Could not acquire lock '{RECONCILE_LOCK_KEY}' after waiting. Another instance likely running. Skipping this run.")
                 raise Ignore() # Use Ignore to skip gracefully without failure/retry

        logger.info(f"{log_prefix} Successfully acquired lock: {RECONCILE_LOCK_KEY}. Starting reconciliation.")

        # --- Main Reconciliation Logic (Inside Lock) ---
        currencies_to_check = list(CURRENCY_CONFIG.keys())
        if not currencies_to_check:
             # Fallback check (redundant if CURRENCY_CONFIG load check works, but safe)
             currencies_to_check = getattr(settings, 'SUPPORTED_CURRENCIES', [])
             if not currencies_to_check:
                 logger.warning(f"{log_prefix} No currencies configured in CURRENCY_CONFIG or SUPPORTED_CURRENCIES. Task exiting.")
                 # Release lock before returning
                 if lock and lock.locked(): lock.release()
                 return {"status": "SUCCESS", "reason": "No currencies configured"}

        results: Dict[str, Dict[str, Any]] = {}
        overall_discrepancy_found = False # Tracks if *any* currency failed or had discrepancy

        for currency in currencies_to_check:
            # Reset state for current currency
            node_balance: Optional[Decimal] = None
            ledger_total: Optional[Decimal] = None
            config = CURRENCY_CONFIG.get(currency)
            status = "PENDING"
            error_message = None
            node_balance_str = "N/A"
            ledger_total_str = "N/A"
            difference_str = "N/A"

            if not config:
                logger.warning(f"{log_prefix} Skipping {currency}: No configuration found in CURRENCY_CONFIG.")
                results[currency] = {"status": "SKIPPED", "reason": "Not configured"}
                continue

            service = config.get('service')
            balance_func_name = config.get('balance_func_name')
            ledger_fields = config.get('ledger_aggregation_fields', ['balance'])
            precision = config.get('precision', 8)
            decimal_format = _get_decimal_places(precision)

            logger.debug(f"{log_prefix} Reconciling {currency}: Config = {config}")

            try:
                # --- 1. Get Node Wallet Balance ---
                if not service or not balance_func_name or not hasattr(service, balance_func_name):
                    raise ValueError(f"Service or balance function '{balance_func_name}' not configured correctly for {currency}.")

                logger.debug(f"{log_prefix} Fetching node balance for {currency} via {service.__class__.__name__}.{balance_func_name}...")
                balance_func = getattr(service, balance_func_name)
                # node_balance_raw = balance_func(address=config.get('relevant_address')) # If address needed
                node_balance_raw = balance_func() # Assuming no args

                if node_balance_raw is None:
                    # This indicates a potentially recoverable issue with the node/service call
                    # Let autoretry_for handle ConnectionError etc., but raise specific error if None returned unexpectedly
                    raise ValueError(f"Node balance query unexpectedly returned None for {currency}. Check service implementation.")

                try:
                    node_balance = Decimal(str(node_balance_raw))
                    node_balance_str = format(node_balance, decimal_format)
                except (InvalidOperation, TypeError) as conv_err:
                    logger.error(f"{log_prefix} Invalid balance format received from node for {currency}: Type={type(node_balance_raw)}, Value='{str(node_balance_raw)[:100]}...'. Error: {conv_err}")
                    raise ValueError(f"Invalid balance format from node: {conv_err}") from conv_err

                logger.debug(f"{log_prefix} {currency} Node Balance Raw: {node_balance_raw}, Decimal: {node_balance_str}")

                # --- 2. Get Total Ledger Balance ---
                logger.debug(f"{log_prefix} Calculating ledger total for {currency} from fields: {ledger_fields}...")
                if not UserBalance: raise RuntimeError("UserBalance model is not available.") # Should be caught earlier

                # Ensure ledger fields are valid DecimalFields on the model
                valid_fields = []
                for field_name in ledger_fields:
                     try:
                         field_obj = UserBalance._meta.get_field(field_name)
                         if isinstance(field_obj, models.DecimalField):
                             valid_fields.append(field_name)
                         else:
                             logger.warning(f"{log_prefix} Configured ledger field '{field_name}' for {currency} is not a DecimalField on UserBalance model. Skipping field.")
                     except models.FieldDoesNotExist:
                         logger.warning(f"{log_prefix} Configured ledger field '{field_name}' for {currency} does not exist on UserBalance model. Skipping field.")

                if not valid_fields:
                     raise ValueError(f"No valid DecimalFields found for ledger aggregation for {currency} based on config: {ledger_fields}")

                aggregation_expressions = {
                    f"sum_{field}": models.Sum(field, default=Decimal('0.0'), output_field=models.DecimalField())
                    for field in valid_fields
                }

                # This DB query might raise OperationalError/DatabaseError caught by autoretry_for
                aggregation_result = UserBalance.objects.filter(currency=currency).aggregate(**aggregation_expressions)

                ledger_total = sum(aggregation_result.get(f"sum_{field}", Decimal('0.0')) for field in valid_fields)
                ledger_total_str = format(ledger_total, decimal_format)
                logger.debug(f"{log_prefix} {currency} Ledger Total calculated ({', '.join(valid_fields)}): {ledger_total_str}")

                # --- 3. Compare Balances ---
                logger.info(f"{log_prefix} Reconciliation Check {currency}: Node={node_balance_str}, Ledger={ledger_total_str}")
                if node_balance != ledger_total:
                    difference = node_balance - ledger_total
                    difference_str = format(difference, decimal_format)
                    overall_discrepancy_found = True
                    status = "FAILED"
                    error_message = (
                        f"CRITICAL LEDGER DISCREPANCY [{currency}]! Diff: {difference_str} {currency}. "
                        f"Node: {node_balance_str}, Ledger: {ledger_total_str}. IMMEDIATE INVESTIGATION REQUIRED."
                    )
                    security_logger.critical(error_message)
                    _trigger_alert("critical", f"Ledger Discrepancy: {currency}", error_message)
                    logger.info(f"{log_prefix} Ledger reconciliation FAILED for {currency}. Difference: {difference_str}")
                else:
                    status = "SUCCESS"
                    logger.info(f"{log_prefix} Ledger reconciliation PASSED for {currency}.")

            # --- Per-Currency Error Handling (Errors not caught by autoretry) ---
            except (ValueError, TypeError, InvalidOperation, RuntimeError) as config_or_logic_err:
                # Errors related to configuration, data parsing (non-Decimal), or logic issues within this loop
                status = "ERROR"
                error_message = f"Error processing {currency}: {config_or_logic_err}"
                logger.error(f"{log_prefix} {error_message}", exc_info=True) # Include stack trace for these errors
                _trigger_alert("error", f"Ledger Reconciliation Error: {currency}", error_message)
                overall_discrepancy_found = True # Treat these errors as needing investigation

            except Exception as e:
                # Catch any other unexpected errors for this specific currency
                # This should ideally not be reached if specific errors and autoretry handle known cases.
                status = "ERROR"
                error_message = f"Unexpected error during reconciliation for {currency}: {e}"
                logger.exception(f"{log_prefix} {error_message}") # Log stack trace
                _trigger_alert("error", f"Ledger Reconciliation Unexpected Error: {currency}", error_message)
                overall_discrepancy_found = True
                # Do NOT re-raise here, allow task to continue checking other currencies.
                # The main task might retry if the error was transient DB/Connection related.

            # Store results for this currency
            results[currency] = {
                "status": status,
                "node_balance": node_balance_str,
                "ledger_total": ledger_total_str,
                "difference": difference_str if status == "FAILED" else "N/A",
                "error": error_message if status in ["ERROR", "FAILED"] else None,
            }

        # --- End of Currency Loop ---

        # --- Final Summary (Inside Lock) ---
        final_status = "FAILED" if overall_discrepancy_found else "SUCCESS"
        summary_message = f"{log_prefix} Ledger Reconciliation Task finished with overall status: {final_status}."

        if overall_discrepancy_found:
            logger.critical(summary_message + " Discrepancies or errors detected.")
            # Optional: Trigger a summary alert
            _trigger_alert("warning", "Ledger Reconciliation Completed with Issues", f"Details: {results}")
        else:
            logger.info(summary_message + " All configured currency balances match.")

        return {"status": final_status, "results": results}

    except Ignore: # Catch Ignore exception raised due to lock contention
         logger.info(f"{log_prefix} Task ignored due to lock contention or explicit request.")
         # Task run is skipped gracefully, return value indicates skipped status maybe?
         return {"status": "SKIPPED", "reason": "Lock contended or Ignore raised"}
    except Exception as e:
         # Catch errors acquiring lock or other unexpected issues OUTSIDE the loop
         # These might be candidates for retry if transient. If autoretry is configured,
         # Celery handles it. Log critically here.
         logger.exception(f"{log_prefix} Unhandled exception in reconciliation task wrapper: {e}")
         _trigger_alert("critical", "Ledger Reconciliation Task Failed Critically", f"Error: {e}")
         # Re-raise allows Celery's retry/failure mechanism to take over
         raise
    finally:
        # --- Release Lock ---
        if lock and lock.locked():
            try:
                lock.release()
                logger.info(f"{log_prefix} Released lock: {RECONCILE_LOCK_KEY}")
            except Exception as release_err:
                logger.error(f"{log_prefix} Failed to release lock '{RECONCILE_LOCK_KEY}': {release_err}", exc_info=True)
    # <<< END CHANGE [Rev 1.0]