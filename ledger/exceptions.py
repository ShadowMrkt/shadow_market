# backend/ledger/exceptions.py
"""
Custom exceptions for the Ledger application.

This module defines specific exceptions related to ledger operations,
allowing for more granular error handling and identification of issues
originating within the ledger system.
"""

class LedgerError(Exception):
    """
    Base exception class for ledger-related errors.

    All custom exceptions raised by the ledger application should inherit
    from this class. This allows callers to catch any ledger-specific
    error using `except LedgerError:`.
    """
    def __init__(self, message="An error occurred in the ledger system."):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message

# Add other specific ledger exceptions below if needed, inheriting from LedgerError.
# For example, if 'InsufficientFundsError' or 'InvalidLedgerOperationError'
# were primarily exception types rather than errors raised within service logic,
# they could potentially be defined here as well, inheriting from LedgerError.
# However, based on the import in escrow_service.py (`from ledger.services import ...`),
# it seems they might be defined within ledger/services.py or are closely tied to service logic.
# Sticking to just LedgerError here directly addresses the ModuleNotFoundError.

# Example of a more specific error (if you needed one):
# class AccountNotFoundError(LedgerError):
#     """Raised when a ledger account cannot be found."""
#     def __init__(self, account_id, message=None):
#         self.account_id = account_id
#         if message is None:
#             message = f"Ledger account not found: {account_id}"
#         super().__init__(message)