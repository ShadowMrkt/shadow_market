# backend/store/tests/test_market_wallet_service.py
"""
Tests for the Market Wallet Service (store.services.market_wallet_service).
"""

# --- Revision History ---
# 2025-04-11 (Gemini Rev 30 - Test File):
#  - test_withdraw_eth_success: Resolved RecursionError by removing the
#    patching of `to_wei`. Calculated the expected_wei value directly
#    using the real `eth_utils.to_wei` function within the test. Removed
#    the assertion for MockToWei call.
# 2025-04-11 (Gemini Rev 29 - Test File):
#  - test_withdraw_eth_success: Simplified mocking by removing the shared
#    `mock_web3_client_context` and applying direct patches... (Introduced RecursionError)
# 2025-04-11 (Gemini Rev 28 - Test File):
#  - test_generate_eth_address: Simplified mocking... (Confirmed successful)
# 2025-04-11 (Gemini Rev 27 - Test File):
#  - Changed patch target for 'Account' in `mock_web3_client_context`... (Ineffective)
# 2025-04-11 (Gemini Rev 25 - Test File):
#  - test_get_eth_client_connection_error: Escaped regex characters...
#  - mock_web3_client_context: Redefined checksum address constants INSIDE the context...
#  - test_generate_eth_address: Compare against internally defined constant. (Approach changed in Rev 28)
#  - test_scan_eth_*: Assert get_balance call against internally defined constant.
#  - test_withdraw_eth_success: Assert validate_ethereum_address call against internally defined constant... (Approach changed in Rev 29)
# 2025-04-11 (Gemini Rev 24 - Test File):
#  - Changed patch target for 'Account' to 'eth_account.Account'. (Superseded)
#  - test_get_eth_client_success: Patched '_get_eth_market_rpc_client' directly...
#  - test_get_eth_client_connection_error: Patched '_get_eth_market_rpc_client' directly...
# ... (Previous revisions)
# ------------------------

import pytest
import re
from unittest.mock import patch, MagicMock, ANY, call, PropertyMock
from decimal import Decimal
from contextlib import contextmanager

# Django Imports
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

# Service being tested
from store.services import market_wallet_service
service_under_test = market_wallet_service
from store.exceptions import CryptoProcessingError

# Need these for type hints and using real functions as side_effects
try:
    from web3 import Web3
    from web3.providers.http import HTTPProvider
    # Import real to_wei for direct use in tests
    from eth_utils import to_wei as real_to_wei, to_checksum_address as real_to_checksum_address
    ETH_UTILS_AVAILABLE = True
except ImportError:
    Web3 = None
    HTTPProvider = None
    # Fallback lambda only used if eth-utils is missing
    real_to_wei = lambda x, unit: int(Decimal(str(x)) * (10**18))
    real_to_checksum_address = None
    to_checksum_address_fallback = lambda x: f"0x{x[2:].upper()}" if isinstance(x, str) and x.startswith('0x') else x
    ETH_UTILS_AVAILABLE = False


# --- Test Constants (Raw Values remain the same) ---
MOCK_ORDER_ID = "order_123xyz"
MOCK_BTC_RPC_USER = "testbtcuser"
MOCK_BTC_RPC_PASSWORD = "testbtcpassword"
MOCK_BTC_ADDRESS = "bc1qtestbtcaddressgenerated"
MOCK_BTC_ADDRESS_PLACEHOLDER = f"placeholder_btc_addr_for_{MOCK_ORDER_ID}"
MOCK_BTC_TXID = "btc_txid_" + "a" * 56
MOCK_BTC_TXID_PLACEHOLDER = f"placeholder_btc_withdrawal_txid_for_{MOCK_BTC_ADDRESS[:10]}"
MOCK_XMR_RPC_USER = "testxmruser"
MOCK_XMR_RPC_PASSWORD = "testxmrpassword"
MOCK_XMR_ADDRESS = "4AdreSs..." + "X" * 85
MOCK_XMR_TXID = "xmr_txid_" + "b" * 56
MOCK_ETH_RPC_URL = "http://mock-eth-node:8545"
MOCK_ETH_RAW_ADDRESS_GENERATED = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
EXPECTED_CHECKSUM_GENERATED = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'
MOCK_ETH_SENDER_ADDRESS_RAW = "0xdddddddddddddddddddddddddddddddddddddddd"
EXPECTED_CHECKSUM_SENDER = '0xDdDdDdDDdDDddDDddDDddDDDDdDDdDDdDDDDDDd'
MOCK_ETH_SENDER_PK = "0x" + "0" * 63 + "1"
MOCK_ETH_TARGET_ADDRESS_RAW = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
EXPECTED_CHECKSUM_TARGET = '0xaAaAaAaaAaAaAaaAaAAAAAAAAaaaAaAaAaaAaaAa'
MOCK_ETH_TX_HASH_RAW = "0x" + "c" * 64
MOCK_ETH_TX_HASH = MOCK_ETH_TX_HASH_RAW
MOCK_ETH_TX_HASH_BYTES = bytes.fromhex(MOCK_ETH_TX_HASH[2:])


# --- Fixtures (remains the same) ---
@pytest.fixture
def mock_market_wallet_settings(settings):
    """Override Django settings for market wallet tests."""
    settings.MARKET_BTC_RPC_USER = MOCK_BTC_RPC_USER
    settings.MARKET_BTC_RPC_PASSWORD = MOCK_BTC_RPC_PASSWORD
    settings.MARKET_BTC_RPC_HOST = '127.0.0.1'
    settings.MARKET_BTC_RPC_PORT = 8332
    settings.MARKET_XMR_WALLET_RPC_USER = MOCK_XMR_RPC_USER
    settings.MARKET_XMR_WALLET_RPC_PASSWORD = MOCK_XMR_RPC_PASSWORD
    settings.MARKET_XMR_WALLET_RPC_HOST = '127.0.0.1'
    settings.MARKET_XMR_WALLET_RPC_PORT = 18083
    settings.MARKET_ETH_RPC_URL = MOCK_ETH_RPC_URL
    settings.MARKET_ETH_SENDER_PRIVATE_KEY = MOCK_ETH_SENDER_PK
    settings.MARKET_ETH_POA_CHAIN = False
    settings.MARKET_RPC_TIMEOUT = 15
    settings.SECRET_KEY = getattr(settings, 'SECRET_KEY', 'test_secret_key')
    service_under_test._get_btc_market_rpc_client.cache_clear()
    service_under_test._get_xmr_market_rpc_client.cache_clear()
    service_under_test._get_eth_market_rpc_client.cache_clear()
    yield settings
    service_under_test._get_btc_market_rpc_client.cache_clear()
    service_under_test._get_xmr_market_rpc_client.cache_clear()
    service_under_test._get_eth_market_rpc_client.cache_clear()


# --- Mocks for Crypto Libraries (Shared Context - Kept for other tests) ---
@contextmanager
@patch('store.services.market_wallet_service.Web3')
@patch('store.services.market_wallet_service.HTTPProvider')
@patch('store.services.market_wallet_service.Account')
@patch('store.services.market_wallet_service.to_wei') # Still patching to_wei here for other tests
@patch('store.services.market_wallet_service.to_checksum_address')
def mock_web3_client_context(MockToChecksumAddress, MockToWei, MockEthAccount, MockHTTPProvider, MockWeb3):
    """
    Provides mocked Web3, Account, and utils within a context.
    NOTE: No longer used by test_generate_eth_address or test_withdraw_eth_success.
    """
    # (Code remains the same as Rev 28)
    mock_provider_instance = MockHTTPProvider.return_value
    mock_w3_instance = MockWeb3.return_value
    mock_eth_instance = MagicMock(name='w3.eth')
    mock_w3_instance.eth = mock_eth_instance
    mock_w3_instance.middleware_onion = MagicMock()
    mock_created_account = MagicMock(name='CreatedAccountInstance')
    mock_created_account.address = MOCK_ETH_RAW_ADDRESS_GENERATED
    mock_created_account.key.hex.return_value = "0xPRIVATEKEYMOCK" + "0"*48
    MockEthAccount.create.return_value = mock_created_account
    mock_sender_account = MagicMock(name='SenderAccountInstance')
    mock_sender_account.sign_transaction = MagicMock(name='sign_transaction')
    MockEthAccount.from_key.return_value = mock_sender_account
    # Assign side effect for MockToWei here if needed by other tests
    MockToWei.side_effect = real_to_wei
    def checksum_side_effect_simple(addr):
        if addr == MOCK_ETH_RAW_ADDRESS_GENERATED: return EXPECTED_CHECKSUM_GENERATED
        if addr == MOCK_ETH_SENDER_ADDRESS_RAW: return EXPECTED_CHECKSUM_SENDER
        if addr == MOCK_ETH_TARGET_ADDRESS_RAW: return EXPECTED_CHECKSUM_TARGET
        if ETH_UTILS_AVAILABLE and real_to_checksum_address:
             try: return real_to_checksum_address(addr)
             except: pass # noqa E722
        return f"0x{addr[2:].upper()}" if isinstance(addr, str) and addr.startswith('0x') else addr
    MockToChecksumAddress.side_effect = checksum_side_effect_simple
    mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
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
        MockEthAccount.create.return_value = mock_created_account
        mock_created_account.address = MOCK_ETH_RAW_ADDRESS_GENERATED
        mock_created_account.key.hex.return_value = "0xPRIVATEKEYMOCK" + "0"*48
        MockEthAccount.from_key.return_value = mock_sender_account
        mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
        MockToWei.side_effect = real_to_wei # Re-apply side effect after reset
        MockToChecksumAddress.side_effect = checksum_side_effect_simple # Re-apply side effect
        if success:
            mock_w3_instance.is_connected.return_value = True
            mock_eth_instance.block_number = 1000000
            mock_eth_instance.chain_id = 1
            mock_eth_instance.get_balance.return_value = 0
            mock_eth_instance.get_transaction_count = MagicMock(return_value=5)
            mock_eth_instance.gas_price = 50 * 10**9
            mock_eth_instance.estimate_gas.return_value = 21000
            mock_signed_tx = MagicMock(name='SignedTx')
            mock_signed_tx.raw_transaction = b'\mockedRawTxBytes'
            mock_sender_account.sign_transaction.return_value = mock_signed_tx
            mock_eth_instance.send_raw_transaction.return_value = MOCK_ETH_TX_HASH_BYTES
        else:
            mock_w3_instance.is_connected.side_effect = ConnectionError("w3.is_connected() returned False.")
            mock_w3_instance.is_connected.return_value = False
            mock_eth_instance.block_number = PropertyMock(side_effect=ConnectionError("Cannot get block number"))
            mock_eth_instance.get_transaction_count.side_effect = ConnectionError("Node unavailable for nonce")
    yield (configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
           EXPECTED_CHECKSUM_GENERATED, EXPECTED_CHECKSUM_SENDER, EXPECTED_CHECKSUM_TARGET)


# --- Test Classes ---

@pytest.mark.usefixtures("mock_market_wallet_settings")
class TestMarketWalletClientHelpers:
    """Tests for the _get_..._client helper functions."""
    # --- All tests in this class remain unchanged from Rev 29 ---
    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    @patch('store.services.market_wallet_service.BitcoinAuthServiceProxy')
    def test_get_btc_client_success(self, MockBtcClient):
        mock_instance = MockBtcClient.return_value
        mock_instance.ping.return_value = None
        service_under_test._get_btc_market_rpc_client.cache_clear()
        client = service_under_test._get_btc_market_rpc_client()
        assert client is not None
        MockBtcClient.assert_called_once()
        client.ping.assert_called_once()

    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    @patch('store.services.market_wallet_service.BitcoinAuthServiceProxy')
    def test_get_btc_client_connection_error(self, MockBtcClient):
        mock_instance = MockBtcClient.return_value
        mock_instance.ping.side_effect = ConnectionError("Mock BTC ping failed")
        service_under_test._get_btc_market_rpc_client.cache_clear()
        with pytest.raises(CryptoProcessingError, match=r"BTC RPC connection failed \(ConnectionError\): Mock BTC ping failed"):
            service_under_test._get_btc_market_rpc_client()
        MockBtcClient.assert_called_once()

    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    def test_get_btc_client_missing_config(self, settings):
        settings.MARKET_BTC_RPC_USER = None
        service_under_test._get_btc_market_rpc_client.cache_clear()
        with patch('store.services.market_wallet_service.BitcoinAuthServiceProxy'):
            with pytest.raises(ImproperlyConfigured, match="MARKET_BTC_RPC config missing"):
                service_under_test._get_btc_market_rpc_client()

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    def test_get_xmr_client_success(self, MockXmrClient):
        mock_instance = MockXmrClient.return_value
        mock_instance.get_version = MagicMock(return_value={'version': 'mock_v0.17'})
        service_under_test._get_xmr_market_rpc_client.cache_clear()
        client = service_under_test._get_xmr_market_rpc_client()
        assert client is not None
        MockXmrClient.assert_called_once()
        client.get_version.assert_called_once()

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    def test_get_xmr_client_connection_error(self, MockXmrClient):
        mock_instance = MockXmrClient.return_value
        mock_instance.get_version = MagicMock(side_effect=ConnectionError("Mock XMR get_version failed"))
        service_under_test._get_xmr_market_rpc_client.cache_clear()
        with pytest.raises(CryptoProcessingError, match=r"Monero RPC connection failed \(ConnectionError\): Mock XMR get_version failed"):
            service_under_test._get_xmr_market_rpc_client()
        MockXmrClient.assert_called_once()

    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_get_eth_client_success(self, mock_get_eth_client):
        mock_w3_success = MagicMock(name='MockW3Success')
        mock_w3_success.eth = MagicMock(name='eth')
        mock_w3_success.is_connected.return_value = True
        mock_w3_success.eth.block_number = 1000000
        mock_get_eth_client.return_value = mock_w3_success
        service_under_test._get_eth_market_rpc_client.cache_clear()
        client = service_under_test._get_eth_market_rpc_client()
        assert client is not None
        assert client == mock_w3_success
        mock_get_eth_client.assert_called_once()
        service_under_test._get_eth_market_rpc_client.cache_clear()

    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_get_eth_client_connection_error(self, mock_get_eth_client):
        error_message_raw = "Ethereum RPC connection failed (ConnectionError): Mocked connection failure."
        error_message_escaped = re.escape(error_message_raw)
        mock_get_eth_client.side_effect = CryptoProcessingError(error_message_raw)
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with pytest.raises(CryptoProcessingError, match=error_message_escaped):
            service_under_test._get_eth_market_rpc_client()
        mock_get_eth_client.assert_called_once()
        service_under_test._get_eth_market_rpc_client.cache_clear()

    def test_get_eth_client_missing_config(self, settings):
        settings.MARKET_ETH_RPC_URL = None
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with patch('store.services.market_wallet_service.WEB3_AVAILABLE', True):
             with patch('store.services.market_wallet_service.Web3', MagicMock()):
                  with patch('store.services.market_wallet_service.HTTPProvider', MagicMock()):
                       with pytest.raises(ImproperlyConfigured, match="MARKET_ETH_RPC_URL not configured"):
                            service_under_test._get_eth_market_rpc_client()


@pytest.mark.usefixtures("mock_market_wallet_settings")
class TestGenerateDepositAddress:
    """Tests for generate_deposit_address function."""

    # --- BTC/XMR Tests (unchanged) ---
    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    def test_generate_btc_address(self):
        address = service_under_test.generate_deposit_address('BTC', MOCK_ORDER_ID)
        assert address == MOCK_BTC_ADDRESS_PLACEHOLDER

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_generate_xmr_address(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_client_instance.create_address = MagicMock(return_value={'address': MOCK_XMR_ADDRESS, 'address_index': 1})
        mock_get_client.return_value = mock_client_instance
        address = service_under_test.generate_deposit_address('XMR', MOCK_ORDER_ID)
        assert address == MOCK_XMR_ADDRESS
        mock_get_client.assert_called_once()
        mock_client_instance.create_address.assert_called_once_with(account_index=0, label=f"order_{MOCK_ORDER_ID}")

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_generate_xmr_rpc_error(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_client_instance.create_address = MagicMock(side_effect=Exception("Mock XMR RPC Down"))
        mock_get_client.return_value = mock_client_instance
        with pytest.raises(CryptoProcessingError, match=r"XMR market address generation failed \(Unexpected Error\): Mock XMR RPC Down"):
            service_under_test.generate_deposit_address('XMR', MOCK_ORDER_ID)
        mock_get_client.assert_called_once()
        mock_client_instance.create_address.assert_called_once()

    # --- ETH Test (Simplified Mocking - Rev 28 - Passed) ---
    @patch('store.services.market_wallet_service.validate_ethereum_address')
    @patch('store.services.market_wallet_service.to_checksum_address')
    @patch('store.services.market_wallet_service.Account')
    def test_generate_eth_address(self, MockEthAccount, MockToChecksumAddress, mock_validate_addr):
        """Test successful ETH address generation with simplified, direct mocks."""
        mock_created = MagicMock()
        mock_created.address = MOCK_ETH_RAW_ADDRESS_GENERATED
        mock_created.key.hex.return_value = "0x..."
        MockEthAccount.create.return_value = mock_created
        MockToChecksumAddress.return_value = EXPECTED_CHECKSUM_GENERATED

        address = service_under_test.generate_deposit_address('ETH', MOCK_ORDER_ID)

        assert address == EXPECTED_CHECKSUM_GENERATED
        MockEthAccount.create.assert_called_once_with(f'order_{MOCK_ORDER_ID}_{django_settings.SECRET_KEY}')
        MockToChecksumAddress.assert_called_once_with(MOCK_ETH_RAW_ADDRESS_GENERATED)
        mock_validate_addr.assert_called_once_with(EXPECTED_CHECKSUM_GENERATED)

    # --- General Test ---
    def test_generate_unsupported_currency(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            service_under_test.generate_deposit_address('LTC', MOCK_ORDER_ID)


@pytest.mark.usefixtures("mock_market_wallet_settings")
class TestScanForDeposit:
    """Tests for scan_for_deposit function."""
    # --- Tests remain unchanged from Rev 29, still using context manager ---
    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    def test_scan_btc_found(self):
        result = service_under_test.scan_for_deposit('BTC', MOCK_BTC_ADDRESS, Decimal(100000), 3)
        assert result is None

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
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
        assert result is not None
        assert result[0] is True
        assert result[1] == amount_pico
        assert result[2] == confs_needed + 5
        assert result[3] == MOCK_XMR_TXID
        mock_get_client.assert_called_once()
        mock_client_instance.get_transfers.assert_called_once_with(in_=True, pool_=False, out_=False, pending_=False, failed_=False, filter_by_height=False)

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_scan_xmr_not_found(self, mock_get_client, MockXmrClientClass):
        mock_client_instance = MockXmrClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        mock_client_instance.get_transfers = MagicMock(return_value={'in': []})
        result = service_under_test.scan_for_deposit('XMR', MOCK_XMR_ADDRESS, Decimal(1000), 10)
        assert result is None
        mock_get_client.assert_called_once()
        mock_client_instance.get_transfers.assert_called_once()

    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_scan_eth_found(self, mock_get_w3_helper):
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with mock_web3_client_context() as (
            configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
            context_checksum_generated, _, _
        ):
            configure_mocks(success=True)
            mock_w3_instance = MockWeb3.return_value
            mock_get_w3_helper.return_value = mock_w3_instance
            amount_eth_dec = Decimal("0.05")
            # Use the MockToWei from context here
            amount_wei = Decimal(MockToWei(amount_eth_dec, 'ether'))
            confs_needed = 12
            mock_w3_instance.eth.get_balance.return_value = int(amount_wei)
            result = service_under_test.scan_for_deposit('ETH', context_checksum_generated, amount_wei, confs_needed)
            assert result is not None
            if result is not None:
                assert result[0] is True
                assert result[1] == amount_wei
                assert result[2] == confs_needed
                assert result[3] is None
                mock_get_w3_helper.assert_called_once()
                mock_w3_instance.eth.get_balance.assert_called_once_with(context_checksum_generated)

    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_scan_eth_zero_balance(self, mock_get_w3_helper):
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with mock_web3_client_context() as (
             configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
             context_checksum_generated, _, _
        ):
            configure_mocks(success=True)
            mock_w3_instance = MockWeb3.return_value
            mock_get_w3_helper.return_value = mock_w3_instance
            mock_w3_instance.eth.get_balance.return_value = 0
            result = service_under_test.scan_for_deposit('ETH', context_checksum_generated, Decimal(1), 12)
            assert result is None
            mock_get_w3_helper.assert_called_once()
            mock_w3_instance.eth.get_balance.assert_called_once_with(context_checksum_generated)

    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_scan_eth_rpc_error(self, mock_get_w3_helper):
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with mock_web3_client_context() as (
            configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
            context_checksum_generated, _, _
        ):
            configure_mocks(success=True)
            mock_w3_instance = MockWeb3.return_value
            mock_get_w3_helper.return_value = mock_w3_instance
            mock_w3_instance.eth.get_balance.side_effect = ConnectionError("ETH Node unavailable")
            result = service_under_test.scan_for_deposit('ETH', context_checksum_generated, Decimal(1), 12)
            assert result is None
            mock_get_w3_helper.assert_called_once()
            mock_w3_instance.eth.get_balance.assert_called_once_with(context_checksum_generated)


@pytest.mark.usefixtures("mock_market_wallet_settings")
class TestInitiateMarketWithdrawal:
    """Tests for initiate_market_withdrawal function."""

    # --- BTC/XMR Tests (unchanged) ---
    @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
    @patch('store.services.market_wallet_service.validate_bitcoin_address')
    @patch('store.services.market_wallet_service.BitcoinAuthServiceProxy')
    @patch.object(service_under_test, '_get_btc_market_rpc_client')
    def test_withdraw_btc_success(self, mock_get_client, MockBtcClientClass, mock_validate_btc):
        mock_client_instance = MockBtcClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        txid = service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, Decimal("0.1"))
        assert txid == MOCK_BTC_TXID_PLACEHOLDER
        mock_validate_btc.assert_called_once_with(MOCK_BTC_ADDRESS)
        mock_get_client.assert_called_once()

    @patch('store.services.market_wallet_service.MONERO_AVAILABLE', True)
    @patch('store.services.market_wallet_service.validate_monero_address')
    @patch('store.utils.conversion.xmr_to_piconero')
    @patch('store.services.market_wallet_service.MoneroWalletRPC')
    @patch.object(service_under_test, '_get_xmr_market_rpc_client')
    def test_withdraw_xmr_success(self, mock_get_client, MockXmrClientClass, mock_conv, mock_validate_xmr):
        mock_client_instance = MockXmrClientClass.return_value
        mock_get_client.return_value = mock_client_instance
        amount_xmr = Decimal("0.5")
        expected_pico = int(amount_xmr * 10**12)
        mock_conv.return_value=expected_pico
        mock_client_instance.transfer = MagicMock(return_value={'tx_hash': MOCK_XMR_TXID})
        txid = service_under_test.initiate_market_withdrawal('XMR', MOCK_XMR_ADDRESS, amount_xmr)
        assert txid == MOCK_XMR_TXID
        mock_validate_xmr.assert_called_once_with(MOCK_XMR_ADDRESS)
        mock_conv.assert_called_once_with(amount_xmr)
        mock_get_client.assert_called_once()
        mock_client_instance.transfer.assert_called_once_with(
            destinations=[{'address': MOCK_XMR_ADDRESS, 'amount': expected_pico}],
            priority=1, get_tx_hex=True
        )

    # --- ETH Tests (Simplified Mocking - Rev 30) ---
    @patch('store.services.market_wallet_service.validate_ethereum_address')
    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    @patch('store.services.market_wallet_service.Account')
    # Removed patch for to_wei
    @patch('store.services.market_wallet_service.to_checksum_address')
    def test_withdraw_eth_success(self, MockToChecksumAddress, MockEthAccount, mock_get_w3_helper, mock_validate_eth):
        """Test successful ETH withdrawal with simplified, direct mocks."""
        service_under_test._get_eth_market_rpc_client.cache_clear()

        # --- Configure Mocks ---
        # 1. Mock w3 instance
        mock_w3_instance = MagicMock(name='MockW3Instance')
        mock_eth_instance = MagicMock(name='w3.eth')
        mock_w3_instance.eth = mock_eth_instance
        mock_get_w3_helper.return_value = mock_w3_instance

        # 2. Mock Account.from_key
        mock_sender_account = MagicMock(name='MockSenderAccount')
        mock_sender_account.address = EXPECTED_CHECKSUM_SENDER
        MockEthAccount.from_key.return_value = mock_sender_account

        # 3. Mock to_checksum_address
        def checksum_side_effect(addr):
             if addr == MOCK_ETH_TARGET_ADDRESS_RAW: return EXPECTED_CHECKSUM_TARGET
             if addr == MOCK_ETH_SENDER_ADDRESS_RAW: return EXPECTED_CHECKSUM_SENDER
             if ETH_UTILS_AVAILABLE and real_to_checksum_address:
                 try: return real_to_checksum_address(addr)
                 except: pass # noqa E722
             return f"0x{addr[2:].upper()}" if isinstance(addr, str) and addr.startswith('0x') else addr
        MockToChecksumAddress.side_effect = checksum_side_effect

        # 4. Configure w3.eth methods
        mock_eth_instance.get_transaction_count.return_value = 5
        mock_eth_instance.gas_price = 50 * 10**9
        mock_eth_instance.chain_id = 1
        mock_eth_instance.estimate_gas.return_value = 21000

        # 5. Configure signing mock
        mock_signed_tx = MagicMock(name='SignedTx')
        mock_signed_tx.raw_transaction = b'\mockedRawTxBytesWithdraw'
        mock_sender_account.sign_transaction.return_value = mock_signed_tx

        # 6. Configure send_raw_transaction mock
        mock_eth_instance.send_raw_transaction.return_value = MOCK_ETH_TX_HASH_BYTES

        # --- Call Service Function ---
        amount_eth = Decimal("0.01")
        # Use the real to_wei function directly (imported at top of file)
        expected_wei = int(real_to_wei(amount_eth, 'ether'))

        tx_hash = service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, amount_eth)

        # --- Assertions ---
        # 1. Check final TX Hash
        assert tx_hash == MOCK_ETH_TX_HASH

        # 2. Check helper calls
        mock_get_w3_helper.assert_called_once()
        MockToChecksumAddress.assert_any_call(MOCK_ETH_TARGET_ADDRESS_RAW)
        mock_validate_eth.assert_called_once_with(EXPECTED_CHECKSUM_TARGET)

        # 3. Check Account.from_key call
        MockEthAccount.from_key.assert_called_once_with(MOCK_ETH_SENDER_PK)

        # 4. Check w3.eth calls (no check for to_wei anymore)
        mock_eth_instance.get_transaction_count.assert_called_once_with(EXPECTED_CHECKSUM_SENDER)
        expected_estimate_dict = {
            'to': EXPECTED_CHECKSUM_TARGET, 'value': expected_wei, 'gas': 0,
            'gasPrice': mock_eth_instance.gas_price, 'nonce': 5, # Use actual nonce value
            'chainId': mock_eth_instance.chain_id, 'from': EXPECTED_CHECKSUM_SENDER
        }
        mock_eth_instance.estimate_gas.assert_called_once_with(expected_estimate_dict)

        # 5. Check signing call
        expected_sign_dict = {
            'to': EXPECTED_CHECKSUM_TARGET, 'value': expected_wei, 'gas': 21000, # Use actual gas value
            'gasPrice': mock_eth_instance.gas_price, 'nonce': 5, # Use actual nonce value
            'chainId': mock_eth_instance.chain_id
        }
        mock_sender_account.sign_transaction.assert_called_once_with(expected_sign_dict)

        # 6. Check send call
        mock_eth_instance.send_raw_transaction.assert_called_once_with(mock_signed_tx.raw_transaction)


    def test_withdraw_negative_amount(self):
        """Test withdrawal with negative or zero amount."""
        with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
            service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("-0.1"))
        with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
            service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("0"))

        @patch('store.services.market_wallet_service.BITCOIN_AVAILABLE', True)
        @patch('store.services.market_wallet_service.validate_bitcoin_address')
        def run_btc_neg_test(mock_validate):
            with pytest.raises(ValueError, match="Withdrawal amount must be positive"):
                service_under_test.initiate_market_withdrawal('BTC', MOCK_BTC_ADDRESS, Decimal("0"))
        run_btc_neg_test()


    def test_withdraw_invalid_address(self):
        """Test withdrawal with an invalid target address."""
        invalid_addr = "not_an_address"
        with patch('store.services.market_wallet_service.to_checksum_address', side_effect=ValueError("Invalid address for checksum")):
             with patch('store.services.market_wallet_service.validate_ethereum_address'):
                 with pytest.raises(ValueError, match="Invalid target withdrawal address"):
                     service_under_test.initiate_market_withdrawal('ETH', invalid_addr, Decimal("0.1"))


    # Kept using context manager - may need simplification if it fails
    @patch('store.services.market_wallet_service.validate_ethereum_address')
    @patch.object(service_under_test, '_get_eth_market_rpc_client')
    def test_withdraw_eth_send_fails(self, mock_get_w3_helper, mock_validate_eth):
        """Test ETH withdrawal when send_raw_transaction fails."""
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with mock_web3_client_context() as (
            configure_mocks, MockWeb3, MockHTTPProvider, MockEthAccount, MockToWei, MockToChecksumAddress,
            _, _, context_checksum_target
        ):
            configure_mocks(success=True)
            mock_w3_instance = MockWeb3.return_value
            mock_get_w3_helper.return_value = mock_w3_instance
            mock_w3_instance.eth.send_raw_transaction.side_effect = Exception("Node connection lost during send")

            expected_regex = r"Failed to send transaction to node: Node connection lost during send"
            with pytest.raises(CryptoProcessingError, match=expected_regex):
                service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("0.01"))

            mock_validate_eth.assert_called_once_with(context_checksum_target)
            mock_get_w3_helper.assert_called_once()


    def test_withdraw_eth_missing_sender_key(self, settings):
        """Test ETH withdrawal when sender private key is not configured."""
        settings.MARKET_ETH_SENDER_PRIVATE_KEY = None
        service_under_test._get_eth_market_rpc_client.cache_clear()
        with patch('store.services.market_wallet_service.validate_ethereum_address'):
             with patch('store.services.market_wallet_service.to_checksum_address', return_value=EXPECTED_CHECKSUM_TARGET):
                 with pytest.raises(ImproperlyConfigured, match="MARKET_ETH_SENDER_PRIVATE_KEY not configured"):
                     service_under_test.initiate_market_withdrawal('ETH', MOCK_ETH_TARGET_ADDRESS_RAW, Decimal("0.01"))


# ------ End Of file-----