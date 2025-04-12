# backend/store/exceptions.py
# Revision 1.3: Updated PostBroadcastUpdateError.__init__ to accept kwargs (Apr 11, 2025).
# Revision 1.2: Added PostBroadcastUpdateError exception (Apr 11, 2025).
# Revision 1.1: Added MoneroDaemonError exception (Apr 5, 2025).
# Revision 1.0: Added missing exception definitions (EscrowError, CryptoProcessingError, MoneroRPCError). Cleaned up comments.

from typing import Optional # Added for type hinting

class ShadowMarketException(Exception):
    """Base exception for Shadow Market errors."""
    pass

class UnauthorizedAccessException(ShadowMarketException):
    """Raised when unauthorized access is attempted."""
    pass

class InvalidInputException(ShadowMarketException):
    """Raised when user input is invalid."""
    pass

class OperationFailedException(ShadowMarketException):
    """Raised when a critical operation fails."""
    pass

# Note: LedgerError might be better placed in ledger/exceptions.py if that module exists.
# Keeping definition here if it's used across store app.
class LedgerError(Exception):
    """Base exception for ledger operations."""
    pass

# +++ Added missing exception types +++
class EscrowError(OperationFailedException):
    """Specific errors related to the escrow process."""
    pass

class CryptoProcessingError(OperationFailedException):
    """Specific errors related to cryptocurrency operations (creation, signing, broadcast etc.)."""
    pass

# +++ Added missing PostBroadcastUpdateError +++
class PostBroadcastUpdateError(OperationFailedException):
    """Raised when updating internal state fails after a successful transaction broadcast."""
    # +++ Fix: Added __init__ to accept kwargs +++
    def __init__(self, message: str, original_exception: Exception, tx_hash: Optional[str] = None, *args):
        """
        Initializes PostBroadcastUpdateError.

        Args:
            message: Description of the update failure.
            original_exception: The underlying exception that occurred during the update.
            tx_hash: The hash of the transaction that was successfully broadcast.
        """
        super().__init__(message, *args)
        self.original_exception = original_exception
        self.tx_hash = tx_hash
        # Optionally enhance the message stored in the base class
        self.args = (f"{message} (Original exception: {type(original_exception).__name__}, TX Hash: {tx_hash or 'N/A'})",)

    def __str__(self):
        # Override str for potentially cleaner representation if needed
        # Default inherited str() will use self.args[0] which we modified above.
        return super().__str__()

# +++ End added PostBroadcastUpdateError +++

class MoneroRPCError(CryptoProcessingError):
    """Specific errors reported by the Monero RPC interface."""
    def __init__(self, message: str, code: int = 0, *args):
        """
        Initializes MoneroRPCError.

        Args:
            message: The error message from the RPC response or description.
            code: The error code from the RPC response (if available, defaults to 0).
        """
        self.code = code
        self.message = message
        # Ensure the message includes the code for clarity in logs/exceptions.
        full_message = f"Monero RPC Error (Code: {code}): {message}"
        super().__init__(full_message, *args)

    def __str__(self):
        # Override str for cleaner representation without repeating the class name.
        return f"Monero RPC Error (Code: {self.code}): {self.message}"

# +++ Added MoneroDaemonError +++
class MoneroDaemonError(OperationFailedException):
    """Specific errors related to connecting or communicating with the Monero daemon."""
    pass

# Note: NotificationError might be better placed in notifications/exceptions.py if that module exists.
class NotificationError(Exception):
    """Base exception for notification operations."""
    pass

# --- Cleaned up duplicate LedgerError definition ---
# +++ End added exceptions +++