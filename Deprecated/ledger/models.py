# backend/ledger/models.py
# Revision History:
# 2025-04-09 - v1.2.1 - Applied uncommenting based on user request and v1.2 comment. # Updated date
# 2025-04-06 - v1.2 - Uncommented LOCK_FUNDS and UNLOCK_FUNDS in TRANSACTION_TYPE_CHOICES to align with ledger service logic and fix test failures.
# 2025-04-06 - v1.1 - Added DISPUTE_RESOLUTION_BUYER and DISPUTE_RESOLUTION_VENDOR to TRANSACTION_TYPE_CHOICES to fix InvalidLedgerOperationError during escrow dispute resolution.
# Initial Version - v1.0
"""
Database models for the ledger application.

Includes UserBalance to track funds per currency and LedgerTransaction
to audit all balance changes.
"""

import uuid
import logging # Added for logging in __str__ fallback
from decimal import Decimal
from django.db import models
from django.conf import settings # To reference AUTH_USER_MODEL
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _ # For choice labels

# Initialize logger for this module
logger = logging.getLogger(__name__)

# --- Choices Definitions ---

# Define currency choices centrally or import them if defined elsewhere
CURRENCY_CHOICES = [
    ('BTC', _('Bitcoin')),
    ('XMR', _('Monero')),
    ('ETH', _('Ethereum')),
    # Add other supported currencies here as needed
]

# Define Transaction Types - Ensure this list is comprehensive and matches service layer logic
# Includes types added based on recent fixes/requirements
TRANSACTION_TYPE_CHOICES = [
    # Standard Operations
    ('DEPOSIT', _('Deposit Confirmed')),
    ('WITHDRAWAL_REQUEST', _('Withdrawal Requested')), # Typically locks funds
    ('WITHDRAWAL_SENT', _('Withdrawal Sent')), # Debits balance after successful send
    ('WITHDRAWAL_FAIL', _('Withdrawal Failed')), # Typically unlocks funds

    # Escrow Lifecycle (Example Flow)
    ('ESCROW_LOCK', _('Escrow Funds Locked')), # Optional separate entry if tracking lock via ledger
    ('ESCROW_FUND_DEBIT', _('Escrow Funded (Debit Buyer)')), # <<< Debits buyer total balance for escrow >>>
    ('ESCROW_RELEASE_VENDOR', _('Escrow Released to Vendor')), # <<< Credits Vendor balance >>>
    ('ESCROW_RELEASE_BUYER', _('Escrow Released to Buyer')), # <<< Credits Buyer balance (e.g., dispute win) >>>

    # --- Dispute Resolution Specific Types (Added v1.1) ---
    ('DISPUTE_RESOLUTION_BUYER', _('Dispute Resolution (Credit Buyer)')), # <<< Credits Buyer balance from dispute >>>
    ('DISPUTE_RESOLUTION_VENDOR', _('Dispute Resolution (Credit Vendor)')), # <<< Credits Vendor balance from dispute >>>
    # --- End Added v1.1 ---

    # Market/Fees/Bonds
    ('MARKET_FEE', _('Market Fee Collected')), # <<< Credits market balance >>>
    ('VENDOR_BOND_PAY', _('Vendor Bond Paid')), # Debits Vendor balance
    ('MARKET_BOND_FORFEIT', _('Market Bond Forfeited')), # <<< Credits market balance from forfeit >>>

    # Adjustments
    ('MANUAL_ADJUST_CREDIT', _('Manual Adjustment (Credit)')),
    ('MANUAL_ADJUST_DEBIT', _('Manual Adjustment (Debit)')),

    # Optional Auditing Types (if creating ledger entries for simple lock/unlock actions)
    # --- Updated based on v1.2 comment ---
    ('LOCK_FUNDS', _('Funds Locked')), # <-- Uncommented
    ('UNLOCK_FUNDS', _('Funds Unlocked')), # <-- Uncommented
    # --- End Updated v1.2 ---
]


# --- Model Definitions ---

class UserBalance(models.Model):
    """ Stores the current and locked balance for each user per currency. """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, # Prevent deleting user if they have balance. Consider implications.
        related_name='ledger_balances',
        verbose_name=_("User")
    )
    currency = models.CharField(
        _("Currency"),
        max_length=10, # Sufficient for common currency codes
        choices=CURRENCY_CHOICES,
        db_index=True # Index for quick lookup by currency
    )
    # Use high precision Decimals for financial data.
    # Adjust max_digits and decimal_places based on the maximum expected value and required precision.
    balance = models.DecimalField(
        _("Total Balance"),
        max_digits=30, # e.g., up to 18 digits left of decimal, 12 right
        decimal_places=12,
        default=Decimal('0.0'),
        validators=[MinValueValidator(Decimal('0.0'))], # Basic database/form level check
        help_text=_("Total balance including locked funds.")
    )
    locked_balance = models.DecimalField(
        _("Locked Balance"),
        max_digits=30,
        decimal_places=12,
        default=Decimal('0.0'),
        validators=[MinValueValidator(Decimal('0.0'))], # Basic database/form level check
        help_text=_("Funds locked for escrow, pending withdrawals, etc.")
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Last Updated"), auto_now=True)

    class Meta:
        verbose_name = _("User Balance")
        verbose_name_plural = _("User Balances")
        # Ensure only one balance record per user/currency combination
        unique_together = ('user', 'currency')
        indexes = [
            # Index for efficient lookup/joining by user and currency
            models.Index(fields=['user', 'currency'], name='ledger_userbalance_user_curr_idx'),
        ]
        ordering = ['user__username', 'currency'] # Default ordering in admin/queries

    def __str__(self):
        """ String representation showing available balance. """
        try:
            # Calculate available balance using the property
            available = self.available_balance
            # Basic formatting - consider more sophisticated currency formatting if needed
            display_precision = 8 # Default precision for display
            if self.currency in ['XMR']: # Example of different precision
                 display_precision = 12
            # Use f-string formatting for precision
            # Ensure user object is loaded or handle potential RelatedObjectDoesNotExist
            username = getattr(self.user, self.user.USERNAME_FIELD, f"User {self.user_id}")
            return f"{username} - {self.currency}: {available:.{display_precision}f} Available"
        except Exception as e: # Catch potential errors during property access or formatting
            # Fallback representation
            logger.error(f"Error formatting UserBalance string for balance ID {self.pk} (User ID: {getattr(self, 'user_id', 'N/A')}): {e}", exc_info=True)
            username = getattr(self, 'user_id', 'N/A') # Use user_id if user object isn't loaded
            return f"User {username} - {self.currency}"


    @property
    def available_balance(self) -> Decimal:
        """
        Calculated available balance (Total Balance - Locked Balance).
        Ensures the result is never negative, guarding against potential state inconsistencies.
        """
        available = self.balance - self.locked_balance
        # Safety check: Available funds cannot logically be negative.
        return max(available, Decimal('0.0'))

    def clean(self):
        """
        Adds model-level validation beyond basic field validators.
        Called during ModelForm validation and full_clean().
        """
        super().clean() # Call parent clean method first

        # Ensure balances are not negative (supplements MinValueValidator for ModelForms/full_clean)
        # Note: Database CHECK constraints are more robust for direct DB operations if supported.
        if self.balance is not None and self.balance < Decimal('0.0'):
            raise ValidationError({'balance': _("Balance cannot be negative.")})

        if self.locked_balance is not None and self.locked_balance < Decimal('0.0'):
            raise ValidationError({'locked_balance': _("Locked balance cannot be negative.")})

        # Critical check: Locked funds cannot exceed the total balance.
        if (self.balance is not None and self.locked_balance is not None and
                self.locked_balance > self.balance):
            raise ValidationError(
                _("Locked balance (%(locked)s) cannot exceed total balance (%(balance)s).") %
                {'locked': self.locked_balance, 'balance': self.balance}
            )

    # Optional: Add methods for atomic updates if performing balance changes
    # outside the main `record_transaction` service, ensuring use of F() expressions.
    # Example:
    # from django.db.models import F
    # def increase_locked_balance_atomic(self, amount: Decimal):
    #   if amount > 0:
    #       self.locked_balance = F('locked_balance') + amount
    #       self.save(update_fields=['locked_balance'])
    #       self.refresh_from_db(fields=['locked_balance']) # Get the updated value


class LedgerTransaction(models.Model):
    """
    Records every change to user balances for auditing purposes.
    Designed to be immutable (append-only).
    """
    # Use UUID for primary key to avoid sequence gaps and improve potential distribution
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, # Protect transaction history if user is deleted
        related_name='ledger_transactions',
        verbose_name=_("User")
    )
    transaction_type = models.CharField(
        _("Transaction Type"),
        max_length=30, # Adjust if longer type codes are needed
        choices=TRANSACTION_TYPE_CHOICES, # Use the updated list
        db_index=True # Index for filtering by type
    )
    currency = models.CharField(
        _("Currency"),
        max_length=10, # Match UserBalance.currency
        choices=CURRENCY_CHOICES,
        db_index=True # Index for filtering by currency
    )
    # Amount represents the specific change (+/-) in this transaction
    amount = models.DecimalField(
        _("Amount Change"),
        max_digits=30, # Match UserBalance precision
        decimal_places=12
    )
    # Snapshot of balance *before* this transaction was applied for auditing
    balance_before = models.DecimalField(
        _("Balance Before"),
        max_digits=30,
        decimal_places=12,
        help_text=_("The user's total balance immediately before this transaction.")
    )
    # Snapshot of balance *after* this transaction was applied
    balance_after = models.DecimalField(
        _("Balance After"),
        max_digits=30,
        decimal_places=12,
        help_text=_("The user's total balance immediately after this transaction.")
    )
    # Snapshot of locked balance state *after* this transaction occurred
    locked_balance_after = models.DecimalField(
        _("Locked Balance After"),
        max_digits=30,
        decimal_places=12,
        null=True, # Allow null if not applicable (e.g., older entries, non-locking tx)
        blank=True, # Allow blank in forms
        help_text=_("The user's locked balance state immediately after this transaction (snapshot).")
    )

    # Optional related objects for context
    related_order = models.ForeignKey(
        'store.Order', # Use string reference ('app_label.ModelName') to avoid circular imports
        on_delete=models.SET_NULL, # Keep transaction history even if order is deleted
        null=True,
        blank=True,
        related_name='ledger_entries', # How Order accesses its ledger entries
        verbose_name=_("Related Order")
    )
    # Add other ForeignKeys if transactions relate to other models, e.g.:
    # related_withdrawal = models.ForeignKey('withdrawals.Withdrawal', on_delete=models.SET_NULL, null=True, blank=True)

    external_txid = models.CharField(
        _("External TXID"),
        max_length=255, # Allow for long blockchain transaction IDs
        blank=True, # Not all transactions have an external ID
        null=True,
        db_index=True, # Index if searching by external TXID is common
        help_text=_("Blockchain TXID or other external reference, if applicable.")
    )

    notes = models.TextField(
        _("Notes"),
        blank=True, # Notes are optional
        help_text=_("Additional details, e.g., admin username for manual adjustments, reason for tx.")
    )
    timestamp = models.DateTimeField(
        _("Timestamp"),
        auto_now_add=True, # Automatically set when the transaction record is created
        editable=False, # Should not be changed after creation
        db_index=True # Essential for ordering and time-based queries
    )

    class Meta:
        verbose_name = _("Ledger Transaction")
        verbose_name_plural = _("Ledger Transactions")
        ordering = ['-timestamp'] # Show newest transactions first by default
        indexes = [
            # Composite index for common filtering/ordering by user+currency+time
            models.Index(fields=['user', 'currency', 'timestamp'], name='ledger_tx_user_curr_time_idx'),
            # Index for filtering by type (e.g., finding all deposits)
            models.Index(fields=['transaction_type', 'timestamp'], name='ledger_tx_type_time_idx'),
            # Index if filtering by related order is frequent
            models.Index(fields=['related_order'], name='ledger_tx_order_idx'),
            # Index if looking up transactions by external ID is frequent
            models.Index(fields=['external_txid'], name='ledger_tx_ext_txid_idx'),
        ]

    def __str__(self):
        """ String representation showing key details. """
        # Format amount with sign (+/-) for clarity
        amount_sign = '+' if self.amount >= Decimal('0.0') else ''
        # Ensure amount is formatted reasonably, avoid excessive precision if zero
        if self.amount == Decimal('0.0'):
            amount_str = "0"
        else:
             # Basic formatting, consider currency-specific precision later if needed
            amount_str = f"{amount_sign}{self.amount.normalize()}" # normalize removes trailing zeros

        # Use get_FOO_display() for choice fields to show the human-readable label
        try:
             username = getattr(self.user, self.user.USERNAME_FIELD, f"User {self.user_id}")
             tx_type_display = self.get_transaction_type_display()
        except Exception as e:
             logger.error(f"Error accessing related user or display value for LedgerTransaction {self.id}: {e}", exc_info=True)
             username = f"User {getattr(self, 'user_id', 'N/A')}"
             tx_type_display = self.transaction_type # Fallback to raw type

        return (
            f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - "
            f"{username} - "
            f"{tx_type_display} "
            f"({amount_str} {self.currency})"
        )

    # --- Immutability Enforcement (Optional) ---
    # Uncomment these methods to strictly prevent changes or deletions
    # after a transaction record is created. Test thoroughly if enabled.

    # def save(self, *args, **kwargs):
    #   """ Prevent updates to existing ledger transactions. """
    #   if self.pk and not kwargs.get('force_insert', False):
    #       # Check if it's an update by seeing if pk exists and it's not a forced insert
    #       raise ValidationError(_("Ledger transactions cannot be modified after creation."))
    #   super().save(*args, **kwargs)

    # def delete(self, *args, **kwargs):
    #   """ Prevent deletion of ledger transactions. """
    #   raise ValidationError(_("Ledger transactions cannot be deleted."))