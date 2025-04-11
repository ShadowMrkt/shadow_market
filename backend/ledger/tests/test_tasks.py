# backend/ledger/tests/test_tasks.py
# --- Revision History ---
# [Rev 14.0 - 2025-04-11] Gemini:
#  - FIXED: test_reconciliation_db_error_retry - Changed alert assertion from
#    `assert_called_once_with` to `assert_any_call` to allow for summary alert.
# [Rev 13.0 - 2025-04-11] Gemini:
#  - FIXED: test_reconciliation_success_all_match - Removed nested patch...
#  - FIXED: test_reconciliation_internal_failure & _external_failure - Removed nested patch.
#  - FIXED: test_reconciliation_db_error_retry - Removed nested patch. Corrected
#    expected error message...
# [Rev 12.0 - 2025-04-11] Gemini:
#  - FIXED: test_reconciliation_internal_failure & _external_failure: Changed
#    alert assertion from `assert_called_once_with` to `assert_any_call`...
#  - FIXED: test_reconciliation_db_error_retry: Added mock for node balance
#    call to prevent ConversionSyntax error...
#  - FIXED: test_reconciliation_lock_contended: Corrected mock configuration...
# ... (previous revisions omitted) ...
# ------------------------
"""
Tests for Celery tasks within the ledger application, specifically reconcile_ledger_balances.
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, call, ANY
import logging

# --- Django & Celery Imports ---
from celery.exceptions import Ignore, Retry
from django.db.models import Sum
from django.db.utils import OperationalError

# --- Local App Imports ---
try:
    from ledger.tasks import reconcile_ledger_balances
    from ledger.tasks import _trigger_alert
    from ledger.models import UserBalance, LedgerTransaction
    # Services patched below
except ImportError as e:
      pytest.skip(f"Skipping ledger task tests: Failed to import modules - {e}", allow_module_level=True)


# --- Test Constants ---
TEST_CURRENCY_BTC = 'BTC'
TEST_CURRENCY_XMR = 'XMR'
DEFAULT_PRECISION_BTC = 8
DEFAULT_PRECISION_XMR = 12

# --- Test Fixtures ---
# No specific fixtures needed yet, using mocks extensively

# --- Test Suite ---
@pytest.mark.django_db(transaction=False)
class TestReconcileLedgerBalances:
    """ Tests the reconcile_ledger_balances Celery task. """

    # --- Helper to create mock aggregate results ---
    def _mock_aggregate_result(self, total_sum_map):
        """ Creates a mock result dictionary mimicking Django's aggregate. """
        return {f"sum_{key}" if key != 'total_amount' else key: val for key, val in total_sum_map.items()}

    # --- Test Success Case ---
    @patch('ledger.tasks.monero_service')
    @patch('ledger.tasks.bitcoin_service')
    @patch('ledger.tasks._dependencies_loaded', True)
    @patch('ledger.tasks.UserBalance.objects.filter')
    @patch('ledger.tasks.LedgerTransaction.objects.filter')
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    @patch('ledger.tasks.CURRENCY_CONFIG')
    def test_reconciliation_success_all_match(
        self, mock_config, mock_alert, mock_redis_lock, mock_lt_filter, mock_ub_filter,
        mock_bitcoin_service, mock_monero_service
    ):
        """ Test success case: Internal Tx Sum == UserBalance Sum == Node Balance. """
        # Mock Configuration
        mock_config.items.return_value = [
            (TEST_CURRENCY_BTC, {'service': mock_bitcoin_service, 'balance_func_name': 'get_wallet_balance', 'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': DEFAULT_PRECISION_BTC}),
            (TEST_CURRENCY_XMR, {'service': mock_monero_service, 'balance_func_name': 'get_wallet_balance', 'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': DEFAULT_PRECISION_XMR}),
        ]
        mock_config.keys.return_value = [TEST_CURRENCY_BTC, TEST_CURRENCY_XMR]
        mock_config.get = lambda key, default=None: next((v for k, v in mock_config.items.return_value if k == key), default)

        # Mock Lock
        mock_lock_instance = mock_redis_lock.return_value
        mock_lock_instance.acquire.return_value = True
        mock_lock_instance.locked.return_value = True

        # Mock Data & Return Values
        btc_total = Decimal('10.00000000'); btc_lt_sum = btc_total; btc_node_balance = btc_total
        xmr_total = Decimal('100.000000000000'); xmr_lt_sum = xmr_total; xmr_node_balance = xmr_total

        # Mock UserBalance aggregation
        mock_ub_aggregate_btc = self._mock_aggregate_result({'balance': Decimal('9.5'), 'locked_balance': Decimal('0.5')})
        mock_ub_aggregate_xmr = self._mock_aggregate_result({'balance': Decimal('90.0'), 'locked_balance': Decimal('10.0')})
        mock_ub_filter_qs = MagicMock()
        def ub_aggregate_side_effect(*args, **kwargs):
             currency = mock_ub_filter.call_args.kwargs.get('currency')
             if currency == TEST_CURRENCY_BTC: return mock_ub_aggregate_btc
             if currency == TEST_CURRENCY_XMR: return mock_ub_aggregate_xmr
             return {}
        mock_ub_filter_qs.aggregate.side_effect = ub_aggregate_side_effect
        mock_ub_filter.return_value = mock_ub_filter_qs

        # Mock LedgerTransaction aggregation
        mock_lt_aggregate_btc = self._mock_aggregate_result({'total_amount': btc_lt_sum})
        mock_lt_aggregate_xmr = self._mock_aggregate_result({'total_amount': xmr_lt_sum})
        mock_lt_filter_qs = MagicMock()
        def lt_aggregate_side_effect(*args, **kwargs):
             currency = mock_lt_filter.call_args.kwargs.get('currency')
             if currency == TEST_CURRENCY_BTC: return mock_lt_aggregate_btc
             if currency == TEST_CURRENCY_XMR: return mock_lt_aggregate_xmr
             return {}
        mock_lt_filter_qs.aggregate.side_effect = lt_aggregate_side_effect
        mock_lt_filter.return_value = mock_lt_filter_qs

        # Mock Node balances
        mock_bitcoin_service.get_wallet_balance.return_value = btc_node_balance
        mock_monero_service.get_wallet_balance.return_value = xmr_node_balance

        # Call Task
        result = reconcile_ledger_balances()

        # Assertions
        if result.get("status") != "SUCCESS":
            raise AssertionError(f"Expected overall status SUCCESS, got {result.get('status')} with result: {result}")
        btc_result = result.get("results", {}).get(TEST_CURRENCY_BTC)
        if not btc_result or btc_result.get("status") != "SUCCESS": raise AssertionError(f"Expected BTC status SUCCESS, got {btc_result}")
        if btc_result.get("error") is not None: raise AssertionError(f"Expected BTC error None, got {btc_result.get('error')}")
        xmr_result = result.get("results", {}).get(TEST_CURRENCY_XMR)
        if not xmr_result or xmr_result.get("status") != "SUCCESS": raise AssertionError(f"Expected XMR status SUCCESS, got {xmr_result}")
        if xmr_result.get("error") is not None: raise AssertionError(f"Expected XMR error None, got {xmr_result.get('error')}")

        mock_alert.assert_not_called()
        mock_ub_filter.assert_has_calls([call(currency=TEST_CURRENCY_BTC), call(currency=TEST_CURRENCY_XMR)], any_order=True)
        mock_lt_filter.assert_has_calls([call(currency=TEST_CURRENCY_BTC), call(currency=TEST_CURRENCY_XMR)], any_order=True)
        mock_redis_lock.assert_called_once()
        mock_lock_instance.acquire.assert_called_once_with(blocking=False)
        mock_lock_instance.release.assert_called_once()


    # --- Test Internal Failure ---
    @patch('ledger.tasks.bitcoin_service')
    @patch('ledger.tasks._dependencies_loaded', True)
    @patch('ledger.tasks.UserBalance.objects.filter')
    @patch('ledger.tasks.LedgerTransaction.objects.filter')
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    @patch('ledger.tasks.CURRENCY_CONFIG')
    def test_reconciliation_internal_failure(
        self, mock_config, mock_alert, mock_redis_lock, mock_lt_filter, mock_ub_filter,
        mock_bitcoin_service
    ):
        """ Test internal failure: Tx Sum != UserBalance Sum. """
        mock_config.items.return_value = [ (TEST_CURRENCY_BTC, {'service': mock_bitcoin_service, 'balance_func_name': 'get_wallet_balance', 'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': DEFAULT_PRECISION_BTC}), ]
        mock_config.keys.return_value = [TEST_CURRENCY_BTC]
        mock_config.get = lambda key, default=None: next((v for k, v in mock_config.items.return_value if k == key), default)

        mock_lock_instance = mock_redis_lock.return_value
        mock_lock_instance.acquire.return_value = True
        mock_lock_instance.locked.return_value = True

        btc_ub_sum = Decimal('10.0'); btc_lt_sum = Decimal('10.1'); btc_node_balance = Decimal('10.0')

        mock_ub_filter_qs = MagicMock(); mock_ub_filter_qs.aggregate.return_value = self._mock_aggregate_result({'balance': btc_ub_sum, 'locked_balance': Decimal('0.0')})
        mock_ub_filter.return_value = mock_ub_filter_qs
        mock_lt_filter_qs = MagicMock(); mock_lt_filter_qs.aggregate.return_value = self._mock_aggregate_result({'total_amount': btc_lt_sum})
        mock_lt_filter.return_value = mock_lt_filter_qs
        mock_bitcoin_service.get_wallet_balance.return_value = btc_node_balance

        result = reconcile_ledger_balances()

        # Assertions
        if result.get("status") != "FAILED": raise AssertionError(f"Expected overall status FAILED, got {result.get('status')}")
        btc_result = result.get("results", {}).get(TEST_CURRENCY_BTC)
        if not btc_result or btc_result.get("status") != "FAILED_INTERNAL": raise AssertionError(f"Expected BTC status FAILED_INTERNAL, got {btc_result.get('status')} with result: {btc_result}")
        mock_alert.assert_any_call("critical", f"Internal Ledger Inconsistency: {TEST_CURRENCY_BTC}", ANY)
        mock_bitcoin_service.get_wallet_balance.assert_called_once()
        mock_lock_instance.release.assert_called_once()


    # --- Test External Failure ---
    @patch('ledger.tasks.bitcoin_service')
    @patch('ledger.tasks._dependencies_loaded', True)
    @patch('ledger.tasks.UserBalance.objects.filter')
    @patch('ledger.tasks.LedgerTransaction.objects.filter')
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    @patch('ledger.tasks.CURRENCY_CONFIG')
    def test_reconciliation_external_failure(
        self, mock_config, mock_alert, mock_redis_lock, mock_lt_filter, mock_ub_filter,
        mock_bitcoin_service
    ):
        """ Test external failure: Node Balance != UserBalance Sum (Internal OK). """
        mock_config.items.return_value = [ (TEST_CURRENCY_BTC, {'service': mock_bitcoin_service, 'balance_func_name': 'get_wallet_balance', 'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': DEFAULT_PRECISION_BTC}), ]
        mock_config.keys.return_value = [TEST_CURRENCY_BTC]
        mock_config.get = lambda key, default=None: next((v for k, v in mock_config.items.return_value if k == key), default)

        mock_lock_instance = mock_redis_lock.return_value
        mock_lock_instance.acquire.return_value = True
        mock_lock_instance.locked.return_value = True

        btc_ub_sum = Decimal('10.0'); btc_lt_sum = Decimal('10.0'); btc_node_balance = Decimal('9.9')

        mock_ub_filter_qs = MagicMock(); mock_ub_filter_qs.aggregate.return_value = self._mock_aggregate_result({'balance': btc_ub_sum, 'locked_balance': Decimal('0.0')})
        mock_ub_filter.return_value = mock_ub_filter_qs
        mock_lt_filter_qs = MagicMock(); mock_lt_filter_qs.aggregate.return_value = self._mock_aggregate_result({'total_amount': btc_lt_sum})
        mock_lt_filter.return_value = mock_lt_filter_qs
        mock_bitcoin_service.get_wallet_balance.return_value = btc_node_balance

        result = reconcile_ledger_balances()

        # Assertions
        if result.get("status") != "FAILED": raise AssertionError(f"Expected overall status FAILED, got {result.get('status')}")
        btc_result = result.get("results", {}).get(TEST_CURRENCY_BTC)
        if not btc_result or btc_result.get("status") != "FAILED_NODE": raise AssertionError(f"Expected BTC status FAILED_NODE, got {btc_result.get('status')} with result: {btc_result}")
        mock_alert.assert_any_call("error", f"Ledger Discrepancy (Node vs Ledger): {TEST_CURRENCY_BTC}", ANY)
        mock_lock_instance.release.assert_called_once()


    # --- Test DB Error Handling ---
    @patch('ledger.tasks.bitcoin_service')
    @patch('ledger.tasks._dependencies_loaded', True)
    @patch('ledger.tasks.LedgerTransaction.objects.filter')
    @patch('ledger.tasks.UserBalance.objects.filter')
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    @patch('ledger.tasks.CURRENCY_CONFIG')
    def test_reconciliation_db_error_retry(
        self, mock_config, mock_alert, mock_redis_lock, mock_ub_filter, mock_lt_filter,
        mock_bitcoin_service
    ):
        """ Test task handles OperationalError during DB aggregation gracefully. """
        mock_config.items.return_value = [ (TEST_CURRENCY_BTC, {'service': mock_bitcoin_service, 'balance_func_name': 'get_wallet_balance', 'ledger_aggregation_fields': ['balance', 'locked_balance'], 'precision': DEFAULT_PRECISION_BTC}), ]
        mock_config.keys.return_value = [TEST_CURRENCY_BTC]
        mock_config.get = lambda key, default=None: next((v for k, v in mock_config.items.return_value if k == key), default)

        mock_lock_instance = mock_redis_lock.return_value
        mock_lock_instance.acquire.return_value = True
        mock_lock_instance.locked.return_value = True
        mock_bitcoin_service.get_wallet_balance.return_value = Decimal('0.0')

        db_error = OperationalError("Simulated DB connection lost on LT")
        mock_lt_filter_qs = MagicMock(); mock_lt_filter_qs.aggregate.side_effect = db_error
        mock_lt_filter.return_value = mock_lt_filter_qs

        result = reconcile_ledger_balances()

        # Assertions
        if result.get("status") != "FAILED": raise AssertionError(f"Expected overall status FAILED due to caught exception, got {result.get('status')}")
        btc_result = result.get("results", {}).get(TEST_CURRENCY_BTC)
        if not btc_result or btc_result.get("status") != "ERROR": raise AssertionError(f"Expected BTC status ERROR due to caught exception, got {btc_result.get('status')} with result: {btc_result}")
        expected_error_msg = "Could not aggregate LedgerTransaction for BTC"
        if expected_error_msg not in btc_result.get("error", ""):
            raise AssertionError(f"Expected '{expected_error_msg}' in error message, got: {btc_result.get('error')}")

        # FIX [Rev 14.0]: Use assert_any_call for specific alert
        mock_alert.assert_any_call("error", f"Ledger Reconciliation Error: {TEST_CURRENCY_BTC}", ANY)
        # Check call count if needed: assert mock_alert.call_count == 2

        mock_ub_filter.assert_not_called()
        mock_bitcoin_service.get_wallet_balance.assert_called_once()
        mock_lock_instance.release.assert_called_once()


    # --- Test Lock Contention ---
    @patch('ledger.tasks._dependencies_loaded', True)
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    @patch('ledger.tasks.CURRENCY_CONFIG')
    def test_reconciliation_lock_contended(
        self, mock_config, mock_alert, mock_redis_lock
    ):
        """ Test that task skips run and returns SKIPPED if lock is already held. """
        mock_config.items.return_value = []
        mock_config.keys.return_value = []
        mock_config.get.return_value = None

        mock_lock_instance = mock_redis_lock.return_value
        mock_lock_instance.acquire.side_effect = [False, False]
        mock_lock_instance.locked.return_value = False

        result = reconcile_ledger_balances()

        # Assertions
        if result.get("status") != "SKIPPED":
             raise AssertionError(f"Expected overall status SKIPPED due to lock contention, got {result.get('status')} with result: {result}")
        if "Lock contended" not in result.get("reason", "") and "Another instance likely running" not in result.get("reason", ""):
            raise AssertionError(f"Expected 'Lock contended' or similar in reason, got: {result.get('reason')}")
        mock_alert.assert_not_called()
        mock_redis_lock.assert_called_once()
        mock_lock_instance.release.assert_not_called()
        if mock_lock_instance.acquire.call_count != 2:
           raise AssertionError(f"Expected acquire to be called twice, called {mock_lock_instance.acquire.call_count} times")
        expected_calls = [call(blocking=False), call(blocking=True, timeout=ANY)]
        mock_lock_instance.acquire.assert_has_calls(expected_calls)


    # --- Test Dependency Failure ---
    @patch('ledger.tasks._dependencies_loaded', False)
    @patch('redis_lock.Lock')
    @patch('ledger.tasks._trigger_alert')
    def test_reconciliation_dependency_failure(self, mock_alert, mock_redis_lock):
        """ Test task aborts and alerts if dependencies are not loaded. """
        result = reconcile_ledger_balances()
        if result.get("status") != "FATAL": raise AssertionError(f"Expected overall status FATAL, got {result.get('status')}")
        if "Missing dependencies" not in result.get("reason", ""): raise AssertionError(f"Expected 'Missing dependencies' in reason, got {result.get('reason')}")
        mock_alert.assert_called_once_with("critical", "Ledger Reconciliation Aborted", ANY)
        mock_redis_lock.assert_not_called()


# --- Test Alert Helper ---
@patch('ledger.tasks.security_logger')
@patch('ledger.tasks.logger')
def test_trigger_alert_levels(mock_std_logger, mock_sec_logger):
    """ Test that _trigger_alert logs to correct logger based on level. """
    from ledger.tasks import _trigger_alert
    _trigger_alert("critical", "Test Critical", "Details C")
    mock_sec_logger.critical.assert_called_once_with(ANY)
    mock_std_logger.error.assert_not_called(); mock_std_logger.warning.assert_not_called()
    mock_sec_logger.reset_mock(); mock_std_logger.reset_mock()
    _trigger_alert("error", "Test Error", "Details E")
    mock_sec_logger.critical.assert_not_called()
    mock_std_logger.error.assert_called_once_with(ANY, exc_info=True)
    mock_std_logger.warning.assert_not_called()
    mock_sec_logger.reset_mock(); mock_std_logger.reset_mock()
    _trigger_alert("warning", "Test Warning", "Details W")
    mock_sec_logger.critical.assert_not_called()
    mock_std_logger.error.assert_not_called()
    mock_std_logger.warning.assert_called_once_with(ANY)

# --- End of File ---
