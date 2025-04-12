# backend/store/utils/conversion.py
# Revision History:
# - v1.1.1 (2025-04-11): Added alias xmr_to_piconero = to_atomic to resolve AttributeError
#                        in market_wallet_service. Uncommented ETH in CURRENCY_CONFIG. (Gemini Rev 6)
# - v1.1.0 (2025-04-06): Enterprise Grade Refactor: Added CURRENCY_CONFIG, custom exceptions,
#                        enhanced validation, logging, type hinting, and improved structure.
# - v1.0.0 (2025-04-06): Initial creation to resolve ModuleNotFoundError in tests.

# --- Standard Library Imports ---
import logging
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Dict, NamedTuple, Union

# --- Setup Logging ---
# In a full enterprise application, logger configuration would typically be centralized.
# This provides a basic logger instance for this module.
logger = logging.getLogger(__name__)

# --- Custom Exceptions ---
class ConversionError(Exception):
    """Base class for errors during currency conversion."""
    pass

class UnsupportedCurrencyError(ConversionError):
    """Raised when an unsupported currency code is provided."""
    def __init__(self, currency_code: str):
        self.currency_code = currency_code
        super().__init__(f"Unsupported currency for conversion: {currency_code}")

class InvalidAmountError(ConversionError):
    """Raised when an invalid amount (type, value, sign) is provided for conversion."""
    def __init__(self, message: str):
        super().__init__(message)


# --- Currency Configuration ---
class CurrencyInfo(NamedTuple):
    """Holds configuration details for a supported cryptocurrency."""
    atomic_factor: int          # Factor to multiply standard units by to get atomic units (e.g., 10^8 for BTC)
    quantizer: Decimal          # Decimal quantizer for standard representation (e.g., Decimal('1e-8'))
    symbol: str                 # Canonical currency symbol (uppercase)

# Centralized configuration for supported currencies.
# Makes adding/modifying currencies easier and less error-prone.
# Keys should be uppercase currency codes.
CURRENCY_CONFIG: Dict[str, CurrencyInfo] = {
    'BTC': CurrencyInfo(
        atomic_factor=100_000_000,      # 10^8 Satoshis per BTC
        quantizer=Decimal('1e-8'),    # Standard BTC precision
        symbol='BTC'
    ),
    'XMR': CurrencyInfo(
        atomic_factor=1_000_000_000_000, # 10^12 Piconeros per XMR
        quantizer=Decimal('1e-12'),   # Standard XMR precision
        symbol='XMR'
    ),
    # --- Add other supported currencies here ---
    # Example: ETH (Uncommented as it's a standard currency likely needed)
    'ETH': CurrencyInfo(
        atomic_factor=1_000_000_000_000_000_000, # 10^18 Wei per ETH
        quantizer=Decimal('1e-18'),          # Standard ETH precision
        symbol='ETH'
    ),
}

# --- Conversion Functions ---

def to_atomic(amount_std: Decimal, currency: str) -> int:
    """
    Converts a standard currency amount (Decimal) to its atomic unit (integer).

    Ensures the amount is non-negative and valid before conversion. Handles
    conversion by multiplying with the currency's atomic factor and taking the
    integer part (effectively rounding towards zero).

    Args:
        amount_std: The amount in standard units (e.g., Decimal('0.5')). Must be a non-negative Decimal.
        currency: The currency code (e.g., 'BTC', 'XMR'). Case-insensitive.

    Returns:
        The equivalent amount in atomic units (integer).

    Raises:
        UnsupportedCurrencyError: If the currency code is not configured in CURRENCY_CONFIG.
        InvalidAmountError: If the amount is negative, None, NaN, infinite, or causes calculation issues.
        TypeError: If amount_std is not a Decimal or currency is not a string.
    """
    # --- Input Type Validation ---
    if not isinstance(currency, str):
        # Logged at ERROR because it indicates a programming error calling this function.
        logger.error("Invalid type for currency: Expected str, got %s", type(currency))
        raise TypeError("Currency code must be a string.")
    if not isinstance(amount_std, Decimal):
        logger.error("Invalid type for amount_std: Expected Decimal, got %s", type(amount_std))
        raise TypeError(f"Input amount must be a Decimal, got {type(amount_std)}")

    # --- Input Value Validation ---
    if amount_std is None: # Should ideally be caught by static analysis with non-Optional type hint
        raise InvalidAmountError("Input amount cannot be None.")
    if amount_std.is_nan() or amount_std.is_infinite():
        raise InvalidAmountError(f"Invalid Decimal amount (NaN or Infinity): {amount_std}")
    if amount_std < Decimal('0'):
        # Enforce non-negative amounts for standard representation-to-atomic conversion.
        # Ledger operations dealing with debits/credits might handle negatives differently elsewhere.
        raise InvalidAmountError(f"Input standard amount cannot be negative: {amount_std}")

    # --- Get Currency Configuration ---
    currency_upper = currency.upper()
    config = CURRENCY_CONFIG.get(currency_upper)

    if config is None:
        logger.warning("Attempted 'to_atomic' conversion for unsupported currency: %s", currency)
        raise UnsupportedCurrencyError(currency_upper)

    # --- Conversion Logic ---
    try:
        # Multiply the standard Decimal amount by the atomic factor.
        # int() truncates (rounds towards zero), ensuring we don't create extra atomic units.
        # Example: 1.9 satoshis becomes 1 satoshi.
        atomic_value = int(amount_std * config.atomic_factor)

        # Python integers handle arbitrary size, so overflow is less likely than in
        # languages with fixed-size integers, but Decimal operations can still raise.

        return atomic_value

    except (InvalidOperation, OverflowError, ValueError) as e: # Catch potential Decimal/int issues
        logger.error(
            "Error converting %s %s to atomic units: %s",
            amount_std, currency_upper, e, exc_info=True # Log stack trace for errors
        )
        # Raise a specific, user-friendly error.
        raise InvalidAmountError(f"Calculation error converting {amount_std} {currency_upper} to atomic units.") from e


def from_atomic(amount_atomic: int, currency: str) -> Decimal:
    """
    Converts an atomic currency amount (integer) back to its standard unit (Decimal).

    Ensures the atomic amount is a non-negative integer. Quantizes the result
    to the standard precision for the currency using ROUND_DOWN to avoid
    artificially inflating values.

    Args:
        amount_atomic: The amount in atomic units (e.g., 50000000). Must be a non-negative integer.
        currency: The currency code (e.g., 'BTC', 'XMR'). Case-insensitive.

    Returns:
        The equivalent amount in standard units (Decimal), quantized (rounded down)
        to the currency's standard precision.

    Raises:
        UnsupportedCurrencyError: If the currency code is not configured in CURRENCY_CONFIG.
        InvalidAmountError: If the atomic amount is negative, None, or causes calculation issues.
        TypeError: If amount_atomic is not an integer or currency is not a string.
    """
    # --- Input Type Validation ---
    if not isinstance(currency, str):
        logger.error("Invalid type for currency: Expected str, got %s", type(currency))
        raise TypeError("Currency code must be a string.")
    if not isinstance(amount_atomic, int):
        logger.error("Invalid type for amount_atomic: Expected int, got %s", type(amount_atomic))
        raise TypeError(f"Input atomic amount must be an integer, got {type(amount_atomic)}")

    # --- Input Value Validation ---
    if amount_atomic is None:
        raise InvalidAmountError("Input atomic amount cannot be None.")
    if amount_atomic < 0:
        # Atomic units should represent a count, typically non-negative.
        raise InvalidAmountError(f"Input atomic amount cannot be negative: {amount_atomic}")

    # --- Get Currency Configuration ---
    currency_upper = currency.upper()
    config = CURRENCY_CONFIG.get(currency_upper)

    if config is None:
        logger.warning("Attempted 'from_atomic' conversion for unsupported currency: %s", currency)
        raise UnsupportedCurrencyError(currency_upper)

    # --- Conversion Logic ---
    try:
        # Use Decimal division for precise calculation
        standard_value = Decimal(amount_atomic) / Decimal(config.atomic_factor)

        # Quantize to the standard number of decimal places using the defined quantizer.
        # ROUND_DOWN is critical for financial accuracy (prevents rounding 0.000...001 up to 1).
        quantized_value = standard_value.quantize(config.quantizer, rounding=ROUND_DOWN)

        return quantized_value

    except (InvalidOperation, OverflowError, ValueError) as e: # Catch potential Decimal issues
        logger.error(
            "Error converting %d atomic units of %s to standard: %s",
            amount_atomic, currency_upper, e, exc_info=True # Log stack trace
        )
        raise InvalidAmountError(
            f"Calculation error converting {amount_atomic} {currency_upper} atomic units to standard."
        ) from e

# --- Aliases (for compatibility or clearer intent) ---

# Alias to satisfy the import in market_wallet_service.py
xmr_to_piconero = to_atomic

# --- End of File ---