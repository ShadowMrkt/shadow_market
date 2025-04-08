# backend/withdraw/exceptions.py
# Revision 1: Initial production-grade creation.

from django.utils.translation import gettext_lazy as _

class WithdrawalError(Exception):
    """
    Base exception class for all errors specific to the withdrawal application.

    Catching this exception will catch any error originating predictably
    from the withdrawal logic. More specific exceptions inheriting from this
    should be used for finer-grained error handling.
    """
    def __init__(self, message=_("An unspecified withdrawal error occurred."), *args):
        super().__init__(message, *args)


class InvalidWithdrawalRequestError(WithdrawalError):
    """
    Raised when the data provided for a withdrawal request is invalid
    after initial validation (e.g., logic errors, inconsistent data).
    """
    def __init__(self, message=_("The withdrawal request data is invalid."), *args):
        super().__init__(message, *args)


class InsufficientBalanceError(WithdrawalError):
    """
    Raised specifically by the withdrawal service when an account's available
    balance is insufficient to cover the requested withdrawal amount and fees.
    Note: May wrap or be related to ledger service's InsufficientFundsError.
    """
    def __init__(self, message=_("Insufficient available balance for withdrawal."), *args):
        super().__init__(message, *args)


class WithdrawalProcessingError(WithdrawalError):
    """
    Raised when an error occurs during the processing phase of a withdrawal,
    such as issues interacting with external crypto services or internal state updates.
    Often wraps a more specific underlying error (e.g., CryptoProcessingError).
    """
    def __init__(self, message=_("An error occurred while processing the withdrawal."), *args):
        super().__init__(message, *args)


class InvalidWithdrawalStateError(WithdrawalError):
    """
    Raised when attempting an operation on a withdrawal request that is
    not appropriate for its current status (e.g., trying to cancel a
    completed withdrawal).
    """
    def __init__(self, message=_("The operation is not valid for the withdrawal's current state."), *args):
        super().__init__(message, *args)


class WithdrawalConfigurationError(WithdrawalError):
    """
    Raised when there's a misconfiguration related to the withdrawal
    system itself (e.g., missing fee settings, invalid crypto service setup).
    """
    def __init__(self, message=_("Withdrawal system configuration error."), *args):
        super().__init__(message, *args)


# Add other specific exceptions as your withdrawal logic requires.
# For example:
# class MinimumWithdrawalError(InvalidWithdrawalRequestError):
#     """Raised when the requested amount is below the configured minimum."""
#     def __init__(self, message=_("Withdrawal amount is below the minimum allowed."), *args):
#         super().__init__(message, *args)

# class MaximumWithdrawalError(InvalidWithdrawalRequestError):
#     """Raised when the requested amount exceeds the configured maximum."""
#     def __init__(self, message=_("Withdrawal amount exceeds the maximum allowed."), *args):
#         super().__init__(message, *args)