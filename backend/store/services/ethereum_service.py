# backend/store/services/ethereum_service.py
# <<< REVISED FOR ENTERPRISE GRADE: Robust Web3py, Vault Key, Basic Functions + Multi-Sig Placeholders >>>

import logging
import time
import secrets # <<< ADDED: For placeholder generation >>>
from decimal import Decimal, InvalidOperation, ROUND_DOWN # <<< ADDED: ROUND_DOWN >>>
from typing import Optional, Dict, Tuple, List, Any

# --- Django Imports ---
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

# --- Web3 Imports ---
# <<< BEST PRACTICE: Use try/except for critical library imports >>>
try:
    from web3 import Web3
    from web3.middleware import geth_poa_middleware # If using PoA chains like Goerli/Sepolia testnets
    from web3.exceptions import (
        TransactionNotFound, InvalidAddress, ContractLogicError, BadFunctionCallOutput,
        # Add other specific web3 exceptions you might catch
    )
    WEB3_AVAILABLE = True
except ImportError:
    logging.basicConfig() # Ensure logging is configured even if Django isn't fully loaded yet
    logger_init = logging.getLogger(__name__)
    logger_init.critical("CRITICAL: web3.py library not installed. Ethereum functionality disabled. `pip install web3`")
    WEB3_AVAILABLE = False
    # Define dummies/stubs if library is missing to prevent NameErrors later
    # <<< REFINED DUMMY: Define expected exceptions explicitly >>>
    class DummyWeb3Exceptions:
        TransactionNotFound = type('TransactionNotFound', (Exception,), {})
        InvalidAddress = type('InvalidAddress', (Exception,), {})
        ContractLogicError = type('ContractLogicError', (Exception,), {})
        BadFunctionCallOutput = type('BadFunctionCallOutput', (Exception,), {})
        # Add other exception stubs as needed

    class DummyEth:
        account = None
        chain_id = None
        block_number = None
        gas_price = None
        def get_transaction_count(self, *args, **kwargs): return 0
        def get_balance(self, *args, **kwargs): return 0
        def estimate_gas(self, *args, **kwargs): return 21000
        def send_raw_transaction(self, *args, **kwargs): return b'\x00'*32
        def get_block(self, *args, **kwargs): return {'transactions': []}

    class DummyWeb3:
        middleware_onion = None
        eth = DummyEth()
        exceptions = DummyWeb3Exceptions()
        client_version = "N/A (web3 not installed)" # Corrected line 57
        def is_connected(self): return False
        def is_address(self, x): return False
        def to_checksum_address(self, x): return x
        def from_wei(self, *args, **kwargs): return Decimal('0') # Added kwargs
        def to_wei(self, *args, **kwargs): return 0 # Added dummy to_wei

    Web3 = DummyWeb3()
    geth_poa_middleware = None
    TransactionNotFound = Web3.exceptions.TransactionNotFound
    InvalidAddress = Web3.exceptions.InvalidAddress
    ContractLogicError = Web3.exceptions.ContractLogicError
    BadFunctionCallOutput = Web3.exceptions.BadFunctionCallOutput

# --- Local Imports ---
try:
    # <<< BEST PRACTICE: Use more specific types if possible instead of Any >>>
    from store.models import Order, CryptoPayment, User, GlobalSettings
    from ledger.models import LedgerTransaction
    # <<< CHANGE: Use standardized Vault import for key handling >>>
    # Use absolute import from the 'backend' root
    # >>>>> CORRECTED IMPORT: Changed function name <<<<<
    from vault_integration import get_crypto_secret_from_vault
    # >>>>> REMOVED STRAY LINES that followed the import <<<<<
    # <<< CHANGE: Import validator for Ethereum addresses >>>
    from store.validators import validate_ethereum_address
    MODELS_AVAILABLE = True
    # >>>>> CORRECTED CHECK: Check the newly imported function name <<<<<
    VAULT_AVAILABLE = callable(get_crypto_secret_from_vault) # Check if it's callable
except ImportError as e:
    logging.basicConfig()
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL: Failed to import models/vault/validator in ethereum_service.py: {e}")
    # Define dummies
    # <<< REFINED DUMMIES: Use dummy classes/types >>>
    Order = type('DummyOrder', (object,), {})
    CryptoPayment = type('DummyCryptoPayment', (object,), {'objects': type('DummyManager', (object,), {'filter': lambda **kwargs: type('DummyQuerySet', (object,), {'exists': lambda: False})()})()})
    User = type('DummyUser', (object,), {})
    GlobalSettings = type('DummyGlobalSettings', (object,), {})
    LedgerTransaction = type('DummyLedgerTransaction', (object,), {'objects': type('DummyManager', (object,), {'filter': lambda **kwargs: type('DummyQuerySet', (object,), {'exists': lambda: False})()})()})
    # >>>>> Set dummy for the CORRECT function name <<<<<
    get_crypto_secret_from_vault = None
    validate_ethereum_address = lambda x: None # Validator failure will likely cause issues downstream if used
    MODELS_AVAILABLE = False
    VAULT_AVAILABLE = False
    # <<< CHANGE: Re-raise import error >>>
    raise ImportError(f"Failed to import critical modules in ethereum_service.py: {e}") from e
except Exception as e:
    # Catching broad exceptions during import is risky but sometimes necessary.
    # Ensure logging captures the full context.
    logging.basicConfig()
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"Unexpected error during critical ethereum_service imports: {e}", exc_info=True)
    raise # Re-raise to halt execution if imports are truly critical

# --- Constants ---
WEI_PER_ETH = Decimal('1000000000000000000') # 1e18
# <<< BEST PRACTICE: Use settings for confirmations >>>
CONFIRMATIONS_NEEDED = getattr(settings, 'ETHEREUM_CONFIRMATIONS_NEEDED', 12)
# <<< CHANGE: Standardized market key name for Vault >>>
MARKET_ETH_KEY_NAME_IN_VAULT = getattr(settings, 'MARKET_ETH_VAULT_KEY_NAME', "market_eth_hot_wallet_key") # Allow override
MARKET_ETH_EXPECTED_ADDRESS = getattr(settings, 'MARKET_ETH_HOT_WALLET_ADDRESS', None) # Optional: Address for verification

# --- Configuration (Fetched from Django settings) ---
NODE_URL = getattr(settings, 'ETHEREUM_NODE_URL', None)
CHAIN_ID = getattr(settings, 'ETHEREUM_CHAIN_ID', None) # e.g., 1 for mainnet
NODE_REQUEST_TIMEOUT = getattr(settings, 'ETHEREUM_NODE_TIMEOUT', 60) # seconds

# <<< CHANGE: Gnosis Safe Contract Addresses (MUST be configured if using multi-sig) >>>
GNOSIS_SAFE_FACTORY_ADDRESS = getattr(settings, 'GNOSIS_SAFE_FACTORY_ADDRESS', None)
GNOSIS_SAFE_SINGLETON_ADDRESS = getattr(settings, 'GNOSIS_SAFE_SINGLETON_ADDRESS', None)
# <<< TODO: Define ABIs needed for Gnosis Safe interaction if implementing >>>
# <<< BEST PRACTICE: Load ABIs from JSON files, not hardcoded strings >>>
# Example:
# def load_abi(filename): try: with open(os.path.join(settings.ABI_DIR, filename), 'r') as f: return json.load(f); except Exception: return None
# GNOSIS_SAFE_FACTORY_ABI = load_abi('gnosis_safe_factory.json')
GNOSIS_SAFE_FACTORY_ABI = '[{"inputs":[],"stateMutability":"nonpayable","type":"constructor"}]' # Placeholder ABI
GNOSIS_SAFE_PROXY_ABI = '[{"inputs":[],"stateMutability":"nonpayable","type":"constructor"}]' # Placeholder ABI
GNOSIS_SAFE_EXEC_TX_ABI = '[{"inputs":[],"stateMutability":"nonpayable","type":"constructor"}]' # Placeholder ABI

# --- Custom Exceptions ---
class EthereumServiceError(Exception):
    """Base exception for this service."""
    pass

class InsufficientFundsError(EthereumServiceError):
    """Raised when the market wallet lacks sufficient funds."""
    pass

class ConfigurationError(EthereumServiceError):
    """Raised for configuration issues."""
    pass

class Web3ConnectionError(EthereumServiceError):
    """Raised specifically for Web3 connection issues."""
    pass


# --- Logging ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security') # Standard Django security logger

# --- Web3 Instance Initialization ---
# <<< BEST PRACTICE: Singleton pattern for Web3 instance >>>
_w3_instance: Optional[Web3] = None
def _get_w3() -> Optional[Web3]:
    """
    Gets or initializes the Web3 instance using configured settings.
    Performs connectivity and configuration checks.
    Returns: Initialized and connected Web3 instance or None if setup fails.
    """
    global _w3_instance
    if not WEB3_AVAILABLE:
        # Logged during import, no need to repeat unless verbose
        # logger.debug("Web3 library not available.")
        return None

    # Check cached instance and connectivity
    if _w3_instance:
        try:
            if _w3_instance.is_connected():
                return _w3_instance
            else:
                logger.warning("Cached Web3 instance lost connection. Attempting reconnect.")
                _w3_instance = None # Force re-initialization
        except Exception as conn_e:
            logger.warning(f"Web3 connection check failed unexpectedly ({type(conn_e).__name__}: {conn_e}). Attempting reconnect.")
            _w3_instance = None # Force re-initialization

    # <<< BEST PRACTICE: Validate configuration before attempting connection >>>
    if not NODE_URL:
        logger.critical("ETHEREUM_NODE_URL is not configured in settings. Cannot connect.")
        return None
    if CHAIN_ID is None: # Chain ID 0 is valid (some private chains), so check for None
        logger.critical("ETHEREUM_CHAIN_ID is not configured in settings. Cannot verify network.")
        return None

    logger.info(f"Attempting to connect to Ethereum node: {NODE_URL} (Chain ID: {CHAIN_ID})")
    try:
        # <<< CHANGE: Support different provider types based on URL >>>
        provider_kwargs = {'timeout': NODE_REQUEST_TIMEOUT}
        if NODE_URL.startswith('http'):
            provider = Web3.HTTPProvider(NODE_URL, request_kwargs=provider_kwargs)
        elif NODE_URL.startswith('ws'):
            provider = Web3.WebsocketProvider(NODE_URL, websocket_kwargs=provider_kwargs)
        # <<< TODO: Add IPCProvider support if needed >>>
        # elif NODE_URL.endswith('.ipc'):
        #     provider = Web3.IPCProvider(NODE_URL, timeout=NODE_REQUEST_TIMEOUT)
        else:
            logger.critical(f"Unsupported Ethereum node URL scheme: {NODE_URL}")
            raise ConfigurationError(f"Unsupported Ethereum node URL scheme: {NODE_URL}")

        w3 = Web3(provider)

        # Check connection immediately
        if not w3.is_connected():
            raise Web3ConnectionError(f"Failed to connect to Ethereum node at {NODE_URL}")

        # <<< BEST PRACTICE: Inject PoA middleware if needed (e.g., for testnets) >>>
        # Needs to be done AFTER initial connection check
        # Example common PoA Chain IDs (adjust as needed): Mainnet=1, Ropsten=3, Rinkeby=4, Goerli=5, Sepolia=11155111
        poa_chain_ids = getattr(settings, 'ETHEREUM_POA_CHAIN_IDS', [5, 11155111])
        if CHAIN_ID in poa_chain_ids:
            try:
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                logger.info(f"Injected PoA middleware for Chain ID {CHAIN_ID}.")
            except AttributeError: # Handle case where middleware stack isn't available (older Web3?)
                logger.warning("Could not inject PoA middleware (middleware_onion attribute missing?).")
            except Exception as mw_e: # Catch other potential errors during injection
                 logger.warning(f"Failed to inject PoA middleware: {mw_e}")

        # Verify Chain ID against the connected node
        node_chain_id = w3.eth.chain_id
        if node_chain_id != CHAIN_ID:
            logger.critical(f"Chain ID Mismatch! Configured: {CHAIN_ID}, Node ({NODE_URL}) reports: {node_chain_id}. Aborting connection.")
            # Option: raise ConfigurationError("Chain ID mismatch") # To halt startup if desired
            return None # Safer default: refuse connection on mismatch

        node_version = w3.client_version
        _w3_instance = w3
        logger.info(f"Web3 instance initialized successfully. Node Version: {node_version}, Chain ID: {CHAIN_ID}, Connected: True")
        return _w3_instance

    except (Web3ConnectionError, ConfigurationError) as config_conn_e:
         logger.critical(f"{config_conn_e}")
         _w3_instance = None
         return None
    except Exception as e:
        logger.exception(f"CRITICAL: Unexpected error during Web3 initialization: {e}")
        _w3_instance = None
        return None

# --- Secure Key Retrieval (for Withdrawals) ---
# <<< BEST PRACTICE: Centralize secure key fetching >>>
_market_eth_private_key_cache: Optional[bytes] = None # Store raw bytes
def _get_market_eth_private_key() -> Optional[bytes]:
    """
    Securely retrieves the market's ETH private key (for withdrawals) from Vault.
    Fetches raw private key hex, validates it, converts to bytes, and caches it.
    Optionally verifies the derived address against settings.MARKET_ETH_HOT_WALLET_ADDRESS.

    Returns: Private key as bytes if successful, None otherwise.
    """
    global _market_eth_private_key_cache
    if _market_eth_private_key_cache:
        return _market_eth_private_key_cache

    # <<< CHANGE: Ensure Vault service integration is available >>>
    # >>>>> CORRECTED CHECK: Use the correct function name <<<<<
    if not callable(get_crypto_secret_from_vault):
        security_logger.critical("Vault integration service (get_crypto_secret_from_vault) is unavailable or not callable. Cannot fetch market ETH key.")
        return None

    security_logger.info(f"Attempting to load market ETH private key from Vault (Key: {MARKET_ETH_KEY_NAME_IN_VAULT})")
    try:
        # <<< CHANGE: Fetch raw hex key using standardized key name >>>
        # Assumes Vault secret contains a field named 'private_key_hex' (without 0x prefix)
        # >>>>> CORRECTED CALL: Use the correct function name and arguments <<<<<
        key_hex = get_crypto_secret_from_vault(
            key_type='ethereum', # Identify the type of key being fetched
            key_name=MARKET_ETH_KEY_NAME_IN_VAULT, # Use the standardized name
            key_field='private_key_hex', # Specify the field containing the hex key within the Vault secret
            raise_error=True # Let vault integration handle specific vault errors
        )

        if not key_hex or not isinstance(key_hex, str):
            # Error should have been logged by get_crypto_secret_from_vault if raise_error=True
            # Or it might return None if key/field not found and raise_error=False
            security_logger.critical(f"Did not receive a valid private key string from Vault for {MARKET_ETH_KEY_NAME_IN_VAULT}.")
            return None

        # <<< BEST PRACTICE: Validate hex format and length rigorously >>>
        key_hex = key_hex.strip().lower()
        if len(key_hex) != 64 or not all(c in '0123456789abcdef' for c in key_hex):
            raise ValueError("Invalid private key hex format retrieved from Vault (must be 64 hex characters).")

        private_key_bytes = bytes.fromhex(key_hex)

        # <<< BEST PRACTICE: Derive address and log/verify >>>
        w3 = _get_w3() # Requires web3 connection
        if w3:
            try:
                derived_account = w3.eth.account.from_key(private_key_bytes)
                derived_address = derived_account.address
                security_logger.info(f"Successfully loaded and validated market ETH private key from Vault. Derived Address: {derived_address}")

                # Optional: Verify against expected address in settings
                if MARKET_ETH_EXPECTED_ADDRESS:
                    expected_checksum = w3.to_checksum_address(MARKET_ETH_EXPECTED_ADDRESS)
                    if derived_address != expected_checksum:
                        security_logger.critical(
                            f"CRITICAL SECURITY ALERT: Derived market ETH address ({derived_address}) "
                            f"does NOT match expected address ({expected_checksum}) from settings!"
                        )
                        # Depending on policy, you might want to return None here to prevent use of the wrong key
                        # return None
                    else:
                         security_logger.info(f"Derived market ETH address matches expected address from settings.")

            except Exception as addr_e:
                # Log failure to derive address, but might still proceed if key format was valid
                security_logger.warning(f"Could not derive address from market ETH key, but format was valid. Error: {addr_e}")
        else:
            security_logger.warning("Web3 unavailable, cannot derive/verify market ETH address from private key.")

        _market_eth_private_key_cache = private_key_bytes
        # Clear the hex key from memory as soon as possible
        del key_hex
        return _market_eth_private_key_cache

    except ValueError as val_err:
        security_logger.critical(f"CRITICAL: Invalid format or value for Market ETH key '{MARKET_ETH_KEY_NAME_IN_VAULT}' in Vault: {val_err}")
        return None
    except Exception as e:
        # Catch potential errors from vault_integration or other unexpected issues
        security_logger.exception(f"CRITICAL: Failed to load, decode, or validate market ETH key from Vault: {e}")
        return None

# --- Conversion Utilities ---
def eth_to_wei(amount_eth: Decimal) -> int:
    """
    Converts ETH Decimal to Wei (integer), rounding down for safety.
    Raises ValueError for invalid input.
    """
    if amount_eth is None:
        raise ValueError("Invalid amount for Wei conversion: None")
    try:
        # Ensure input is treated as Decimal, then convert
        dec_amount = Decimal(amount_eth)
        if dec_amount < 0:
             raise ValueError("Amount cannot be negative for Wei conversion.")
        # <<< CHANGE: Round down for safety (to avoid sending more than intended) >>>
        return int((dec_amount * WEI_PER_ETH).to_integral_value(rounding=ROUND_DOWN))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"Invalid Decimal '{amount_eth}' for eth_to_wei conversion: {e}")
        raise ValueError(f"Invalid amount for Wei conversion: {amount_eth}") from e

def wei_to_eth(amount_wei: int) -> Decimal:
    """
    Converts Wei (integer) to ETH Decimal with 18 decimal places.
    Raises ValueError for invalid input.
    """
    if amount_wei is None:
        raise ValueError("Invalid amount for ETH conversion: None")
    try:
        # <<< BEST PRACTICE: Use quantize for correct 18 decimal places >>>
        wei_dec = Decimal(amount_wei)
        if wei_dec < 0:
            # This shouldn't happen with blockchain balances, but good to check
            raise ValueError("Wei amount cannot be negative for ETH conversion.")
        eth_val = (wei_dec / WEI_PER_ETH).quantize(Decimal('1e-18'))
        return eth_val
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"Invalid integer '{amount_wei}' for wei_to_eth conversion: {e}")
        raise ValueError(f"Invalid amount for ETH conversion: {amount_wei}") from e

# --- Core Service Functions ---
def get_latest_block_number() -> Optional[int]:
    """Gets the latest block number from the connected node."""
    w3 = _get_w3()
    if not w3: return None
    try:
        return w3.eth.block_number
    except Exception as e:
        logger.exception(f"Failed to get latest ETH block number: {e}")
        return None

def estimate_gas_price(buffer_percentage: int = 10) -> Optional[int]:
    """
    Estimates gas price in Wei, optionally adding a buffer.
    Returns gas price in Wei, or None on error.
    """
    w3 = _get_w3()
    if not w3: return None
    try:
        gas_price_wei = w3.eth.gas_price
        if buffer_percentage > 0:
             buffer = gas_price_wei * buffer_percentage // 100
             gas_price_wei += buffer

        # <<< BEST PRACTICE: Consider adding check against minimum/maximum gas prices from settings >>>
        min_gas_gwei = getattr(settings, 'ETHEREUM_MIN_GAS_PRICE_GWEI', 1) # Example minimum 1 Gwei
        max_gas_gwei = getattr(settings, 'ETHEREUM_MAX_GAS_PRICE_GWEI', 500) # Example maximum 500 Gwei
        min_gas_wei = w3.to_wei(min_gas_gwei, 'gwei')
        max_gas_wei = w3.to_wei(max_gas_gwei, 'gwei')

        gas_price_wei = max(gas_price_wei, min_gas_wei)
        if gas_price_wei > max_gas_wei:
            logger.warning(f"Estimated gas price ({w3.from_wei(gas_price_wei, 'gwei')} Gwei) exceeds maximum ({max_gas_gwei} Gwei). Capping.")
            gas_price_wei = max_gas_wei

        logger.info(f"Estimated gas price (incl. ~{buffer_percentage}% buffer & min/max checks): {w3.from_wei(gas_price_wei, 'gwei')} Gwei ({gas_price_wei} Wei)")
        return gas_price_wei
    except Exception as e:
        logger.exception(f"Failed to estimate ETH gas price: {e}")
        return None

# <<< CHANGE: Basic address generation REMOVED - DO NOT generate ETH keys in backend >>>

# --- Multi-Sig Functions (Gnosis Safe Placeholders) ---
# <<< CRITICAL WARNING: The following functions are conceptual placeholders. >>>
# <<< Implementing secure Gnosis Safe multi-sig requires deep expertise in: >>>
# <<<   - Smart contract interaction (ABIs, encoding, event parsing)       >>>
# <<<   - Off-chain signature collection and verification (EIP-712)        >>>
# <<<   - Gas estimation, transaction relaying, and nonce management       >>>
# <<<   - Secure deployment/verification of factory/singleton contracts    >>>
# <<<   - Thorough auditing of both off-chain logic and related contracts. >>>
# <<< DO NOT USE THESE IN PRODUCTION WITHOUT FULL IMPLEMENTATION & AUDIT. >>>

def deploy_escrow_contract(order: 'Order') -> Optional[str]:
    """
    (Placeholder) Deploys a new Gnosis Safe proxy contract for the order.
    Requires pre-deployed Factory and Singleton contracts configured in settings.
    Returns the address of the new proxy contract or None on failure.
    """
    logger.critical("CRITICAL: deploy_escrow_contract is a NON-FUNCTIONAL PLACEHOLDER and should NOT be used in production!")
    # Basic checks even for placeholder
    if Order is None or type(Order).__name__ == 'DummyOrder': logger.critical("Order model not loaded."); return None;
    if not isinstance(order, Order): logger.error("Invalid Order object passed."); return None;

    w3 = _get_w3()
    if not w3: logger.error("Web3 connection unavailable for Gnosis deployment."); return None;
    if not GNOSIS_SAFE_FACTORY_ADDRESS or not GNOSIS_SAFE_SINGLETON_ADDRESS:
        logger.error("Gnosis Safe factory or singleton address not configured in settings.")
        return None
    # Example owner addresses from order (adjust field names as needed)
    owners = [
        getattr(order, 'eth_multisig_owner_buyer', None),
        getattr(order, 'eth_multisig_owner_vendor', None),
        getattr(order, 'eth_multisig_owner_market', None) # Market's address for multi-sig
    ]
    if not all(owners):
        logger.error(f"Missing one or more owner addresses on Order {order.id} for Gnosis deployment.")
        return None

    # --- Actual implementation requires extensive logic (see original comments) ---

    # Placeholder returns a mock address
    new_proxy_address = f"0xMOCK_GNOSIS_PROXY_{order.id}_{secrets.token_hex(10)}"
    logger.info(f"(Placeholder) 'Deployed' Gnosis Safe proxy for Order {order.id} at {new_proxy_address}")
    return new_proxy_address

def prepare_eth_multisig_tx_hash(order: 'Order', recipient_address: str, amount_eth: Decimal) -> Optional[str]:
    """
    (Placeholder) Prepares the EIP-712 hash for executing a Safe transaction.
    This hash needs to be signed off-chain by the required owners (e.g., buyer and vendor).
    Returns the EIP-712 compatible hash (hex string) or None on failure.
    """
    logger.critical("CRITICAL: prepare_eth_multisig_tx_hash is a NON-FUNCTIONAL PLACEHOLDER!")
    if Order is None or type(Order).__name__ == 'DummyOrder': logger.critical("Order model not loaded."); return None;
    if not isinstance(order, Order): logger.error("Invalid Order object passed."); return None;

    w3 = _get_w3()
    escrow_contract_address = getattr(order, 'eth_escrow_contract_address', None)
    if not w3: logger.error("Web3 unavailable for preparing Gnosis hash."); return None;
    if not escrow_contract_address: logger.error(f"Missing eth_escrow_contract_address on Order {order.id}."); return None;
    try:
        validate_ethereum_address(recipient_address)
        recipient_checksum = w3.to_checksum_address(recipient_address)
        amount_wei = eth_to_wei(amount_eth)
        if amount_wei <= 0: raise ValueError("Amount must be positive.")
    except (DjangoValidationError, ValueError, InvalidOperation) as e:
        logger.error(f"Invalid recipient address/amount for Gnosis hash prep O:{order.id}: {e}")
        return None

    # --- Actual implementation requires extensive logic (see original comments) ---

    # Placeholder returns a mock hash
    tx_hash_hex = f"0xMOCK_EIP712_HASH_{order.id}_{secrets.token_hex(20)}"
    logger.info(f"(Placeholder) Prepared Gnosis Safe EIP-712 Tx Hash for Order {order.id}: {tx_hash_hex[:20]}...")
    return tx_hash_hex

def execute_eth_multisig_tx(order: 'Order', recipient_address: str, amount_eth: Decimal, combined_signatures_hex: str) -> Optional[str]:
    """
    (Placeholder) Executes a Gnosis Safe transaction using collected signatures.
    Requires a market key ('relayer') with gas funds to submit the transaction.
    The `combined_signatures_hex` is the tightly packed concatenation of signatures from required owners.
    Returns the blockchain transaction hash (TXID) of the executed Safe transaction or None on failure.
    """
    logger.critical("CRITICAL: execute_eth_multisig_tx is a NON-FUNCTIONAL PLACEHOLDER!")
    if Order is None or type(Order).__name__ == 'DummyOrder': logger.critical("Order model not loaded."); return None;
    if not isinstance(order, Order): logger.error("Invalid Order object passed."); return None;

    w3 = _get_w3()
    escrow_contract_address = getattr(order, 'eth_escrow_contract_address', None)
    if not w3: logger.error("Web3 unavailable for executing Gnosis tx."); return None;
    if not escrow_contract_address: logger.error(f"Missing eth_escrow_contract_address on Order {order.id}."); return None;
    if not combined_signatures_hex or not isinstance(combined_signatures_hex, str): logger.error(f"Missing or invalid combined_signatures_hex for Order {order.id}."); return None;
    # Basic validation of hex signature format (length depends on number of sigs, typically N * 65 bytes)
    if not combined_signatures_hex.startswith('0x') or not all(c in '0123456789abcdefABCDEF' for c in combined_signatures_hex[2:]):
         logger.error(f"Invalid combined_signatures_hex format for Order {order.id}.")
         return None
    signatures_bytes = bytes.fromhex(combined_signatures_hex[2:]) # Remove 0x prefix


    try:
        # Validate inputs again just before execution
        validate_ethereum_address(recipient_address)
        recipient_checksum = w3.to_checksum_address(recipient_address)
        amount_wei = eth_to_wei(amount_eth)
        if amount_wei <= 0: raise ValueError("Amount must be positive.")
    except (DjangoValidationError, ValueError, InvalidOperation) as e:
        logger.error(f"Invalid recipient address/amount for Gnosis tx execution O:{order.id}: {e}")
        return None

    # --- Actual implementation requires extensive logic (see original comments) ---

    # Placeholder returns a mock hash
    broadcast_tx_hash = f"0xMOCK_BROADCAST_HASH_{order.id}_{secrets.token_hex(20)}"
    logger.info(f"(Placeholder) 'Executed' Gnosis Safe tx for Order {order.id}. Broadcast Hash: {broadcast_tx_hash[:20]}...")
    return broadcast_tx_hash

# --- Basic Withdrawal (Non-Escrow / Centralized Hot Wallet) ---
def process_withdrawal(user: 'User', amount_eth: Decimal, address: str) -> Tuple[bool, Optional[str]]:
    """
    Processes a direct ETH withdrawal from the market's hot wallet (using the key from Vault).
    This is NOT part of the multi-sig escrow flow.

    Args:
        user: The User object requesting the withdrawal (for logging/context).
        amount_eth: The amount of ETH (as Decimal) to withdraw.
        address: The recipient Ethereum address (string).

    Returns:
        Tuple (success: bool, tx_hash: Optional[str])
    """
    # <<< CHANGE: Added necessary model checks >>>
    if User is None or type(User).__name__ == 'DummyUser': logger.critical("User model not loaded."); return False, None;
    w3 = _get_w3()
    if not w3: logger.critical("Web3 unavailable for ETH withdrawal."); return False, None;
    if not isinstance(user, User): logger.error(f"Invalid User object type passed: {type(user)}"); return False, None;

    username = getattr(user, 'username', 'UnknownUser') # Safely get username for logging

    # --- Validate Inputs ---
    try:
        # <<< CHANGE: Use validator (which should use Web3 for checksum check if available) >>>
        validate_ethereum_address(address) # Raises DjangoValidationError on failure
        recipient_checksum = w3.to_checksum_address(address) # Ensure checksum format
        # <<< CHANGE: Ensure amount is positive and convert >>>
        if amount_eth <= Decimal('0.0'): raise ValueError("Withdrawal amount must be positive.")
        amount_wei = eth_to_wei(amount_eth) # Raises ValueError on failure
    except (DjangoValidationError, ValueError, InvalidOperation) as e:
        logger.error(f"Invalid withdrawal address or amount for U:{username}. Addr: '{address}', Amt: '{amount_eth}'. Error: {e}")
        return False, None

    # --- Get Market Key & Build Tx ---
    market_private_key_bytes = _get_market_eth_private_key()
    if not market_private_key_bytes:
        # Critical error already logged by _get_market_eth_private_key
        logger.critical(f"Cannot process withdrawal for U:{username}: Market ETH private key is unavailable.")
        return False, None

    try:
        market_account = w3.eth.account.from_key(market_private_key_bytes)
        market_address = market_account.address
        security_logger.info(f"Processing ETH withdrawal: User {username}, Amount {amount_eth:.18f} ETH ({amount_wei} Wei), To {recipient_checksum} (From Market Hot Wallet: {market_address})")

        # --- Estimate Gas & Nonce ---
        # <<< BEST PRACTICE: Estimate gas price using helper >>>
        gas_price_wei = estimate_gas_price() # Includes buffer and checks
        if gas_price_wei is None:
            raise EthereumServiceError("Failed to estimate gas price for withdrawal.")

        # <<< CHANGE: Use specific market address for nonce & 'pending' >>>
        try:
            nonce = w3.eth.get_transaction_count(market_address, 'pending') # Use 'pending' for robustness against stuck txs
        except Exception as nonce_e:
             logger.exception(f"Failed to get nonce for market address {market_address}: {nonce_e}")
             raise EthereumServiceError(f"Failed to get nonce for withdrawal: {nonce_e}") from nonce_e

        # Basic ETH transfer transaction parameters
        tx_params = {
            'to': recipient_checksum,
            'value': amount_wei,
            'gas': 21000, # Standard gas limit for a basic ETH transfer
            'gasPrice': gas_price_wei,
            'nonce': nonce,
            'chainId': CHAIN_ID
        }

        # --- CRITICAL: Check Market Wallet Balance ---
        try:
            market_balance_wei = w3.eth.get_balance(market_address)
        except Exception as balance_e:
             logger.exception(f"Failed to get balance for market address {market_address}: {balance_e}")
             raise EthereumServiceError(f"Failed to get market balance for withdrawal check: {balance_e}") from balance_e

        required_wei = amount_wei + (tx_params['gas'] * tx_params['gasPrice'])

        if market_balance_wei < required_wei:
            # Log critical error, potentially trigger monitoring/alerts
            alert_message = (f"CRITICAL: Market ETH wallet {market_address} has insufficient funds for withdrawal. "
                             f"User: {username}, Amount: {amount_eth} ETH. "
                             f"Required: {required_wei} Wei, Available: {market_balance_wei} Wei.")
            security_logger.critical(alert_message)
            logger.critical(alert_message) # Also log to main logger
            # <<< TODO: Implement admin alert system trigger here >>>
            # e.g., trigger_admin_alert("Insufficient ETH Balance", alert_message)
            raise InsufficientFundsError(f"Market wallet {market_address} has insufficient ETH balance for this withdrawal.")

        # --- Sign & Send ---
        logger.info(f"Signing ETH withdrawal tx for U:{username} (Nonce: {nonce}, GasPrice: {w3.from_wei(gas_price_wei, 'gwei')} Gwei)")
        signed_tx = w3.eth.account.sign_transaction(tx_params, market_private_key_bytes)

        logger.info(f"Sending ETH withdrawal tx for U:{username} (Nonce: {nonce})...")
        tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_hash_hex = tx_hash_bytes.hex()

        logger.info(f"ETH Withdrawal Sent Successfully: User {username}, Amount {amount_eth:.18f} ETH. TXID: {tx_hash_hex}")
        security_logger.info(f"ETH WD OK: U:{username} A:{amount_eth:.18f} Addr:{recipient_checksum} TXID:{tx_hash_hex} From:{market_address}")

        # --- IMPORTANT: Post-withdrawal actions ---
        # The calling code should handle:
        # 1. Recording the transaction hash (tx_hash_hex) in the database (e.g., WithdrawalRequest model).
        # 2. Updating the user's balance *optimistically* or after confirmation, depending on policy.
        # 3. Monitoring the transaction status on the blockchain.

        return True, tx_hash_hex

    except InsufficientFundsError as ife:
        # Already logged critically. Return False to indicate failure.
        logger.error(f"Withdrawal failed for U:{username} due to insufficient market funds.")
        return False, None
    except (ValueError, TypeError, EthereumServiceError) as build_err: # Catch specific errors building/signing/sending tx
        logger.error(f"Error building/signing/sending ETH withdrawal tx for U:{username}: {build_err}")
        return False, None
    except Exception as e:
        # Catch unexpected errors (e.g., node connection issues during send)
        logger.exception(f"Unexpected error during ETH withdrawal processing U:{username}: {e}")
        return False, None

# --- Deposit Scanning ---
def scan_for_payment_confirmation(payment: 'CryptoPayment') -> Optional[Tuple[bool, Decimal, int, Optional[str]]]:
    """
    Checks a specific Ethereum payment address for a confirmed transaction meeting criteria.
    Currently uses basic block iteration - **inefficient for high volume**. Consider filters or indexing.

    Args:
        payment: The CryptoPayment object containing details (payment_address, expected_amount_native, etc.).

    Returns:
        - If confirmed: (True, received_amount_eth, confirmations, txid_found)
        - If not yet confirmed: (False, Decimal('0.0'), 0, None)
        - On error: None
    """
    # <<< CHANGE: Added necessary model checks >>>
    required_models = [CryptoPayment, LedgerTransaction]
    if any(m is None or type(m).__name__.startswith('Dummy') for m in required_models):
        logger.error("Required models (CryptoPayment, LedgerTransaction) not loaded for ETH confirm scan.")
        return None

    w3 = _get_w3()
    if not w3: logger.critical("Web3 unavailable for ETH payment scan."); return None;

    # Validate payment object
    if not payment or not isinstance(payment, CryptoPayment) or payment.currency != 'ETH' or not payment.payment_address:
        logger.error(f"Invalid or incomplete CryptoPayment object provided for ETH scan: ID={getattr(payment, 'id', 'N/A')}")
        return None

    order_id = getattr(payment, 'order_id', 'N/A') # For logging

    try:
        target_address_checksum = w3.to_checksum_address(payment.payment_address)
        # Default confirmations if not set on payment record
        min_confirmations = payment.confirmations_needed if payment.confirmations_needed is not None else CONFIRMATIONS_NEEDED
        # Use precise expected amount
        if payment.expected_amount_native is None:
             raise ValueError(f"Missing expected_amount_native on Payment {payment.id}")
        expected_amount_wei = eth_to_wei(payment.expected_amount_native)
        if expected_amount_wei <= 0 and payment.expected_amount_native > 0: # Handle potential rounding to zero for tiny amounts
             logger.warning(f"Expected amount {payment.expected_amount_native} ETH resulted in 0 Wei for Payment {payment.id}. Check precision/amount.")
             # Decide policy: require at least 1 Wei? For now, allow 0 if original > 0.
             pass # Allow expected 0 wei if original amount was positive but very small

    except (ValueError, InvalidAddress, InvalidOperation) as val_err:
        logger.error(f"Invalid data on CryptoPayment ID {payment.id} for scan: {val_err}")
        return None # Cannot proceed with invalid data

    try:
        # --- Get current block number ---
        latest_block_num = get_latest_block_number()
        if latest_block_num is None:
            raise Web3ConnectionError("Failed to get latest block number for scan.")

        # --- Determine Scan Range ---
        # <<< ENTERPRISE BEST PRACTICE: Store last scanned block per address/globally and scan from there + confirmation depth >>>
        # Example using a field on the payment model: `last_scanned_block = payment.last_scanned_block or 0`
        # `scan_from_block = max(0, last_scanned_block + 1)`
        # `scan_to_block = latest_block_num`
        # --- Simplified Approach (less robust): Scan last N blocks ---
        scan_depth = getattr(settings, 'ETHEREUM_SCAN_DEPTH', 200) # Scan more blocks? Make configurable.
        # Scan from `latest - depth` OR from block where payment *could* have first appeared + confs needed.
        # Simplest: just scan last `scan_depth` blocks.
        start_block = max(0, latest_block_num - scan_depth)
        # Important: We need to ensure we scan deep enough to potentially find tx and achieve confirmations.
        # A better start_block might be `max(0, latest_block_num - scan_depth - min_confirmations)`
        # but for simplicity, we stick to scan_depth and check confirmations later.

        logger.debug(f"Scanning ETH blocks {start_block} to {latest_block_num} for payment to {target_address_checksum} (Order {order_id}, Payment {payment.id})")

        found_match: Optional[Dict[str, Any]] = None

        # --- Iterating Blocks (Basic Method - Inefficient & can miss txs during downtime without persistent state) ---
        # <<< Recommendation: Use w3.eth.filter('latest') for new blocks, or eth_getLogs for range, or dedicated indexing service >>>
        for block_num in range(start_block, latest_block_num + 1):
            try:
                # Fetch block with full transactions
                block = w3.eth.get_block(block_num, full_transactions=True)
                if not block or not block.get('transactions'):
                    # logger.debug(f"Block {block_num} empty or no transactions.")
                    continue

                # logger.debug(f"Scanning {len(block['transactions'])} txs in block {block_num}")
                for tx in block['transactions']:
                    # Checksum comparison needed for 'to' address
                    tx_to = tx.get('to')
                    tx_hash_bytes = tx.get('hash')
                    tx_value = tx.get('value') # Value is in Wei (integer)

                    if not tx_to or tx_value is None or tx_hash_bytes is None: # Skip contract creation or incomplete tx data
                        continue

                    # Check if transaction is directed TO our target address
                    if w3.to_checksum_address(tx_to) == target_address_checksum:
                        try:
                            tx_amount_wei = int(tx_value)
                            txid_hex = tx_hash_bytes.hex()
                            confirmations = latest_block_num - block_num + 1

                            # Check 1: Has this TXID already been processed for this payment/order?
                            # <<< BEST PRACTICE: Check LedgerTransaction table >>>
                            if LedgerTransaction.objects.filter(
                                external_txid=txid_hex,
                                transaction_type='DEPOSIT', # Ensure it's a deposit type
                                currency='ETH',
                                # Be specific: link to order or user or payment record if possible
                                related_order=payment.order # Assuming payment has direct link to order
                                # Alternatively: related_payment=payment
                            ).exists():
                                # logger.debug(f"ETH TXID {txid_hex} Order {order_id} Addr {target_address_checksum} already processed in ledger.")
                                continue # Skip already processed transaction

                            # Check 2: Does it meet amount and confirmation requirements?
                            # <<< CHANGE: Check amount >= expected, confirmations >= required >>>
                            # Allow for slightly MORE than expected (user overpayment)
                            if confirmations >= min_confirmations and tx_amount_wei >= expected_amount_wei:
                                received_amount_eth = wei_to_eth(tx_amount_wei)
                                match_data = {
                                    'amount_eth': received_amount_eth,
                                    'confirmations': confirmations,
                                    'txid': txid_hex,
                                    'block_num': block_num
                                }
                                # Simple strategy: Take the first valid one found.
                                # Could be enhanced: prioritize exact match, or highest confirmation match etc.
                                found_match = match_data
                                logger.info(f"Found candidate ETH payment: Order {order_id}, Payment {payment.id}, TX: {txid_hex}, Block: {block_num}, Amount: {received_amount_eth} ETH, Confs: {confirmations}")
                                break # Found a suitable match in this block, stop scanning txs here

                        except (ValueError, TypeError, InvalidOperation, InvalidAddress) as parse_e:
                            txid_hex_err = tx_hash_bytes.hex() if tx_hash_bytes else 'N/A'
                            logger.warning(f"Error parsing tx data in Block {block_num}, Tx {txid_hex_err}: {parse_e}")
                            continue # Skip this transaction

            except (TransactionNotFound, BadFunctionCallOutput) as node_e:
                # These might happen if node is syncing or block is unavailable temporarily
                logger.warning(f"Node error fetching/processing ETH block {block_num}: {node_e}. Skipping block.")
                continue
            except Exception as block_e:
                # Catch other unexpected errors during block processing
                logger.exception(f"Unexpected error processing ETH block {block_num}: {block_e}")
                continue # Skip this block

            # If we found a match in the inner loop, break the outer block loop too
            if found_match:
                break

        # --- Process Result ---
        if found_match:
            logger.info(f"Confirmed ETH payment for Order {order_id}, Payment {payment.id}. TXID: {found_match['txid']}, Amount: {found_match['amount_eth']} ETH, Confs: {found_match['confirmations']}")
            # <<< BEST PRACTICE: Update last_scanned_block on the payment record here >>>
            # payment.last_scanned_block = latest_block_num # Or found_match['block_num'] ? Need consistent strategy.
            # payment.save(update_fields=['last_scanned_block'])
            return (True, found_match['amount_eth'], found_match['confirmations'], found_match['txid'])
        else:
            # No confirmed, sufficient payment found within the scanned range
            logger.debug(f"No confirmed, sufficient ETH payment found yet for Order {order_id}, Payment {payment.id}, Addr {target_address_checksum}.")
            # <<< BEST PRACTICE: Update last_scanned_block even if not found >>>
            # payment.last_scanned_block = latest_block_num
            # payment.save(update_fields=['last_scanned_block'])
            return (False, Decimal('0.0'), 0, None) # Not confirmed yet

    except Web3ConnectionError as conn_err:
        logger.error(f"Web3 connection error during ETH payment scan P:{payment.id} O:{order_id}: {conn_err}")
        return None # Indicate error
    except Exception as e:
        logger.exception(f"Unexpected error during ETH payment confirmation scan P:{payment.id} O:{order_id} Addr:{target_address_checksum}: {e}")
        return None # Indicate error


# --- Centralized Escrow Release Function (Placeholder - Requires careful consideration) ---
# <<< NOTE: This uses the MAIN hot wallet and basic transfer. It does NOT use multi-sig. >>>
# <<< Recommendation: If using multi-sig escrow, replace this with calls to the Gnosis Safe workflow (prepare/execute). >>>
# <<< If using a centralized model IS intended, ensure security/authorization is extremely robust. >>>
def process_escrow_release(order: 'Order', vendor_address: str, payout_eth: Decimal) -> Tuple[bool, Optional[str]]:
    """
    (Basic/Centralized Escrow Model ONLY) Processes escrow release from market hot wallet to vendor via basic transfer.

    Args:
        order: The Order object being released.
        vendor_address: The ETH address of the vendor receiving payment.
        payout_eth: The amount of ETH (Decimal) to pay out.

    Returns:
        (True, txid) on success, (False, None) on failure.

    WARNING: This bypasses any multi-sig flow. Use only if a centralized escrow model is explicitly intended
             and secured appropriately. Otherwise, replace with multi-sig execution calls.
    """
    # Get loggers (assuming defined globally)
    # logger = logging.getLogger(__name__) # Already defined
    # security_logger = logging.getLogger('django.security') # Already defined

    # <<< CHANGE: Added Order/User model check >>>
    if Order is None or type(Order).__name__ == 'DummyOrder' or User is None or type(User).__name__ == 'DummyUser':
        logger.critical("Models (Order, User) not loaded for basic escrow release.")
        return False, None
    if not isinstance(order, Order):
        logger.error(f"Invalid Order object type passed to process_escrow_release: {type(order)}")
        return False, None

    # Get the vendor User object associated with the order for context/logging in process_withdrawal
    vendor_user = getattr(order, 'vendor', None)
    if not vendor_user or not isinstance(vendor_user, User):
        logger.error(f"Could not find valid Vendor User object on Order {order.id} for basic escrow release.")
        return False, None

    security_logger.warning(
        f"Executing BASIC/CENTRALIZED ETH Escrow Release via direct transfer for Order {order.id}. "
        f"Amount: {payout_eth} ETH, Vendor User: {getattr(vendor_user, 'username', 'N/A')}, Vendor Addr: {vendor_address}"
    )

    # --- Reuse the existing basic withdrawal logic ---
    # Pass the vendor User object (for logging context), amount, and the validated vendor payout address
    success, tx_hash = process_withdrawal(vendor_user, payout_eth, vendor_address)

    if success:
        logger.info(f"BASIC ETH Escrow Release (via process_withdrawal) Sent OK: Order:{order.id}, Amt:{payout_eth:.18f}, VendorAddr:{vendor_address}, TXID:{tx_hash}")
        security_logger.info(f"BASIC ETH Release OK: O:{order.id} A:{payout_eth:.18f} V_Addr:{vendor_address} TXID:{tx_hash}")
    else:
        # Failure reason logged within process_withdrawal
        logger.error(f"BASIC ETH Escrow Release (via process_withdrawal) FAILED: Order:{order.id}, Amt:{payout_eth:.18f}, VendorAddr:{vendor_address}")

    # The calling function needs to handle DB updates (e.g., marking order as released/paid) based on this result.
    return success, tx_hash