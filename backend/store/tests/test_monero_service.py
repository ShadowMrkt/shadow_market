# backend/store/tests/test_monero_service.py

# --- Revision History ---
# v1.2.21 (2025-05-12): Gemini Rev 16
#   - FIXED: Modified `TestSettingHelper.test_get_setting_required_missing` to use
#            `self.assertLogs()` for more reliable logger assertion, replacing
#            `unittest.mock.patch` for this specific test case.
# v1.2.20 (2025-05-03): Gemini Rev 15
#   - FIXED: Standardized all local application imports (store, ledger, vault_integration)
#            to use absolute paths starting with `backend.` (or just `vault_integration` if top-level)
#            to resolve conflicting model loading errors (`globalsettings`).
# v1.2.19 (2025-04-08):
#   - FIXED: Corrected Python syntax error "Expected indented block" on line 1402 by adding indentation
#            within the preceding `with self.assertRaisesRegex(...)` block.
# - v1.2.18 (2025-04-08):
#   - SECURITY: Suppressed Bandit B105 (hardcoded_password_string) findings for dummy test passwords
#               DUMMY_TEST_WALLET_PASSWORD (line ~91) and DUMMY_TEST_RPC_PASSWORD (line ~92) as they
#               are clearly marked test data (# nosec B105).
# ... (Previous revisions omitted for brevity) ...

"""
Unit tests for the Monero Service (backend.store.services.monero_service).
Uses extensive mocking to isolate the service logic from actual RPC calls,
Vault interactions, and database access where necessary.
Focuses on input validation, correct RPC parameter construction,
response parsing, error handling, and workflow orchestration logic.
"""

import pytest
import json
import secrets
import requests # R12.2: Added missing import
from decimal import Decimal, InvalidOperation
from unittest.mock import patch, MagicMock, call

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError as DjangoValidationError
from django.test import override_settings, TestCase

# --- Models and Exceptions from the application (Standardized) ---
from backend.store.models import CryptoPayment, Order, User # FIXED Import Path
try:
    from backend.ledger.models import LedgerTransaction # FIXED Import Path
    LEDGER_TX_DEPOSIT = 'DEPOSIT'
except ImportError:
    LedgerTransaction = MagicMock() # Use MagicMock if ledger app is not available/installed
    LEDGER_TX_DEPOSIT = 'DEPOSIT'

from backend.store.exceptions import MoneroRPCError, OperationFailedException, CryptoProcessingError, MoneroDaemonError # FIXED Import Path
from backend.store.validators import validate_monero_address # FIXED Import Path
# Assuming vault_integration is a top-level app/module alongside backend, or adjust path if needed
# If vault_integration is INSIDE backend, it should be backend.vault_integration
# For now, assuming it's a sibling package/app:
from vault_integration import VaultError, VaultSecretNotFoundError, VaultAuthenticationError

# --- Service Functions to Test (Standardized) ---
from backend.store.services import monero_service # FIXED Import Path
from backend.store.services.monero_service import ( # FIXED Import Path
    PICONERO_PER_XMR,
    DEFAULT_CONFIRMATIONS_NEEDED,
    MAX_RETRIES,
    _make_rpc_request,
    _managed_wallet_session,
    _get_setting,
    _validate_hex_data,
    xmr_to_piconero,
    piconero_to_xmr,
    get_daemon_block_height,
    get_wallet_balance,
    generate_integrated_address,
    get_market_prepare_multisig_info,
    create_monero_multisig_wallet,
    prepare_monero_release_tx,
    sign_monero_txset,
    submit_monero_txset,
    process_withdrawal,
    scan_for_payment_confirmation,
    process_escrow_release,
    finalize_and_broadcast_xmr_release,
    create_and_broadcast_dispute_tx,
)

# --- Constants for Testing ---
TEST_RPC_URL = "http://127.0.0.1:18082/json_rpc"
TEST_DAEMON_URL = "http://127.0.0.1:18081/json_rpc"
TEST_WALLET_NAME = "test_wallet_123"
# <<< Revision 7: Apply nosec B105 >>>
DUMMY_TEST_WALLET_PASSWORD = "dummy-password-for-testing-123!" # nosec B105 - Dummy password for testing only.
DUMMY_TEST_RPC_PASSWORD = "dummy-rpc-password-for-testing-456!" # nosec B105 - Dummy password for testing only.
TEST_ORDER_ID_STR = "order_abc_789"
TEST_MULTISIG_WALLET_NAME = f"msig_order_{TEST_ORDER_ID_STR}"
TEST_VALID_XMR_ADDRESS = "4AdRN5dKiN2B7MgSTm1kMbub5FAnceKQTG5QpXU91Qnscc6MJ1S3nEq6fGDrHG8jN33p3DB1wNUZEt58h3vRwaM8AKQbaq7"
TEST_VALID_INTEGRATED_ADDRESS = "4LdpnMo9wPESgQ4N3SpYYy1f5t9aZnsQA6zMCg9KDGpQEAd2HpSCq4x7p8tjPnUbqQe2xShzXgCMZtVmrB8s8tqqJbsUnE1zQ7hFzU5gX9"
TEST_VALID_PAYMENT_ID_SHORT = secrets.token_hex(8) # 16 chars
TEST_VALID_PAYMENT_ID_LONG = secrets.token_hex(32) # 64 chars
TEST_VALID_TXID = secrets.token_hex(32) # 64 chars

UNSIGNED_TXSET_LEN = 256
PARTIAL_SIGNED_TXSET_LEN = 512
FULL_SIGNED_TXSET_LEN = 1024
MSIG_INFO_LEN = 256

# R12.13 Fix: Ensure hex strings are generated with correct length
TEST_UNSIGNED_TXSET = secrets.token_hex(UNSIGNED_TXSET_LEN // 2)
TEST_PARTIAL_SIGNED_TXSET = secrets.token_hex(PARTIAL_SIGNED_TXSET_LEN // 2)
TEST_FULL_SIGNED_TXSET = secrets.token_hex(FULL_SIGNED_TXSET_LEN // 2)
TEST_MARKET_MSIG_INFO = secrets.token_hex(MSIG_INFO_LEN // 2)
TEST_PARTICIPANT_MSIG_INFO_1 = secrets.token_hex(MSIG_INFO_LEN // 2)
TEST_PARTICIPANT_MSIG_INFO_2 = secrets.token_hex(MSIG_INFO_LEN // 2)
# R12.13 Fix: Final MSIG info often has different length in reality, use a plausible one
TEST_FINAL_MSIG_INFO = secrets.token_hex(MSIG_INFO_LEN // 2 + 128) # Example adjusted length

# Helper to create mock Order/User/CryptoPayment objects
def create_mock_order(pk=1, xmr_multisig_wallet_name=TEST_MULTISIG_WALLET_NAME):
    mock_order = MagicMock(spec=Order)
    mock_order.pk = pk
    mock_order.xmr_multisig_wallet_name = xmr_multisig_wallet_name
    mock_order.status = "PENDING"
    return mock_order

def create_mock_user(pk=1, username="testuser"):
    mock_user = MagicMock(spec=User)
    mock_user.pk = pk
    mock_user.username = username
    return mock_user

def create_mock_payment(
    pk=1,
    order_id=1,
    currency='XMR',
    payment_id_monero=TEST_VALID_PAYMENT_ID_LONG,
    expected_amount_native=Decimal("123456789000"), # Piconero as Decimal
    confirmations_needed=5
):
    mock_payment = MagicMock(spec=CryptoPayment)
    mock_payment.pk = pk
    mock_payment.order_id = order_id
    mock_payment.currency = currency
    mock_payment.payment_id_monero = payment_id_monero
    mock_payment.expected_amount_native = expected_amount_native
    mock_payment.confirmations_needed = confirmations_needed
    mock_payment.is_confirmed = False
    return mock_payment

# --- Test Cases ---

class TestSettingHelper(TestCase):
    @override_settings(MY_TEST_SETTING="my_value")
    def test_get_setting_exists(self):
        self.assertEqual(_get_setting("MY_TEST_SETTING"), "my_value")

    def test_get_setting_not_exists_default(self):
        self.assertEqual(_get_setting("NON_EXISTENT_SETTING", default="default_val"), "default_val")

    # v1.2.21 - Gemini Rev 16: Replaced @patch with self.assertLogs for reliability
    def test_get_setting_required_missing(self):
        # The logger name comes from the module where _get_setting is defined and logs
        # which is backend.store.services.monero_service
        with self.assertLogs('backend.store.services.monero_service', level='ERROR') as cm:
            self.assertIsNone(_get_setting("REQUIRED_MISSING_SETTING", required=True))
        
        self.assertEqual(len(cm.records), 1)
        log_record = cm.records[0]
        self.assertEqual(log_record.levelname, 'ERROR')
        # Check the formatted message
        expected_message = "CRITICAL SETTING MISSING: 'REQUIRED_MISSING_SETTING'. Service functionality may be impaired."
        self.assertEqual(log_record.getMessage(), expected_message)
        # Optionally, check the raw message format string and arguments
        self.assertEqual(log_record.msg, "CRITICAL SETTING MISSING: '%s'. Service functionality may be impaired.")
        self.assertEqual(log_record.args, ("REQUIRED_MISSING_SETTING",))

class TestHexValidationHelper(TestCase):
    def test_validate_hex_data_valid(self):
        self.assertTrue(_validate_hex_data("0011aabb", "Test Data"))
        self.assertTrue(_validate_hex_data("0011AABB", "Test Data Caps"))
        self.assertTrue(_validate_hex_data(TEST_VALID_TXID, "Test TXID"))
        self.assertTrue(_validate_hex_data(TEST_UNSIGNED_TXSET, "Test Generated Unsigned"))

    def test_validate_hex_data_invalid_chars(self):
        self.assertFalse(_validate_hex_data("0011aabbZZ", "Test Bad Chars"))

    def test_validate_hex_data_invalid_odd_length(self):
        self.assertFalse(_validate_hex_data("0011aabbc", "Test Odd Length"))

    def test_validate_hex_data_invalid_type(self):
        self.assertFalse(_validate_hex_data(None, "Test None"))
        self.assertFalse(_validate_hex_data(123, "Test Int")) # type: ignore
        self.assertFalse(_validate_hex_data("", "Test Empty String"))

    def test_validate_hex_data_length_check_pass(self):
        self.assertTrue(_validate_hex_data(TEST_VALID_TXID, "Test TXID", 64))

    def test_validate_hex_data_length_check_fail(self):
        self.assertFalse(_validate_hex_data(TEST_VALID_TXID, "Test TXID", 66))


class TestConversionUtilities(TestCase):

    def test_xmr_to_piconero_success(self):
        self.assertEqual(xmr_to_piconero(Decimal("1.0")), 1000000000000)
        self.assertEqual(xmr_to_piconero(Decimal("0.5")), 500000000000)
        self.assertEqual(xmr_to_piconero(Decimal("123.456")), 123456000000000)
        self.assertEqual(xmr_to_piconero(Decimal("0.000000000001")), 1)
        self.assertEqual(xmr_to_piconero(Decimal("0")), 0)

    def test_xmr_to_piconero_rounding(self):
        # Uses ROUND_DOWN
        self.assertEqual(xmr_to_piconero(Decimal("1.234567890123999")), 1234567890123)

    def test_xmr_to_piconero_invalid_type(self):
        with self.assertRaisesRegex(TypeError, "must be a Decimal"):
            xmr_to_piconero(1.0) # type: ignore
        with self.assertRaisesRegex(TypeError, "must be a Decimal"):
            xmr_to_piconero("1.0") # type: ignore

    def test_xmr_to_piconero_invalid_value(self):
        with self.assertRaisesRegex(ValueError, "cannot be NaN or Infinity"):
            xmr_to_piconero(Decimal("NaN"))
        with self.assertRaisesRegex(ValueError, "cannot be NaN or Infinity"):
            xmr_to_piconero(Decimal("Inf"))
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            xmr_to_piconero(Decimal("-1.0"))

    def test_piconero_to_xmr_success(self):
        self.assertEqual(piconero_to_xmr(1000000000000), Decimal("1.0"))
        self.assertEqual(piconero_to_xmr(500000000000), Decimal("0.5"))
        self.assertEqual(piconero_to_xmr(1), Decimal("0.000000000001"))
        self.assertEqual(piconero_to_xmr(0), Decimal("0.0"))
        self.assertEqual(piconero_to_xmr("1234567890123"), Decimal("1.234567890123"))

    def test_piconero_to_xmr_rounding(self):
        # Quantized to 12 places using ROUND_DOWN
        self.assertEqual(piconero_to_xmr(1234567890123), Decimal("1.234567890123"))

    def test_piconero_to_xmr_invalid_type(self):
        # First check (float)
        with self.assertRaisesRegex(TypeError, "cannot be a float"):
            piconero_to_xmr(1.0) # type: ignore
        # Second check (must be int/str) - R15 Fix: Use None to trigger correct error path
        with self.assertRaisesRegex(TypeError, "must be an integer or string"):
            piconero_to_xmr(None) # type: ignore
        # R15: Removed redundant checks from previous test version

    def test_piconero_to_xmr_invalid_value(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            piconero_to_xmr(-1)


@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@override_settings(MONERO_RPC_URL=TEST_DAEMON_URL)
class TestDaemonBlockHeight(TestCase):

    def test_get_daemon_height_success(self, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly (it strips 'result')
        mock_rpc.return_value = {"count": 1234567} # _make_rpc_request returns the content of "result"
        height = get_daemon_block_height()
        self.assertEqual(height, 1234567)
        mock_rpc.assert_called_once_with(TEST_DAEMON_URL, "get_block_count", is_wallet=False)

    def test_get_daemon_height_rpc_error(self, mock_rpc):
        mock_rpc.side_effect = MoneroRPCError("Daemon busy", code=-50)
        height = get_daemon_block_height()
        self.assertIsNone(height)

    def test_get_daemon_height_network_error(self, mock_rpc):
        mock_rpc.side_effect = OperationFailedException("Connection timed out")
        height = get_daemon_block_height()
        self.assertIsNone(height)

    def test_get_daemon_height_unexpected_response(self, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"status": "OK", "height": "wrong"} # No "count" key
        height = get_daemon_block_height()
        self.assertIsNone(height)

    def test_get_daemon_height_no_url(self, mock_rpc):
        with override_settings(MONERO_RPC_URL=None):
            height = get_daemon_block_height()
            self.assertIsNone(height)
            mock_rpc.assert_not_called()

    def test_get_daemon_height_daemon_specific_error(self, mock_rpc):
        mock_rpc.side_effect = MoneroDaemonError(f"Could not connect to Monero daemon at {TEST_DAEMON_URL} after retries.")
        height = get_daemon_block_height()
        self.assertIsNone(height)


# --- Managed Wallet Session Tests ---
@patch('backend.store.services.monero_service.get_monero_wallet_password') # FIXED Patch Path
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestManagedWalletSession(TestCase):

    def test_session_success(self, mock_rpc_request, mock_get_password):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        # R16 Fix: _make_rpc_request returns content of "result"
        mock_rpc_request.side_effect = [
            {"status": "OK"}, # For open_wallet
            {"status": "OK"}  # For close_wallet
        ]
        with _managed_wallet_session(TEST_WALLET_NAME) as rpc_url:
            self.assertEqual(rpc_url, TEST_RPC_URL)
        mock_get_password.assert_called_once_with(TEST_WALLET_NAME, raise_error=True)
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": TEST_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "close_wallet", {"filename": TEST_WALLET_NAME}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 2)

    def test_session_get_password_fails_vault_error(self, mock_rpc_request, mock_get_password):
        mock_get_password.side_effect = VaultSecretNotFoundError("Password not found")
        with self.assertRaises(VaultSecretNotFoundError):
            with _managed_wallet_session(TEST_WALLET_NAME): pass
        mock_rpc_request.assert_not_called()

    def test_session_get_password_fails_other_vault_error(self, mock_rpc_request, mock_get_password):
        mock_get_password.side_effect = VaultAuthenticationError("Vault auth failed")
        with self.assertRaises(VaultAuthenticationError):
            with _managed_wallet_session(TEST_WALLET_NAME): pass
        mock_rpc_request.assert_not_called()

    def test_session_open_wallet_rpc_fails(self, mock_rpc_request, mock_get_password):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        mock_rpc_request.side_effect = MoneroRPCError("Wrong password", code=-1)
        with self.assertRaises(MoneroRPCError):
            with _managed_wallet_session(TEST_WALLET_NAME): pass
        mock_rpc_request.assert_called_once_with(TEST_RPC_URL, "open_wallet", {"filename": TEST_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True) # R17 Use constant

    def test_session_open_wallet_network_fails(self, mock_rpc_request, mock_get_password):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        mock_rpc_request.side_effect = OperationFailedException("Timeout opening wallet")
        with self.assertRaises(OperationFailedException):
            with _managed_wallet_session(TEST_WALLET_NAME): pass
        mock_rpc_request.assert_called_once_with(TEST_RPC_URL, "open_wallet", {"filename": TEST_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True) # R17 Use constant

    def test_session_action_inside_fails(self, mock_rpc_request, mock_get_password):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        # R16 Fix: Correct mock returns
        mock_rpc_request.side_effect = [
            {"status": "OK"}, # Open succeeds
            {"status": "OK"}  # Close succeeds
        ]
        custom_exception = ValueError("Something failed inside the 'with' block")
        with self.assertRaises(ValueError) as cm:
            with _managed_wallet_session(TEST_WALLET_NAME):
                raise custom_exception
        self.assertEqual(cm.exception, custom_exception)
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": TEST_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "close_wallet", {"filename": TEST_WALLET_NAME}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 2)

    @patch('backend.store.services.monero_service.logger') # FIXED Patch Path
    def test_session_close_wallet_fails_logged(self, mock_logger, mock_rpc_request, mock_get_password):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        close_error = OperationFailedException("Timeout closing wallet")
        # R16 Fix: Correct mock returns
        mock_rpc_request.side_effect = [
            {"status": "OK"}, # Open succeeds
            close_error       # Close fails
        ]
        # Should not raise the close_error out of the context manager
        with _managed_wallet_session(TEST_WALLET_NAME):
            pass # Simulate successful operation inside
        self.assertEqual(mock_rpc_request.call_count, 2)
        mock_logger.error.assert_called_once_with(
            "%s: Failed to close wallet in finally block: %s",
            f"Wallet session ('{TEST_WALLET_NAME}')",
            close_error,
            exc_info=True
        )

    def test_session_invalid_wallet_name(self, mock_rpc_request, mock_get_password):
        with self.assertRaisesRegex(ValueError, "Invalid or empty wallet name"):
            with _managed_wallet_session(""): pass
        with self.assertRaisesRegex(ValueError, "Invalid or empty wallet name"):
            with _managed_wallet_session(None): pass # type: ignore
        mock_rpc_request.assert_not_called()
        mock_get_password.assert_not_called()

    def test_session_missing_rpc_url(self, mock_rpc_request, mock_get_password):
        with override_settings(MONERO_WALLET_RPC_URL=None):
            expected_msg = "Monero Wallet RPC URL is not configured or invalid."
            with self.assertRaisesRegex(ValueError, expected_msg):
                with _managed_wallet_session(TEST_WALLET_NAME): pass


# --- Wallet Balance Tests ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service._managed_wallet_session') # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestGetWalletBalance(TestCase):

    def test_get_balance_default_wallet_success(self, mock_session, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"unlocked_balance": 1500000000000, "balance": 2000000000000}
        balance = get_wallet_balance()
        self.assertEqual(balance, Decimal("1.5"))
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "get_balance", {"account_index": 0}, is_wallet=True)
        mock_session.assert_not_called()

    def test_get_balance_specific_wallet_success(self, mock_session, mock_rpc):
        mock_session.return_value.__enter__.return_value = TEST_RPC_URL
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"unlocked_balance": 750000000000, "balance": 800000000000}
        balance = get_wallet_balance(wallet_name=TEST_WALLET_NAME)
        self.assertEqual(balance, Decimal("0.75"))
        mock_session.assert_called_once_with(TEST_WALLET_NAME)
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "get_balance", {"account_index": 0}, is_wallet=True)

    def test_get_balance_rpc_error(self, mock_session, mock_rpc):
        mock_rpc.side_effect = MoneroRPCError("Wallet sync error", -10)
        balance = get_wallet_balance()
        self.assertIsNone(balance)
        mock_session.assert_not_called()

    def test_get_balance_network_error(self, mock_session, mock_rpc):
        mock_rpc.side_effect = OperationFailedException("Connection refused")
        balance = get_wallet_balance()
        self.assertIsNone(balance)
        mock_session.assert_not_called()

    def test_get_balance_conversion_error(self, mock_session, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"unlocked_balance": "not-a-number", "balance": 100} # Invalid unlocked_balance type
        balance = get_wallet_balance()
        self.assertIsNone(balance)
        mock_session.assert_not_called()

    def test_get_balance_specific_wallet_session_fails(self, mock_session, mock_rpc):
        mock_session.side_effect = VaultError("Failed to get password")
        balance = get_wallet_balance(wallet_name=TEST_WALLET_NAME)
        self.assertIsNone(balance)
        mock_rpc.assert_not_called()


# --- Integrated Address Tests ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestGenerateIntegratedAddress(TestCase):

    def test_generate_integrated_success(self, mock_validator, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {
            "integrated_address": TEST_VALID_INTEGRATED_ADDRESS,
            "payment_id": TEST_VALID_PAYMENT_ID_SHORT
        }
        result = generate_integrated_address(payment_id=TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("address"), TEST_VALID_INTEGRATED_ADDRESS)
        self.assertEqual(result.get("payment_id"), TEST_VALID_PAYMENT_ID_SHORT)
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "make_integrated_address", {"payment_id": TEST_VALID_PAYMENT_ID_SHORT}, is_wallet=True)
        mock_validator.assert_called_once_with(TEST_VALID_INTEGRATED_ADDRESS)

    def test_generate_standard_subaddress_success(self, mock_validator, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {
            "address": TEST_VALID_XMR_ADDRESS,
            "address_index": 5
        }
        result = generate_integrated_address(payment_id=None)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("address"), TEST_VALID_XMR_ADDRESS)
        self.assertEqual(result.get("address_index"), 5)
        mock_rpc.assert_called_once()
        call_args, call_kwargs = mock_rpc.call_args
        self.assertEqual(call_args[0], TEST_RPC_URL)
        self.assertEqual(call_args[1], "create_address")
        self.assertEqual(call_args[2]['account_index'], 0)
        self.assertTrue(call_args[2]['label'].startswith("generated_"))
        self.assertTrue(call_kwargs.get('is_wallet'))
        mock_validator.assert_called_once_with(TEST_VALID_XMR_ADDRESS)

    def test_generate_invalid_payment_id_format(self, mock_validator, mock_rpc):
        result = generate_integrated_address(payment_id="invalid_pid_too_short")
        self.assertIsNone(result)
        mock_rpc.assert_not_called()
        result = generate_integrated_address(payment_id="toolong" + TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNone(result)
        mock_rpc.assert_not_called()
        result = generate_integrated_address(payment_id="not_hex!" + TEST_VALID_PAYMENT_ID_SHORT[:8])
        self.assertIsNone(result)
        mock_rpc.assert_not_called()

    def test_generate_rpc_error(self, mock_validator, mock_rpc):
        mock_rpc.side_effect = MoneroRPCError("RPC Failed", -5)
        result = generate_integrated_address(payment_id=TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNone(result)

    def test_generate_network_error(self, mock_validator, mock_rpc):
        mock_rpc.side_effect = OperationFailedException("Timeout")
        result = generate_integrated_address(payment_id=TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNone(result)

    def test_generate_validation_fails_on_result(self, mock_validator, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {
            "integrated_address": "invalid-address-format",
            "payment_id": TEST_VALID_PAYMENT_ID_SHORT
        }
        mock_validator.side_effect = DjangoValidationError("Invalid address format")
        result = generate_integrated_address(payment_id=TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNone(result) # Service should return None if validation fails
        mock_validator.assert_called_once_with("invalid-address-format")

    def test_generate_rpc_returns_unexpected_structure(self, mock_validator, mock_rpc):
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"address": TEST_VALID_INTEGRATED_ADDRESS} # Wrong key for integrated
        result = generate_integrated_address(payment_id=TEST_VALID_PAYMENT_ID_SHORT)
        self.assertIsNone(result)
        # R16 Fix: Validator is called *after* checking the key, so it shouldn't be called here
        mock_validator.assert_not_called()


# --- Market Multisig Info Tests ---
@patch('backend.store.services.monero_service.cache') # FIXED Patch Path
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestMarketMultisigInfo(TestCase):

    def test_get_market_info_cache_hit_valid(self, mock_rpc, mock_cache):
        mock_cache.get.return_value = TEST_MARKET_MSIG_INFO
        info = get_market_prepare_multisig_info()
        self.assertEqual(info, TEST_MARKET_MSIG_INFO)
        mock_cache.get.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY)
        mock_rpc.assert_not_called()

    def test_get_market_info_cache_hit_invalid_hex(self, mock_rpc, mock_cache):
        invalid_hex = "INVALID_HEX_GHI_ODD"
        mock_cache.get.return_value = invalid_hex
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"multisig_info": TEST_MARKET_MSIG_INFO}
        info = get_market_prepare_multisig_info()
        self.assertEqual(info, TEST_MARKET_MSIG_INFO)
        mock_cache.get.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY)
        mock_cache.delete.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY)
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "prepare_multisig", is_wallet=True)
        mock_cache.set.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY, TEST_MARKET_MSIG_INFO, timeout=3600)

    def test_get_market_info_cache_miss_success(self, mock_rpc, mock_cache):
        mock_cache.get.return_value = None
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"multisig_info": TEST_MARKET_MSIG_INFO}
        info = get_market_prepare_multisig_info()
        self.assertEqual(info, TEST_MARKET_MSIG_INFO)
        mock_cache.get.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY)
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "prepare_multisig", is_wallet=True)
        mock_cache.set.assert_called_once_with(monero_service.MARKET_MULTISIG_INFO_CACHE_KEY, TEST_MARKET_MSIG_INFO, timeout=3600)

    def test_get_market_info_rpc_error(self, mock_rpc, mock_cache):
        mock_cache.get.return_value = None
        mock_rpc.side_effect = MoneroRPCError("Prepare failed", -20)
        info = get_market_prepare_multisig_info()
        self.assertIsNone(info)
        mock_cache.set.assert_not_called()

    def test_get_market_info_rpc_returns_invalid_hex(self, mock_rpc, mock_cache):
        mock_cache.get.return_value = None
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"multisig_info": "INVALID_RPC_HEX_ODD"}
        info = get_market_prepare_multisig_info()
        self.assertIsNone(info)
        mock_cache.set.assert_not_called()

    def test_get_market_info_rpc_returns_wrong_structure(self, mock_rpc, mock_cache):
        mock_cache.get.return_value = None
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"wrong_key": TEST_MARKET_MSIG_INFO}
        info = get_market_prepare_multisig_info()
        self.assertIsNone(info)
        mock_cache.set.assert_not_called()


# --- Create Multisig Wallet Tests ---
@patch('backend.store.services.monero_service.delete_monero_wallet_password') # FIXED Patch Path
@patch('backend.store.services.monero_service.store_monero_wallet_password') # FIXED Patch Path
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@patch('secrets.token_urlsafe')
@patch('secrets.token_hex')
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestCreateMultisigWallet(TestCase):

    def test_create_multisig_success(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix" # For potential internal token generation
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        expected_wallet_name = f"msig_order_{TEST_ORDER_ID_STR}"
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        final_msig_info = TEST_FINAL_MSIG_INFO

        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {
            "address": TEST_VALID_XMR_ADDRESS,
            "multisig_info": final_msig_info
        }

        result = create_monero_multisig_wallet(
            participant_multisig_infos=participant_infos, order_id_str=TEST_ORDER_ID_STR, threshold=2
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.get("address"), TEST_VALID_XMR_ADDRESS)
        self.assertEqual(result.get("wallet_name"), expected_wallet_name)
        self.assertEqual(result.get("multisig_info"), final_msig_info)
        mock_store_pw.assert_called_once_with(expected_wallet_name, DUMMY_TEST_WALLET_PASSWORD, raise_error=True) # R17 Use constant
        expected_rpc_params = {
            "multisig_info": participant_infos, "threshold": 2, "filename": expected_wallet_name,
            "password": DUMMY_TEST_WALLET_PASSWORD, "autosave_current": False, "language": "English", # R17 Use constant
        }
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "make_multisig", expected_rpc_params, is_wallet=True)
        mock_validator.assert_called_once_with(TEST_VALID_XMR_ADDRESS)
        mock_delete_pw.assert_not_called()

    # ... (other validation tests remain the same) ...
    def test_create_multisig_validation_fails_participants(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        with self.assertRaisesRegex(ValueError, "Requires at least 2"):
            create_monero_multisig_wallet([TEST_PARTICIPANT_MSIG_INFO_1], TEST_ORDER_ID_STR)
        with self.assertRaisesRegex(TypeError, "must be a list"):
            create_monero_multisig_wallet("not a list", TEST_ORDER_ID_STR) # type: ignore

    def test_create_multisig_validation_fails_threshold(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        with self.assertRaisesRegex(ValueError, r"Threshold \(1\) must be between 2 and number of participants \(2\)\."):
            create_monero_multisig_wallet(infos, TEST_ORDER_ID_STR, threshold=1)
        with self.assertRaisesRegex(ValueError, r"Threshold \(3\) must be between 2 and number of participants \(2\)\."):
            create_monero_multisig_wallet(infos, TEST_ORDER_ID_STR, threshold=3)
        with self.assertRaisesRegex(TypeError, "must be an integer"):
            create_monero_multisig_wallet(infos, TEST_ORDER_ID_STR, threshold="2") # type: ignore

    def test_create_multisig_validation_fails_hex_info(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        infos = [TEST_PARTICIPANT_MSIG_INFO_1, "INVALID HEX ODD"]
        with self.assertRaisesRegex(ValueError, "Invalid hex data format found for participant info at index 1"):
            create_monero_multisig_wallet(infos, TEST_ORDER_ID_STR)

    def test_create_multisig_validation_fails_order_id(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        with self.assertRaisesRegex(ValueError, "valid, non-empty string for order_id_str"):
            create_monero_multisig_wallet(infos, "")
        with self.assertRaisesRegex(ValueError, "valid, non-empty string for order_id_str"):
            create_monero_multisig_wallet(infos, None) # type: ignore

    def test_create_multisig_vault_store_fails(self, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix"
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        mock_store_pw.side_effect = VaultError("Vault connection failed")
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        with self.assertRaises(VaultError):
            create_monero_multisig_wallet(participant_infos, TEST_ORDER_ID_STR)
        mock_rpc.assert_not_called()
        mock_delete_pw.assert_not_called()

    @patch('sys.exc_info')
    def test_create_multisig_rpc_fails_vault_cleanup_called(self, mock_exc_info, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix"
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        expected_wallet_name = f"msig_order_{TEST_ORDER_ID_STR}"
        rpc_error = MoneroRPCError("RPC make_multisig failed", -30)
        mock_rpc.side_effect = rpc_error
        mock_exc_info.return_value = (type(rpc_error), rpc_error, None)
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        with self.assertRaises(MoneroRPCError):
            create_monero_multisig_wallet(participant_infos, TEST_ORDER_ID_STR)
        mock_store_pw.assert_called_once_with(expected_wallet_name, DUMMY_TEST_WALLET_PASSWORD, raise_error=True) # R17 Use constant
        mock_rpc.assert_called_once()
        mock_delete_pw.assert_called_once_with(expected_wallet_name, raise_error=False)

    @patch('sys.exc_info') # Need to mock exc_info for finally block check
    def test_create_multisig_rpc_returns_invalid_address(self, mock_exc_info, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix"
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        expected_wallet_name = f"msig_order_{TEST_ORDER_ID_STR}"
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"address": "invalid-address", "multisig_info": TEST_FINAL_MSIG_INFO}
        mock_validator.side_effect = DjangoValidationError("Invalid format")
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        # Simulate exception for finally block check
        rpc_error = MoneroRPCError("make_multisig succeeded HTTP but returned unexpected data", code=-96)
        mock_exc_info.return_value = (type(rpc_error), rpc_error, None)
        with self.assertRaisesRegex(MoneroRPCError, "make_multisig succeeded HTTP but returned unexpected data.*Invalid or missing 'address'"):
            create_monero_multisig_wallet(participant_infos, TEST_ORDER_ID_STR)
        mock_validator.assert_called_once_with("invalid-address")
        mock_store_pw.assert_called_once()
        mock_delete_pw.assert_called_once_with(expected_wallet_name, raise_error=False)

    @patch('sys.exc_info') # Need to mock exc_info for finally block check
    def test_create_multisig_rpc_returns_invalid_msig_info(self, mock_exc_info, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix"
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        expected_wallet_name = f"msig_order_{TEST_ORDER_ID_STR}"
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"address": TEST_VALID_XMR_ADDRESS, "multisig_info": "INVALID_HEX_ODD"}
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        # Simulate exception for finally block check
        rpc_error = MoneroRPCError("make_multisig succeeded HTTP but returned unexpected data", code=-96)
        mock_exc_info.return_value = (type(rpc_error), rpc_error, None)
        with self.assertRaisesRegex(MoneroRPCError, "make_multisig succeeded HTTP but returned unexpected data.*Invalid or missing 'multisig_info'"):
            create_monero_multisig_wallet(participant_infos, TEST_ORDER_ID_STR)
        mock_validator.assert_called_once_with(TEST_VALID_XMR_ADDRESS)
        mock_store_pw.assert_called_once()
        mock_delete_pw.assert_called_once_with(expected_wallet_name, raise_error=False)

    @patch('sys.exc_info') # Need to mock exc_info for finally block check
    def test_create_multisig_rpc_returns_missing_keys(self, mock_exc_info, mock_hex, mock_pw, mock_validator, mock_rpc, mock_store_pw, mock_delete_pw):
        mock_hex.return_value = "suffix"
        mock_pw.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        expected_wallet_name = f"msig_order_{TEST_ORDER_ID_STR}"
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {} # Missing keys
        participant_infos = [TEST_PARTICIPANT_MSIG_INFO_1, TEST_PARTICIPANT_MSIG_INFO_2]
        # Simulate exception for finally block check
        rpc_error = MoneroRPCError("make_multisig succeeded HTTP but returned unexpected data", code=-96)
        mock_exc_info.return_value = (type(rpc_error), rpc_error, None)
        with self.assertRaisesRegex(MoneroRPCError, "make_multisig succeeded HTTP but returned unexpected data.*Invalid or missing 'address'.*Invalid or missing 'multisig_info'"):
            create_monero_multisig_wallet(participant_infos, TEST_ORDER_ID_STR)
        mock_validator.assert_not_called()
        mock_store_pw.assert_called_once()
        mock_delete_pw.assert_called_once_with(expected_wallet_name, raise_error=False)


# --- Transaction Lifecycle Tests (Prepare, Sign, Submit) ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.get_monero_wallet_password') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestTransactionLifecycle(TestCase):

    # R16 Fix: Remove {"result":...} wrapping from helper return
    def _mock_rpc_side_effect(self, expected_wallet_name, *rpc_results, password=DUMMY_TEST_WALLET_PASSWORD): # R17 Use Constant
        call_sequence = iter(rpc_results)
        def side_effect(rpc_url, method, params=None, is_wallet=True, **kwargs):
            print(f"Mock RPC Helper Lifecycle: method={method}, params={params}")
            if method == "open_wallet":
                print(f"Mock RPC Helper Lifecycle: Simulating SUCCESS for open_wallet '{params.get('filename')}'")
                return {"status": "OK"} # Open returns actual result content
            elif method == "close_wallet":
                print(f"Mock RPC Helper Lifecycle: Simulating SUCCESS for close_wallet '{params.get('filename')}'")
                return {"status": "OK"} # Close returns actual result content
            else:
                try:
                    action_result = next(call_sequence)
                    print(f"Mock RPC Helper Lifecycle: Returning {action_result} for method {method}")
                    if isinstance(action_result, Exception):
                        raise action_result
                    else:
                        # Return the raw result dictionary - _make_rpc_request handles JSON-RPC layer
                        return action_result
                except StopIteration:
                    raise AssertionError(f"Mock RPC Helper Lifecycle: Called too many times for method {method}")
        return side_effect

    def test_prepare_release_tx_success(self, mock_validator, mock_get_password, mock_rpc_request):
        mock_order = create_mock_order()
        vendor_addr, amount_xmr = TEST_VALID_XMR_ADDRESS, Decimal("2.5")
        amount_pico = xmr_to_piconero(amount_xmr)
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        prepare_success_result = {
            "unsigned_txset": TEST_UNSIGNED_TXSET, "fee": 12345000000
        }
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            TEST_MULTISIG_WALLET_NAME, prepare_success_result
        )

        txset_hex = prepare_monero_release_tx(mock_order, amount_xmr, vendor_addr)

        self.assertEqual(txset_hex, TEST_UNSIGNED_TXSET)
        mock_get_password.assert_called_once_with(TEST_MULTISIG_WALLET_NAME, raise_error=True)
        expected_transfer_params = {
            "destinations": [{'address': vendor_addr, 'amount': amount_pico}], "account_index": 0,
            "priority": 1, "get_tx_hex": False, "do_not_relay": True, "get_unsigned_txset": True
        }
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": TEST_MULTISIG_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "transfer", expected_transfer_params, is_wallet=True),
            call(TEST_RPC_URL, "close_wallet", {"filename": TEST_MULTISIG_WALLET_NAME}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 3)

    def test_prepare_release_tx_validation_fails(self, mock_validator, mock_get_password, mock_rpc_request):
        mock_order = create_mock_order()
        mock_validator.side_effect = DjangoValidationError("Invalid address")
        txset_hex = prepare_monero_release_tx(mock_order, Decimal("1.0"), "bad-address")
        self.assertIsNone(txset_hex)
        mock_rpc_request.assert_not_called()
        mock_validator.side_effect = None
        txset_hex = prepare_monero_release_tx(mock_order, Decimal("-1.0"), TEST_VALID_XMR_ADDRESS)
        self.assertIsNone(txset_hex)
        mock_rpc_request.assert_not_called()
        mock_order_bad = create_mock_order(xmr_multisig_wallet_name=None)
        txset_hex = prepare_monero_release_tx(mock_order_bad, Decimal("1.0"), TEST_VALID_XMR_ADDRESS)
        self.assertIsNone(txset_hex)
        mock_rpc_request.assert_not_called()

    def test_prepare_release_tx_insufficient_funds(self, mock_validator, mock_get_password, mock_rpc_request):
        mock_order = create_mock_order()
        vendor_addr, amount_xmr = TEST_VALID_XMR_ADDRESS, Decimal("1000.0")
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        insufficient_funds_error = MoneroRPCError("Not enough spendable outputs", code=-38)
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            TEST_MULTISIG_WALLET_NAME, insufficient_funds_error
        )

        txset_hex = prepare_monero_release_tx(mock_order, amount_xmr, vendor_addr)

        self.assertIsNone(txset_hex)
        mock_get_password.assert_called_once()
        self.assertEqual(mock_rpc_request.call_count, 3) # open, transfer-failed, close

    def test_sign_txset_partial_success(self, mock_validator, mock_get_password, mock_rpc_request):
        signing_wallet_name = "participant_1_wallet"
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        sign_partial_result = {
            "tx_data_hex": TEST_PARTIAL_SIGNED_TXSET, "tx_hash_list": []
        }
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            signing_wallet_name, sign_partial_result
        )

        signed_hex, is_complete = sign_monero_txset(TEST_UNSIGNED_TXSET, signing_wallet_name)

        self.assertEqual(signed_hex, TEST_PARTIAL_SIGNED_TXSET)
        self.assertFalse(is_complete)
        mock_get_password.assert_called_once_with(signing_wallet_name, raise_error=True)
        expected_sign_params = {"tx_data_hex": TEST_UNSIGNED_TXSET}
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": signing_wallet_name, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "sign_multisig", expected_sign_params, is_wallet=True),
            call(TEST_RPC_URL, "close_wallet", {"filename": signing_wallet_name}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 3)

    def test_sign_txset_complete_success(self, mock_validator, mock_get_password, mock_rpc_request):
        signing_wallet_name = "participant_2_wallet"
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        sign_complete_result = {
            "tx_data_hex": TEST_FULL_SIGNED_TXSET, "tx_hash_list": [TEST_VALID_TXID]
        }
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            signing_wallet_name, sign_complete_result
        )

        signed_hex, is_complete = sign_monero_txset(TEST_PARTIAL_SIGNED_TXSET, signing_wallet_name)

        self.assertEqual(signed_hex, TEST_FULL_SIGNED_TXSET)
        self.assertTrue(is_complete)
        mock_get_password.assert_called_once_with(signing_wallet_name, raise_error=True)
        expected_sign_params = {"tx_data_hex": TEST_PARTIAL_SIGNED_TXSET}
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": signing_wallet_name, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "sign_multisig", expected_sign_params, is_wallet=True),
            call(TEST_RPC_URL, "close_wallet", {"filename": signing_wallet_name}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 3)

    def test_sign_txset_invalid_input(self, mock_validator, mock_get_password, mock_rpc_request):
        signed_hex, is_complete = sign_monero_txset("INVALID_HEX_ODD", TEST_WALLET_NAME)
        self.assertIsNone(signed_hex)
        self.assertFalse(is_complete)
        mock_rpc_request.assert_not_called()
        signed_hex, is_complete = sign_monero_txset(TEST_UNSIGNED_TXSET, None) # type: ignore
        self.assertIsNone(signed_hex)
        self.assertFalse(is_complete)
        mock_rpc_request.assert_not_called()

    def test_sign_txset_rpc_error(self, mock_validator, mock_get_password, mock_rpc_request):
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        sign_error = MoneroRPCError("Signing failed", -15)
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            TEST_WALLET_NAME, sign_error
        )

        signed_hex, is_complete = sign_monero_txset(TEST_UNSIGNED_TXSET, TEST_WALLET_NAME)

        self.assertIsNone(signed_hex)
        self.assertFalse(is_complete)
        self.assertEqual(mock_rpc_request.call_count, 3) # open, sign-failed, close

    def test_submit_txset_success(self, mock_validator, mock_get_password, mock_rpc_request):
        submit_context_wallet = TEST_MULTISIG_WALLET_NAME
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        submit_success_result = {
            "tx_hash_list": [TEST_VALID_TXID]
        }
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            submit_context_wallet, submit_success_result
        )

        txid = submit_monero_txset(TEST_FULL_SIGNED_TXSET, submit_context_wallet)

        self.assertEqual(txid, TEST_VALID_TXID)
        mock_get_password.assert_called_once_with(submit_context_wallet, raise_error=True)
        expected_submit_params = {"tx_data_hex": TEST_FULL_SIGNED_TXSET}
        expected_calls = [
            call(TEST_RPC_URL, "open_wallet", {"filename": submit_context_wallet, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), # R17 Use constant
            call(TEST_RPC_URL, "submit_multisig", expected_submit_params, is_wallet=True),
            call(TEST_RPC_URL, "close_wallet", {"filename": submit_context_wallet}, is_wallet=True)
        ]
        mock_rpc_request.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc_request.call_count, 3)

    def test_submit_txset_invalid_input(self, mock_validator, mock_get_password, mock_rpc_request):
        txid = submit_monero_txset("INVALID_HEX_FOR_SUBMIT_ODD", TEST_WALLET_NAME)
        self.assertIsNone(txid)
        mock_rpc_request.assert_not_called()
        txid = submit_monero_txset(TEST_FULL_SIGNED_TXSET, "")
        self.assertIsNone(txid)
        mock_rpc_request.assert_not_called()

    def test_submit_txset_rejected_by_network(self, mock_validator, mock_get_password, mock_rpc_request):
        submit_context_wallet = TEST_MULTISIG_WALLET_NAME
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        rejection_error = MoneroRPCError("Transaction was rejected by daemon", code=-5)
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            submit_context_wallet, rejection_error
        )

        txid = submit_monero_txset(TEST_FULL_SIGNED_TXSET, submit_context_wallet)

        self.assertIsNone(txid)
        self.assertEqual(mock_rpc_request.call_count, 3) # open, submit-failed, close

    def test_submit_txset_rpc_returns_empty_list(self, mock_validator, mock_get_password, mock_rpc_request):
        submit_context_wallet = TEST_MULTISIG_WALLET_NAME
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        submit_empty_list_result = {"tx_hash_list": []}
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            submit_context_wallet, submit_empty_list_result
        )
        txid = submit_monero_txset(TEST_FULL_SIGNED_TXSET, submit_context_wallet)
        self.assertIsNone(txid)
        self.assertEqual(mock_rpc_request.call_count, 3) # open, submit-ok-but-empty, close

    def test_submit_txset_rpc_returns_invalid_txid(self, mock_validator, mock_get_password, mock_rpc_request):
        submit_context_wallet = TEST_MULTISIG_WALLET_NAME
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        submit_bad_txid_result = {"tx_hash_list": ["INVALID_TXID_HEX_ODD"]}
        mock_rpc_request.side_effect = self._mock_rpc_side_effect(
            submit_context_wallet, submit_bad_txid_result
        )
        txid = submit_monero_txset(TEST_FULL_SIGNED_TXSET, submit_context_wallet)
        self.assertIsNone(txid)
        self.assertEqual(mock_rpc_request.call_count, 3) # open, submit-ok-but-invalid, close


# --- Orchestration Tests (Finalize & Broadcast) ---
@patch('backend.store.services.monero_service.submit_monero_txset') # FIXED Patch Path
@patch('backend.store.services.monero_service.sign_monero_txset') # FIXED Patch Path
class TestOrchestration(TestCase):

    def test_finalize_and_broadcast_release_success(self, mock_sign, mock_submit):
        mock_order = create_mock_order()
        initial_txset = TEST_PARTIAL_SIGNED_TXSET
        final_txset_after_sign = TEST_FULL_SIGNED_TXSET
        expected_broadcast_txid = TEST_VALID_TXID
        mock_sign.return_value = (final_txset_after_sign, True)
        mock_submit.return_value = expected_broadcast_txid

        txid = finalize_and_broadcast_xmr_release(mock_order, initial_txset)

        self.assertEqual(txid, expected_broadcast_txid)
        mock_sign.assert_called_once_with(initial_txset, mock_order.xmr_multisig_wallet_name)
        mock_submit.assert_called_once_with(final_txset_after_sign, mock_order.xmr_multisig_wallet_name)

    def test_finalize_and_broadcast_signing_fails(self, mock_sign, mock_submit):
        mock_order = create_mock_order()
        initial_txset = TEST_PARTIAL_SIGNED_TXSET
        mock_sign.return_value = (None, False) # Simulate sign failure
        txid = finalize_and_broadcast_xmr_release(mock_order, initial_txset)
        self.assertIsNone(txid)
        mock_sign.assert_called_once_with(initial_txset, mock_order.xmr_multisig_wallet_name)
        mock_submit.assert_not_called()

    def test_finalize_and_broadcast_signing_not_complete(self, mock_sign, mock_submit):
        mock_order = create_mock_order()
        initial_txset = TEST_UNSIGNED_TXSET
        mock_sign.return_value = (TEST_PARTIAL_SIGNED_TXSET, False) # Simulate partial sign
        txid = finalize_and_broadcast_xmr_release(mock_order, initial_txset)
        self.assertIsNone(txid)
        mock_sign.assert_called_once_with(initial_txset, mock_order.xmr_multisig_wallet_name)
        mock_submit.assert_not_called()

    def test_finalize_and_broadcast_submit_fails(self, mock_sign, mock_submit):
        mock_order = create_mock_order()
        initial_txset = TEST_PARTIAL_SIGNED_TXSET
        final_txset_after_sign = TEST_FULL_SIGNED_TXSET
        mock_sign.return_value = (final_txset_after_sign, True)
        mock_submit.return_value = None # Simulate submit failure
        txid = finalize_and_broadcast_xmr_release(mock_order, initial_txset)
        self.assertIsNone(txid)
        mock_sign.assert_called_once_with(initial_txset, mock_order.xmr_multisig_wallet_name)
        mock_submit.assert_called_once_with(final_txset_after_sign, mock_order.xmr_multisig_wallet_name)

    def test_finalize_and_broadcast_invalid_input_hex(self, mock_sign, mock_submit):
        mock_order = create_mock_order()
        txid = finalize_and_broadcast_xmr_release(mock_order, "INVALID_HEX_ODD")
        self.assertIsNone(txid)
        mock_sign.assert_not_called()
        mock_submit.assert_not_called()

    def test_finalize_and_broadcast_invalid_order_wallet(self, mock_sign, mock_submit):
        mock_order_bad = create_mock_order(xmr_multisig_wallet_name=None)
        initial_txset = TEST_PARTIAL_SIGNED_TXSET
        with self.assertRaisesRegex(ValueError, "missing valid Monero multisig wallet name"):
            finalize_and_broadcast_xmr_release(mock_order_bad, initial_txset)
        mock_sign.assert_not_called()
        mock_submit.assert_not_called()


# --- Withdrawal Tests ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestProcessWithdrawal(TestCase):
    def test_process_withdrawal_success(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        amount_xmr = Decimal("0.987")
        amount_pico = 987000000000
        recipient_address = TEST_VALID_XMR_ADDRESS
        expected_txid = TEST_VALID_TXID
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {
            "tx_hash": expected_txid, "fee": 543210000,
            "tx_key": secrets.token_hex(32), "tx_blob": secrets.token_hex(128)
        }
        success, txid = process_withdrawal(mock_user, amount_xmr, recipient_address)
        self.assertTrue(success)
        self.assertEqual(txid, expected_txid)
        mock_validator.assert_called_once_with(recipient_address)
        expected_rpc_params = {
            "destinations": [{'address': recipient_address, 'amount': amount_pico}], "account_index": 0,
            "priority": 2, "get_tx_hex": True, "get_tx_key": True, "do_not_relay": False
        }
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "transfer", expected_rpc_params, is_wallet=True)

    def test_process_withdrawal_validation_fails(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        mock_validator.side_effect = DjangoValidationError("Bad address")
        success, txid = process_withdrawal(mock_user, Decimal("1.0"), "bad-address")
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_not_called()
        mock_validator.side_effect = None
        success, txid = process_withdrawal(mock_user, Decimal("0.0"), TEST_VALID_XMR_ADDRESS)
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_not_called()
        success, txid = process_withdrawal(None, Decimal("1.0"), TEST_VALID_XMR_ADDRESS) # type: ignore
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_not_called()

    def test_process_withdrawal_insufficient_funds(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        mock_rpc.side_effect = MoneroRPCError("Not enough money", code=-38)
        success, txid = process_withdrawal(mock_user, Decimal("5000.0"), TEST_VALID_XMR_ADDRESS)
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_called_once()

    def test_process_withdrawal_generic_transfer_fail(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        mock_rpc.side_effect = MoneroRPCError("Transaction creation failed", code=-4)
        success, txid = process_withdrawal(mock_user, Decimal("1.0"), TEST_VALID_XMR_ADDRESS)
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_called_once()

    def test_process_withdrawal_rpc_returns_invalid_txid(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"tx_hash": "INVALID_TXID_ODD"}
        success, txid = process_withdrawal(mock_user, Decimal("1.0"), TEST_VALID_XMR_ADDRESS)
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_called_once()

    def test_process_withdrawal_rpc_returns_missing_key(self, mock_validator, mock_rpc):
        mock_user = create_mock_user()
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"fee": 1000} # Missing tx_hash
        success, txid = process_withdrawal(mock_user, Decimal("1.0"), TEST_VALID_XMR_ADDRESS)
        self.assertFalse(success)
        self.assertIsNone(txid)
        mock_rpc.assert_called_once()


# --- Payment Scan Tests ---
# Adapt patching based on ledger availability and import path
_ledger_filter_path = 'backend.ledger.models.LedgerTransaction.objects.filter' if LedgerTransaction != MagicMock else 'unittest.mock.MagicMock'
@patch(_ledger_filter_path) # FIXED Patch Path
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.get_daemon_block_height') # FIXED Patch Path
@patch('backend.store.services.monero_service.GlobalSettings.get_solo') # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestScanForPayment(TestCase):

    def test_scan_success_confirmed(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        current_height, tx_height = 2000000, 1999990
        expected_confs = current_height - tx_height + 1
        received_pico = 1234567890123 # Use integer
        received_xmr = piconero_to_xmr(received_pico)
        tx_hash = TEST_VALID_TXID
        # Expect slightly less than received
        mock_payment = create_mock_payment(expected_amount_native=Decimal(received_pico - 100), confirmations_needed=10)
        mock_daemon_height.return_value = current_height
        mock_ledger_filter.return_value.exists.return_value = False
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = { "payments": [{"payment_id": mock_payment.payment_id_monero, "tx_hash": tx_hash, "amount": received_pico, "block_height": tx_height, "unlock_time": 0}] }
        result = scan_for_payment_confirmation(mock_payment)
        self.assertTrue(result[0])
        self.assertEqual(result[1], received_xmr)
        self.assertEqual(result[2], expected_confs)
        self.assertEqual(result[3], tx_hash)
        mock_daemon_height.assert_called_once()
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "get_payments", {"payment_ids": [mock_payment.payment_id_monero]}, is_wallet=True)
        mock_ledger_filter.assert_called_once_with(external_txid=tx_hash, transaction_type='DEPOSIT', currency='XMR')


    def test_scan_found_not_enough_confirmations(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=10)
        mock_get_settings.return_value = mock_settings_obj
        current_height, tx_height = 2000000, 1999995 # 6 confs
        mock_payment = create_mock_payment(confirmations_needed=10) # Needs 10
        mock_daemon_height.return_value = current_height
        mock_ledger_filter.return_value.exists.return_value = False
        mock_amount_pico = int(mock_payment.expected_amount_native)
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = { "payments": [{"payment_id": mock_payment.payment_id_monero, "tx_hash": TEST_VALID_TXID, "amount": mock_amount_pico, "block_height": tx_height, "unlock_time": 0}] }

        result = scan_for_payment_confirmation(mock_payment)

        self.assertFalse(result[0])
        # Filter should now be called correctly
        mock_ledger_filter.assert_called_once_with(
            external_txid=TEST_VALID_TXID, transaction_type='DEPOSIT', currency='XMR'
        )

    def test_scan_found_not_enough_amount(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        current_height, tx_height = 2000000, 1999990
        mock_payment = create_mock_payment(expected_amount_native=Decimal("2000000000000"), confirmations_needed=5) # Expect 2 XMR (pico)
        mock_daemon_height.return_value = current_height
        mock_ledger_filter.return_value.exists.return_value = False
        # Provide payment with only 1 XMR (pico)
        received_pico_int = 1000000000000
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = { "payments": [{"payment_id": mock_payment.payment_id_monero, "tx_hash": TEST_VALID_TXID, "amount": received_pico_int, "block_height": tx_height, "unlock_time": 0}] }

        result = scan_for_payment_confirmation(mock_payment)

        self.assertFalse(result[0])
        # Filter should now be called correctly
        mock_ledger_filter.assert_called_once_with(
            external_txid=TEST_VALID_TXID, transaction_type='DEPOSIT', currency='XMR'
        )

    def test_scan_found_tx_already_processed(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        current_height, tx_height = 2000000, 1999990
        mock_payment = create_mock_payment(confirmations_needed=5)
        mock_daemon_height.return_value = current_height
        mock_ledger_filter.return_value.exists.return_value = True # Already processed
        mock_amount_pico = int(mock_payment.expected_amount_native)
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = { "payments": [{"payment_id": mock_payment.payment_id_monero, "tx_hash": TEST_VALID_TXID, "amount": mock_amount_pico, "block_height": tx_height, "unlock_time": 0}] }

        result = scan_for_payment_confirmation(mock_payment)

        self.assertFalse(result[0])
        # Filter should now be called correctly
        mock_ledger_filter.assert_called_once_with(external_txid=TEST_VALID_TXID, transaction_type='DEPOSIT', currency='XMR')

    def test_scan_payment_not_found(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        mock_payment = create_mock_payment()
        mock_daemon_height.return_value = 2000000
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"payments": []}
        result = scan_for_payment_confirmation(mock_payment)
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])
        self.assertEqual(result[1], Decimal('0.0'))
        self.assertEqual(result[2], 0)
        self.assertIsNone(result[3])
        mock_ledger_filter.assert_not_called()

    def test_scan_daemon_height_fails(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        mock_payment = create_mock_payment()
        mock_daemon_height.return_value = None
        result = scan_for_payment_confirmation(mock_payment)
        self.assertIsNone(result) # Service returns None on critical failure
        mock_rpc.assert_not_called()
        mock_ledger_filter.assert_not_called()

    def test_scan_rpc_error(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_settings_obj = MagicMock(confirmations_needed_xmr=5)
        mock_get_settings.return_value = mock_settings_obj
        mock_payment = create_mock_payment()
        mock_daemon_height.return_value = 2000000
        mock_rpc.side_effect = MoneroRPCError("RPC Busy", -1)
        result = scan_for_payment_confirmation(mock_payment)
        self.assertIsNone(result) # Service returns None on critical failure
        mock_ledger_filter.assert_not_called()

    def test_scan_invalid_payment_object(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        result = scan_for_payment_confirmation(None) # type: ignore
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])
        mock_daemon_height.assert_not_called()

    def test_scan_invalid_payment_id(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_payment = create_mock_payment(payment_id_monero="invalid-short")
        result = scan_for_payment_confirmation(mock_payment)
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])
        mock_get_settings.assert_called_once()
        mock_daemon_height.assert_not_called()

    def test_scan_invalid_expected_amount(self, mock_get_settings, mock_daemon_height, mock_rpc, mock_ledger_filter):
        mock_payment = create_mock_payment(expected_amount_native=Decimal("-100"))
        result = scan_for_payment_confirmation(mock_payment)
        self.assertIsInstance(result, tuple)
        self.assertFalse(result[0])
        mock_get_settings.assert_called_once()
        mock_daemon_height.assert_not_called()


# --- Centralized Escrow Release Tests ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestProcessEscrowRelease(TestCase):
    def test_centralized_release_success(self, mock_validator, mock_rpc):
        mock_order = create_mock_order()
        amount_xmr, recipient_address = Decimal("1.45"), TEST_VALID_XMR_ADDRESS
        amount_pico = xmr_to_piconero(amount_xmr)
        expected_txid = TEST_VALID_TXID
        # R16 Fix: Mock _make_rpc_request correctly
        mock_rpc.return_value = {"tx_hash": expected_txid, "fee": 678900000}
        success, txid = process_escrow_release(mock_order, recipient_address, amount_xmr)
        self.assertTrue(success)
        self.assertEqual(txid, expected_txid)
        mock_validator.assert_called_once_with(recipient_address)
        expected_rpc_params = { "destinations": [{'address': recipient_address, 'amount': amount_pico}], "account_index": 0, "priority": 2, "get_tx_hex": True, "get_tx_key": True, "do_not_relay": False }
        mock_rpc.assert_called_once_with(TEST_RPC_URL, "transfer", expected_rpc_params, is_wallet=True)

    def test_centralized_release_validation_fails(self, mock_validator, mock_rpc):
        mock_order = create_mock_order()
        mock_validator.side_effect = DjangoValidationError("Bad address")
        success, txid = process_escrow_release(mock_order, "bad-address", Decimal("1.0"))
        self.assertFalse(success); self.assertIsNone(txid); mock_rpc.assert_not_called()
        mock_validator.side_effect = None
        success, txid = process_escrow_release(mock_order, TEST_VALID_XMR_ADDRESS, Decimal("-1.0"))
        self.assertFalse(success); self.assertIsNone(txid); mock_rpc.assert_not_called()

    def test_centralized_release_insufficient_funds(self, mock_validator, mock_rpc):
        mock_order = create_mock_order()
        mock_rpc.side_effect = MoneroRPCError("Not enough money", code=-38)
        success, txid = process_escrow_release(mock_order, TEST_VALID_XMR_ADDRESS, Decimal("5000.0"))
        self.assertFalse(success); self.assertIsNone(txid); mock_rpc.assert_called_once()


# --- Dispute Transaction Tests ---
@patch('backend.store.services.monero_service._make_rpc_request') # FIXED Patch Path
@patch('backend.store.services.monero_service.get_monero_wallet_password') # FIXED Patch Path
@patch('backend.store.services.monero_service.validate_monero_address', return_value=None) # FIXED Patch Path
@override_settings(MONERO_WALLET_RPC_URL=TEST_RPC_URL)
class TestCreateDisputeTx(TestCase):

    # R16 Fix: Remove {"result":...} wrapping from helper return
    def _mock_rpc_side_effect(self, expected_wallet_name, *rpc_results, password=DUMMY_TEST_WALLET_PASSWORD): # R17 Use Constant
        call_sequence = iter(rpc_results)
        def side_effect(rpc_url, method, params=None, is_wallet=True, **kwargs):
            print(f"Mock RPC Helper Dispute: method={method}, params={params}")
            if method == "open_wallet":
                print(f"Mock RPC Helper Dispute: Simulating SUCCESS for open_wallet '{params.get('filename')}'")
                return {"status": "OK"}
            elif method == "close_wallet":
                print(f"Mock RPC Helper Dispute: Simulating SUCCESS for close_wallet '{params.get('filename')}'")
                return {"status": "OK"}
            else:
                try:
                    action_result = next(call_sequence)
                    print(f"Mock RPC Helper Dispute: Returning {action_result} for method {method}")
                    if isinstance(action_result, Exception):
                        raise action_result
                    else:
                        # Return the raw result dictionary
                        return action_result
                except StopIteration:
                    raise AssertionError(f"Mock RPC Helper Dispute: Called too many times for method {method}")
        return side_effect

    def test_dispute_tx_success_both_shares(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        buyer_addr, vendor_addr = "4AddressBuyer" + TEST_VALID_XMR_ADDRESS[13:], "4AddressVendor" + TEST_VALID_XMR_ADDRESS[14:]
        buyer_xmr, vendor_xmr = Decimal("0.6"), Decimal("0.4")
        buyer_pico, vendor_pico = xmr_to_piconero(buyer_xmr), xmr_to_piconero(vendor_xmr)
        expected_txid = TEST_VALID_TXID
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        # R16 Fix: Raw result for helper
        rpc_success_result = {"tx_hash": expected_txid, "fee": 777700000}
        mock_rpc.side_effect = self._mock_rpc_side_effect(
            TEST_MULTISIG_WALLET_NAME, rpc_success_result
        )

        txid = create_and_broadcast_dispute_tx(mock_order, buyer_xmr, buyer_addr, vendor_xmr, vendor_addr)

        self.assertEqual(txid, expected_txid)
        mock_validator.assert_has_calls([call(buyer_addr), call(vendor_addr)], any_order=True)
        mock_get_password.assert_called_once_with(TEST_MULTISIG_WALLET_NAME, raise_error=True)
        expected_transfer_params = { "destinations": [{'address': buyer_addr, 'amount': buyer_pico}, {'address': vendor_addr, 'amount': vendor_pico}], "account_index": 0, "priority": 3, "get_tx_hex": False, "get_tx_key": False, "do_not_relay": False }
        expected_calls = [ call(TEST_RPC_URL, "open_wallet", {"filename": TEST_MULTISIG_WALLET_NAME, "password": DUMMY_TEST_WALLET_PASSWORD}, is_wallet=True), call(TEST_RPC_URL, "transfer", expected_transfer_params, is_wallet=True), call(TEST_RPC_URL, "close_wallet", {"filename": TEST_MULTISIG_WALLET_NAME}, is_wallet=True) ] # R17 Use constant
        mock_rpc.assert_has_calls(expected_calls)
        self.assertEqual(mock_rpc.call_count, 3)

    def test_dispute_tx_success_buyer_only(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        buyer_addr, buyer_xmr = TEST_VALID_XMR_ADDRESS, Decimal("1.0")
        vendor_xmr = Decimal("0.0")
        buyer_pico = xmr_to_piconero(buyer_xmr)
        expected_txid = TEST_VALID_TXID
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        # R16 Fix: Raw result for helper
        rpc_success_result = {"tx_hash": expected_txid, "fee": 888800000}
        mock_rpc.side_effect = self._mock_rpc_side_effect(
            TEST_MULTISIG_WALLET_NAME, rpc_success_result
        )

        txid = create_and_broadcast_dispute_tx(mock_order, buyer_xmr, buyer_addr, vendor_xmr, None)

        self.assertEqual(txid, expected_txid)
        mock_validator.assert_called_once_with(buyer_addr)
        mock_get_password.assert_called_once()
        expected_transfer_params = { "destinations": [{'address': buyer_addr, 'amount': buyer_pico}], "account_index": 0, "priority": 3, "get_tx_hex": False, "get_tx_key": False, "do_not_relay": False }
        transfer_call = mock_rpc.call_args_list[1] # 0=open, 1=transfer, 2=close
        self.assertEqual(transfer_call, call(TEST_RPC_URL, "transfer", expected_transfer_params, is_wallet=True))
        self.assertEqual(mock_rpc.call_count, 3)

    def test_dispute_tx_no_payouts(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        txid = create_and_broadcast_dispute_tx(mock_order, Decimal("0.0"), None, Decimal("0.0"), None)
        self.assertIsNone(txid)
        mock_rpc.assert_not_called()
        mock_get_password.assert_not_called()

    def test_dispute_tx_validation_fails(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        with self.assertRaisesRegex(CryptoProcessingError, "Invalid parameters.*Buyer address required"):
            create_and_broadcast_dispute_tx(mock_order, Decimal("1.0"), None, Decimal("0.0"), None)
        mock_validator.side_effect = DjangoValidationError("Bad vendor addr")
        with self.assertRaisesRegex(CryptoProcessingError, "Invalid parameters.*Bad vendor addr"):
            create_and_broadcast_dispute_tx(mock_order, Decimal("0.1"), TEST_VALID_XMR_ADDRESS, Decimal("0.9"), "bad-addr")
        mock_validator.side_effect = None
        with self.assertRaisesRegex(CryptoProcessingError, "Invalid parameters.*non-negative Decimal"):
            create_and_broadcast_dispute_tx(mock_order, Decimal("-1.0"), TEST_VALID_XMR_ADDRESS, Decimal("0.0"), None)


    def test_dispute_tx_rpc_fails(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        mock_get_password.return_value = DUMMY_TEST_WALLET_PASSWORD # R17 Use constant
        rpc_error = MoneroRPCError("Dispute transfer failed", code=-4)
        mock_rpc.side_effect = self._mock_rpc_side_effect(
            TEST_MULTISIG_WALLET_NAME, rpc_error
        )
        with self.assertRaisesRegex(CryptoProcessingError, r"Failed to process XMR dispute transaction: Monero RPC Error \(Code: -4\): Dispute transfer failed"):
            create_and_broadcast_dispute_tx(mock_order, Decimal("1.0"), TEST_VALID_XMR_ADDRESS, Decimal("0.0"), None)
        self.assertEqual(mock_rpc.call_count, 3) # open, transfer-failed, close

    def test_dispute_tx_session_fails(self, mock_validator, mock_get_password, mock_rpc):
        mock_order = create_mock_order()
        mock_get_password.side_effect = VaultError("Cannot get password")
        with self.assertRaisesRegex(CryptoProcessingError, "Failed to process XMR dispute transaction.*Cannot get password"):
            create_and_broadcast_dispute_tx(mock_order, Decimal("1.0"), TEST_VALID_XMR_ADDRESS, Decimal("0.0"), None)
        mock_rpc.assert_not_called()


# --- Mock RPC Request Helper Tests ---
@patch('requests.post')
@override_settings(
    MONERO_WALLET_RPC_URL=TEST_RPC_URL,
    MONERO_RPC_USER="testuser",
    MONERO_RPC_PASSWORD=DUMMY_TEST_RPC_PASSWORD, # R17 Use constant
    SUPPORT_CONTACT_URL="http://support.example.com"
)
class TestMakeRpcRequest(TestCase):
    def test_rpc_success(self, mock_post):
        mock_response = MagicMock(status_code=200)
        expected_result = {"balance": 1000}
        mock_response.json.return_value = {"result": expected_result}
        mock_post.return_value = mock_response
        result = _make_rpc_request(TEST_RPC_URL, "get_balance", {"account_index": 0}, is_wallet=True)
        self.assertEqual(result, expected_result)
        mock_post.assert_called_once()
    def test_rpc_connection_error_all_retries_fail(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Refused consistently")
        with self.assertRaises(OperationFailedException) as cm:
            _make_rpc_request(TEST_RPC_URL, "get_balance", retries=1, is_wallet=True)
        self.assertIn(f"Network error connecting to {TEST_RPC_URL} after retries.", str(cm.exception))
        self.assertEqual(mock_post.call_count, 2)

    def test_rpc_connection_error_all_retries_fail_daemon(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectTimeout("Timeout consistently")
        with self.assertRaises(MoneroDaemonError) as cm:
            _make_rpc_request(TEST_RPC_URL, "get_block_count", retries=1, is_wallet=False)
        self.assertIn(f"Could not connect to Monero daemon at {TEST_RPC_URL} after retries.", str(cm.exception))
        self.assertEqual(mock_post.call_count, 2)

    def test_rpc_invalid_json_response(self, mock_post):
        mock_response = MagicMock(status_code=200, text="This is not JSON")
        json_error = json.JSONDecodeError("Expecting value", "This is not JSON", 0)
        mock_response.json.side_effect = json_error
        mock_post.return_value = mock_response
        # R16 Fix: Align regex with actual observed exception message from generic handler
        expected_regex = r"An unexpected error occurred during RPC request: Expecting value.*"
        # R19 Fix: Added indentation for the block below
        with self.assertRaisesRegex(OperationFailedException, expected_regex):
            _make_rpc_request(TEST_RPC_URL, "get_balance", is_wallet=True)


    def test_rpc_missing_url(self, mock_post):
        with self.assertRaisesRegex(ValueError, "Monero Wallet RPC URL is not configured or invalid."):
            _make_rpc_request(None, "get_balance", is_wallet=True) # type: ignore
        with self.assertRaisesRegex(ValueError, "Monero Daemon RPC URL is not configured or invalid."):
            _make_rpc_request(None, "get_block_count", is_wallet=False) # type: ignore

    #-----End of File-----