# backend/ledger/constants.py
# --- Revision History ---
# 2025-05-03 - v1.0.1 - Added ATOMIC_FACTOR dictionary for currency conversions. (Gemini)
# 2025-04-29 - v1.0.0 - Created constants based on choices in ledger/models.py v1.2.1
"""
Constants for the ledger application.

Defines constants based on model choices to provide reliable references
in service and task logic, avoiding the use of raw strings.
Values MUST be kept in sync with the choices defined in ledger/models.py.
"""
import datetime # Added for revision date
from decimal import Decimal # Import Decimal for consistency if needed later

# --- Transaction Types ---
# Extracted from TRANSACTION_TYPE_CHOICES in ledger/models.py (v1.2.1)
# Ensure these string values exactly match the first element of each tuple
# in the TRANSACTION_TYPE_CHOICES list in models.py.

# Standard Operations
TRANSACTION_TYPE_DEPOSIT = 'DEPOSIT'
TRANSACTION_TYPE_WITHDRAWAL_REQUEST = 'WITHDRAWAL_REQUEST'
TRANSACTION_TYPE_WITHDRAWAL_SENT = 'WITHDRAWAL_SENT'
TRANSACTION_TYPE_WITHDRAWAL_FAIL = 'WITHDRAWAL_FAIL'

# Escrow Lifecycle
TRANSACTION_TYPE_ESCROW_LOCK = 'ESCROW_LOCK'
TRANSACTION_TYPE_ESCROW_FUND_DEBIT = 'ESCROW_FUND_DEBIT'
TRANSACTION_TYPE_ESCROW_RELEASE_VENDOR = 'ESCROW_RELEASE_VENDOR'
TRANSACTION_TYPE_ESCROW_RELEASE_BUYER = 'ESCROW_RELEASE_BUYER'

# Dispute Resolution Specific Types
TRANSACTION_TYPE_DISPUTE_RESOLUTION_BUYER = 'DISPUTE_RESOLUTION_BUYER'
TRANSACTION_TYPE_DISPUTE_RESOLUTION_VENDOR = 'DISPUTE_RESOLUTION_VENDOR'

# Market/Fees/Bonds
TRANSACTION_TYPE_MARKET_FEE = 'MARKET_FEE'
TRANSACTION_TYPE_VENDOR_BOND_PAY = 'VENDOR_BOND_PAY'
TRANSACTION_TYPE_MARKET_BOND_FORFEIT = 'MARKET_BOND_FORFEIT' # Changed from MARKET_ to match usage in forfeit_bond

# Adjustments
TRANSACTION_TYPE_MANUAL_ADJUST_CREDIT = 'MANUAL_ADJUST_CREDIT'
TRANSACTION_TYPE_MANUAL_ADJUST_DEBIT = 'MANUAL_ADJUST_DEBIT'

# Optional Auditing Types
TRANSACTION_TYPE_LOCK_FUNDS = 'LOCK_FUNDS'
TRANSACTION_TYPE_UNLOCK_FUNDS = 'UNLOCK_FUNDS'

# Add any other transaction types defined in models.py here


# --- Currency Constants ---

# Dictionary mapping currency codes to their atomic unit factor (integer)
# (e.g., Satoshis per BTC, piconeros per XMR, Wei per ETH)
# Keys should match the values used in store.models.Currency enum/choices.
ATOMIC_FACTOR = {
    'BTC': 100_000_000,                 # 1 BTC = 10^8 Satoshis
    'XMR': 1_000_000_000_000,           # 1 XMR = 10^12 Piconeros
    'ETH': 1_000_000_000_000_000_000,   # 1 ETH = 10^18 Wei
    # Add other supported currencies here if needed, ensuring the key matches
    # the string representation used elsewhere (e.g., store.models.Currency.BTC.value)
}


# --- Other Ledger Constants (if any) ---
# Example:
# DEFAULT_RECONCILIATION_THRESHOLD = Decimal('0.00000001')