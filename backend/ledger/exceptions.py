# backend/ledger/exceptions.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Defines custom exceptions for the Ledger application.
# Changes:
# - Rev 1.1:
#   - Added InsufficientFundsError class.
#   - Added InvalidLedgerOperationError class.
#   - Both inherit from LedgerError.
#   - This resolves the ImportError for InsufficientFundsError.
# - Rev 1.0 (Assumed Initial Version from provided content):
#   - Defined base LedgerError.

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

class InsufficientFundsError(LedgerError):
    """
    Raised when an operation cannot be completed due to insufficient funds
    in a ledger account.
    """
    def __init__(self, account_id=None, currency=None, requested_amount=None, available_amount=None, message=None):
        self.account_id = account_id
        self.currency = currency
        self.requested_amount = requested_amount
        self.available_amount = available_amount
        if message is None:
            parts = ["Insufficient funds"]
            if currency:
                parts.append(f"for {currency}")
            if account_id:
                parts.append(f"in account '{account_id}'")
            if requested_amount is not None and available_amount is not None:
                parts.append(f" (requested: {requested_amount}, available: {available_amount})")
            elif requested_amount is not None:
                parts.append(f" (requested: {requested_amount})")
            message = "".join(parts) + "."
        super().__init__(message)

class InvalidLedgerOperationError(LedgerError):
    """
    Raised when an attempted ledger operation is invalid for the current
    state or parameters.
    """
    def __init__(self, operation=None, reason=None, message=None):
        self.operation = operation
        self.reason = reason
        if message is None:
            parts = ["Invalid ledger operation"]
            if operation:
                parts.append(f"'{operation}'")
            if reason:
                parts.append(f": {reason}")
            message = "".join(parts) + "."
        super().__init__(message)

class AccountNotFoundError(LedgerError):
    """Raised when a ledger account cannot be found."""
    def __init__(self, account_id=None, user_id=None, currency=None, message=None):
        self.account_id = account_id
        self.user_id = user_id
        self.currency = currency
        if message is None:
            parts = ["Ledger account not found"]
            if account_id:
                parts.append(f"for account ID '{account_id}'")
            elif user_id and currency:
                parts.append(f"for user '{user_id}' and currency '{currency}'")
            elif user_id:
                parts.append(f"for user '{user_id}'")
            elif currency:
                parts.append(f"for currency '{currency}'")
            message = "".join(parts) + "."
        super().__init__(message)

# Example of another specific error mentioned in comments (now implemented)
# class AccountNotFoundError(LedgerError): # Now defined above
#     """Raised when a ledger account cannot be found."""
#     def __init__(self, account_id, message=None):
#         self.account_id = account_id
#         if message is None:
#             message = f"Ledger account not found: {account_id}"
#         super().__init__(message)