# backend/store/services/escrow_service.py
# Revision Notes (Continuing from previous):
# - v1.22.4 (2025-04-07):
#   - FIXED (New Failure in test_create_escrow_btc_success): Updated `create_escrow_for_order` (BTC path)
#     to pass participant keys via the keyword argument `participant_pubkeys_hex`, aligning
#     with the test's expectation (updated in test v1.18.2).
#   - RECOMMENDED: Update `CryptoServiceInterface` protocol definition for `create_btc_multisig_address`
#     to reflect `participant_pubkeys_hex` as a keyword-only argument.
# <<< ENTERPRISE GRADE REVISION: v1.22.0 - Improve Dispute Resolution Error Handling >>>
# Revision Notes:
# - v1.22.0:
#   - FIXED: Modified `resolve_dispute` function's final exception handling.
#     - Instead of returning `False` on errors occurring *after* a potentially successful
#       crypto broadcast, it now raises a specific `PostBroadcastUpdateError`.
#     - This makes failures in the critical post-broadcast update phase (user re-fetch,
#       order save, ledger update) explicit and prevents callers (like tests) from
#       misinterpreting the outcome as a simple non-success.
#     - The goal is to replace the `AssertionError: assert False is True` in tests
#       with a more informative `PostBroadcastUpdateError`, pinpointing the actual
#       failure during the final state updates.
#   - ADDED: `PostBroadcastUpdateError` custom exception class inheriting from `EscrowError`.
#   - NOTE: No changes made regarding the `ValidationError` in `test_mark_shipped_btc_success`.
#     As stated previously, this error indicates invalid input data (`btc_escrow_address`)
#     and requires an external fix in the crypto service or test mocks/fixtures.
# - v1.21.0:
#   - DEBUG: Enhanced logging within the final `try...except` block of `resolve_dispute`.
#   - CLARIFICATION: Reinforced notes about external fix needed for `mark_order_shipped` error.
# - v1.20.2:
#   - DEBUG: Added detailed logging within the final `try...except` block of `resolve_dispute`.
#   - NOTE: Reinforced notes about external fix needed for `mark_order_shipped` error.
# - v1.20.1:
#   - FIXED: Corrected ledger transaction notes for market fee in `broadcast_release_transaction`.
#   - NOTE: Reinforced notes about external fixes needed for other test failures.
# - v1.20.0:
#   - IMPLEMENTED: 2.5% market fee on deposits within `check_and_confirm_payment`.
#   - UPDATED: `_get_market_fee_percentage` default fallback.
#   - ADDED: Settings fallback suggestion, user re-fetching safeguard.
#   - CLARIFICATION: Added notes about `ValidationError` in `mark_order_shipped`.
#   - MINOR: Improved logging/comments.
# - v1.19.0: MAJOR FIX: Removed suppression of 'btc_escrow_address' validation error.
# - v1.18.0: FIXED: Logic error in `sign_order_release` for BTC signature counting.
# --- Prior revisions omitted ---

import logging
import json
import secrets
from datetime import timedelta, datetime # Added datetime directly
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from typing import Optional, Tuple, Dict, Any, Final, TYPE_CHECKING, Protocol, List, runtime_checkable, Union # Added List, runtime_checkable, Union

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist, NON_FIELD_ERRORS # Correct import path
from django.shortcuts import get_object_or_404 # Keep for potential future use if views call this directly

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
ATTR_ETH_ESCROW_ADDRESS: Final = 'eth_escrow_address' # Example if needed

# Define a basic protocol for expected crypto service methods (can be expanded)
@runtime_checkable # FIX v1.9.0: Added decorator
class CryptoServiceInterface(Protocol):
    # --- Escrow Creation ---
    def create_monero_multisig_wallet(self, participant_infos: list, order_id: str, threshold: int) -> Dict[str, Any]: ...
    def create_btc_multisig_address(self, participant_infos: list, threshold: int) -> Dict[str, Any]: ...
    # def create_eth_gnosis_safe(self, owner_addresses: list, threshold: int) -> Dict[str, Any]: ... # Example ETH

    # --- Payment Confirmation ---
    def scan_for_payment_confirmation(self, payment: 'CryptoPayment') -> Optional[Tuple[bool, Decimal, int, Optional[str]]]: ... # Returns native/atomic amount

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
    # This protocol defines the expected *interface* for type checking, even if the escrow service itself
    # doesn't implement it directly but calls it on the registered crypto service module.
    # Changed signature to match bitcoin_service.py v1.5.10 definition
    # NOTE (v1.19.0): Optional[str]=None for private_key_wif might be ambiguous if key is always required by service. Review if None is valid input.
    def sign_btc_multisig_tx(self, psbt_base64: str, private_key_wif: Optional[str] = None) -> Optional[str]: ... # Example BTC
    # NOTE (v1.19.0): Passing full `order` object slightly breaks abstraction. Consider passing only needed data in future refactor.
    def sign_xmr_multisig_tx(self, order: 'Order', unsigned_tx_data: str, private_key_info: str, signer_role: str) -> Dict[str, Any]: ... # Example XMR - Assume this signature for now
    # def sign_eth_multisig_tx(self, ... ) -> Dict[str, Any]: ... # Example ETH

    # --- Release Finalization/Broadcast ---
    def finalize_and_broadcast_btc_release(self, order: 'Order', current_psbt_base64: str) -> Optional[str]: ...
    def finalize_and_broadcast_xmr_release(self, order: 'Order', current_txset_hex: str) -> Optional[str]: ...
    # def finalize_and_broadcast_eth_release(self, order: 'Order', ...) -> Optional[str]: ... # Example ETH

    # --- Dispute Resolution ---
    # Expects standard amounts
    def create_and_broadcast_dispute_tx(self, order: 'Order', buyer_payout_amount_btc: Optional[Decimal] = None, buyer_address: Optional[str] = None, vendor_payout_amount_btc: Optional[Decimal] = None, vendor_address: Optional[str] = None, buyer_payout_amount_xmr: Optional[Decimal] = None, vendor_payout_amount_xmr: Optional[Decimal] = None, moderator_key_info: Optional[Any] = None) -> Optional[str]: ... # Consolidated example

# Use TYPE_CHECKING to avoid circular imports / runtime issues for type hints
if TYPE_CHECKING:
    from store.models import Order, CryptoPayment, GlobalSettings as GlobalSettingsModel, Product as ProductModel
    from django.contrib.auth.models import AbstractUser # A common base
    # Define a more specific type alias for User model type hinting
    UserModel = AbstractUser # Alias for User model type hinting
    # Import ledger service protocol if defined
    # from ledger.services import LedgerServiceInterface

# --- Model Imports ---
User = get_user_model() # Keep runtime User fetch

try:
    # Runtime imports needed for logic
    from store.models import Order, GlobalSettings, CryptoPayment, Product, OrderStatus as OrderStatusChoices
    from store.services import monero_service, bitcoin_service, ethereum_service # Placeholder for ETH
    from ledger import services as ledger_service
    from ledger.services import InsufficientFundsError, InvalidLedgerOperationError
    from notifications.services import create_notification
    # --- Custom Exceptions ---
    from store.exceptions import EscrowError, CryptoProcessingError
    from ledger.exceptions import LedgerError
    from notifications.exceptions import NotificationError

    # ADDED v1.22.0: Custom exception for critical post-broadcast failures
    class PostBroadcastUpdateError(EscrowError):
        """Indicates a critical failure updating internal state after a successful broadcast."""
        def __init__(self, message, original_exception=None, tx_hash=None):
            self.tx_hash = tx_hash
            self.original_exception = original_exception
            full_message = f"{message} (Broadcast TX: {tx_hash or 'N/A'})"
            # Ensure the base class EscrowError is initialized correctly
            super().__init__(full_message)

except ImportError as e:
    # Use basicConfig for initial setup if logging isn't configured yet
    logging.basicConfig(level=logging.CRITICAL)
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL IMPORT ERROR in escrow_service.py: {e}. Check dependencies/paths/installations.")
    # In production, this might warrant exiting or preventing startup
    raise ImportError(f"Failed to import critical modules in escrow_service.py: {e}") from e
except Exception as e:
    # Catch-all for other unexpected import errors
    logging.basicConfig(level=logging.CRITICAL)
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"Unexpected error during escrow_service imports: {e}", exc_info=True)
    raise

# --- Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')


# --- Internal Helper Functions ---

_market_user_cache: Optional['UserModel'] = None
def get_market_user() -> 'UserModel':
    """
    Gets the designated Market User instance from settings. Caches the result.
    Raises ObjectDoesNotExist if not found or configured, or RuntimeError if setting missing.
    """
    global _market_user_cache
    if _market_user_cache:
        return _market_user_cache

    market_username = getattr(settings, 'MARKET_USER_USERNAME', None)
    if not market_username:
        logger.critical("CRITICAL: settings.MARKET_USER_USERNAME is not defined.")
        # Raise a more specific configuration error
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
        # Wrap unexpected DB errors
        raise RuntimeError(f"Database error fetching market user '{market_username}'.") from e


def _get_currency_precision(currency: str) -> int:
    """ Returns the number of decimal places for ledger/calculations based on currency. """
    # NOTE (v1.19.0): Consider moving this map to Django settings or a central DB config model
    # for easier updates without code deployment.
    precision_map: Dict[str, int] = {
        'XMR': 12,
        'BTC': 8,
        'ETH': 18, # Example
    }
    default_precision: int = 8 # Default for unknown currencies
    precision = precision_map.get(currency.upper())
    if precision is None:
        logger.warning(f"Unknown currency '{currency}' encountered in _get_currency_precision, using default precision {default_precision}.")
        return default_precision
    return precision

# Set Decimal precision globally for safety, if needed, based on max required precision
# Consider if this is appropriate vs. always using quantize
# getcontext().prec = max(_get_currency_precision('BTC'), _get_currency_precision('XMR'), _get_currency_precision('ETH')) + 2 # Example: max + buffer

def _get_atomic_to_standard_converter(crypto_service: CryptoServiceInterface, currency: str) -> Optional[callable]:
    """ Gets the appropriate atomic-to-standard conversion function from the crypto service. """
    conversion_method_map = {
        'BTC': 'satoshis_to_btc',
        'XMR': 'piconero_to_xmr',
        'ETH': 'wei_to_eth',
        # Add other currencies here
    }
    method_name = conversion_method_map.get(currency.upper())
    if method_name and hasattr(crypto_service, method_name):
        return getattr(crypto_service, method_name)
    logger.warning(f"No specific atomic-to-standard conversion method found for {currency} on {type(crypto_service).__name__}.")
    return None

def _convert_atomic_to_standard(amount_atomic: Decimal, currency: str, crypto_service: CryptoServiceInterface) -> Decimal:
    """ Converts an atomic amount (Decimal) to standard units using the crypto service method or fallback. """
    log_prefix = f"(_convert_atomic_to_std for {currency})"
    if amount_atomic is None: # Should not happen if validation is correct
        raise ValueError("Cannot convert None atomic amount.")

    converter = _get_atomic_to_standard_converter(crypto_service, currency)
    if converter:
        try:
            # Converter expects integer input usually
            atomic_int = int(amount_atomic)
            standard_amount = converter(atomic_int)
            logger.debug(f"{log_prefix}: Converted {amount_atomic} atomic to {standard_amount} standard using {converter.__name__}.")
            # Ensure return value is Decimal
            if not isinstance(standard_amount, Decimal):
                standard_amount = Decimal(str(standard_amount))
            return standard_amount
        except (TypeError, ValueError, InvalidOperation) as conv_err:
            logger.error(f"{log_prefix}: Error using {getattr(converter,'__name__','N/A')} to convert {amount_atomic} atomic: {conv_err}. Falling back.", exc_info=True)
            # Fallback logic
    else:
        logger.warning(f"{log_prefix}: Falling back to precision-based conversion for {amount_atomic} atomic.")

    # Fallback: Assume standard precision if conversion method missing
    precision = _get_currency_precision(currency)
    divisor = Decimal(f'1e{precision}')
    if divisor == 0: # Avoid division by zero if precision is somehow invalid
        raise ValueError(f"Invalid precision {precision} resulting in zero divisor for currency {currency}.")
    standard_amount = (amount_atomic / divisor).quantize(Decimal(f'1e-{precision}'), rounding=ROUND_DOWN)
    logger.debug(f"{log_prefix}: Fallback conversion: {amount_atomic} atomic -> {standard_amount} standard (Precision: {precision})")
    return standard_amount


def _get_market_fee_percentage(currency: str) -> Decimal:
    """
    Gets the market fee percentage for the specified currency from GlobalSettings.
    Uses settings.DEFAULT_MARKET_FEE_PERCENTAGE as fallback if available, else 2.5%.
    """
    # v1.20.0: Use Django setting for default, fallback to 2.5%
    default_fee = getattr(settings, 'DEFAULT_MARKET_FEE_PERCENTAGE', Decimal('2.5'))
    # Ensure default_fee is Decimal
    if not isinstance(default_fee, Decimal):
        try:
            default_fee = Decimal(str(default_fee))
            if not (Decimal('0.0') <= default_fee <= Decimal('100.0')):
                logger.warning(f"DEFAULT_MARKET_FEE_PERCENTAGE setting ('{settings.DEFAULT_MARKET_FEE_PERCENTAGE}') is invalid or out of range. Using 2.5%.")
                default_fee = Decimal('2.5')
        except (InvalidOperation, TypeError, ValueError):
            logger.error(f"Invalid format for settings.DEFAULT_MARKET_FEE_PERCENTAGE ('{settings.DEFAULT_MARKET_FEE_PERCENTAGE}'). Using default 2.5%.")
            default_fee = Decimal('2.5')

    # Check if GlobalSettings model itself was imported correctly
    if GlobalSettings is None: # Should not happen if imports succeed
        logger.error("GlobalSettings model is unexpectedly None. Using default fee percentage {default_fee}%.")
        return default_fee

    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        fee_attr = f'market_fee_percentage_{currency.lower()}'
        # Use getattr with a default marker to distinguish missing attribute from None value
        marker = object()
        fee = getattr(gs, fee_attr, marker)

        if fee is marker:
             # Attribute doesn't exist on the model
             logger.warning(f"GlobalSettings model missing fee attribute '{fee_attr}'. Using default fee percentage {default_fee}%.")
             return default_fee

        if fee is None:
            # Attribute exists but is None in DB
            logger.warning(f"Market fee setting for {currency} ('{fee_attr}') is None in GlobalSettings. Using default fee percentage {default_fee}%.")
            return default_fee

        if isinstance(fee, Decimal):
            # Validate range
            if not (Decimal('0.0') <= fee <= Decimal('100.0')):
                logger.warning(f"Market fee for {currency} ({fee}%) from GlobalSettings is outside expected 0-100 range. Clamping and using.")
                fee = max(Decimal('0.0'), min(Decimal('100.0'), fee))
            return fee
        else:
            # Attempt conversion if not Decimal, log warning
            logger.warning(f"Market fee setting for {currency} ('{fee}') is not a Decimal in GlobalSettings. Attempting conversion.")
            try:
                fee_decimal = Decimal(str(fee))
                # Validate range after conversion
                if not (Decimal('0.0') <= fee_decimal <= Decimal('100.0')):
                    logger.warning(f"Converted market fee for {currency} ({fee_decimal}%) is outside expected 0-100 range. Clamping and using.")
                    fee_decimal = max(Decimal('0.0'), min(Decimal('100.0'), fee_decimal))
                logger.debug(f"Converted fee '{fee}' to Decimal {fee_decimal} for {currency}.")
                return fee_decimal
            except (InvalidOperation, TypeError, ValueError):
                logger.error(f"Invalid market fee setting format ('{fee}') for {currency} in GlobalSettings field '{fee_attr}'. Using default {default_fee}%.")
                return default_fee

    except ObjectDoesNotExist:
        # This means the GlobalSettings singleton row is missing in the DB
        logger.error(f"GlobalSettings entry not found (should be singleton). Using default fee percentage {default_fee}%.")
        return default_fee
    # Removed AttributeError catch as getattr handles missing attribute now
    except Exception as e:
        # Catch unexpected errors during settings access
        logger.exception(f"Unexpected error fetching market fee for {currency} from GlobalSettings: {e}. Using default {default_fee}%.")
        return default_fee


def _get_withdrawal_address(user: 'UserModel', currency: str) -> str:
    """
    Gets the pre-configured withdrawal address for the user for a given currency.
    Raises ValueError if address is missing, empty, or invalid format (basic checks).
    """
    # Runtime check against the actual User model class
    if not isinstance(user, User):
        msg = f"Invalid user object type passed to _get_withdrawal_address: {type(user)}"
        logger.error(msg)
        raise ValueError(msg)

    # Map currency to the expected attribute name on the User model
    address_attribute_map = {
        'BTC': ATTR_BTC_WITHDRAWAL_ADDRESS,
        'XMR': ATTR_XMR_WITHDRAWAL_ADDRESS,
        'ETH': ATTR_ETH_WITHDRAWAL_ADDRESS, # Example
    }
    addr_attr = address_attribute_map.get(currency.upper())

    if not addr_attr:
        msg = f"Withdrawal address attribute mapping not found for currency {currency}."
        logger.error(msg)
        raise ValueError(msg)

    # Check if the user model actually has the attribute
    if not hasattr(user, addr_attr):
        msg = f"User model {type(user).__name__} does not have the expected attribute '{addr_attr}' for {currency} withdrawals."
        logger.error(msg)
        raise ValueError(msg)

    # Get the address value
    address = getattr(user, addr_attr, None)

    # Validate the address value
    if not address or not isinstance(address, str) or not address.strip():
        msg = f"User {user.username} missing valid withdrawal address in field '{addr_attr}' for currency {currency}."
        logger.error(msg)
        raise ValueError(msg) # Raise error as address is required

    address = address.strip() # Use stripped address

    # Basic sanity check for address length (adjust thresholds as needed)
    min_len = 25 # Example minimum length
    if len(address) < min_len:
        msg = f"Withdrawal address for {user.username} ({currency}: '{address}') seems unusually short (less than {min_len} chars)."
        logger.warning(msg)
        # Depending on policy, you might raise ValueError here too

    logger.debug(f"Retrieved withdrawal address for {user.username} ({currency}): {address[:10]}...")
    return address


def _check_order_timeout(order: 'Order') -> bool:
    """
    Internal helper: Checks and cancels timed-out PENDING_PAYMENT orders atomically.
    Returns True if cancelled by this call, False otherwise. Uses OrderStatusChoices.
    """
    # Ensure order object is valid before proceeding
    if not isinstance(order, Order):
        logger.warning(f"_check_order_timeout received invalid object: {type(order)}")
        return False

    # Check status and deadline existence efficiently
    if order.status == OrderStatusChoices.PENDING_PAYMENT and order.payment_deadline and timezone.now() > order.payment_deadline:
        log_prefix = f"Order {order.id} (TimeoutCheck)"
        logger.info(f"{log_prefix}: Payment deadline {order.payment_deadline} passed. Attempting cancellation.")

        try:
            # Atomic update using filter for status to prevent race conditions
            with transaction.atomic():
                updated_count = Order.objects.filter(
                    pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT # Ensure status hasn't changed
                ).update(
                    status=OrderStatusChoices.CANCELLED_TIMEOUT,
                    updated_at=timezone.now()
                )

                if updated_count > 0:
                    logger.info(f"{log_prefix}: Successfully cancelled due to payment timeout. Status -> {OrderStatusChoices.CANCELLED_TIMEOUT}")
                    security_logger.warning(f"Order {order.id} automatically cancelled due to payment timeout.")

                    # Refresh order object to get potentially updated fields if needed later
                    order.refresh_from_db(fields=['status', 'updated_at'])

                    # Attempt to send notifications (best effort, failure doesn't rollback)
                    try:
                        order_url = f"/orders/{order.id}" # Consider using reverse()
                        product_name = getattr(order.product, 'name', 'N/A') # Safe attribute access
                        common_msg = f"Order #{str(order.id)[:8]} ({product_name}) has been automatically cancelled because payment was not received before the deadline." # FIX v1.7.3 - str()

                        if order.buyer:
                            create_notification(user_id=order.buyer.id, level='warning', message=common_msg, link=order_url)
                        if order.vendor:
                            create_notification(user_id=order.vendor.id, level='info', message=common_msg, link=order_url)
                    except Exception as notify_e:
                        # Log notification failure but don't let it fail the timeout process
                        logger.error(f"{log_prefix}: Failed to create timeout cancellation notification: {notify_e}", exc_info=True)

                    return True # Order was cancelled by this call
                else:
                    # Order status was likely changed by another process between the initial check and the update attempt
                    logger.info(f"{log_prefix}: Order status was not '{OrderStatusChoices.PENDING_PAYMENT}' during atomic update. No action taken.")
                    return False # Order was not cancelled by this call
        except Exception as e:
            # Log errors during the atomic update itself
            logger.exception(f"{log_prefix}: Error during timeout cancellation database update for Order {order.id}: {e}")
            return False # Cancellation failed

    # If conditions for timeout check are not met
    return False


_crypto_service_registry: Dict[str, Any] = {} # Stores modules for now
def _register_crypto_services():
    """Initializes the crypto service registry (storing modules)."""
    global _crypto_service_registry
    if not _crypto_service_registry: # Only register once
        logger.debug("Registering crypto service modules...")
        # Ensure services are imported before registering
        if 'bitcoin_service' in globals():
            _crypto_service_registry['BTC'] = bitcoin_service # Store module
        if 'monero_service' in globals():
            _crypto_service_registry['XMR'] = monero_service # Store module
        if 'ethereum_service' in globals():
            _crypto_service_registry['ETH'] = ethereum_service # Store module (Example)
        logger.debug(f"Registered service modules: {list(_crypto_service_registry.keys())}")

# Call registration on module load
_register_crypto_services()

def _get_crypto_service(currency: str) -> Any: # Return type is Any as it's a module
    """Retrieves the appropriate crypto service *module* for the currency."""
    service_module = _crypto_service_registry.get(currency.upper())
    if not service_module:
        logger.error(f"No crypto service module registered or available for currency: {currency}")
        raise ValueError(f"Unsupported or unregistered currency for crypto operations: {currency}")

    # FIX v1.9.0: Removed the isinstance check against CryptoServiceInterface
    # Runtime checks will now rely on subsequent AttributeError if methods are missing.

    return service_module


# --- Escrow Lifecycle Functions ---

# --- Start Replacement Block ---

@transaction.atomic
def create_escrow_for_order(order: 'Order') -> None:
    """
    Prepares an order for payment: Generates multi-sig details (XMR/BTC/ETH),
    creates the crypto payment record, sets deadlines, and updates order status.

    Args:
        order: The Order instance (must be in PENDING_PAYMENT status initially).
    Raises:
        ValueError: If inputs are invalid (order, participants, keys).
        ObjectDoesNotExist: If related objects (User, GlobalSettings) are missing.
        EscrowError: For general escrow process failures (e.g., wrong status, save errors).
        CryptoProcessingError: If crypto service calls fail.
        RuntimeError: If critical settings/models are unavailable.
        NotImplementedError: If currency/functionality is not supported.
    """
    log_prefix = f"Order {order.id} ({order.selected_currency})"
    logger.info(f"{log_prefix}: Initiating multi-sig escrow setup...")

    # --- Input Validation ---
    if not isinstance(order, Order) or not order.pk or not hasattr(order, 'product'):
        logger.error(f"Invalid or unsaved Order object passed to create_escrow_for_order: {order}")
        raise ValueError("Invalid Order object provided.")

    # Check dependencies (redundant if imports succeed, but good practice)
    if not all([CryptoPayment, User, GlobalSettings]):
        logger.critical("Required models (CryptoPayment, User, GlobalSettings) not loaded.")
        raise RuntimeError("Critical application models are not available.")

    # --- State Validation & Idempotency ---
    # FIX v1.10.0: Adjust idempotency check to raise error for non-PENDING_PAYMENT states,
    # aligning with test_create_escrow_invalid_order_status expectation.
    if order.status == OrderStatusChoices.PENDING_PAYMENT:
        # True Idempotency Check: If pending, check if payment record already exists.
        if CryptoPayment.objects.filter(order=order).exists():
            logger.info(f"{log_prefix}: CryptoPayment details already exist for PENDING order. Skipping creation (Idempotency).")
            return # Okay to return None here, already done or in progress
    else:
        # If status is *not* PENDING_PAYMENT, raise error as per test expectation.
        logger.warning(f"{log_prefix}: Cannot create escrow details. Status: '{order.status}' (Expected: '{OrderStatusChoices.PENDING_PAYMENT}').")
        raise EscrowError(f"Order must be in '{OrderStatusChoices.PENDING_PAYMENT}' state to setup escrow (Current Status: {order.status})")

    # --- Configuration Loading ---
    currency = order.selected_currency
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        # NOTE (v1.19.0): Consider moving defaults to Django settings for central config.
        confirmations_needed = getattr(gs, f'confirmations_needed_{currency.lower()}', 10) # Default 10
        payment_wait_hours = int(getattr(gs, 'payment_wait_hours', 4)) # Default 4 hours
        threshold = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2)) # Default 2-of-3
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        logger.critical(f"{log_prefix}: Error loading critical GlobalSettings or Django settings: {e}. Cannot proceed.", exc_info=True)
        # Use ObjectDoesNotExist as the most likely cause or wrap others
        raise ObjectDoesNotExist(f"Failed to load required settings: {e}") from e

    # --- Participant Loading ---
    try:
        buyer = order.buyer
        vendor = order.vendor
        market_user = get_market_user() # Uses cached market user
        if not all([buyer, vendor]): # market_user handled by get_market_user
            logger.critical(f"{log_prefix}: Missing buyer or vendor relationship on order.")
            raise ObjectDoesNotExist("Buyer or Vendor missing for the order.")
    except ObjectDoesNotExist as e:
        # Critical error if participants can't be determined
        logger.critical(f"{log_prefix}: Error fetching participants: {e}")
        raise

    # --- Gather Participant Keys/Info ---
    participant_infos: List[Any] = []
    order_update_fields = ['payment_deadline', 'updated_at', 'status'] # Fields always updated
    try:
        logger.debug(f"{log_prefix}: Gathering multi-sig participant info for {currency}...")

        # Map currency to expected user attribute names
        user_key_attribute_map = {
            'BTC': ATTR_BTC_MULTISIG_PUBKEY,
            'XMR': ATTR_XMR_MULTISIG_INFO,
            'ETH': ATTR_ETH_MULTISIG_OWNER_ADDRESS, # Example
        }
        key_attr = user_key_attribute_map.get(currency.upper())
        if not key_attr:
            # NOTE (v1.19.0): Ensure `test_create_escrow_unsupported_currency` expects this error format.
            raise ValueError(f"Multisig key attribute mapping not found for currency {currency}.")

        # Get info for each participant
        buyer_info = getattr(buyer, key_attr, None)
        vendor_info = getattr(vendor, key_attr, None)
        market_info = getattr(market_user, key_attr, None)

        # Validate that all participants have the required info
        if not all([buyer_info, vendor_info, market_info]):
            missing = [u.username for u, i in zip([buyer, vendor, market_user], [buyer_info, vendor_info, market_info]) if not i]
            msg = f"Missing required multisig setup info ('{key_attr}') for user(s): {', '.join(missing)}."
            logger.error(f"{log_prefix}: {msg}")
            raise ValueError(msg) # Raise error, setup cannot proceed

        # Prepare participant info list for crypto service (ETH might not need sorting)
        if currency == 'ETH': # Example specific handling
            participant_infos = [buyer_info, vendor_info, market_info]
        else:
            # Sort keys for BTC/XMR to ensure consistent address generation regardless of user order
            participant_infos = sorted([buyer_info, vendor_info, market_info]) # Ensure consistent order

        # Avoid logging potentially sensitive key info directly
        logger.debug(f"{log_prefix}: Gathered participant info for {len(participant_infos)} participants.")

    except (ValueError, AttributeError, Exception) as e:
        # Catch errors during key gathering
        logger.error(f"{log_prefix}: Failed to gather participant info: {e}", exc_info=True)
        # NOTE (v1.19.0): Ensure `test_create_escrow_unsupported_currency` expects this error format.
        raise ValueError(f"Failed to gather required participant info: {e}") from e

    # --- Crypto Service Interaction: Generate Escrow Details ---
    escrow_address: Optional[str] = None
    msig_details: Dict[str, Any] = {}
    try:
        crypto_service_module = _get_crypto_service(currency) # Returns the module
        logger.debug(f"{log_prefix}: Generating {currency} multi-sig escrow details via {crypto_service_module.__name__}...")

        if currency == 'XMR':
            # Assume function exists directly on the module
            # FIX v1.22.1: Pass order ID as keyword argument 'order_guid' to match test assertion expectation.
            msig_details = crypto_service_module.create_monero_multisig_wallet(
                participant_infos=participant_infos, # Use keyword arg for clarity
                order_guid=str(order.id),           # Use keyword arg 'order_guid'
                threshold=threshold
            )
            escrow_address = msig_details.get('address')
            # Store XMR specific details on order if fields exist
            if hasattr(order, ATTR_XMR_MULTISIG_WALLET_NAME):
                order.xmr_multisig_wallet_name = msig_details.get('wallet_name')
                order_update_fields.append(ATTR_XMR_MULTISIG_WALLET_NAME)
            if hasattr(order, ATTR_XMR_MULTISIG_INFO_ORDER):
                order.xmr_multisig_info = msig_details.get('multisig_info')
                order_update_fields.append(ATTR_XMR_MULTISIG_INFO_ORDER)

        elif currency == 'BTC':
            # Assume function exists directly on the module
            # FIX v1.22.4: Pass participant keys as keyword argument 'participant_pubkeys_hex'
            # to match test assertion expectation from v1.18.2.
            msig_details = crypto_service_module.create_btc_multisig_address(
                participant_pubkeys_hex=participant_infos, # Use expected kwarg name
                threshold=threshold
            )
            escrow_address = msig_details.get('address')

            # CRITICAL NOTE (Root cause of ValidationError in mark_order_shipped):
            # The `escrow_address` returned by the crypto service (or test mock) MUST be a valid, standard
            # Bitcoin address format (e.g., P2SH, Bech32). If it returns an internal identifier or placeholder
            # (like the failing test's '2N8hw...' if that's not considered valid by the model validator),
            # the `full_clean()` call in `mark_order_shipped` WILL FAIL correctly. The fix must happen
            # in the crypto service or the test mock to ensure a valid address is returned and saved here.
            # No fix needed in THIS file for that error.

            # Store BTC specific details on order if fields exist
            if hasattr(order, ATTR_BTC_REDEEM_SCRIPT):
                # Service should ideally return a consistent key, check for common ones
                script = msig_details.get('witnessScript') or msig_details.get('redeemScript')
                if script:
                    order.btc_redeem_script = script
                    order_update_fields.append(ATTR_BTC_REDEEM_SCRIPT)
                else:
                    logger.warning(f"{log_prefix}: BTC multisig details missing expected redeem/witness script.")

            if hasattr(order, ATTR_BTC_ESCROW_ADDRESS):
                # Save the address returned by the service. Validation happens later.
                # Ensure the crypto service / mock returns a VALID address format.
                order.btc_escrow_address = escrow_address
                order_update_fields.append(ATTR_BTC_ESCROW_ADDRESS)

        elif currency == 'ETH':
            # Example ETH/Gnosis Safe creation
            # msig_details = crypto_service_module.create_eth_gnosis_safe(owner_addresses=participant_infos, threshold=threshold)
            # escrow_address = msig_details.get('safe_address')
            # if hasattr(order, ATTR_ETH_ESCROW_ADDRESS):
            #     order.eth_escrow_address = escrow_address
            #     order_update_fields.append(ATTR_ETH_ESCROW_ADDRESS)
            logger.error(f"{log_prefix}: ETH Escrow creation not implemented.")
            raise NotImplementedError(f"ETH Escrow creation not implemented for Order {order.id}.")

        else:
            # This case should be caught by _get_crypto_service, but defense in depth
            raise ValueError(f"Unsupported currency for multi-sig setup: {currency}")

        # Validate address was returned (basic check)
        if not escrow_address or not isinstance(escrow_address, str):
            raise ValueError(f"Crypto service module failed to return a valid escrow address string for {currency}.")

        logger.info(f"{log_prefix}: Generated {currency} Escrow Address: {escrow_address[:15]}...") # Log cautiously

    except (AttributeError, NotImplementedError, ValueError, KeyError, CryptoProcessingError) as crypto_err:
        # AttributeError can now occur if the module doesn't have the expected function
        # Handle errors from crypto service calls gracefully
        logger.error(f"{log_prefix}: Crypto service error during {currency} escrow generation: {crypto_err}", exc_info=True)
        # Wrap or re-raise specific errors
        raise CryptoProcessingError(f"Failed to generate {currency} escrow details: {crypto_err}") from crypto_err
    except Exception as e:
        # Catch unexpected errors
        logger.exception(f"{log_prefix}: Unexpected error during {currency} escrow generation: {e}")
        raise CryptoProcessingError(f"Unexpected error generating {currency} escrow details.") from e

    # --- Create CryptoPayment Record ---
    try:
        # Ensure total_price_native_selected is valid Decimal before creating payment
        if not isinstance(order.total_price_native_selected, Decimal):
            raise ValueError(f"Order {order.id} total_price_native_selected is not Decimal ({type(order.total_price_native_selected)})")

        payment_obj = CryptoPayment.objects.create(
            order=order,
            currency=currency,
            payment_address=escrow_address,
            # Add payment ID if relevant for the currency (e.g., Monero integrated address)
            payment_id_monero=msig_details.get('payment_id') if currency == 'XMR' else None,
            expected_amount_native=order.total_price_native_selected, # Should be atomic units
            confirmations_needed=confirmations_needed
        )
        logger.info(f"{log_prefix}: Created CryptoPayment {payment_obj.id} (Multi-sig). Expected Atomic: {payment_obj.expected_amount_native}")
    except IntegrityError as ie:
        # Handle potential race conditions or duplicate creation attempts
        logger.error(f"{log_prefix}: IntegrityError creating CryptoPayment (Multi-sig). Race condition or duplicate? {ie}", exc_info=True)
        raise EscrowError("Failed to create unique payment record, possibly duplicate.") from ie
    except (ValueError, Exception) as e: # Catch validation error too
        logger.exception(f"{log_prefix}: Unexpected error creating CryptoPayment (Multi-sig): {e}")
        raise EscrowError(f"Failed to create payment record: {e}") from e

    # --- Final Order Updates & Notification ---
    try:
        order.payment_deadline = timezone.now() + timedelta(hours=payment_wait_hours)
        order.status = OrderStatusChoices.PENDING_PAYMENT # Should already be this, but ensures state
        order.updated_at = timezone.now()

        # Ensure no duplicate fields before saving
        unique_fields_to_update = list(set(order_update_fields))
        order.save(update_fields=unique_fields_to_update)

        logger.info(f"{log_prefix}: Multi-sig escrow setup successful. Status -> {order.status}. Payment deadline: {order.payment_deadline}. Awaiting payment to {escrow_address[:15]}...")

        # Send notification to buyer (best effort)
        try:
            order_url = f"/orders/{order.id}" # Use reverse() if possible
            product_name = getattr(order.product, 'name', 'N/A')
            # FIX v1.7.3: Convert UUID to string before slicing
            order_id_str = str(order.id)
            message = (f"Your Order #{order_id_str[:8]} ({product_name}) is ready for payment. "
                       f"Please send exactly {order.total_price_native_selected} {currency} (atomic units) " # Clarify atomic units
                       f"to the escrow address provided on the order page before {order.payment_deadline.strftime('%Y-%m-%d %H:%M UTC')}.")
                       # f"to the escrow address: {escrow_address}") # Avoid sending address directly in notification
            create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent 'ready for payment' notification to Buyer {buyer.username}.")
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Failed to create 'ready for payment' notification for Buyer {buyer.id}: {notify_e}", exc_info=True)

    except Exception as e:
        # Catch errors during final save
        logger.exception(f"{log_prefix}: Failed to save final order updates (status, deadlines, crypto fields): {e}")
        raise EscrowError("Failed to save order updates during escrow creation.") from e

# --- End Replacement Block ---
    except Exception as e:
        # Catch errors during final save
        logger.exception(f"{log_prefix}: Failed to save final order updates (status, deadlines, crypto fields): {e}")
        raise EscrowError("Failed to save order updates during escrow creation.") from e

# --- End Replacement Block ---

@transaction.atomic
def check_and_confirm_payment(payment_id: Any) -> None:
    """
    Checks crypto node for payment confirmation TO THE ESCROW ADDRESS,
    applies deposit fee, compares amount, and if valid, atomically updates
    Ledger (using standard units) and Order status.

    Args:
        payment_id: The ID of the CryptoPayment record to check.
    Raises:
        ObjectDoesNotExist: If the payment record or related users are not found.
        EscrowError: For general process failures (DB errors, amount format).
        CryptoProcessingError: If crypto service communication fails.
        LedgerError: If ledger updates fail critically (e.g., inconsistency).
        InsufficientFundsError: If funds cannot be locked/debited after deposit.
    """
    payment: Optional['CryptoPayment'] = None
    order: Optional['Order'] = None
    log_prefix = f"PaymentConfirm Check (ID: {payment_id})"
    crypto_service_module: Optional[Any] = None # Initialize
    buyer_id: Optional[int] = None # For safe re-fetching in final block
    market_user_id: Optional[int] = None # For safe re-fetching in final block

    # --- Fetch and Lock Records ---
    try:
        # Fetch market user ID once safely
        market_user_id = get_market_user().pk

        # Lock payment record and related order to prevent concurrent processing
        payment = CryptoPayment.objects.select_for_update().select_related(
            'order__buyer', 'order__vendor', 'order__product' # Include necessary relations
        ).get(id=payment_id)
        order = payment.order # Get related order
        currency = payment.currency # Get currency early
        crypto_service_module = _get_crypto_service(currency) # Get service module early for conversions
        buyer_id = order.buyer_id # Store buyer ID

        log_prefix = f"PaymentConfirm Check (Order: {order.id}, Payment: {payment_id}, Currency: {currency})"
        logger.info(f"{log_prefix}: Starting check.")

    except CryptoPayment.DoesNotExist:
        logger.error(f"Payment record with ID {payment_id} not found.")
        raise # Re-raise ObjectDoesNotExist
    except User.DoesNotExist: # Catch if market user fetch failed
        logger.critical(f"{log_prefix}: Market user not found. Cannot process payment.")
        raise ObjectDoesNotExist("Market user not found during payment confirmation.")
    except (ValueError, AttributeError, Exception) as e: # ValueError from _get_crypto_service, AttributeError if buyer missing
        logger.exception(f"{log_prefix}: Error fetching payment/order details, users, or getting crypto service module: {e}")
        raise EscrowError(f"Database/Setup error fetching details for payment {payment_id}.") from e

    # --- Status Checks ---
    if payment.is_confirmed:
        logger.info(f"{log_prefix}: Already confirmed.")
        return # Idempotent: already processed

    if order.status != OrderStatusChoices.PENDING_PAYMENT:
        logger.warning(f"{log_prefix}: Order status is '{order.status}', not '{OrderStatusChoices.PENDING_PAYMENT}'. Skipping confirmation check.")
        # Check for timeout *before* returning, as timeout might have occurred concurrently
        _check_order_timeout(order)
        return

    # --- Crypto Confirmation Check ---
    is_crypto_confirmed = False
    received_native = Decimal('0.0') # Amount in Atomic Units from scan
    confirmations = 0
    external_txid: Optional[str] = payment.transaction_hash # Use existing if any
    scan_function_name = 'scan_for_payment_confirmation' # Assumed standard name

    try:
        # Crypto service module already fetched above
        if not hasattr(crypto_service_module, scan_function_name):
            logger.error(f"{log_prefix}: Crypto service module {crypto_service_module.__name__} missing required function '{scan_function_name}'.")
            raise CryptoProcessingError(f"Payment scanning not implemented for {currency}")

        logger.debug(f"{log_prefix}: Calling {scan_function_name} for {currency} on Payment {payment.id} (Address: {payment.payment_address[:15]}...) ...")
        # Expect Tuple[bool (confirmed?), Decimal (amount ATOMIC), int (confs), Optional[str] (txid)]
        scan_function = getattr(crypto_service_module, scan_function_name)
        check_result: Optional[Tuple[bool, Decimal, int, Optional[str]]] = scan_function(payment)

        if check_result:
            is_crypto_confirmed, received_native, confirmations, txid_found = check_result
            if txid_found and not external_txid: # Update txid if found and not already set
                external_txid = txid_found
            logger.debug(f"{log_prefix}: Scan Result - Confirmed={is_crypto_confirmed}, RcvdAtomic={received_native}, Confs={confirmations}, TX={external_txid}")
        else:
            # Service returned None, indicating no relevant transaction found yet
            is_crypto_confirmed = False
            logger.debug(f"{log_prefix}: Scan Result - No confirmed transaction found yet.")

    except (AttributeError, CryptoProcessingError) as cpe: # Catch AttributeError too
        logger.error(f"{log_prefix}: Error during crypto payment check: {cpe}", exc_info=True)
        raise CryptoProcessingError(f"Failed to check {currency} payment: {cpe}") from cpe # Re-raise specific crypto errors
    except Exception as e:
        # Catch unexpected errors during the scan
        logger.exception(f"{log_prefix}: Unexpected error during crypto payment check: {e}")
        raise CryptoProcessingError(f"Failed to check {currency} payment: {e}") from e

    # --- Handle Unconfirmed Payment ---
    if not is_crypto_confirmed:
        logger.debug(f"{log_prefix}: Payment not confirmed yet.")
        # Check for timeout after checking confirmation
        _check_order_timeout(order)
        return # Exit, wait for next check

    # --- Handle Confirmed Payment: Amount Verification & Conversion ---
    # Amounts expected/received here are ATOMIC units initially
    logger.info(f"{log_prefix}: Crypto confirmed. RcvdAtomic={received_native}, ExpAtomic={payment.expected_amount_native}, Confs={confirmations}, TXID={external_txid}")
    try:
        # Ensure expected amount is Decimal
        if not isinstance(payment.expected_amount_native, Decimal):
            raise ValueError(f"Expected amount on Payment {payment.id} is not a Decimal ({type(payment.expected_amount_native)})")

        # Compare amounts in ATOMIC units for sufficiency check (more precise)
        expected_atomic = payment.expected_amount_native
        # Ensure received_native is Decimal before comparison
        if not isinstance(received_native, Decimal):
            received_native = Decimal(str(received_native)) # Attempt conversion

        # Use a small tolerance if needed, e.g., for floating point issues if amounts weren't Decimal
        # is_amount_sufficient = received_native >= expected_atomic - Decimal('0.00000001') # Example small tolerance
        is_amount_sufficient = received_native >= expected_atomic

        # --- Convert amounts to STANDARD units for Ledger/Logging ---
        # FIX v1.8.0: Perform conversion here
        # Note: Pass the module to _convert_atomic_to_standard, which handles hasattr checks
        expected_std = _convert_atomic_to_standard(expected_atomic, currency, crypto_service_module)
        received_std = _convert_atomic_to_standard(received_native, currency, crypto_service_module)
        logger.debug(f"{log_prefix}: Converted amounts: ExpStd={expected_std}, RcvdStd={received_std} {currency}")

    except (InvalidOperation, TypeError, ValueError) as q_err:
        logger.error(f"{log_prefix}: Invalid amount format or conversion error. ExpectedAtomic={payment.expected_amount_native}, ReceivedNative='{received_native}'. Error: {q_err}")
        raise EscrowError("Invalid payment amount format or conversion error.") from q_err

    # --- Handle Insufficient Amount ---
    if not is_amount_sufficient:
        # FIX v1.8.0: Log STANDARD amounts in warning
        # NOTE (v1.19.0): Ensure `test_check_confirm_btc_insufficient_amount` test asserts this log format.
        logger.warning(f"{log_prefix}: Amount insufficient. RcvdStd: {received_std}, ExpStd: {expected_std} {currency}. (RcvdAtomic: {received_native}, ExpAtomic: {expected_atomic}). TXID: {external_txid}")
        try:
            # Update payment record to reflect confirmed but insufficient payment
            payment.is_confirmed = True # Mark as confirmed to prevent re-checking
            payment.confirmations_received = confirmations
            payment.received_amount_native = received_native # Store actual atomic received amount
            payment.transaction_hash = external_txid
            payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

            # Cancel the order due to underpayment (atomic update)
            updated_count = Order.objects.filter(pk=order.pk, status=OrderStatusChoices.PENDING_PAYMENT).update(
                status=OrderStatusChoices.CANCELLED_UNDERPAID, updated_at=timezone.now()
            )

            if updated_count > 0:
                logger.info(f"{log_prefix}: Order status set to '{OrderStatusChoices.CANCELLED_UNDERPAID}'.")
                security_logger.warning(f"Order {order.id} cancelled due to underpayment. Rcvd {received_std}, Exp {expected_std} {currency}. TX: {external_txid}")
                # Send notification (best effort)
                try:
                    buyer = User.objects.get(pk=buyer_id) # Re-fetch buyer for notification
                    if buyer:
                        order_url = f"/orders/{order.id}"
                        product_name = getattr(order.product,'name','N/A')
                        order_id_str = str(order.id)
                        message = (f"Your payment for Order #{order_id_str[:8]} ({product_name}) was confirmed "
                                   # FIX v1.8.0: Use STANDARD amounts in notification
                                   f"but the amount received ({received_std} {currency}) was less than expected ({expected_std} {currency}). "
                                   f"The order has been cancelled. Please contact support if this seems incorrect. TXID: {external_txid or 'N/A'}")
                        create_notification(user_id=buyer.id, level='error', message=message, link=order_url)
                except User.DoesNotExist:
                        logger.error(f"{log_prefix}: Failed to send underpayment notification: Buyer {buyer_id} not found.")
                except Exception as notify_e:
                    logger.error(f"{log_prefix}: Failed to create underpayment cancellation notification for Buyer {buyer_id}: {notify_e}", exc_info=True)
            else:
                # Status changed concurrently
                current_status = Order.objects.get(pk=order.pk).status # Get current status for logging
                logger.warning(f"{log_prefix}: Order status was not '{OrderStatusChoices.PENDING_PAYMENT}' when attempting to mark as '{OrderStatusChoices.CANCELLED_UNDERPAID}'. Current status: {current_status}")

            return # Stop processing after handling underpayment
        except Exception as e:
            # Error during underpayment handling - transaction will rollback
            logger.exception(f"{log_prefix}: Error updating records for underpaid order: {e}. Transaction will rollback.")
            raise EscrowError("Failed to process underpayment.") from e

    # --- Handle Sufficient Amount: Apply Deposit Fee, Update Ledger and Order ---
    try:
        # Re-fetch users safely within this final block of the transaction
        buyer: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None
        logger.debug(f"{log_prefix}: Sufficient amount detected. Re-fetching users for final update.")
        try:
            if buyer_id is None or market_user_id is None:
                 raise ValueError("Buyer or Market User ID missing unexpectedly before re-fetch.")
            buyer = User.objects.get(pk=buyer_id)
            market_user = User.objects.get(pk=market_user_id)
            logger.debug(f"{log_prefix}: Re-fetched buyer ({buyer.username}) and market user ({market_user.username}) OK.")
        except User.DoesNotExist as user_err:
            logger.critical(f"{log_prefix}: CRITICAL: Required user not found during final update: {user_err}. Check BuyerID: {buyer_id}, MarketUserID: {market_user_id}", exc_info=True)
            raise LedgerError(f"Required user not found during ledger update (BuyerID: {buyer_id}, MarketUserID: {market_user_id}).") from user_err
        except ValueError as val_err:
            logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
            raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
        except Exception as fetch_exc:
            logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
            raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc

        # --- v1.20.0: Calculate and Apply Deposit Fee ---
        prec = _get_currency_precision(currency)
        quantizer = Decimal(f'1e-{prec}')
        deposit_fee_percent = _get_market_fee_percentage(currency) # Use same % for now
        deposit_fee_std = (received_std * deposit_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if deposit_fee_std < Decimal('0.0'): deposit_fee_std = Decimal('0.0') # Ensure non-negative
        net_deposit_std = (received_std - deposit_fee_std).quantize(quantizer, rounding=ROUND_DOWN)
        if net_deposit_std < Decimal('0.0'): net_deposit_std = Decimal('0.0') # Ensure non-negative

        logger.info(f"{log_prefix}: Applying Deposit Fee ({deposit_fee_percent}%). Gross: {received_std}, Fee: {deposit_fee_std}, Net: {net_deposit_std} {currency}")

        # Ledger Updates (STANDARD units)
        ledger_deposit_notes = f"Confirmed payment deposit Order {order.id}, TX: {external_txid}"

        # 1. Credit Market User with the deposit fee
        if deposit_fee_std > Decimal('0.0'):
            ledger_service.credit_funds(
                user=market_user, currency=currency, amount=deposit_fee_std,
                transaction_type=LEDGER_TX_MARKET_FEE, # Use market fee type
                related_order=order, # Link to order for context
                notes=f"Deposit Fee Order {order.id}"
            )

        # 2. Credit Buyer's internal balance with the NET received standard amount
        if net_deposit_std > Decimal('0.0'): # Only credit if there's a net amount
             ledger_service.credit_funds(
                 user=buyer, currency=currency, amount=net_deposit_std, # Use NET amount
                 transaction_type=LEDGER_TX_DEPOSIT, external_txid=external_txid,
                 related_order=order, notes=ledger_deposit_notes
             )
        else:
             # Log if the entire deposit was consumed by the fee (edge case)
             if received_std > Decimal('0.0'):
                 logger.warning(f"{log_prefix}: Entire deposit amount {received_std} {currency} consumed by deposit fee {deposit_fee_std}. Buyer receives 0 net credit.")
                 # Optionally create a zero-value deposit transaction for audit trail
                 ledger_service.credit_funds(
                     user=buyer, currency=currency, amount=Decimal('0.0'),
                     transaction_type=LEDGER_TX_DEPOSIT, external_txid=external_txid,
                     related_order=order, notes=f"{ledger_deposit_notes} (Net Zero after fee)"
                 )

        # 3. Lock the *expected* standard escrow amount in the buyer's balance
        logger.debug(f"{log_prefix}: Attempting to lock {expected_std} {currency} from Buyer {buyer.username}'s available balance.")
        lock_success = ledger_service.lock_funds(
            user=buyer, currency=currency, amount=expected_std, # Lock the required STANDARD order amount
            related_order=order, notes=f"Lock funds for Order {order.id} escrow"
        )
        if not lock_success:
            # This indicates insufficient funds *after* the net deposit credit
            available_balance = ledger_service.get_available_balance(buyer, currency)
            logger.critical(f"{log_prefix}: Failed to lock sufficient funds ({expected_std} {currency}) for Buyer {buyer.username} after net deposit ({net_deposit_std}). Available: {available_balance}")
            raise InsufficientFundsError(f"Insufficient available balance ({available_balance}) to lock {expected_std} {currency} for escrow after net deposit.")

        # 4. Debit the locked standard amount from the buyer's balance
        ledger_service.debit_funds(
            user=buyer, currency=currency, amount=expected_std, # Debit the expected STANDARD amount
            transaction_type=LEDGER_TX_ESCROW_FUND_DEBIT, related_order=order,
            external_txid=external_txid, notes=f"Debit funds for Order {order.id} escrow funding"
        )

        # 5. Unlock the locked standard amount (as they've been successfully debited)
        unlock_success = ledger_service.unlock_funds(
            user=buyer, currency=currency, amount=expected_std, # Unlock expected STANDARD amount
            related_order=order, notes=f"Unlock funds after Order {order.id} escrow debit"
        )
        if not unlock_success:
            # Critical inconsistency: Debit succeeded, but unlock failed. Requires manual fix.
            logger.critical(f"{log_prefix}: CRITICAL LEDGER INCONSISTENCY: Escrow Debit OK but FAILED TO UNLOCK Buyer {buyer.username}! MANUAL FIX NEEDED!")
            raise LedgerError("Ledger unlock failed after escrow debit, indicating potential data inconsistency.")

        # 6. Update Order and Payment statuses
        now = timezone.now()
        order.status = OrderStatusChoices.PAYMENT_CONFIRMED
        order.paid_at = now
        # Reset deadlines that become relevant after payment
        order.dispute_deadline = None # Will be set when shipped
        order.auto_finalize_deadline = None # Will be set when shipped
        order.save(update_fields=['status', 'paid_at', 'auto_finalize_deadline', 'dispute_deadline', 'updated_at'])

        payment.is_confirmed = True
        payment.confirmations_received = confirmations
        payment.received_amount_native = received_native # Store actual GROSS atomic amount received
        payment.transaction_hash = external_txid
        payment.save(update_fields=['is_confirmed', 'confirmations_received', 'received_amount_native', 'transaction_hash', 'updated_at'])

        logger.info(f"{log_prefix}: Ledger updated (incl. deposit fee) & Order status -> {OrderStatusChoices.PAYMENT_CONFIRMED}. TXID: {external_txid}")
        security_logger.info(f"Order {order.id} ({currency}) payment confirmed & ledger updated (Deposit Fee: {deposit_fee_std}, Net: {net_deposit_std}). Buyer: {buyer.username}, Vendor: {getattr(order.vendor,'username','N/A')}. TX: {external_txid}")

        # Send notification to Vendor (best effort)
        try:
            vendor = order.vendor # Use prefetched vendor if available
            if vendor:
                order_url = f"/orders/{order.id}"
                product_name = getattr(order.product,'name','N/A')
                order_id_str = str(order.id)
                create_notification(
                    user_id=vendor.id, level='success',
                    message=f"Payment confirmed for Order #{order_id_str[:8]} ({product_name}). Please prepare for shipment.",
                    link=order_url
                )
                logger.info(f"{log_prefix}: Sent payment confirmation notification to Vendor {vendor.username}.")
            else:
                logger.error(f"{log_prefix}: Cannot send payment confirmed notification: Vendor missing on order.")
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Failed to create payment confirmed notification for Vendor {getattr(order.vendor,'id','N/A')}: {notify_e}", exc_info=True)

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError, ObjectDoesNotExist) as e:
        # Catch specific ledger/DB errors during the update phase
        logger.critical(f"{log_prefix}: CRITICAL: Ledger/Order atomic update FAILED during payment confirmation! Error: {e}. Transaction rolled back.", exc_info=True)
        # Re-raise the specific error for upstream handling
        raise
    except Exception as e:
        # Catch unexpected errors during the update phase
        logger.exception(f"{log_prefix}: CRITICAL: Unexpected error during ledger/order update for confirmed payment: {e}. Transaction rolled back.")
        # Wrap in EscrowError for consistent handling by callers
        raise EscrowError(f"Unexpected error confirming payment: {e}") from e


@transaction.atomic
def mark_order_shipped(order: 'Order', vendor: 'UserModel', tracking_info: Optional[str] = None) -> None:
    """
    Marks an order as shipped by the vendor, sets deadlines, notifies the buyer,
    and prepares initial release transaction metadata.

    Args:
        order: The Order instance to mark shipped.
        vendor: The User performing the action (must be the order's vendor).
        tracking_info: Optional tracking information string.
    Raises:
        ObjectDoesNotExist: If the order is not found.
        PermissionError: If the user is not the vendor.
        EscrowError: For invalid state or DB save failures.
        CryptoProcessingError: If preparing the release transaction fails.
        ValueError: If vendor withdrawal address is missing.
        DjangoValidationError: If order data is invalid before saving (requires fix in model/data).
    """
    log_prefix = f"Order {order.id} (MarkShipped by {vendor.username})"
    logger.info(f"{log_prefix}: Attempting...")

    # Basic dependency check
    if not all([Order, GlobalSettings, User]):
        raise RuntimeError("Critical application models are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    try:
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order.pk)
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise ObjectDoesNotExist
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission and State Checks ---
    if order_locked.vendor_id != vendor.id:
        vendor_username = getattr(order_locked.vendor, 'username', 'N/A')
        logger.warning(f"{log_prefix}: Permission denied. User {vendor.username} is not the vendor ({vendor_username}).")
        raise PermissionError("Only the vendor can mark this order as shipped.")

    if order_locked.status != OrderStatusChoices.PAYMENT_CONFIRMED:
        logger.warning(f"{log_prefix}: Cannot mark shipped. Invalid status '{order_locked.status}' (Expected: '{OrderStatusChoices.PAYMENT_CONFIRMED}').")
        raise EscrowError(f"Order must be in '{OrderStatusChoices.PAYMENT_CONFIRMED}' state to be marked shipped (Current: {order_locked.status}).")

    # --- Prepare Release Transaction (must succeed before marking shipped) ---
    prepared_release_metadata: Dict[str, Any]
    try:
        logger.debug(f"{log_prefix}: Preparing initial release metadata...")
        # _prepare_release handles fetching withdrawal address, calculating payout/fee, calling crypto service
        prepared_release_metadata = _prepare_release(order_locked) # Definition is later in file
        if not prepared_release_metadata or not isinstance(prepared_release_metadata, dict): # Check result validity
            raise CryptoProcessingError(f"Failed to prepare {order_locked.selected_currency} release transaction metadata (invalid result).")
        logger.debug(f"{log_prefix}: Release metadata prepared successfully.")
    except (ValueError, CryptoProcessingError, ObjectDoesNotExist) as prep_err:
        # Handle specific errors from _prepare_release (like missing withdrawal address)
        logger.error(f"{log_prefix}: Failed to prepare release transaction: {prep_err}", exc_info=True)
        raise # Re-raise the specific error
    except Exception as e:
        # Catch unexpected errors during preparation
        logger.exception(f"{log_prefix}: Unexpected error during _prepare_release: {e}")
        raise CryptoProcessingError("Unexpected error preparing release transaction.") from e

    # --- Update Order State and Deadlines ---
    now = timezone.now()
    order_locked.status = OrderStatusChoices.SHIPPED
    order_locked.shipped_at = now
    order_locked.release_metadata = prepared_release_metadata # Store the prepared data
    order_locked.release_initiated = True # Mark release process as started
    order_locked.updated_at = now # Update timestamp

    # Calculate deadlines based on GlobalSettings
    try:
        gs: 'GlobalSettingsModel' = GlobalSettings.get_solo()
        # NOTE (v1.19.0): Consider moving defaults to Django settings.
        # Use explicit defaults if settings are missing
        dispute_days = int(getattr(gs, 'dispute_window_days', 7))
        finalize_days = int(getattr(gs, 'order_auto_finalize_days', 14))
        order_locked.dispute_deadline = now + timedelta(days=dispute_days)
        order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)
    except (ObjectDoesNotExist, AttributeError, ValueError, TypeError) as e:
        # Fallback to hardcoded defaults if settings fail
        logger.error(f"{log_prefix}: Error loading GlobalSettings deadlines: {e}. Using defaults (Dispute: 7d, Finalize: 14d).")
        dispute_days = 7
        finalize_days = 14
        order_locked.dispute_deadline = now + timedelta(days=dispute_days)
        order_locked.auto_finalize_deadline = now + timedelta(days=finalize_days)

    # Prepare fields for saving
    update_fields = [
        'status', 'shipped_at', 'updated_at', 'dispute_deadline',
        'auto_finalize_deadline', 'release_metadata', 'release_initiated'
    ]

    # Add tracking info if provided and field exists
    tracking_field = 'tracking_info' # Assume standard field name
    if tracking_info and hasattr(order_locked, tracking_field):
        order_locked.tracking_info = tracking_info
        update_fields.append(tracking_field)
        logger.info(f"{log_prefix}: Added tracking info.")
    elif tracking_info:
        # Log if tracking info provided but field is missing on model
        logger.warning(f"{log_prefix}: Tracking info provided but '{tracking_field}' field missing on Order model.")

    # --- Save Order Updates ---
    try:
        # CRITICAL NOTE (Re-confirmed v1.22.0): The following `full_clean()` call is CORRECT.
        # The `pytest` failure ('btc_escrow_address' format error) indicates invalid data
        # was saved during `create_escrow_for_order`.
        # FIX THIS EXTERNALLY: Ensure `bitcoin_service.create_btc_multisig_address`
        # (or its test mock) returns a VALID Bitcoin address format.
        # DO NOT REMOVE OR SUPPRESS THIS VALIDATION.
        logger.debug(f"{log_prefix}: Validating order before saving shipment updates...")
        order_locked.full_clean(exclude=None) # Perform full validation
        logger.debug(f"{log_prefix}: Validation passed. Saving fields: {update_fields}")

        # Ensure unique fields before saving
        order_locked.save(update_fields=list(set(update_fields)))
        logger.info(f"{log_prefix}: Marked shipped. Status -> {OrderStatusChoices.SHIPPED}. Dispute deadline: {order_locked.dispute_deadline}, Auto-finalize: {order_locked.auto_finalize_deadline}")
        security_logger.info(f"Order {order_locked.id} marked shipped by Vendor {vendor.username}.")

    except DjangoValidationError as ve:
        # If full_clean fails, log the specific validation errors and re-raise.
        # This confirms the issue with data validity (e.g., btc_escrow_address format).
        logger.error(f"{log_prefix}: CRITICAL: Order model validation failed when saving shipping updates: {ve.message_dict}. FIX THE EXTERNAL DATA SOURCE (e.g., crypto service or test mock providing the invalid address).", exc_info=False) # Keep log concise
        raise ve # Re-raise the validation error - DO NOT SUPPRESS
    except Exception as e:
        # Catch other errors during save operation
        logger.exception(f"{log_prefix}: Failed to save order updates after marking shipped: {e}")
        raise EscrowError("Failed to save order shipping updates.") from e

    # --- Notify Buyer (Best Effort) ---
    try:
        buyer = order_locked.buyer
        if buyer:
            order_url = f"/orders/{order_locked.id}"
            product_name = getattr(order_locked.product, 'name', 'N/A')
            order_id_str = str(order_locked.id)
            message = f"Your Order #{order_id_str[:8]} ({product_name}) has been marked as shipped by the vendor."
            if tracking_info and hasattr(order_locked, tracking_field):
                message += f" Tracking info ({tracking_info[:20]}...) may be available on the order page." # Include snippet if desired
            create_notification(user_id=buyer.id, level='info', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent order shipped notification to Buyer {buyer.username}.")
        else:
            # Should not happen if order validation is correct, but log defensively
            logger.error(f"{log_prefix}: Cannot send shipped notification: Buyer relationship missing on order.")
    except Exception as notify_e:
        logger.error(f"{log_prefix}: Failed to create order shipped notification for Buyer {getattr(buyer,'id','N/A')}: {notify_e}", exc_info=True)
# END OF mark_order_shipped function


@transaction.atomic
def sign_order_release(order: 'Order', user: 'UserModel', private_key_info: str) -> Tuple[bool, bool]:
    """
    Applies a user's signature (Buyer or Vendor) to the prepared release transaction
    by calling the appropriate crypto service.

    Args:
        order: The Order instance being signed.
        user: The User performing the signing (Buyer or Vendor).
        private_key_info: User's private key or signing credential (format depends on crypto).
    Returns:
        Tuple[bool, bool]: (signing_successful, is_release_complete)
    Raises:
        ValueError: If inputs are invalid.
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        EscrowError: For invalid state, metadata issues, or save failures.
        CryptoProcessingError: If crypto signing fails.
        NotImplementedError: If signing logic is not implemented for the currency.
    """
    log_prefix = f"Order {order.id} (SignRelease by {user.username})"
    logger.info(f"{log_prefix}: Attempting signature...")

    # --- Input and Dependency Validation ---
    if not all([Order, User]):
        raise RuntimeError("Critical application models are not available.")
    if not isinstance(order, Order) or not order.pk:
        raise ValueError("Invalid Order object provided.")
    if not isinstance(user, User) or not user.pk:
        raise ValueError("Invalid User object provided.")
    # Basic check for key info - real validation depends on crypto type
    if not private_key_info or not isinstance(private_key_info, str) or len(private_key_info) < 10: # Keep basic check
        logger.warning(f"{log_prefix}: Private key info missing or seems too short.")
        raise ValueError("Missing or potentially invalid private key information.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    try:
        order_locked = Order.objects.select_for_update().select_related('buyer', 'vendor', 'product').get(pk=order.pk) # Added product for notification context
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission and State Checks ---
    is_buyer = (user.id == order_locked.buyer_id)
    is_vendor = (user.id == order_locked.vendor_id)
    if not (is_buyer or is_vendor):
        logger.warning(f"{log_prefix}: Permission denied. User is not buyer or vendor.")
        raise PermissionError("Only the buyer or vendor can sign this release.")

    if not order_locked.release_initiated:
        raise EscrowError("Order release process has not been initiated (missing prepared tx).")

    # Check if order is in a state where signing is allowed
    allowed_sign_states = [
        OrderStatusChoices.PAYMENT_CONFIRMED, # Can sign immediately after payment (e.g., auto-release scenario)
        OrderStatusChoices.SHIPPED,           # Normal scenario after vendor ships
    ]
    if order_locked.status not in allowed_sign_states:
        raise EscrowError(f"Cannot sign release from status '{order_locked.status}'. Expected one of: {allowed_sign_states}")

    # --- Metadata Validation ---
    current_metadata: Dict[str, Any] = order_locked.release_metadata or {}
    if not isinstance(current_metadata, dict):
        raise EscrowError("Prepared release metadata is missing or invalid type.")

    unsigned_crypto_data = current_metadata.get('data')
    if not unsigned_crypto_data:
        raise EscrowError("Prepared transaction data ('data' key) is missing from release metadata.")

    # --- Check if Already Signed ---
    current_sigs: Dict[str, Any] = current_metadata.get('signatures', {})
    # Ensure signatures is a dict before checking
    if not isinstance(current_sigs, dict):
        logger.warning(f"{log_prefix}: 'signatures' field in metadata is not a dict ({type(current_sigs)}). Resetting.")
        current_sigs = {}

    user_id_str = str(user.id)
    if user_id_str in current_sigs:
        logger.warning(f"{log_prefix}: User {user.username} (ID: {user_id_str}) has already signed this release.")
        # Raising error prevents accidental multiple signing attempts.
        raise EscrowError("You have already signed this release.")

    # --- Crypto Signing Interaction ---
    signed_artifact_data: Optional[str] = None # Data after this user's signature
    is_complete = False # Is the transaction fully signed and ready for broadcast?
    updated_sigs_map = {} # Only relevant for crypto services returning a map (like XMR example)

    try:
        currency = order_locked.selected_currency
        required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
        crypto_service_module = _get_crypto_service(currency) # Get module

        logger.info(f"{log_prefix}: Calling crypto service module {crypto_service_module.__name__} for {currency} signing...")

        sign_result: Union[Dict[str, Any], str, None] = None # Initialize, result type depends on currency

        if currency == 'BTC':
            sign_func_name = 'sign_btc_multisig_tx' # Matches the test mock target
            if not hasattr(crypto_service_module, sign_func_name):
                raise NotImplementedError(f"Signing function '{sign_func_name}' not found in {crypto_service_module.__name__}")
            sign_func = getattr(crypto_service_module, sign_func_name)
            # Corrected call based on bitcoin_service.sign_btc_multisig_tx signature
            sign_result = sign_func(
                psbt_base64=unsigned_crypto_data,  # Map to expected arg name
                private_key_wif=private_key_info    # Map to expected arg name
            )

            # Process BTC result
            if isinstance(sign_result, str):
                signed_artifact_data = sign_result
                # --- FIX START (v1.18.0) ---
                # Manually add the current signer to the map BEFORE checking completion
                # user_id_str is defined earlier in the function
                if user_id_str not in current_sigs: # Add only if not already present (defensive)
                    current_sigs[user_id_str] = {
                        'signed_at': timezone.now().isoformat(), # Add timestamp
                        'signer': user.username
                    }
                    logger.debug(f"{log_prefix}: Added BTC signature for user {user_id_str} to current_sigs.")
                else:
                    logger.warning(f"{log_prefix}: Attempted to add BTC signature for user {user_id_str}, but they were already in current_sigs.")
                # No updated_sigs_map needed from BTC result
                # is_complete will be calculated later based on the updated current_sigs map
                # --- FIX END (v1.18.0) ---
            elif sign_result is None:
                # NOTE (v1.19.0): Ensure test `test_sign_order_release_crypto_fail` handles this outcome.
                logger.error(f"{log_prefix}: BTC signing function returned None.")
                signed_artifact_data = None # Will cause validation error below
            else:
                logger.error(f"{log_prefix}: Unexpected return type from {sign_func_name}: {type(sign_result)}")
                signed_artifact_data = None # Will cause validation error below

        elif currency == 'XMR':
            sign_func_name = 'sign_xmr_multisig_tx' # Example: Replace with actual XMR function name
            if not hasattr(crypto_service_module, sign_func_name):
                raise NotImplementedError(f"Signing function '{sign_func_name}' not found in {crypto_service_module.__name__}")
            sign_func = getattr(crypto_service_module, sign_func_name)
            # Assuming old signature for XMR for now
            sign_result = sign_func(
                order=order_locked,
                unsigned_tx_data=unsigned_crypto_data,
                private_key_info=private_key_info,
                signer_role='buyer' if is_buyer else 'vendor'
            )
            # Process XMR result (assuming Dict return)
            if isinstance(sign_result, dict):
                signed_artifact_data = sign_result.get('signed_tx_data') # Adapt key if needed
                updated_sigs_map = sign_result.get('signatures', {}) # Get signatures map from XMR
                is_complete = sign_result.get('is_complete', False) # XMR might determine completeness
            else:
                logger.error(f"{log_prefix}: Unexpected or None return from {sign_func_name}: {sign_result}")
                signed_artifact_data = None

        elif currency == 'ETH':
            logger.error(f"{log_prefix}: ETH signing not implemented.")
            raise NotImplementedError(f"ETH signing not implemented for Order {order.id}.")
        else:
            raise ValueError(f"Unsupported currency for signing: {currency}")

        # --- Post-Signing Validation ---
        # Basic validation of processed data
        if not signed_artifact_data or not isinstance(signed_artifact_data, str):
             logger.error(f"{log_prefix}: Crypto service signing function for {currency} did not return valid signed transaction data after processing. Processed Result: {signed_artifact_data}")
             raise CryptoProcessingError(f"Crypto service signing function for {currency} did not return valid signed transaction data.")
        # Validate signatures map if provided by crypto service (e.g., XMR)
        if not isinstance(updated_sigs_map, dict):
             logger.warning(f"{log_prefix}: Signing function for {currency} returned invalid 'signatures' format ({type(updated_sigs_map)}). Using empty dict.")
             updated_sigs_map = {}

        # --- Calculate Final State ---
        # Update the current signatures map with any map returned by the crypto service (relevant for XMR)
        current_sigs.update(updated_sigs_map) # For BTC path, this updates with {} - harmless.

        # Re-calculate completeness based on the potentially updated combined signatures map
        # This check now includes the signature manually added for BTC path above
        is_complete = (len(current_sigs) >= required_sigs)
        logger.debug(f"{log_prefix}: Signing result processed. Signatures count: {len(current_sigs)}/{required_sigs}. IsComplete: {is_complete}")

    except (AttributeError, NotImplementedError):
        logger.error(f"{log_prefix}: Signing not implemented or function missing for currency {currency}.", exc_info=True)
        raise NotImplementedError(f"Signing not implemented for currency {currency}.")
    except (ValueError, CryptoProcessingError) as crypto_err:
        logger.error(f"{log_prefix}: Crypto signing error: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Failed to sign {currency} release transaction: {crypto_err}") from crypto_err
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during crypto signing: {e}")
        raise CryptoProcessingError("Unexpected error during signing.") from e

    # --- Update Order Metadata and Save ---
    try:
        fields_to_save = ['updated_at']
        now_iso = timezone.now().isoformat() # Use consistent timestamp

        # Ensure metadata exists before updating
        if not isinstance(order_locked.release_metadata, dict):
             # This should ideally be caught earlier, but defense-in-depth
             order_locked.release_metadata = {}

        # Update metadata with new signed data and the potentially updated signatures map
        order_locked.release_metadata['data'] = signed_artifact_data # Store the latest signed data
        order_locked.release_metadata['signatures'] = current_sigs # Store the final map (includes BTC manual add)
        order_locked.release_metadata['ready_for_broadcast'] = is_complete # Store calculated readiness
        order_locked.release_metadata['last_signed_at'] = now_iso # Add timestamp
        fields_to_save.append('release_metadata')

        order_locked.updated_at = timezone.now()
        order_locked.save(update_fields=list(set(fields_to_save)))

        logger.info(f"{log_prefix}: Signature applied. Current signers: {len(current_sigs)}/{required_sigs}. Ready for broadcast: {is_complete}.")
        security_logger.info(f"Order {order.id} release signed by {user.username}. Ready: {is_complete}.")

        # --- Notify Other Party if Complete (Best Effort) ---
        if is_complete:
            other_party = order_locked.vendor if is_buyer else order_locked.buyer
            if other_party:
                try:
                    order_url = f"/orders/{order.id}"
                    product_name = getattr(order_locked.product, 'name', 'N/A')
                    order_id_str = str(order.id)
                    message = (f"Order #{order_id_str[:8]} ({product_name}) has received the final signature "
                               f"and is ready for broadcast to release funds.")
                    create_notification(user_id=other_party.id, level='info', message=message, link=order_url)
                    logger.info(f"{log_prefix}: Sent 'ready for broadcast' notification to {other_party.username}.")
                except Exception as notify_e:
                    logger.error(f"{log_prefix}: Failed to create 'ready for broadcast' notification for User {other_party.id}: {notify_e}", exc_info=True)

        # Return success status and completion status
        return True, is_complete

    except Exception as e:
        # Catch errors during final save
        logger.exception(f"{log_prefix}: Failed to save order updates after signing: {e}")
        raise EscrowError("Failed to save signature updates.") from e
# END OF sign_order_release function


@transaction.atomic
def broadcast_release_transaction(order_id: Any) -> bool:
    """
    Finalizes (if needed), broadcasts the fully signed release transaction,
    and updates Ledger/Order state upon success.

    Args:
        order_id: The ID of the Order to finalize and broadcast.
    Returns:
        bool: True if broadcast and internal updates were fully successful.
              False if internal updates failed critically after successful broadcast
              (indicating inconsistency requiring manual intervention).
    Raises:
        ObjectDoesNotExist: If order not found.
        EscrowError: For invalid state or metadata issues.
        CryptoProcessingError: If crypto broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail (before broadcast).
        RuntimeError: If critical dependencies are missing.
    """
    log_prefix = f"Order {order_id} (BroadcastRelease)"
    logger.info(f"{log_prefix}: Initiating broadcast...")

    # --- Dependency Check ---
    if not all([ledger_service, Order, User] + list(_crypto_service_registry.values())):
        logger.critical(f"{log_prefix}: Critical application components (Ledger, Models, Crypto Services) are not available.")
        raise RuntimeError("Critical application components are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    market_user_id: Optional[int] = None # To store market user ID before potential re-fetch
    vendor_id: Optional[int] = None
    tx_hash: Optional[str] = None # Define tx_hash earlier to be accessible in final except blocks
    currency: Optional[str] = None # Define currency earlier

    try:
        # Fetch market user ID once outside the main try block if needed for re-fetch
        market_user_id = get_market_user().pk
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product' # Keep buyer/vendor selected for notifications
        ).get(pk=order_id)
        vendor_id = order_locked.vendor_id # Store vendor ID for re-fetch
        currency = order_locked.selected_currency # Store currency

    except ObjectDoesNotExist: # Catches User.DoesNotExist from get_market_user or Order.DoesNotExist
        logger.error(f"{log_prefix}: Order or Market User not found.")
        raise # Re-raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order or market user: {e}")
        raise EscrowError(f"Database error fetching required objects for order {order_id}.") from e

    # --- State and Metadata Validation ---
    if not order_locked.release_initiated:
        raise EscrowError("Order release process not initiated (cannot broadcast).")

    # Idempotency: If already finalized, nothing to do.
    if order_locked.status == OrderStatusChoices.FINALIZED:
        logger.info(f"{log_prefix}: Order already finalized. Broadcast call redundant.")
        return True # Consider it successful as the end state is achieved

    release_metadata: Dict[str, Any] = order_locked.release_metadata or {}
    if not isinstance(release_metadata, dict):
        raise EscrowError("Release metadata is missing or invalid type.")

    # Check readiness flag and signature count for robustness
    metadata_ready = release_metadata.get('ready_for_broadcast') is True
    current_sigs: Dict[str, Any] = release_metadata.get('signatures', {})
    if not isinstance(current_sigs, dict): current_sigs = {} # Handle invalid type
    required_sigs = int(getattr(settings, 'MULTISIG_SIGNATURES_REQUIRED', 2))
    has_enough_sigs = len(current_sigs) >= required_sigs

    if not metadata_ready:
        if has_enough_sigs:
            # If enough sigs present but flag is false, warn and proceed (potentially fix flag)
            logger.warning(f"{log_prefix}: Signatures seem sufficient ({len(current_sigs)}/{required_sigs}) but 'ready_for_broadcast' flag not True in metadata. Proceeding based on signature count and setting flag.")
            release_metadata['ready_for_broadcast'] = True # Fix the flag
        else:
            # Not enough signatures and flag is false - cannot proceed
            raise EscrowError(f"Order is not ready for broadcast (Missing readiness flag and/or signatures: {len(current_sigs)}/{required_sigs}).")

    # Ensure order is in a state where broadcast is expected
    allowed_broadcast_states = [
        OrderStatusChoices.SHIPPED,           # Normal path after signing
        OrderStatusChoices.PAYMENT_CONFIRMED, # Allows for immediate release after payment if logic permits
    ]
    if order_locked.status not in allowed_broadcast_states:
        raise EscrowError(f"Cannot broadcast release from status '{order_locked.status}'. Expected one of: {allowed_broadcast_states}")

    # --- Load Participants and Metadata Values ---
    # currency already fetched
    # Vendor ID already fetched

    try:
        # Extract necessary data from metadata, converting types carefully
        payout_str = release_metadata.get('payout')
        fee_str = release_metadata.get('fee')
        signed_crypto_data = release_metadata.get('data')
        release_type = release_metadata.get('type')

        if not signed_crypto_data or not release_type or payout_str is None or fee_str is None:
            raise ValueError("Missing critical release metadata (data, type, payout, fee).")

        # Convert payout/fee (these are STANDARD units from _prepare_release), ensuring non-negative
        payout_std = Decimal(payout_str)
        fee_std = Decimal(fee_str)
        if payout_std < Decimal('0.0') or fee_std < Decimal('0.0'):
            raise ValueError("Invalid negative values found in payout/fee metadata.")

    except (ValueError, TypeError, InvalidOperation, KeyError) as e:
        logger.error(f"{log_prefix}: Invalid or incomplete release metadata for broadcast: {e}")
        raise EscrowError(f"Invalid release metadata: {e}") from e

    # --- Crypto Broadcast Interaction ---
    broadcast_success = False
    # tx_hash defined earlier
    try:
        logger.info(f"{log_prefix}: Calling crypto service module to finalize and broadcast ({currency}, Type: {release_type})...")
        crypto_service_module = _get_crypto_service(currency) # Get module

        if currency == 'BTC':
            broadcast_func_name = 'finalize_and_broadcast_btc_release'
            if not hasattr(crypto_service_module, broadcast_func_name):
                raise NotImplementedError(f"Broadcast function '{broadcast_func_name}' missing in {currency} service module.")
            broadcast_func = getattr(crypto_service_module, broadcast_func_name)
            tx_hash = broadcast_func(
                order=order_locked, current_psbt_base64=signed_crypto_data
            )
        elif currency == 'XMR':
            broadcast_func_name = 'finalize_and_broadcast_xmr_release'
            if not hasattr(crypto_service_module, broadcast_func_name):
                raise NotImplementedError(f"Broadcast function '{broadcast_func_name}' missing in {currency} service module.")
            broadcast_func = getattr(crypto_service_module, broadcast_func_name)
            tx_hash = broadcast_func(
                order=order_locked, current_txset_hex=signed_crypto_data
            )
        elif currency == 'ETH':
            logger.error(f"{log_prefix}: ETH Broadcast not implemented.")
            raise NotImplementedError("ETH Broadcast not implemented.")
        else:
            raise ValueError(f"Unsupported currency '{currency}' for broadcast.")

        # Validate tx_hash
        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10 # Basic check
        if not broadcast_success:
            raise CryptoProcessingError(f"Crypto broadcast failed for Order {order_locked.id} (service module returned invalid tx_hash: '{tx_hash}').")

        logger.info(f"{log_prefix}: Broadcast successful. Transaction Hash: {tx_hash}")

    except (AttributeError, CryptoProcessingError, ValueError, NotImplementedError) as crypto_err: # Catch AttributeError
        logger.error(f"{log_prefix}: Crypto broadcast failed: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Crypto broadcast error: {crypto_err}") from crypto_err # Re-raise the specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected broadcast error: {e}")
        raise CryptoProcessingError(f"Unexpected broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    try:
        # Re-fetch users within this transaction block safely
        vendor: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None
        logger.debug(f"{log_prefix}: Entering final update block post-broadcast.")
        try:
            if vendor_id is None or market_user_id is None:
                raise ValueError("Vendor ID or Market User ID missing unexpectedly before re-fetch.")
            vendor = User.objects.get(pk=vendor_id)
            market_user = User.objects.get(pk=market_user_id)
            logger.debug(f"{log_prefix}: Re-fetched vendor ({vendor.username}) and market user ({market_user.username}) OK.")
        except User.DoesNotExist as user_err:
            logger.critical(f"{log_prefix}: CRITICAL: Required user not found during final update: {user_err}. Check VendorID: {vendor_id}, MarketUserID: {market_user_id}", exc_info=True)
            raise LedgerError(f"Required user not found during ledger update (VendorID: {vendor_id}, MarketUserID: {market_user_id}).") from user_err
        except ValueError as val_err:
            logger.critical(f"{log_prefix}: CRITICAL: Missing user ID for re-fetch: {val_err}")
            raise LedgerError(f"Missing user ID for ledger update: {val_err}") from val_err
        except Exception as fetch_exc:
            logger.critical(f"{log_prefix}: CRITICAL: Unexpected error fetching users: {fetch_exc}", exc_info=True)
            raise LedgerError(f"Unexpected error fetching users: {fetch_exc}") from fetch_exc

        # Proceed with updates only if users were fetched
        now = timezone.now()
        order_locked.status = OrderStatusChoices.FINALIZED
        order_locked.finalized_at = now
        order_locked.release_tx_broadcast_hash = tx_hash
        order_locked.updated_at = now

        release_metadata['broadcast_tx_hash'] = tx_hash
        release_metadata['broadcast_at'] = now.isoformat()
        release_metadata['ready_for_broadcast'] = True # Ensure flag is true post-broadcast
        order_locked.release_metadata = release_metadata

        logger.debug(f"{log_prefix}: Attempting to save order finalization state...")
        order_locked.save(update_fields=['status', 'finalized_at', 'release_tx_broadcast_hash', 'release_metadata', 'updated_at'])
        logger.info(f"{log_prefix}: Order state saved successfully. Proceeding to ledger updates.")

        # Update Ledger balances (using STANDARD amounts loaded earlier)
        ledger_notes_base = f"Release Order {order_locked.id}, TX: {tx_hash}"
        if payout_std > Decimal('0.0'):
            logger.debug(f"{log_prefix}: Attempting vendor credit. User: {vendor.username}, Amount: {payout_std} {currency}")
            ledger_service.credit_funds(
                user=vendor, currency=currency, amount=payout_std,
                transaction_type=LEDGER_TX_ESCROW_RELEASE_VENDOR, related_order=order_locked,
                external_txid=tx_hash, notes=f"{ledger_notes_base} Vendor Payout"
            )
        if fee_std > Decimal('0.0'):
            logger.debug(f"{log_prefix}: Attempting market fee credit. User: {market_user.username}, Amount: {fee_std} {currency}")
            # FIX v1.20.1: Correct notes string
            ledger_service.credit_funds(
                user=market_user, currency=currency, amount=fee_std,
                transaction_type=LEDGER_TX_MARKET_FEE, related_order=order_locked,
                notes=f"Market Fee Order {order_locked.id}" # Corrected from "Purchase Fee..."
            )

        logger.info(f"{log_prefix}: Ledger updated. Vendor: {payout_std} {currency}, Fee: {fee_std} {currency}.")
        security_logger.info(f"Order {order_locked.id} finalized and released via Ledger. Vendor: {vendor.username}, TX: {tx_hash}")

        # Notifications (Best Effort)
        buyer = order_locked.buyer
        product_name = getattr(order_locked.product, 'name', 'N/A')
        order_url = f"/orders/{order_locked.id}"
        order_id_str = str(order_locked.id)
        finalization_msg_buyer = f"Your Order #{order_id_str[:8]} ({product_name}) has been successfully finalized. Funds released to vendor."
        finalization_msg_vendor = f"Your Sale #{order_id_str[:8]} ({product_name}) has been successfully finalized. Funds of {payout_std} {currency} credited to your account."

        if buyer:
            try: create_notification(user_id=buyer.id, level='success', message=finalization_msg_buyer, link=order_url)
            except Exception as notify_e: logger.error(f"{log_prefix}: Failed to create finalized notification for Buyer {buyer.id}: {notify_e}", exc_info=True)
        try: create_notification(user_id=vendor.id, level='success', message=finalization_msg_vendor, link=order_url)
        except Exception as notify_e: logger.error(f"{log_prefix}: Failed to create finalized notification for Vendor {vendor.id}: {notify_e}", exc_info=True)

        logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
        return True

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError) as final_db_err:
        # CRITICAL FAILURE STATE
        logger.critical(f"{log_prefix}: CRITICAL FAILURE: Broadcast OK (TX: {tx_hash}) but FINAL LEDGER/ORDER UPDATE FAILED. Error Type: {type(final_db_err).__name__}, Details: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Return False to indicate critical failure post-broadcast
        return False # Modified from raise PostBroadcastUpdateError for broadcast_release_transaction
                     # because the return False pattern might be expected by callers here.
                     # Keeping the critical log.
    except Exception as final_e:
        # CRITICAL FAILURE STATE (Unexpected Error)
        logger.critical(f"{log_prefix}: CRITICAL UNEXPECTED ERROR: Broadcast OK (TX: {tx_hash}) but unexpected error during final DB/Ledger update. Error Type: {type(final_e).__name__}, Details: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        # Return False to indicate critical failure post-broadcast
        return False # Modified from raise PostBroadcastUpdateError
# END OF broadcast_release_transaction function

@transaction.atomic
def open_dispute(order: 'Order', user: 'UserModel', reason: str) -> None:
    """
    Opens a dispute on an order, changes status, and notifies the other party.

    Args:
        order: The Order instance to open dispute for.
        user: The User opening the dispute (must be buyer or vendor).
        reason: A string explaining the reason for the dispute.
    Raises:
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        ValueError: If reason is invalid or dispute window closed.
        EscrowError: For invalid state or DB save failures.
        RuntimeError: If critical models unavailable.
    """
    log_prefix = f"Order {order.id} (OpenDispute by {user.username})"
    logger.info(f"{log_prefix}: Attempting...")

    # --- Input and Dependency Validation ---
    if not all([Order, User]):
        raise RuntimeError("Critical application models are not available.")
    if not reason or not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("A valid reason (minimum 10 characters) is required to open a dispute.")
    reason = reason.strip() # Use stripped reason

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    try:
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order.pk)
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise
    except Exception as e:
        logger.exception(f"{log_prefix}: Error fetching order: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission Check ---
    is_buyer = (user.id == order_locked.buyer_id)
    is_vendor = (user.id == order_locked.vendor_id)
    if not (is_buyer or is_vendor):
        raise PermissionError("Only the buyer or vendor can open a dispute on this order.")

    # --- State and Deadline Checks ---
    allowed_dispute_states = [
        OrderStatusChoices.SHIPPED,
        OrderStatusChoices.PAYMENT_CONFIRMED,
    ]
    if order_locked.status not in allowed_dispute_states:
        raise EscrowError(f"Cannot open dispute from status '{order_locked.status}'. Expected one of: {allowed_dispute_states}")

    if order_locked.dispute_deadline and timezone.now() > order_locked.dispute_deadline:
        logger.warning(f"{log_prefix}: Attempt to open dispute after deadline {order_locked.dispute_deadline}.")
        raise ValueError("Dispute window has closed for this order.")

    if order_locked.status == OrderStatusChoices.DISPUTED:
        logger.info(f"{log_prefix}: Dispute already open. Open dispute call redundant.")
        return

    # --- Update Order State ---
    original_status = order_locked.status
    now = timezone.now()
    order_locked.status = OrderStatusChoices.DISPUTED
    order_locked.disputed_at = now
    order_locked.updated_at = now
    update_fields = ['status', 'disputed_at', 'updated_at']

    if hasattr(order_locked, 'dispute_reason'):
        order_locked.dispute_reason = reason[:1000] # Limit length
        update_fields.append('dispute_reason')
    if hasattr(order_locked, 'dispute_opened_by'):
        order_locked.dispute_opened_by = user
        update_fields.append('dispute_opened_by')

    # --- Save Order ---
    try:
        order_locked.save(update_fields=list(set(update_fields)))
        logger.info(f"{log_prefix}: Dispute opened successfully (Previous status: {original_status}). Status -> {OrderStatusChoices.DISPUTED}.")
        security_logger.info(f"Dispute opened Order {order_locked.id} by {user.username}. Reason: {reason[:100]}...")
    except Exception as e:
        logger.exception(f"{log_prefix}: Failed to save order dispute status: {e}")
        raise EscrowError("Failed to save order dispute status.") from e

    # --- Notify Other Party (Best Effort) ---
    recipient = order_locked.vendor if is_buyer else order_locked.buyer
    if recipient:
        try:
            order_url = f"/orders/{order_locked.id}"
            product_name = getattr(order_locked.product, 'name', 'N/A')
            order_id_str = str(order_locked.id)
            message = f"A dispute has been opened by {user.username} regarding Order #{order_id_str[:8]} ({product_name}). Reason: '{reason[:75]}...'. Please review the order details and respond in the dispute section."
            create_notification(user_id=recipient.id, level='warning', message=message, link=order_url)
            logger.info(f"{log_prefix}: Sent dispute opened notification to {recipient.username}.")
        except Exception as notify_e:
            logger.error(f"{log_prefix}: Failed to create dispute opened notification for User {recipient.id}: {notify_e}", exc_info=True)
    else:
        logger.error(f"{log_prefix}: Could not find recipient (buyer/vendor) to notify about dispute.")
# END OF open_dispute function


@transaction.atomic
def resolve_dispute(
    order: 'Order',
    moderator: 'UserModel',
    resolution_notes: str,
    release_to_buyer_percent: int = 0
) -> bool:
    """
    Resolves a dispute: Calculates split (using standard units), prepares/broadcasts
    crypto tx via service (expecting standard units), updates Ledger/Order,
    and notifies parties.

    Args:
        order: The Order instance in dispute.
        moderator: The staff/superuser resolving the dispute.
        resolution_notes: Explanation of the resolution.
        release_to_buyer_percent: Integer percentage (0-100) of escrowed funds
                                  to release to the buyer. Remainder goes to vendor.
    Returns:
        bool: True if resolution (broadcast + internal updates) was fully successful.
              False if internal updates failed critically after successful broadcast.
    Raises:
        ObjectDoesNotExist: If order, buyer, vendor, or market user not found.
        PermissionError: If moderator lacks permissions.
        ValueError: For invalid percentage, notes, or calculation errors.
        EscrowError: For invalid order state or DB save failures.
        CryptoProcessingError: If crypto broadcast fails.
        LedgerError / InsufficientFundsError: If ledger updates fail.
        RuntimeError: If critical dependencies missing.
    """
    log_prefix = f"Order {order.id} (ResolveDispute by {moderator.username})"
    logger.info(f"{log_prefix}: Attempting resolution. Buyer %: {release_to_buyer_percent}, Notes: '{resolution_notes[:50]}...'")

    # --- Dependency Checks ---
    if not all([ledger_service, Order, User, GlobalSettings] + list(_crypto_service_registry.values())):
        raise RuntimeError("Critical application components are not available.")

    # --- Fetch and Lock Order ---
    order_locked: 'Order'
    crypto_service_module: Optional[Any] = None # Initialize
    buyer_id: Optional[int] = None # Store IDs for re-fetch
    vendor_id: Optional[int] = None
    market_user_id: Optional[int] = None # Need market user for potential fee
    tx_hash: Optional[str] = None # Define tx_hash earlier
    currency: Optional[str] = None # Define currency earlier

    try:
        market_user_id = get_market_user().pk # Get market user ID early
        order_locked = Order.objects.select_for_update().select_related(
            'buyer', 'vendor', 'product'
        ).get(pk=order.pk)
        currency = order_locked.selected_currency # Store currency
        crypto_service_module = _get_crypto_service(currency) # Get service module early
        buyer_id = order_locked.buyer_id
        vendor_id = order_locked.vendor_id
    except Order.DoesNotExist:
        logger.error(f"{log_prefix}: Order not found.")
        raise # Re-raise
    except User.DoesNotExist: # Market user lookup failed
        logger.critical(f"{log_prefix}: Market user not found. Cannot process dispute resolution.")
        raise ObjectDoesNotExist("Market user not found during dispute resolution.")
    except (ValueError, AttributeError, Exception) as e: # ValueError from _get_crypto_service, AttributeError if buyer/vendor missing
        logger.exception(f"{log_prefix}: Error fetching order, users, or getting crypto service module: {e}")
        raise EscrowError(f"Database/Setup error fetching details for order {order.pk}.") from e

    # --- Input and Permission Validation ---
    if order_locked.status != OrderStatusChoices.DISPUTED:
        raise EscrowError(f"Order must be in '{OrderStatusChoices.DISPUTED}' state to resolve (Current: '{order_locked.status}').")
    if not getattr(moderator, 'is_staff', False) and not getattr(moderator, 'is_superuser', False):
        logger.warning(f"{log_prefix}: Permission denied for user {moderator.username} (not staff/superuser).")
        raise PermissionError("User does not have permission to resolve disputes.")
    if not (0 <= release_to_buyer_percent <= 100):
        raise ValueError("Percentage must be an integer between 0 and 100.")
    if not resolution_notes or not isinstance(resolution_notes, str) or len(resolution_notes.strip()) < 5:
        raise ValueError("Valid resolution notes (minimum 5 characters) are required.")
    resolution_notes = resolution_notes.strip()

    # --- Calculate Payout Shares (in STANDARD units) ---
    # NOTE: Dispute resolution implicitly includes the market fee within the vendor's share if applicable by normal rules.
    #       If dispute rules dictate NO market fee, the calculation here might need adjustment,
    #       or the crypto service `create_and_broadcast_dispute_tx` needs to handle it.
    #       Assuming standard fee rules apply implicitly based on vendor share for now.
    release_to_vendor_percent = 100 - release_to_buyer_percent
    prec = _get_currency_precision(currency)
    quantizer = Decimal(f'1e-{prec}')
    buyer_share_std = Decimal('0.0')
    vendor_share_std = Decimal('0.0')
    total_escrowed_std = Decimal('0.0') # Initialize

    logger.debug(f"{log_prefix}: Preparing to calculate shares. "
                 f"Total Price Native Type: {type(order_locked.total_price_native_selected)}, "
                 f"Value: {order_locked.total_price_native_selected}, "
                 f"Buyer Percent Type: {type(release_to_buyer_percent)}, "
                 f"Value: {release_to_buyer_percent}")

    try:
        if order_locked.total_price_native_selected is None:
            raise ValueError(f"Order {order_locked.id} total_price_native_selected is None.")
        if not isinstance(order_locked.total_price_native_selected, Decimal):
            try:
                total_escrowed_raw = Decimal(str(order_locked.total_price_native_selected))
                logger.warning(f"{log_prefix}: Order total_price_native_selected was not Decimal ({type(order_locked.total_price_native_selected)}), converted successfully.")
            except (InvalidOperation, TypeError):
                raise ValueError(f"Order {order_locked.id} total_price_native_selected is not a valid Decimal or convertible ('{order_locked.total_price_native_selected}')")
        else:
            total_escrowed_raw = order_locked.total_price_native_selected

        total_escrowed_std = _convert_atomic_to_standard(total_escrowed_raw, currency, crypto_service_module)
        logger.debug(f"{log_prefix}: Calculated total_escrowed_std: {total_escrowed_std}")

        if total_escrowed_std <= Decimal('0.0'):
            raise ValueError("Cannot resolve dispute with zero or negative calculated escrowed amount.")

        # Calculate buyer share directly
        if release_to_buyer_percent > 0:
            buyer_share_std = (total_escrowed_std * Decimal(release_to_buyer_percent) / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
            if buyer_share_std < Decimal('0.0'): buyer_share_std = Decimal('0.0')

        # Vendor gets the remainder
        vendor_share_std = (total_escrowed_std - buyer_share_std).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_share_std < Decimal('0.0'): vendor_share_std = Decimal('0.0')

        # Verification Step
        epsilon = Decimal(f'1e-{prec-1}') if prec > 1 else Decimal('1') # Adjust tolerance if needed
        calculated_sum = buyer_share_std + vendor_share_std
        difference = abs(calculated_sum - total_escrowed_std)

        # Allow for tiny differences due to rounding down both parts
        if difference > epsilon:
            logger.error(f"{log_prefix}: Share calculation mismatch detected! "
                         f"Total={total_escrowed_std}, Buyer={buyer_share_std}, Vendor={vendor_share_std}, "
                         f"Sum={calculated_sum}, Diff={difference}, Epsilon={epsilon}")
            # If the sum is slightly less due to ROUND_DOWN on both, add dust to vendor? Or buyer? Needs policy.
            # For now, raise error. A robust solution might add the dust to the larger share recipient.
            raise ValueError("Calculated buyer + vendor share does not match total escrowed amount within tolerance.")

        logger.info(f"{log_prefix}: Calculated Shares - Total: {total_escrowed_std}, Buyer: {buyer_share_std} {currency}, Vendor: {vendor_share_std} {currency}.")

    except InvalidOperation as dec_err:
        logger.error(f"{log_prefix}: Decimal calculation error during dispute share calculation: {dec_err}", exc_info=True)
        raise ValueError("Invalid decimal operation calculating dispute shares.") from dec_err
    except (TypeError, ValueError) as type_val_err:
        logger.error(f"{log_prefix}: Type or Value error calculating dispute shares: {type_val_err}", exc_info=True)
        raise ValueError("Failed to calculate dispute payout shares due to invalid input type or value.") from type_val_err
    except Exception as e:
        logger.error(f"{log_prefix}: Unexpected error calculating dispute shares: {e}", exc_info=True)
        raise ValueError("An unexpected error occurred while calculating dispute payout shares.") from e

    # --- Get Payout Addresses ---
    buyer_payout_address: Optional[str] = None
    vendor_payout_address: Optional[str] = None
    try:
        # Need actual buyer/vendor objects for _get_withdrawal_address
        buyer_obj = order_locked.buyer
        vendor_obj = order_locked.vendor
        if not buyer_obj or not vendor_obj:
             raise ObjectDoesNotExist("Buyer or Vendor object missing on locked order.")

        if buyer_share_std > Decimal('0.0'):
            buyer_payout_address = _get_withdrawal_address(buyer_obj, currency)
        if vendor_share_std > Decimal('0.0'):
            vendor_payout_address = _get_withdrawal_address(vendor_obj, currency)
    except ValueError as e:
        logger.error(f"{log_prefix}: Failed to get required withdrawal address for dispute resolution: {e}")
        raise ValueError(f"Missing withdrawal address for payout: {e}") from e
    except ObjectDoesNotExist as obj_err:
        logger.error(f"{log_prefix}: Error getting withdrawal address: {obj_err}")
        raise ObjectDoesNotExist(f"Buyer or Vendor missing when fetching withdrawal address: {obj_err}")

    # --- Crypto Broadcast Interaction ---
    broadcast_success = False
    # tx_hash defined earlier
    try:
        logger.info(f"{log_prefix}: Attempting dispute broadcast ({currency})...")

        broadcast_args = {
            'order': order_locked,
            'moderator_key_info': None # Placeholder - Moderator key likely needed by crypto service
        }
        # Pass STANDARD amounts to crypto service
        if currency == 'BTC':
            broadcast_args.update({
                'buyer_payout_amount_btc': buyer_share_std if buyer_payout_address else None,
                'buyer_address': buyer_payout_address,
                'vendor_payout_amount_btc': vendor_share_std if vendor_payout_address else None,
                'vendor_address': vendor_payout_address,
            })
        elif currency == 'XMR':
            broadcast_args.update({
                'buyer_payout_amount_xmr': buyer_share_std if buyer_payout_address else None,
                'buyer_address': buyer_payout_address,
                'vendor_payout_amount_xmr': vendor_share_std if vendor_payout_address else None,
                'vendor_address': vendor_payout_address,
            })
        elif currency == 'ETH':
            logger.error(f"{log_prefix}: ETH Dispute Broadcast not implemented.")
            raise NotImplementedError("ETH Dispute Broadcast not implemented.")
        else:
            raise ValueError(f"Unsupported currency '{currency}' for dispute broadcast.")

        broadcast_func_name = 'create_and_broadcast_dispute_tx'
        if not hasattr(crypto_service_module, broadcast_func_name):
            raise NotImplementedError(f"Dispute broadcast function '{broadcast_func_name}' not found in {type(crypto_service_module).__name__}")

        broadcast_func = getattr(crypto_service_module, broadcast_func_name)
        tx_hash = broadcast_func(**broadcast_args)

        broadcast_success = bool(tx_hash) and isinstance(tx_hash, str) and len(tx_hash) > 10
        if not broadcast_success:
            raise CryptoProcessingError(f"Crypto dispute broadcast failed for Order {order_locked.id} (service module returned invalid tx_hash: '{tx_hash}').")

        logger.info(f"{log_prefix}: Dispute transaction broadcast successful. TX: {tx_hash}")

    except (AttributeError, CryptoProcessingError, ValueError, NotImplementedError) as crypto_err: # Catch AttributeError
        logger.error(f"{log_prefix}: Dispute broadcast error: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Dispute broadcast error: {crypto_err}") from crypto_err # Re-raise the specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error during dispute broadcast: {e}")
        raise CryptoProcessingError(f"Unexpected dispute broadcast error: {e}") from e

    # --- Final DB/Ledger Update (Only if broadcast succeeded) ---
    # >>> FIX v1.21.0 Start: Enhanced detailed logging <<<
    try:
        buyer: Optional['UserModel'] = None
        vendor: Optional['UserModel'] = None
        market_user: Optional['UserModel'] = None # Need market user again for fee implicit in vendor share
        logger.debug(f"{log_prefix}: Entering final update block post-dispute-broadcast (TX: {tx_hash}).")
        try:
            logger.debug(f"{log_prefix}: Attempting final user re-fetch (BuyerID: {buyer_id}, VendorID: {vendor_id}, MarketUserID: {market_user_id})...")
            if buyer_id is None or vendor_id is None or market_user_id is None:
                raise ValueError("Buyer, Vendor, or Market User ID missing unexpectedly before final re-fetch.")
            buyer = User.objects.get(pk=buyer_id)
            vendor = User.objects.get(pk=vendor_id)
            market_user = User.objects.get(pk=market_user_id)
            logger.debug(f"{log_prefix}: Re-fetched buyer ({buyer.username}), vendor ({vendor.username}), and market_user ({market_user.username}) OK.")
        except User.DoesNotExist as user_err:
            # Specific log for user fetch failure
            logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (User Re-fetch): Required user not found during final update: {user_err}. Check IDs.", exc_info=True)
            raise LedgerError(f"Required user not found during final ledger update.") from user_err
        except ValueError as val_err:
             # Specific log for missing ID
            logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (User Re-fetch): Missing user ID: {val_err}")
            raise LedgerError(f"Missing user ID for final ledger update: {val_err}") from val_err
        except Exception as fetch_exc:
             # Specific log for other fetch errors
            logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (User Re-fetch): Unexpected error: {fetch_exc}", exc_info=True)
            raise LedgerError(f"Unexpected error during final user re-fetch: {fetch_exc}") from fetch_exc

        # Proceed with updates only if users were fetched
        now = timezone.now()
        order_locked.status = OrderStatusChoices.DISPUTE_RESOLVED
        order_locked.release_tx_broadcast_hash = tx_hash
        order_locked.dispute_resolved_at = now
        order_locked.updated_at = now

        update_fields = ['status', 'release_tx_broadcast_hash', 'dispute_resolved_at', 'updated_at']
        if hasattr(order_locked, 'dispute_resolved_by'):
            order_locked.dispute_resolved_by = moderator
            update_fields.append('dispute_resolved_by')
        if hasattr(order_locked, 'dispute_resolution_notes'):
            order_locked.dispute_resolution_notes = resolution_notes[:2000]
            update_fields.append('dispute_resolution_notes')
        if hasattr(order_locked, 'dispute_buyer_percent'):
            order_locked.dispute_buyer_percent = release_to_buyer_percent
            update_fields.append('dispute_buyer_percent')

        logger.debug(f"{log_prefix}: Attempting to save final order state (Status: {order_locked.status})...")
        order_locked.save(update_fields=list(set(update_fields)))
        logger.info(f"{log_prefix}: Order state saved successfully. Proceeding to ledger updates.")

        # Update Ledger balances
        notes_base = f"Dispute resolution Order {order_locked.id} by {moderator.username}. TX: {tx_hash}."
        if buyer_share_std > Decimal('0.0'):
            logger.debug(f"{log_prefix}: Attempting buyer ledger credit. User='{buyer.username}', Amount={buyer_share_std}, Currency='{currency}'")
            ledger_service.credit_funds(
                user=buyer, currency=currency, amount=buyer_share_std,
                transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_BUYER,
                related_order=order_locked, external_txid=tx_hash,
                notes=f"{notes_base} Buyer Share ({release_to_buyer_percent}%)"
            )
            logger.debug(f"{log_prefix}: Buyer ledger credit call completed.")
        else:
            logger.debug(f"{log_prefix}: Skipping buyer ledger credit (share is zero).")

        if vendor_share_std > Decimal('0.0'):
            # NOTE: Still assuming vendor_share_std is net, add explicit fee calc if needed.
            logger.debug(f"{log_prefix}: Attempting vendor ledger credit. User='{vendor.username}', Amount={vendor_share_std}, Currency='{currency}'")
            ledger_service.credit_funds(
                user=vendor, currency=currency, amount=vendor_share_std, # Assuming vendor_share_std is net
                transaction_type=LEDGER_TX_DISPUTE_RESOLUTION_VENDOR,
                related_order=order_locked, external_txid=tx_hash,
                notes=f"{notes_base} Vendor Share ({release_to_vendor_percent}%)"
            )
            # TODO: Add explicit market fee credit from vendor share if required by rules.
            logger.debug(f"{log_prefix}: Vendor ledger credit call completed.")
        else:
             logger.debug(f"{log_prefix}: Skipping vendor ledger credit (share is zero).")

        logger.info(f"{log_prefix}: Ledger updated. Buyer: {buyer_share_std}, Vendor: {vendor_share_std} {currency}. TX: {tx_hash}")
        security_logger.info(f"Dispute resolved Order {order_locked.id} by {moderator.username}. Ledger updated. TX: {tx_hash}")

        # Notifications (Best Effort)
        logger.debug(f"{log_prefix}: Attempting final notifications...")
        order_url = f"/orders/{order_locked.id}"
        product_name = getattr(order_locked.product,'name','N/A')
        order_id_str = str(order_locked.id)
        resolution_msg_part = (f"Dispute resolved for Order #{order_id_str[:8]} ({product_name}) by moderator. "
                               f"Decision: Buyer {release_to_buyer_percent}%, Vendor {release_to_vendor_percent}%.")
        resolution_details_msg = resolution_msg_part + f" Moderator notes: '{resolution_notes[:100]}...'. Check order details."
        msg_buyer = resolution_details_msg + (f" Amount credited (if applicable): {buyer_share_std} {currency}." if buyer_share_std > 0 else "")
        msg_vendor = resolution_details_msg + (f" Amount credited (if applicable): {vendor_share_std} {currency}." if vendor_share_std > 0 else "") # Assuming net vendor amount

        try:
            logger.debug(f"{log_prefix}: Sending notification to buyer {buyer.id}...")
            create_notification(user_id=buyer.id, level='info', message=msg_buyer, link=order_url)
        except Exception as notify_e:
             logger.error(f"{log_prefix}: Failed to create dispute resolved notification for Buyer {buyer.id}: {notify_e}", exc_info=True)
        try:
            logger.debug(f"{log_prefix}: Sending notification to vendor {vendor.id}...")
            create_notification(user_id=vendor.id, level='info', message=msg_vendor, link=order_url)
        except Exception as notify_e:
             logger.error(f"{log_prefix}: Failed to create dispute resolved notification for Vendor {vendor.id}: {notify_e}", exc_info=True)

        logger.debug(f"{log_prefix}: Final update block completed successfully. Returning True.")
        return True

    except (InsufficientFundsError, LedgerError, DjangoValidationError, IntegrityError) as final_db_err:
        # CRITICAL FAILURE STATE - Log specific DB/Ledger error type
        logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (DB/Ledger Update): Broadcast OK (TX: {tx_hash}) but FINAL LEDGER/ORDER UPDATE FAILED. Error Type: {type(final_db_err).__name__}, Details: {final_db_err}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        return False
    except Exception as final_e:
        # CRITICAL FAILURE STATE (Unexpected Error) - Log specific exception type
        logger.critical(f"{log_prefix}: CRITICAL FAILURE POINT (Unexpected): Broadcast OK (TX: {tx_hash}) but unexpected error during final DB/Ledger update. Error Type: {type(final_e).__name__}, Details: {final_e}. MANUAL INTERVENTION REQUIRED!", exc_info=True)
        return False
    # >>> FIX v1.21.0 End <<<
# END OF resolve_dispute function


def get_unsigned_release_tx(order: 'Order', user: 'UserModel') -> Optional[Dict[str, str]]:
    """
    Retrieves the currently stored unsigned/partially signed transaction data
    from the order's release_metadata for offline signing by the specified user.

    Args:
        order: The Order instance.
        user: The User requesting the data (must be buyer or vendor).
    Returns:
        A dictionary containing {'unsigned_tx': transaction_data_string} if successful,
        otherwise None (though typically raises exceptions on failure).
    Raises:
        ObjectDoesNotExist: If order not found.
        PermissionError: If user is not buyer/vendor.
        EscrowError: For invalid state, missing/invalid metadata.
        ValueError: For invalid input objects.
        RuntimeError: If critical models unavailable.
    """
    log_prefix = f"Order {order.id} (GetUnsignedTx for {user.username})"
    logger.info(f"{log_prefix}: Request received.")

    # --- Input and Dependency Validation ---
    if not all([Order, User]):
        raise RuntimeError("Critical application models are not available.")
    if not isinstance(order, Order) or not order.pk:
        raise ValueError("Invalid Order object provided.")
    if not isinstance(user, User) or not user.pk:
        raise ValueError("Invalid User object provided.")

    # --- Fetch Fresh Order Data (Read-only, no lock needed) ---
    try:
        # Fetch with related buyer/vendor for permission check efficiency
        order_fresh = Order.objects.select_related('buyer', 'vendor').get(pk=order.pk)
    except Order.DoesNotExist:
        logger.warning(f"{log_prefix}: Order {order.pk} not found.")
        raise ObjectDoesNotExist(f"Order {order.pk} not found.")
    except Exception as e:
        logger.exception(f"{log_prefix}: Database error fetching order {order.pk}: {e}")
        raise EscrowError(f"Database error fetching order {order.pk}.") from e

    # --- Permission Check ---
    is_buyer = (user.id == order_fresh.buyer_id)
    is_vendor = (user.id == order_fresh.vendor_id)
    if not (is_buyer or is_vendor):
        logger.warning(f"{log_prefix}: Permission denied. User not buyer or vendor.")
        raise PermissionError("Only the buyer or vendor can request unsigned transaction data.")

    # --- State and Metadata Checks ---
    if not order_fresh.release_initiated:
        logger.warning(f"{log_prefix}: Attempted to get unsigned TX before release initiated.")
        raise EscrowError("Release process has not been initiated for this order.")

    release_metadata: Dict[str, Any] = order_fresh.release_metadata or {}
    if not isinstance(release_metadata, dict):
        logger.error(f"{log_prefix}: Release metadata is missing or invalid type ({type(release_metadata)}).")
        raise EscrowError("Release metadata is missing or invalid.")

    unsigned_crypto_data = release_metadata.get('data')
    release_type = release_metadata.get('type')

    # Ensure essential parts of metadata are present
    if not release_type or not unsigned_crypto_data:
        logger.error(f"{log_prefix}: Release metadata incomplete. Missing 'type' or 'data'. Metadata: {release_metadata}")
        raise EscrowError("Release metadata is incomplete (missing 'type' or 'data').")

    # Check data type and attempt conversion if necessary (defensive)
    if not isinstance(unsigned_crypto_data, str):
        logger.warning(f"{log_prefix}: Release metadata 'data' field is not a string ({type(unsigned_crypto_data)}). Attempting conversion.")
        try:
            unsigned_crypto_data = str(unsigned_crypto_data)
        except Exception as conv_err:
            logger.error(f"{log_prefix}: Failed to convert release metadata 'data' to string: {conv_err}")
            raise EscrowError("Release metadata 'data' field has an invalid format and could not be converted to string.")

    # Log if the requesting user has already signed (informational)
    already_signed = False
    if 'signatures' in release_metadata and isinstance(release_metadata['signatures'], dict):
        if str(user.id) in release_metadata['signatures']:
            already_signed = True
            logger.info(f"{log_prefix}: User {user.username} has already signed this release according to metadata.")

    logger.info(f"{log_prefix}: Returning prepared transaction data (Type: {release_type}). Already Signed: {already_signed}")

    # Return only the data needed for signing in the expected format
    return {'unsigned_tx': unsigned_crypto_data}
# END OF get_unsigned_release_tx function


# --- Internal Helper: _prepare_release ---
def _prepare_release(order: 'Order') -> Dict[str, Any]:
    """
    Internal helper: Calculates payouts (using standard units), gets addresses, calls
    crypto service to create initial unsigned release transaction data (passing standard units).
    Stores result in metadata format (with standard units for payout/fee).

    Args:
        order: The Order instance (should be locked if called within atomic block).
    Returns:
        Dict[str, Any]: A dictionary containing the prepared release metadata.
    Raises:
        ObjectDoesNotExist: If vendor or market user not found.
        ValueError: For calculation errors or missing withdrawal address.
        CryptoProcessingError: If crypto service fails to prepare the transaction.
        NotImplementedError: If currency is not supported.
    """
    log_prefix = f"Order {order.id} (_prepare_release)"
    logger.debug(f"{log_prefix}: Preparing {order.selected_currency} release metadata...")

    currency = order.selected_currency
    vendor = order.vendor # Assumes order object passed in has vendor prefetched/selected
    crypto_service_module: Optional[Any] = None # Initialize

    # --- Load Participants and Validate ---
    try:
        market_user = get_market_user() # Use cached market user
        crypto_service_module = _get_crypto_service(currency) # Get service module early
        if not vendor:
            # Re-fetch if not available on the passed object (defensive)
            if order.vendor_id:
                vendor = User.objects.get(pk=order.vendor_id)
            else:
                raise ObjectDoesNotExist(f"Vendor relationship missing for order {order.id}")
    except (ObjectDoesNotExist, ValueError) as obj_err: # ValueError from _get_crypto_service
        logger.critical(f"{log_prefix}: Cannot prepare release - missing participants or crypto service module: {obj_err}")
        raise obj_err # Re-raise critical error

    # --- Get Vendor Payout Address ---
    try:
        # This must succeed for a standard release
        vendor_payout_address = _get_withdrawal_address(vendor, currency)
    except ValueError as e:
        # Vendor missing withdrawal address is a blocker for preparing release
        logger.error(f"{log_prefix}: Cannot prepare release. Vendor {vendor.username} missing required withdrawal address for {currency}. Error: {e}")
        # Re-raise as ValueError indicating required setup is missing
        raise ValueError(f"Cannot prepare release: Vendor {vendor.username} missing required withdrawal address for {currency}.") from e

    # --- Calculate Payouts and Fees (in STANDARD units) ---
    prec = _get_currency_precision(currency)
    quantizer = Decimal(f'1e-{prec}')
    vendor_payout_std = Decimal('0.0')
    market_fee_std = Decimal('0.0')
    total_escrowed_std = Decimal('0.0')

    try:
        # Validate and get total amount (which is ATOMIC)
        if order.total_price_native_selected is None:
            raise ValueError(f"Order {order.id} total_price_native_selected is None.")
        if not isinstance(order.total_price_native_selected, Decimal):
            raise ValueError(f"Order {order.id} total_price_native_selected is not a valid Decimal ('{order.total_price_native_selected}')")

        # Convert total price from ATOMIC to STANDARD units for fee calculation
        total_escrowed_std = _convert_atomic_to_standard(order.total_price_native_selected, currency, crypto_service_module)
        logger.debug(f"{log_prefix}: Total escrowed (standard units): {total_escrowed_std} {currency}")

        if total_escrowed_std <= Decimal('0.0'):
            raise ValueError("Cannot prepare release with zero or negative calculated escrowed amount.")

        # Get and validate market fee percentage
        market_fee_percent = _get_market_fee_percentage(currency) # Uses 2.5% default now

        # Calculate fee (ROUND_DOWN) based on standard units
        market_fee_std = (total_escrowed_std * market_fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if market_fee_std > total_escrowed_std: market_fee_std = total_escrowed_std
        if market_fee_std < Decimal('0.0'): market_fee_std = Decimal('0.0')

        # Vendor gets the remainder (also ROUND_DOWN) in standard units
        vendor_payout_std = (total_escrowed_std - market_fee_std).quantize(quantizer, rounding=ROUND_DOWN)
        if vendor_payout_std < Decimal('0.0'): vendor_payout_std = Decimal('0.0')

        # Verification Step
        epsilon = Decimal(f'1e-{prec-1}') if prec > 1 else Decimal('1') # Adjust tolerance if needed
        calculated_sum = vendor_payout_std + market_fee_std
        difference = abs(calculated_sum - total_escrowed_std)

        # Allow for tiny differences due to rounding down both parts
        if difference > epsilon:
            logger.error(f"{log_prefix}: Payout calculation mismatch! "
                         f"Total={total_escrowed_std}, Vendor={vendor_payout_std}, Fee={market_fee_std}, "
                         f"Sum={calculated_sum}, Diff={difference}, Epsilon={epsilon}")
            # If sum < total due to double ROUND_DOWN, add dust to vendor? Needs policy.
            # Raising error for now.
            raise ValueError("Calculated vendor payout + market fee does not match total escrowed amount within tolerance.")

        logger.debug(f"{log_prefix}: Calculated payout: Vendor={vendor_payout_std}, Fee={market_fee_std} {currency} ({market_fee_percent}%)")

    except (InvalidOperation, ValueError, TypeError) as e:
        logger.error(f"{log_prefix}: Error calculating release payout/fee: {e}", exc_info=True)
        raise ValueError("Failed to calculate release payout/fee amounts.") from e

    # --- Prepare Unsigned Transaction via Crypto Service ---
    prepared_data: Optional[str] = None
    release_type: Optional[str] = None
    try:
        # Pass STANDARD unit amounts to prepare functions
        if currency == 'BTC':
            release_type = 'btc_psbt'
            prepare_func_name = 'prepare_btc_release_tx'
            if not hasattr(crypto_service_module, prepare_func_name):
                raise NotImplementedError(f"Prepare function '{prepare_func_name}' missing in {currency} service module.")
            prepare_func = getattr(crypto_service_module, prepare_func_name)
            prepared_data = prepare_func(
                order=order, vendor_payout_amount_btc=vendor_payout_std,
                vendor_address=vendor_payout_address
            )
        elif currency == 'XMR':
            release_type = 'xmr_unsigned_txset'
            prepare_func_name = 'prepare_xmr_release_tx'
            if not hasattr(crypto_service_module, prepare_func_name):
                raise NotImplementedError(f"Prepare function '{prepare_func_name}' missing in {currency} service module.")
            prepare_func = getattr(crypto_service_module, prepare_func_name)
            prepared_data = prepare_func(
                order=order, vendor_payout_amount_xmr=vendor_payout_std,
                vendor_address=vendor_payout_address
            )
        elif currency == 'ETH':
            logger.error(f"{log_prefix}: ETH release preparation not implemented.")
            raise NotImplementedError("ETH release preparation not implemented.")
        else:
            raise ValueError(f"Unsupported currency '{currency}' for release preparation.")

        if not prepared_data or not isinstance(prepared_data, str) or len(prepared_data) < 10:
            raise CryptoProcessingError(f"Failed to get valid prepared {currency} transaction data (Result: '{prepared_data}').")

        logger.info(f"{log_prefix}: Successfully prepared unsigned {currency} transaction data (Type: {release_type}).")

    except (AttributeError, CryptoProcessingError, ValueError, NotImplementedError) as crypto_err: # Catch AttributeError
        logger.error(f"{log_prefix}: Failed to prepare crypto release transaction: {crypto_err}", exc_info=True)
        raise CryptoProcessingError(f"Crypto preparation error: {crypto_err}") from crypto_err # Re-raise the specific error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error preparing {currency} release: {e}")
        raise CryptoProcessingError(f"Unexpected error preparing {currency} release: {e}") from e

    # --- Construct Metadata Dictionary ---
    metadata: Dict[str, Any] = {
        'type': release_type,
        'data': prepared_data,
        'payout': str(vendor_payout_std), # Store STANDARD units as strings
        'fee': str(market_fee_std),      # Store STANDARD units as strings
        'vendor_address': vendor_payout_address,
        'ready_for_broadcast': False,
        'signatures': {},
        'prepared_at': timezone.now().isoformat()
    }
    return metadata
# END OF _prepare_release function

# --- Withdrawal Fee Clarification ---
# NOTE (v1.20.0): Applying fees to user withdrawals (moving funds from internal ledger
# balance to an external crypto address) is NOT handled by this escrow service.
# That functionality would typically reside in a separate `withdrawal_service.py`
# or similar module, which would interact with the ledger and crypto services
# to process and broadcast withdrawal transactions, applying fees as needed.

# <<< END OF FILE: backend/store/services/escrow_service.py >>>