# backend/store/services/market_wallet_service.py
# --- Revision History ---
# 2025-05-03 (Gemini Rev 12): Enforced absolute imports starting with 'backend.'
#                              - Updated imports for exceptions, validators,
#                                utils.conversion, and models to use the
#                                'backend.' prefix (e.g., backend.store.models).
#                              Aims to resolve Django model registry conflicts.
# 2025-04-28 (Gemini Rev 77 - Fix Bandit B110 try_except_pass):
#  - generate_deposit_address (ETH): Replaced `except Exception: pass` in the `finally`
#    block during `hdwallet.clean_derivation()` call.
#  - Now catches `Exception as cleanup_exc` and logs a warning:
#    `logger.warning(f"Ignoring exception during HDWallet cleanup: {cleanup_exc}", exc_info=False)`
#  - This ensures potential cleanup errors are logged for visibility without
#    crashing and avoids excessive stack traces in logs for non-fatal cleanup issues.
# 2025-04-27 (Gemini Rev 76 - Fix BTC Withdrawal Insufficient Funds Handling):
#  - initiate_market_withdrawal (BTC): Reworked the `except Exception as e` block.
#    - Removed reliance on checking `isinstance(e, BitcoinJSONRPCException)`.
#    - Directly attempts to access `e.code` and `e.message` using `getattr`.
#    - Prioritizes checking for insufficient funds conditions (`e.code == -6` or
#      'insufficient funds' in message).
#    - If not insufficient funds, checks if the exception *looks like* an RPC error
#      (has `code` and `message` attributes) and raises "(RPC Error)".
#    - Otherwise, raises "(Unexpected Error)".
#    - This avoids issues where the imported `BitcoinJSONRPCException` might be None
#      at runtime within the function scope, ensuring the insufficient funds
#      case is correctly identified based on the caught exception's attributes.
# 2025-04-27 (Gemini Rev 75 - Fix BTC Withdrawal TypeError Catching):
#  - initiate_market_withdrawal (BTC): Removed the explicit `except BitcoinJSONRPCException`.
#    - Relies solely on `except Exception as e:`.
#    - Moved the `if BitcoinJSONRPCException and isinstance(e, BitcoinJSONRPCException):`
#      check inside the `except Exception as e:` block.
#    - This ensures Python doesn't raise a TypeError when trying to prepare the except clause
#      for a potentially non-BaseException class.
# 2025-04-27 (Gemini Rev 74 - Fix BTC Withdrawal Exception Type Handling):
#  - initiate_market_withdrawal (BTC): Restructured the `try...except` block again.
#    - Catches `ConnectionError` first.
#    - Catches general `Exception` next.
#    - *Inside* the `except Exception as e:` block, it now checks
#      `if BitcoinJSONRPCException and isinstance(e, BitcoinJSONRPCException):`.
#    - If it's a `BitcoinJSONRPCException`, it proceeds to check the error code (-6)
#      and raises the appropriate `CryptoProcessingError`.
#    - If it's any other `Exception`, it raises the "Unexpected Error" `CryptoProcessingError`.
#    - This avoids the `TypeError` from trying to directly catch a potentially non-BaseException class.
# 2025-04-27 (Gemini Rev 73 - Refactor BTC Withdrawal Exception Handling):
#  - initiate_market_withdrawal (BTC): Restructured the `try...except` block.
#    - Now explicitly catches `ConnectionError` first.
#    - Then explicitly catches `BitcoinJSONRPCException`. Inside this block:
#      - Checks for code -6 (Insufficient Funds) and raises the specific error.
#      - Raises the generic "RPC Error" for other codes.
#    - Finally catches the general `Exception` for truly unexpected issues.
#    - This prevents specific RPC errors from falling through to the generic handler.
# 2025-04-27 (Gemini Rev 71 - Implement BTC Placeholders):
#  - generate_deposit_address (BTC): Replaced placeholder with `btc_client.getnewaddress(label=label)`.
#    Added standard RPC error handling (ConnectionError, BitcoinJSONRPCException, unexpected).
#  - scan_for_deposit (BTC): Implemented logic using `btc_client.listtransactions`.
#    Requires `order_id` for label lookup.
#    Requires `btc_to_satoshi` conversion utility (import checked).
#    Iterates transactions, checks category, address, amount (converted to satoshis).
#    Selects best match based on highest confirmations.
#    Returns tuple or None. Added standard RPC error handling.
#  - initiate_market_withdrawal (BTC): Replaced placeholder with `btc_client.sendtoaddress`.
#    Uses `amount_standard` (Decimal BTC). Sets `subtractfeefromamount=True`.
#    Uses `conf_target` from settings or default.
#    Added standard RPC error handling, including specific check for insufficient funds (RPC code -6).
#  - Added/updated related logging and exception handling within BTC blocks.
# 2025-04-27 (Gemini Rev 69 - Explicit Tuple Return in ETH Scan):
#  - scan_for_deposit (ETH): Modified the return statement when a match is found.
#    - Explicitly creates the tuple `result_tuple = (is_confirmed, ...)` first.
#    - Added a DEBUG log to show the tuple's representation right before returning.
#    - Returns the explicitly created `result_tuple`. This aims to eliminate any
#      ambiguity or potential runtime issue causing only the first element to be returned.
# 2025-04-27 (Gemini Rev 67 - Add Debug Log Before get_block Call):
#  - scan_for_deposit (ETH): Added a specific DEBUG log immediately before the
#    `try...except BlockNotFound` block for the `w3.eth.get_block` call. This
#    helps confirm if the loop reaches the point of calling get_block for the
#    block that is expected to raise BlockNotFound in the failing test.
# 2025-04-27 (Gemini Rev 65 - Refine ETH Best Match Logic):
#  - scan_for_deposit (ETH): Modified the best_match update logic.
#    - It still prioritizes higher confirmations (`confs > highest_conf`).
#    - If confirmations are equal (`confs == highest_conf`), it now *only*
#      updates if the new match provides a valid `tx_hash_hex` when the
#      previous best match did not have one. This prevents a match with
#      no hash from incorrectly overwriting a match with the same confirmation
#      count that *does* have a hash, addressing the failure in
#      `test_scan_eth_malformed_tx_data`.
# 2025-04-27 (Gemini Rev 64 - Fix BlockNotFound & Malformed TX Handling):
#  - scan_for_deposit (ETH):
#    - Added specific `try...except BlockNotFound:` around the `w3.eth.get_block`
#      call inside the block loop. If BlockNotFound occurs, log a warning and
#      `continue` to the next block, ensuring the scan progresses.
#    - Modified the check for missing essential fields inside the transaction loop.
#      The loop now only skips the transaction immediately if `tx_to_raw` (address)
#      or `tx_value_raw` (value) are None, as these are critical for matching.
#    - Removed `blockNumber` and `hash` from the *initial* skip condition.
#    - Added specific logging *after* a potential match is found if `blockNumber`
#      or `hash` were missing, as this affects the final result but not the match itself.
#    - Updated confirmation calculation logic to handle potential `None` for `tx_block_num_int`.
# ... (previous revisions truncated) ...
# ------------------------

import logging
import sys
from decimal import Decimal, InvalidOperation # Added InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, ValidationError as DjangoValidationError # Added DjangoValidationError
from django.db import transaction, DatabaseError # Added transaction, DatabaseError
from django.db.models import F # Added F

# Crypto Libraries (handle optional imports)
_eth_import_error = None
try:
    from bitcoinrpc.authproxy import AuthServiceProxy as BitcoinAuthServiceProxy, JSONRPCException as BitcoinJSONRPCException
    BITCOIN_AVAILABLE = True
except ImportError:
    BitcoinAuthServiceProxy = None
    BitcoinJSONRPCException = None # Still define as None if import fails
    BITCOIN_AVAILABLE = False
    logging.getLogger(__name__).warning("Bitcoin libraries (bitcoinrpc) not found. BTC functionality will be disabled.")

try:
    from monero.backends.jsonrpc import JSONRPCWallet as MoneroWalletRPC
    from monero.exceptions import MoneroException
    MONERO_AVAILABLE = True
except ImportError:
    MoneroWalletRPC = None
    MoneroException = None
    MONERO_AVAILABLE = False
    logging.getLogger(__name__).warning("Monero libraries (monero-python) not found. XMR functionality will be disabled.")

# --- ETH Library Imports ---
try:
    from web3 import Web3, HTTPProvider
    from web3.exceptions import TransactionNotFound, BlockNotFound as Web3BlockNotFound
    from eth_account import Account
    from eth_utils import to_checksum_address, to_wei, from_wei
    WEB3_AVAILABLE = True
    BlockNotFound = Web3BlockNotFound # Use the real one
except ImportError as e:
    _eth_import_error = e
    Web3 = None
    HTTPProvider = None
    TransactionNotFound = None
    BlockNotFound = type('BlockNotFound', (Exception,), {}) # Dummy if web3.exceptions fails
    Account = None
    to_checksum_address = None
    to_wei = None
    from_wei = None
    WEB3_AVAILABLE = False
    logging.getLogger(__name__).warning(f"Core Ethereum libraries (web3, eth-account, eth-utils) import failed: {_eth_import_error}. ETH functionality may be limited or disabled.")
# --- End ETH Library Imports ---

# --- Add necessary HD Wallet and Vault imports ---
try:
    from hdwallet import HDWallet
    from hdwallet.utils import is_mnemonic
    from hdwallet.symbols import ETH as ETH_SYMBOL
    HDWALLET_AVAILABLE = True
except ImportError:
    HDWallet = None
    is_mnemonic = None
    ETH_SYMBOL = None
    HDWALLET_AVAILABLE = False

try:
    # Assuming vault_utils is outside the 'backend' hierarchy, or adjust path if needed
    from common.vault_utils import get_crypto_secret_from_vault, VaultError, VaultSecretNotFoundError, VaultAuthenticationError
except ImportError:
    def get_crypto_secret_from_vault(*args, **kwargs):
        raise ImportError("Vault utils (common.vault_utils) not found or import failed.")
    VaultError = type('VaultError', (Exception,), {})
    VaultSecretNotFoundError = type('VaultSecretNotFoundError', (VaultError,), {})
    VaultAuthenticationError = type('VaultAuthenticationError', (VaultError,), {})
    logging.getLogger(__name__).warning("Could not import Vault helpers/exceptions from common.vault_utils. Define dummies.")


# --- Local Imports (Using absolute paths from 'backend') ---
from backend.store.exceptions import CryptoProcessingError
try:
    from backend.store.validators import validate_ethereum_address, validate_monero_address, validate_bitcoin_address
except ImportError:
    validate_ethereum_address = None
    validate_monero_address = None
    validate_bitcoin_address = None
    logging.getLogger(__name__).error("Failed to import crypto address validators from backend.store.validators", exc_info=True)

try:
    from backend.store.utils.conversion import btc_to_satoshi, xmr_to_piconero
except ImportError:
    def btc_to_satoshi(*args, **kwargs):
        raise ImportError("Conversion utils (backend.store.utils.conversion) including btc_to_satoshi not found.")
    def xmr_to_piconero(*args, **kwargs):
        raise ImportError("Conversion utils (backend.store.utils.conversion) including xmr_to_piconero not found.")
    logging.getLogger(__name__).warning("Could not import btc_to_satoshi or xmr_to_piconero from backend.store.utils.conversion.")

try:
    from backend.store.models import GlobalSettings
except ImportError:
    GlobalSettings = None
    logging.getLogger(__name__).warning("Could not import GlobalSettings model from backend.store.models. ETH HD index tracking will fail.")


logger = logging.getLogger(__name__) # Standard module logger
root_logger = logging.getLogger() # <<< Rev 62: Get root logger for specific messages

# Default settings
DEFAULT_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW = 200
DEFAULT_BTC_LISTTRANSACTIONS_COUNT = 100
DEFAULT_BTC_CONF_TARGET = 6

# --- Internal Helper Functions ---
@lru_cache(maxsize=1) # Cache the client instance for efficiency
def _get_btc_market_rpc_client():
    """Gets a configured Bitcoin Core RPC client instance."""
    if not BITCOIN_AVAILABLE:
        raise ImproperlyConfigured("Bitcoin libraries (bitcoinrpc) not installed.")
    if not BitcoinAuthServiceProxy: # Check if class itself is available
        raise ImproperlyConfigured("BitcoinAuthServiceProxy class is not available (Import Error).")

    host = getattr(settings, 'MARKET_BTC_RPC_HOST', None)
    port = getattr(settings, 'MARKET_BTC_RPC_PORT', None)
    user = getattr(settings, 'MARKET_BTC_RPC_USER', None)
    password = getattr(settings, 'MARKET_BTC_RPC_PASSWORD', None)
    timeout = getattr(settings, 'MARKET_RPC_TIMEOUT', 30)

    if not all([host, port, user, password]):
        raise ImproperlyConfigured("MARKET_BTC_RPC config missing or incomplete in Django settings.")

    rpc_url = f"http://{user}:{password}@{host}:{port}"
    logger.debug(f"Attempting to connect to BTC RPC: {host}:{port}")
    try:
        client = BitcoinAuthServiceProxy(rpc_url, timeout=timeout)
        # Perform a simple command to test connection and authentication
        client.getblockchaininfo() # Changed from ping()
        logger.info("Successfully connected to Bitcoin market node.")
        return client
    except ConnectionError as ce: # Catch specific connection errors
        logger.error(f"Failed to connect to Bitcoin market node RPC ({host}:{port}): {ce}", exc_info=True)
        raise CryptoProcessingError(f"BTC RPC connection failed (ConnectionError): {ce}") from ce
    except Exception as e:
        # Check if it's the specific library exception, if the library was imported
        if BitcoinJSONRPCException and isinstance(e, BitcoinJSONRPCException):
            logger.error(f"Bitcoin RPC error during connection test ({host}:{port}): {e.code} - {e.message}", exc_info=True) # Log code and message
            # Provide more context for common RPC errors
            if e.code == -1: # Miscellaneous RPC error
                error_msg = f"BTC RPC connection failed (RPC Error): {e.message} (Code: {e.code})"
            elif e.code == -28: # RPC in warmup
                error_msg = f"BTC RPC connection failed (RPC Error): Node is starting up. {e.message} (Code: {e.code})"
            elif e.code == -32601: # Method not found (less likely for getblockchaininfo)
                error_msg = f"BTC RPC connection failed (RPC Error): Method not found. {e.message} (Code: {e.code})"
            else:
                error_msg = f"BTC RPC connection failed (RPC Error): {e.message} (Code: {e.code})"
            raise CryptoProcessingError(error_msg) from e
        # Catch other potential errors during init/ping
        logger.error(f"Unexpected error connecting to Bitcoin market node RPC ({host}:{port}): {e}", exc_info=True)
        if isinstance(e, BaseException) and not isinstance(e, Exception):
            raise # Don't wrap system-exiting exceptions etc.
        raise CryptoProcessingError(f"BTC RPC connection failed (Unexpected Error): {e}") from e


@lru_cache(maxsize=1)
def _get_xmr_market_rpc_client():
    """Gets a configured Monero Wallet RPC client instance."""
    if not MONERO_AVAILABLE:
        raise ImproperlyConfigured("Monero libraries (monero-python) not installed.")
    # Check the consistent variable name used in the import block
    if not MoneroWalletRPC:
        raise ImproperlyConfigured("MoneroWalletRPC class is not available (Import Error).")

    host = getattr(settings, 'MARKET_XMR_WALLET_RPC_HOST', '127.0.0.1')
    port = getattr(settings, 'MARKET_XMR_WALLET_RPC_PORT', 18083) # Default wallet RPC port
    user = getattr(settings, 'MARKET_XMR_WALLET_RPC_USER', None)
    password = getattr(settings, 'MARKET_XMR_WALLET_RPC_PASSWORD', None)
    # timeout = getattr(settings, 'MARKET_RPC_TIMEOUT', 120) # Check monero-python docs for timeout support

    logger.debug(f"Attempting to connect to Monero Wallet RPC: {host}:{port}")
    try:
        # Use the consistent imported name
        client = MoneroWalletRPC(host=host, port=port, user=user, password=password)
        version_info = client.get_version() # Test connection
        logger.info(f"Successfully connected to Monero market wallet RPC. Version: {version_info.get('version', 'N/A')}")
        return client
    except ConnectionError as ce:
        logger.error(f"Failed to connect to Monero market wallet RPC ({host}:{port}): {ce}", exc_info=True)
        raise CryptoProcessingError(f"Monero RPC connection failed (ConnectionError): {ce}") from ce
    except Exception as e:
        # Check if it's the specific library exception, if the library was imported
        if MoneroException and isinstance(e, MoneroException):
                logger.error(f"Monero library error during connection test ({host}:{port}): {e}", exc_info=True)
                raise CryptoProcessingError(f"Monero RPC connection failed (MoneroException): {e}") from e
        # Catch other potential errors during init/get_version
        logger.error(f"Unexpected error connecting to Monero market wallet RPC ({host}:{port}): {e}", exc_info=True)
        if isinstance(e, BaseException) and not isinstance(e, Exception):
                raise
        raise CryptoProcessingError(f"Monero RPC connection failed (Unexpected Error): {e}") from e


@lru_cache(maxsize=1)
def _get_eth_market_rpc_client():
    """Gets a configured Ethereum Web3 client instance."""
    # This check relies on the WEB3_AVAILABLE set during top-level import
    if not WEB3_AVAILABLE:
        detail = f": {_eth_import_error}" if _eth_import_error else ""
        raise ImproperlyConfigured(f"Ethereum libraries (web3, eth-account, eth-utils) not installed or import failed{detail}")

    # These checks should pass if WEB3_AVAILABLE is True, but are good safety measures
    if not Web3 or not HTTPProvider:
        raise ImproperlyConfigured("Web3 or HTTPProvider class not available (Internal State Error after import).")

    rpc_url = getattr(settings, 'MARKET_ETH_RPC_URL', None)
    rpc_timeout = getattr(settings, 'MARKET_RPC_TIMEOUT', 60)

    if not rpc_url:
        raise ImproperlyConfigured("MARKET_ETH_RPC_URL not configured in Django settings.")

    logger.debug(f"Attempting to connect to ETH RPC: {rpc_url}")
    try:
        provider = HTTPProvider(rpc_url, request_kwargs={'timeout': rpc_timeout})
        w3 = Web3(provider)

        # --- Inject middleware for PoA networks if configured ---
        if getattr(settings, 'MARKET_ETH_POA_CHAIN', False):
            try:
                # --- Attempt to import middleware ONLY when needed ---
                from web3.middleware import geth_poa_middleware
                # --- Inject the middleware ---
                # Verify correct method for your web3 version (e.g., add, inject)
                w3.middleware_onion.add(geth_poa_middleware)
                logger.info("Injected geth_poa_middleware for ETH connection.")
            except ImportError:
                logger.warning(
                    "MARKET_ETH_POA_CHAIN is True, but 'geth_poa_middleware' could not be imported "
                    "from 'web3.middleware'. PoA chain may not function correctly. "
                    "Check web3.py installation/version.",
                    exc_info=True # Log the ImportError traceback for debugging
                )
            except Exception as mw_err:
                logger.warning(
                    f"Failed to inject PoA middleware even after import attempt: {mw_err}. "
                    "Check web3.py version/API compatibility.",
                    exc_info=True
                )
        # --- End PoA Middleware Injection ---

        # Test connection
        if not w3.is_connected():
            # Use built-in ConnectionError here now
            raise ConnectionError("w3.is_connected() returned False.")

        block_number = w3.eth.block_number # Further test connection
        logger.info(f"Successfully connected to Ethereum market node. Current block: {block_number}")
        return w3
    # Catch built-in ConnectionError now
    except ConnectionError as ce: # Catch explicit ConnectionErrors
        logger.error(f"Failed to connect to Ethereum market node RPC ({rpc_url}): {ce}", exc_info=True)
        raise CryptoProcessingError(f"Ethereum RPC connection failed (ConnectionError): {ce}") from ce
    except Exception as e: # Catch other errors (e.g., from Web3 init, middleware, block_number call)
        logger.error(f"Unexpected error connecting to Ethereum market node RPC ({rpc_url}): {e}", exc_info=True)
        if isinstance(e, BaseException) and not isinstance(e, Exception):
                raise
        # Include original error message for context
        raise CryptoProcessingError(f"Ethereum RPC connection failed (Unexpected Error): {e}") from e


# --- Public Service Functions ---

def generate_deposit_address(currency: str, order_id: str) -> str:
    """
    Generates a new, unique deposit address for a specific order and currency.
    For BTC: Uses Bitcoin Core RPC `getnewaddress` with a label.
    For ETH: Uses a secure HD Wallet approach with a master seed from Vault.
    For XMR: Uses Monero wallet RPC `create_address`.
    """
    currency_upper = currency.upper()
    logger.info(f"Generating {currency_upper} deposit address for order {order_id}")

    # --- Availability Checks ---
    if currency_upper == 'BTC' and not BITCOIN_AVAILABLE:
        raise CryptoProcessingError("BTC support not available (libs missing).")
    if currency_upper == 'XMR' and not MONERO_AVAILABLE:
        raise CryptoProcessingError("XMR support not available (libs missing).")
    if currency_upper == 'ETH':
        if not WEB3_AVAILABLE:
            detail = f": {_eth_import_error}" if _eth_import_error else ""
            raise CryptoProcessingError(f"Core ETH support not available (libs missing or import failed{detail})")
        if not HDWALLET_AVAILABLE:
            raise CryptoProcessingError("Secure ETH address generation requires hdwallet library.")
        if not to_checksum_address:
            raise CryptoProcessingError("ETH to_checksum_address util not available (Internal State Error).")
        if not validate_ethereum_address:
            raise CryptoProcessingError("ETH validate_ethereum_address util not available (Internal State Error or Import Failed).")
        if not GlobalSettings:
             raise CryptoProcessingError("GlobalSettings model not available for ETH HD index tracking (Import Failed or Missing Model).")

    # --- Generation Logic ---
    try:
        if currency_upper == 'BTC':
            # --- Use Bitcoin Core RPC to generate address with label ---
            btc_client = _get_btc_market_rpc_client()
            label = f"order_{order_id}"
            try:
                # TODO: Consider address type if needed (e.g., bech32, legacy)
                # address = btc_client.getnewaddress(label=label, address_type='bech32')
                address = btc_client.getnewaddress(label=label)
                logger.info(f"Generated BTC address {address} with label '{label}' for order {order_id}")
                # TODO: Add validation using python-bitcoinlib once implemented (Task 2.5)
                return address
            except ConnectionError as ce:
                logger.error(f"BTC ConnectionError generating address for order {order_id}: {ce}", exc_info=True)
                raise CryptoProcessingError(f"BTC market address generation failed (ConnectionError): {ce}") from ce
            except Exception as e: # Catch general exception first
                # Then check if it's the specific RPC exception
                if BitcoinJSONRPCException and isinstance(e, BitcoinJSONRPCException):
                    logger.error(f"BitcoinJSONRPCException generating address for order {order_id}: {e.code} - {e.message}", exc_info=True)
                    raise CryptoProcessingError(f"BTC market address generation failed (RPC Error): {e.message}") from e
                # If not RPC exception, treat as unexpected
                logger.error(f"Unexpected error generating BTC address for order {order_id}: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"BTC market address generation failed (Unexpected Error): {e}") from e
            # --- End BTC Logic ---

        elif currency_upper == 'XMR':
            # --- Keep existing XMR Logic ---
            xmr_client = _get_xmr_market_rpc_client()
            try:
                # Using Monero wallet's create_address which handles subaddresses internally
                result = xmr_client.create_address(account_index=0, label=f"order_{order_id}")
                address = result.get('address')
                if not address:
                    logger.error(f"Monero create_address RPC call response missing 'address': {result}")
                    raise CryptoProcessingError("Monero create_address RPC did not return an address.")
                # Monero subaddress index is tracked within the wallet, no need for external index here.
                logger.info(f"Generated XMR address {address} (Index: {result.get('address_index', 'N/A')}) for order {order_id}")
                return address
            except ConnectionError as ce:
                logger.error(f"XMR ConnectionError generating address for order {order_id}: {ce}", exc_info=True)
                raise CryptoProcessingError(f"XMR market address generation failed (ConnectionError): {ce}") from ce
            except Exception as e:
                if MoneroException and isinstance(e, MoneroException):
                    logger.error(f"MoneroException generating address for order {order_id}: {e}", exc_info=True)
                    raise CryptoProcessingError(f"XMR market address generation failed (MoneroException): {e}") from e
                logger.error(f"Unexpected error generating XMR address for order {order_id}: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"XMR market address generation failed (Unexpected Error): {e}") from e
            # --- End XMR Logic ---

        elif currency_upper == 'ETH':
            # --- SECURE ETH HD Wallet Logic ---
            derivation_index = -1
            master_seed_phrase = None
            hdwallet = None
            try:
                logger.debug(f"Fetching ETH HD master seed from Vault for order {order_id}")
                master_seed_phrase = get_crypto_secret_from_vault(
                    key_type='eth', key_name='hd_master_seed', key_field='seed_phrase', raise_error=True
                )
                if not master_seed_phrase: raise VaultSecretNotFoundError("ETH HD master seed phrase is empty in Vault.")
                if is_mnemonic and not is_mnemonic(master_seed_phrase):
                    logger.error("The retrieved ETH HD master seed phrase from Vault is not a valid mnemonic.")
                    raise ValueError("Invalid ETH HD master seed phrase format retrieved from Vault.")

                logger.debug(f"Determining next ETH HD index atomically for order {order_id}")
                try:
                    with transaction.atomic():
                        settings_obj, created = GlobalSettings.objects.get_or_create(pk=1, defaults={'last_eth_hd_index': -1})
                        if created: logger.warning("Created default GlobalSettings record for ETH HD index tracking (pk=1).")
                        settings_obj_locked = GlobalSettings.objects.select_for_update().get(pk=settings_obj.pk)
                        settings_obj_locked.last_eth_hd_index = F('last_eth_hd_index') + 1
                        settings_obj_locked.save(update_fields=['last_eth_hd_index'])
                        settings_obj_locked.refresh_from_db(fields=['last_eth_hd_index'])
                        derivation_index = settings_obj_locked.last_eth_hd_index
                        if derivation_index < 0: raise ValueError(f"Derivation index is unexpectedly negative ({derivation_index}) after increment.")
                        logger.info(f"Atomically obtained next ETH HD derivation index: {derivation_index}")
                except AttributeError as ae:
                    if 'last_eth_hd_index' in str(ae):
                        logger.critical("CRITICAL SETUP ERROR: 'last_eth_hd_index' field not found on GlobalSettings model.")
                        raise ImproperlyConfigured("Missing 'last_eth_hd_index' field on GlobalSettings model.") from ae
                    else: raise
                except (ObjectDoesNotExist, DatabaseError, ValueError, TypeError) as idx_err:
                    logger.error(f"Failed to determine/increment next ETH HD derivation index: {idx_err}", exc_info=True)
                    raise CryptoProcessingError(f"Failed to determine next ETH HD derivation index ({type(idx_err).__name__}).") from idx_err

                logger.debug(f"Initializing HDWallet for index {derivation_index}")
                hdwallet = HDWallet(symbol=ETH_SYMBOL, use_default_path=False)
                hdwallet.from_mnemonic(mnemonic=master_seed_phrase, passphrase=None, language='english', strict=True)
                derivation_path = f"m/44'/60'/0'/0/{derivation_index}"
                logger.debug(f"Deriving ETH address using path: {derivation_path}")
                hdwallet.from_path(path=derivation_path)
                derived_address_raw = hdwallet.address()
                address = to_checksum_address(derived_address_raw)
                logger.debug(f"Derived raw address: {derived_address_raw}, Checksummed: {address}")

                try:
                    validate_ethereum_address(address)
                except DjangoValidationError as val_err:
                    logger.error(f"Generated ETH address failed validation: {val_err}")
                    raise CryptoProcessingError(f"Generated ETH address failed validation: {val_err}") from val_err

                logger.info(f"Generated SECURE ETH deposit address {address} using HD path {derivation_path} for order {order_id}")
                return address

            except (VaultSecretNotFoundError, VaultAuthenticationError, VaultError) as vault_e:
                 logger.error(f"Vault error retrieving ETH HD master seed: {vault_e}", exc_info=True)
                 raise CryptoProcessingError(f"Vault config/access error for ETH HD seed: {vault_e}") from vault_e
            except ImportError as imp_e:
                 logger.error(f"Import error likely related to Vault integration: {imp_e}", exc_info=True)
                 raise CryptoProcessingError(f"Vault integration module not found: {imp_e}") from imp_e
            except Exception as e:
                index_info = f"(Index Attempted: {derivation_index})" if derivation_index >= 0 else ""
                logger.error(f"Error generating SECURE ETH address {index_info}: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                error_type = type(e).__name__
                if isinstance(e, (ValueError, TypeError, ImproperlyConfigured)):
                    raise CryptoProcessingError(f"ETH address generation failed (Config/Value Error: {error_type} - {e})") from e
                else:
                    raise CryptoProcessingError(f"ETH address generation failed (HD Wallet/Processing Error: {error_type})") from e
            finally:
                if 'hdwallet' in locals() and hdwallet is not None:
                    try:
                        hdwallet.clean_derivation()
                    except Exception as cleanup_exc: # <<< MODIFIED HERE (Rev 77)
                        logger.warning(f"Ignoring exception during HDWallet cleanup: {cleanup_exc}", exc_info=False)
                if 'master_seed_phrase' in locals() and master_seed_phrase is not None:
                    del master_seed_phrase
            # --- End SECURE ETH HD Wallet Logic ---

        else:
            # This path should not be reachable if availability checks are correct
            raise ValueError(f"Unsupported currency for deposit address generation: {currency}")

    except (ValueError, CryptoProcessingError, ImproperlyConfigured) as specific_err:
        # Log specific errors that are expected control flow / config issues distinctly
        logger.warning(f"Specific error generating {currency_upper} address for order {order_id}: {specific_err}")
        raise specific_err
    except Exception as e:
        # Catch truly unexpected errors at the outer level
        logger.exception(f"Outer unexpected error generating {currency_upper} address for order {order_id}")
        if isinstance(e, BaseException) and not isinstance(e, Exception): raise
        raise CryptoProcessingError(f"Failed to generate {currency_upper} address due to outer unexpected error: {e}") from e


def scan_for_deposit(
    currency: str,
    deposit_address: str,
    expected_amount_atomic: Decimal, # Expected amount in smallest unit (satoshi, piconero, wei)
    confirmations_needed: int,
    # Add optional order_id for BTC label lookup
    order_id: str | None = None # <<< ADDED order_id parameter
) -> tuple[bool, Decimal, int, str | None] | None: # Adjusted return type hint for txid
    """
    Scans the relevant blockchain for a deposit to the given address.

    For BTC: Uses Bitcoin Core RPC `listtransactions` with label lookup (requires order_id).
    For ETH: Scans recent blocks for incoming transactions matching the address and amount.
    For XMR: Uses Monero wallet RPC `get_transfers`.

    Args:
        currency (str): The currency code (BTC, XMR, ETH).
        deposit_address (str): The address to scan.
        expected_amount_atomic (Decimal): Minimum amount expected in atomic units.
        confirmations_needed (int): Minimum confirmations required.
        order_id (str | None): Required for BTC label-based scanning.

    Returns:
        - None: If no relevant transaction is found or an error occurs.
        - tuple(is_confirmed, received_atomic, confirmations_found, txid): Details if found.
    """
    currency_upper = currency.upper()
    log_suffix = f"(Order: {order_id})" if order_id and currency_upper == 'BTC' else ""
    logger.debug(f"[SCAN START] Scanning for {currency_upper} deposit to {deposit_address}{log_suffix}, expecting >= {expected_amount_atomic} atomic units, needing {confirmations_needed} confs.")

    # --- Check Library Availability Early ---
    if currency_upper == 'ETH' and not WEB3_AVAILABLE:
        logger.warning(f"ETH scan skipped: Ethereum libraries not available or import failed ({_eth_import_error}).")
        return None
    if currency_upper == 'BTC' and not BITCOIN_AVAILABLE:
        logger.warning("BTC scan skipped: Bitcoin libraries not available.")
        return None
    if currency_upper == 'XMR' and not MONERO_AVAILABLE:
        logger.warning("XMR scan skipped: Monero libraries not available.")
        return None
    # --- End Availability Check ---

    logger.debug(f"[SCAN] Checking currency: {currency_upper}") # Retain this debug log

    try:
        if currency_upper == 'BTC':
            # --- BTC Logic ---
            logger.debug("[BTC SCAN] Entered BTC scanning path.")
            if not order_id:
                logger.error("BTC deposit scan requires order_id for label lookup.")
                return None # Return None as specified in docstring on error
            try:
                # Ensure conversion utility is loaded
                _ = btc_to_satoshi
            except NameError:
                logger.error("Missing btc_to_satoshi utility function for BTC scan.")
                raise CryptoProcessingError("Missing BTC conversion utility for scanning.")
            except ImportError as e:
                logger.error(f"ImportError accessing btc_to_satoshi: {e}")
                raise CryptoProcessingError("ImportError for BTC conversion utility.") from e

            btc_client = _get_btc_market_rpc_client()
            label = f"order_{order_id}"
            listtx_count = getattr(settings, 'MARKET_BTC_LISTTRANSACTIONS_COUNT', DEFAULT_BTC_LISTTRANSACTIONS_COUNT)

            found_deposit = None
            highest_conf = -1

            try:
                transactions = btc_client.listtransactions(
                    label=label,
                    count=listtx_count,
                    include_watchonly=True # Important if addresses aren't imported with rescan
                )
                logger.debug(f"Found {len(transactions)} transactions for label '{label}' (limit: {listtx_count})")

                for tx in transactions:
                    # Check if it's a receive transaction and matches the specific address
                    if tx.get('category') == 'receive' and tx.get('address') == deposit_address:
                        try:
                            # Amount in listtransactions is usually Decimal BTC
                            tx_amount_btc = Decimal(tx.get('amount', 0))
                            # Ignore negative amounts (shouldn't happen for 'receive')
                            if tx_amount_btc <= 0: continue

                            # Convert amount to satoshis for comparison
                            received_atomic = btc_to_satoshi(tx_amount_btc)
                            tx_confs = int(tx.get('confirmations', 0))
                            txid = tx.get('txid')

                            # Check if amount is sufficient and confirmations are better than current best
                            if received_atomic >= expected_amount_atomic and tx_confs > highest_conf:
                                logger.debug(f"Found potential BTC match for {deposit_address}: Amount {received_atomic} sat >= Expected {expected_amount_atomic} sat, Confs {tx_confs} > Highest {highest_conf}. TXID: {txid}")
                                found_deposit = (True, received_atomic, tx_confs, txid)
                                highest_conf = tx_confs

                        except (ValueError, TypeError, InvalidOperation) as parse_err:
                            logger.warning(f"Error processing BTC transaction data for {deposit_address}, label {label}: {parse_err}. TX: {tx}", exc_info=True)
                            continue # Skip this transaction if parsing fails

            except ConnectionError as ce:
                logger.error(f"BTC ConnectionError scanning deposits for {deposit_address} (label {label}): {ce}", exc_info=True)
                raise CryptoProcessingError(f"BTC deposit scan failed (ConnectionError): {ce}") from ce
            except Exception as e: # Catch general exception first
                if BitcoinJSONRPCException and isinstance(e, BitcoinJSONRPCException):
                    logger.error(f"BitcoinJSONRPCException scanning deposits for {deposit_address} (label {label}): {e.code} - {e.message}", exc_info=True)
                    raise CryptoProcessingError(f"BTC deposit scan failed (RPC Error): {e.message}") from e
                # Reraise if not the RPC exception or if it's a BaseException
                logger.error(f"Unexpected error scanning BTC deposits for {deposit_address} (label {label}): {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"BTC deposit scan failed (Unexpected Error): {e}") from e

            # After checking all transactions, process the best match found
            if found_deposit:
                is_sufficient, received, confs, txid = found_deposit
                is_confirmed = confs >= confirmations_needed
                logger.info(
                    f"Found best BTC deposit match for {deposit_address} (label {label}): Amount={received}, Confs={confs}, "
                    f"Needed={confirmations_needed}, Sufficiently Confirmed={is_confirmed}, TXID={txid}"
                )
                return is_confirmed, received, confs, txid
            else:
                logger.debug(f"No matching 'receive' BTC transaction found for {deposit_address} (label {label}) with sufficient amount in last {listtx_count} transactions.")
                return None
            # --- End BTC Logic ---

        elif currency_upper == 'XMR':
            # --- XMR Logic ---
            logger.debug("[XMR SCAN] Entered XMR scanning path.")
            xmr_client = _get_xmr_market_rpc_client()
            found_deposit = None
            highest_conf = -1
            try:
                transfers = xmr_client.get_transfers(in_=True, pool_=False, out_=False, pending_=False, failed_=False, filter_by_height=False)
            except ConnectionError as ce:
                logger.error(f"XMR ConnectionError scanning deposits: {ce}", exc_info=True)
                raise CryptoProcessingError(f"XMR deposit scan failed (ConnectionError): {ce}") from ce
            except Exception as e:
                if MoneroException and isinstance(e, MoneroException):
                    logger.error(f"MoneroException scanning deposits: {e}", exc_info=True)
                    raise CryptoProcessingError(f"XMR deposit scan failed (MoneroException): {e}") from e
                logger.error(f"Unexpected error scanning XMR deposits: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"XMR deposit scan failed (Unexpected Error): {e}") from e

            for tx in transfers.get('in', []):
                try:
                    tx_addr = tx.get('address')
                    if tx_addr == deposit_address:
                        tx_amount_pico = tx.get('amount', 0)
                        tx_confs = tx.get('confirmations', 0)
                        txid = tx.get('txid')
                        received_atomic = Decimal(tx_amount_pico)
                        confs = tx_confs if tx_confs is not None else 0
                        if received_atomic >= expected_amount_atomic and confs > highest_conf:
                            logger.debug(f"Found potential XMR match: Amount {received_atomic}, Confs {confs}, TXID: {txid}")
                            found_deposit = (True, received_atomic, confs, txid)
                            highest_conf = confs
                except (ValueError, TypeError, InvalidOperation) as dec_err:
                    logger.warning(f"Error processing XMR tx data: {dec_err}. TX: {tx}", exc_info=True)
                    continue
            if found_deposit:
                is_sufficient, received, confs, txid = found_deposit
                is_confirmed = confs >= confirmations_needed
                logger.info(f"Found best XMR match: Amount={received}, Confs={confs}, Needed={confirmations_needed}, Confirmed={is_confirmed}, TXID={txid}")
                return is_confirmed, received, confs, txid
            else:
                logger.debug(f"No confirmed XMR deposit found for {deposit_address}")
                return None
            # --- End XMR Logic ---

        elif currency_upper == 'ETH':
            # --- ETH Transaction History Scanning Logic ---
            logger.debug("[ETH SCAN] Entered ETH scanning path.")

            # --- START Rev 68: Explicitly ensure correct exception type is in scope ---
            try:
                # Attempt to import the specific exception from web3
                from web3.exceptions import BlockNotFound as Web3BlockNotFound_Local
                BlockNotFound_Local = Web3BlockNotFound_Local
                logger.debug("[ETH SCAN] Using specific BlockNotFound from web3.exceptions")
            except ImportError:
                # If web3.exceptions itself fails, use the global dummy/fallback
                BlockNotFound_Local = BlockNotFound
                logger.warning("[ETH SCAN] Using global BlockNotFound (dummy or fallback)")
            # --- END Rev 68 ---

            if not WEB3_AVAILABLE:
                logger.warning(f"[ETH SCAN] Internal Check: WEB3_AVAILABLE is False! ETH scan skipped. Import error was: {_eth_import_error}")
                return None
            if not to_checksum_address:
                logger.critical("[ETH SCAN] Internal Check: CRITICAL: to_checksum_address function is not available!")
                raise CryptoProcessingError("ETH to_checksum_address util not available (checked internally).")
            if BlockNotFound_Local.__name__ == 'BlockNotFound' and 'web3' not in BlockNotFound_Local.__module__:
                 logger.warning("[ETH SCAN] Internal Check: BlockNotFound_Local appears to be the dummy exception!")

            w3 = _get_eth_market_rpc_client()
            logger.debug("[ETH SCAN] Successfully obtained Web3 client.")
            best_match = None
            highest_conf = -1
            checksum_address = None
            try:
                checksum_address = to_checksum_address(deposit_address)
                logger.debug(f"[ETH SCAN] Target checksum address calculated: {checksum_address}")
            except Exception as cs_err:
                logger.error(f"[ETH SCAN] Invalid deposit address for checksum: {deposit_address} - {cs_err}", exc_info=True)
                raise CryptoProcessingError(f"Invalid deposit address for checksum: {deposit_address}") from cs_err

            latest_block_num = -1
            try:
                try:
                    block_num_prop = w3.eth.block_number
                    latest_block_num = int(block_num_prop)
                except ConnectionError as conn_err:
                    logger.error(f"[ETH SCAN] ConnectionError fetching latest block number: {conn_err}", exc_info=True)
                    raise CryptoProcessingError("Failed to get latest block number due to connection error.") from conn_err
                except (ValueError, TypeError) as conv_err:
                    logger.error(f"[ETH SCAN] Failed to convert block number ({block_num_prop}) to int: {conv_err}", exc_info=True)
                    raise CryptoProcessingError(f"Received non-integer block number: {block_num_prop}") from conv_err
                except Exception as block_num_err:
                    logger.error(f"[ETH SCAN] Unexpected error fetching latest block number: {block_num_err}", exc_info=True)
                    raise CryptoProcessingError(f"Failed to get latest block number: {block_num_err}") from block_num_err

                if latest_block_num < 0:
                    raise CryptoProcessingError(f"Latest block number is unexpectedly negative: {latest_block_num}")

                logger.debug(f"[ETH SCAN] Fetched latest block number: {latest_block_num}")

                lookback_window = getattr(settings, 'MARKET_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW', DEFAULT_ETH_DEPOSIT_SCAN_LOOKBACK_WINDOW)
                start_block = max(0, latest_block_num - lookback_window)
                logger.debug(f"[ETH SCAN] Calculated scan range: {start_block} to {latest_block_num} (Lookback: {lookback_window})")

                logger.debug(f"[ETH SCAN] Entering block iteration loop...")
                for block_num in range(start_block, latest_block_num + 1):
                    try: # Outer try for block processing
                        logger.debug(f"[ETH SCAN] Processing block {block_num}...")
                        block = None # Initialize before try

                        # <<< START Rev 67 >>>
                        logger.debug(f"[ETH SCAN] Attempting w3.eth.get_block({block_num}, full_transactions=True)")
                        # <<< END Rev 67 >>>
                        try:
                            block = w3.eth.get_block(block_num, full_transactions=True)
                        # <<< START Rev 68/69: Use explicitly imported Exception >>>
                        except BlockNotFound_Local:
                        # <<< END Rev 68/69 >>>
                            # Log and continue to the next block
                            logger.warning(f"[ETH SCAN] Block {block_num} not found while scanning. Continuing loop.")
                            continue # Go to next block_num
                        except ConnectionError as conn_err_get_block:
                            logger.error(f"[ETH SCAN] ConnectionError fetching block {block_num}: {conn_err_get_block}", exc_info=True)
                            # For connection errors, stopping might be safer than continuing with potentially stale data
                            raise CryptoProcessingError(f"Failed to get block {block_num} due to connection error.") from conn_err_get_block
                        except Exception as get_block_err:
                            # Catch other unexpected errors from get_block
                            logger.error(f"[ETH SCAN] Unexpected error fetching block {block_num}: {get_block_err}", exc_info=True)
                            raise CryptoProcessingError(f"Failed to get block {block_num}: {get_block_err}") from get_block_err

                        if not block:
                            # This handles the case where get_block returns None (e.g., from our Rev 68 test mock)
                            logger.debug(f"[ETH SCAN] Block {block_num}: Received None or empty block object. Skipping.")
                            continue

                        # --- Accessing Transactions ---
                        transactions = None
                        try:
                            transactions = block['transactions']
                        except KeyError:
                            logger.warning(f"[ETH SCAN] Block {block_num}: No 'transactions' key found. Skipping block.")
                            continue
                        except Exception as access_err:
                            logger.error(f"[ETH SCAN] Block {block_num}: Error accessing 'transactions': {access_err}", exc_info=True)
                            continue # Skip block if cannot access transactions reliably

                        if not transactions:
                            logger.debug(f"[ETH SCAN] Block {block_num}: Transactions list is empty or None.")
                            continue

                        if not isinstance(transactions, list):
                            logger.warning(f"[ETH SCAN] Block {block_num}: 'transactions' key found but is not a list (Type: {type(transactions)}). Skipping block.")
                            continue

                        logger.debug(f"[ETH SCAN] Block {block_num}: Found {len(transactions)} transactions. Iterating...")

                        # <<< START Rev 59/62 Logging Point (Use ROOT logger) >>>
                        root_logger.debug(f"[ETH SCAN pre-loop ROOT] Checking transactions list for block={block_num}: type={type(transactions)}, len={len(transactions)}, content={repr(transactions)}")
                        # <<< END Rev 59/62 Logging Point >>>

                        # --- Start of transaction loop ---
                        for tx_index, tx in enumerate(transactions):
                            # <<< START Rev 57/58/62 Logging Point (Use ROOT logger) >>>
                            root_logger.debug(f"[ETH SCAN tx loop ROOT] Processing block={block_num}, tx_index={tx_index}, type={type(tx)}, content={repr(tx)}")
                            # <<< END Rev 57/58/62 Logging Point >>>
                            log_prefix = f"[ETH SCAN block={block_num},tx_index={tx_index}]" # Local logger prefix
                            try: # Outer try for getting data from tx object
                                try:
                                    tx_to_raw = tx.get('to')
                                    tx_value_raw = tx.get('value')
                                    tx_block_num_raw = tx.get('blockNumber') # Still retrieve, check later
                                    tx_hash_raw = tx.get('hash') # Still retrieve, check later
                                    # Log retrieved values using the normal module logger
                                    logger.debug(f"{log_prefix} Retrieved values: to={repr(tx_to_raw)}, value={repr(tx_value_raw)}, blockNum={repr(tx_block_num_raw)}, hash={repr(tx_hash_raw)}")
                                except AttributeError as ae:
                                    logger.warning(f"{log_prefix} Error accessing tx data (AttributeError: {ae}). TX object type: {type(tx)}. Skipping.")
                                    continue # Exit: AttributeError accessing tx data

                                # <<< START Rev 64: Modified Essential Field Check >>>
                                # Only skip if 'to' or 'value' are None, as they are essential for matching
                                essential_missing_fields = []
                                if tx_to_raw is None: essential_missing_fields.append('to')
                                if tx_value_raw is None: essential_missing_fields.append('value')

                                if essential_missing_fields:
                                    root_logger.debug(f"{log_prefix} ROOT Skipping tx due to missing ESSENTIAL field(s) for matching: {', '.join(essential_missing_fields)}.")
                                    continue # Skip this transaction if core matching fields are missing
                                # <<< END Rev 64: Modified Essential Field Check >>>

                                # --- Start Inner Processing Block (for validated data) ---
                                # Use normal module logger for these detailed steps
                                logger.debug(f"{log_prefix} Passed essential checks, entering inner processing block.")
                                try:
                                    # 1. Checksum 'to' address (already ensured tx_to_raw is not None)
                                    tx_to_addr_checksum = None
                                    try:
                                        tx_to_addr_checksum = to_checksum_address(tx_to_raw)
                                        logger.debug(f"{log_prefix} Checksum address calculated: {tx_to_addr_checksum}")
                                    except ValueError as cs_val_err:
                                        # Should be less likely now tx_to_raw is checked, but keep for safety
                                        logger.debug(f"{log_prefix} Skipping tx due to invalid 'to' address for checksumming: {cs_val_err} (value='{tx_to_raw}').")
                                        continue

                                    # 2. Compare addresses
                                    address_match = (tx_to_addr_checksum == checksum_address)
                                    logger.debug(f"{log_prefix} Address match check: tx_checksum='{tx_to_addr_checksum}', target_checksum='{checksum_address}', match={address_match}")

                                    if address_match:
                                        logger.debug(f"{log_prefix} Address MATCHED!")

                                        # 3. Convert and compare value (already ensured tx_value_raw is not None)
                                        tx_value_wei = None
                                        try:
                                            if not isinstance(tx_value_raw, (int, float, str, Decimal)):
                                                raise TypeError(f"Unexpected type for tx value: {type(tx_value_raw)}")
                                            tx_value_wei = Decimal(tx_value_raw)
                                            if tx_value_wei < 0: raise ValueError("Transaction value cannot be negative.")
                                            logger.debug(f"{log_prefix} Converted value to Decimal: {tx_value_wei}")
                                        except (ValueError, TypeError, InvalidOperation) as val_conv_err:
                                            # Should be less likely now tx_value_raw is checked, but keep for safety
                                            logger.debug(f"{log_prefix} Skipping tx due to invalid 'value' format: {val_conv_err} (value='{tx_value_raw}').")
                                            continue

                                        amount_match = (tx_value_wei >= expected_amount_atomic)
                                        logger.debug(f"{log_prefix} Amount match check: tx_value='{tx_value_wei}', expected='{expected_amount_atomic}', match={amount_match}")

                                        if amount_match:
                                            logger.debug(f"{log_prefix} Amount MATCHED! (Value: {tx_value_wei}). Checking confirmations...")

                                            # 4. Convert block number and calculate confirmations
                                            # <<< Rev 64: Check tx_block_num_raw AFTER match confirmed >>>
                                            tx_block_num_int = None
                                            confs = 0 # Default to 0 if block number missing/invalid
                                            if tx_block_num_raw is None:
                                                logger.warning(f"{log_prefix} Matched address/amount, but 'blockNumber' is missing in tx data. Confirmations cannot be calculated accurately (defaulting to 0).")
                                            else:
                                                try:
                                                    if not isinstance(tx_block_num_raw, int):
                                                        if isinstance(tx_block_num_raw, str) and tx_block_num_raw.isdigit():
                                                            tx_block_num_int = int(tx_block_num_raw)
                                                        else:
                                                            raise TypeError(f"Unexpected type for tx blockNumber: {type(tx_block_num_raw)}")
                                                    else:
                                                        tx_block_num_int = tx_block_num_raw
                                                    if tx_block_num_int < 0: raise ValueError("Transaction block number cannot be negative.")
                                                    logger.debug(f"{log_prefix} Converted block number to Int: {tx_block_num_int}")
                                                    # Calculate confs only if block number is valid
                                                    confs = (latest_block_num - tx_block_num_int) + 1
                                                    logger.debug(f"{log_prefix} Calculated confirmations: {confs} (latest={latest_block_num}, tx_block={tx_block_num_int})")
                                                    if confs < 0:
                                                        logger.warning(f"{log_prefix} Calculated negative confirmations ({confs}). latest={latest_block_num}, tx_block={tx_block_num_int}. Treating as 0 confirmations.")
                                                        confs = 0 # Treat negative confs as 0
                                                except (ValueError, TypeError) as bn_conv_err:
                                                    logger.warning(f"{log_prefix} Matched address/amount, but failed to parse 'blockNumber': {bn_conv_err} (value='{tx_block_num_raw}'). Confirmations cannot be calculated accurately (defaulting to 0).")
                                                    # confs remains 0

                                            # 5. Format hash (More robustly)
                                            # <<< Rev 64: Check tx_hash_raw AFTER match confirmed >>>
                                            tx_hash_hex = None
                                            if tx_hash_raw is None:
                                                logger.warning(f"{log_prefix} Matched address/amount, but 'hash' is missing in tx data. TXID cannot be recorded.")
                                            else:
                                                try:
                                                    temp_hex = None
                                                    if isinstance(tx_hash_raw, bytes):
                                                        temp_hex = tx_hash_raw.hex()
                                                    elif isinstance(tx_hash_raw, str):
                                                        temp_hex = tx_hash_raw[2:] if tx_hash_raw.startswith('0x') else tx_hash_raw
                                                        int(temp_hex, 16) # Validate hex characters only
                                                    else:
                                                        raise TypeError(f"Unexpected type for tx hash: {type(tx_hash_raw)}")

                                                    if len(temp_hex) != 64:
                                                        logger.warning(f"{log_prefix} TX hash '{temp_hex}' has unexpected length ({len(temp_hex)}). Expected 64.")

                                                    tx_hash_hex = '0x' + temp_hex # Ensure prefix
                                                    logger.debug(f"{log_prefix} Formatted hash: {tx_hash_hex}")
                                                except (TypeError, ValueError) as hash_fmt_err:
                                                    logger.warning(f"{log_prefix} Could not format 'hash' ({tx_hash_raw}) to standard hex: {hash_fmt_err}. Storing as None.")
                                                    tx_hash_hex = None # Explicitly set to None on formatting error

                                            # <<< START Rev 65: Refined Best Match Logic >>>
                                            # 6. Best Match Logic
                                            # Prioritize higher confirmations, or if equal, prioritize matches with a valid TX hash
                                            update_best_match = False
                                            if confs > highest_conf:
                                                update_best_match = True
                                                logger.debug(f"{log_prefix} Conditions met. New best match due to higher confs ({confs} > {highest_conf}).")
                                            elif confs == highest_conf:
                                                # If confs are equal, only update if the current best_match doesn't have a hash
                                                # OR if this new match *does* have a hash and the old one didn't.
                                                # Essentially, prefer the one with the hash if confs are equal.
                                                if best_match is None or (best_match.get('tx_hash') is None and tx_hash_hex is not None):
                                                    update_best_match = True
                                                    logger.debug(f"{log_prefix} Conditions met. Updating best_match because confs ({confs}) are equal, and this match provides a TX hash where the previous might not have.")
                                                else:
                                                    logger.debug(f"{log_prefix} Conditions met, but confs ({confs}) are equal to highest_conf ({highest_conf}), and current best_match already has a hash or this one doesn't. Ignoring.")
                                            else: # confs < highest_conf
                                                logger.debug(f"{log_prefix} Conditions met, but confs {confs} < highest_conf {highest_conf}. Ignoring.")

                                            if update_best_match:
                                                highest_conf = confs
                                                best_match = {'tx_hash': tx_hash_hex, 'value': tx_value_wei, 'confs': confs}
                                            # <<< END Rev 65: Refined Best Match Logic >>>

                                        else: # Amount didn't match
                                            logger.debug(f"{log_prefix} Amount did not match (tx={tx_value_wei}, expected={expected_amount_atomic}).")
                                    # else: Address didn't match
                                    #     pass # Already logged

                                except Exception as inner_proc_err: # Catch unexpected error during inner processing
                                    logger.error(f"{log_prefix} Skipping tx due to unexpected error during inner processing: {inner_proc_err}", exc_info=True)
                                    continue # Skip to next transaction on inner error

                            except Exception as tx_outer_err: # Catch unexpected errors getting data from tx dict
                                logger.error(f"{log_prefix} Skipping tx due to unexpected error accessing raw data: {tx_outer_err}", exc_info=True)
                                continue # Skip to next transaction on outer error
                        # --- End of transaction loop ---

                    except CryptoProcessingError as cpe_block: # Catch errors raised during get_block or block access
                        logger.error(f"[ETH SCAN] Halting scan due to critical error processing block {block_num}: {cpe_block}")
                        raise # Re-raise to signal failure to the caller
                    except Exception as block_proc_err: # Catch unexpected errors processing block/tx list access
                        logger.error(f"[ETH SCAN] Unexpected error processing block {block_num} or its transaction list: {block_proc_err}", exc_info=True)
                        # Decide whether to stop scan or just skip block. Stopping is safer.
                        raise CryptoProcessingError(f"Failed during scan loop for block {block_num}: {block_proc_err}") from block_proc_err

                # --- End of block loop ---
                logger.debug("[ETH SCAN] Finished block iteration loop.")
                if best_match:
                    received_atomic = best_match['value']
                    confirmations_found = best_match['confs']
                    txid = best_match['tx_hash']
                    is_confirmed = confirmations_found >= confirmations_needed
                    logger.info(f"[ETH SCAN] Found best ETH match: Amount={received_atomic}, Confs={confirmations_found}, Needed={confirmations_needed}, Confirmed={is_confirmed}, TXID={txid}")
                    # <<< START Rev 69: Explicit Tuple Creation >>>
                    result_tuple = (is_confirmed, received_atomic, confirmations_found, txid)
                    logger.debug(f"[ETH SCAN] Returning result tuple: {repr(result_tuple)}") # Add log
                    return result_tuple
                    # <<< END Rev 69 >>>
                else:
                    logger.debug(f"[ETH SCAN] No suitable ETH deposit found for {checksum_address} in window.")
                    return None

            except CryptoProcessingError as cpe_outer:
                 logger.error(f"[ETH SCAN] Crypto Processing Error during ETH scan setup or loop: {cpe_outer}", exc_info=True)
                 raise # Re-raise critical errors
            except (ValueError, TypeError, InvalidOperation) as setup_err: # Catch potential checksum/block_number errors, Added InvalidOperation
                 logger.error(f"[ETH SCAN] ETH ValueError/TypeError/InvalidOperation during scan setup: {setup_err}", exc_info=True)
                 raise CryptoProcessingError(f"ETH deposit scan failed (Initial Setup Error): {setup_err}") from setup_err
            except Exception as e:
                logger.error(f"[ETH SCAN] Unexpected outer error scanning ETH deposits (before or during loop): {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"ETH deposit scan failed (Outer Unexpected Error): {e}") from e
            # --- End ETH Logic ---

        else:
            logger.warning(f"Unsupported currency for deposit scanning: {currency}")
            return None

    except (CryptoProcessingError, ImproperlyConfigured, ImportError) as cpe: # Added ImportError
        logger.error(f"Crypto Processing/Config/Import Error during {currency_upper} scan for {deposit_address}: {cpe}")
        return None # Do not raise, return None as per function spec
    except Exception as e:
        logger.exception(f"Outer unexpected error scanning for {currency_upper} deposit to {deposit_address}")
        if isinstance(e, BaseException) and not isinstance(e, Exception): raise
        return None


def initiate_market_withdrawal(
    currency: str,
    target_address: str,
    amount_standard: Decimal # Amount in standard units (BTC, XMR, ETH)
) -> str:
    """
    Initiates a withdrawal (release) from the market's central wallet.

    For BTC: Uses Bitcoin Core RPC `sendtoaddress`.
    For XMR: Uses Monero wallet RPC `transfer`.
    For ETH: Builds, signs, and sends a raw transaction via Web3.

    Returns:
        str: The transaction ID/hash of the withdrawal.
    Raises:
        ValueError: For invalid input amounts or addresses.
        ImproperlyConfigured: For missing settings (e.g., private key).
        CryptoProcessingError: For issues during the crypto operation (RPC errors, signing, sending).
    """
    logger.warning(f"Initiating market withdrawal: {amount_standard} {currency} to {target_address}")
    currency_upper = currency.upper()

    # --- Check Library Availability Early ---
    if currency_upper == 'BTC' and not BITCOIN_AVAILABLE: raise CryptoProcessingError("BTC support not available (libs missing).")
    if currency_upper == 'XMR' and not MONERO_AVAILABLE: raise CryptoProcessingError("XMR support not available (libs missing).")
    if currency_upper == 'ETH' and not WEB3_AVAILABLE:
        detail = f": {_eth_import_error}" if _eth_import_error else ""
        raise CryptoProcessingError(f"ETH support not available (libs missing or import failed{detail})")
    # --- End Availability Check ---

    # Input Validation
    if amount_standard <= 0:
        raise ValueError("Withdrawal amount must be positive.")

    # Address validation specific to currency
    try:
        if currency_upper == 'ETH':
            if not to_checksum_address: raise CryptoProcessingError("ETH to_checksum_address util not available.")
            target_address = to_checksum_address(target_address) # Checksum early
            if not validate_ethereum_address: raise CryptoProcessingError("ETH validate_ethereum_address util not available.")
            validate_ethereum_address(target_address)
        elif currency_upper == 'XMR':
            if not validate_monero_address: raise CryptoProcessingError("XMR validate_monero_address util not available.")
            validate_monero_address(target_address)
        elif currency_upper == 'BTC':
            if not validate_bitcoin_address: raise CryptoProcessingError("BTC validate_bitcoin_address util not available.")
            # TODO: Add proper BTC address validation (Task 2.5)
            logger.warning("Using basic BTC address validation (no checksum).")
            validate_bitcoin_address(target_address)
        else:
            raise ValueError(f"Unsupported currency for withdrawal: {currency}")
    except ImportError as imp_err:
        logger.error(f"Validator missing for {currency_upper}: {imp_err}")
        raise CryptoProcessingError(f"Cannot validate address: Validator for {currency_upper} not found.") from imp_err
    except (ValueError, TypeError, DjangoValidationError) as val_err: # Catch Django's ValidationError too
        logger.error(f"Invalid withdrawal address '{target_address}' for {currency}: {val_err}")
        err_msg = getattr(val_err, 'message', str(val_err))
        # Ensure target_address used in message reflects the potentially checksummed one for ETH
        display_addr = target_address # Already potentially checksummed for ETH or original for others
        raise ValueError(f"Invalid target withdrawal address '{display_addr}' for {currency}: {err_msg}") from val_err
    except Exception as e:
        logger.error(f"Unexpected error during address validation setup for {currency}: {e}", exc_info=True)
        if isinstance(e, BaseException) and not isinstance(e, Exception): raise
        raise CryptoProcessingError(f"Unexpected error during address validation setup for {currency}") from e

    # --- Withdrawal Logic ---
    try:
        if currency_upper == 'BTC':
            # --- BTC Withdrawal using sendtoaddress ---
            btc_client = _get_btc_market_rpc_client()
            conf_target = getattr(settings, 'MARKET_BTC_CONF_TARGET', DEFAULT_BTC_CONF_TARGET)
            try:
                # sendtoaddress expects amount in BTC (standard unit)
                txid = btc_client.sendtoaddress(
                    address=target_address,
                    amount=amount_standard, # Pass the Decimal directly
                    subtractfeefromamount=True,
                    conf_target=conf_target
                )
                logger.info(f"Initiated market BTC withdrawal. TXID: {txid}")
                return txid
            # <<< START Rev 76: Refined BTC Exception Handling v3 (Attribute-Based) >>>
            except ConnectionError as ce:
                logger.error(f"BTC ConnectionError during withdrawal: {ce}", exc_info=True)
                raise CryptoProcessingError(f"BTC withdrawal failed (ConnectionError): {ce}") from ce
            except Exception as e:
                # Attempt to extract RPC error details safely
                e_code = getattr(e, 'code', None)
                e_msg = getattr(e, 'message', None) # Prefer 'message' attribute
                e_str = str(e) # Always get the string representation

                # Determine the message to use: prefer 'message' attribute if available, else use str(e)
                final_msg = e_msg if e_msg is not None else e_str

                logger.error(f"Exception during BTC withdrawal: Type={type(e).__name__}, Code={e_code}, Message='{final_msg}'", exc_info=True)

                # --- Condition Checks ---
                # Check specifically for insufficient funds via code or message content
                is_insufficient_funds = (e_code == -6) or ('insufficient funds' in final_msg.lower())

                # Heuristic: Does it look like a JSONRPCException from the library? (Check for attributes)
                is_rpc_error_known = hasattr(e, 'code') and hasattr(e, 'message')

                # --- Raise Appropriate Exception ---
                if is_insufficient_funds:
                    raise CryptoProcessingError(f"BTC withdrawal failed (Insufficient Funds): {final_msg}") from e
                elif is_rpc_error_known: # It looks like an RPC error, but not insufficient funds
                    raise CryptoProcessingError(f"BTC withdrawal failed (RPC Error): {final_msg}") from e
                else: # Otherwise, treat as an unexpected error
                    if isinstance(e, BaseException) and not isinstance(e, Exception): raise # Don't wrap BaseExceptions like SystemExit
                    raise CryptoProcessingError(f"BTC withdrawal failed (Unexpected Error): {final_msg}") from e
            # <<< END Rev 76: Refined BTC Exception Handling v3 (Attribute-Based) >>>
            # --- End BTC Logic ---

        elif currency_upper == 'XMR':
            # --- XMR Logic ---
            xmr_client = _get_xmr_market_rpc_client()
            try:
                # Use absolute import path here
                try: from backend.store.utils.conversion import xmr_to_piconero
                except ImportError: raise CryptoProcessingError("Missing XMR conversion utility (checked path).")
                try:
                    amount_pico = xmr_to_piconero(amount_standard)
                    if amount_pico <= 0: raise ValueError("Piconero amount not positive.")
                except (ValueError, TypeError) as conv_err: raise ValueError(f"Invalid XMR amount: {amount_standard}") from conv_err
                try:
                    transfer_priority = getattr(settings, 'MARKET_XMR_TRANSFER_PRIORITY', 1)
                    result = xmr_client.transfer(
                        destinations=[{'address': target_address, 'amount': int(amount_pico)}],
                        priority=transfer_priority, get_tx_hex=True
                    )
                    txid = result.get('tx_hash')
                    if not txid: raise CryptoProcessingError("Monero transfer RPC missing 'tx_hash'.")
                    logger.info(f"Initiated market XMR withdrawal. TXID: {txid}")
                    return txid
                except ConnectionError as ce: raise CryptoProcessingError(f"XMR withdrawal failed (ConnectionError): {ce}") from ce
                except Exception as e:
                    if MoneroException and isinstance(e, MoneroException): raise CryptoProcessingError(f"XMR withdrawal failed (MoneroException): {e}") from e
                    logger.error(f"XMR transfer unexpected error: {e}", exc_info=True)
                    if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                    raise CryptoProcessingError(f"XMR withdrawal failed (Unexpected Transfer Error): {e}") from e
            except (CryptoProcessingError, ValueError) as inner_err: raise inner_err
            except Exception as e:
                logger.error(f"Unexpected error preparing XMR withdrawal: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"Unexpected error preparing XMR withdrawal: {e}") from e
            # --- End XMR Logic ---

        elif currency_upper == 'ETH':
            # --- ETH Withdrawal Logic ---
            if not Account: raise CryptoProcessingError("ETH Account lib component missing.")
            if not to_wei: raise CryptoProcessingError("ETH to_wei util missing.")
            sender_private_key = getattr(settings, 'MARKET_ETH_SENDER_PRIVATE_KEY', None)
            if not sender_private_key: raise ImproperlyConfigured("MARKET_ETH_SENDER_PRIVATE_KEY not configured.")
            w3 = _get_eth_market_rpc_client()
            sender_account = None # Define before try block
            try:
                # Added Debug Log (Rev 48)
                logger.debug(f"Attempting to load sender account from key for ETH withdrawal to {target_address}")
                sender_account = Account.from_key(sender_private_key)
                sender_address = sender_account.address
                logger.info(f"Using sender address {sender_address} for ETH withdrawal.")
            except Exception as key_err: raise ImproperlyConfigured(f"Invalid sender PK: {key_err}") from key_err
            try:
                try:
                    amount_wei = int(to_wei(amount_standard, 'ether'))
                    if amount_wei <= 0: raise ValueError("Wei amount not positive.")
                except (ValueError, TypeError) as conv_err: raise ValueError(f"Invalid ETH amount: {amount_standard}") from conv_err
                try:
                    nonce = w3.eth.get_transaction_count(sender_address)
                    gas_price = w3.eth.gas_price
                    chain_id = w3.eth.chain_id
                except Exception as net_info_err: raise CryptoProcessingError(f"Failed to get network info: {net_info_err}") from net_info_err
                tx_dict = {'to': target_address, 'value': amount_wei, 'gas': 0, 'gasPrice': gas_price, 'nonce': nonce, 'chainId': chain_id}
                try:
                    estimate_tx_dict = tx_dict.copy(); estimate_tx_dict['from'] = sender_address
                    estimated_gas = w3.eth.estimate_gas(estimate_tx_dict)
                    gas_buffer_multiplier = Decimal(getattr(settings, 'MARKET_ETH_GAS_BUFFER_MULTIPLIER', '1.1'))
                    tx_dict['gas'] = int(estimated_gas * gas_buffer_multiplier)
                    logger.debug(f"Estimated Gas: {estimated_gas}, Using Gas: {tx_dict['gas']}")
                except Exception as gas_err:
                    if 'insufficient funds' in str(gas_err).lower(): raise CryptoProcessingError(f"Gas estimation failed (Insufficient Funds?): {gas_err}") from gas_err
                    raise CryptoProcessingError(f"Failed to estimate gas: {gas_err}") from gas_err
                logger.debug(f"Final ETH Tx Dict: {tx_dict}")
                try:
                    signed_tx = sender_account.sign_transaction(tx_dict)
                except Exception as sign_err: raise CryptoProcessingError(f"Failed to sign tx: {sign_err}") from sign_err
                try:
                    tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    tx_hash_hex = tx_hash_bytes.hex()
                    # Ensure 0x prefix (already done in previous rev, keep for safety)
                    if not tx_hash_hex.startswith('0x'): tx_hash_hex = '0x' + tx_hash_hex
                    logger.info(f"Initiated market ETH withdrawal. TX HASH: {tx_hash_hex}")
                    return tx_hash_hex
                except Exception as send_err:
                    if 'nonce too low' in str(send_err).lower(): raise CryptoProcessingError(f"Failed to send tx (Nonce too low?): {send_err}") from send_err
                    if 'insufficient funds' in str(send_err).lower(): raise CryptoProcessingError(f"Failed to send tx (Insufficient Funds?): {send_err}") from send_err
                    raise CryptoProcessingError(f"Failed to send tx to node: {send_err}") from send_err
            # Catch specific web3/connection errors now
            except (ConnectionError, TransactionNotFound, TimeoutError, ValueError, InvalidOperation) as known_err: # Added InvalidOperation
                error_context = "node/network issue" if not isinstance(known_err, (ValueError, InvalidOperation)) else "value conversion/validation issue"
                raise CryptoProcessingError(f"ETH withdrawal failed ({error_context}): {known_err}") from known_err
            except CryptoProcessingError as cpe: raise cpe
            except Exception as e:
                logger.error(f"Unexpected error during ETH tx prep/send: {e}", exc_info=True)
                if isinstance(e, BaseException) and not isinstance(e, Exception): raise
                raise CryptoProcessingError(f"ETH withdrawal failed (Unexpected Signing/Sending Error): {e}") from e
            # --- End ETH Withdrawal Logic ---

        else:
            # Should not be reachable
            raise ValueError(f"Unsupported currency for withdrawal: {currency}")

    except (ValueError, CryptoProcessingError, ImproperlyConfigured) as specific_err:
        # Log specific errors expected from config/validation/inner logic
        logger.warning(f"Specific error initiating {currency_upper} withdrawal to {target_address}: {specific_err}")
        raise specific_err # Re-raise the specific error type
    except Exception as e:
        # Catch any other unexpected errors at the outer level
        logger.exception(f"Outer unexpected critical error during market withdrawal of {currency}")
        if isinstance(e, BaseException) and not isinstance(e, Exception): raise
        raise CryptoProcessingError(f"Unexpected withdrawal failure for {currency}: {e}") from e


# Note: Function for checking withdrawal confirmation status might still be needed.

# ------ End Of file-----