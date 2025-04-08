# backend/ledger/services.py
# <<< REVISION 1 (YYYY-MM-DD) >>> # TODO: Update Date when applying
# --- CHANGES ---
# 1. Added explicit LedgerTransaction creation for lock_funds and unlock_funds using new assumed types 'LOCK_FUNDS', 'UNLOCK_FUNDS'.
# 2. Changed lock_funds to raise InsufficientFundsError instead of returning False.
# 3. Changed lock_funds to raise LedgerServiceError if UserBalance does not exist (instead of returning False).
# 4. Modified lock_funds and unlock_funds to return the created LedgerTransaction on success (or None for unlock if amount was zero).
# 5. Introduced LedgerConfigurationError for critical model/setup issues (e.g., missing available_balance property).
# 6. Updated error handling in record_transaction, get_user_balance, and lock_funds to raise LedgerConfigurationError for missing available_balance.
# 7. Updated docstrings for lock_funds and unlock_funds reflecting changes.
# 8. Ensured validation checks and atomic blocks remain intact.
# --- END CHANGES ---

"""
Service layer functions for managing user balances and ledger transactions.

Provides atomic operations for recording transactions, querying balances,
and locking/unlocking funds (e.g., for escrow or pending operations).

Handles validation, race conditions via row locking, and balance updates
atomically. Raises specific exceptions for known error conditions like
insufficient funds or invalid operations.
"""

import logging
from decimal import Decimal, InvalidOperation # Ensure InvalidOperation is imported
from typing import Optional, Tuple, Set, Union # Added Union

# Django Core Imports
from django.db import transaction, IntegrityError
# from django.conf import settings # Keep if settings like CURRENCY_PRECISIONS are used
from django.core.exceptions import ValidationError # Used as base for custom exceptions
from django.contrib.auth import get_user_model # Use get_user_model for flexibility

# Local Application Imports
# Ensure these paths are correct for your project structure.
# Using try-except for robustness during imports.
try:
    from .models import (
        UserBalance,
        LedgerTransaction,
        TRANSACTION_TYPE_CHOICES, # Assumed to contain LOCK_FUNDS, UNLOCK_FUNDS after model update
        CURRENCY_CHOICES,
    )
    # Assuming 'Order' model is defined elsewhere, adjust as necessary.
    from store.models import Order # Replace 'store' if Order is in another app

    # Custom exceptions are defined within this service file itself.

except ImportError as e:
    logging.basicConfig(level=logging.CRITICAL) # Fallback basic config
    _logger = logging.getLogger(__name__)
    _logger.critical(f"CRITICAL IMPORT ERROR in {__name__}: {e}. Check model paths/app dependencies.")
    # Re-raise to prevent application startup with missing dependencies.
    raise ImportError(f"Could not import required models/modules for ledger services: {e}") from e

# Setup Logger (Ideally configured via Django settings)
logger = logging.getLogger(__name__)

# Get the configured User model
User = get_user_model()

# --- Pre-compute valid choices for efficiency ---
# Assumes choices are defined as ((value1, label1), (value2, label2), ...)
try:
    VALID_TRANSACTION_TYPES: Set[str] = {choice[0] for choice in TRANSACTION_TYPE_CHOICES}
    VALID_CURRENCIES: Set[str] = {choice[0] for choice in CURRENCY_CHOICES}

    # Check if lock/unlock types are present (requires models.py update)
    # These checks are defensive; the code using them will fail later if types are missing.
    if 'LOCK_FUNDS' not in VALID_TRANSACTION_TYPES:
        logger.warning("Ledger Service: 'LOCK_FUNDS' not found in TRANSACTION_TYPE_CHOICES. lock_funds will fail.")
    if 'UNLOCK_FUNDS' not in VALID_TRANSACTION_TYPES:
        logger.warning("Ledger Service: 'UNLOCK_FUNDS' not found in TRANSACTION_TYPE_CHOICES. unlock_funds will fail.")

except (IndexError, TypeError) as e: # Catch potential errors if choices format is wrong
    logger.critical(f"CRITICAL SETUP ERROR: TRANSACTION_TYPE_CHOICES or CURRENCY_CHOICES"
                    f" are not in the expected format (e.g., ((val, label), ...)). Error: {e}")
    raise ValueError(f"Invalid format for ledger choices constants: {e}") from e


# --- Custom Exceptions (Defined within this service) ---

class LedgerServiceError(Exception):
    """Base exception for ledger service errors."""
    pass

class LedgerConfigurationError(LedgerServiceError):
    """Exception for critical internal configuration or model definition errors."""
    pass

class InsufficientFundsError(LedgerServiceError, ValidationError):
    """Custom exception for insufficient available balance."""
    def __init__(self, message, available=None, required=None, currency=None):
        self.available = available
        self.required = required
        self.currency = currency
        super().__init__(message) # Pass message to base Exception

class InvalidLedgerOperationError(LedgerServiceError, ValidationError):
    """Custom exception for invalid operations (e.g., bad type, amount format, non-positive amount)."""
    pass


# --- Core Transaction Logic ---

@transaction.atomic # Ensure all database operations within are atomic
def record_transaction(
    user: User,
    transaction_type: str,
    currency: str,
    amount: Decimal,
    related_order: Optional[Order] = None,
    external_txid: Optional[str] = None,
    notes: str = ""
) -> LedgerTransaction:
    """
    Records a ledger transaction and updates the user's balance atomically.
    Locks the UserBalance row during the transaction to prevent race conditions.

    Args:
        user: The User instance for whom the transaction is recorded.
        transaction_type: A valid identifier from TRANSACTION_TYPE_CHOICES.
        currency: A valid identifier from CURRENCY_CHOICES.
        amount: The amount to change the balance by (Decimal).
                Positive values represent credits (increase balance).
                Negative values represent debits (decrease balance).
        related_order: Optional related Order instance.
        external_txid: Optional external transaction identifier (e.g., blockchain txid).
        notes: Optional descriptive notes for the transaction.

    Returns:
        The created LedgerTransaction instance upon success.

    Raises:
        InvalidLedgerOperationError: If transaction_type, currency, or amount format is invalid.
        InsufficientFundsError: If attempting a debit greater than the available balance.
        LedgerConfigurationError: If critical model properties (e.g., available_balance) are missing.
        IntegrityError: For underlying database constraint violations.
        LedgerServiceError: For other ledger-specific operational errors.
        Exception: For unexpected errors during processing.
    """
    # 1. Input Validation
    if transaction_type not in VALID_TRANSACTION_TYPES:
        msg = f"Invalid transaction type: {transaction_type}"
        logger.error(f"{msg} for user {user.pk}.")
        raise InvalidLedgerOperationError(msg)
    if currency not in VALID_CURRENCIES:
        msg = f"Invalid currency: {currency}"
        logger.error(f"{msg} for user {user.pk}.")
        raise InvalidLedgerOperationError(msg)

    if not isinstance(amount, Decimal):
        try:
            amount = Decimal(str(amount)) # Use str() for robustness
        except InvalidOperation: # Specific Decimal exception
            msg = f"Invalid amount format '{amount!r}' (Type: {type(amount)})"
            logger.error(f"{msg} for user {user.pk}.")
            raise InvalidLedgerOperationError("Invalid amount format provided.")

    # Optional: Currency-specific precision/quantization
    # precision = settings.CURRENCY_PRECISIONS.get(currency, ...)
    # amount = amount.quantize(precision, rounding=ROUND_DOWN) # Example

    logger.debug(f"Attempting ledger transaction: User={user.pk}, Type={transaction_type}, "
                 f"Amount={amount}, Currency={currency}")

    # 2. Acquire Lock and Get/Create Balance Record
    balance_obj: UserBalance
    created: bool
    try:
        balance_obj, created = UserBalance.objects.select_for_update().get_or_create(
            user=user,
            currency=currency,
            defaults={'balance': Decimal('0.0'), 'locked_balance': Decimal('0.0')} # Sensible defaults
        )
        if created:
            logger.info(f"Created new UserBalance record for User {user.pk}, Currency {currency}.")

    except IntegrityError as e:
        logger.exception(f"Database integrity error getting/creating UserBalance User {user.pk}, Currency {currency}: {e}")
        raise # Re-raise the original DB error
    except Exception as e:
        logger.exception(f"Unexpected error getting/creating UserBalance User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError(f"Failed to access balance record for User {user.pk}, Currency {currency}.") from e

    # 3. Check Sufficient Funds for Debits (only if amount is negative)
    if amount < Decimal('0.0'):
        try:
            current_available = balance_obj.available_balance
        except AttributeError:
            # Critical configuration error - the UserBalance model is likely missing the required property.
            logger.critical(f"CRITICAL MODEL ERROR: UserBalance missing 'available_balance' property. User {user.pk}, Currency {currency}.")
            raise LedgerConfigurationError(f"Internal configuration error: Cannot determine available balance for {currency}. Model setup required.")
        except Exception as e:
            logger.exception(f"Error calculating available_balance User {user.pk}, Currency {currency}: {e}")
            raise LedgerServiceError("Failed to calculate available balance.") from e

        required_amount = abs(amount) # The positive amount needed for the debit

        if current_available < required_amount:
            logger.warning(
                f"Insufficient funds: User {user.pk}, Currency {currency}. "
                f"Available: {current_available}, Required Debit: {required_amount}"
            )
            raise InsufficientFundsError(
                f"Insufficient {currency} funds.",
                available=current_available,
                required=required_amount,
                currency=currency
            )

    # 4. Update Balance (if funds are sufficient or it's a credit)
    initial_balance: Decimal
    try:
        initial_balance = balance_obj.balance # Capture before change
        balance_obj.balance += amount
        balance_obj.save(update_fields=['balance']) # Save efficiently

        logger.debug(f"Balance updated User {user.pk}, Currency {currency}. "
                     f"Initial: {initial_balance}, Change: {amount}, New: {balance_obj.balance}")

    except Exception as e:
        logger.exception(f"Failed to save updated balance User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError("Failed to save balance update.") from e # Let atomic block handle rollback

    # 5. Create Ledger Entry (AFTER successful balance update)
    ledger_entry: LedgerTransaction
    try:
        # balance_obj fields now reflect the committed state *within this atomic transaction*.
        ledger_entry = LedgerTransaction.objects.create(
            user=user,
            transaction_type=transaction_type,
            currency=currency,
            amount=amount,
            balance_before=initial_balance, # Use captured value
            balance_after=balance_obj.balance, # Use updated value
            locked_balance_after=balance_obj.locked_balance, # Snapshot of locked state
            related_order=related_order,
            external_txid=external_txid,
            notes=notes
        )
        logger.info(
            f"Ledger transaction {ledger_entry.id} recorded: User {user.pk}, "
            f"Type {transaction_type}, Amount {amount} {currency}"
        )
    except Exception as e:
        logger.exception(f"Failed to create LedgerTransaction entry User {user.pk}, Currency {currency} after balance update: {e}")
        # Automatic rollback of balance update due to @transaction.atomic
        raise LedgerServiceError("Failed to record ledger transaction after balance update.") from e

    return ledger_entry


# --- Helper Functions (Semantic Wrappers for Credits/Debits) ---

def credit_funds(user: User, currency: str, amount: Decimal, transaction_type: str, **kwargs) -> LedgerTransaction:
    """
    Helper to record a credit transaction (increases balance).
    Ensures the credited amount is positive before calling record_transaction.

    Args:
        user: The User instance.
        currency: Currency identifier.
        amount: The amount to credit (must be positive Decimal or convertible).
        transaction_type: The type of credit transaction.
        **kwargs: Additional arguments for record_transaction (related_order, notes, etc.).

    Returns:
        The created LedgerTransaction instance.

    Raises:
        InvalidLedgerOperationError: If amount is not positive or invalid format.
        Other exceptions from record_transaction.
    """
    try:
        amount_decimal = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
        if amount_decimal <= Decimal('0.0'):
            raise InvalidLedgerOperationError("Credit amount must be positive.")
    except InvalidOperation:
        raise InvalidLedgerOperationError("Invalid credit amount format.")
    except InvalidLedgerOperationError: # Re-raise the specific error
        raise

    return record_transaction(
        user=user,
        transaction_type=transaction_type,
        currency=currency,
        amount=amount_decimal, # Pass validated positive amount
        **kwargs
    )

def debit_funds(user: User, currency: str, amount: Decimal, transaction_type: str, **kwargs) -> LedgerTransaction:
    """
    Helper to record a debit transaction (decreases balance).
    Ensures the debited amount (input) is positive before calling record_transaction.

    Args:
        user: The User instance.
        currency: Currency identifier.
        amount: The amount to debit (must be positive Decimal or convertible).
        transaction_type: The type of debit transaction.
        **kwargs: Additional arguments for record_transaction (related_order, notes, etc.).

    Returns:
        The created LedgerTransaction instance.

    Raises:
        InvalidLedgerOperationError: If amount is not positive or invalid format.
        InsufficientFundsError: If debit amount exceeds available balance (raised by record_transaction).
        Other exceptions from record_transaction.
    """
    try:
        amount_decimal = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
        if amount_decimal <= Decimal('0.0'):
            raise InvalidLedgerOperationError("Debit amount must be positive.")
    except InvalidOperation:
        raise InvalidLedgerOperationError("Invalid debit amount format.")
    except InvalidLedgerOperationError: # Re-raise the specific error
        raise

    # Pass negative amount for debit
    return record_transaction(
        user=user,
        transaction_type=transaction_type,
        currency=currency,
        amount=-amount_decimal,
        **kwargs
    )


# --- Balance Querying ---

def get_user_balance(user: User, currency: str) -> Tuple[Decimal, Decimal]:
    """
    Retrieves the total and available balance for a specific user and currency.

    Args:
        user: The User instance.
        currency: The currency identifier.

    Returns:
        A tuple containing (total_balance: Decimal, available_balance: Decimal).
        Returns (Decimal('0.0'), Decimal('0.0')) if no balance record exists.

    Raises:
        InvalidLedgerOperationError: If the currency code is invalid.
        LedgerConfigurationError: If critical model properties (e.g., available_balance) are missing.
        LedgerServiceError: For unexpected errors during balance retrieval or calculation.
    """
    if currency not in VALID_CURRENCIES:
        raise InvalidLedgerOperationError(f"Invalid currency: {currency}")

    try:
        balance_obj = UserBalance.objects.get(user=user, currency=currency)

        # Safely access the available_balance property
        try:
            available = balance_obj.available_balance
            return balance_obj.balance, available
        except AttributeError:
            logger.critical(f"CRITICAL MODEL ERROR: UserBalance missing 'available_balance' property. User {user.pk}, Currency {currency}.")
            raise LedgerConfigurationError(f"Internal configuration error: Cannot determine available balance for {currency}. Model setup required.")
        except Exception as e_prop:
            logger.exception(f"Error accessing available_balance property User {user.pk}, Currency {currency}: {e_prop}")
            raise LedgerServiceError("Failed to calculate available balance.") from e_prop

    except UserBalance.DoesNotExist:
        logger.debug(f"No balance record for User {user.pk}, Currency {currency}. Returning zero.")
        return Decimal('0.0'), Decimal('0.0')
    except Exception as e:
        logger.exception(f"Error retrieving balance User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError(f"Could not retrieve balance for user {user.pk}.") from e


def get_available_balance(user: User, currency: str) -> Decimal:
    """
    Retrieves only the available balance for a specific user and currency.

    Args:
        user: The User instance.
        currency: The currency identifier.

    Returns:
        The available balance (Decimal). Returns Decimal('0.0') if no record exists.

    Raises:
        InvalidLedgerOperationError: If the currency code is invalid.
        LedgerConfigurationError: If critical model properties (e.g., available_balance) are missing.
        LedgerServiceError: If underlying balance retrieval/calculation fails.
    """
    try:
        # Delegates validation and error handling to get_user_balance
        _, available_balance = get_user_balance(user, currency)
        return available_balance
    except (InvalidLedgerOperationError, LedgerConfigurationError, LedgerServiceError):
        raise # Re-raise known specific errors
    except Exception as e:
        logger.exception(f"Unexpected error in get_available_balance User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError("Unexpected error retrieving available balance.") from e


# --- Fund Locking / Unlocking ---

@transaction.atomic
def lock_funds(user: User, currency: str, amount: Decimal, reason_notes: str = "") -> LedgerTransaction:
    """
    Increases the locked_balance for a user/currency if sufficient available funds exist,
    and records a 'LOCK_FUNDS' transaction. Reduces available balance but keeps total
    balance unchanged. Used for escrow/pending actions.

    Args:
        user: The User instance.
        currency: The currency identifier.
        amount: The amount to lock (must be positive Decimal or convertible).
        reason_notes: Optional description of why funds are being locked (recorded in transaction).

    Returns:
        The created 'LOCK_FUNDS' LedgerTransaction instance on success.

    Raises:
        InvalidLedgerOperationError: If amount format/value or currency is invalid.
        InsufficientFundsError: If available funds are less than the amount to lock.
        LedgerConfigurationError: If critical model properties (e.g., available_balance) are missing.
        LedgerServiceError: If the UserBalance record does not exist, or for other database
                          or unexpected operational errors.
    """
    # 1. Input Validation
    if currency not in VALID_CURRENCIES:
        raise InvalidLedgerOperationError(f"Invalid currency: {currency}")
    if 'LOCK_FUNDS' not in VALID_TRANSACTION_TYPES: # Check type is configured
        raise LedgerConfigurationError("Transaction type 'LOCK_FUNDS' is not defined in TRANSACTION_TYPE_CHOICES.")

    try:
        amount_decimal = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
        if amount_decimal <= Decimal('0.0'):
            raise InvalidLedgerOperationError("Lock amount must be positive.")
    except InvalidOperation:
        raise InvalidLedgerOperationError("Invalid lock amount format.")
    except InvalidLedgerOperationError: # Re-raise specific error
        raise

    balance_obj: UserBalance
    # 2. Get Balance Record (with lock)
    try:
        balance_obj = UserBalance.objects.select_for_update().get(user=user, currency=currency)
    except UserBalance.DoesNotExist:
        logger.error(f"Cannot lock funds, balance record not found: User {user.pk}, Currency {currency}")
        raise LedgerServiceError(f"Balance record not found for user {user.pk}, currency {currency}. Cannot lock funds.")
    except Exception as e:
        logger.exception(f"Error retrieving UserBalance for locking User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError("Failed to access balance record for locking.") from e

    # 3. Check Sufficient Available Funds (after acquiring lock)
    try:
        current_available = balance_obj.available_balance
    except AttributeError:
        logger.critical(f"CRITICAL MODEL ERROR: UserBalance missing 'available_balance'. User {user.pk}, Currency {currency}.")
        raise LedgerConfigurationError(f"Internal config error: Cannot determine available balance for {currency}. Model setup required.")
    except Exception as e_prop:
        logger.exception(f"Error accessing available_balance for locking User {user.pk}, Currency {currency}: {e_prop}")
        raise LedgerServiceError("Failed to calculate available balance for locking.") from e_prop

    if current_available < amount_decimal:
        logger.warning(
            f"Insufficient available funds to lock: User {user.pk}, Currency {currency}. "
            f"Available: {current_available}, Tried to lock: {amount_decimal}"
        )
        # Raise specific error instead of returning False
        raise InsufficientFundsError(
            f"Insufficient available {currency} funds to lock.",
            available=current_available,
            required=amount_decimal,
            currency=currency
        )

    # 4. Increase locked balance and Save
    initial_locked: Decimal
    initial_balance: Decimal
    try:
        initial_locked = balance_obj.locked_balance # For logging/audit
        initial_balance = balance_obj.balance # For ledger transaction (remains unchanged)
        balance_obj.locked_balance += amount_decimal
        balance_obj.save(update_fields=['locked_balance'])

        logger.info(
            f"Locked {amount_decimal} {currency} for User {user.pk}. "
            f"Initial Locked: {initial_locked}, New Locked: {balance_obj.locked_balance}. "
            f"Reason: {reason_notes or 'N/A'}"
        )

    except Exception as e:
        logger.exception(f"Failed to save updated locked_balance User {user.pk}, Currency {currency}: {e}")
        # Let atomic block handle rollback
        raise LedgerServiceError("Failed to save locked balance update.") from e

    # 5. Create Audit Ledger Entry for Lock (AFTER successful lock update)
    ledger_entry: LedgerTransaction
    try:
        ledger_notes = f"Lock funds. Reason: {reason_notes or 'System lock'}"
        ledger_entry = LedgerTransaction.objects.create(
            user=user,
            transaction_type='LOCK_FUNDS', # Use specific type
            currency=currency,
            amount=amount_decimal, # Amount locked
            balance_before=initial_balance, # Total balance unchanged
            balance_after=balance_obj.balance, # Total balance unchanged
            locked_balance_after=balance_obj.locked_balance, # New locked balance state
            related_order=None, # Typically not related directly to order here, maybe meta?
            external_txid=None,
            notes=ledger_notes
        )
        logger.info(
            f"Ledger transaction {ledger_entry.id} recorded for LOCK_FUNDS: User {user.pk}, "
            f"Amount {amount_decimal} {currency}"
        )
    except Exception as e:
        logger.exception(f"Failed to create LOCK_FUNDS LedgerTransaction entry User {user.pk}, Currency {currency} after lock update: {e}")
        # Rollback lock update and locked_balance save due to @transaction.atomic
        raise LedgerServiceError("Failed to record lock funds ledger transaction after balance update.") from e

    return ledger_entry # Return the audit transaction


@transaction.atomic
def unlock_funds(user: User, currency: str, amount: Decimal, reason_notes: str = "") -> Optional[LedgerTransaction]:
    """
    Decreases the locked_balance for a user/currency and records an 'UNLOCK_FUNDS' transaction.
    Increases available balance. Safely handles attempts to unlock more than locked.

    Args:
        user: The User instance.
        currency: The currency identifier.
        amount: The amount to unlock (must be positive Decimal or convertible).
        reason_notes: Optional description of why funds are being unlocked (recorded in transaction).

    Returns:
        The created 'UNLOCK_FUNDS' LedgerTransaction instance if funds were unlocked.
        None if the amount to unlock was zero or negative, or if the balance record was not found.

    Raises:
        InvalidLedgerOperationError: If amount format/value or currency is invalid.
        LedgerConfigurationError: If 'UNLOCK_FUNDS' type is not configured.
        LedgerServiceError: For database or unexpected operational errors.
    """
    # 1. Input Validation
    if currency not in VALID_CURRENCIES:
        raise InvalidLedgerOperationError(f"Invalid currency: {currency}")
    if 'UNLOCK_FUNDS' not in VALID_TRANSACTION_TYPES: # Check type is configured
         raise LedgerConfigurationError("Transaction type 'UNLOCK_FUNDS' is not defined in TRANSACTION_TYPE_CHOICES.")

    try:
        amount_decimal = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
        if amount_decimal <= Decimal('0.0'):
            raise InvalidLedgerOperationError("Unlock amount must be positive.")
    except InvalidOperation:
         raise InvalidLedgerOperationError("Invalid unlock amount format.")
    except InvalidLedgerOperationError: # Re-raise specific error
        raise

    balance_obj: UserBalance
    # 2. Get Balance Record (with lock)
    try:
        balance_obj = UserBalance.objects.select_for_update().get(user=user, currency=currency)
    except UserBalance.DoesNotExist:
        logger.warning(f"Cannot unlock funds, balance record not found: User {user.pk}, Currency {currency}")
        # Nothing to unlock if balance doesn't exist
        return None
    except Exception as e:
        logger.exception(f"Error retrieving UserBalance for unlocking User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError("Failed to access balance record for unlocking.") from e

    # 3. Determine Actual Amount to Unlock
    current_locked: Decimal
    initial_balance: Decimal
    try:
        current_locked = balance_obj.locked_balance
        initial_balance = balance_obj.balance # For ledger transaction (remains unchanged)
    except Exception as e_prop:
        logger.exception(f"Error accessing balance properties for unlocking User {user.pk}, Currency {currency}: {e_prop}")
        raise LedgerServiceError("Failed to determine current balance state for unlock.") from e_prop

    # Calculate the amount that can actually be unlocked
    amount_to_unlock = min(amount_decimal, current_locked)

    if amount_to_unlock <= Decimal('0.0'):
        logger.info(f"Unlock requested User {user.pk}, Currency {currency}, but nothing to unlock (Locked={current_locked}, Requested={amount_decimal}).")
        return None # Indicate no unlock occurred

    # Log if requested amount was higher than what was locked
    if amount_decimal > current_locked:
        logger.warning(
            f"Unlock attempt User {user.pk}: Requested {amount_decimal} {currency}, "
            f"but only {current_locked} locked. Unlocking available amount ({amount_to_unlock})."
        )

    # 4. Decrease locked balance and Save
    try:
        balance_obj.locked_balance -= amount_to_unlock
        balance_obj.save(update_fields=['locked_balance'])

        logger.info(
            f"Unlocked {amount_to_unlock} {currency} for User {user.pk}. "
            f"Initial Locked: {current_locked}, New Locked: {balance_obj.locked_balance}. "
            f"Reason: {reason_notes or 'N/A'}"
        )

    except Exception as e:
        logger.exception(f"Failed to save updated locked_balance after unlock User {user.pk}, Currency {currency}: {e}")
        raise LedgerServiceError("Failed to save locked balance update after unlock.") from e # Rollback handled by atomic block

    # 5. Create Audit Ledger Entry for Unlock (AFTER successful unlock update)
    ledger_entry: LedgerTransaction
    try:
        ledger_notes = f"Unlock funds. Reason: {reason_notes or 'System unlock'}"
        ledger_entry = LedgerTransaction.objects.create(
            user=user,
            transaction_type='UNLOCK_FUNDS', # Use specific type
            currency=currency,
            amount=amount_to_unlock, # Amount actually unlocked
            balance_before=initial_balance, # Total balance unchanged
            balance_after=balance_obj.balance, # Total balance unchanged
            locked_balance_after=balance_obj.locked_balance, # New locked balance state
            related_order=None,
            external_txid=None,
            notes=ledger_notes
        )
        logger.info(
            f"Ledger transaction {ledger_entry.id} recorded for UNLOCK_FUNDS: User {user.pk}, "
            f"Amount {amount_to_unlock} {currency}"
        )
    except Exception as e:
        logger.exception(f"Failed to create UNLOCK_FUNDS LedgerTransaction entry User {user.pk}, Currency {currency} after unlock update: {e}")
        # Rollback unlock update and locked_balance save due to @transaction.atomic
        raise LedgerServiceError("Failed to record unlock funds ledger transaction after balance update.") from e

    # Return the amount that was actually unlocked
    return ledger_entry # Return the audit transaction