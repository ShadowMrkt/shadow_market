# backend/store/services/common_escrow_utils.py
# Contains shared constants, exceptions, and helper functions for escrow services.
# Revision History:
# 2025-04-11: (Gemini Rev 8): Re-enabled 'ETH-MULTISIG' mapping in service_module_map
#                            to resolve test failures in test_ethereum_escrow_service.py.
# 2025-04-11: (Gemini): Updated service_module_map: Removed 'ETH-MULTISIG', Added 'ETH-BASIC'.
# 2025-04-10: v1.13.1 (Gemini):
#           - FIXED: ValueError in _get_specific_escrow_service due to incorrect case comparison.
#                    Changed `escrow_type.upper()` to `escrow_type.lower()` for comparison with EscrowTypeChoices.values.
# 2025-04-10: v1.13.0 (Gemini):
#           - MODIFIED: _get_specific_escrow_service now takes escrow_type and uses it
#             along with currency to determine the correct service module (MULTISIG vs BASIC).
#           - UPDATED: service_module_map includes entries for BASIC escrow services.
#           - MODIFIED: Dispatcher functions (create_escrow_for_order, check_and_confirm_payment,
#             sign_order_release, broadcast_release_transaction, resolve_dispute) now retrieve
#             order.escrow_type and pass it to _get_specific_escrow_service.
#           - ADDED: sign_order_release now explicitly handles BASIC escrow (logs warning, returns False)
#             as signing is not applicable.
# 2025-04-09: v1.12.1 (The Void):
#           - FIX: `broadcast_release_transaction` dispatcher now passes `order_id`
#             to `specific_service.broadcast_release` instead of the full `order` object,
#             resolving ValidationError in tests/test_integration_escrow.py.
# 2025-04-09: v1.12.0 (The Void):
#           - Implemented dispatcher functions: create_escrow_for_order, check_and_confirm_payment,
#             sign_order_release, broadcast_release_transaction, resolve_dispute.
#           - Added _get_specific_escrow_service helper for dynamic module loading based on currency.
#           - Removed NotImplementedError stubs for broadcast and resolve functions.
#           - Added basic error handling (ImportError, AttributeError, EscrowError, CryptoProcessingError) in dispatchers.
#           - Assumes corresponding functions exist in specific service modules (e.g., bitcoin_escrow_service.create_escrow).
# 2025-04-09: v1.1.4 (The Void):
#           - REVERT/FIX: _get_market_fee_percentage now returns default fee for missing/None config, raises RuntimeError on DB errors. Aligns with updated test v1.1.4.
# --- Previous revisions omitted ---

import logging
import secrets
import importlib # Added for dynamic imports
from types import ModuleType # Added for type hinting dynamic modules
from datetime import timedelta, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from typing import Optional, Tuple, Dict, Any, Final, TYPE_CHECKING, Protocol, List, runtime_checkable, Union

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist, NON_FIELD_ERRORS

# Use TYPE_CHECKING to avoid circular imports / runtime issues for type hints
if TYPE_CHECKING:
    from store.models import Order, CryptoPayment, GlobalSettings as GlobalSettingsModel, OrderStatus as OrderStatusChoices, EscrowType as EscrowTypeChoices # Added EscrowTypeChoices
    from django.contrib.auth.models import AbstractUser # A common base
    # Define a more specific type alias for User model type hinting
    UserModel = AbstractUser # Alias for User model type hinting
    # Import ledger service protocol if defined
    # from ledger.services import LedgerServiceInterface

# --- Model Imports (ensure these are needed by helpers, or move specific imports to specific services) ---
User = get_user_model() # Keep runtime User fetch

try:
    # Runtime imports needed by some helper functions
    # Ensure EscrowType is imported for use in dispatchers
    from store.models import GlobalSettings, Order, CryptoPayment, OrderStatus as OrderStatusChoices, EscrowType as EscrowTypeChoices # Added EscrowTypeChoices
    from store.exceptions import EscrowError, CryptoProcessingError # Assume these are defined elsewhere or move EscrowError here
    # Note: Dependencies on specific crypto services (monero_service, etc.) should NOT be here.
    #       Dependencies on ledger_service and notifications should also be carefully considered
    #       if they are needed directly by these common utils.
    # from ledger import services as ledger_service
    # from ledger.services import InsufficientFundsError, InvalidLedgerOperationError
    # from notifications.services import create_notification # <-- Test expects this sometimes, but it's not defined here.
    # from notifications.exceptions import NotificationError
    pass # Placeholder if no specific runtime imports needed right now

except ImportError as e:
    logging.basicConfig(level=logging.CRITICAL)
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL IMPORT ERROR in common_escrow_utils.py: {e}. Check dependencies/paths/installations.")
    raise ImportError(f"Failed to import critical modules in common_escrow_utils.py: {e}") from e
except Exception as e:
    logging.basicConfig(level=logging.CRITICAL)
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"Unexpected error during common_escrow_utils imports: {e}", exc_info=True)
    raise


# --- Custom Exceptions (Consider moving to a central store/exceptions.py) ---
class PostBroadcastUpdateError(EscrowError):
    """Indicates a critical failure updating internal state after a successful broadcast."""
    def __init__(self, message, original_exception=None, tx_hash=None):
        self.tx_hash = tx_hash
        self.original_exception = original_exception
        full_message = f"{message} (Broadcast TX: {tx_hash or 'N/A'})"
        # Ensure the base class EscrowError is initialized correctly
        super().__init__(full_message)


# --- Constants ---
# Ledger Transaction Types
LEDGER_TX_DEPOSIT: Final = 'DEPOSIT'
LEDGER_TX_ESCROW_FUND_DEBIT: Final = 'ESCROW_FUND_DEBIT'
LEDGER_TX_ESCROW_RELEASE_VENDOR: Final = 'ESCROW_RELEASE_VENDOR'
LEDGER_TX_ESCROW_RELEASE_BUYER: Final = 'ESCROW_RELEASE_BUYER'
LEDGER_TX_DISPUTE_RESOLUTION_BUYER: Final = 'DISPUTE_RESOLUTION_BUYER'
LEDGER_TX_DISPUTE_RESOLUTION_VENDOR: Final = 'DISPUTE_RESOLUTION_VENDOR'
LEDGER_TX_MARKET_FEE: Final = 'MARKET_FEE' # Used for both purchase and deposit fees

# User Attribute Names (for consistency)
ATTR_BTC_MULTISIG_PUBKEY: Final = 'btc_multisig_pubkey'
ATTR_XMR_MULTISIG_INFO: Final = 'xmr_multisig_info'
ATTR_ETH_MULTISIG_OWNER_ADDRESS: Final = 'eth_multisig_owner_address'
ATTR_BTC_WITHDRAWAL_ADDRESS: Final = 'btc_withdrawal_address'
ATTR_XMR_WITHDRAWAL_ADDRESS: Final = 'xmr_withdrawal_address'
ATTR_ETH_WITHDRAWAL_ADDRESS: Final = 'eth_withdrawal_address'

# Order Attribute Names
ATTR_BTC_REDEEM_SCRIPT: Final = 'btc_redeem_script'
ATTR_BTC_ESCROW_ADDRESS: Final = 'btc_escrow_address'
ATTR_XMR_MULTISIG_WALLET_NAME: Final = 'xmr_multisig_wallet_name'
ATTR_XMR_MULTISIG_INFO_ORDER: Final = 'xmr_multisig_info' # Note: Same name as user attr for XMR
ATTR_ETH_ESCROW_ADDRESS: Final = 'eth_escrow_contract_address' # Corrected attribute name based on models.py


# Define a basic protocol for expected crypto service methods (can be expanded)
# This helps type checking in the individual escrow services that will use specific crypto services.
@runtime_checkable
class CryptoServiceInterface(Protocol):
    # --- Escrow Creation ---
    def create_monero_multisig_wallet(self, participant_infos: list, order_guid: str, threshold: int) -> Dict[str, Any]: ...
    def create_btc_multisig_address(self, participant_pubkeys_hex: list, threshold: int) -> Dict[str, Any]: ... # Corrected arg name
    # def create_eth_gnosis_safe(self, owner_addresses: list, threshold: int) -> Dict[str, Any]: ... # Example ETH

    # --- Payment Confirmation ---
    # Returns native/atomic amount
    def scan_for_payment_confirmation(self, payment: 'CryptoPayment') -> Optional[Tuple[bool, Decimal, int, Optional[str]]]: ...

    # --- Unit Conversion (Essential for bridging service logic and ledger/logging) ---
    # These might return Decimal or raise errors on failure
    def satoshis_to_btc(self, satoshis: int) -> Decimal: ... # Example for BTC
    def piconero_to_xmr(self, piconero: int) -> Decimal: ... # Example for XMR
    def wei_to_eth(self, wei: int) -> Decimal: ... # Example for ETH
    # Add corresponding standard-to-atomic if needed elsewhere
    # def btc_to_satoshis(self, btc: Decimal) -> int: ...
    # def xmr_to_piconero(self, xmr: Decimal) -> int: ...
    # def eth_to_wei(self, eth: Decimal) -> int: ...

    # --- Release Preparation ---
    def prepare_btc_release_tx(self, order: 'Order', vendor_payout_amount_btc: Decimal, vendor_address: str) -> Optional[str]: ... # Expects standard amount
    def prepare_xmr_release_tx(self, order: 'Order', vendor_payout_amount_xmr: Decimal, vendor_address: str) -> Optional[str]: ... # Expects standard amount
    # def prepare_eth_release_tx(self, order: 'Order', ...) -> Optional[str]: ... # Example ETH

    # --- Release Signing (Actual implementation in crypto services) ---
    # Changed signature to match bitcoin_service.py v1.5.10 definition
    def sign_btc_multisig_tx(self, psbt_base64: str, private_key_wif: Optional[str] = None) -> Optional[str]: ... # Example BTC
    def sign_xmr_multisig_tx(self, order: 'Order', unsigned_tx_data: str, private_key_info: str, signer_role: str) -> Dict[str, Any]: ... # Example XMR
    # def sign_eth_multisig_tx(self, ... ) -> Dict[str, Any]: ... # Example ETH

    # --- Release Finalization/Broadcast ---
    def finalize_and_broadcast_btc_release(self, order: 'Order', current_psbt_base64: str) -> Optional[str]: ...
    def finalize_and_broadcast_xmr_release(self, order: 'Order', current_txset_hex: str) -> Optional[str]: ...
    # def finalize_and_broadcast_eth_release(self, order: 'Order', ...) -> Optional[str]: ... # Example ETH

    # --- Dispute Resolution ---
    # Expects standard amounts
    def create_and_broadcast_dispute_tx(self, order: 'Order', buyer_payout_amount_btc: Optional[Decimal] = None, buyer_address: Optional[str] = None, vendor_payout_amount_btc: Optional[Decimal] = None, vendor_address: Optional[str] = None, buyer_payout_amount_xmr: Optional[Decimal] = None, vendor_payout_amount_xmr: Optional[Decimal] = None, moderator_key_info: Optional[Any] = None) -> Optional[str]: ... # Consolidated example


# --- Loggers ---
logger = logging.getLogger(__name__) # Logger for common utils
security_logger = logging.getLogger('django.security') # Keep access to security logger


# --- Common Helper Functions ---

_market_user_cache: Optional['UserModel'] = None
def get_market_user() -> 'UserModel':
    """
    Gets the designated Market User instance from settings. Caches the result.
    Raises ObjectDoesNotExist if not found or configured, or RuntimeError if setting missing or DB error.
    """
    global _market_user_cache
    if _market_user_cache:
        return _market_user_cache

    market_username = getattr(settings, 'MARKET_USER_USERNAME', None)
    if not market_username:
        logger.critical("CRITICAL: settings.MARKET_USER_USERNAME is not defined.")
        raise RuntimeError("Market user username not configured in settings.")
    try:
        user: 'UserModel' = User.objects.get(username=market_username)
        _market_user_cache = user
        logger.info(f"Market user '{market_username}' loaded and cached.")
        return user
    except User.DoesNotExist:
        logger.critical(f"CRITICAL: Market user '{market_username}' not found in database.")
        raise # Re-raise ObjectDoesNotExist
    except Exception as e:
        logger.exception(f"Unexpected error fetching market user '{market_username}': {e}")
        raise RuntimeError(f"Database error fetching market user '{market_username}'.") from e


def _get_currency_precision(currency: str) -> int:
    """
    Returns the number of decimal places for ledger/calculations based on currency.
    Raises ValueError if currency is not supported/mapped.
    """
    precision_map: Dict[str, int] = {
        'XMR': 12,
        'BTC': 8,
        'ETH': 18, # Example
    }
    precision = precision_map.get(currency.upper())
    if precision is None:
        logger.error(f"Unsupported currency '{currency}' encountered in _get_currency_precision.")
        raise ValueError(f"Unsupported currency for precision: {currency}")
    return precision


def _get_atomic_to_standard_converter(crypto_service: Optional[CryptoServiceInterface], currency: str) -> Optional[callable]:
    """ Gets the appropriate atomic-to-standard conversion function from the crypto service (if provided). """
    if not crypto_service: return None # Handle case where service isn't needed/provided for fallback
    conversion_method_map = {
        'BTC': 'satoshis_to_btc',
        'XMR': 'piconero_to_xmr',
        'ETH': 'wei_to_eth',
    }
    method_name = conversion_method_map.get(currency.upper())
    if method_name and hasattr(crypto_service, method_name):
        return getattr(crypto_service, method_name)
    logger.warning(f"No specific converter method '{method_name}' found for {currency} on {type(crypto_service).__name__}.")
    return None


def _convert_atomic_to_standard(amount_atomic: Decimal, currency: str, crypto_service: Optional[CryptoServiceInterface]) -> Decimal:
    """ Converts an atomic amount (Decimal) to standard units using the crypto service method or fallback precision. """
    log_prefix = f"(_convert_atomic_to_std for {currency})"
    if amount_atomic is None:
        raise ValueError("Cannot convert None atomic amount.")
    converter = _get_atomic_to_standard_converter(crypto_service, currency)
    if converter:
        try:
            atomic_int = int(amount_atomic)
            standard_amount = converter(atomic_int)
            if not isinstance(standard_amount, Decimal):
                 standard_amount = Decimal(str(standard_amount))
            return standard_amount
        except (TypeError, ValueError, InvalidOperation) as conv_err:
             logger.error(f"{log_prefix}: Error using {getattr(converter,'__name__','N/A')}: {conv_err}. Falling back.", exc_info=True)
    # Fallback logic using precision
    try:
        precision = _get_currency_precision(currency)
        divisor = Decimal(f'1e{precision}')
        if divisor == 0:
            raise ValueError(f"Invalid precision {precision} for {currency}.")
        if not isinstance(amount_atomic, Decimal):
            amount_atomic = Decimal(str(amount_atomic))
        standard_amount = (amount_atomic / divisor).quantize(Decimal(f'1e-{precision}'), rounding=ROUND_DOWN)
        logger.debug(f"{log_prefix}: Fallback conversion: {amount_atomic} atomic -> {standard_amount} standard")
        return standard_amount
    except ValueError as precision_err:
        logger.error(f"{log_prefix}: Fallback failed: {precision_err}")
        raise EscrowError(f"Cannot convert unsupported currency {currency}.") from precision_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected fallback error: {e}")
        raise EscrowError("Unexpected conversion error.") from e


def _get_market_fee_percentage(currency: str) -> Decimal:
    """
    Gets the market fee percentage for the specified currency from GlobalSettings.
    Returns the default fee from settings if the specific currency fee is missing or None in GlobalSettings.
    Raises ValueError if a fee is found but has an invalid format.
    Raises RuntimeError if GlobalSettings cannot be accessed at all.
    """
    # Prepare default fee first (used if specific fee is missing/None)
    default_fee = getattr(settings, 'DEFAULT_MARKET_FEE_PERCENTAGE', Decimal('2.5'))
    try:
        if not isinstance(default_fee, Decimal):
             default_fee = Decimal(str(default_fee))
        if not (Decimal('0.0') <= default_fee <= Decimal('100.0')):
             logger.warning(f"DEFAULT_MARKET_FEE_PERCENTAGE setting ('{settings.DEFAULT_MARKET_FEE_PERCENTAGE}') out of range 0-100. Clamping.")
             default_fee = max(Decimal('0.0'), min(Decimal('100.0'), default_fee))
    except (InvalidOperation, TypeError, ValueError):
        logger.error(f"Invalid format for settings.DEFAULT_MARKET_FEE_PERCENTAGE ('{settings.DEFAULT_MARKET_FEE_PERCENTAGE}'). Using hardcoded 2.5%.")
        default_fee = Decimal('2.5') # Hardcoded fallback if setting is unusable

    # Check if GlobalSettings model is available (import check)
    if 'GlobalSettings' not in globals():
        msg = "GlobalSettings model not imported correctly. Cannot determine market fee."
        logger.critical(msg)
        raise RuntimeError(msg) # Critical failure if model isn't loaded

    # Try to access GlobalSettings and the specific fee
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        fee_attr = f'market_fee_percentage_{currency.lower()}'
        marker = object()
        fee_value = getattr(gs, fee_attr, marker)

        # FIX v1.1.4: Return default fee if attribute is missing or None
        if fee_value is marker or fee_value is None:
            logger.warning(f"Market fee percentage not configured or is None for currency {currency} (attribute '{fee_attr}'). Using default fee {default_fee}%.")
            return default_fee

        # If attribute exists and is not None, validate/convert it
        if isinstance(fee_value, Decimal):
            if not (Decimal('0.0') <= fee_value <= Decimal('100.0')):
                 logger.warning(f"Market fee for {currency} ({fee_value}%) from GlobalSettings is outside 0-100 range. Clamping.")
                 fee_value = max(Decimal('0.0'), min(Decimal('100.0'), fee_value))
            return fee_value
        else:
            # Try converting non-Decimal value, raise ValueError on failure
            try:
                fee_decimal = Decimal(str(fee_value))
                if not (Decimal('0.0') <= fee_decimal <= Decimal('100.0')):
                     logger.warning(f"Converted market fee for {currency} ({fee_decimal}%) is outside 0-100 range. Clamping.")
                     fee_decimal = max(Decimal('0.0'), min(Decimal('100.0'), fee_decimal))
                logger.debug(f"Converted stored fee '{fee_value}' to Decimal {fee_decimal} for {currency}.")
                return fee_decimal
            except (InvalidOperation, TypeError, ValueError) as conv_err:
                msg = f"Invalid market fee percentage format configured for currency {currency} (value: '{fee_value}', field: '{fee_attr}')."
                logger.error(msg)
                raise ValueError(msg) from conv_err # Raise specific error if format is bad

    except ObjectDoesNotExist:
        # FIX v1.1.4: Raise RuntimeError if GlobalSettings row is missing
        msg = "GlobalSettings entry not found (should be singleton). Cannot determine fee configuration."
        logger.critical(msg)
        raise RuntimeError(msg)
    except Exception as e:
        # FIX v1.1.4: Raise RuntimeError for other unexpected DB errors
        msg = f"Unexpected database error accessing GlobalSettings for market fee: {e}"
        logger.exception(msg)
        raise RuntimeError(msg) from e


def _get_withdrawal_address(user: 'UserModel', currency: str) -> str:
    """
    Gets the pre-configured withdrawal address for the user for a given currency.
    Raises ValueError if address attribute is missing, address is empty/None, or currency is unsupported.
    """
    if not isinstance(user, User):
        msg = f"Invalid user object type passed to _get_withdrawal_address: {type(user)}"
        logger.error(msg)
        raise ValueError(msg)

    address_attribute_map = {
        'BTC': ATTR_BTC_WITHDRAWAL_ADDRESS,
        'XMR': ATTR_XMR_WITHDRAWAL_ADDRESS,
        'ETH': ATTR_ETH_WITHDRAWAL_ADDRESS,
    }
    upper_currency = currency.upper()
    addr_attr = address_attribute_map.get(upper_currency)

    if not addr_attr:
        msg = f"Unsupported currency for withdrawal address: {currency}"
        logger.error(msg + f" (User: {user.username})")
        raise ValueError(msg)

    if not hasattr(user, addr_attr):
        msg = f"User model {type(user).__name__} missing attribute '{addr_attr}' for {currency} withdrawals."
        logger.critical(msg + f" (User: {user.username})")
        raise ValueError(msg)

    address = getattr(user, addr_attr, None)

    if not address or not isinstance(address, str) or not address.strip():
        msg = f"User {user.username} missing valid withdrawal address for {upper_currency}"
        logger.error(msg + f" (Field checked: '{addr_attr}')")
        raise ValueError(msg)

    address = address.strip()
    min_len = 25 # Basic sanity check
    if len(address) < min_len:
        logger.warning(f"Withdrawal address for {user.username} ({currency}: '{address[:15]}...') seems unusually short (less than {min_len} chars).")

    logger.debug(f"Retrieved withdrawal address for {user.username} ({currency}): {address[:10]}...")
    return address


def _check_order_timeout(order: 'Order') -> bool:
    """
    Internal helper: Checks and cancels timed-out PENDING_PAYMENT orders atomically.
    Returns True if cancelled by this call, False otherwise. Uses OrderStatusChoices.
    Requires 'create_notification' to be available in the calling scope if notifications are desired.
    """
    if not isinstance(order, Order):
        logger.warning(f"_check_order_timeout received invalid object: {type(order)}")
        return False

    if 'OrderStatusChoices' not in globals():
        logger.error("_check_order_timeout cannot function: OrderStatusChoices not defined/imported.")
        return False

    if order.status == OrderStatusChoices.PENDING_PAYMENT and order.payment_deadline and timezone.now() > order.payment_deadline:
        log_prefix = f"Order {order.id} (TimeoutCheck)"
        logger.info(f"{log_prefix}: Payment deadline {order.payment_deadline} passed. Attempting cancellation.")

        try:
            with transaction.atomic():
                updated_count = Order.objects.filter(
                    pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT
                ).update(
                    status=OrderStatusChoices.CANCELLED_TIMEOUT,
                    updated_at=timezone.now()
                )

                if updated_count > 0:
                    logger.info(f"{log_prefix}: Successfully cancelled due to payment timeout. Status -> {OrderStatusChoices.CANCELLED_TIMEOUT}")
                    security_logger.warning(f"Order {order.id} automatically cancelled due to payment timeout.")
                    order.refresh_from_db(fields=['status', 'updated_at'])

                    # --- Notification Sending Placeholder ---
                    # if 'create_notification' in globals():
                    #     try:
                    #         ... (notification logic) ...
                    #     except Exception as notify_e:
                    #         logger.error(...)
                    # else:
                    #     logger.warning(...)
                    # --- End Notification Sending Placeholder ---

                    return True
                else:
                    logger.info(f"{log_prefix}: Order status was not '{OrderStatusChoices.PENDING_PAYMENT}' during atomic update.")
                    return False
        except Exception as e:
            logger.exception(f"{log_prefix}: Error during timeout cancellation database update for Order {order.id}: {e}")
            return False

    return False


# --- Dynamic Service Loading Helper ---

_specific_service_cache: Dict[str, ModuleType] = {}

def _get_specific_escrow_service(currency: str, escrow_type: str) -> ModuleType:
    """
    Dynamically imports and returns the specific escrow service module for the
    given currency AND escrow type (e.g., 'MULTISIG', 'BASIC').
    Caches the imported module.
    Raises ImportError if the module cannot be imported.
    Raises ValueError if the currency or escrow_type combination is not supported/mapped.
    """
    upper_currency = currency.upper()
    # Ensure escrow_type is valid from choices if EscrowTypeChoices is available
    if 'EscrowTypeChoices' in globals():
        # FIX: Compare lowercase escrow_type against lowercase EscrowTypeChoices.values
        if not isinstance(escrow_type, str) or escrow_type.lower() not in EscrowTypeChoices.values:
            raise ValueError(f"Invalid or unsupported escrow_type: '{escrow_type}'. Must be one of {EscrowTypeChoices.values}")
    # If EscrowTypeChoices not loaded, skip validation (might happen during startup/test?)
    # Convert to upper *after* validation for map lookup
    upper_escrow_type = escrow_type.upper()

    # Use combined key for cache and lookup
    service_key = f"{upper_currency}-{upper_escrow_type}"

    if service_key in _specific_service_cache:
        return _specific_service_cache[service_key]

    # --- Service Map (FIX APPLIED HERE) ---
    service_module_map = {
        # Bitcoin
        'BTC-MULTISIG': 'store.services.bitcoin_escrow_service',
        'BTC-BASIC': 'store.services.simple_bitcoin_escrow_service',
        # Monero
        'XMR-MULTISIG': 'store.services.monero_escrow_service',
        'XMR-BASIC': 'store.services.simple_monero_escrow_service',
        # Ethereum
        'ETH-MULTISIG': 'store.services.ethereum_escrow_service', # RE-ENABLED (Fix for test failure)
        'ETH-BASIC': 'store.services.simple_ethereum_escrow_service',
    }
    # --- End Service Map ---

    module_name = service_module_map.get(service_key)
    if not module_name:
        msg = f"No specific escrow service module mapped for combination: Currency='{currency}', Type='{escrow_type}'"
        logger.error(msg)
        raise ValueError(msg)

    try:
        module = importlib.import_module(module_name)
        _specific_service_cache[service_key] = module
        logger.debug(f"Dynamically loaded escrow service module '{module_name}' for {service_key}.")
        return module
    except ImportError as e:
        msg = f"Failed to import specific escrow service module '{module_name}' for {service_key}: {e}"
        logger.exception(msg)
        # Raise ImportError to indicate the module itself is missing or has issues
        raise ImportError(msg) from e


# --- Main Escrow Service Dispatcher Functions ---

def create_escrow_for_order(order: 'Order') -> None:
    """
    Dispatcher: Creates the necessary escrow setup (address, contract, etc.) for an order
    by calling the appropriate currency-specific and type-specific service.
    Raises EscrowError, CryptoProcessingError, ValueError, ImportError.
    """
    log_prefix = f"Order {order.id} (CreateEscrow)"
    if not order or not order.selected_currency or not order.escrow_type:
        raise ValueError(f"{log_prefix}: Invalid order or missing currency/escrow_type for escrow creation.")

    currency = order.selected_currency
    escrow_type = order.escrow_type # Get escrow type from order
    logger.info(f"{log_prefix}: Dispatching escrow creation for Currency={currency}, Type={escrow_type}.")

    try:
        # Get service based on currency AND type
        specific_service = _get_specific_escrow_service(currency, escrow_type)
        if hasattr(specific_service, 'create_escrow'):
            # Assuming the specific service function handles internal logic,
            # including updating the Order/CryptoPayment models and logging.
            specific_service.create_escrow(order)
            logger.info(f"{log_prefix}: Escrow creation delegated to {specific_service.__name__}.create_escrow.")
        else:
            msg = f"Function 'create_escrow' not found in module {specific_service.__name__} for {currency}-{escrow_type}."
            logger.error(msg)
            raise AttributeError(msg)

    except (ImportError, ValueError, AttributeError) as e:
        # Errors related to finding/loading the service or function
        logger.error(f"{log_prefix}: Failed to dispatch escrow creation: {e}")
        raise EscrowError(f"Failed to initialize escrow service for {currency}-{escrow_type}: {e}") from e
    except (CryptoProcessingError, EscrowError) as e:
        # Errors originating from the specific service implementation
        logger.error(f"{log_prefix}: Escrow creation failed in specific service ({currency}-{escrow_type}): {e}", exc_info=True)
        raise # Re-raise the specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during escrow creation dispatch for {currency}-{escrow_type}: {e}")
        raise EscrowError("An unexpected error occurred during escrow creation.") from e


def check_and_confirm_payment(payment_id: Union[int, str, CryptoPayment]) -> bool:
    """
    Dispatcher: Checks for payment confirmation for a CryptoPayment by calling the specific service
    based on the related order's currency AND escrow type.
    Handles ledger updates and order status changes upon confirmation.
    Returns True if confirmed successfully by this call, False otherwise.
    Raises EscrowError, CryptoProcessingError, ValueError, ImportError, ObjectDoesNotExist.
    """
    log_prefix = f"Payment Check (ID: {payment_id})"
    payment: Optional['CryptoPayment'] = None # Define for access in error blocks
    order: Optional['Order'] = None
    try:
        if isinstance(payment_id, CryptoPayment):
            payment = payment_id
            log_prefix = f"Payment Check (ID: {payment.id})" # Update log prefix
        else:
            # Need to fetch related order to get escrow_type
            payment = CryptoPayment.objects.select_related('order').get(pk=payment_id)

        order = payment.order
        if not order:
            raise ObjectDoesNotExist(f"Order not found for Payment ID {payment.id}")

        currency = payment.currency
        escrow_type = order.escrow_type # Get type from related order
        if not escrow_type:
            raise ValueError(f"{log_prefix}: Order {order.id} missing escrow_type for payment check.")

        logger.info(f"{log_prefix}: Dispatching payment confirmation check for Currency={currency}, Type={escrow_type}.")

        specific_service = _get_specific_escrow_service(currency, escrow_type)
        check_func_name = 'check_confirm' # Use 'check_confirm' as defined in simple/multi-sig services
        if hasattr(specific_service, check_func_name):
            # Pass the payment_id to the specific service function
            payment_pk = payment.id
            confirmed = getattr(specific_service, check_func_name)(payment_pk)
            if confirmed:
                 logger.info(f"{log_prefix}: Payment confirmed by {specific_service.__name__}.{check_func_name}.")
            else:
                 logger.debug(f"{log_prefix}: Payment not confirmed by {specific_service.__name__}.{check_func_name}.")
            return confirmed
        else:
            # Try legacy name 'check_and_confirm_payment' just in case? Or enforce 'check_confirm'?
            # Sticking to 'check_confirm' for now based on recent service files.
            msg = f"Function '{check_func_name}' not found in module {specific_service.__name__} for {currency}-{escrow_type}."
            logger.error(msg)
            raise AttributeError(msg)

    except CryptoPayment.DoesNotExist:
        logger.error(f"{log_prefix}: CryptoPayment not found.")
        raise # Re-raise ObjectDoesNotExist
    except Order.DoesNotExist: # Catch if order is missing from payment somehow
        logger.error(f"{log_prefix}: Order not found for payment.")
        raise
    except (ImportError, ValueError, AttributeError) as e:
        cur = getattr(payment, 'currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.error(f"{log_prefix}: Failed to dispatch payment check: {e}")
        raise EscrowError(f"Failed to initialize payment check service for {cur}-{typ}: {e}") from e
    except (CryptoProcessingError, EscrowError) as e:
        cur = getattr(payment, 'currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.error(f"{log_prefix}: Payment check failed in specific service ({cur}-{typ}): {e}", exc_info=True)
        raise # Re-raise
    # except (InsufficientFundsError, InvalidLedgerOperationError) as e: # Uncomment if using ledger service
    #     logger.error(f"{log_prefix}: Ledger operation failed during confirmation: {e}", exc_info=True)
    #     raise EscrowError(f"Ledger update failed during payment confirmation: {e}") from e
    except Exception as e:
        cur = getattr(payment, 'currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.exception(f"{log_prefix}: Unexpected error during payment confirmation dispatch for {cur}-{typ}: {e}")
        raise EscrowError("An unexpected error occurred during payment confirmation.") from e


# Note: Type hint for key_info remains 'Any' as its structure depends on the crypto
def sign_order_release(order: 'Order', signing_user: 'UserModel', key_info: Any) -> Tuple[bool, bool]:
    """
    Dispatcher: Signs the release transaction for an order using the signing user's key info.
    Calls the appropriate MULTISIG currency-specific service.
    !! This is NOT applicable to BASIC escrow. !!
    Returns a tuple: (success: bool, is_fully_signed: bool)
    Raises EscrowError, CryptoProcessingError, ValueError, ImportError, AttributeError.
    """
    log_prefix = f"Order {order.id} (SignRelease by {signing_user.username})"
    if not order or not order.selected_currency or not order.escrow_type:
        raise ValueError(f"{log_prefix}: Invalid order or missing currency/escrow_type for signing release.")

    currency = order.selected_currency
    escrow_type = order.escrow_type

    # --- Explicitly handle BASIC escrow ---
    if escrow_type == EscrowTypeChoices.BASIC:
        logger.warning(f"{log_prefix}: Attempted to call sign_order_release for a BASIC escrow order. Signing is not applicable.")
        return False, False # Indicate failure, not fully signed (as it's irrelevant)
    # --- End BASIC handling ---

    # Proceed only if MULTISIG (or other future types needing signing)
    logger.info(f"{log_prefix}: Dispatching release signing for Currency={currency}, Type={escrow_type}.")

    try:
        specific_service = _get_specific_escrow_service(currency, escrow_type)
        sign_func_name = 'sign_order_release'
        if hasattr(specific_service, sign_func_name):
            # Assuming the specific service function handles crypto signing,
            # updates order.release_metadata, and returns (success, is_ready).
            success, is_ready = getattr(specific_service, sign_func_name)(order, signing_user, key_info)
            logger.info(f"{log_prefix}: Release signing delegated to {specific_service.__name__}.{sign_func_name}. Success: {success}, Ready: {is_ready}")
            return success, is_ready
        else:
            msg = f"Function '{sign_func_name}' not found in module {specific_service.__name__} for {currency}-{escrow_type}."
            logger.error(msg)
            raise AttributeError(msg)

    except (ImportError, ValueError, AttributeError) as e:
        logger.error(f"{log_prefix}: Failed to dispatch release signing: {e}")
        raise EscrowError(f"Failed to initialize release signing service for {currency}-{escrow_type}: {e}") from e
    except (CryptoProcessingError, EscrowError) as e:
        logger.error(f"{log_prefix}: Release signing failed in specific service ({currency}-{escrow_type}): {e}", exc_info=True)
        raise # Re-raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during release signing dispatch for {currency}-{escrow_type}: {e}")
        raise EscrowError("An unexpected error occurred during release signing.") from e


def broadcast_release_transaction(order_id: Union[int, str]) -> bool:
    """
    Dispatcher: Broadcasts the finalized release transaction for an order.
    Calls the appropriate currency-specific and type-specific service. Handles ledger updates and status changes.
    Returns True on successful broadcast AND post-broadcast updates, False otherwise.
    Raises EscrowError, CryptoProcessingError, ValueError, ImportError, ObjectDoesNotExist, PostBroadcastUpdateError.
    """
    log_prefix = f"Order ID {order_id} (BroadcastRelease)"
    order: Optional['Order'] = None # Define order here to access in except blocks if needed
    try:
        # Fetch order using the provided order_id
        order = Order.objects.select_related('buyer', 'vendor').get(pk=order_id)
        currency = order.selected_currency
        escrow_type = order.escrow_type # Get type from order
        if not currency or not escrow_type:
            raise ValueError(f"{log_prefix}: Order {order.id} missing selected currency or escrow type.")

        logger.info(f"{log_prefix}: Dispatching release broadcast for Currency={currency}, Type={escrow_type}.")

        specific_service = _get_specific_escrow_service(currency, escrow_type)
        if hasattr(specific_service, 'broadcast_release'):
            # Assuming the specific service function handles crypto broadcast, ledger updates,
            # order status changes, and returns True on success. It might raise
            # CryptoProcessingError on broadcast failure or PostBroadcastUpdateError on DB/ledger failure after broadcast.

            # FIX v1.12.1: Pass order_id instead of order object
            success = specific_service.broadcast_release(order_id=order_id) # Pass the ID

            if success:
                 logger.info(f"{log_prefix}: Release broadcast successfully handled by {specific_service.__name__}.broadcast_release.")
            else:
                 # This case might indicate a handled failure within the specific service (e.g., already broadcast)
                 logger.warning(f"{log_prefix}: Release broadcast call to {specific_service.__name__} returned False.")
            return success
        else:
            msg = f"Function 'broadcast_release' not found in module {specific_service.__name__} for {currency}-{escrow_type}."
            logger.error(msg)
            raise AttributeError(msg)

    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise
    except (ImportError, ValueError, AttributeError) as e:
        cur = getattr(order, 'selected_currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.error(f"{log_prefix}: Failed to dispatch release broadcast: {e}")
        raise EscrowError(f"Failed to initialize release broadcast service for {cur}-{typ}: {e}") from e
    except (CryptoProcessingError, PostBroadcastUpdateError, EscrowError) as e: # Catch specific errors from service
        cur = getattr(order, 'selected_currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.error(f"{log_prefix}: Release broadcast failed ({cur}-{typ}): {e}", exc_info=True)
        raise # Re-raise
    # except (InsufficientFundsError, InvalidLedgerOperationError) as e: # Uncomment if using ledger service
    #     logger.error(f"{log_prefix}: Ledger operation failed during broadcast: {e}", exc_info=True)
    #     # Decide if this should be PostBroadcastUpdateError if crypto succeeded
    #     raise EscrowError(f"Ledger update failed during release broadcast: {e}") from e
    except Exception as e:
        cur = getattr(order, 'selected_currency', 'N/A')
        typ = getattr(order, 'escrow_type', 'N/A')
        logger.exception(f"{log_prefix}: Unexpected error during release broadcast dispatch for {cur}-{typ}: {e}")
        raise EscrowError("An unexpected error occurred during release broadcast.") from e


def resolve_dispute(order: 'Order', moderator: 'UserModel', resolution_notes: str, release_to_buyer_percent: Union[int, float]) -> bool:
    """
    Dispatcher: Resolves a dispute by creating and broadcasting a dispute transaction.
    Calls the appropriate currency-specific and type-specific service. Handles ledger/status updates.
    Returns True on successful resolution and broadcast, False otherwise.
    Raises EscrowError, CryptoProcessingError, ValueError, ImportError, PostBroadcastUpdateError.
    """
    log_prefix = f"Order {order.id} (ResolveDispute by {moderator.username})"
    if not order or not order.selected_currency or not order.escrow_type:
        raise ValueError(f"{log_prefix}: Invalid order or missing currency/escrow_type for dispute resolution.")

    # Convert percentage to int if float (consider Decimal for precision later if needed)
    try:
        # Handle potential floating point precision issues if input is float
        if isinstance(release_to_buyer_percent, float):
             release_to_buyer_percent_dec = Decimal(str(release_to_buyer_percent))
        elif isinstance(release_to_buyer_percent, int):
             release_to_buyer_percent_dec = Decimal(release_to_buyer_percent)
        elif isinstance(release_to_buyer_percent, Decimal):
             release_to_buyer_percent_dec = release_to_buyer_percent
        else:
             raise TypeError("Percentage must be int, float, or Decimal.")

        # Validate range 0-100
        if not (Decimal('0.0') <= release_to_buyer_percent_dec <= Decimal('100.0')):
             raise ValueError("Percentage must be between 0.0 and 100.0.")

    except (TypeError, ValueError, InvalidOperation) as e:
        raise ValueError(f"Invalid release_to_buyer_percent format or value: {release_to_buyer_percent}. Must be convertible to Decimal 0-100.") from e


    currency = order.selected_currency
    escrow_type = order.escrow_type # Get type from order
    logger.info(f"{log_prefix}: Dispatching dispute resolution for Currency={currency}, Type={escrow_type} ({release_to_buyer_percent_dec}% to buyer).")

    try:
        specific_service = _get_specific_escrow_service(currency, escrow_type)
        resolve_func_name = 'resolve_dispute'
        if hasattr(specific_service, resolve_func_name):
            # Pass the validated Decimal percentage to the specific service
            success = getattr(specific_service, resolve_func_name)(
                order=order,
                moderator=moderator,
                resolution_notes=resolution_notes,
                release_to_buyer_percent=release_to_buyer_percent_dec # Pass Decimal
            )
            if success:
                 logger.info(f"{log_prefix}: Dispute resolution successfully handled by {specific_service.__name__}.{resolve_func_name}.")
            else:
                 logger.warning(f"{log_prefix}: Dispute resolution call to {specific_service.__name__} returned False.")
            return success
        else:
            msg = f"Function '{resolve_func_name}' not found in module {specific_service.__name__} for {currency}-{escrow_type}."
            logger.error(msg)
            raise AttributeError(msg)

    except (ImportError, ValueError, AttributeError) as e:
        logger.error(f"{log_prefix}: Failed to dispatch dispute resolution: {e}")
        raise EscrowError(f"Failed to initialize dispute resolution service for {currency}-{escrow_type}: {e}") from e
    except (CryptoProcessingError, PostBroadcastUpdateError, EscrowError) as e: # Catch specific errors from service
        logger.error(f"{log_prefix}: Dispute resolution failed ({currency}-{escrow_type}): {e}", exc_info=True)
        raise # Re-raise
    # except (InsufficientFundsError, InvalidLedgerOperationError) as e: # Uncomment if using ledger service
    #     logger.error(f"{log_prefix}: Ledger operation failed during dispute resolution: {e}", exc_info=True)
    #     # Decide if this should be PostBroadcastUpdateError if crypto succeeded
    #     raise EscrowError(f"Ledger update failed during dispute resolution: {e}") from e
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during dispute resolution dispatch for {currency}-{escrow_type}: {e}")
        raise EscrowError("An unexpected error occurred during dispute resolution.") from e

# <<< END OF FILE: backend/store/services/common_escrow_utils.py >>>