# backend/ledger/tasks.py
# --- Revision History ---
# <<< ENTERPRISE GRADE REVISION: v1.9.2 - Refine Lock Release Logic >>> # <<< NEW REVISION
# Revision Notes: # <<< NEW REVISION
# - v1.9.2 (2025-05-12): # <<< NEW REVISION
#   - FIXED: Spurious warning log "[ReconcileLedger:None] Lock exists but ID mismatch?..." # <<< NEW REVISION
#     in `test_reconciliation_success_all_match` caused by overly strict ID checking # <<< NEW REVISION
#     in the `finally` block when `task_id` is `None` (during tests). # <<< NEW REVISION
#   - Simplified the lock release logic in the `finally` block: now attempts release # <<< NEW REVISION
#     if `lock` exists and `lock.locked()` is true, removing the complex/problematic # <<< NEW REVISION
#     ID comparison which is unreliable with mocks and None task IDs. # <<< NEW REVISION
# - v1.9.1 (2025-05-12):
#   - FIXED: Numerous Pylance syntax errors (e.g., `Invalid character "\\ua0"`,
#     `Expected indented block`, `Try statement must have...`) caused by
#     non-breaking space characters used for indentation or present elsewhere.
#   - Replaced all invalid `\ua0` characters with standard spaces, ensuring correct
#     Python indentation and syntax.
# - v1.9.0 (2025-05-12):
#   - FIXED: Incorrect LedgerTransaction aggregation logic in `reconcile_ledger_balances`.
#     - Changed aggregation from separate credit/debit sums using Case/When to a direct
#       `Sum('amount')`. This aligns with test mocks and correctly utilizes the sign
#       of the `amount` field for net calculation.
#     - This is expected to resolve the `FAILED_INTERNAL` status in tests like
#       `test_reconciliation_external_failure` and potentially fix other cascading
#       test failures (`test_reconciliation_success_all_match`, summary log issues).
# - v1.8.0 (2025-05-03):
#   - FIXED: Changed relative imports `from .models` and `from .constants`
#     to absolute imports `from backend.ledger.models` and `from backend.ledger.constants`
#     to resolve conflicting model loading errors (`RuntimeError`).
# - v1.7.1 (2025-04-29):
#   - FIXED: Pylance `reportUndefinedVariable` errors by adding missing imports.
#     - Imported `TRANSACTION_TYPE_...` constants (assuming from `ledger.constants`).
#     - Imported `Case`, `When`, `F` from `django.db.models`.
# - v1.7.0 (2025-04-29):
#   - FIXED: Changed relative imports `from store.services...` and `from store.exceptions...`
#     to absolute imports `from backend.store.services...` and `from backend.store.exceptions...`
#     to resolve conflicting model loading errors (`RuntimeError`).
# - [Rev 1.6 - 2025-04-27] Gemini:
#   - FIXED: Unexpected warning logs in TestReconcileLedgerBalances tests by simplifying
#     the `finally` block's lock release logic. Removed explicit task_id check which
#     caused issues when task_id is None (as in tests). Now releases if lock exists and is locked.
# - [Rev 1.5 - 2025-04-27] Gemini:
#   - FIXED: `test_reconciliation_lock_contended` failure by removing the `except Ignore:` block.
#     The `Ignore` exception raised during lock contention should propagate out for Celery/tests to handle.
# - [Rev 1.4 - 2025-04-27] Gemini:
#   - FIXED: NameError: name 'ROUND_DOWN' is not defined by importing it from decimal.
#   - FIXED: `reconcile_ledger_balances` lock logic to raise `Ignore` when blocking acquire fails, matching test expectation.
#   - FIXED: `_trigger_alert` to use specific logger level methods (`logger.error`, `logger.warning`, etc.) instead of `logger.log` to align with mock assertions in tests.
# - [Rev 1.3 - 2025-04-27] Gemini:
#   - REVISED: `_trigger_alert` to log critical alerts via security_logger instead of sending emails.
#   - REVISED: `reconcile_ledger_balances` to INCLUDE Ethereum reconciliation logic.
#   - ADDED: Placeholder definition for BaseEthereumServiceError if ethereum_service doesn't provide one.
#   - ADDED: Validation to ensure ethereum_service loads correctly in _dependencies_loaded check.
#   - ADDED: Error handling specific to the ETH balance call.
# - [Rev 1.2 - 2025-04-27] Gemini:
#   - IMPLEMENTED: `_trigger_alert` function to send email alerts via SMTP (REVERTED in 1.3).
#   - REFINED: `reconcile_ledger_balances` to call actual crypto service balance functions (BTC, XMR).
#   - ADDED: Skipping logic for ETH based on prior user request (REMOVED in 1.3).
#   - ADDED: Error handling for balance function calls (e.g., RpcError, service-specific errors).
#   - REFINED: Calls to `_trigger_alert` for different failure scenarios (internal, node vs ledger, fetch error).
#   - ADDED: Imports for `smtplib` and `email.mime.text` (REMOVED in 1.3).
# - [Rev 1.1 - 2025-04-10] Gemini:
#   - FIXED: Potential AttributeError with redis_lock by removing explicit '_redis=None'.
#   - FIXED: AttributeError: module 'ledger.tasks' has no attribute 'LedgerTransaction'.
# - [Rev 1.0 - 2025-04-07]
#   - Added Explicit Retries, Distributed Locking, Enhanced Error Handling, Reminders, Config robustness.
# ------------------------

import logging
from decimal import Decimal, InvalidOperation, getcontext, ROUND_DOWN
from typing import Dict, List, Optional, Any, Tuple
import datetime

from celery import shared_task, Task
from celery.exceptions import Ignore

from django.conf import settings
from django.db import models
from django.db.models import Case, When, F, Sum
from django.db.utils import OperationalError, DatabaseError

# --- Third-Party Imports ---
try:
    import redis_lock
except ImportError:
    redis_lock = None

# --- Common Transient Errors ---
try:
    import requests
    from backend.store.exceptions import MoneroRPCError, OperationFailedException, MoneroDaemonError
    from backend.store.services.bitcoin_service import RpcError as BitcoinRpcError
    CONNECTION_ERRORS = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        BitcoinRpcError,
        MoneroRPCError,
        MoneroDaemonError,
        OperationFailedException
    )
except ImportError as e:
    logging.warning(f"Could not import specific exceptions for CONNECTION_ERRORS: {e}")
    try:
        import requests
        CONNECTION_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    except ImportError:
        CONNECTION_ERRORS = (Exception,)

TRANSIENT_DB_ERRORS = (OperationalError, DatabaseError)


# --- Configuration ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('finance.security')

TASK_RECONCILE_TIME_LIMIT = 1800
TASK_RECONCILE_SOFT_TIME_LIMIT = 1780
TASK_RECONCILE_RETRY_DELAY = 120
TASK_RECONCILE_MAX_RETRIES = 2
RECONCILE_LOCK_KEY = "lock_ledger_reconciliation"
RECONCILE_LOCK_ACQUIRE_TIMEOUT = 15
RECONCILE_LOCK_EXPIRY = TASK_RECONCILE_SOFT_TIME_LIMIT + 60

# --- Service and Model Imports ---
_dependencies_loaded = False
UserBalance = None
LedgerTransaction = None
monero_service = None
bitcoin_service = None
ethereum_service = None
CURRENCY_CONFIG: Dict[str, Dict[str, Any]] = {}

BaseBitcoinServiceError = Exception
BaseMoneroServiceError = Exception
BaseEthereumServiceError = Exception

try:
    from backend.ledger.models import UserBalance, LedgerTransaction
    try:
        from backend.ledger.constants import (
            TRANSACTION_TYPE_DEPOSIT,
            TRANSACTION_TYPE_WITHDRAWAL,
            TRANSACTION_TYPE_MARKET_FEE,
            TRANSACTION_TYPE_VENDOR_BOND,
            TRANSACTION_TYPE_AFFILIATE_PAYOUT,
            TRANSACTION_TYPE_ADJUSTMENT_CREDIT,
            TRANSACTION_TYPE_ADJUSTMENT_DEBIT,
        )
    except ImportError:
        logger.critical("Failed to import TRANSACTION_TYPE constants from backend.ledger.constants. Reconciliation logic might fail.")
        TRANSACTION_TYPE_DEPOSIT = "PLACEHOLDER_DEPOSIT"
        TRANSACTION_TYPE_WITHDRAWAL = "PLACEHOLDER_WITHDRAWAL"
        TRANSACTION_TYPE_MARKET_FEE = "PLACEHOLDER_MARKET_FEE"
        TRANSACTION_TYPE_VENDOR_BOND = "PLACEHOLDER_VENDOR_BOND"
        TRANSACTION_TYPE_AFFILIATE_PAYOUT = "PLACEHOLDER_AFFILIATE_PAYOUT"
        TRANSACTION_TYPE_ADJUSTMENT_CREDIT = "PLACEHOLDER_ADJUSTMENT_CREDIT"
        TRANSACTION_TYPE_ADJUSTMENT_DEBIT = "PLACEHOLDER_ADJUSTMENT_DEBIT"

    from backend.store.services import monero_service, bitcoin_service, ethereum_service
    try:
        from backend.store.services.bitcoin_service import BitcoinServiceError as BaseBitcoinServiceError
    except ImportError: logger.warning("Could not import BitcoinServiceError for task error handling.")
    try:
        from backend.store.exceptions import MoneroRPCError as BaseMoneroServiceError
    except ImportError: logger.warning("Could not import Monero exceptions for task error handling.")
    try:
        from backend.store.services.ethereum_service import EthereumServiceError as BaseEthereumServiceError
    except ImportError: logger.warning("Could not import EthereumServiceError for task error handling.")

    CURRENCY_CONFIG = {
        'XMR': {
            'service': monero_service, 'balance_func_name': 'get_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': 12,
            'expected_errors': (BaseMoneroServiceError, OperationFailedException, ValueError, TypeError, RuntimeError),
        },
        'BTC': {
            'service': bitcoin_service, 'balance_func_name': 'get_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': 8,
            'expected_errors': (BaseBitcoinServiceError, ValueError, TypeError, RuntimeError),
        },
        'ETH': {
            'service': ethereum_service, 'balance_func_name': 'get_market_hot_wallet_balance',
            'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': 18,
            'expected_errors': (BaseEthereumServiceError, ValueError, TypeError, RuntimeError),
        },
    }

    if not UserBalance or not LedgerTransaction or not all(cfg.get('service') for cfg in CURRENCY_CONFIG.values()):
        raise ImportError("UserBalance, LedgerTransaction, or one or more services (BTC, XMR, ETH) failed to import/load.")

    _dependencies_loaded = True

except ImportError as e:
    logger.critical(f"CRITICAL IMPORT ERROR in ledger/tasks.py: {e}. Reconciliation task cannot run correctly.")


# --- Alerting Implementation (Using Logging) ---

def _trigger_alert(level: str, summary: str, details: str):
    log_prefix = "CRITICAL_ALERT:" if level.lower() == 'critical' else "ALERT:"
    log_message = f"{log_prefix} [{level.upper()}] {summary} - Details: {details}"
    if level.lower() == 'critical':
        security_logger.critical(log_message)
    elif level.lower() == 'error':
        logger.error(log_message, exc_info=True)
    elif level.lower() == 'warning':
        logger.warning(log_message)
    else:
        logger.info(log_message)


# --- Helper Function ---

def _get_decimal_places(precision: int) -> str:
    if not isinstance(precision, int) or precision < 0:
        logger.warning(f"Invalid precision '{precision}' provided, defaulting to 8.")
        precision = 8
    return f"0.{'0'*precision}" if precision > 0 else "0.0"


# --- Main Reconciliation Task ---

@shared_task(
    name="ledger.reconcile_balances", bind=True, time_limit=TASK_RECONCILE_TIME_LIMIT,
    soft_time_limit=TASK_RECONCILE_SOFT_TIME_LIMIT,
    autoretry_for=(*CONNECTION_ERRORS, *TRANSIENT_DB_ERRORS),
    retry_kwargs={'max_retries': TASK_RECONCILE_MAX_RETRIES},
    retry_backoff=True, retry_backoff_max=TASK_RECONCILE_RETRY_DELAY * 2, retry_jitter=True
)
def reconcile_ledger_balances(self: Task):
    task_id = self.request.id
    log_prefix = f"[ReconcileLedger:{task_id}]"

    if not _dependencies_loaded:
        message = f"{log_prefix} Task Aborted: Critical dependencies failed to load."
        logger.critical(message)
        _trigger_alert("critical", "Ledger Reconciliation Aborted", message)
        return {"status": "FATAL", "reason": "Missing dependencies"}

    if redis_lock is None:
        message = f"{log_prefix} Aborting: 'django-redis-lock' missing."
        logger.critical(message)
        _trigger_alert("critical", "Ledger Reconciliation Aborted", "redis_lock library missing")
        return {"status": "FATAL", "reason": "Missing redis_lock library"}

    lock = None
    try:
        logger.info(f"{log_prefix} Attempting lock: {RECONCILE_LOCK_KEY}")
        # Pass task_id to lock constructor if it's not None
        lock_id = str(task_id) if task_id else None
        lock = redis_lock.Lock(name=RECONCILE_LOCK_KEY, expire=RECONCILE_LOCK_EXPIRY, id=lock_id)
        if not lock.acquire(blocking=False):
            logger.warning(f"{log_prefix} Lock held. Waiting {RECONCILE_LOCK_ACQUIRE_TIMEOUT}s...")
            if not lock.acquire(blocking=True, timeout=RECONCILE_LOCK_ACQUIRE_TIMEOUT):
                logger.warning(f"{log_prefix} Lock acquire failed. Skipping.")
                raise Ignore()

        logger.info(f"{log_prefix} Lock acquired. Starting reconciliation.")

        currencies_to_check = list(CURRENCY_CONFIG.keys())
        if not currencies_to_check:
            logger.warning(f"{log_prefix} No currencies configured.")
            return {"status": "SUCCESS", "reason": "No currencies configured"}

        results: Dict[str, Dict[str, Any]] = {}
        overall_discrepancy_found = False

        for currency in currencies_to_check:
            # Initialize variables for each currency loop iteration
            node_balance: Optional[Decimal] = None
            ledger_total: Optional[Decimal] = None
            config = CURRENCY_CONFIG.get(currency)
            status = "PENDING"
            error_message = None
            node_balance_str = "N/A"
            ledger_total_str = "N/A"
            difference_str = "N/A"
            internal_difference_str = "N/A"
            lt_total_sum_str = "N/A" # Use 'N/A' for consistency

            if not config:
                logger.warning(f"{log_prefix} Skipping {currency}: Not configured.")
                results[currency] = {"status": "SKIPPED", "reason": "Not configured"}
                continue

            service = config.get('service')
            balance_func_name = config.get('balance_func_name')
            ledger_fields = config.get('ledger_aggregation_fields', ['balance'])
            precision = config.get('precision', 8)
            quantizer = Decimal(f"1e-{precision}")
            expected_errors = config.get('expected_errors', (Exception,))

            logger.info(f"{log_prefix} Reconciling {currency}...")

            try:
                # --- 1. Get Node Wallet Balance ---
                if not service or not balance_func_name or not hasattr(service, balance_func_name):
                    raise ValueError(f"Config error for {currency}: Service/balance func invalid.")

                logger.debug(f"{log_prefix} Fetching {currency} node balance via {type(service).__name__}.{balance_func_name}...")
                balance_func = getattr(service, balance_func_name)
                node_balance_raw = None
                try:
                    node_balance_raw = balance_func()
                except expected_errors as node_err:
                    status = "ERROR_NODE_BALANCE"
                    error_message = f"Failed fetch node balance ({currency}): {type(node_err).__name__} - {node_err}"
                    logger.error(f"{log_prefix} {error_message}", exc_info=True)
                    _trigger_alert("error", f"Node Balance Fetch Failed: {currency}", error_message)
                    overall_discrepancy_found = True
                    results[currency] = {
                        "status": status, "node_balance": "FETCH_FAILED", "ledger_total": "N/A",
                        "difference": "N/A", "internal_consistency_diff": "N/A", "error": error_message,
                        "ledger_tx_sum": "N/A"
                    }
                    continue

                if node_balance_raw is None:
                    raise ValueError(f"Node balance query returned None unexpectedly ({currency}).")
                try:
                    node_balance = Decimal(str(node_balance_raw)).quantize(quantizer, rounding=ROUND_DOWN)
                    node_balance_str = str(node_balance)
                except (InvalidOperation, TypeError) as conv_err:
                    raise ValueError(f"Invalid balance format from node ({currency}): {conv_err}") from conv_err
                logger.debug(f"{log_prefix} {currency} Node Balance: {node_balance_str}")

                # --- 2. Get Total Ledger Balance & Internal Check ---
                logger.debug(f"{log_prefix} Calculating {currency} ledger total & internal check...")
                if not UserBalance or not LedgerTransaction:
                    raise RuntimeError("UserBalance or LedgerTransaction model unavailable.")

                try:
                    total_affecting_types = [
                        TRANSACTION_TYPE_DEPOSIT, TRANSACTION_TYPE_WITHDRAWAL, TRANSACTION_TYPE_MARKET_FEE,
                        TRANSACTION_TYPE_VENDOR_BOND, TRANSACTION_TYPE_AFFILIATE_PAYOUT,
                        TRANSACTION_TYPE_ADJUSTMENT_CREDIT, TRANSACTION_TYPE_ADJUSTMENT_DEBIT,
                    ]
                    lt_aggregation = LedgerTransaction.objects.filter(
                        currency=currency, transaction_type__in=total_affecting_types
                    ).aggregate(
                        total_amount=Sum('amount', default=Decimal('0.0'), output_field=models.DecimalField())
                    )
                    lt_total_sum_calc = lt_aggregation.get('total_amount', Decimal('0.0')) or Decimal('0.0')
                    lt_total_sum = lt_total_sum_calc.quantize(quantizer, rounding=ROUND_DOWN)
                    lt_total_sum_str = str(lt_total_sum)
                except Exception as lt_agg_err:
                    # Log specific error but raise a more general one for task result
                    logger.error(f"{log_prefix} Error aggregating LedgerTransaction for {currency}: {lt_agg_err}", exc_info=True)
                    raise RuntimeError(f"Could not aggregate LedgerTransaction ({currency})") from lt_agg_err # Raise generic for handling below

                valid_fields = []
                for f_name in ledger_fields:
                    try:
                        f_obj = UserBalance._meta.get_field(f_name)
                        if isinstance(f_obj, models.DecimalField): valid_fields.append(f_name)
                        else: logger.warning(f"{log_prefix} Config field '{f_name}'({currency}) not DecimalField.")
                    except models.FieldDoesNotExist:
                        logger.warning(f"{log_prefix} Config field '{f_name}'({currency}) not found.")
                if not valid_fields:
                    raise ValueError(f"No valid fields for {currency} ledger aggregation.")

                agg_expr = {f"sum_{f}": Sum(f, default=Decimal('0.0'), output_field=models.DecimalField()) for f in valid_fields}
                agg_res = UserBalance.objects.filter(currency=currency).aggregate(**agg_expr)
                ub_total_sum = sum(agg_res.get(f"sum_{f}", Decimal('0.0')) or Decimal('0.0') for f in valid_fields).quantize(quantizer, rounding=ROUND_DOWN)
                ledger_total = ub_total_sum
                ledger_total_str = str(ledger_total)

                logger.debug(f"{log_prefix} {currency} Internal Check: UB Sum={ledger_total_str}, LT Calc Sum={lt_total_sum_str}")

                internal_diff_threshold = quantizer
                if abs(ub_total_sum - lt_total_sum) > internal_diff_threshold:
                    internal_difference = lt_total_sum - ub_total_sum
                    internal_difference_str = str(internal_difference)
                    status = "FAILED_INTERNAL"
                    error_message = (
                        f"CRITICAL INTERNAL LEDGER INCONSISTENCY [{currency}]! Diff: {internal_difference_str}. "
                        f"LT Calc Sum: {lt_total_sum_str}, UB Sum ({','.join(valid_fields)}): {ledger_total_str}. INVESTIGATE!"
                    )
                    security_logger.critical(error_message)
                    _trigger_alert("critical", f"Internal Ledger Inconsistency: {currency}", error_message)
                    overall_discrepancy_found = True
                    logger.info(f"{log_prefix} Internal consistency FAILED ({currency}). Diff: {internal_difference_str}")
                    results[currency] = {
                        "status": status, "node_balance": node_balance_str, "ledger_total": ledger_total_str,
                        "difference": "N/A", "internal_consistency_diff": internal_difference_str, "error": error_message,
                        "ledger_tx_sum": lt_total_sum_str
                    }
                    continue # Skip node comparison if internal check failed

                # --- 3. Compare Node vs Ledger ---
                logger.info(f"{log_prefix} Reconciliation Check {currency}: Node={node_balance_str}, Ledger={ledger_total_str}")
                comparison_threshold = quantizer
                if abs(node_balance - ledger_total) > comparison_threshold:
                    difference = node_balance - ledger_total
                    difference_str = str(difference)
                    status = "FAILED_NODE"
                    error_message = (
                        f"Ledger Discrepancy (Node vs Ledger) [{currency}]! Diff: {difference_str}. "
                        f"Node: {node_balance_str}, Ledger: {ledger_total_str}. INVESTIGATE."
                    )
                    security_logger.error(error_message) # Use security logger for node discrepancies too
                    _trigger_alert("error", f"Ledger Discrepancy (Node vs Ledger): {currency}", error_message)
                    overall_discrepancy_found = True
                    logger.info(f"{log_prefix} Node vs Ledger FAILED ({currency}). Diff: {difference_str}")
                else:
                    status = "SUCCESS"
                    logger.info(f"{log_prefix} Ledger reconciliation PASSED ({currency}).")

            except (ValueError, TypeError, InvalidOperation, RuntimeError) as config_or_logic_err:
                # Catch errors like invalid config, aggregation failures, conversion errors
                status = "ERROR"
                # Use the specific error message from the exception
                error_message = f"Config/Logic error processing {currency}: {type(config_or_logic_err).__name__} - {config_or_logic_err}"
                logger.error(f"{log_prefix} {error_message}", exc_info=True)
                _trigger_alert("error", f"Ledger Reconciliation Error: {currency}", error_message)
                overall_discrepancy_found = True
                # Ensure values are recorded even on error
                node_balance_str = str(node_balance) if node_balance is not None else "ERROR"
                ledger_total_str = str(ledger_total) if ledger_total is not None else "ERROR"
                lt_total_sum_str = str(lt_total_sum) if 'lt_total_sum' in locals() else "ERROR"


            except Exception as e: # Catch any other unexpected error for this currency
                status = "ERROR"
                error_message = f"Unexpected error reconciling {currency}: {type(e).__name__} - {e}"
                logger.exception(f"{log_prefix} {error_message}")
                _trigger_alert("error", f"Ledger Reconciliation Unexpected Error: {currency}", error_message)
                overall_discrepancy_found = True
                # Ensure values are recorded even on error
                node_balance_str = str(node_balance) if node_balance is not None else "UNEXPECTED_ERROR"
                ledger_total_str = str(ledger_total) if ledger_total is not None else "UNEXPECTED_ERROR"
                lt_total_sum_str = str(lt_total_sum) if 'lt_total_sum' in locals() else "UNEXPECTED_ERROR"

            # Store results for this currency, ensuring all keys exist
            results[currency] = {
                "status": status,
                "node_balance": node_balance_str,
                "ledger_total": ledger_total_str,
                "difference": difference_str if status == "FAILED_NODE" else "N/A",
                "internal_consistency_diff": internal_difference_str if status == "FAILED_INTERNAL" else "N/A",
                "error": error_message if status not in ["SUCCESS", "PENDING", "SKIPPED"] else None,
                "ledger_tx_sum": lt_total_sum_str if status not in ["ERROR_NODE_BALANCE", "SKIPPED"] else "N/A"
            }
        # --- End Currency Loop ---

        final_status = "FAILED" if overall_discrepancy_found else "SUCCESS"
        summary_message = f"{log_prefix} Task finished. Overall status: {final_status}."
        if overall_discrepancy_found:
            logger.warning(summary_message + " Issues detected.")
            _trigger_alert("warning", "Ledger Reconciliation Completed with Issues", f"Details: {results}")
        else:
            logger.info(summary_message + " All balances match.")
        return {"status": final_status, "results": results}

    except Ignore:
        # Lock contention or other reason to ignore the task run
        logger.info(f"{log_prefix} Task run ignored.")
        # Reraise Ignore is important if Celery needs to handle it (e.g., not retry)
        raise
    except Exception as e:
        logger.exception(f"{log_prefix} Unhandled exception in task wrapper: {e}")
        _trigger_alert("critical", "Ledger Reconciliation Task Failed Critically", f"Error: {e}")
        raise
    finally:
        # <<< FIX v1.9.2: Simplified lock release logic >>>
        # Attempt release if lock object exists and it's currently locked.
        # Avoids issues with task_id being None or mock object IDs in tests.
        if lock and lock.locked():
            try:
                lock.release()
                logger.info(f"{log_prefix} Released lock: {RECONCILE_LOCK_KEY}")
            except Exception as release_err:
                # Log error if release fails (e.g., LockNotOwnedError if somehow it's not ours)
                 logger.error(f"{log_prefix} Failed to release lock: {release_err}", exc_info=True)


#------------END OF FILE-------------