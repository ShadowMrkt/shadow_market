# backend/store/services/bitcoin_service.py
"""
Bitcoin Service for handling transactions, specializing in Taproot (P2TR) Multi-Sig.
Handles address generation, UTXO management, PSBTv2 creation/signing/finalization,
transaction broadcasting, fee estimation, and payment scanning.
"""
# <<< ENTERPRISE GRADE REVISION: v2.1.3 - Debug _get_market_btc_private_key Failure >>>
# Revision Notes:
# - v2.1.3 (2025-04-07):
#   - DEBUG (#1): Added specific debug logging around the public key verification step in
#     `_get_market_btc_private_key` to compare the derived pubkey hex with the expected hex
#     from settings, trying to pinpoint why the test `test_get_market_btc_private_key_success` fails.
# - v2.1.2 (2025-04-07):
#   - FIXED (#1): Changed `satoshis_to_btc` to raise `ValueError` (instead of TypeError) for invalid input types, matching test expectations.
#   - DEBUG (#2, #3, #4): Added extensive debug logging to `_get_market_btc_private_key` to trace execution flow regarding cache, lock, vault calls, and key processing, helping diagnose test failures.
#   - DEBUG (#6): Added debug logging to `create_btc_multisig_address` to trace execution flow when BITCOINLIB_AVAILABLE is mocked as True.
#   - CONFIRMED (#7): Input validation for `outputs` in `prepare_btc_multisig_tx` is working (now raises TypeError as expected when test passes string). Test code needs fixing.
#   - NOTED: Failures for mismatched log messages (#5, #8, #9, #10, #11, #12) still require test code updates.
# - v2.1.1 (2025-04-06): Fixed Test Failures (Validation, Logic)
# - v2.1.0: MAJOR REFACTOR & IMPLEMENTATION (details omitted)
# - v2.0.0: MAJOR REWRITE for Taproot (P2TR) 2/3 Multi-Sig Support (details omitted)
# --- Prior revisions omitted ---

import logging
import base64
import hashlib
import threading
import binascii # For hex conversions and error catching
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from typing import Optional, Dict, Tuple, List, Any, Union, TYPE_CHECKING

# --- Django Imports ---
from django.conf import settings
from django.db import transaction # Keep, might be used if service interacts with DB directly later

# --- Bitcoin Library Imports ---
# (Imports remain the same)
# Set defaults FIRST in case import fails
_BITCOINLIB_NETWORK_SET = False
BITCOINLIB_AVAILABLE = False
# Define base Exception types that exist even if the library isn't available
BitcoinAddressError_Base = ValueError # Map base address errors to ValueError
CBitcoinSecretError_Base = ValueError # Map base secret errors to ValueError
InvalidPubKeyError_Base = ValueError # Map base pubkey errors to ValueError
JSONRPCError_Base = ConnectionError # Map base RPC errors to ConnectionError
PSBTParseException_Base = ValueError # Map base PSBT errors to ValueError
TaprootError_Base = ValueError # Map base Taproot errors to ValueError

# Actual Library Import and Class Definitions
try:
    # Attempt to import the real library
    import bitcoin as RealBitcoinLib
    import bitcoin.wallet
    import bitcoin.rpc
    import bitcoin.core
    import bitcoin.core.script
    import bitcoin.core.key
    import bitcoin.psbt
    import bitcoin.base58

    # Assign actual classes/exceptions if import succeeds
    bitcoin = RealBitcoinLib
    CBitcoinSecret = bitcoin.wallet.CBitcoinSecret
    CBitcoinAddress = bitcoin.wallet.CBitcoinAddress
    P2TRBitcoinAddress = bitcoin.wallet.P2TRBitcoinAddress
    TaprootInfo = bitcoin.wallet.TaprootInfo
    TaprootScriptPath = bitcoin.wallet.TaprootScriptPath
    CMutableTransaction = bitcoin.core.CMutableTransaction
    CTxIn = bitcoin.core.CTxIn
    CTxOut = bitcoin.core.CTxOut
    COutPoint = bitcoin.core.COutPoint
    CScript = bitcoin.core.script.CScript
    OP_N = bitcoin.core.script.OP_N
    OP_CHECKMULTISIG = bitcoin.core.script.OP_CHECKMULTISIG
    TAPROOT_LEAF_VERSION = bitcoin.core.script.TAPROOT_LEAF_VERSION
    CKey = bitcoin.core.key.CKey
    CPubKey = bitcoin.core.key.CPubKey
    Proxy = bitcoin.rpc.Proxy
    PSBT = bitcoin.psbt.PSBT
    # Specific conversion functions
    lx = bitcoin.core.lx
    x = bitcoin.core.x
    # Exceptions from the library
    BitcoinAddressError = bitcoin.wallet.CBitcoinAddressError
    CBitcoinSecretError = bitcoin.wallet.CBitcoinSecretError
    InvalidPubKeyError = ValueError # bitcoinlib often uses ValueError for invalid key formats
    JSONRPCError = bitcoin.rpc.JSONRPCError
    PSBTParseException = bitcoin.psbt.PSBTParseException
    TaprootError = bitcoin.wallet.TaprootError

    BITCOIN_NETWORK_NAME = getattr(settings, 'BITCOIN_NETWORK', 'mainnet')
    logger_init = logging.getLogger(__name__) # Get logger for init phase
    if not BITCOIN_NETWORK_NAME:
        logger_init.critical("CRITICAL: settings.BITCOIN_NETWORK is not defined. Bitcoin functionality may fail.")
        BITCOIN_NETWORK_NAME = 'mainnet' # Fallback
        logger_init.warning(f"WARNING: Falling back to default Bitcoin network: {BITCOIN_NETWORK_NAME}")
    elif BITCOIN_NETWORK_NAME not in ['mainnet', 'testnet', 'regtest', 'signet']:
        logger_init.critical(f"CRITICAL: Invalid settings.BITCOIN_NETWORK: '{BITCOIN_NETWORK_NAME}'. Must be mainnet, testnet, regtest, or signet.")
        BITCOIN_NETWORK_NAME = 'mainnet' # Fallback
        logger_init.warning(f"WARNING: Falling back to default Bitcoin network: {BITCOIN_NETWORK_NAME}")

    bitcoin.SelectParams(BITCOIN_NETWORK_NAME)
    _BITCOINLIB_NETWORK_SET = True
    BITCOINLIB_AVAILABLE = True
    logger_init.info(f"python-bitcoinlib imported successfully. Network set to: {BITCOIN_NETWORK_NAME}")

except (ImportError, ModuleNotFoundError) as lib_err:
    logging.basicConfig(level=logging.CRITICAL) # Ensure logging is configured if lib fails early
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL: Failed to import essential python-bitcoinlib components: {lib_err}. Bitcoin functionality DISABLED.")
    BITCOINLIB_AVAILABLE = False
    _BITCOINLIB_NETWORK_SET = False
    # Use base exception types if library fails
    BitcoinAddressError = BitcoinAddressError_Base
    CBitcoinSecretError = CBitcoinSecretError_Base
    InvalidPubKeyError = InvalidPubKeyError_Base
    JSONRPCError = JSONRPCError_Base
    PSBTParseException = PSBTParseException_Base
    TaprootError = TaprootError_Base
    # Define dummy placeholders for type hints if needed elsewhere, though explicit checks are better
    CBitcoinSecret = object
    CBitcoinAddress = object
    P2TRBitcoinAddress = object
    TaprootInfo = object
    TaprootScriptPath = object
    CMutableTransaction = object
    CTxIn = object
    CTxOut = object
    COutPoint = object
    CScript = object
    OP_N = lambda n: n
    OP_CHECKMULTISIG = 0xae
    TAPROOT_LEAF_VERSION = 0xc0
    CKey = object
    CPubKey = object
    Proxy = object
    PSBT = object
    lx = lambda v: v
    x = lambda v: v


# --- Type Hinting Imports (using real types if available) ---
# (Type hinting imports remain the same)
if TYPE_CHECKING:
    from store.models import Order as OrderModelTypeHint, CryptoPayment as CryptoPaymentTypeHint, User as UserModelTypeHint
    # Define concrete types for better static analysis if bitcoinlib loaded
    if BITCOINLIB_AVAILABLE:
        BitcoinProxy = Proxy
        BitcoinCKey = CKey
        BitcoinCPubKey = CPubKey
        BitcoinCScript = CScript
        BitcoinPSBT = PSBT
        BitcoinCMutableTransaction = CMutableTransaction
        BitcoinCTxOut = CTxOut
        BitcoinCTxIn = CTxIn
        BitcoinCOutPoint = COutPoint
        BitcoinP2TRAddress = P2TRBitcoinAddress
        BitcoinCBitcoinAddress = CBitcoinAddress
        BitcoinTaprootInfo = TaprootInfo
        BitcoinTaprootScriptPath = TaprootScriptPath
    else: # Fallback to Any if import failed, avoids NameError in type checking
        BitcoinProxy = Any
        BitcoinCKey = Any
        BitcoinCPubKey = Any
        BitcoinCScript = Any
        BitcoinPSBT = Any
        BitcoinCMutableTransaction = Any
        BitcoinCTxOut = Any
        BitcoinCTxIn = Any
        BitcoinCOutPoint = Any
        BitcoinP2TRAddress = Any
        BitcoinCBitcoinAddress = Any
        BitcoinTaprootInfo = Any
        BitcoinTaprootScriptPath = Any
else:
    # Define runtime fallbacks if not TYPE_CHECKING, prevents runtime NameErrors
    BitcoinProxy = Any
    BitcoinCKey = Any
    BitcoinCPubKey = Any
    BitcoinCScript = Any
    BitcoinPSBT = Any
    BitcoinCMutableTransaction = Any
    BitcoinCTxOut = Any
    BitcoinCTxIn = Any
    BitcoinCOutPoint = Any
    BitcoinP2TRAddress = Any
    BitcoinCBitcoinAddress = Any
    BitcoinTaprootInfo = Any
    BitcoinTaprootScriptPath = Any


# --- Local Imports ---
# (Local imports remain the same)
try:
    # Runtime imports
    from store.models import Order, CryptoPayment, User
    from store.exceptions import CryptoProcessingError # Import local exception
    # from ledger.models import LedgerTransaction # Removed as not directly used here
    from vault_integration import get_crypto_secret_from_vault
    MODELS_AVAILABLE = True
    VAULT_AVAILABLE = callable(get_crypto_secret_from_vault)
except ImportError as e:
    # Ensure logger exists before using it here
    if 'logger_init' not in locals():
        logging.basicConfig(level=logging.CRITICAL)
        logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL: Failed to import local models/vault in bitcoin_service.py: {e}")
    # Define dummy placeholders for runtime if imports fail
    class Order: pass
    class CryptoPayment: pass
    class User: pass
    class CryptoProcessingError(Exception): pass # Define dummy exception
    get_crypto_secret_from_vault = None
    MODELS_AVAILABLE = False
    VAULT_AVAILABLE = False
    # Define dummy type hints if needed by runtime logic (though checks are better)
    OrderModelTypeHint = Any
    CryptoPaymentTypeHint = Any
    UserModelTypeHint = Any


# --- Constants ---
# (Constants remain the same)
SATOSHIS_PER_BTC = Decimal('100000000')
BTC_DECIMAL_PLACES = Decimal('0.00000001')
CONFIRMATIONS_NEEDED = getattr(settings, 'BITCOIN_CONFIRMATIONS_NEEDED', 3)
MULTISIG_THRESHOLD = getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2)
MULTISIG_PARTICIPANTS = getattr(settings, 'MULTISIG_TOTAL_PARTICIPANTS', 3)

# Taproot/PSBTv2 Weight/vByte Estimates (approximations, refined in v2.1.0)
# These are FALLBACKS if testmempoolaccept/analyzepsbt fail.
ESTIMATED_P2TR_OUTPUT_VBYTES = Decimal('43.0')
# Approx 2-of-3 Taproot Script Path Spend Input:
# Base(10.5) + Txid(32) + Vout(4) + Sequence(4) + WitnessItemsCount(1)
# + Sig1(64/4=16) + Sig2(64/4=16) + Script(OP_2 <xkey1> <xkey2> <xkey3> OP_3 OP_CMS ~ 1+32+32+32+1+1 = 100 bytes / 4 = 25)
# + ControlBlock(33 + 32*depth(1) = 65 bytes / 4 = 16.25)
# Total ~= 10.5 + 32 + 4 + 4 + 1 + 16 + 16 + 25 + 16.25 = 124.75 vBytes --> Use 125 as estimate
ESTIMATED_TAPROOT_INPUT_VBYTES = Decimal('125.0') # Refined v2.1.0
ESTIMATED_P2WPKH_OUTPUT_VBYTES = Decimal('31.0')
ESTIMATED_P2WSH_OUTPUT_VBYTES = Decimal('43.0') # Same as P2TR
ESTIMATED_P2PKH_OUTPUT_VBYTES = Decimal('34.0')
ESTIMATED_P2SH_OUTPUT_VBYTES = Decimal('32.0')
ESTIMATED_BASE_TX_VBYTES = Decimal('10.5') # Basic non-witness tx overhead

DUST_THRESHOLD_SATS = 546 # Standard dust threshold

# --- Configuration ---
# (Configuration remains the same)
RPC_URL = getattr(settings, 'BITCOIN_RPC_URL', None)
RPC_USER = getattr(settings, 'BITCOIN_RPC_USER', None)
RPC_PASSWORD = getattr(settings, 'BITCOIN_RPC_PASSWORD', None)
NETWORK = getattr(settings, 'BITCOIN_NETWORK', 'mainnet')
MARKET_BTC_KEY_NAME_IN_VAULT = getattr(settings, 'MARKET_BTC_VAULT_KEY_NAME', "market_btc_multisig_key")
IMPORTADDRESS_RESCAN = getattr(settings, 'BITCOIN_IMPORTADDRESS_RESCAN', False) # Default to no rescan for performance

# --- Logging ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Conversion Utilities ---
# (Conversion utilities remain the same)

def satoshis_to_btc(sats: Optional[Union[int, Decimal]]) -> Decimal:
    """Converts satoshis (int or Decimal) to a Decimal BTC value."""
    if sats is None:
        return Decimal('0.0').quantize(BTC_DECIMAL_PLACES)
    # FIX v2.1.2 (#1): Raise ValueError for invalid types to match test
    if not isinstance(sats, (int, Decimal)):
        # Previous: TypeError
        raise ValueError(f"Invalid input type for satoshis_to_btc: Expected int or Decimal, got {type(sats).__name__}.")
    try:
        sats_decimal = Decimal(sats)
    except InvalidOperation: # Catch Decimal conversion errors specifically
        raise ValueError(f"Invalid value for satoshis_to_btc: Cannot convert '{sats}' to Decimal.")

    if sats_decimal != sats_decimal.to_integral_value():
        raise ValueError(f"Invalid amount: Satoshis must be whole numbers, got {sats_decimal}.")
    if sats_decimal < 0:
        raise ValueError(f"Invalid amount: Satoshis cannot be negative ({sats_decimal}).")

    try:
        return (sats_decimal / SATOSHIS_PER_BTC).quantize(BTC_DECIMAL_PLACES, rounding=ROUND_DOWN)
    except InvalidOperation as e:
        logger.error(f"Unexpected Decimal InvalidOperation during satoshis_to_btc conversion: {e}. Input sats: {sats}")
        raise ValueError(f"Decimal calculation error for satoshis amount '{sats}'.") from e


def btc_to_satoshis(amount_btc: Union[Decimal, str, float, int]) -> int:
    """Converts a BTC amount (Decimal, str, float, int) to satoshis (int)."""
    if amount_btc is None:
        return 0
    try:
        local_amount_btc = Decimal(str(amount_btc))
    except (InvalidOperation, TypeError) as e:
        logger.error(f"Invalid type or value for btc_to_satoshis: {amount_btc}. Error: {e}")
        raise ValueError(f"Invalid amount format or type '{amount_btc}' for Satoshi conversion.") from e

    if local_amount_btc < 0:
        raise ValueError("BTC amount cannot be negative")

    try:
        sats = (local_amount_btc * SATOSHIS_PER_BTC).to_integral_value(rounding=ROUND_DOWN)
        if sats < 0:
             raise ValueError("Calculated satoshis resulted in a negative value") # Should not happen
        return int(sats)
    except InvalidOperation as e:
        logger.error(f"Decimal operation error during btc_to_satoshis calculation for {local_amount_btc}: {e}")
        raise ValueError(f"Calculation error converting BTC amount '{local_amount_btc}' to Satoshis.") from e
    except Exception as e:
        logger.exception(f"Unexpected error in btc_to_satoshis with input {amount_btc} (Decimal: {local_amount_btc}): {e}")
        raise ValueError(f"Unexpected error converting amount '{amount_btc}' to Satoshis.") from e


# --- RPC Proxy Instance ---
# (_get_rpc_proxy remains the same)
_rpc_proxy_instance: Optional['BitcoinProxy'] = None
_rpc_proxy_lock = threading.Lock()

def _get_rpc_proxy() -> Optional['BitcoinProxy']:
    """Gets a cached instance of the Bitcoin RPC proxy, reconnecting if necessary."""
    global _rpc_proxy_instance
    if not BITCOINLIB_AVAILABLE or not _BITCOINLIB_NETWORK_SET:
        logger.critical("Bitcoinlib unavailable or network not set. Cannot create RPC proxy.")
        return None

    proxy_instance = _rpc_proxy_instance
    if proxy_instance:
        try:
            proxy_instance.getnetworkinfo() # type: ignore # Assume method exists
            return proxy_instance
        except Exception as conn_e:
            logger.warning(f"Bitcoin RPC connection check failed ({conn_e}). Will attempt reconnect.")
            _rpc_proxy_instance = None

    with _rpc_proxy_lock:
        proxy_instance = _rpc_proxy_instance # Re-check after acquiring lock
        if proxy_instance:
            try:
                proxy_instance.getnetworkinfo() # type: ignore
                return proxy_instance
            except Exception as conn_e:
                logger.warning(f"Bitcoin RPC connection check failed again inside lock ({conn_e}). Forcing reconnect.")
                _rpc_proxy_instance = None

        if not all([RPC_URL, RPC_USER, RPC_PASSWORD]):
            logger.critical("Bitcoin RPC credentials or URL missing in settings.")
            return None

        try:
            if "://" not in RPC_URL:
                service_url = f"http://{RPC_USER}:{RPC_PASSWORD}@{RPC_URL.split('://')[-1]}"
                logger.warning(f"Assuming HTTP for RPC URL: {RPC_URL}.")
            else:
                protocol, host_port = RPC_URL.split("://", 1)
                service_url = f"{protocol}://{RPC_USER}:{RPC_PASSWORD}@{host_port}"

            # Use the real Proxy class now
            proxy_instance_local: 'BitcoinProxy' = Proxy(service_url=service_url, timeout=120) # type: ignore # Real class used here
            network_info = proxy_instance_local.getnetworkinfo()
            node_version = network_info.get('version', 'N/A')
            logger.info(f"Bitcoin RPC Proxy initialized. Connected to: {RPC_URL}. Node Version: {node_version}")
            _rpc_proxy_instance = proxy_instance_local
            return proxy_instance_local

        except Exception as e:
            logger.exception(f"CRITICAL: Failed to initialize Bitcoin RPC Proxy to {RPC_URL}: {e}")
            _rpc_proxy_instance = None
            return None

# --- _make_rpc_request remains the same ---
def _make_rpc_request(method: str, *args) -> Optional[Any]:
    """Makes an RPC request using the cached proxy."""
    proxy = _get_rpc_proxy()
    if not proxy:
        logger.error(f"Cannot call Bitcoin RPC method '{method}': Proxy unavailable.")
        return None
    try:
        # Use proxy.call directly which exists on the real Proxy object
        result = proxy.call(method, *args)
        # logger.debug(f"RPC call {method}({args}) successful. Result: {str(result)[:200]}...")
        return result
    except JSONRPCError as rpc_err: # Use specific library exception
        error_details = getattr(rpc_err, 'error', {})
        if isinstance(error_details, dict):
            code = error_details.get('code')
            msg = error_details.get('message', str(rpc_err))
        else:
            code = 'N/A'
            msg = str(rpc_err)
        logger.error(f"Bitcoin RPC Error - Method: {method}, Args: {args}, Code: {code}, Msg: {msg}")
        return None
    except (ConnectionError, TimeoutError, OSError) as conn_err: # Catch specific connection errors
        logger.error(f"Bitcoin RPC Connection/OS Error - Method: {method}, Args: {args}, Error: {conn_err}")
        _rpc_proxy_instance = None # Clear proxy on connection error
        return None
    except AttributeError:
        # This might happen if the method doesn't exist on the node/proxy
        logger.error(f"Bitcoin RPC Error - Method '{method}' not found on proxy object or node.")
        return None
    except Exception as e:
        logger.exception(f"Bitcoin RPC Exception - Method: {method}, Args: {args}, Error: {e}")
        return None

# --- Secure Key Retrieval ---
_market_btc_private_key_cache: Optional['BitcoinCKey'] = None
_market_key_lock = threading.Lock()

def _get_market_btc_private_key() -> Optional['BitcoinCKey']:
    """Securely retrieves and caches the market's BTC private key from Vault."""
    global _market_btc_private_key_cache
    log_prefix = "[get_market_btc_key]" # DEBUG v2.1.2

    # Check library availability first
    if not BITCOINLIB_AVAILABLE:
        logger.error(f"{log_prefix} Bitcoinlib unavailable, cannot process private keys.")
        return None
    # logger.debug(f"{log_prefix} Bitcoinlib is available.") # DEBUG v2.1.2 - Commented out for brevity

    local_cache_copy = _market_btc_private_key_cache
    if local_cache_copy:
        # logger.debug(f"{log_prefix} Returning cached market BTC key.") # DEBUG v2.1.2 - Commented out for brevity
        return local_cache_copy

    # Acquire lock before further checks/operations
    logger.debug(f"{log_prefix} Cache miss, acquiring lock...") # DEBUG v2.1.2
    with _market_key_lock:
        logger.debug(f"{log_prefix} Lock acquired.") # DEBUG v2.1.2
        # Re-check cache inside lock
        if _market_btc_private_key_cache:
            logger.debug(f"{log_prefix} Returning cached market BTC key (checked inside lock).")
            return _market_btc_private_key_cache

        logger.debug(f"{log_prefix} Cache still empty, proceeding to fetch.") # DEBUG v2.1.2
        # Check vault availability
        if not VAULT_AVAILABLE or get_crypto_secret_from_vault is None:
            logger.critical(f"{log_prefix} Vault integration unavailable. Cannot fetch market BTC key.")
            return None
        # logger.debug(f"{log_prefix} Vault is available.") # DEBUG v2.1.2 - Commented out for brevity

        wif_key: Optional[str] = None
        private_key_obj: Optional['BitcoinCKey'] = None # Define before try
        try:
            logger.info(f"{log_prefix} Fetching market BTC key '{MARKET_BTC_KEY_NAME_IN_VAULT}' from Vault...")
            # Ensure the mock/real function is called if vault is available
            wif_key = get_crypto_secret_from_vault(
                key_type='bitcoin',
                key_name=MARKET_BTC_KEY_NAME_IN_VAULT,
                key_field='private_key_wif',
                raise_error=True # Raise error if vault call fails
            )
            # logger.debug(f"{log_prefix} Vault call returned: {'<string>' if wif_key else 'None'}") # DEBUG v2.1.2

            if not wif_key or not isinstance(wif_key, str):
                logger.critical(f"{log_prefix} Vault returned invalid data for key '{MARKET_BTC_KEY_NAME_IN_VAULT}': {wif_key}")
                return None

            # Decode WIF and create CKey object
            # logger.debug(f"{log_prefix} Attempting to decode WIF and create CKey...") # DEBUG v2.1.2
            bitcoin_secret = CBitcoinSecret(wif_key) # type: ignore # Real class used here
            # logger.debug(f"{log_prefix} CBitcoinSecret created.") # DEBUG v2.1.2
            # Ensure compressed pubkey is generated, important for Taproot/Segwit
            private_key_obj = CKey(bitcoin_secret.secret, compressed=True) # type: ignore
            # logger.debug(f"{log_prefix} CKey object created successfully.") # DEBUG v2.1.2

            # Optional pubkey verification
            expected_pubkey_hex = getattr(settings, 'MARKET_BTC_PUBKEY_HEX', None)
            if expected_pubkey_hex:
                # logger.debug(f"{log_prefix} Verifying key against settings.MARKET_BTC_PUBKEY_HEX...") # DEBUG v2.1.2
                derived_pubkey_hex = private_key_obj.pub.hex()

                # <<< START DEBUG v2.1.3 (#1) >>>
                logger.debug(f"{log_prefix} PubKey Check: Derived='{derived_pubkey_hex}', Expected='{expected_pubkey_hex}'")
                # <<< END DEBUG v2.1.3 (#1) >>>

                if derived_pubkey_hex != expected_pubkey_hex:
                    # <<< START DEBUG v2.1.3 (#1) >>>
                    logger.debug(f"{log_prefix} PubKey Mismatch DETECTED. Returning None.")
                    # <<< END DEBUG v2.1.3 (#1) >>>
                    security_logger.critical(f"{log_prefix} CRITICAL SECURITY: Market BTC key from Vault (PubKey: {derived_pubkey_hex[:10]}...) does NOT match settings.MARKET_BTC_PUBKEY_HEX ({expected_pubkey_hex[:10]}...)!")
                    return None # Return None on mismatch
                else:
                    logger.info(f"{log_prefix} Market BTC key pubkey matches settings ({expected_pubkey_hex[:10]}...).")
            else:
                logger.debug(f"{log_prefix} No settings.MARKET_BTC_PUBKEY_HEX found for verification.") # DEBUG v2.1.2

            # Cache the successfully created key object
            _market_btc_private_key_cache = private_key_obj
            pubkey_hex = _market_btc_private_key_cache.pub.hex()
            logger.info(f"{log_prefix} Successfully loaded and cached market BTC key from Vault (PubKey starts with: {pubkey_hex[:10]}...).")
            return _market_btc_private_key_cache # Return the newly cached object

        except (CBitcoinSecretError, ValueError) as wif_err:
            security_logger.critical(f"{log_prefix} CRITICAL: Invalid format or error decoding Market BTC key WIF ('{MARKET_BTC_KEY_NAME_IN_VAULT}') from Vault: {wif_err}", exc_info=False)
            return None
        except Exception as key_err:
            logger.error(f"{log_prefix} ERROR processing Market BTC key ('{MARKET_BTC_KEY_NAME_IN_VAULT}'): {key_err}", exc_info=True)
            return None
        finally:
             logger.debug(f"{log_prefix} Releasing lock.") # DEBUG v2.1.2
            
# --- Core Service Functions ---
# (get_network, get_blockchain_info, generate_new_address, estimate_fee_rate, _get_scriptpubkey_for_address, import_btc_address_to_node remain the same)

def get_network() -> str:
    """Returns the configured Bitcoin network name."""
    return NETWORK

def get_blockchain_info() -> Optional[Dict[str, Any]]:
    """Gets blockchain info from the RPC node."""
    return _make_rpc_request("getblockchaininfo")

def generate_new_address() -> Optional[str]:
    """Generates a new Bech32m (P2TR) address via RPC node wallet."""
    result = _make_rpc_request("getnewaddress", "", "bech32m")
    if result and isinstance(result, str):
        logger.info(f"Generated new node wallet Bech32m address: {result}")
        return result
    logger.error("Failed to generate new Bech32m Bitcoin address via RPC.")
    return None

def estimate_fee_rate(conf_target: int = 6) -> Optional[Decimal]:
    """Estimates the fee rate (BTC per kB) for a given confirmation target."""
    # (Function remains unchanged, relies on _make_rpc_request)
    result = _make_rpc_request("estimatesmartfee", conf_target, "CONSERVATIVE")

    if result and isinstance(result, dict) and 'feerate' in result:
        try:
            fee_rate_btc_kb = Decimal(str(result['feerate']))
            if fee_rate_btc_kb <= 0:
                logger.warning(f"Node returned non-positive fee rate ({fee_rate_btc_kb}), using fallback.")
                raise ValueError("Non-positive fee rate")
            logger.info(f"Estimated fee rate for {conf_target} blocks: {fee_rate_btc_kb:.8f} BTC/kB")
            return fee_rate_btc_kb
        except (InvalidOperation, ValueError) as dec_err:
            logger.error(f"Invalid fee rate value received from node: {result.get('feerate')}. Error: {dec_err}. Falling back.")
    elif result and 'errors' in result:
        logger.error(f"Fee estimation error reported by node: {result['errors']}. Falling back.")
    else:
        if result is None: logger.error("Failed to estimate fee rate: RPC request failed or returned None. Falling back.")
        else: logger.error(f"Failed to estimate fee rate: Unexpected RPC result format: {result}. Falling back.")

    # Fallback logic
    try:
        min_feerate_sats_vb_str = getattr(settings, 'BITCOIN_MIN_FEERATE_SATS_VBYTE', '1.0')
        min_feerate_sats_vb = Decimal(min_feerate_sats_vb_str)
        if min_feerate_sats_vb <= 0: min_feerate_sats_vb = Decimal('1.0')
        min_feerate_btc_kb = (min_feerate_sats_vb / SATOSHIS_PER_BTC) * 1000
        logger.warning(f"Using fallback minimum fee rate from settings: {min_feerate_btc_kb:.8f} BTC/kB ({min_feerate_sats_vb} sats/vB)")
        return min_feerate_btc_kb.quantize(Decimal('0.00000001'))
    except (ValueError, InvalidOperation, TypeError) as setting_err:
        logger.error(f"Error processing BITCOIN_MIN_FEERATE_SATS_VBYTE setting ('{min_feerate_sats_vb_str}'): {setting_err}. Using hardcoded fallback 1 sat/vB.")
        fallback_btc_kb = (Decimal('1.0') / SATOSHIS_PER_BTC) * 1000
        logger.warning(f"Using hardcoded fallback minimum fee rate: {fallback_btc_kb:.8f} BTC/kB")
        return fallback_btc_kb.quantize(Decimal('0.00000001'))

# --- Helper Functions ---
def _get_scriptpubkey_for_address(address: str) -> Optional['BitcoinCScript']:
    """Converts a Bitcoin address string to its CScript scriptPubKey."""
    if not BITCOINLIB_AVAILABLE:
        logger.error("Bitcoinlib unavailable, cannot convert address to scriptPubKey.")
        return None
    try:
        addr_obj: 'BitcoinCBitcoinAddress' = CBitcoinAddress(address) # type: ignore
        return addr_obj.to_scriptPubKey()
    except BitcoinAddressError as e:
        logger.error(f"Invalid Bitcoin address format '{address}': {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error converting address '{address}' to scriptPubKey: {e}")
        return None

def import_btc_address_to_node(address: str, label: str = "", rescan: bool = IMPORTADDRESS_RESCAN) -> bool:
    """
    Imports a Bitcoin address into the node's wallet using RPC 'importaddress'.
    Returns True on success, False on failure.
    """
    log_prefix = f"[import_btc_address(Addr:{address[:10]}...)]"
    logger.info(f"{log_prefix} Attempting to import address into node wallet (Rescan={rescan})...")

    # Get scriptPubKey first to potentially avoid importing invalid addresses
    scriptPubKey_obj = _get_scriptpubkey_for_address(address)
    if not scriptPubKey_obj:
        logger.error(f"{log_prefix} Cannot import invalid address: {address}")
        return False
    scriptPubKey_hex = scriptPubKey_obj.hex()

    # Import the address (using scriptPubKey is sometimes more reliable for non-legacy)
    # importaddress <address> [label] [rescan] [p2sh] -- Use address directly for simplicity
    result = _make_rpc_request("importaddress", address, label, rescan)

    # importaddress returns None on success. Check for errors in logs if needed.
    if result is None:
        logger.info(f"{log_prefix} RPC 'importaddress' executed for {address}. Assuming success (result is None).")
        # Optionally verify import with getaddressinfo again
        try:
            addr_info = _make_rpc_request("getaddressinfo", address)
            if addr_info and (addr_info.get('iswatchonly') or addr_info.get('ismine')):
                logger.info(f"{log_prefix} Confirmed address {address} is now watched by node.")
                return True
            else:
                logger.warning(f"{log_prefix} Import RPC seemed successful, but getaddressinfo doesn't show address as watched. Info: {addr_info}")
                return False # Indicate potential issue
        except Exception as e:
            logger.warning(f"{log_prefix} Could not confirm import via getaddressinfo after RPC call: {e}")
            return True # Assume success based on RPC result being None
    else:
        # Should only happen if RPC itself failed (_make_rpc_request handled JSONRPCError)
        logger.error(f"{log_prefix} RPC call 'importaddress' failed unexpectedly (expected None on success). Result: {result}")
        return False


# --- Taproot Multi-Sig Implementation ---

def create_btc_multisig_address(pubkeys_hex: List[str], threshold: int = MULTISIG_THRESHOLD) -> Optional[Dict[str, str]]:
    """
    Creates a P2TR (Taproot) 2-of-3 multisig address using a script path spend.
    Uses real python-bitcoinlib objects.
    """
    log_prefix = "[create_btc_taproot_msig_addr]"
    logger.info(f"{log_prefix} Attempting to create {threshold}-of-{len(pubkeys_hex)} P2TR address.")

    if not BITCOINLIB_AVAILABLE:
        logger.error(f"{log_prefix} Bitcoinlib unavailable.")
        return None
    logger.debug(f"{log_prefix} Bitcoinlib available, proceeding.") # DEBUG v2.1.2

    # Validate Inputs (logic remains the same)
    num_participants = len(pubkeys_hex)
    total_expected = MULTISIG_PARTICIPANTS # Should be 3 for 2-of-3
    if num_participants != total_expected:
        logger.error(f"{log_prefix} Incorrect number of public keys provided. Expected {total_expected}, got {num_participants}.")
        return None
    if threshold != 2: # Enforce 2-of-3
        logger.error(f"{log_prefix} Invalid threshold {threshold}. This function currently supports only 2-of-3.")
        return None
    if not isinstance(pubkeys_hex, list) or not all(isinstance(pk, str) for pk in pubkeys_hex):
        logger.error(f"{log_prefix} pubkeys_hex must be a list of strings.")
        return None
    logger.debug(f"{log_prefix} Input validation passed.") # DEBUG v2.1.2

    try:
        # Convert hex pubkeys to CPubKey objects
        logger.debug(f"{log_prefix} Converting pubkey hex strings to CPubKey objects...") # DEBUG v2.1.2
        pubkeys: List['BitcoinCPubKey'] = []
        for i, pk_hex in enumerate(pubkeys_hex):
            try:
                logger.debug(f"{log_prefix} Processing key {i+1}: {pk_hex[:10]}...") # DEBUG v2.1.2
                pubkey_bytes = bytes.fromhex(pk_hex)
                pubkey_obj: 'BitcoinCPubKey' = CPubKey(pubkey_bytes) # type: ignore # Use real class
                if not pubkey_obj.is_compressed:
                    raise ValueError(f"Non-compressed public key provided: {pk_hex}")
                pubkeys.append(pubkey_obj)
            except (ValueError, TypeError, binascii.Error) as key_err:
                logger.error(f"{log_prefix} Invalid public key hex string '{pk_hex}': {key_err}", exc_info=True)
                return None
        logger.debug(f"{log_prefix} Successfully converted {len(pubkeys)} pubkeys.") # DEBUG v2.1.2

        # --- Taproot Construction using Real Objects ---
        logger.debug(f"{log_prefix} Starting Taproot construction...") # DEBUG v2.1.2
        internal_pubkey_full: 'BitcoinCPubKey' = pubkeys[0]
        internal_pubkey_xonly_bytes: bytes = x(internal_pubkey_full) # type: ignore
        internal_pubkey_xonly_hex = internal_pubkey_xonly_bytes.hex()
        logger.debug(f"{log_prefix} Using internal key x-only: {internal_pubkey_xonly_hex}.")

        pubkeys_xonly = [x(pk) for pk in pubkeys] # type: ignore
        script_items = [OP_N(threshold)] + pubkeys_xonly + [OP_N(num_participants), OP_CHECKMULTISIG] # type: ignore
        tap_script: 'BitcoinCScript' = CScript(script_items) # type: ignore
        tap_script_hex = tap_script.hex()
        logger.debug(f"{log_prefix} Created Tapscript: {tap_script_hex}")

        script_path = TaprootScriptPath(tap_script) # type: ignore
        logger.debug(f"{log_prefix} Created TaprootScriptPath.") # DEBUG v2.1.2

        tr_info: 'BitcoinTaprootInfo' = script_path.GetTreeInfo(internal_pubkey_full) # type: ignore
        logger.debug(f"{log_prefix} Generated TaprootInfo.") # DEBUG v2.1.2

        p2tr_address_obj: 'BitcoinP2TRAddress' = P2TRBitcoinAddress(tr_info.output_pubkey) # type: ignore
        p2tr_address_str = str(p2tr_address_obj)

        if tap_script not in tr_info.control_blocks:
            logger.error(f"{log_prefix} Control block for the Tapscript was not found in TaprootInfo.")
            return None
        control_block_bytes = tr_info.control_blocks[tap_script]
        control_block_hex = control_block_bytes.hex()
        logger.debug(f"{log_prefix} Extracted control block.") # DEBUG v2.1.2

        logger.info(f"{log_prefix} Successfully generated P2TR address: {p2tr_address_str}")

        # Return the dictionary
        result_dict = {
            "address": p2tr_address_str,
            "internal_pubkey": internal_pubkey_xonly_hex,
            "tapscript": tap_script_hex,
            "control_block": control_block_hex,
        }
        logger.debug(f"{log_prefix} Returning result dictionary.") # DEBUG v2.1.2
        return result_dict

    except (ValueError, TypeError, AttributeError, TaprootError) as e:
        logger.error(f"{log_prefix} Error during Taproot address creation: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during Taproot address creation: {e}")
        return None


# --- Implementation for P2TR Payment Scanning ---
# (scan_for_payment_confirmation remains the same)
def scan_for_payment_confirmation(payment: 'CryptoPaymentTypeHint') -> Optional[Tuple[bool, Decimal, int, Optional[str]]]:
    """
    Scans the blockchain for a confirmed payment to the given P2TR escrow address using listunspent.
    Attempts to import the address if not already watched.
    Returns (is_confirmed, amount_received_sats_decimal, confirmations, txid) or None on error.
    """
    if not isinstance(payment, CryptoPayment) or not hasattr(payment, 'id'):
        # Check if payment is the expected model type
        logger.warning(f"[scan_for_payment_conf(Pay:N/A)] Invalid payment object type: {type(payment)}")
        return None # Indicate error/invalid input

    log_prefix = f"[scan_for_payment_conf(Pay:{payment.id})]"
    logger.debug(f"{log_prefix} Starting scan for P2TR address: {payment.payment_address}")

    if not BITCOINLIB_AVAILABLE or not MODELS_AVAILABLE:
        logger.error(f"{log_prefix} Dependencies unavailable (bitcoinlib or models).")
        return None
    if payment.currency != 'BTC' or not payment.payment_address:
        logger.warning(f"{log_prefix} Invalid payment object - missing currency 'BTC' or payment_address.")
        return None

    try:
        address_to_scan = payment.payment_address
        # Ensure expected_amount_native is Decimal or convertible
        expected_amount_native_raw = payment.expected_amount_native
        if isinstance(expected_amount_native_raw, (int, float, str)):
            expected_sats_decimal = Decimal(str(expected_amount_native_raw))
        elif isinstance(expected_amount_native_raw, Decimal):
            expected_sats_decimal = expected_amount_native_raw
        else:
             logger.error(f"{log_prefix} Invalid expected_amount_native type: {type(expected_amount_native_raw)}")
             return None
        if expected_sats_decimal <= 0:
             logger.warning(f"{log_prefix} Expected amount is zero or negative ({expected_sats_decimal}). Cannot confirm payment.")
             return None # Or return (False, 0, 0, None)? None indicates error better.

        confirmations_required = payment.confirmations_needed or CONFIRMATIONS_NEEDED

        # --- Ensure Node Awareness (Import Address if Needed) ---
        label = f"Order_{payment.order_id}_Escrow" if payment.order_id else f"Payment_{payment.id}_Escrow"
        import_success = import_btc_address_to_node(address_to_scan, label=label)
        if not import_success:
             logger.warning(f"{log_prefix} Failed to import or confirm import of address {address_to_scan} into node. Scan may fail.")
             # Decide whether to proceed or return None. Proceeding might still work if already imported.

        # --- Use listunspent RPC Call ---
        logger.debug(f"{log_prefix} Calling listunspent for {address_to_scan} (Req Confs: {confirmations_required}).")
        # Using min confs = 0 includes unconfirmed UTXOs if needed for logging/tracking
        unspent_outputs = _make_rpc_request("listunspent", 0, 9999999, [address_to_scan])

        if unspent_outputs is None:
             logger.error(f"{log_prefix} RPC call listunspent failed or returned None for address {address_to_scan}.")
             # This could be a connection error or node issue.
             return None # Indicate error

        if not isinstance(unspent_outputs, list):
             logger.error(f"{log_prefix} Unexpected non-list result from listunspent: {type(unspent_outputs)}")
             return None

        if not unspent_outputs:
             logger.debug(f"{log_prefix} No UTXOs found for {address_to_scan}.")
             return (False, Decimal('0'), 0, None) # No payment found yet

        # --- Find a Suitable UTXO ---
        best_match = None # Store the best candidate UTXO dict
        found_sufficient_unconfirmed = False

        for utxo in unspent_outputs:
             if not isinstance(utxo, dict): continue # Skip invalid entries

             try:
                 utxo_sats_decimal = Decimal(btc_to_satoshis(utxo.get('amount', 0)))
                 utxo_confs = int(utxo.get('confirmations', 0))
                 utxo_txid = utxo.get('txid')
                 utxo_vout = utxo.get('vout')

                 # Check if amount is sufficient (allow overpayment)
                 if utxo_sats_decimal >= expected_sats_decimal:
                     logger.debug(f"{log_prefix} Found candidate UTXO {utxo_txid}:{utxo_vout} ({utxo_sats_decimal} sats, {utxo_confs} confs)")
                     # Check if confirmations are sufficient
                     if utxo_confs >= confirmations_required:
                         # Found a fully confirmed, sufficient payment
                         best_match = utxo
                         logger.info(f"{log_prefix} Found confirmed matching payment: {utxo_txid}:{utxo_vout} ({utxo_sats_decimal} sats, {utxo_confs} confs)")
                         break # Stop searching once a fully confirmed match is found
                     else:
                         # Found a sufficient payment, but not enough confirmations yet
                         found_sufficient_unconfirmed = True
                         # Could store this candidate if no confirmed one is found
                         if best_match is None: # Store the first unconfirmed match as a possibility
                             best_match = utxo
                 else:
                     logger.debug(f"{log_prefix} Skipping UTXO {utxo_txid}:{utxo_vout} - insufficient amount ({utxo_sats_decimal} < {expected_sats_decimal})")

             except (ValueError, TypeError, InvalidOperation) as utxo_err:
                 logger.warning(f"{log_prefix} Error processing UTXO data: {utxo}. Error: {utxo_err}")
                 continue # Skip this UTXO

        # --- Process Result ---
        if best_match and best_match.get('confirmations', 0) >= confirmations_required:
            # Found a confirmed match
            received_sats_decimal = Decimal(btc_to_satoshis(best_match['amount']))
            confs = best_match['confirmations']
            txid = best_match.get('txid')
            logger.info(f"{log_prefix} Confirmed payment FOUND. Rcvd Sats: {received_sats_decimal}, Confs: {confs}, TXID: {txid}")
            return (True, received_sats_decimal, confs, txid)
        elif found_sufficient_unconfirmed:
            # Found sufficient amount but waiting for confirmations
            unconf_sats = Decimal(btc_to_satoshis(best_match['amount'])) if best_match else Decimal('0')
            unconf_confs = best_match.get('confirmations', 0) if best_match else 0
            unconf_txid = best_match.get('txid') if best_match else None
            logger.info(f"{log_prefix} Sufficient payment amount found ({unconf_sats} sats, TX: {unconf_txid}) but waiting for confirmations ({unconf_confs}/{confirmations_required}).")
            return (False, unconf_sats, unconf_confs, unconf_txid) # Return False, but with details of pending tx
        else:
            # No UTXO found with sufficient amount
            logger.debug(f"{log_prefix} No UTXO found with amount >= {expected_sats_decimal} sats for {address_to_scan}.")
            return (False, Decimal('0'), 0, None)

    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during payment scan: {e}")
        return None # Indicate error


# --- PSBTv2 Preparation for Taproot ---
# (prepare_btc_multisig_tx remains the same, including input validation added in 2.1.1)
def prepare_btc_multisig_tx(
    order: 'OrderModelTypeHint',
    outputs: Dict[str, int], # {destination_address: amount_sats}
    fee_rate_sats_vb_override: Optional[int] = None
) -> Optional[str]:
    """
    Prepares an unsigned PSBTv2 for spending from the order's P2TR escrow address
    using the script path. Handles multiple outputs. Uses testmempoolaccept for fee estimation.

    Args:
        order: The Order object containing Taproot details.
        outputs: Dictionary mapping destination address(es) to amount in satoshis.
        fee_rate_sats_vb_override: Optional fee rate in sats/vB to bypass estimation.

    Returns:
        Base64 encoded PSBTv2 string or None on failure.
    """
    if not hasattr(order, 'id'): # Basic check for valid Order object
        logger.error("[prepare_btc_taproot_psbt(Ord:N/A)] Invalid Order object received.")
        return None
    log_prefix = f"[prepare_btc_taproot_psbt(Ord:{order.id})]"

    # FIX v2.1.1 (#7): Add input type validation for outputs
    if not isinstance(outputs, dict):
        logger.error(f"{log_prefix} Invalid 'outputs' argument: Expected a dictionary, got {type(outputs).__name__}.")
        # Raise error as this indicates a programming mistake in the caller
        raise TypeError(f"Invalid 'outputs' argument: Expected a dictionary, got {type(outputs).__name__}.")
    if not outputs:
         logger.error(f"{log_prefix} Invalid 'outputs' dictionary provided (empty).")
         return None # Cannot create tx with no outputs

    output_desc = ", ".join([f"{addr[:10]}...:{sats}sats" for addr, sats in outputs.items()])
    logger.info(f"{log_prefix} Preparing PSBTv2 for output(s): {output_desc}")

    if not BITCOINLIB_AVAILABLE or not MODELS_AVAILABLE:
        logger.error(f"{log_prefix} Dependencies unavailable.")
        return None

    # --- Validate Inputs & Extract Order Data ---
    try:
        # Validate output amounts and addresses
        output_details: List[Tuple[str, int, 'BitcoinCScript', Decimal]] = [] # (addr, sats, scriptPubKey, estimated_vsize)
        total_output_sats = 0
        total_output_vsize_estimate = Decimal('0.0')

        for address, amount_sats in outputs.items():
            if not isinstance(amount_sats, int) or amount_sats <= DUST_THRESHOLD_SATS:
                raise ValueError(f"Invalid or dust amount_sats ({amount_sats}) for address {address}")
            if not isinstance(address, str):
                raise ValueError("Output address must be a string.")

            # Validate address and get scriptPubKey/estimated size
            try:
                dest_addr_obj: 'BitcoinCBitcoinAddress' = CBitcoinAddress(address) # type: ignore
                dest_scriptPubKey = dest_addr_obj.to_scriptPubKey()
                # Estimate vsize based on address type (use constants as fallback)
                if isinstance(dest_addr_obj, P2TRBitcoinAddress): dest_output_vsize = ESTIMATED_P2TR_OUTPUT_VBYTES
                elif isinstance(dest_addr_obj, bitcoin.wallet.P2WPKHBitcoinAddress): dest_output_vsize = ESTIMATED_P2WPKH_OUTPUT_VBYTES
                elif isinstance(dest_addr_obj, bitcoin.wallet.P2WSHBitcoinAddress): dest_output_vsize = ESTIMATED_P2WSH_OUTPUT_VBYTES
                elif isinstance(dest_addr_obj, bitcoin.wallet.P2PKHBitcoinAddress): dest_output_vsize = ESTIMATED_P2PKH_OUTPUT_VBYTES
                elif isinstance(dest_addr_obj, bitcoin.wallet.P2SHBitcoinAddress): dest_output_vsize = ESTIMATED_P2SH_OUTPUT_VBYTES
                else:
                    logger.warning(f"{log_prefix} Unknown destination address type: {type(dest_addr_obj)}. Using default estimate.")
                    dest_output_vsize = ESTIMATED_P2WPKH_OUTPUT_VBYTES # Default fallback
                logger.debug(f"{log_prefix} Dest Addr: {address}, Sats: {amount_sats}, Est VSize: {dest_output_vsize}")
                output_details.append((address, amount_sats, dest_scriptPubKey, dest_output_vsize))
                total_output_sats += amount_sats
                total_output_vsize_estimate += dest_output_vsize
            except BitcoinAddressError as addr_err:
                raise ValueError(f"Invalid destination_address: {address} ({addr_err})") from addr_err

        # Extract Taproot details from Order
        escrow_address = getattr(order, 'btc_escrow_address', None)
        internal_pubkey_hex = getattr(order, 'btc_internal_pubkey', None)
        tap_script_hex = getattr(order, 'btc_tapscript', None)
        control_block_hex = getattr(order, 'btc_control_block', None)

        if not all([escrow_address, internal_pubkey_hex, tap_script_hex, control_block_hex]):
            missing = [k for k, v in {'escrow_addr': escrow_address, 'internal_pk': internal_pubkey_hex, 'script': tap_script_hex, 'ctrl_block': control_block_hex}.items() if not v]
            raise ValueError(f"Order object missing required Taproot details: {', '.join(missing)}")

        # Decode necessary hex data
        internal_pubkey_bytes = bytes.fromhex(internal_pubkey_hex)
        tap_script: 'BitcoinCScript' = CScript(bytes.fromhex(tap_script_hex)) # type: ignore
        control_block_bytes = bytes.fromhex(control_block_hex)

    except (ValueError, TypeError, AttributeError, binascii.Error) as e:
        logger.error(f"{log_prefix} Invalid input parameters or missing/invalid order/output details: {e}")
        return None
    except Exception as e:
        logger.error(f"{log_prefix} Error processing initial details: {e}", exc_info=True)
        return None

    # --- RPC Calls & Transaction Building ---
    # (Rest of the function logic remains the same)
    try:
        # --- Fee Rate Estimation ---
        fee_rate_sats_vb: Optional[int] = None
        if fee_rate_sats_vb_override is not None:
            if isinstance(fee_rate_sats_vb_override, int) and fee_rate_sats_vb_override > 0:
                fee_rate_sats_vb = fee_rate_sats_vb_override
                logger.info(f"{log_prefix} Using provided fee rate override: {fee_rate_sats_vb} sats/vB")
            else:
                logger.warning(f"{log_prefix} Invalid fee_rate_sats_vb_override ({fee_rate_sats_vb_override}). Estimating instead.")
                fee_rate_sats_vb_override = None # Fall through to estimation

        if fee_rate_sats_vb is None:
            logger.debug(f"{log_prefix} Estimating fee rate...")
            fee_rate_btc_kb = estimate_fee_rate()
            if fee_rate_btc_kb is None:
                raise ValueError("Failed to estimate fee rate via estimatesmartfee and no override provided.")
            # Convert BTC/kB to sats/vByte: (BTC/kB) * (1e8 sats/BTC) / (1000 B/kB) # vByte != B, but close enough for rate
            fee_rate_sats_vb = int((fee_rate_btc_kb * SATOSHIS_PER_BTC) / 1000)
            if fee_rate_sats_vb <= 0: fee_rate_sats_vb = 1 # Ensure minimum 1 sat/vB
            logger.info(f"{log_prefix} Estimated fee rate via estimatesmartfee: {fee_rate_sats_vb} sats/vB")

        # --- Find UTXOs ---
        logger.debug(f"{log_prefix} Listing UTXOs for address: {escrow_address}")
        unspent_outputs = _make_rpc_request("listunspent", 1, 9999999, [escrow_address])
        if unspent_outputs is None: raise ConnectionError(f"RPC listunspent failed for {escrow_address}.")
        if not isinstance(unspent_outputs, list): raise TypeError(f"Unexpected listunspent result type: {type(unspent_outputs)}")
        if not unspent_outputs:
            logger.warning(f"{log_prefix} No spendable UTXOs found for escrow address {escrow_address}. Cannot create transaction.")
            return None
        logger.info(f"{log_prefix} Found {len(unspent_outputs)} UTXO(s) for {escrow_address}.")

        # --- Coin Selection ---
        selected_utxos = []
        total_input_sats = 0
        sorted_utxos = sorted(unspent_outputs, key=lambda u: btc_to_satoshis(u.get('amount', 0)), reverse=True)

        required_sats_estimate = total_output_sats # Start with just output amount
        estimated_vsize_for_fee_calc = Decimal('0.0') # Calculate vsize iteratively

        for utxo in sorted_utxos:
            if not isinstance(utxo, dict): continue

            utxo_sats = btc_to_satoshis(utxo['amount'])
            if utxo_sats <= 0: continue # Skip zero/negative value UTXOs

            # Add UTXO to selection
            selected_utxos.append(utxo)
            total_input_sats += utxo_sats

            # Update estimated vsize for fee calculation
            num_inputs = len(selected_utxos)
            estimated_vsize_for_fee_calc = (
                ESTIMATED_BASE_TX_VBYTES
                + (num_inputs * ESTIMATED_TAPROOT_INPUT_VBYTES)
                + total_output_vsize_estimate # Pre-calculated sum of destination outputs
                + ESTIMATED_P2TR_OUTPUT_VBYTES # Assume P2TR change output for now
            )
            estimated_fee = int(estimated_vsize_for_fee_calc * fee_rate_sats_vb)
            required_sats_estimate = total_output_sats + estimated_fee

            logger.debug(
                f"{log_prefix} Selecting UTXO: {utxo.get('txid','?')[:8]}...:{utxo.get('vout','?')} ({utxo_sats} sats). "
                f"Cumulative Input: {total_input_sats} sats. Required Est: ~{required_sats_estimate} sats. Est VSize: {estimated_vsize_for_fee_calc:.1f}"
            )
            # Check if we have enough input value
            if total_input_sats >= required_sats_estimate:
                logger.info(f"{log_prefix} Selected {len(selected_utxos)} UTXO(s) totaling {total_input_sats} sats.")
                break # Stop selection
        else:
            # Loop finished without finding enough funds
            logger.error(f"{log_prefix} Insufficient funds. Found {total_input_sats} sats, need ~{required_sats_estimate} sats.")
            return None

        # --- Refined Fee Estimation using testmempoolaccept (v2.1.0) ---
        final_fee = estimated_fee # Use previous estimate as fallback
        try:
            logger.debug(f"{log_prefix} Attempting fee estimation via testmempoolaccept...")
            # 1. Build the preliminary transaction
            prelim_tx: 'BitcoinCMutableTransaction' = CMutableTransaction() # type: ignore
            prelim_tx.nVersion = 2
            prelim_tx.nLockTime = 0
            witnesses = [] # Store dummy witnesses

            # Add inputs
            for utxo in selected_utxos:
                txid_bytes = lx(utxo['txid']) # type: ignore
                vout_index = utxo['vout']
                prelim_tx.vin.append(CTxIn(COutPoint(txid_bytes, vout_index))) # type: ignore
                dummy_sig = b'\x00' * 64
                dummy_script_bytes = tap_script.serialize()
                dummy_witness = [dummy_sig, dummy_sig, dummy_script_bytes, control_block_bytes]
                witnesses.append(dummy_witness)

            # Add outputs
            change_output_required = False
            change_sats = total_input_sats - total_output_sats - estimated_fee # Initial change estimate
            if change_sats > DUST_THRESHOLD_SATS:
                change_output_required = True

            for addr, sats, script_pk, _ in output_details:
                prelim_tx.vout.append(CTxOut(sats, script_pk)) # type: ignore
            if change_output_required:
                change_addr_obj: 'BitcoinCBitcoinAddress' = CBitcoinAddress(escrow_address) # type: ignore
                change_scriptPubKey = change_addr_obj.to_scriptPubKey()
                prelim_tx.vout.append(CTxOut(change_sats, change_scriptPubKey)) # type: ignore

            # Add witness data (critical for correct vsize calculation)
            prelim_tx.wit = bitcoin.core.CMutableTxWitness(witnesses) # type: ignore

            # Serialize the transaction
            raw_tx_hex = prelim_tx.serialize().hex()
            logger.debug(f"{log_prefix} Built preliminary raw TX (len:{len(raw_tx_hex)}) for testmempoolaccept.")

            # Call testmempoolaccept
            max_fee_rate_for_test = float(fee_rate_sats_vb * 1000) # Convert sats/vB to sats/kvB for RPC
            test_result = _make_rpc_request("testmempoolaccept", [raw_tx_hex], max_fee_rate_for_test)

            if test_result and isinstance(test_result, list) and len(test_result) > 0 and isinstance(test_result[0], dict):
                tx_test_info = test_result[0]
                if tx_test_info.get("allowed"):
                    actual_vsize = tx_test_info.get("vsize")
                    actual_fee_sats_btc = tx_test_info.get("fees", {}).get("base") # Fee in BTC
                    if actual_vsize and actual_fee_sats_btc is not None:
                        actual_fee_sats = btc_to_satoshis(actual_fee_sats_btc)
                        if actual_fee_sats > 0:
                            final_fee = actual_fee_sats
                            calculated_rate = final_fee / actual_vsize
                            logger.info(f"{log_prefix} testmempoolaccept SUCCEEDED. Using actual fee: {final_fee} sats (VSize: {actual_vsize}, Rate: {calculated_rate:.2f} sats/vB)")
                        else:
                             logger.warning(f"{log_prefix} testmempoolaccept succeeded but returned zero fee. Using estimate.")
                    else:
                         logger.warning(f"{log_prefix} testmempoolaccept succeeded but missing vsize/fee info. Using estimate.")
                else:
                    reject_reason = tx_test_info.get("reject-reason", "Unknown reason")
                    logger.warning(f"{log_prefix} testmempoolaccept REJECTED transaction (Fee: {estimated_fee}). Reason: {reject_reason}. Using estimated fee.")
            else:
                 logger.warning(f"{log_prefix} testmempoolaccept returned unexpected result or failed. Using estimated fee. Result: {test_result}")

        except Exception as test_err:
            logger.warning(f"{log_prefix} Error during testmempoolaccept fee estimation: {test_err}. Falling back to vByte constant estimation.", exc_info=True)
            final_fee = estimated_fee

        # --- Calculate Final Change ---
        change_sats = total_input_sats - total_output_sats - final_fee
        change_output: Optional['BitcoinCTxOut'] = None
        if change_sats > DUST_THRESHOLD_SATS:
            try:
                change_addr_obj: 'BitcoinCBitcoinAddress' = CBitcoinAddress(escrow_address) # type: ignore
                change_scriptPubKey = change_addr_obj.to_scriptPubKey()
                change_output = CTxOut(change_sats, change_scriptPubKey) # type: ignore
                logger.info(f"{log_prefix} Calculated change: {change_sats} sats to {escrow_address}. Final Fee: {final_fee} sats.")
            except BitcoinAddressError as ch_addr_err:
                logger.error(f"{log_prefix} Invalid change address (escrow address? {escrow_address}): {ch_addr_err}. Change sacrificed to fee.")
                final_fee += change_sats
                change_sats = 0
        else:
            # Change is dust or negative, add to fee
            if change_sats > 0: logger.info(f"{log_prefix} Change amount {change_sats} is dust, adding to fee.")
            final_fee += change_sats
            change_sats = 0
            logger.info(f"{log_prefix} No change output needed. Final Fee: {final_fee} sats.")

        # Final Sanity Check
        if (total_output_sats + change_sats + final_fee) != total_input_sats:
             logger.error(f"{log_prefix} SANITY CHECK FAILED: Output({total_output_sats}) + Change({change_sats}) + Fee({final_fee}) != Input({total_input_sats}).")
             raise ValueError("Transaction amount sanity check failed.")

        # --- Build Final Transaction for PSBT ---
        final_tx: 'BitcoinCMutableTransaction' = CMutableTransaction() # type: ignore
        final_tx.nVersion = 2
        final_tx.nLockTime = 0
        for utxo in selected_utxos:
            txid_bytes = lx(utxo['txid']) # type: ignore
            final_tx.vin.append(CTxIn(COutPoint(txid_bytes, utxo['vout']))) # type: ignore
        for _, sats, script_pk, _ in output_details:
            final_tx.vout.append(CTxOut(sats, script_pk)) # type: ignore
        if change_output:
            final_tx.vout.append(change_output)
        logger.debug(f"{log_prefix} Built final CMutableTransaction with {len(final_tx.vin)} inputs and {len(final_tx.vout)} outputs.")

        # --- Create and Populate PSBTv2 ---
        psbt_obj: 'BitcoinPSBT' = PSBT.from_transaction(final_tx, version=2) # type: ignore

        for i, utxo in enumerate(selected_utxos):
            if i >= len(psbt_obj.inputs): # Should not happen
                raise IndexError(f"Mismatch between selected UTXOs ({len(selected_utxos)}) and PSBT inputs ({len(psbt_obj.inputs)}).")

            psbt_input = psbt_obj.inputs[i]

            # 1. Add Witness UTXO
            utxo_amount_sats = btc_to_satoshis(utxo['amount'])
            utxo_scriptPubKey_hex = utxo.get('scriptPubKey')
            if not utxo_scriptPubKey_hex: raise ValueError(f"UTXO {utxo['txid']}:{utxo['vout']} missing scriptPubKey.")
            utxo_scriptPubKey: 'BitcoinCScript' = CScript(bytes.fromhex(utxo_scriptPubKey_hex)) # type: ignore
            witness_utxo_obj: 'BitcoinCTxOut' = CTxOut(utxo_amount_sats, utxo_scriptPubKey) # type: ignore
            psbt_input.witness_utxo = witness_utxo_obj

            # 2. Add Taproot Script Path Info
            psbt_input.tap_internal_key = internal_pubkey_bytes # x-only bytes
            psbt_input.tap_leaf_script = { control_block_bytes : (tap_script, TAPROOT_LEAF_VERSION) } # type: ignore

        logger.debug(f"{log_prefix} PSBTv2 inputs populated with witness_utxo and Taproot script path info.")

        # --- Serialize PSBT ---
        serialized_psbt = psbt_obj.serialize()
        psbt_base64 = base64.b64encode(serialized_psbt).decode('utf-8')
        logger.info(f"{log_prefix} Successfully created unsigned PSBTv2.")

        return psbt_base64

    except (ConnectionError, JSONRPCError) as rpc_err: # Use real exception
        logger.error(f"{log_prefix} RPC Error during PSBT creation: {rpc_err}", exc_info=True)
        return None
    except (PSBTParseException, base64.binascii.Error, TypeError, ValueError, AttributeError, BitcoinAddressError, TaprootError, IndexError) as lib_err: # Use real exceptions
        logger.error(f"{log_prefix} Library or Data Error during PSBT creation: {lib_err}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during PSBT creation: {e}")
        return None


# --- PSBTv2 Signing for Taproot Script Path ---
# (sign_btc_multisig_tx remains the same)
def sign_btc_multisig_tx(psbt_base64: str, private_key_wif: Optional[str] = None) -> Optional[str]:
    """
    Signs PSBTv2 Taproot inputs using the script path with the provided WIF or market key.
    Uses real python-bitcoinlib objects and improved pubkey checking.
    """
    log_prefix = "[sign_btc_taproot_psbt]"
    logger.info(f"{log_prefix} Attempting to sign PSBTv2 Taproot script path...")

    if not BITCOINLIB_AVAILABLE:
        logger.error(f"{log_prefix} Bitcoinlib unavailable.")
        return None

    # --- Get Signing Key ---
    signing_key: Optional['BitcoinCKey'] = None
    key_source = "provided WIF" if private_key_wif else "market vault"
    try:
        if private_key_wif:
            logger.debug(f"{log_prefix} Using provided WIF key.")
            secret = CBitcoinSecret(private_key_wif) # type: ignore
            signing_key = CKey(secret.secret, compressed=True) # type: ignore # Ensure key generates compressed pubkey
        else:
            logger.debug(f"{log_prefix} Using market key from Vault.")
            signing_key = _get_market_btc_private_key()

        if not signing_key:
            logger.error(f"{log_prefix} Could not obtain private key ({key_source}) for signing.")
            return None
        logger.debug(f"{log_prefix} Successfully obtained signing key from {key_source}.")

    except (CBitcoinSecretError, ValueError) as key_err: # Includes InvalidPubKeyError mapping
        logger.error(f"{log_prefix} Invalid or error processing private key WIF ({key_source}): {key_err}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error obtaining signing key ({key_source}): {e}")
        return None

    # --- Deserialize and Sign PSBTv2 ---
    try:
        if not isinstance(psbt_base64, str): raise TypeError("psbt_base64 input must be a string")
        psbt_bytes = base64.b64decode(psbt_base64)

        psbt: 'BitcoinPSBT' = PSBT(version=2) # type: ignore # Explicitly use v2
        psbt.deserialize(psbt_bytes)
        logger.debug(f"{log_prefix} PSBTv2 deserialized successfully. Found {len(psbt.inputs)} inputs.")

        # Get the signing pubkey once
        signing_pubkey: 'BitcoinCPubKey' = signing_key.pub
        signing_pubkey_bytes = signing_pubkey.to_bytes()
        signing_pubkey_xonly_bytes = x(signing_pubkey) # type: ignore

        signed_an_input = False
        for i, psbt_input in enumerate(psbt.inputs):
            # Check if this input has the necessary Taproot script info
            if psbt_input.tap_leaf_script and psbt_input.witness_utxo:
                if len(psbt_input.tap_leaf_script) != 1:
                    logger.warning(f"{log_prefix} Input {i}: Expected exactly one leaf script, found {len(psbt_input.tap_leaf_script)}. Skipping.")
                    continue

                control_block_bytes, (leaf_script, leaf_version) = next(iter(psbt_input.tap_leaf_script.items()))

                # --- v2.1.0: Improved Key Relevance Check ---
                is_key_relevant = False
                try:
                    script_ops = list(leaf_script) # Iterate over opcodes/data in the CScript
                    for item in script_ops:
                        if isinstance(item, bytes) and len(item) == 32: # Check if item is an x-only pubkey (32 bytes)
                            if item == signing_pubkey_xonly_bytes:
                                is_key_relevant = True
                                logger.debug(f"{log_prefix} Input {i}: Found matching x-only pubkey in Tapscript.")
                                break
                except Exception as parse_err:
                    logger.warning(f"{log_prefix} Input {i}: Error parsing Tapscript to check key relevance: {parse_err}. Falling back to basic check (may be inaccurate).")
                    # Fallback: check hex string (less reliable)
                    if signing_pubkey_bytes.hex() not in leaf_script.hex():
                         logger.debug(f"{log_prefix} Input {i}: Signing key's pubkey ({signing_pubkey_bytes.hex()[:10]}...) not found in leaf script via hex search. Skipping.")
                         continue
                    else: # Hex search matched, proceed with signing attempt
                         is_key_relevant = True

                if not is_key_relevant:
                     logger.debug(f"{log_prefix} Input {i}: Signing key ({signing_pubkey_xonly_bytes.hex()}) not found among required keys in Tapscript. Skipping.")
                     continue
                # --- End Key Relevance Check ---

                logger.debug(f"{log_prefix} Input {i}: Attempting Taproot script path signing...")
                try:
                    # Use sign_taproot_script_path method from real PSBT object
                    psbt.sign_taproot_script_path(
                        key=signing_key,
                        leaf_script=leaf_script,
                        control_block=control_block_bytes,
                        input_index=i
                    )
                    logger.info(f"{log_prefix} Input {i}: sign_taproot_script_path called successfully.")
                    signed_an_input = True
                except (TaprootError, ValueError, Exception) as sign_path_err: # Use real TaprootError
                    logger.error(f"{log_prefix} Input {i}: Error during sign_taproot_script_path: {sign_path_err}", exc_info=True)
                    # Continue trying other inputs
            else:
                logger.debug(f"{log_prefix} Input {i}: Skipping, missing Taproot leaf script or witness UTXO.")

        if not signed_an_input:
             logger.warning(f"{log_prefix} No suitable inputs were signed by the provided key.")

        # --- Serialize the potentially updated PSBT ---
        updated_psbt_bytes = psbt.serialize()
        updated_psbt_base64 = base64.b64encode(updated_psbt_bytes).decode('utf-8')
        logger.info(f"{log_prefix} PSBT processed (signed={signed_an_input}) and re-serialized.")

        return updated_psbt_base64

    except (PSBTParseException, base64.binascii.Error, TypeError) as parse_err: # Use real PSBTParseException
        logger.error(f"{log_prefix} Error parsing/decoding PSBT: {parse_err}", exc_info=True)
        return None
    except Exception as sign_err:
        logger.exception(f"{log_prefix} Unexpected error during PSBT signing or serialization: {sign_err}")
        return None


# --- PSBT Finalization and Broadcasting ---
# (finalize_btc_psbt and broadcast_btc_tx remain the same)
def finalize_btc_psbt(psbt_base64: str) -> Optional[str]:
    """
    Finalizes a potentially partially signed PSBTv2 using the Bitcoin node's RPC.
    Returns the hex-encoded finalized transaction, ready for broadcast.
    """
    log_prefix = "[finalize_btc_psbt]"
    logger.info(f"{log_prefix} Attempting to finalize PSBT via RPC...")

    if not BITCOINLIB_AVAILABLE:
        logger.error(f"{log_prefix} Bitcoinlib unavailable.")
        return None

    try:
        if not isinstance(psbt_base64, str): raise TypeError("psbt_base64 input must be a string")

        result = _make_rpc_request("finalizepsbt", psbt_base64)

        if result and isinstance(result, dict):
            final_tx_hex = result.get('hex')
            is_complete = result.get('complete', False)

            if is_complete and final_tx_hex:
                logger.info(f"{log_prefix} PSBT finalized successfully by node. TX Hex length: {len(final_tx_hex)}")
                return final_tx_hex
            elif final_tx_hex:
                logger.warning(f"{log_prefix} Node returned finalized hex but marked incomplete. Returning hex anyway for inspection.")
                return None
            elif is_complete:
                logger.error(f"{log_prefix} Node marked PSBT complete but did not return transaction hex.")
                return None
            else:
                logger.warning(f"{log_prefix} PSBT finalization via node returned incomplete status.")
                return None # Not complete
        elif result is None:
             logger.error(f"{log_prefix} RPC call 'finalizepsbt' failed or returned None.")
             return None
        else:
             logger.error(f"{log_prefix} Unexpected result format from 'finalizepsbt': {result}")
             return None

    except (TypeError, ValueError) as data_err:
        logger.error(f"{log_prefix} Data error: {data_err}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during PSBT finalization: {e}")
        return None

def broadcast_btc_tx(tx_hex: str) -> Optional[str]:
    """
    Broadcasts a finalized, hex-encoded Bitcoin transaction via RPC.
    Returns the transaction ID (txid) on success, None on failure.
    """
    log_prefix = "[broadcast_btc_tx]"
    logger.info(f"{log_prefix} Attempting to broadcast transaction...")

    if not BITCOINLIB_AVAILABLE:
        logger.error(f"{log_prefix} Bitcoinlib unavailable.")
        return None

    try:
        if not isinstance(tx_hex, str) or len(tx_hex) < 60: # Basic sanity check
            raise TypeError("tx_hex input must be a valid hex string")

        max_feerate_btc_kvb = getattr(settings, 'BITCOIN_BROADCAST_MAX_FEERATE_BTC_KVB', 0.1) # Default 0.1 BTC/kvB
        txid = _make_rpc_request("sendrawtransaction", tx_hex, max_feerate_btc_kvb)

        if txid and isinstance(txid, str) and len(txid) == 64:
            logger.info(f"{log_prefix} Transaction broadcast successful. TXID: {txid}")
            return txid
        elif txid is None:
            logger.error(f"{log_prefix} RPC call 'sendrawtransaction' failed or returned None.")
            return None
        else:
            logger.error(f"{log_prefix} Transaction broadcast failed. RPC Result: {txid}")
            return None

    except (TypeError, ValueError) as data_err:
        logger.error(f"{log_prefix} Data error: {data_err}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during transaction broadcast: {e}")
        return None


# --- Release Workflow Functions ---
# (prepare_btc_release_tx and finalize_and_broadcast_btc_release remain the same)
def prepare_btc_release_tx(order: 'OrderModelTypeHint', vendor_payout_amount_btc: Decimal, vendor_address: str) -> Optional[str]:
    """Prepares the unsigned PSBTv2 for a standard vendor release."""
    if not hasattr(order, 'id'): # Basic check
        logger.error("[prepare_btc_release_tx(Ord:N/A)] Invalid order object provided.")
        return None
    log_prefix = f"[prepare_btc_release_tx(Ord:{order.id})]"
    logger.info(f"{log_prefix} Preparing Taproot release PSBTv2 for {vendor_payout_amount_btc:.8f} BTC to {vendor_address[:10]}...")

    if not BITCOINLIB_AVAILABLE or not MODELS_AVAILABLE:
        logger.error(f"{log_prefix} Dependencies unavailable.")
        return None

    try:
        # Convert payout amount to satoshis
        amount_sats = btc_to_satoshis(vendor_payout_amount_btc)
        if amount_sats <= DUST_THRESHOLD_SATS:
            logger.error(f"{log_prefix} Vendor payout amount {amount_sats} sats is below or equal to dust threshold.")
            return None

        # Call the main multi-output PSBT preparation function
        outputs = {vendor_address: amount_sats}
        return prepare_btc_multisig_tx(order, outputs)

    except ValueError as e:
        logger.error(f"{log_prefix} Error preparing release tx: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error: {e}")
        return None

def finalize_and_broadcast_btc_release(order: 'OrderModelTypeHint', current_psbt_base64: str) -> Optional[str]:
    """Finalizes the signed PSBTv2 and broadcasts the release transaction."""
    if not hasattr(order, 'id'): # Basic check
        logger.error("Invalid order object provided to finalize_and_broadcast_btc_release.")
        return None
    log_prefix = f"Finalize BTC Taproot Release (Order: {order.id})"
    logger.info(f"{log_prefix}: Starting finalization and broadcast...")

    # Step 1: Finalize the PSBT
    final_tx_hex = finalize_btc_psbt(current_psbt_base64)
    if not final_tx_hex:
        logger.error(f"{log_prefix}: Finalization step failed. Aborting broadcast.")
        return None

    # Step 2: Broadcast the finalized transaction
    logger.info(f"{log_prefix}: PSBT finalized successfully. Attempting broadcast...")
    txid = broadcast_btc_tx(final_tx_hex)
    if not txid:
        logger.critical(f"{log_prefix}: BROADCAST FAILED after successful finalization! Final TX Hex: {final_tx_hex}. Manual broadcast may be needed.")
        return None

    logger.info(f"{log_prefix}: Successfully finalized and broadcasted Taproot release. TXID: {txid}")
    return txid


# --- Dispute Workflow Function (Partial Stub Implementation) ---
# (create_and_broadcast_dispute_tx remains the same)
def create_and_broadcast_dispute_tx(
    order: 'OrderModelTypeHint',
    buyer_payout_amount_btc: Optional[Decimal] = None,
    buyer_address: Optional[str] = None,
    vendor_payout_amount_btc: Optional[Decimal] = None,
    vendor_address: Optional[str] = None,
    moderator_key_info: Any = None # CRITICAL TODO: Define how moderator key is provided (WIF, Vault name, etc.)
) -> Optional[str]:
    """
    CRITICAL STUB (v2.1.0): Creates, signs (with moderator key), finalizes, and broadcasts
    a transaction spending the P2TR escrow based on dispute resolution percentages.

    Requires:
        - Implementation of moderator private key retrieval/usage.
        - Refined fee calculation for multi-output transactions (currently uses estimation).
        - Verification that moderator is one of the original 3 multi-sig participants.
    """
    if not hasattr(order, 'id'): # Basic check
        logger.error("[create_broadcast_dispute_tx(Ord:N/A)] Invalid order object provided.")
        return None
    log_prefix = f"[create_broadcast_dispute_tx(Ord:{order.id})]"
    logger.critical(f"{log_prefix} CRITICAL STUB: Needs implementation for moderator signing and refined fee calculation.")

    if not all([BITCOINLIB_AVAILABLE, MODELS_AVAILABLE]):
        logger.error(f"{log_prefix} Dependencies unavailable.")
        return None

    # --- Validate Inputs & Calculate Sats ---
    outputs_to_create: Dict[str, int] = {}
    try:
        # Buyer payout
        if buyer_payout_amount_btc is not None and buyer_payout_amount_btc > 0:
            if not buyer_address: raise ValueError("Missing buyer_address for non-zero buyer payout.")
            buyer_share_sats = btc_to_satoshis(buyer_payout_amount_btc)
            if buyer_share_sats <= DUST_THRESHOLD_SATS: raise ValueError(f"Buyer payout {buyer_share_sats} sats is dust or less.")
            if not isinstance(buyer_address, str) or len(buyer_address) < 26: raise ValueError("Invalid buyer_address format.")
            outputs_to_create[buyer_address] = buyer_share_sats

        # Vendor payout
        if vendor_payout_amount_btc is not None and vendor_payout_amount_btc > 0:
            if not vendor_address: raise ValueError("Missing vendor_address for non-zero vendor payout.")
            vendor_share_sats = btc_to_satoshis(vendor_payout_amount_btc)
            if vendor_share_sats <= DUST_THRESHOLD_SATS: raise ValueError(f"Vendor payout {vendor_share_sats} sats is dust or less.")
            if not isinstance(vendor_address, str) or len(vendor_address) < 26: raise ValueError("Invalid vendor_address format.")
            outputs_to_create[vendor_address] = vendor_share_sats

        if not outputs_to_create:
            raise ValueError("Dispute resolution requires at least one valid payout output.")

        # --- CRITICAL TODO: Process Moderator Key ---
        moderator_signing_key: Optional['BitcoinCKey'] = None
        if not moderator_key_info:
            logger.error(f"{log_prefix} Moderator key information (moderator_key_info) is required but missing.")
            return None
        else:
            # Placeholder: Implement logic to get CKey from moderator_key_info
            if isinstance(moderator_key_info, str):
                try:
                    mod_secret = CBitcoinSecret(moderator_key_info) # type: ignore
                    moderator_signing_key = CKey(mod_secret.secret, compressed=True) # type: ignore
                    logger.info(f"{log_prefix} Loaded moderator signing key (PubKey: {moderator_signing_key.pub.hex()[:10]}...).")
                except (CBitcoinSecretError, ValueError) as e:
                    logger.error(f"{log_prefix} Failed to decode moderator WIF key: {e}")
                    return None
            else:
                # Handle other ways moderator key might be provided (e.g., lookup via User object, Vault)
                logger.error(f"{log_prefix} Moderator key processing logic not fully implemented for type: {type(moderator_key_info)}")
                return None
        # --- End CRITICAL TODO ---

        # TODO: Add check: moderator_signing_key.pub must match one of the original pubkeys

    except (ValueError, BitcoinAddressError) as val_err: # Use real exception
        logger.error(f"{log_prefix} Invalid dispute parameters: {val_err}")
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during dispute preparation: {e}")
        return None

    # --- Prepare, Sign, Finalize, Broadcast Workflow ---
    try:
        # 1. Prepare PSBT with multiple outputs
        logger.info(f"{log_prefix} Preparing dispute PSBT with outputs: {outputs_to_create}")
        unsigned_psbt_b64 = prepare_btc_multisig_tx(order, outputs_to_create)
        if not unsigned_psbt_b64:
            logger.error(f"{log_prefix} Failed to prepare unsigned PSBT for dispute.")
            return None

        # 2. Sign PSBT with Moderator Key
        logger.info(f"{log_prefix} Signing dispute PSBT with moderator key...")
        moderator_key_wif = None
        if isinstance(moderator_key_info, str): # Basic assumption
            moderator_key_wif = moderator_key_info
        else:
             # TODO: Need to get WIF from CKey or other info
             logger.error(f"{log_prefix} Cannot get moderator WIF from provided key info.")
             return None

        signed_psbt_b64 = sign_btc_multisig_tx(unsigned_psbt_b64, private_key_wif=moderator_key_wif)
        if not signed_psbt_b64:
            logger.error(f"{log_prefix} Failed to sign dispute PSBT with moderator key.")
            return None
        # TODO: Need check if signing actually added a signature

        # 3. Finalize PSBT
        logger.info(f"{log_prefix} Finalizing signed dispute PSBT...")
        final_tx_hex = finalize_btc_psbt(signed_psbt_b64)
        if not final_tx_hex:
            logger.error(f"{log_prefix} Failed to finalize dispute PSBT. Needs more signatures or setup requires moderator-only path?")
            return None

        # 4. Broadcast Transaction
        logger.info(f"{log_prefix} Broadcasting finalized dispute transaction...")
        txid = broadcast_btc_tx(final_tx_hex)
        if not txid:
            logger.error(f"{log_prefix} Failed to broadcast finalized dispute transaction.")
            return None

        logger.info(f"{log_prefix} Dispute transaction successfully created and broadcast. TXID: {txid}")
        return txid

    except CryptoProcessingError as e: # Catch specific crypto errors
        logger.error(f"{log_prefix} Crypto processing error during dispute workflow: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected error during dispute signing/broadcast: {e}")
        return None


# --- Deprecated Functions ---
def process_btc_withdrawal(*args, **kwargs):
    logger.warning("Deprecated function `process_btc_withdrawal` called. Use Ledger system.")
    return False, None
def process_escrow_release(*args, **kwargs):
    logger.warning("Deprecated function `process_escrow_release` called. Use Taproot multi-sig workflow (prepare/sign/finalize/broadcast).")
    return False, None

# --- END OF FILE ---