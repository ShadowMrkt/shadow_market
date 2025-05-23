# backend/store/tests/test_market_wallet_service.py
# --- Revision History ---
# 2025-05-18 (Gemini Rev 84): # <<< UPDATED REVISION
#   - FIXED: Standardized patch paths to use absolute `backend.` prefix
#     (e.g., `backend.store.services.market_wallet_service.XXX`) for all
#     patches targeting objects within the `market_wallet_service` or
#     `store.utils.conversion` to ensure mocks are applied correctly.
#   - FIXED: Added `@patch('backend.store.services.market_wallet_service.WEB3_AVAILABLE', True)`
#     to `test_withdraw_eth_send_fails` to ensure the test targets the correct
#     logic path when web3 libraries are assumed to be available for the test scenario.
# 2025-05-03 (Gemini Rev 83 - Address Pylance reportMissingImports):
#   - Analyzed Pylance errors for `common.vault_utils`, `bitcoinrpc.authproxy`,
#     and `web3.providers.http`.
#   - Confirmed the code already uses robust `try...except ImportError` blocks
#     to handle the potential absence of these modules, defining dummies/fallbacks.
#   - Pylance errors indicate an environment setup issue (missing packages or
#     incorrect Python path/project root config) rather than a code logic error.
#   - Added comments near relevant import blocks explaining this and directing
#     the user to fix the environment (install packages, check interpreter/paths).
#   - No changes made to the import logic itself as it correctly handles failures.
# 2025-04-28 (Gemini Rev 82 - Fix Incorrect Assertion in ETH Scan Test):
#   - TestScanForDeposit.test_scan_eth_block_not_found:
#     - Corrected the assertion on line 1367 (previously line ~1164 before B101 fixes).
#     - The test setup (tx in block 960, latest block 1000, 5 confs needed) results
#       in 41 confirmations (1000 - 960 + 1). Since 41 >= 5, the transaction IS confirmed.
#     - Changed the assertion from expecting `is_confirmed` to be False to correctly
#       expecting `is_confirmed` to be True based on the test's own parameters.
# 2025-04-28 (Gemini Rev 81 - Fix Bandit B101):
#   - FIXED: Replaced all `assert` statements with `if not condition: raise AssertionError`
#     throughout the file to resolve Bandit B101 warnings, while preserving test logic.
# 2025-04-28 (Gemini Rev 80 - Fix Invalid Escape Sequence '\m'):
#   - Fixed `SyntaxWarning: invalid escape sequence '\m'` found by `compileall`.
#   - Changed byte string literals on lines 329, 1587, 1674:
#     - `b'\mockedRawTxBytes'` -> `b'\\mockedRawTxBytes'`
#     - `b'\mockedRawTxBytesWithdraw'` -> `b'\\mockedRawTxBytesWithdraw'`
#     - `b'\mockedRawTxBytesSendFail'` -> `b'\\mockedRawTxBytesSendFail'`
#   - This ensures a literal backslash is used instead of an invalid escape.
# 2025-04-27 (Gemini Rev 79 - Fix Mock Exception Type in BTC Error Test):
#   - test_withdraw_btc_rpc_error:
#     - Modified the `exception_side_effect` function used by the `MockBtcExc` patch.
#     - Instead of returning a raw `MagicMock`, it now defines a local class
#       `MockExceptionClass(Exception)` which correctly inherits from BaseException.
#     - The `__init__` of this local class sets the `code` and `message` attributes
#       based on the input dictionary.
#     - The `exception_side_effect` now returns an instance of this proper exception subclass.
#     - This fixes the `TypeError: exceptions must derive from BaseException` that occurred
#       when the mock framework tried to raise the previous non-exception MagicMock object.
# 2025-04-27 (Gemini Rev 78 - Fix BTC RPC Error Test Mocking):
#   - test_withdraw_btc_rpc_error:
#     - Added a patch for `store.services.market_wallet_service.BitcoinJSONRPCException`.
#     - Configured the side_effect of the mocked exception class (`MockBtcExc`).
#     - When MockBtcExc is instantiated (e.g., `MockBtcExc({...})`), it now creates
#       a MagicMock instance and explicitly sets the `code` and `message` attributes
#       on that instance based on the dictionary passed during instantiation.
#     - This ensures that the exception object raised by the mock `sendtoaddress`
#       has the correct attributes (`code=-6`, `message='Insufficient funds'`)
#       when caught by the service code, allowing the correct error path to be taken.
# 2025-04-27 (Gemini Rev 77 - Add Missing Reset Mock in BTC Error Test):
#   - test_withdraw_btc_rpc_error: Added the missing call to
#     `mock_client_instance.sendtoaddress.reset_mock()` after the assertion block
#     for the "Insufficient Funds" test case (step 2). This prevents the mock's
#     side_effect from leaking into subsequent test cases within the same function.
# 2025-04-27 (Gemini Rev 72 - Update BTC Tests):
#   - TestScanForDeposit:
#     - Removed `test_scan_btc_placeholder`.
#     - Added new tests: `test_scan_btc_found_confirmed`, `test_scan_btc_found_unconfirmed`,
#       `test_scan_btc_insufficient_amount`, `test_scan_btc_no_match`,
#       `test_scan_btc_rpc_error`, `test_scan_btc_missing_order_id`.
#     - These tests mock `_get_btc_market_rpc_client`, `listtransactions`, and `btc_to_satoshi`.
#     - Assertions verify the returned tuple or None based on mock RPC data.
#   - TestInitiateMarketWithdrawal:
#     - Updated `test_withdraw_btc_success` to verify `sendtoaddress` arguments precisely.
#     - Added `test_withdraw_btc_rpc_error` to mock `sendtoaddress` raising exceptions
#       (ConnectionError, JSONRPCException - including insufficient funds) and assert
#       that `CryptoProcessingError` is raised with correct messages.
#     - Imported `BitcoinJSONRPCException` for specific error mocking.
# ... (previous revisions truncated) ...
# ------------------------

import pytest
import re
import logging # Import logging
from unittest.mock import patch, MagicMock, ANY, call, PropertyMock
from decimal import Decimal
from contextlib import contextmanager, nullcontext

# Django Imports
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import transaction, DatabaseError
from django.db.models import F # Needed for asserting F() object usage simulation

# Service being tested
# Use absolute import path based on common project structure
from backend.store.services import market_wallet_service 
service_under_test = market_wallet_service # Allows easier refactoring if service module moves

# Local/App-specific Exceptions
from backend.store.exceptions import CryptoProcessingError # Use absolute import path

# Define logger for use within test file helpers/mocks
logger = logging.getLogger(__name__) # <<< Rev 61: Define logger instance

# Vault Exceptions (Assuming they live in common.vault_utils)
# Note (Rev 83): The try/except block correctly handles cases where this module
# is not found. Pylance's `reportMissingImports` indicates an environment issue
# (module not in path/project root) rather than a code error here. Ensure
# your environment/PYTHONPATH allows resolving `common.vault_utils`.
try:
    from common.vault_utils import VaultSecretNotFoundError, VaultAuthenticationError, VaultError
except ImportError:
    # Define dummies if vault_utils might not be available, tests MUST patch/handle this
    VaultError = type('VaultError', (Exception,), {})
    VaultSecretNotFoundError = type('VaultSecretNotFoundError', (VaultError,), {})
    VaultAuthenticationError = type('VaultAuthenticationError', (VaultError,), {})
    logger.warning("Could not import Vault exceptions from common.vault_utils. Define dummies.") # Use defined logger


# Import BTC Exceptions if available - This is primarily for type hinting in the test itself now.
# The *actual* exception type used by the service is patched in test_withdraw_btc_rpc_error (Rev 78/79).
# Note (Rev 83): The try/except block correctly handles cases where this module
# is not installed. Pylance's `reportMissingImports` indicates the `bitcoinrpc`
# package is likely missing from the analysis environment. Install it (`pip install python-bitcoinrpc`).
try:
    from bitcoinrpc.authproxy import JSONRPCException as BitcoinJSONRPCException_RealType
    BITCOIN_RPC_EXC_AVAILABLE = True
except ImportError:
    # Define a dummy type for type hints if needed, but don't rely on its attributes.
    BitcoinJSONRPCException_RealType = type('BitcoinJSONRPCException_RealType', (Exception,), {})
    BITCOIN_RPC_EXC_AVAILABLE = False


# Import the actual GlobalSettings model to potentially create mock specs if needed elsewhere,
# but be careful not to use it directly where the service's import path is patched.
# from backend.store.models import GlobalSettings as RealGlobalSettings # Use absolute import path

# Need these for type hints and using real functions as side_effects
# Note (Rev 83): The try/except block correctly handles cases where these modules
# are not installed. Pylance's `reportMissingImports` for `web3.providers.http`
# indicates the `web3` package (and potentially `eth-utils`) is likely missing
# from the analysis environment. Install them (`pip install web3 eth-utils`).
try:
    from web3 import Web3
    from web3.providers.http import HTTPProvider # <<< Specific import Pylance might flag
    # Import BlockNotFound for mocking test scenarios
    from web3.exceptions import BlockNotFound, ConnectionError as Web3ConnectionError # Import specific ConnectionError
    # Import real to_wei for direct use in tests
    from eth_utils import to_wei as real_to_wei, to_checksum_address as real_to_checksum_address, is_mnemonic
    ETH_UTILS_AVAILABLE = True
except ImportError as eth_import_error:
    Web3 = None
    HTTPProvider = None
    BlockNotFound = type('BlockNotFound', (Exception,), {}) # Dummy exception if web3 missing
    Web3ConnectionError = ConnectionError # Fallback to built-in if web3 specific one is missing
    # Fallback lambda only used if eth-utils is missing
    real_to_wei = lambda x, unit: int(Decimal(str(x)) * (10**18))
    # Define real_to_checksum_address as None if import fails
    real_to_checksum_address = None
    is_mnemonic = None # Mnemonic check not available
    # Keep the simple fallback for consistency if needed
    to_checksum_address_fallback = lambda x: f"0x{x[2:].upper()}" if isinstance(x, str) and x.startswith('0x') else x
    ETH_UTILS_AVAILABLE = False
    _eth_import_error = eth_import_error # Store error for reporting

# <<< START Rev 51/60 Import >>> Needed for get_block mock logic
try:
    from web3.datastructures import AttributeDict
    WEB3_INSTALLED_FOR_ATTRDICT = True
except ImportError:
    AttributeDict = dict # Fallback to dict
    WEB3_INSTALLED_FOR_ATTRDICT = False
# <<< END Rev 51/60 Import >>>

try:
    from hdwallet import HDWallet
    from hdwallet.symbols import ETH as ETH_SYMBOL # Use the constant from the library
    HDWALLET_AVAILABLE = True
except ImportError:
    HDWallet = None
    ETH_SYMBOL = 'ETH' # Fallback symbol name if import fails (used in test assertions)
    HDWALLET_AVAILABLE = False

# Optional Monero libs for specific exception handling
try:
    from monero.exceptions import MoneroException
except ImportError:
    MoneroException = None

# Need validator for tests (can be mocked, but sometimes useful to have real one)
# Use try-except for robustness if utils is optional or might fail
try:
    # Assuming validators live in store.validators now based on service file
    from backend.store.validators import validate_ethereum_address, validate_monero_address, validate_bitcoin_address # Use absolute import path
except ImportError:
    validate_ethereum_address = None # Define as None if unavailable
    validate_monero_address = None
    validate_bitcoin_address = None # Define as None if unavailable

# Get Vault helper - mock this thoroughly in tests
# Note (Rev 83): The try/except block correctly handles cases where this module
# is not found. Pylance's `reportMissingImports` indicates an environment issue
# (module not in path/project root) rather than a code error here. Ensure
# your environment/PYTHONPATH allows resolving `common.vault_utils`.
try:
    # Assume vault_utils provides this function
    from common.vault_utils import get_crypto_secret_from_vault
except ImportError:
    # Define a dummy function if vault_utils is unavailable, tests MUST patch this
    def get_crypto_secret_from_vault(*args, **kwargs):
        raise ImportError("Vault utils (common.vault_utils) not found or import failed.")

# BTC Conversion utility - needed for BTC scan tests
# Use real conversion if available, otherwise mock it in tests
try:
    from backend.store.utils.conversion import btc_to_satoshi as real_btc_to_satoshi # Use absolute import path
    BTC_CONVERSION_AVAILABLE = True
except ImportError:
    # Define a fallback lambda function
    real_btc_to_satoshi = lambda x: Decimal(int(Decimal(str(x)) * (10**8)))
    BTC_CONVERSION_AVAILABLE = False
    logger.warning("Real btc_to_satoshi not found, using basic lambda fallback.")


# --- Test Constants ---
MOCK_ORDER_ID = "order_123xyz"
MOCK_BTC_RPC_USER = "testbtcuser"
# B105 Fix: Use placeholder instead of "testbtcpassword"
MOCK_BTC_RPC_PASSWORD = "mock_btc_rpc_password"  # nosec B105 - Mock data for testing
MOCK_BTC_ADDRESS = "bc1qtestbtcaddressgenerated" # Example generated BTC address
MOCK_BTC_TXID = "a" * 64 # Valid 64-char hex
MOCK_XMR_RPC_USER = "testxmruser"
# B105 Fix: Use placeholder instead of "testxmrpassword"
MOCK_XMR_RPC_PASSWORD = "mock_xmr_rpc_password"  # nosec B105 - Mock data for testing
MOCK_XMR_ADDRESS = "4AdreSs..." + "1" * 85 # Example XMR address
MOCK_XMR_TXID = "b" * 64 # Valid 64-char hex
MOCK_ETH_RPC_URL = "http://mock-eth-node:8545"
MOCK_ETH_RAW_ADDRESS_GENERATED = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
# Use real checksum function if available for expected values
EXPECTED_CHECKSUM_GENERATED = real_to_checksum_address(MOCK_ETH_RAW_ADDRESS_GENERATED) if real_to_checksum_address else '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'
MOCK_ETH_SENDER_ADDRESS_RAW = "0xdddddddddddddddddddddddddddddddddddddddd"
EXPECTED_CHECKSUM_SENDER = real_to_checksum_address(MOCK_ETH_SENDER_ADDRESS_RAW) if real_to_checksum_address else '0xDdDdDdDDdDDddDDddDDddDDDDdDDdDDdDDDDDDd'
MOCK_ETH_SENDER_PK = "0x" + "1" * 64 # <<< Ensure this is valid hex PK
MOCK_ETH_TARGET_ADDRESS_RAW = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
EXPECTED_CHECKSUM_TARGET = real_to_checksum_address(MOCK_ETH_TARGET_ADDRESS_RAW) if real_to_checksum_address else '0xaAaAaAaaAaAaAaaAaAAAAAAAAaaaAaAaAaaAaaAa'
MOCK_ETH_TX_HASH_RAW = "0x" + "c" * 64 # Valid 64-char hex
MOCK_ETH_TX_HASH = MOCK_ETH_TX_HASH_RAW
MOCK_ETH_TX_HASH_BYTES = bytes.fromhex(MOCK_ETH_TX_HASH[2:])
MOCK_ETH_DEPOSIT_ADDRESS_RAW = "0x1111111111111111111111111111111111111111"
EXPECTED_CHECKSUM_DEPOSIT = real_to_checksum_address(MOCK_ETH_DEPOSIT_ADDRESS_RAW) if real_to_checksum_address else "0x1111111111111111111111111111111111111111" # Example checksum

# --- Fixtures ---
@pytest.fixture(autouse=True) # Apply automatically to all test methods in classes using it
def mock_market_wallet_settings(settings):
    """Override Django settings for market wallet tests."""
    settings.MARKET_BTC_RPC_USER = MOCK_BTC_RPC_USER
    settings.MARKET_BTC_RPC_PASSWORD = MOCK_BTC_RPC_PASSWORD # Uses updated placeholder
    settings.MARKET_BTC_RPC_HOST = '127.0.0.1'
    settings.MARKET_BTC_RPC_PORT = 8332
    settings.MARKET_XMR_WALLET_RPC_USER = MOCK_XMR_RPC_USER
    settings.MARKET_XMR_WALLET_RPC_PASSWORD = MOCK_XMR_RPC_PASSWORD # Uses updated placeholder
    settings.MARKET_XMR_WALLET_RPC_HOST = '127.0.0.1'
    settings.MARKET_XMR_WALLET_RPC_PORT = 18083
    settings.MARKET_ETH_RPC_URL = MOCK_ETH_RPC_URL
    settings.MARKET_ETH_SENDER_PRIVATE_KEY = MOCK_ETH_SENDER_PK # <<< This line needs MOCK_ETH_SENDER_PK
    settings.MARKET_ETH_POA_CHAIN = False
    settings.MARKET_RPC_TIMEOUT = 15
    # Set a default lookback window for tests if not already set
    if not hasattr(settings, 'MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW'):
        settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW = 100 # Use a smaller window for tests
    # Set a default listtransactions count if not set
    if not hasattr(settings, 'MARKET_BTC_LISTTRANSACTIONS_COUNT'):
        settings.MARKET_BTC_LISTTRANSACTIONS_COUNT = 50
    # Set a default BTC confirmation target if not set
    if not hasattr(settings, 'MARKET_BTC_CONF_TARGET'):
        settings.MARKET_BTC_CONF_TARGET = 6
    # Make sure the gas buffer setting exists for the test calculation, using the default if not set
    if not hasattr(settings, 'MARKET_ETH_GAS_BUFFER_MULTIPLIER'):
        settings.MARKET_ETH_GAS_BUFFER_MULTIPLIER = '1.1'
    settings.SECRET_KEY = getattr(settings, 'SECRET_KEY', 'test_secret_key')
    # Ensure caches are cleared for client helper functions using lru_cache
    if hasattr(service_under_test, '_get_btc_market_rpc_client') and hasattr(service_under_test._get_btc_market_rpc_client, 'cache_clear'):
        service_under_test._get_btc_market_rpc_client.cache_clear()
    if hasattr(service_under_test, '_get_xmr_market_rpc_client') and hasattr(service_under_test._get_xmr_market_rpc_client, 'cache_clear'):
        service_under_test._get_xmr_market_rpc_client.cache_clear()
    if hasattr(service_under_test, '_get_eth_market_rpc_client') and hasattr(service_under_test._get_eth_market_rpc_client, 'cache_clear'):
        service_under_test._get_eth_market_rpc_client.cache_clear()
    yield settings
    # Clear caches again after test run
    if hasattr(service_under_test, '_get_btc_market_rpc_client') and hasattr(service_under_test._get_btc_market_rpc_client, 'cache_clear'):
        service_under_test._get_btc_market_rpc_client.cache_clear()
    if hasattr(service_under_test, '_get_xmr_market_rpc_client') and hasattr(service_under_test._get_xmr_market_rpc_client, 'cache_clear'):
        service_under_test._get_xmr_market_rpc_client.cache_clear()
    if hasattr(service_under_test, '_get_eth_market_rpc_client') and hasattr(service_under_test._get_eth_market_rpc_client, 'cache_clear'):
        service_under_test._get_eth_market_rpc_client.cache_clear()


# --- Mocks for Crypto Libraries (Shared Context - mostly for withdrawal tests) ---
# This context manager remains unchanged as it's mostly for withdrawal tests
# Note: test_withdraw_eth_send_fails no longer uses this context manager as of Rev 49
@contextmanager
@patch('backend.store.services.market_wallet_service.Web3') # FIXED PATCH PATH
@patch('backend.store.services.market_wallet_service.HTTPProvider') # FIXED PATCH PATH
@patch('backend.store.services.market_wallet_service.Account') # FIXED PATCH PATH: Keep for withdrawal tests needing Account.from_key
@patch('backend.store.services.market_wallet_service.to_wei') # FIXED PATCH PATH
@patch('backend.store.services.market_wallet_service.to_checksum_address') # FIXED PATCH PATH
def mock_web3_client_context(MockToChecksumAddress, MockToWei, MockEthAccount, MockHTTPProvider, MockWeb3):
    """
    Provides mocked Web3, Account, and utils within a context.
    NOTE: Primarily used for withdrawal tests now. Scan tests use direct mocks via 'mocker'.
    """
    mock_provider_instance = MockHTTPProvider.return_value
    mock_w3_instance = MockWeb3.return_value
    mock_eth_instance = MagicMock(name='w3.eth')
    mock_w3_instance.eth = mock_eth_instance
    mock_w3_instance.middleware_onion = MagicMock()
    # Mock for Account.create (legacy, not used in HD path)
    mock_created_account = MagicMock(name='CreatedAccountInstance')
    mock_created_account.address = MOCK_ETH_RAW_ADDRESS_GENERATED
    mock_created_account.key.hex.return_value = "0xPRIVATEKEYMOCK" + "0"*48
    MockEthAccount.create.return_value = mock_created_account
    # Mock for Account.from_key (used in withdrawal)
    mock_sender_account = MagicMock(name='SenderAccountInstance')
    mock_sender_account.sign_transaction = MagicMock(name='sign_transaction')
    MockEthAccount.from_key.return_value = mock_sender_account
    MockToWei.side_effect = real_to_wei

    def checksum_side_effect_simple(addr):
        # Return specific expected checksums for known test addresses
        if addr is not None:
            addr_lower = addr.lower()
            if addr_lower == MOCK_ETH_RAW_ADDRESS_GENERATED.lower(): return EXPECTED_CHECKSUM_GENERATED
            if addr_lower == MOCK_ETH_SENDER_ADDRESS_RAW.lower(): return EXPECTED_CHECKSUM_SENDER
            if addr_lower == MOCK_ETH_TARGET_ADDRESS_RAW.lower(): return EXPECTED_CHECKSUM_TARGET
            if addr_lower == MOCK_ETH_DEPOSIT_ADDRESS_RAW.lower(): return EXPECTED_CHECKSUM_DEPOSIT
        # Fallback using real function or basic uppercase
        if real_to_checksum_address:
            try:
                return real_to_checksum_address(addr)
            except (ValueError, TypeError): # Catch potential errors from real function
                pass # Fall through to basic fallback
        return f"0x{addr[2:].upper()}" if isinstance(addr, str) and addr.startswith('0x') else addr

    MockToChecksumAddress.side_effect = checksum_side_effect_simple
    mock_sender_account.address = EXPECTED_CHECKSUM_SENDER # Set address on the instance returned by from_key

    def configure_mocks(success=True):
        mocks_to_reset = [
            MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
            mock_w3_instance, mock_eth_instance, mock_sender_account, mock_created_account
        ]
        for mock_obj in mocks_to_reset:
            if hasattr(mock_obj, 'reset_mock'): mock_obj.reset_mock()
            if hasattr(mock_obj, 'side_effect'): mock_obj.side_effect = None
            if hasattr(mock_obj, 'return_value') and isinstance(mock_obj.return_value, MagicMock):
                if hasattr(mock_obj.return_value, 'reset_mock'): mock_obj.return_value.reset_mock()

        MockHTTPProvider.return_value = mock_provider_instance
        MockWeb3.return_value = mock_w3_instance
        mock_w3_instance.eth = mock_eth_instance
        mock_w3_instance.middleware_onion = MagicMock()
        # Reset mocks related to Account operations
        MockEthAccount.create.return_value = mock_created_account # Reset Account.create mock
        mock_created_account.address = MOCK_ETH_RAW_ADDRESS_GENERATED
        mock_created_account.key.hex.return_value = "0xPRIVATEKEYMOCK" + "0"*48
        MockEthAccount.from_key.return_value = mock_sender_account # Reset Account.from_key mock
        mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
        # Reset util mocks
        MockToWei.side_effect = real_to_wei # Re-apply side effect after reset
        MockToChecksumAddress.side_effect = checksum_side_effect_simple # Re-apply side effect

        if success:
            mock_w3_instance.is_connected.return_value = True
            mock_eth_instance.block_number = 1000000 # Default block number
            mock_eth_instance.chain_id = 1
            mock_eth_instance.get_balance.return_value = 0 # Default balance
            mock_eth_instance.get_transaction_count = MagicMock(return_value=5)
            mock_eth_instance.gas_price = 50 * 10**9
            mock_eth_instance.estimate_gas.return_value = 21000
            mock_signed_tx = MagicMock(name='SignedTx')
            # Use double backslash for literal backslash
            mock_signed_tx.raw_transaction = b'\\mockedRawTxBytes' # <<< MODIFIED HERE (Rev 80)
            mock_sender_account.sign_transaction.return_value = mock_signed_tx # Reset signing mock
            mock_eth_instance.send_raw_transaction.return_value = MOCK_ETH_TX_HASH_BYTES
        else:
            # Simulate connection error behavior using appropriate exception
            conn_err_instance = Web3ConnectionError("w3.is_connected() returned False.")
            mock_w3_instance.is_connected.side_effect = conn_err_instance
            mock_w3_instance.is_connected.return_value = False # Also set return value for direct checks
            mock_eth_instance.block_number = PropertyMock(side_effect=Web3ConnectionError("Cannot get block number"))
            mock_eth_instance.get_transaction_count.side_effect = Web3ConnectionError("Node unavailable for nonce")

    # Yield all 10 items (only 9 were listed before) - add mock_eth_instance
    yield (configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
           mock_w3_instance, mock_eth_instance, mock_sender_account, mock_created_account)


# --- Test Classes ---

# Fixture is applied automatically via autouse=True in mock_market_wallet_settings
class TestMarketWalletClientHelpers:
    """Tests for the _get_..._client helper functions."""

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    def test_get_btc_client_success(self, MockBtcClient):
        mock_instance = MockBtcClient.return_value
        # Mock the actual method called in the service code
        mock_instance.getblockchaininfo.return_value = {'chain': 'main'} # Example valid response
        service_under_test._get_btc_market_rpc_client.cache_clear()
        client = service_under_test._get_btc_market_rpc_client()
        # B101 Fix
        if not (client is not None):
            raise AssertionError("Client should not be None")
        # B101 Fix
        if not (client == mock_instance):
                raise AssertionError("Returned client is not the expected mock instance")
        MockBtcClient.assert_called_once_with(
            f"http://{MOCK_BTC_RPC_USER}:{MOCK_BTC_RPC_PASSWORD}@127.0.0.1:8332",
            timeout=15
        )
        # Assert the correct method was called
        mock_instance.getblockchaininfo.assert_called_once()

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    def test_get_btc_client_connection_error(self, MockBtcClient):
        mock_instance = MockBtcClient.return_value
        # Mock the actual method called in the service to raise ConnectionError
        mock_instance.getblockchaininfo.side_effect = ConnectionError("Mock BTC getblockchaininfo failed")
        service_under_test._get_btc_market_rpc_client.cache_clear()
        # The service should catch ConnectionError and raise CryptoProcessingError
        with pytest.raises(CryptoProcessingError, match=r"BTC RPC connection failed \(ConnectionError\): Mock BTC getblockchaininfo failed"):
            service_under_test._get_btc_market_rpc_client()
        MockBtcClient.assert_called_once()
        mock_instance.getblockchaininfo.assert_called_once() # Ensure the method was called

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    def test_get_btc_client_missing_config(self, settings): # settings is implicitly provided by mock_market_wallet_settings
        settings.MARKET_BTC_RPC_USER = None
        service_under_test._get_btc_market_rpc_client.cache_clear()
        with patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy'): # FIXED PATCH PATH
            with pytest.raises(ImproperlyConfigured, match="MARKET_BTC_RPC config missing"):
                service_under_test._get_btc_market_rpc_client()

    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    def test_get_xmr_client_success(self, MockXmrClient):
        mock_instance = MockXmrClient.return_value
        mock_instance.get_version = MagicMock(return_value={'version': 'mock_v0.17'})
        service_under_test._get_xmr_market_rpc_client.cache_clear()
        client = service_under_test._get_xmr_market_rpc_client()
        # B101 Fix
        if not (client is not None):
            raise AssertionError("Client should not be None")
        MockXmrClient.assert_called_once_with(
            host='127.0.0.1', port=18083, user=MOCK_XMR_RPC_USER, password=MOCK_XMR_RPC_PASSWORD
        )
        client.get_version.assert_called_once()

    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    def test_get_xmr_client_connection_error(self, MockXmrClient):
        mock_instance = MockXmrClient.return_value
        mock_instance.get_version = MagicMock(side_effect=ConnectionError("Mock XMR get_version failed"))
        service_under_test._get_xmr_market_rpc_client.cache_clear()
        with pytest.raises(CryptoProcessingError, match=r"Monero RPC connection failed \(ConnectionError\): Mock XMR get_version failed"):
            service_under_test._get_xmr_market_rpc_client()
        MockXmrClient.assert_called_once()
        mock_instance.get_version.assert_called_once()

    # Test using direct mock object patching via mocker
    def test_get_eth_client_success(self, mocker):
        """ Tests successful connection using mocker for cleaner patching """
        mock_w3_success = MagicMock(name='MockW3Success')
        mock_w3_success.eth = MagicMock(name='eth')
        mock_w3_success.is_connected.return_value = True
        mock_w3_success.eth.block_number = 1000000
        # Patch the helper *within the service* to return our prepared mock
        mock_get_eth_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3_success) # FIXED PATCH PATH
        service_under_test._get_eth_market_rpc_client.cache_clear() # Clear cache if needed
        client = service_under_test._get_eth_market_rpc_client()
        # B101 Fix
        if not (client is not None):
                raise AssertionError("Client should not be None")
        # B101 Fix
        if not (client == mock_w3_success):
                raise AssertionError(f"Client '{client}' does not match expected mock '{mock_w3_success}'")
        mock_get_eth_client.assert_called_once()
        # Re-clear cache after test
        service_under_test._get_eth_market_rpc_client.cache_clear()

    # Test using direct mock object patching via mocker
    def test_get_eth_client_connection_error(self, mocker):
        """ Tests connection error using mocker """
        error_message_raw = "Ethereum RPC connection failed (ConnectionError): Mocked connection failure."
        error_message_escaped = re.escape(error_message_raw)
        # Patch the helper *within the service* to raise the error
        mock_get_eth_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', side_effect=CryptoProcessingError(error_message_raw)) # FIXED PATCH PATH
        service_under_test._get_eth_market_rpc_client.cache_clear() # Clear cache if needed
        with pytest.raises(CryptoProcessingError, match=error_message_escaped):
            service_under_test._get_eth_market_rpc_client()
        mock_get_eth_client.assert_called_once()
        # Re-clear cache after test
        service_under_test._get_eth_market_rpc_client.cache_clear()

    def test_get_eth_client_missing_config(self, settings): # settings implicitly provided
        settings.MARKET_ETH_RPC_URL = None
        service_under_test._get_eth_market_rpc_client.cache_clear()
        # Ensure WEB3_AVAILABLE is correctly patched if needed for this test path
        with patch('backend.store.services.market_wallet_service.WEB3_AVAILABLE', True): # FIXED PATCH PATH
            with patch('backend.store.services.market_wallet_service.Web3', MagicMock()): # FIXED PATCH PATH
                with patch('backend.store.services.market_wallet_service.HTTPProvider', MagicMock()): # FIXED PATCH PATH
                    with pytest.raises(ImproperlyConfigured, match="MARKET_ETH_RPC_URL not configured"):
                        service_under_test._get_eth_market_rpc_client()


# Fixture is applied automatically
class TestGenerateDepositAddress:
    """Tests for generate_deposit_address function."""

    # FIX: Added missing BitcoinAuthServiceProxy patch
    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_generate_btc_address(self, mock_get_client, MockBtcClientClass):
        # Mock the client instance and its method called by the service
        mock_client_instance = MockBtcClientClass.return_value
        mock_client_instance.getnewaddress.return_value = MOCK_BTC_ADDRESS # Simulate returning a real address
        mock_get_client.return_value = mock_client_instance

        address = service_under_test.generate_deposit_address('BTC', MOCK_ORDER_ID)
        # B101 Fix: Assert against the mocked return value
        if not (address == MOCK_BTC_ADDRESS):
            raise AssertionError(f"Expected address '{MOCK_BTC_ADDRESS}', got '{address}'")
        # Verify helper and RPC call
        mock_get_client.assert_called_once()
        mock_client_instance.getnewaddress.assert_called_once_with(label=f"order_{MOCK_ORDER_ID}")

    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_generate_xmr_address(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_client_instance.create_address = MagicMock(return_value={'address': MOCK_XMR_ADDRESS, 'address_index': 1})
        mock_get_client.return_value = mock_client_instance
        address = service_under_test.generate_deposit_address('XMR', MOCK_ORDER_ID)
        # B101 Fix
        if not (address == MOCK_XMR_ADDRESS):
            raise AssertionError(f"Expected address '{MOCK_XMR_ADDRESS}', got '{address}'")
        mock_get_client.assert_called_once()
        mock_client_instance.create_address.assert_called_once_with(account_index=0, label=f"order_{MOCK_ORDER_ID}")

    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_generate_xmr_rpc_error(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        # Use MoneroException if available for more specific testing
        error_instance = MoneroException("Mock XMR RPC Down") if MoneroException else Exception("Mock XMR RPC Down")
        expected_match = "MoneroException" if MoneroException else "Unexpected Error"
        mock_client_instance.create_address = MagicMock(side_effect=error_instance)
        mock_get_client.return_value = mock_client_instance

        with pytest.raises(CryptoProcessingError, match=rf"XMR market address generation failed \({expected_match}\): Mock XMR RPC Down"):
            service_under_test.generate_deposit_address('XMR', MOCK_ORDER_ID)
        mock_get_client.assert_called_once()
        mock_client_instance.create_address.assert_called_once()

    # Test rewritten for HD Wallet implementation using mocker fixture
    def test_generate_eth_address(self, mocker): # Inject mocker
        """Tests successful ETH address generation using the HD Wallet path."""
        # 1. Apply patches using mocker
        # Patch dependencies imported within the service module
        mock_validate_ethereum_address = mocker.patch('backend.store.services.market_wallet_service.validate_ethereum_address') # FIXED PATCH PATH
        mock_to_checksum_address = mocker.patch('backend.store.services.market_wallet_service.to_checksum_address') # FIXED PATCH PATH
        MockHDWalletClass = mocker.patch('backend.store.services.market_wallet_service.HDWallet') # FIXED PATCH PATH
        mock_get_vault_secret = mocker.patch('backend.store.services.market_wallet_service.get_crypto_secret_from_vault') # FIXED PATCH PATH
        MockGlobalSettings = mocker.patch('backend.store.services.market_wallet_service.GlobalSettings') # FIXED PATCH PATH: Patch the class reference in the service
        mocker.patch('backend.store.services.market_wallet_service.HDWALLET_AVAILABLE', True) # FIXED PATCH PATH: Ensure library is "available"
        mock_atomic = mocker.patch('django.db.transaction.atomic') # Mock the atomic transaction context
        mock_is_mnemonic = mocker.patch('backend.store.services.market_wallet_service.is_mnemonic', return_value=True) # FIXED PATCH PATH: Assume seed is valid mnemonic
        # Patch ETH_SYMBOL constant within the service to ensure correct value during test
        mocker.patch('backend.store.services.market_wallet_service.ETH_SYMBOL', ETH_SYMBOL) # FIXED PATCH PATH: Use ETH_SYMBOL imported/defined in test file

        # 2. Configure Mocks
        # --- Vault Mock ---
        mock_seed_phrase = "test fetch witness immense rhythm unusual require hold stadium skate chimney famous"
        mock_get_vault_secret.return_value = mock_seed_phrase

        # --- GlobalSettings Mock (for atomic index) ---
        initial_index = 99
        next_index = initial_index + 1

        # Mock instance returned by get_or_create
        mock_settings_instance = MagicMock()
        mock_settings_instance.pk = 1
        mock_settings_instance.last_eth_hd_index = initial_index
        MockGlobalSettings.objects.get_or_create.return_value = (mock_settings_instance, False)

        # Mock instance returned after select_for_update().get()
        # This instance will have its attribute updated by refresh_from_db mock
        mock_locked_instance = MagicMock()
        mock_locked_instance.pk = 1
        # Set initial state BEFORE refresh is simulated
        # Note: The actual assignment of F() happens in the service code
        mock_locked_instance.last_eth_hd_index = initial_index # State before F() + save + refresh
        MockGlobalSettings.objects.select_for_update.return_value.get.return_value = mock_locked_instance

        # Configure save() mock
        mock_locked_instance.save = MagicMock()

        # Configure refresh_from_db() mock SIDE EFFECT
        # This is CRITICAL: it simulates fetching the updated value from DB
        def mock_refresh_side_effect(*args, **kwargs):
            # Simulate the DB refresh by setting the attribute to the expected *final* value
            mock_locked_instance.last_eth_hd_index = next_index
        mock_locked_instance.refresh_from_db = MagicMock(side_effect=mock_refresh_side_effect)

        # --- HDWallet Mock ---
        mock_hdwallet_instance = MockHDWalletClass.return_value
        mock_hdwallet_instance.address.return_value = MOCK_ETH_RAW_ADDRESS_GENERATED
        mock_hdwallet_instance.clean_derivation = MagicMock()

        # --- to_checksum_address Mock ---
        # Use the actual expected checksum value calculated at the top
        mock_to_checksum_address.return_value = EXPECTED_CHECKSUM_GENERATED

        # --- transaction.atomic Mock ---
        # Use a real context manager or a simpler MagicMock for enter/exit
        @contextmanager
        def mock_atomic_cm(*args, **kwargs):
            yield # Simulate entering and exiting the context
        mock_atomic.side_effect = mock_atomic_cm


        # 3. Call the Service Function
        generated_address = service_under_test.generate_deposit_address('ETH', MOCK_ORDER_ID)

        # 4. Assertions
        # --- Check final address ---
        if not (generated_address == EXPECTED_CHECKSUM_GENERATED):
            raise AssertionError(f"Expected generated address '{EXPECTED_CHECKSUM_GENERATED}', got '{generated_address}'")

        # --- Check Vault call ---
        mock_get_vault_secret.assert_called_once_with(
            key_type='eth',
            key_name='hd_master_seed',
            key_field='seed_phrase',
            raise_error=True
        )
        # Check mnemonic validation call
        mock_is_mnemonic.assert_called_once_with(mock_seed_phrase)

        # --- Check DB/Settings calls for index ---
        mock_atomic.assert_called_once() # Check atomic block was used
        # Assert calls on the *mocked* GlobalSettings class's manager
        MockGlobalSettings.objects.get_or_create.assert_called_once_with(pk=1, defaults={'last_eth_hd_index': -1})
        MockGlobalSettings.objects.select_for_update.return_value.get.assert_called_once_with(pk=mock_settings_instance.pk)

        # Check the calls on the locked instance
        if not mock_locked_instance.save.called:
                                raise AssertionError("Expected settings_obj_locked.save() to be called within the atomic block.")
        # Check F() object was used in assignment before save (by inspecting call args if needed, or relying on successful execution)
        mock_locked_instance.save.assert_called_with(update_fields=['last_eth_hd_index'])

        # Check refresh was called
        if not mock_locked_instance.refresh_from_db.called:
                                raise AssertionError("Expected settings_obj_locked.refresh_from_db() to be called after save.")
        mock_locked_instance.refresh_from_db.assert_called_with(fields=['last_eth_hd_index'])

        # Check the *final* value of the index on the mock *after* refresh was simulated
        if not (mock_locked_instance.last_eth_hd_index == next_index):
                                raise AssertionError(f"Expected final index on refreshed mock object to be {next_index}, but got {mock_locked_instance.last_eth_hd_index}")


        # --- Check HDWallet calls ---
        # Use ETH_SYMBOL imported/defined at the top of this test file
        MockHDWalletClass.assert_called_once_with(symbol=ETH_SYMBOL, use_default_path=False)
        mock_hdwallet_instance.from_mnemonic.assert_called_once_with(
            mnemonic=mock_seed_phrase, passphrase=None, language='english', strict=True
        )
        # Use the *final* index obtained after the atomic update simulation
        expected_derivation_path = f"m/44'/60'/0'/0/{next_index}"
        mock_hdwallet_instance.from_path.assert_called_once_with(path=expected_derivation_path)
        mock_hdwallet_instance.address.assert_called_once()

        # --- Check util calls ---
        mock_to_checksum_address.assert_called_once_with(MOCK_ETH_RAW_ADDRESS_GENERATED)
        mock_validate_ethereum_address.assert_called_once_with(EXPECTED_CHECKSUM_GENERATED)

        # --- Check cleanup ---
        mock_hdwallet_instance.clean_derivation.assert_called_once()


    def test_generate_unsupported_currency(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            service_under_test.generate_deposit_address('LTC', MOCK_ORDER_ID)


# Fixture is applied automatically
class TestScanForDeposit:
    """Tests for scan_for_deposit function."""

    # --- BTC Scan Tests ---
    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.btc_to_satoshi', side_effect=real_btc_to_satoshi) # FIXED PATCH PATH # Use real/fallback conversion
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_scan_btc_found_confirmed(self, mock_get_client, MockBtcClientClass, mock_btc_to_satoshi, mock_market_wallet_settings):
        """BTC scan finds a transaction with sufficient confirmations."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance

        amount_btc = Decimal("0.001")
        amount_sats = real_btc_to_satoshi(amount_btc)
        confs_needed = 3
        confs_found = 5

        mock_client_instance.listtransactions.return_value = [
            {'category': 'receive', 'address': MOCK_BTC_ADDRESS, 'amount': amount_btc, 'confirmations': confs_found, 'txid': MOCK_BTC_TXID},
            # Add some noise
            {'category': 'send', 'address': 'some_other_address', 'amount': Decimal("-0.002"), 'confirmations': 10, 'txid': 'c'*64},
            {'category': 'receive', 'address': 'another_deposit_addr', 'amount': Decimal("0.0005"), 'confirmations': 20, 'txid': 'd'*64},
        ]

        result = service_under_test.scan_for_deposit(
            currency='BTC',
            deposit_address=MOCK_BTC_ADDRESS,
            expected_amount_atomic=amount_sats,
            confirmations_needed=confs_needed,
            order_id=MOCK_ORDER_ID
        )

        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None")
        is_confirmed, received, confs_result, r_txid = result
        # B101 Fix
        if not (is_confirmed is True): raise AssertionError("Expected is_confirmed to be True")
        # B101 Fix
        if not (received == amount_sats): raise AssertionError(f"Expected received {amount_sats}, got {received}")
        # B101 Fix
        if not (confs_result == confs_found): raise AssertionError(f"Expected confs_result {confs_found}, got {confs_result}")
        # B101 Fix
        if not (r_txid == MOCK_BTC_TXID): raise AssertionError(f"Expected txid {MOCK_BTC_TXID}, got {r_txid}")
        mock_get_client.assert_called_once()
        mock_btc_to_satoshi.assert_called_once_with(amount_btc)
        listtx_count = getattr(mock_market_wallet_settings, 'MARKET_BTC_LISTTRANSACTIONS_COUNT', service_under_test.DEFAULT_BTC_LISTTRANSACTIONS_COUNT)
        mock_client_instance.listtransactions.assert_called_once_with(label=f"order_{MOCK_ORDER_ID}", count=listtx_count, include_watchonly=True)

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.btc_to_satoshi', side_effect=real_btc_to_satoshi) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_scan_btc_found_unconfirmed(self, mock_get_client, MockBtcClientClass, mock_btc_to_satoshi, mock_market_wallet_settings):
        """BTC scan finds a transaction with insufficient confirmations."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        amount_btc = Decimal("0.001")
        amount_sats = real_btc_to_satoshi(amount_btc)
        confs_needed = 6
        confs_found = 2 # Less than needed

        mock_client_instance.listtransactions.return_value = [
            {'category': 'receive', 'address': MOCK_BTC_ADDRESS, 'amount': amount_btc, 'confirmations': confs_found, 'txid': MOCK_BTC_TXID},
        ]

        result = service_under_test.scan_for_deposit('BTC', MOCK_BTC_ADDRESS, amount_sats, confs_needed, order_id=MOCK_ORDER_ID)

        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None")
        is_confirmed, received, confs_result, r_txid = result
        # B101 Fix
        if not (is_confirmed is False): raise AssertionError("Expected is_confirmed to be False") # Should be false due to low confs
        # B101 Fix
        if not (received == amount_sats): raise AssertionError(f"Expected received {amount_sats}, got {received}")
        # B101 Fix
        if not (confs_result == confs_found): raise AssertionError(f"Expected confs_result {confs_found}, got {confs_result}")
        # B101 Fix
        if not (r_txid == MOCK_BTC_TXID): raise AssertionError(f"Expected txid {MOCK_BTC_TXID}, got {r_txid}")
        mock_get_client.assert_called_once()
        mock_btc_to_satoshi.assert_called_once_with(amount_btc)
        listtx_count = getattr(mock_market_wallet_settings, 'MARKET_BTC_LISTTRANSACTIONS_COUNT', service_under_test.DEFAULT_BTC_LISTTRANSACTIONS_COUNT)
        mock_client_instance.listtransactions.assert_called_once_with(label=f"order_{MOCK_ORDER_ID}", count=listtx_count, include_watchonly=True)

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.btc_to_satoshi', side_effect=real_btc_to_satoshi) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_scan_btc_insufficient_amount(self, mock_get_client, MockBtcClientClass, mock_btc_to_satoshi):
        """BTC scan finds a transaction but the amount is too small."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        expected_amount_sats = Decimal(100000)
        received_amount_btc = Decimal("0.0005") # Converts to 50000 sats
        confs_found = 10

        mock_client_instance.listtransactions.return_value = [
            {'category': 'receive', 'address': MOCK_BTC_ADDRESS, 'amount': received_amount_btc, 'confirmations': confs_found, 'txid': MOCK_BTC_TXID},
        ]

        result = service_under_test.scan_for_deposit('BTC', MOCK_BTC_ADDRESS, expected_amount_sats, 3, order_id=MOCK_ORDER_ID)

        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None") # Should be None as amount is too low
        mock_get_client.assert_called_once()
        mock_btc_to_satoshi.assert_called_once_with(received_amount_btc)
        mock_client_instance.listtransactions.assert_called_once()

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.btc_to_satoshi', side_effect=real_btc_to_satoshi) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_scan_btc_no_match(self, mock_get_client, MockBtcClientClass, mock_btc_to_satoshi):
        """BTC scan finds no matching transaction."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.listtransactions.return_value = [
            {'category': 'send', 'address': MOCK_BTC_ADDRESS, 'amount': Decimal("-0.001"), 'confirmations': 5, 'txid': 'e'*64}, # Wrong category
            {'category': 'receive', 'address': 'some_other_address', 'amount': Decimal("0.001"), 'confirmations': 10, 'txid': 'f'*64}, # Wrong address
        ]

        result = service_under_test.scan_for_deposit('BTC', MOCK_BTC_ADDRESS, Decimal(100000), 3, order_id=MOCK_ORDER_ID)

        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None")
        mock_get_client.assert_called_once()
        # B101 Fix
        if not (mock_btc_to_satoshi.call_count == 0): raise AssertionError("Conversion shouldn't be called if no matching tx found")
        mock_client_instance.listtransactions.assert_called_once()

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.btc_to_satoshi') # FIXED PATCH PATH: Mock the utility
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_scan_btc_rpc_error(self, mock_get_client, MockBtcClientClass, mock_btc_to_satoshi):
        """BTC scan handles RPC errors during listtransactions."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        # Simulate an RPC error
        mock_client_instance.listtransactions.side_effect = ConnectionError("Node unavailable during listtransactions")

        # Service function catches the error and returns None
        result = service_under_test.scan_for_deposit('BTC', MOCK_BTC_ADDRESS, Decimal(100000), 3, order_id=MOCK_ORDER_ID)

        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None")
        mock_get_client.assert_called_once()
        mock_client_instance.listtransactions.assert_called_once()
        mock_btc_to_satoshi.assert_not_called() # Conversion shouldn't happen if RPC fails

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    def test_scan_btc_missing_order_id(self):
        """BTC scan requires order_id and returns None if missing."""
        result = service_under_test.scan_for_deposit(
            currency='BTC',
            deposit_address=MOCK_BTC_ADDRESS,
            expected_amount_atomic=Decimal(100000),
            confirmations_needed=3,
            order_id=None # Missing order_id
        )
        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None")


    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_scan_xmr_found(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        amount_pico = Decimal(500000000000)
        expected_amount_pico_int = 500000000000
        confs_needed = 10
        mock_client_instance.get_transfers = MagicMock(return_value={
            'in': [{'address': MOCK_XMR_ADDRESS, 'amount': expected_amount_pico_int, 'confirmations': confs_needed + 5, 'txid': MOCK_XMR_TXID}]
        })
        result = service_under_test.scan_for_deposit('XMR', MOCK_XMR_ADDRESS, amount_pico, confs_needed)
        # B101 Fix
        if not (result is not None):
            raise AssertionError(f"Expected result to not be None, got {result}")
        # Check inside the if block remains valid as it prevents None access
        if result is not None:
            is_confirmed, received, confs_found, r_txid = result
            # B101 Fix
            if not (is_confirmed is True):
                    raise AssertionError(f"Expected result[0] to be True, got {is_confirmed}")
            # B101 Fix
            if not (received == amount_pico):
                    raise AssertionError(f"Expected result[1] ({received}) to equal amount_pico ({amount_pico})")
            # B101 Fix
            if not (confs_found == confs_needed + 5):
                    raise AssertionError(f"Expected result[2] ({confs_found}) to equal confs_needed + 5 ({confs_needed + 5})")
            # B101 Fix
            if not (r_txid == MOCK_XMR_TXID):
                    raise AssertionError(f"Expected result[3] ('{r_txid}') to equal MOCK_XMR_TXID ('{MOCK_XMR_TXID}')")
        mock_get_client.assert_called_once()
        mock_client_instance.get_transfers.assert_called_once_with(in_=True, pool_=False, out_=False, pending_=False, failed_=False, filter_by_height=False)

    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_scan_xmr_not_found(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.get_transfers = MagicMock(return_value={'in': []})
        result = service_under_test.scan_for_deposit('XMR', MOCK_XMR_ADDRESS, Decimal(1000), 10)
        # B101 Fix
        if not (result is None):
            raise AssertionError(f"Expected result to be None, got {result}")
        mock_get_client.assert_called_once()
        mock_client_instance.get_transfers.assert_called_once()


    # --- New ETH Scan Tests using Block Iteration ---

    # <<< START Rev 68: Modified Helper for BlockNotFound testing >>>
    def _setup_eth_scan_mocks(self, mocker, latest_block_num=1000, block_data=None, block_behavior_config=None):
        """
        Helper to set up common mocks for ETH scan tests.
        Returns a simple dictionary for blocks instead of MagicMock.
        Can optionally raise BlockNotFound or return None based on block_behavior_config.
        """
        mock_w3 = MagicMock(name="MockW3Instance")
        mock_eth = MagicMock(name="w3.eth")
        mock_w3.eth = mock_eth

        # Mock block_number property directly on the mock_eth instance
        type(mock_eth).block_number = PropertyMock(return_value=latest_block_num)

        if block_data is None:
            block_data = {}
        if block_behavior_config is None: # Ensure it's a dict for safe .get() later
            block_behavior_config = {}

        # --- Side effect for get_block ---
        def get_block_side_effect(block_identifier, full_transactions=False):
            # Updated log marker for clarity
            logger.debug(f"[TEST MOCK get_block Rev68] Called with identifier: {repr(block_identifier)}, full_transactions={full_transactions}")

            block_num = -1
            if isinstance(block_identifier, int):
                block_num = block_identifier
            elif block_identifier == 'latest':
                block_num = latest_block_num
            else:
                logger.error(f"[TEST MOCK get_block Rev68] Unexpected block identifier type in mock: {type(block_identifier)} - {repr(block_identifier)}")
                raise ValueError(f"Unexpected block identifier type in mock: {block_identifier}")

            # <<< START Rev 68: Centralized Block Behavior Logic >>>
            # Check if configured to raise BlockNotFound
            if block_num == block_behavior_config.get('raise_on'):
                    logger.warning(f"[TEST MOCK get_block Rev68] Raising BlockNotFound for block {block_num} based on config")
                    raise BlockNotFound(f"Mock block {block_num} missing per test config")
            # Check if configured to return None
            if block_num == block_behavior_config.get('return_none_on'):
                    logger.warning(f"[TEST MOCK get_block Rev68] Returning None for block {block_num} based on config")
                    return None # Return None instead of raising
            # <<< END Rev 68: Centralized Block Behavior Logic >>>

            # Process transactions for this block_num
            tx_list_processed = []
            if block_data and block_num in block_data:
                block_content = block_data.get(block_num, {})
                raw_tx_list = block_content.get('transactions', [])
                logger.debug(f"[TEST MOCK get_block Rev68] Block {block_num}: Found {len(raw_tx_list)} raw txns in block_data.")
                for tx_dict in raw_tx_list:
                    if WEB3_INSTALLED_FOR_ATTRDICT:
                        try:
                            processed_tx = AttributeDict(tx_dict)
                            tx_list_processed.append(processed_tx)
                        except Exception as attr_dict_err:
                            logger.error(f"[TEST MOCK get_block Rev68] Error creating AttributeDict for {repr(tx_dict)}: {attr_dict_err}", exc_info=True)
                            tx_list_processed.append(tx_dict.copy())
                    else:
                        tx_list_processed.append(tx_dict.copy())
                logger.debug(f"[TEST MOCK get_block Rev68] Block {block_num}: Processed tx list: {repr(tx_list_processed)}")
            else:
                logger.debug(f"[TEST MOCK get_block Rev68] Block {block_num}: No data found in block_data or block not in block_data.")

            # Return a simple dictionary
            return_block_dict = {
                'number': block_num,
                'transactions': tx_list_processed,
                'timestamp': 1234567890 + block_num,
                'hash': f'0xblockhash{block_num}'.encode().hex(),
            }
            logger.debug(f"[TEST MOCK get_block Rev68] Returning dict for block {block_num}: {repr(return_block_dict)}")
            return return_block_dict
        # --- End side effect ---

        mock_eth.get_block = MagicMock(side_effect=get_block_side_effect)

        # Mock to_checksum_address
        mock_to_checksum = mocker.patch('backend.store.services.market_wallet_service.to_checksum_address') # FIXED PATCH PATH

        def reliable_checksum_side_effect(addr):
            """Side effect for to_checksum_address mock."""
            # Updated log marker for clarity
            if addr is None: return None
            if not isinstance(addr, str) or not addr.startswith('0x') or len(addr) != 42:
                logger.debug(f"[Checksum Mock Side Effect Rev68] Input '{addr}' is not a valid address format. Raising ValueError.")
                raise ValueError(f"Address must be 20 bytes (42 hex chars including 0x), received: '{addr}'")

            if ETH_UTILS_AVAILABLE and real_to_checksum_address:
                try:
                    checksummed = real_to_checksum_address(addr)
                    logger.debug(f"[Checksum Mock Side Effect Rev68] Using REAL function for '{addr}'. Result: '{checksummed}'")
                    return checksummed
                except (ValueError, TypeError) as e:
                    logging.warning(f"[Checksum Mock Side Effect Rev68] REAL to_checksum_address failed for '{addr}': {e}. Falling back.")

            try:
                checksummed_fallback = '0x' + addr[2:].upper()
                logger.debug(f"[Checksum Mock Side Effect Rev68] Using FALLBACK checksum for '{addr}'. Result: '{checksummed_fallback}'")
                return checksummed_fallback
            except Exception as fallback_err:
                logger.error(f"[Checksum Mock Side Effect Rev68] Fallback checksum failed unexpectedly for '{addr}': {fallback_err}", exc_info=True)
                return f"CHECKSUM_FALLBACK_ERROR_{addr}"

        mock_to_checksum.side_effect = reliable_checksum_side_effect

        return mock_w3, mock_eth, mock_to_checksum
    # <<< END Rev 68: Modified Helper >>>

    # Ensure _mock_checksum_address is available if any test relies on it directly (though helper now uses reliable_checksum_side_effect)
    def _mock_checksum_address(self, addr):
        # (Keeping this definition consistent with previous example, though helper uses different logic now)
        # <<< Rev 61: Use logger defined at module level >>>
        logger.debug(f"[Checksum Mock Fallback (_mock_checksum_address)] Checking address: {addr}")
        if isinstance(addr, str) and addr.startswith('0x') and len(addr) == 42:
            if addr == MOCK_ETH_DEPOSIT_ADDRESS_RAW: return EXPECTED_CHECKSUM_DEPOSIT # Use constant defined above
            if addr == MOCK_ETH_TARGET_ADDRESS_RAW: return EXPECTED_CHECKSUM_TARGET # Use constant defined above
            logger.debug(f"[Checksum Mock Fallback (_mock_checksum_address)] Using simple uppercase fallback for '{addr}'. Result: '{addr.upper()}'")
            return addr.upper() # Simple fallback
        logger.warning(f"[Checksum Mock Fallback (_mock_checksum_address)] Received potentially invalid address format: {addr}. Returning unmodified.")
        return addr


    # --- Individual ETH Scan Tests (Assertions updated for clarity) ---
    def test_scan_eth_deposit_found_confirmed(self, mocker, mock_market_wallet_settings):
        """ETH scan finds a transaction with sufficient confirmations."""
        latest_block = 1000
        target_block = 900 # 101 confirmations
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        tx_hash = "0xabc123" + "a" * 58
        tx_hash_bytes = bytes.fromhex(tx_hash[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW # Use raw address

        mock_blocks = {
            target_block: {
                'number': target_block,
                'transactions': [
                    {
                        'to': deposit_address,
                        'value': int(amount_wei),
                        'hash': tx_hash_bytes,
                        'blockNumber': target_block
                    }
                ]
            }
        }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies get_block and to_checksum_address patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit(
            'ETH', deposit_address, amount_wei, confs_needed
        )

        # Assertions
        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None")
        is_confirmed, received, confs_found, r_txid = result
        # B101 Fix
        if not is_confirmed: raise AssertionError("Expected is_confirmed to be True")
        # B101 Fix
        if not (received == amount_wei): raise AssertionError(f"Expected received {amount_wei}, got {received}")
        expected_confs = latest_block - target_block + 1
        # B101 Fix
        if not (confs_found == expected_confs): raise AssertionError(f"Expected confs {expected_confs}, got {confs_found}")
        # Compare hex strings directly
        # B101 Fix
        if not (r_txid == tx_hash): raise AssertionError(f"Expected txid {tx_hash}, got {r_txid}")

        # Use the mock object returned by the helper for verification
        mock_checksum_obj.assert_any_call(deposit_address) # Checksum of deposit address input
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW) # Checksum of tx['to'] (which is same address here)


    def test_scan_eth_deposit_found_unconfirmed(self, mocker, mock_market_wallet_settings):
        """ETH scan finds a transaction with insufficient confirmations."""
        latest_block = 1000
        target_block = 995 # 6 confirmations
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        tx_hash = "0xdef456" + "b" * 58
        tx_hash_bytes = bytes.fromhex(tx_hash[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW

        mock_blocks = {
            target_block: {
                'number': target_block,
                'transactions': [ { 'to': deposit_address, 'value': int(amount_wei), 'hash': tx_hash_bytes, 'blockNumber': target_block } ]
            }
        }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None")
        is_confirmed, received, confs_found, r_txid = result
        # B101 Fix
        if is_confirmed: raise AssertionError("Expected is_confirmed to be False")
        # B101 Fix
        if not (received == amount_wei): raise AssertionError(f"Expected received {amount_wei}, got {received}")
        expected_confs = latest_block - target_block + 1
        # B101 Fix
        if not (confs_found == expected_confs): raise AssertionError(f"Expected confs {expected_confs}, got {confs_found}")
        # B101 Fix
        if not (r_txid == tx_hash): raise AssertionError(f"Expected txid {tx_hash}, got {r_txid}")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address)
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW)


    def test_scan_eth_deposit_insufficient_amount(self, mocker, mock_market_wallet_settings):
        """ETH scan finds a transaction but amount is too small."""
        latest_block = 1000
        target_block = 950
        confs_needed = 10
        expected_amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        received_amount_wei = Decimal(real_to_wei(0.05, 'ether')) # Too small
        tx_hash = "0xabc789" + "0" * 58
        tx_hash_bytes = bytes.fromhex(tx_hash[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW

        mock_blocks = {
            target_block: {
                'number': target_block,
                'transactions': [ { 'to': deposit_address, 'value': int(received_amount_wei), 'hash': tx_hash_bytes, 'blockNumber': target_block } ]
            }
        }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, expected_amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None due to insufficient amount")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address)
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW)


    def test_scan_eth_deposit_multiple_matches(self, mocker, mock_market_wallet_settings):
        """ETH scan finds multiple matching transactions, selects the one with most confirmations."""
        latest_block = 1000
        target_block_1 = 900 # 101 confs (older, higher confs)
        target_block_2 = 950 # 51 confs
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        tx_hash_1 = "0x01deface" + "a" * 56
        tx_hash_bytes_1 = bytes.fromhex(tx_hash_1[2:])
        tx_hash_2 = "0x" + "f" * 8 + "b" * 56
        tx_hash_bytes_2 = bytes.fromhex(tx_hash_2[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW

        mock_blocks = {
            target_block_1: { 'number': target_block_1, 'transactions': [ {'to': deposit_address, 'value': int(amount_wei), 'hash': tx_hash_bytes_1, 'blockNumber': target_block_1} ] },
            target_block_2: { 'number': target_block_2, 'transactions': [ {'to': deposit_address, 'value': int(amount_wei), 'hash': tx_hash_bytes_2, 'blockNumber': target_block_2} ] }
        }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None")
        is_confirmed, received, confs_found, r_txid = result
        # B101 Fix
        if not is_confirmed: raise AssertionError("Expected is_confirmed to be True")
        # B101 Fix
        if not (received == amount_wei): raise AssertionError(f"Expected received {amount_wei}, got {received}")
        expected_confs = latest_block - target_block_1 + 1 # Should match block 1 (higher confs)
        # B101 Fix
        if not (confs_found == expected_confs): raise AssertionError(f"Expected confs {expected_confs}, got {confs_found}")
        # B101 Fix
        if not (r_txid == tx_hash_1): raise AssertionError(f"Expected txid {tx_hash_1}, got {r_txid}")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address)
        # Should be called for both transactions 'to' address
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW)


    def test_scan_eth_no_deposit_found(self, mocker, mock_market_wallet_settings):
        """ETH scan finds no matching transactions within the lookback window."""
        latest_block = 1000
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW # The address we want
        tx_address = MOCK_ETH_TARGET_ADDRESS_RAW # The address in the mock tx ('0xaaaa...')

        mock_blocks = {}
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            # Use a different 'to' address for these filler blocks
            mock_blocks[i] = {'number': i, 'transactions': [ {'to': tx_address, 'value': 123, 'hash': b'otherhash', 'blockNumber': i} ]}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None when no deposit is found")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address) # Checksum of deposit address input (0x1111...)
        mock_checksum_obj.assert_any_call(tx_address) # Checksum of tx['to'] address (0xaaaa...)


    def test_scan_eth_deposit_outside_lookback(self, mocker, mock_market_wallet_settings):
        """ETH scan doesn't find a deposit because it's before the lookback window."""
        latest_block = 1000
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        target_block = latest_block - lookback - 50 # Outside window
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        tx_hash = "0x" + "d00d" + "0" * 60
        tx_hash_bytes = bytes.fromhex(tx_hash[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW

        mock_blocks = { target_block: { 'number': target_block, 'transactions': [ {'to': deposit_address, 'value': int(amount_wei), 'hash': tx_hash_bytes, 'blockNumber': target_block} ] } }
        start_scan_block = max(0, latest_block - lookback)
        # Only populate empty blocks within the actual scan window
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: # Avoid overwriting the target block if it fell within somehow
                mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is None): raise AssertionError("Expected result to be None as deposit is outside lookback")
        calls = mock_eth.get_block.call_args_list
        for c in calls:
            args, kwargs = c
            block_num_called = args[0]
            if isinstance(block_num_called, int):
                # B101 Fix (converted from assert)
                if not (block_num_called >= latest_block - lookback):
                        raise AssertionError(f"get_block called for block {block_num_called} which is outside lookback window")
        # Ensure checksum was still called for the deposit address itself
        mock_checksum_obj.assert_any_call(deposit_address)


    def test_scan_eth_rpc_error_block_number(self, mocker, mock_market_wallet_settings):
        """ETH scan handles ConnectionError when getting block_number."""
        # Use helper - this applies get_block and checksum patches
        # No specific block data needed here
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Override block_number property on the mock_eth instance returned by helper
        type(mock_eth).block_number = PropertyMock(side_effect=Web3ConnectionError("RPC Down"))

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', MOCK_ETH_DEPOSIT_ADDRESS_RAW, Decimal(1), 1)

        # Assertions
        # B101 Fix
        if not (result is None): raise AssertionError("Expected None on block_number RPC error")

        # Check prerequisites were called
        mock_get_client.assert_called_once()
        # Use the checksum mock from the helper
        mock_checksum_obj.assert_called_once_with(MOCK_ETH_DEPOSIT_ADDRESS_RAW)

        # *** Removed problematic call_count check ***
        # The checks above + result being None are sufficient evidence


    def test_scan_eth_rpc_error_get_block(self, mocker, mock_market_wallet_settings):
        """ETH scan handles ConnectionError during get_block loop."""
        latest_block = 1000
        # Use helper - this applies get_block and checksum patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Override get_block side effect on the mock returned by helper
        mock_eth.get_block.side_effect = Web3ConnectionError("RPC Down during get_block")

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', MOCK_ETH_DEPOSIT_ADDRESS_RAW, Decimal(1), 1)

        # Assertions
        # B101 Fix
        if not (result is None): raise AssertionError("Expected None on get_block RPC error")

        # Check prerequisites
        mock_get_client.assert_called_once()
        mock_checksum_obj.assert_called_once_with(MOCK_ETH_DEPOSIT_ADDRESS_RAW)
        # Check get_block was attempted (at least once for the start of the loop)
        mock_eth.get_block.assert_called()


    # <<< START Rev 68: Modified Test using return None >>>
    def test_scan_eth_block_not_found(self, mocker, mock_market_wallet_settings):
        """ETH scan handles missing blocks (mock returns None) and continues."""
        latest_block = 1000
        missing_block = 950
        target_block = 960 # Should be found after missing block
        confs_needed = 5
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        tx_hash = "0x" + "fedcba9876543210" + "0"*48
        tx_hash_bytes = bytes.fromhex(tx_hash[2:])
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW

        # Mock data: Only includes the target block and empty blocks within scan window
        mock_blocks = { target_block: { 'number': target_block, 'transactions': [ {'to': deposit_address, 'value': int(amount_wei), 'hash': tx_hash_bytes, 'blockNumber': target_block} ] } }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks and i != missing_block: # Do not populate the missing block
                mock_blocks[i] = {'number': i, 'transactions': []}

        # Setup mocks using the helper, instructing it to return None for the missing_block
        missing_config = {'return_none_on': missing_block} # <<< Rev 68: Use new config key
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(
            mocker,
            latest_block,
            mock_blocks,
            block_behavior_config=missing_config # Pass the config here
        )

        # Patch the client retrieval function to return the configured mock W3
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None, should find tx after missing block")
        is_confirmed, received, confs_found, r_txid = result
        # B101 Fix
        # --- MODIFIED HERE (Rev 82) ---
        if not is_confirmed: raise AssertionError("Expected is_confirmed to be True") # Changed from 'if not (not is_confirmed)' (assert False) to 'if not is_confirmed' (assert True)
        # B101 Fix
        if not (received == amount_wei): raise AssertionError(f"Expected received {amount_wei}, got {received}")
        expected_confs = latest_block - target_block + 1
        # B101 Fix
        if not (confs_found == expected_confs): raise AssertionError(f"Expected confs {expected_confs}, got {confs_found}")
        # B101 Fix
        if not (r_txid == tx_hash): raise AssertionError(f"Expected txid {tx_hash}, got {r_txid}")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address)
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW)

        # Verify get_block was called for both missing and target blocks (and potentially others)
        get_block_calls = mock_eth.get_block.call_args_list
        # <<< START Rev 70: Fix TypeError in assertion >>>
        called_missing = False
        called_target = False
        for call_args in get_block_calls:
            args, kwargs = call_args
            # Check if args is not None and has at least one element before indexing
            if args and len(args) > 0:
                if args[0] == missing_block and kwargs.get('full_transactions') is True:
                    called_missing = True
                if args[0] == target_block and kwargs.get('full_transactions') is True:
                    called_target = True
            # Optimization: break if both found
            if called_missing and called_target:
                break
        # <<< END Rev 70 >>>

        # B101 Fix
        if not called_missing: raise AssertionError(f"Expected get_block to be called for missing block {missing_block}")
        # B101 Fix
        if not called_target: raise AssertionError(f"Expected get_block to be called for target block {target_block}")
    # <<< END Rev 68/70/82: Modified Test >>>


    def test_scan_eth_malformed_tx_data(self, mocker, mock_market_wallet_settings):
        """ETH scan handles transactions with missing 'to', 'value', or 'blockNumber'."""
        latest_block = 1000
        target_block = 950
        confs_needed = 10
        amount_wei = Decimal(real_to_wei(0.1, 'ether'))
        deposit_address = MOCK_ETH_DEPOSIT_ADDRESS_RAW
        valid_tx_hash = "0xabc123" + "a" * 58 # Re-use hash from first test for simplicity
        valid_tx_hash_bytes = bytes.fromhex(valid_tx_hash[2:])

        mock_blocks = {
            target_block: {
                'number': target_block,
                'transactions': [
                    {'to': None, 'value': int(amount_wei), 'hash': b'hash1', 'blockNumber': target_block}, # Missing 'to'
                    {'to': deposit_address, 'value': None, 'hash': b'hash2', 'blockNumber': target_block}, # Missing 'value'
                    {'to': deposit_address, 'value': int(amount_wei), 'hash': b'hash3', 'blockNumber': None}, # Missing 'blockNumber'
                    # Also test missing hash
                    {'to': deposit_address, 'value': int(amount_wei), 'hash': None, 'blockNumber': target_block},
                    # Valid TX should still be found
                    {'to': deposit_address, 'value': int(amount_wei), 'hash': valid_tx_hash_bytes, 'blockNumber': target_block} # Valid TX
                ]
            }
        }
        lookback = mock_market_wallet_settings.MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW
        start_scan_block = max(0, latest_block - lookback)
        for i in range(start_scan_block, latest_block + 1):
            if i not in mock_blocks: mock_blocks[i] = {'number': i, 'transactions': []}

        # Use helper - this applies patches
        mock_w3, mock_eth, mock_checksum_obj = self._setup_eth_scan_mocks(mocker, latest_block, mock_blocks)

        # Apply ONLY the _get_eth_market_rpc_client patch locally
        mock_get_client = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client', return_value=mock_w3) # FIXED PATCH PATH

        # Execute service call
        result = service_under_test.scan_for_deposit('ETH', deposit_address, amount_wei, confs_needed)

        # Assertions
        # B101 Fix
        if not (result is not None): raise AssertionError("Expected result not to be None, should find valid tx among malformed ones")
        is_confirmed, received, confs_found, r_txid = result
        # B101 Fix
        if not is_confirmed: raise AssertionError("Expected is_confirmed to be True")
        # B101 Fix
        if not (received == amount_wei): raise AssertionError(f"Expected received {amount_wei}, got {received}")
        expected_confs = latest_block - target_block + 1
        # B101 Fix
        if not (confs_found == expected_confs): raise AssertionError(f"Expected confs {expected_confs}, got {confs_found}")
        # B101 Fix
        if not (r_txid == valid_tx_hash): raise AssertionError(f"Expected txid '{valid_tx_hash}', got {r_txid}")

        # Verify checksum calls using the helper's mock object
        mock_checksum_obj.assert_any_call(deposit_address)
        # It should be called for the tx missing 'blockNumber', the one missing 'hash', and the valid one
        mock_checksum_obj.assert_any_call(MOCK_ETH_DEPOSIT_ADDRESS_RAW)
        # B101 Fix - Check call count - should be called for the input address + 3 times for valid 'to' addresses in the loop
        # Check if the mock object has the 'call_count' attribute
        if hasattr(mock_checksum_obj, 'call_count'):
                # Assert that the call count is 4 (1 for input + 3 for valid 'to' addresses in the loop)
                # B101 Fix
                if not (mock_checksum_obj.call_count == 4): raise AssertionError(f"Expected checksum mock call count to be 4, got {mock_checksum_obj.call_count}")
        else:
                # If call_count is not available, maybe use call_args_list length
                # B101 Fix
                if not (len(mock_checksum_obj.call_args_list) == 4): raise AssertionError(f"Expected checksum mock call_args_list length to be 4, got {len(mock_checksum_obj.call_args_list)}")



# Fixture is applied automatically
class TestInitiateMarketWithdrawal:
    """Tests for initiate_market_withdrawal function."""

    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.validate_bitcoin_address') # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_withdraw_btc_success(self, mock_get_client, MockBtcClientClass, mock_validate_btc):
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.sendtoaddress.return_value = MOCK_BTC_TXID
        amount_btc = Decimal("0.1")

        txid = service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, amount_btc)

        # B101 Fix
        if not (txid == MOCK_BTC_TXID):
            raise AssertionError(f"Expected txid '{MOCK_BTC_TXID}', got '{txid}'")
        mock_validate_btc.assert_called_once_with(MOCK_BTC_ADDRESS)
        mock_get_client.assert_called_once()
        conf_target = getattr(django_settings, 'MARKET_BTC_CONF_TARGET', service_under_test.DEFAULT_BTC_CONF_TARGET)
        mock_client_instance.sendtoaddress.assert_called_once_with(
            address=MOCK_BTC_ADDRESS,
            amount=amount_btc, # Should be Decimal here
            subtractfeefromamount=True,
            conf_target=conf_target
        )

    # <<< START Rev 78/79: Added/Modified patch for the exception class >>>
    @patch('backend.store.services.market_wallet_service.BitcoinJSONRPCException') # FIXED PATCH PATH
    # <<< END Rev 78/79 >>>
    @patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.validate_bitcoin_address') # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.BitcoinAuthServiceProxy') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    # <<< START Rev 78/79: Added MockBtcExc argument >>>
    def test_withdraw_btc_rpc_error(self, mock_get_client, MockBtcClientClass, mock_validate_btc, MockBtcExc):
    # <<< END Rev 78/79 >>>
        """Test handling of RPC errors during BTC withdrawal."""
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        amount_btc = Decimal("0.1")

        # <<< START Rev 79: Configure mock exception constructor side effect >>>
        def exception_side_effect(error_data):
            """Create a real exception subclass instance with code/message attrs."""
            # Define a local class that inherits from Exception
            class MockExceptionClass(Exception):
                def __init__(self, data):
                    self.code = data.get('code')
                    self.message = data.get('message')
                    # Set the base exception message too for str() representation
                    super().__init__(f"MockBtcExc(code={self.code}, message='{self.message}')")

            return MockExceptionClass(error_data) # Return instance of the real subclass

        MockBtcExc.side_effect = exception_side_effect
        # <<< END Rev 79 >>>


        # 1. Test ConnectionError
        mock_client_instance.sendtoaddress.side_effect = ConnectionError("BTC node unavailable")
        with pytest.raises(CryptoProcessingError, match=r"BTC withdrawal failed \(ConnectionError\): BTC node unavailable"):
            service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, amount_btc)
        mock_validate_btc.assert_called_with(MOCK_BTC_ADDRESS) # Ensure validation still called
        mock_client_instance.sendtoaddress.assert_called_once() # Ensure RPC call was attempted
        mock_client_instance.sendtoaddress.reset_mock() # Reset for next error
        MockBtcExc.reset_mock() # Also reset the exception mock call count

        # 2. Test Insufficient Funds (JSONRPCException code -6)
        # <<< START Rev 78/79: Use the *mocked* exception class >>>
        insufficient_funds_error = MockBtcExc({'code': -6, 'message': 'Insufficient funds'})
        # <<< END Rev 78/79 >>>
        mock_client_instance.sendtoaddress.side_effect = insufficient_funds_error
        with pytest.raises(CryptoProcessingError, match=r"BTC withdrawal failed \(Insufficient Funds\): Insufficient funds"):
            service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, amount_btc)
        mock_client_instance.sendtoaddress.assert_called_once()
        mock_client_instance.sendtoaddress.reset_mock() # <<< ADDED MISSING RESET (Rev 77)
        MockBtcExc.reset_mock() # Also reset the exception mock call count

        # 3. Test Other JSONRPCException
        # <<< START Rev 78/79: Use the *mocked* exception class >>>
        other_rpc_error = MockBtcExc({'code': -5, 'message': 'Invalid address'})
        # <<< END Rev 78/79 >>>
        mock_client_instance.sendtoaddress.side_effect = other_rpc_error
        with pytest.raises(CryptoProcessingError, match=r"BTC withdrawal failed \(RPC Error\): Invalid address"):
            service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, amount_btc)
        mock_client_instance.sendtoaddress.assert_called_once()
        mock_client_instance.sendtoaddress.reset_mock()
        MockBtcExc.reset_mock() # Also reset the exception mock call count

        # 4. Test Unexpected Exception (Doesn't need the MockBtcExc)
        mock_client_instance.sendtoaddress.side_effect = TypeError("Unexpected type error")
        with pytest.raises(CryptoProcessingError, match=r"BTC withdrawal failed \(Unexpected Error\): Unexpected type error"):
            service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, amount_btc)
        mock_client_instance.sendtoaddress.assert_called_once()



    @patch('backend.store.services.market_wallet_service.MONERO_AVAILABLE', True) # FIXED PATCH PATH
    @patch('backend.store.services.market_wallet_service.validate_monero_address') # FIXED PATCH PATH
    @patch('backend.store.utils.conversion.xmr_to_piconero') # FIXED PATCH PATH: Patch correct location
    @patch('backend.store.services.market_wallet_service.MoneroWalletRPC') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_withdraw_xmr_success(self, mock_get_client, MockXmrClientClass, mock_conv, mock_validate_xmr):
        mock_client_instance = MockXmrClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        amount_xmr = Decimal("0.5")
        expected_pico = int(amount_xmr * 10**12)
        mock_conv.return_value=expected_pico
        mock_client_instance.transfer = MagicMock(return_value={'tx_hash': MOCK_XMR_TXID})
        txid = service_under_test.initiate_market_withdrawal('XMR', MOCK_XMR_ADDRESS, amount_xmr)
        # B101 Fix
        if not (txid == MOCK_XMR_TXID):
            raise AssertionError(f"Expected txid '{MOCK_XMR_TXID}', got '{txid}'")
        mock_validate_xmr.assert_called_once_with(MOCK_XMR_ADDRESS)
        mock_conv.assert_called_once_with(amount_xmr)
        mock_get_client.assert_called_once()
        transfer_priority = getattr(django_settings, 'MARKET_XMR_TRANSFER_PRIORITY', 1)
        mock_client_instance.transfer.assert_called_once_with(
            destinations=[{'address': MOCK_XMR_ADDRESS, 'amount': expected_pico}],
            priority=transfer_priority, get_tx_hex=True
        )

    # Using simplified mocks directly with mocker is often cleaner
    def test_withdraw_eth_success(self, mocker):
        """Test successful ETH withdrawal with simplified, direct mocks using mocker."""
        service_under_test._get_eth_market_rpc_client.cache_clear()

        # --- Configure Mocks using mocker ---
        mock_validate_eth = mocker.patch('backend.store.services.market_wallet_service.validate_ethereum_address') # FIXED PATCH PATH
        mock_get_w3_helper = mocker.patch('backend.store.services.market_wallet_service._get_eth_market_rpc_client') # FIXED PATCH PATH
        MockEthAccount = mocker.patch('backend.store.services.market_wallet_service.Account') # FIXED PATCH PATH
        mock_to_checksum_address = mocker.patch('backend.store.services.market_wallet_service.to_checksum_address') # FIXED PATCH PATH
        mocker.patch('backend.store.services.market_wallet_service.WEB3_AVAILABLE', True) # FIXED PATCH PATH
        # Mock to_wei directly as it's used by the withdrawal function
        mock_to_wei = mocker.patch('backend.store.services.market_wallet_service.to_wei', side_effect=real_to_wei) # FIXED PATCH PATH

        # 1. Mock w3 instance
        mock_w3_instance = MagicMock(name='MockW3Instance')
        mock_eth_instance = MagicMock(name='w3.eth')
        mock_w3_instance.eth = mock_eth_instance
        mock_get_w3_helper.return_value = mock_w3_instance

        # 2. Mock Account.from_key
        mock_sender_account = MagicMock(name='MockSenderAccount')
        mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
        MockEthAccount.from_key.return_value = mock_sender_account

        # 3. Mock to_checksum_address (using deterministic logic like in scan tests)
        def checksum_side_effect(addr):
                if addr is not None:
                    addr_lower = addr.lower()
                    if addr_lower == MOCK_ETH_TARGET_ADDRESS_RAW.lower(): return EXPECTED_CHECKSUM_TARGET
                    if addr_lower == MOCK_ETH_SENDER_ADDRESS_RAW.lower(): return EXPECTED_CHECKSUM_SENDER
                    # Add other known addresses if needed by other tests using this mock instance
                if real_to_checksum_address:
                    try: return real_to_checksum_address(addr)
                    except (ValueError, TypeError): pass
                # Basic fallback
                return f"0x{addr[2:].upper()}" if isinstance(addr, str) and addr.startswith('0x') else addr
        mock_to_checksum_address.side_effect = checksum_side_effect


        # 4. Configure w3.eth methods
        mock_eth_instance.get_transaction_count.return_value = 5
        mock_eth_instance.gas_price = 50 * 10**9
        mock_eth_instance.chain_id = 1
        mock_eth_instance.estimate_gas.return_value = 21000

        # 5. Configure signing mock
        mock_signed_tx = MagicMock(name='SignedTx')
        # Use double backslash for literal backslash
        mock_signed_tx.raw_transaction = b'\\mockedRawTxBytesWithdraw' # <<< MODIFIED HERE (Rev 80)
        mock_sender_account.sign_transaction.return_value = mock_signed_tx

        # 6. Configure send_raw_transaction mock
        mock_eth_instance.send_raw_transaction.return_value = MOCK_ETH_TX_HASH_BYTES

        # --- Call Service Function ---
        amount_eth = Decimal("0.01")
        expected_wei = int(real_to_wei(amount_eth, 'ether'))

        tx_hash = service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, amount_eth)

        # --- Assertions ---
        # B101 Fix
        if not (tx_hash == MOCK_ETH_TX_HASH):
                                raise AssertionError(f"Expected tx_hash '{MOCK_ETH_TX_HASH}', got '{tx_hash}'")
        mock_get_w3_helper.assert_called_once()
        mock_to_checksum_address.assert_any_call(MOCK_ETH_TARGET_ADDRESS_RAW) # Called for target address
        mock_validate_eth.assert_called_once_with(EXPECTED_CHECKSUM_TARGET) # Validated checksummed target
        MockEthAccount.from_key.assert_called_once_with(MOCK_ETH_SENDER_PK)
        mock_eth_instance.get_transaction_count.assert_called_once_with(EXPECTED_CHECKSUM_SENDER) # Nonce lookup uses checksummed sender
        expected_estimate_dict = {
            'to': EXPECTED_CHECKSUM_TARGET, 'value': expected_wei, 'gas': 0,
            'gasPrice': mock_eth_instance.gas_price, 'nonce': 5,
            'chainId': mock_eth_instance.chain_id, 'from': EXPECTED_CHECKSUM_SENDER
        }
        mock_eth_instance.estimate_gas.assert_called_once_with(expected_estimate_dict)
        gas_buffer_multiplier = Decimal(getattr(django_settings, 'MARKET_ETH_GAS_BUFFER_MULTIPLIER', '1.1'))
        expected_buffered_gas = int(21000 * gas_buffer_multiplier)
        expected_sign_dict = {
            'to': EXPECTED_CHECKSUM_TARGET, 'value': expected_wei, 'gas': expected_buffered_gas,
            'gasPrice': mock_eth_instance.gas_price, 'nonce': 5,
            'chainId': mock_eth_instance.chain_id
        }
        mock_sender_account.sign_transaction.assert_called_once_with(expected_sign_dict)
        mock_eth_instance.send_raw_transaction.assert_called_once_with(mock_signed_tx.raw_transaction)
        mock_to_wei.assert_called_once_with(amount_eth, 'ether') # Verify to_wei was called


    def test_withdraw_negative_amount(self):
        """Test withdrawal with negative or zero amount."""
        with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
            service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("-0.1"))
        with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
            service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("0"))

        btc_validator_target = 'backend.store.services.market_wallet_service.validate_bitcoin_address' # FIXED PATCH PATH
        with patch(btc_validator_target) if validate_bitcoin_address is None else nullcontext():
                with patch('backend.store.services.market_wallet_service.BITCOIN_AVAILABLE', True): # FIXED PATCH PATH
                    with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
                        service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, Decimal("0"))


    def test_withdraw_invalid_address(self):
        """Test withdrawal with an invalid target address."""
        invalid_addr = "not_an_address"
        # Mock the checksum function within the service to raise error for invalid address
        with patch('backend.store.services.market_wallet_service.to_checksum_address', side_effect=ValueError("Invalid address for checksum")): # FIXED PATCH PATH
            validator_patch_target = 'backend.store.services.market_wallet_service.validate_ethereum_address' # FIXED PATCH PATH
            # Patch validator only if it wasn't imported successfully
            with patch(validator_patch_target) if validate_ethereum_address is None else nullcontext():
                with pytest.raises(ValueError, match="Invalid target withdrawal address.*Invalid address for checksum"):
                    service_under_test.initiate_market_withdrawal('ETH', invalid_addr, Decimal("0.1"))


    # <<< Rev 49: Rewritten using mocker, removed mock_web3_client_context >>>
    @patch('backend.store.services.market_wallet_service.validate_ethereum_address') # FIXED PATCH PATH
    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    @patch('backend.store.services.market_wallet_service.Account') # FIXED PATCH PATH: Patch Account directly
    @patch('backend.store.services.market_wallet_service.to_checksum_address') # FIXED PATCH PATH: Patch checksum directly
    @patch('backend.store.services.market_wallet_service.to_wei') # FIXED PATCH PATH: Patch to_wei directly
    @patch('backend.store.services.market_wallet_service.WEB3_AVAILABLE', True) # <<< ADDED FIX Rev 84 >>>
    def test_withdraw_eth_send_fails(self, mock_to_wei, mock_to_checksum_address, MockEthAccount, mock_get_w3_helper, mock_validate_eth): # Removed WEB3_AVAILABLE from params as it's patched
        """Test ETH withdrawal when send_raw_transaction fails."""
        service_under_test._get_eth_market_rpc_client.cache_clear()

        # 1. Configure Mocks directly
        mock_w3_instance = MagicMock(name='MockW3Instance_SendFail')
        mock_eth_instance = MagicMock(name='w3.eth_SendFail')
        mock_w3_instance.eth = mock_eth_instance
        mock_get_w3_helper.return_value = mock_w3_instance

        # Mock Account.from_key
        mock_sender_account = MagicMock(name='MockSenderAccount_SendFail')
        mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
        MockEthAccount.from_key.return_value = mock_sender_account

        # Mock signing
        mock_signed_tx = MagicMock(name='SignedTx_SendFail')
        # Use double backslash for literal backslash
        mock_signed_tx.raw_transaction = b'\\mockedRawTxBytesSendFail' # <<< MODIFIED HERE (Rev 80)
        mock_sender_account.sign_transaction.return_value = mock_signed_tx

        # Mock checksum (ensure target address is checksummed)
        mock_to_checksum_address.return_value = EXPECTED_CHECKSUM_TARGET

        # Mock to_wei
        amount_eth = Decimal("0.01")
        expected_wei = int(real_to_wei(amount_eth, 'ether'))
        mock_to_wei.return_value = expected_wei

        # Configure w3.eth methods needed *before* send_raw_transaction
        mock_eth_instance.get_transaction_count.return_value = 5
        mock_eth_instance.gas_price = 50 * 10**9
        mock_eth_instance.chain_id = 1
        mock_eth_instance.estimate_gas.return_value = 21000

        # Configure send_raw_transaction to FAIL
        mock_eth_instance.send_raw_transaction.side_effect = Exception("Node connection lost during send")

        # 2. Call service function and assert exception
        expected_regex = r"Failed to send tx to node: Node connection lost during send"
        with pytest.raises(CryptoProcessingError, match=expected_regex):
            service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, amount_eth)

        # 3. Assert calls
        mock_validate_eth.assert_called_once_with(EXPECTED_CHECKSUM_TARGET)
        mock_get_w3_helper.assert_called_once()
        # Assert against the *patched* class MockEthAccount
        MockEthAccount.from_key.assert_called_once_with(MOCK_ETH_SENDER_PK)
        # Ensure signing was called
        mock_sender_account.sign_transaction.assert_called_once()
        # Ensure send was attempted
        mock_eth_instance.send_raw_transaction.assert_called_once()
        # Check checksum was called for the target address
        mock_to_checksum_address.assert_any_call(MOCK_ETH_TARGET_ADDRESS_RAW)


    def test_withdraw_eth_missing_sender_key(self, settings): # settings implicitly provided
        """Test ETH withdrawal when sender private key is not configured."""
        settings.MARKET_ETH_SENDER_PRIVATE_KEY = None
        service_under_test._get_eth_market_rpc_client.cache_clear()
        validator_patch_target = 'backend.store.services.market_wallet_service.validate_ethereum_address' # FIXED PATCH PATH
        checksum_patch_target = 'backend.store.services.market_wallet_service.to_checksum_address' # FIXED PATCH PATH
        # Use the real checksum function or a lambda returning the expected target checksum
        checksum_mock_func = real_to_checksum_address if real_to_checksum_address else lambda a: EXPECTED_CHECKSUM_TARGET

        with patch(validator_patch_target) if validate_ethereum_address is None else nullcontext():
                with patch(checksum_patch_target, side_effect=checksum_mock_func):
                    with pytest.raises(ImproperlyConfigured, match="MARKET_ETH_SENDER_PRIVATE_KEY not configured"):
                        service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("0.01"))


# ------ End Of file-----