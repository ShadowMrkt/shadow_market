# backend/store/views/wallet.py
# Revision: 1.1 (Fix inconsistent import path) # <<< UPDATED REVISION
# Date: 2025-04-29 # <<< UPDATED DATE & NOTE
# Author: Gemini
# Description: Contains API views related to user wallet operations,
#              including withdrawals and balance checks.
# Changes:
# - Rev 1.1:
#   - FIXED: Changed `from store.exceptions...` to `from backend.store.exceptions...`
#     to maintain consistent absolute import paths.
# - Rev 1.0 (Initial Creation):
#   - Initial split of wallet-related views.

# Standard Library Imports
import logging
from decimal import Decimal
from typing import TYPE_CHECKING, List, Dict, Any

# Django Imports
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404 # Potentially useful

# Third-Party Imports
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError as DRFValidationError, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

# Local Application Imports
from backend.store.models import Currency, User # Import User if needed for type hints or checks
from backend.store.permissions import IsPgpAuthenticated # Use PGP check for withdrawals
from backend.store.serializers import (
    WithdrawalPrepareSerializer,
    WithdrawalRequestSerializer,
    WalletBalanceSerializer,
)
from backend.store.utils.utils import log_audit_event

# Import services and exceptions from other apps
try:
    from backend.withdraw.services import request_withdrawal # Use absolute path
    from backend.withdraw.exceptions import WithdrawalError # Use absolute path
    # Import specific crypto errors if handled separately, e.g.:
    # <<<--- FIXED THIS IMPORT --->>>
    from backend.store.exceptions import CryptoProcessingError # Use absolute path
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"Failed to import withdrawal services/exceptions: {e}. Wallet views may fail.")
    # Define dummy functions/exceptions if needed to prevent startup crashes
    def request_withdrawal(*args, **kwargs): raise NotImplementedError("Withdrawal service unavailable")
    WithdrawalError = Exception
    CryptoProcessingError = Exception # Define dummy

try:
    from backend.ledger.services import get_available_balance, InsufficientFundsError, InvalidLedgerOperationError # Use absolute path
    from backend.ledger.exceptions import LedgerError # Use absolute path
    from backend.ledger.models import UserBalance # Use absolute path
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"Failed to import ledger services/exceptions/models: {e}. Wallet views may fail.")
    # Define dummy functions/exceptions/models
    def get_available_balance(*args, **kwargs): return Decimal('0.0')
    InsufficientFundsError = Exception
    LedgerError = Exception
    InvalidLedgerOperationError = Exception
    UserBalance = None

# --- Type Hinting ---
if TYPE_CHECKING:
    # Assume WithdrawalRequest lives in withdraw app
    from backend.withdraw.models import WithdrawalRequest as WithdrawalRequestModel


# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')


# --- Wallet Views ---

class WithdrawalPrepareView(APIView):
    """
    Initiates a withdrawal request.

    Validates input, checks balance, debits ledger, credits fees,
    and attempts immediate crypto broadcast via the withdrawal service.
    Requires recent PGP authentication.
    """
    permission_classes = [IsAuthenticated, IsPgpAuthenticated]
    serializer_class = WithdrawalPrepareSerializer

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user: User = request.user
        log_prefix = f"[WithdrawalPrepare U:{user.id}/{user.username}]"
        logger.info(f"{log_prefix}: Received withdrawal request.")

        serializer = self.serializer_class(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data
            currency = validated_data['currency']
            amount_standard = validated_data['amount'] # Amount is already Decimal from serializer
            withdrawal_address = validated_data['address']

            logger.info(f"{log_prefix}: Input valid. Calling withdrawal service for {amount_standard} {currency} to {withdrawal_address[:15]}...")

            # Call the withdrawal service which handles everything
            withdrawal_request: 'WithdrawalRequestModel' = request_withdrawal(
                user=user,
                currency=currency,
                amount_standard=amount_standard,
                withdrawal_address=withdrawal_address,
            )

            # Service handles logging success internally, just serialize result here
            response_serializer = WithdrawalRequestSerializer(withdrawal_request, context={'request': request})
            log_audit_event(request, user, 'withdrawal_request_success', details=f"ReqID: {withdrawal_request.id}, Amount: {amount_standard} {currency}")
            return Response(response_serializer.data, status=status.HTTP_201_CREATED) # 201 indicates successful creation

        except (InsufficientFundsError, InvalidLedgerOperationError, WithdrawalError, CryptoProcessingError) as service_err:
            # Specific, handled errors from services
            logger.warning(f"{log_prefix}: Withdrawal failed due to service error: {service_err}")
            log_audit_event(request, user, 'withdrawal_request_failed', details=f"Reason: {service_err}")
            # Return a user-friendly error message
            error_message = str(service_err)
            # Customize messages for common errors
            if isinstance(service_err, InsufficientFundsError):
                error_code = 'insufficient_funds'
                http_status = status.HTTP_400_BAD_REQUEST # Or 422 Unprocessable Entity
            elif isinstance(service_err, InvalidLedgerOperationError):
                error_code = 'ledger_error'
                http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
            elif isinstance(service_err, CryptoProcessingError):
                error_code = 'broadcast_error'
                http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
                error_message = "Withdrawal processing failed due to an issue with the cryptocurrency network or service. Please try again later or contact support."
            else: # Generic WithdrawalError
                error_code = 'withdrawal_error'
                http_status = status.HTTP_400_BAD_REQUEST

            raise DRFValidationError({'detail': error_message}, code=error_code) # Let DRF handle status mapping via exception code

        except DRFValidationError as e:
            # Raised by serializer.is_valid() or address/amount validation within service
            logger.warning(f"{log_prefix}: Validation error: {e.detail}")
            log_audit_event(request, user, 'withdrawal_request_invalid', details=f"Reason: {e.detail}")
            raise e # Re-raise validation error for DRF standard handling (400 Bad Request)

        except DjangoValidationError as e: # Catch model validation errors if service raises them
            logger.warning(f"{log_prefix}: Django Validation error: {e.message_dict}")
            log_audit_event(request, user, 'withdrawal_request_invalid', details=f"Reason: Django Validation Error")
            raise DRFValidationError(e.message_dict) # Convert to DRF validation error

        except PermissionDenied as e: # Should be caught by DRF permissions, but belt-and-suspenders
            logger.warning(f"{log_prefix}: Permission denied: {e}")
            log_audit_event(request, None, 'withdrawal_request_permission_denied', target_user=user)
            raise e

        except NotImplementedError as e:
            logger.critical(f"{log_prefix}: Service unavailable/not implemented: {e}")
            raise APIException("Withdrawal service is temporarily unavailable.", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        except Exception as e:
            # Catch-all for unexpected errors during the process
            logger.exception(f"{log_prefix}: Unexpected error during withdrawal preparation: {e}")
            log_audit_event(request, user, 'withdrawal_request_error', details=f"Unexpected error: {type(e).__name__}")
            # Return a generic 500 error
            raise APIException("An unexpected error occurred. Please try again later.", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WalletBalanceView(APIView):
    """
    Retrieves the available, locked, and total balances for the
    currently authenticated user for all supported currencies.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user: User = request.user
        log_prefix = f"[WalletBalance U:{user.id}/{user.username}]"
        logger.debug(f"{log_prefix}: Fetching balances.")

        balances_data: List[Dict[str, Any]] = []
        supported_currencies = Currency.values # Get list like ['BTC', 'XMR', 'ETH']

        # Check if UserBalance model is available
        if UserBalance is None:
            logger.error(f"{log_prefix}: UserBalance model not available. Cannot fetch balances.")
            raise APIException("Wallet service is temporarily unavailable.", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        for currency_code in supported_currencies:
            try:
                # Fetch the UserBalance object to get total and locked balances
                # Use get_object_or_404 or filter().first() with default creation?
                # Let's assume balances are created when needed or default to zero.
                user_balance_obj = UserBalance.objects.filter(user=user, currency=currency_code).first()

                if user_balance_obj:
                    balance = user_balance_obj.balance
                    locked_balance = user_balance_obj.locked_balance
                    # Use the property for available balance for consistency
                    available_balance = user_balance_obj.available_balance
                else:
                    # If no balance record exists, assume zero for all
                    balance = Decimal('0.0')
                    locked_balance = Decimal('0.0')
                    available_balance = Decimal('0.0')

                balances_data.append({
                    'currency': currency_code,
                    'balance': balance,
                    'locked_balance': locked_balance,
                    'available_balance': available_balance,
                })

            except LedgerError as e: # Catch specific ledger errors during fetch (though filter().first() is less likely to raise)
                logger.error(f"{log_prefix}: Ledger error fetching balance for {currency_code}: {e}", exc_info=True)
                # Skip this currency or return partial results? Let's skip.
                continue
            except Exception as e:
                logger.exception(f"{log_prefix}: Unexpected error fetching balance for {currency_code}: {e}")
                # Skip this currency on unexpected error
                continue

        # Serialize the collected data
        # Note: WalletBalanceSerializer expects 'available_balance' in the input data now
        serializer = WalletBalanceSerializer(balances_data, many=True)

        logger.debug(f"{log_prefix}: Balances fetched successfully.")
        return Response(serializer.data, status=status.HTTP_200_OK)

# NOTE: WithdrawalExecuteView is intentionally omitted as the `request_withdrawal`
# service handles the full process atomically, making a separate execute step redundant
# with the current service implementation. If the flow changes (e.g., to require
# a separate confirmation step), this view might need to be added/repurposed.

# --- END OF FILE ---