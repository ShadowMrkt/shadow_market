# backend/withdraw/services.py
# --- Revision History ---
# v1.1.1 (2025-05-03): (Gemini Rev 13) Enforced absolute imports using 'backend.' prefix
#                      for store.services, store.exceptions, and store.services.common_escrow_utils.
#                      Aims to resolve Django model registry conflicts.
# vNEXT (2025-04-09): Fixed ImportError by updating import path for _get_currency_precision to common_escrow_utils.
# v1.1.0 (2025-04-06): Integrate Broadcast & Fee Update.
# v1.0.0 (2025-04-06): Initial creation.
# ------------------------

import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Optional, Tuple, Dict, Any, Final, TYPE_CHECKING

from django.db import transaction, IntegrityError
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError, ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _ # Added for consistency

# --- Constants ---
DEFAULT_WITHDRAWAL_FEE_PERCENTAGE: Final[Decimal] = Decimal('10.0') # Updated Fee
# Ledger Transaction Types (Ensure these are defined consistently in your ledger app)
LEDGER_TX_WITHDRAWAL_DEBIT: Final = 'WITHDRAWAL_DEBIT' # Debit from user initiating withdrawal
LEDGER_TX_WITHDRAWAL_FEE: Final = 'WITHDRAWAL_FEE' # Credit to site owner

# Use TYPE_CHECKING to avoid circular imports / runtime issues for type hints
if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser
    from backend.withdraw.models import WithdrawalRequest as WithdrawalRequestModel # Use absolute path
    # Import crypto service protocols/interfaces if defined
    # from backend.store.services.escrow_service import CryptoServiceInterface # Example if reusing
    # from backend.ledger.services import LedgerServiceInterface # Example if defined

# --- Model Imports ---
User = get_user_model() # Define User using Django's helper

try:
    # Runtime imports needed for logic
    # Use absolute paths for internal apps
    from backend.withdraw.models import WithdrawalRequest, WithdrawalStatusChoices # Assumed model and status choices enum/class
    from backend.ledger import services as ledger_service
    from backend.ledger.services import InsufficientFundsError, InvalidLedgerOperationError # Assuming this is the correct exception name from ledger
    from backend.notifications.services import create_notification
    # Import necessary crypto services (or a generic interface/dispatcher)
    # These need to be actual import paths in your project
    from backend.store.services import bitcoin_service, monero_service # Example, add others like ethereum_service
    from backend.store.exceptions import CryptoProcessingError # Assuming crypto errors are defined here
    # Import custom exceptions if defined
    from backend.withdraw.exceptions import WithdrawalError # Corrected import now that exceptions.py exists
    from backend.ledger.exceptions import LedgerError # Assuming ledger has its own base error
    from backend.notifications.exceptions import NotificationError # Assuming notifications has its own base error

    # Helper to get precision (can be shared or redefined)
    # FIX: Import from common utils instead of non-existent escrow_service module
    from backend.store.services.common_escrow_utils import _get_currency_precision

    # Helper function to get the correct crypto service module based on currency
    # This might live elsewhere (e.g., shared utils, crypto registry)
    # Example implementation:
    _crypto_service_registry = {
        'BTC': bitcoin_service,
        'XMR': monero_service,
        # 'ETH': ethereum_service, # Add other services here
    }
    def _get_crypto_service(currency: str) -> Any: # Return type Any as it's a module/service object
        """ Retrieves the appropriate crypto service module/object for the currency. """
        service = _crypto_service_registry.get(currency.upper())
        if not service:
            logging.error(f"No crypto service module registered or available for currency: {currency}") # Use logging consistently
            raise ValueError(f"Unsupported or unregistered currency for crypto operations: {currency}")
        # Add checks here if it's an object requiring specific methods (e.g., isinstance or hasattr)
        # Ensure crypto services implement a consistent withdrawal method interface
        if not hasattr(service, 'initiate_market_withdrawal'): # Assume this method exists in crypto services
             raise NotImplementedError(f"Crypto service for {currency} does not implement 'initiate_market_withdrawal' method.")
        return service

except ImportError as e:
    # Use logger defined below if possible, fallback to basicConfig if logger fails setup
    try:
        logger_init_fallback = logging.getLogger(__name__)
        logger_init_fallback.critical(f"CRITICAL IMPORT ERROR in withdraw_services.py: {e}. Check dependencies/paths/models/crypto services.")
    except Exception: # Fallback if logging itself fails
        logging.basicConfig(level=logging.CRITICAL)
        logging.critical(f"CRITICAL IMPORT ERROR in withdraw_services.py: {e}. Check dependencies/paths/models/crypto services.")
    # NOTE: The original code re-raised ImportError here. If the test traceback was caused by this
    # specifically, ensure the test environment handles it or adjust the test setup.
    # For now, keeping the original raise behavior.
    raise ImportError(f"Failed to import critical modules in withdraw_services.py: {e}") from e
except Exception as e:
    try:
        logger_init_fallback = logging.getLogger(__name__)
        logger_init_fallback.critical(f"Unexpected error during withdraw_services imports: {e}", exc_info=True)
    except Exception:
        logging.basicConfig(level=logging.CRITICAL)
        logging.critical(f"Unexpected error during withdraw_services imports: {e}", exc_info=True)
    raise

# --- Loggers ---
# Define loggers after potential import errors are handled
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security')

# --- Internal Helper Functions ---

_site_owner_user_cache: Optional['AbstractUser'] = None
def _get_site_owner_user() -> 'AbstractUser':
    """
    Gets the designated Site Owner User instance from settings. Caches the result.
    Raises ObjectDoesNotExist or RuntimeError if not configured or found.
    """
    global _site_owner_user_cache
    if _site_owner_user_cache:
        return _site_owner_user_cache

    owner_username = getattr(settings, 'SITE_OWNER_USERNAME', None)
    if not owner_username:
        logger.critical("CRITICAL: settings.SITE_OWNER_USERNAME is not defined.")
        raise RuntimeError("Site owner username not configured in settings.")
    try:
        user: 'AbstractUser' = User.objects.get(username=owner_username)
        _site_owner_user_cache = user
        logger.info(f"Site owner user '{owner_username}' loaded and cached.")
        return user
    except User.DoesNotExist:
        logger.critical(f"CRITICAL: Site owner user '{owner_username}' not found in database.")
        raise ObjectDoesNotExist(f"Site owner user '{owner_username}' not found.")
    except Exception as e:
        logger.exception(f"Unexpected error fetching site owner user '{owner_username}': {e}")
        raise RuntimeError(f"Database error fetching site owner user '{owner_username}'.") from e


def _get_withdrawal_fee_percentage() -> Decimal:
    """
    Gets the withdrawal fee percentage from settings.
    Uses DEFAULT_WITHDRAWAL_FEE_PERCENTAGE (10%) as fallback.
    """
    fee_setting = getattr(settings, 'WITHDRAWAL_FEE_PERCENTAGE', DEFAULT_WITHDRAWAL_FEE_PERCENTAGE)
    try:
        fee = Decimal(str(fee_setting))
        if not (Decimal('0.0') <= fee <= Decimal('100.0')):
            logger.warning(f"settings.WITHDRAWAL_FEE_PERCENTAGE ('{fee_setting}') is out of range (0-100). Using default {DEFAULT_WITHDRAWAL_FEE_PERCENTAGE}%.")
            return DEFAULT_WITHDRAWAL_FEE_PERCENTAGE
        # Log if the setting differs from the hardcoded default (useful for diagnostics)
        if fee != DEFAULT_WITHDRAWAL_FEE_PERCENTAGE:
            logger.info(f"Using withdrawal fee percentage from settings: {fee}%")
        return fee
    except (InvalidOperation, TypeError, ValueError):
        logger.error(f"Invalid format for settings.WITHDRAWAL_FEE_PERCENTAGE ('{fee_setting}'). Using default {DEFAULT_WITHDRAWAL_FEE_PERCENTAGE}%.")
        return DEFAULT_WITHDRAWAL_FEE_PERCENTAGE

# --- Main Service Function ---

@transaction.atomic
def request_withdrawal(
    user: 'AbstractUser',
    currency: str,
    amount_standard: Decimal,
    withdrawal_address: str,
    # Optional: Add 2FA code, password hash, etc. for security checks if needed
) -> 'WithdrawalRequestModel':
    """
    Handles a user's request to withdraw funds, including immediate broadcast.

    Steps:
    1. Validate inputs (user, currency, amount, address).
    2. Calculate fees and net amount based on currency precision.
    3. Check initial user balance.
    4. Create a WithdrawalRequest record in PENDING state.
    5. Verify balance again after obtaining lock.
    6. Debit the full requested amount from the user's ledger.
    7. Credit the fee amount to the site owner's ledger.
    8. Attempt to broadcast the net withdrawal amount using the appropriate crypto service.
    9. If broadcast succeeds, update WithdrawalRequest to COMPLETED with TX hash.
    10. If broadcast fails, mark WithdrawalRequest as FAILED with reason and ROLLBACK transaction.
    11. If any ledger/check fails, ROLLBACK transaction and mark request FAILED.
    12. Schedule notification on successful transaction commit.

    Raises:
        ValueError: Invalid input data (amount, address, currency).
        PermissionError: Invalid user making the request.
        InsufficientFundsError: User does not have enough available balance.
        LedgerError: Problem interacting with the ledger service.
        CryptoProcessingError: Problem broadcasting the crypto transaction (e.g., RPC error, insufficient node funds).
        WithdrawalError: General failure during withdrawal processing or record creation.
        ObjectDoesNotExist: Site owner user not found.
        RuntimeError: Site owner user not configured in settings.
        NotImplementedError: Crypto service lacks required withdrawal method.
        (potentially others from underlying crypto libs)
    """
    log_prefix = f"WithdrawalRequest (User: {getattr(user, 'username', 'N/A')}, Currency: {currency}, Amount: {amount_standard})"
    logger.info(f"{log_prefix}: Processing request with integrated broadcast...")

    # --- Input Validation ---
    if not isinstance(user, User) or not user.pk:
        logger.error(f"{log_prefix}: Invalid user object provided.")
        raise PermissionError("Invalid user making withdrawal request.")

    # Validate currency (add check against settings.SUPPORTED_CURRENCIES if exists)
    if not currency or not isinstance(currency, str):
        logger.error(f"{log_prefix}: Invalid currency provided: {currency}")
        raise ValueError(f"Invalid or unsupported currency: {currency}")
    currency = currency.upper() # Standardize

    if not isinstance(amount_standard, Decimal) or amount_standard <= Decimal('0.0'):
        logger.error(f"{log_prefix}: Invalid amount provided: {amount_standard}")
        raise ValueError("Withdrawal amount must be a positive Decimal value.")

    # Basic address validation
    if not withdrawal_address or not isinstance(withdrawal_address, str) or len(withdrawal_address.strip()) < 20: # Basic length check
        logger.error(f"{log_prefix}: Invalid withdrawal address provided: '{withdrawal_address}'")
        raise ValueError("Invalid or missing withdrawal address.")
    withdrawal_address = withdrawal_address.strip()

    # --- Precision and Fee Calculation (Using 10% Fee) ---
    try:
        # Use the imported _get_currency_precision function
        precision = _get_currency_precision(currency)
        quantizer = Decimal(f'1e-{precision}')
        amount_standard = amount_standard.quantize(quantizer, rounding=ROUND_DOWN) # Apply precision
        if amount_standard <= Decimal('0.0'):
            raise ValueError("Withdrawal amount is zero or negative after applying currency precision.")

        fee_percent = _get_withdrawal_fee_percentage() # Gets 10% or setting override
        fee_amount_standard = (amount_standard * fee_percent / Decimal(100)).quantize(quantizer, rounding=ROUND_DOWN)
        if fee_amount_standard < Decimal('0.0'): fee_amount_standard = Decimal('0.0') # Ensure non-negative fee

        net_amount_standard = (amount_standard - fee_amount_standard).quantize(quantizer, rounding=ROUND_DOWN)
        if net_amount_standard < Decimal('0.0'): net_amount_standard = Decimal('0.0') # Ensure non-negative net

        # Check if fee consumes entire amount (optional: could raise error)
        if amount_standard > Decimal('0.0') and net_amount_standard <= Decimal('0.0'):
            logger.warning(f"{log_prefix}: Requested amount {amount_standard} {currency} is less than or equal to the calculated fee {fee_amount_standard} ({fee_percent}%). Net withdrawal will be zero or less.")
            # raise ValueError(f"Withdrawal amount {amount_standard} is too small to cover the {fee_percent}% fee.") # Uncomment to reject

        logger.info(f"{log_prefix}: Fee: {fee_amount_standard} {currency} ({fee_percent}%). Net Amount to Send: {net_amount_standard} {currency}.")

    except (InvalidOperation, ValueError) as calc_err:
        logger.error(f"{log_prefix}: Error during amount/fee calculation: {calc_err}", exc_info=True)
        raise ValueError(f"Calculation error: {calc_err}") from calc_err

    # --- Initial Balance Check ---
    try:
        available_balance = ledger_service.get_available_balance(user, currency)
        if available_balance < amount_standard:
            logger.warning(f"{log_prefix}: Insufficient available funds. Available: {available_balance} {currency}, Requested: {amount_standard} {currency}.")
            raise InsufficientFundsError(f"Insufficient available balance. You have {available_balance} {currency}, but need {amount_standard} {currency}.")
        logger.debug(f"{log_prefix}: Initial balance check passed. Available: {available_balance} {currency}")
    except LedgerError as le: # Catch base LedgerError
        logger.error(f"{log_prefix}: Failed to get available balance: {le}", exc_info=True)
        raise LedgerError("Could not verify available balance.") from le

    # --- Create Withdrawal Request Record ---
    withdrawal_request: Optional['WithdrawalRequestModel'] = None # Define variable before try block
    try:
        withdrawal_request = WithdrawalRequest.objects.create(
            user=user,
            currency=currency,
            requested_amount=amount_standard,
            fee_percentage=fee_percent,
            fee_amount=fee_amount_standard,
            net_amount=net_amount_standard,
            withdrawal_address=withdrawal_address,
            status=WithdrawalStatusChoices.PENDING, # Start as pending
        )
        logger.info(f"{log_prefix}: Created WithdrawalRequest {withdrawal_request.id} with status PENDING.")
    except IntegrityError as ie:
         logger.error(f"{log_prefix}: IntegrityError creating WithdrawalRequest. Possible duplicate? {ie}", exc_info=True)
         raise WithdrawalError("Failed to create withdrawal request record, possibly a duplicate.") from ie
    except DjangoValidationError as ve:
         logger.error(f"{log_prefix}: Validation failed creating WithdrawalRequest: {ve.message_dict}", exc_info=False)
         raise DjangoValidationError(ve.message_dict) # Re-raise original validation error
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error creating WithdrawalRequest record: {e}")
        raise WithdrawalError("Failed to create withdrawal request record.") from e

    # --- Perform Ledger Updates and Broadcast ---
    tx_hash: Optional[str] = None # Define tx_hash here for broader scope
    try:
        # Fetch site owner user
        site_owner = _get_site_owner_user()

        # Lock user's ledger & Verify balance again (essential race check)
        logger.debug(f"{log_prefix}: Verifying balance after lock for request {withdrawal_request.id}...")
        available_balance_locked = ledger_service.get_available_balance(user=user, currency=currency)
        if available_balance_locked < amount_standard:
            logger.warning(f"{log_prefix}: Insufficient available funds detected after lock ({available_balance_locked}). Request {withdrawal_request.id} will fail.")
            raise InsufficientFundsError(f"Insufficient available balance after lock. Available: {available_balance_locked}, Required: {amount_standard}.")

        # 1. Debit FULL requested amount from the user
        logger.debug(f"{log_prefix}: Debiting {amount_standard} {currency} from user {user.username}...")
        ledger_service.debit_funds(
            user=user, currency=currency, amount=amount_standard,
            transaction_type=LEDGER_TX_WITHDRAWAL_DEBIT, related_withdrawal=withdrawal_request,
            notes=f"Withdrawal Request {withdrawal_request.id} to {withdrawal_address[:15]}..."
        )
        logger.info(f"{log_prefix}: Debit successful.")

        # 2. Credit the FEE amount to the site owner
        if fee_amount_standard > Decimal('0.0'):
            logger.debug(f"{log_prefix}: Crediting fee {fee_amount_standard} {currency} to owner {site_owner.username}...")
            ledger_service.credit_funds(
                user=site_owner, currency=currency, amount=fee_amount_standard,
                transaction_type=LEDGER_TX_WITHDRAWAL_FEE, related_withdrawal=withdrawal_request,
                notes=f"Withdrawal Fee from Request {withdrawal_request.id} (User: {user.username})"
            )
            logger.info(f"{log_prefix}: Fee credit successful.")
        else:
            logger.info(f"{log_prefix}: Skipping fee credit (zero amount).")

        # 3. Attempt Crypto Broadcast (Net Amount)
        logger.info(f"{log_prefix}: Ledger updates successful. Attempting crypto broadcast for request {withdrawal_request.id}...")
        try:
            crypto_service = _get_crypto_service(currency)
            # Use the method implemented by the specific crypto services (e.g., initiate_market_withdrawal)
            tx_hash = crypto_service.initiate_market_withdrawal(
                currency=currency,
                amount_standard=net_amount_standard, # Send the NET amount
                target_address=withdrawal_address,
                # withdrawal_request_id=withdrawal_request.id # Optional argument if needed by crypto service
            )

            if not tx_hash or not isinstance(tx_hash, str) or len(tx_hash) < 10: # Basic check for non-empty hash
                raise CryptoProcessingError(f"Broadcast function returned invalid tx_hash: '{tx_hash}'")

            logger.info(f"{log_prefix}: Crypto broadcast successful. TXID: {tx_hash}")

        except (CryptoProcessingError, NotImplementedError, AttributeError, ValueError) as crypto_err:
            # Handle specific crypto errors
            logger.error(f"{log_prefix}: Crypto broadcast FAILED for request {withdrawal_request.id}: {crypto_err}", exc_info=True)
            withdrawal_request.status = WithdrawalStatusChoices.FAILED
            withdrawal_request.failure_reason = f"Crypto broadcast error: {crypto_err}"
            withdrawal_request.processed_at = timezone.now()
            try:
                # Attempt to save failure state before rollback (might not persist)
                withdrawal_request.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])
                logger.info(f"{log_prefix}: Marked request {withdrawal_request.id} as FAILED due to broadcast error (pre-rollback attempt).")
            except Exception as save_fail: logger.error(f"{log_prefix}: Failed to save FAILED status for request {withdrawal_request.id} before rollback: {save_fail}")
            raise crypto_err # Re-raise original crypto error to trigger rollback
        except Exception as broadcast_e:
            # Catch unexpected errors during broadcast
            logger.exception(f"{log_prefix}: Unexpected error during crypto broadcast for request {withdrawal_request.id}: {broadcast_e}")
            withdrawal_request.status = WithdrawalStatusChoices.FAILED
            withdrawal_request.failure_reason = f"Unexpected broadcast error: {broadcast_e}"
            withdrawal_request.processed_at = timezone.now()
            try:
                withdrawal_request.save(update_fields=['status', 'failure_reason', 'processed_at', 'updated_at'])
                logger.info(f"{log_prefix}: Marked request {withdrawal_request.id} as FAILED due to unexpected broadcast error (pre-rollback attempt).")
            except Exception as save_fail: logger.error(f"{log_prefix}: Failed to save FAILED status for request {withdrawal_request.id} before rollback: {save_fail}")
            raise WithdrawalError(f"Unexpected broadcast error: {broadcast_e}") from broadcast_e

        # 4. Update WithdrawalRequest to COMPLETED (only if broadcast succeeded)
        withdrawal_request.status = WithdrawalStatusChoices.COMPLETED
        withdrawal_request.broadcast_tx_hash = tx_hash
        withdrawal_request.processed_at = timezone.now() # Completion time
        withdrawal_request.save(update_fields=['status', 'broadcast_tx_hash', 'processed_at', 'updated_at'])
        logger.info(f"{log_prefix}: WithdrawalRequest {withdrawal_request.id} status updated to COMPLETED.")

    # Outer exception handling for errors during Ledger/User fetch/Broadcast re-raise
    except (InsufficientFundsError, LedgerError, ObjectDoesNotExist, CryptoProcessingError, WithdrawalError, NotImplementedError, ValueError) as process_err: # Added ValueError here too
        logger.error(f"{log_prefix}: Withdrawal processing failed for Request ID {getattr(withdrawal_request, 'id', 'N/A')}: {process_err}. Transaction rolling back.", exc_info=False)
        # Attempt to mark request as FAILED if it exists and is PENDING (it might have been marked already)
        if withdrawal_request and withdrawal_request.pk:
            try:
                # Refresh from DB not needed here (inside atomic block)
                # Check in-memory status first
                if withdrawal_request.status == WithdrawalStatusChoices.PENDING:
                    withdrawal_request.status = WithdrawalStatusChoices.FAILED
                    withdrawal_request.failure_reason = withdrawal_request.failure_reason or f"Processing error: {process_err}"
                    withdrawal_request.processed_at = timezone.now()
                    logger.warning(f"{log_prefix}: Marking request {withdrawal_request.id} as FAILED (post-process error, likely won't persist due to rollback). Reason: {withdrawal_request.failure_reason}")
                    # Do NOT save here inside the failing transaction block
            except Exception as final_save_err: logger.error(f"{log_prefix}: Error checking/updating request {withdrawal_request.id} status to FAILED after process error: {final_save_err}")
        # Re-raise the original error after logging
        raise process_err
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception(f"{log_prefix}: Unexpected error during withdrawal processing for Request ID {getattr(withdrawal_request, 'id', 'N/A')}: {e}. Transaction rolling back.")
        if withdrawal_request and withdrawal_request.pk and withdrawal_request.status == WithdrawalStatusChoices.PENDING:
            logger.error(f"{log_prefix}: Attempting to mark request {withdrawal_request.id} as FAILED failed due to unexpected error and rollback.")
        raise WithdrawalError(f"Unexpected withdrawal processing error: {e}") from e

    # --- Send Notification (Best Effort after successful transaction commit) ---
    # Define data payload for the notification function
    notification_payload = {
        'user_id': user.id,
        'username': user.username,
        'request_id': withdrawal_request.id,
        'amount_standard': amount_standard,
        'currency': currency,
        'fee_amount_standard': fee_amount_standard,
        'net_amount_standard': net_amount_standard,
        'withdrawal_address': withdrawal_address,
        'tx_hash': tx_hash, # Include the transaction hash
        'log_prefix': log_prefix
    }
    # Ensure the lambda function has access to necessary variables
    # Pass payload directly if lambda execution scope is tricky
    transaction.on_commit(
        lambda data=notification_payload: send_withdrawal_processed_notification(**data)
    )

    logger.info(f"{log_prefix}: Request {withdrawal_request.id} completed successfully (pending commit). TXID: {tx_hash}")
    security_logger.info(f"Withdrawal processed for user {user.username}: {net_amount_standard} {currency} to {withdrawal_address[:15]}... TX: {tx_hash}. RequestID: {withdrawal_request.id}")
    return withdrawal_request


def send_withdrawal_processed_notification(user_id, username, request_id, amount_standard, currency, fee_amount_standard, net_amount_standard, withdrawal_address, tx_hash, log_prefix):
    """ Sends notification *after* successful transaction commit. """
    try:
        message = (
            f"Your withdrawal of {net_amount_standard} {currency} (Fee: {fee_amount_standard}) "
            f"to address {withdrawal_address[:10]}... has been processed.\n"
            f"Transaction ID: {tx_hash}\n"
            f"(Request ID: {request_id})"
        )
        # link = f"/account/withdrawals/{request_id}" # Optional link
        create_notification(user_id=user_id, level='success', message=message) # link=link
        logger.info(f"{log_prefix}: Sent withdrawal processed notification to User {username} (ID: {user_id}).")
    except NotificationError as ne:
         logger.error(f"{log_prefix}: Failed to create withdrawal processed notification for User {username} (ID: {user_id}): {ne}", exc_info=True)
    except Exception as e:
         logger.error(f"{log_prefix}: Unexpected error sending withdrawal processed notification for User {username} (ID: {user_id}): {e}", exc_info=True)

# <<< END OF FILE: backend/withdraw/services.py >>>