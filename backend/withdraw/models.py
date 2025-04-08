# backend/withdraw/models.py
# Revision 1: Initial creation. Defines WithdrawalStatusChoices and WithdrawalRequest model.

from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

# --- Choices ---

class WithdrawalStatusChoices(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    PROCESSING = 'PROCESSING', _('Processing') # Added intermediate state
    COMPLETED = 'COMPLETED', _('Completed')
    FAILED = 'FAILED', _('Failed')
    CANCELLED = 'CANCELLED', _('Cancelled') # Added state

class CurrencyChoices(models.TextChoices):
    # Assuming these are the primary supported currencies based on settings/tests
    # Add others as needed
    BTC = 'BTC', _('Bitcoin')
    XMR = 'XMR', _('Monero')
    ETH = 'ETH', _('Ethereum')

# --- Models ---

class WithdrawalRequest(models.Model):
    """
    Represents a user's request to withdraw funds from their account.
    """
    id = models.BigAutoField(primary_key=True) # Explicit BigAutoField primary key
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, # Protect user if withdrawals exist? Or CASCADE? PROTECT safer initially.
        related_name='withdrawal_requests',
        verbose_name=_('User')
    )
    currency = models.CharField(
        max_length=10,
        choices=CurrencyChoices.choices,
        verbose_name=_('Currency'),
        db_index=True, # Often queried by currency
    )
    requested_amount = models.DecimalField(
        max_digits=18, # Standard precision for crypto (e.g., 8 decimal places for BTC)
        decimal_places=8,
        verbose_name=_('Requested Amount')
    )
    # Fee details are stored at the time of request
    fee_percentage = models.DecimalField(
        max_digits=5, # e.g., 10.00 %
        decimal_places=2,
        verbose_name=_('Fee Percentage (%)')
    )
    fee_amount = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        verbose_name=_('Fee Amount')
    )
    net_amount = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        verbose_name=_('Net Amount Sent') # Amount sent after fees
    )
    withdrawal_address = models.TextField( # Use TextField for variable address lengths
        verbose_name=_('Withdrawal Address')
    )
    status = models.CharField(
        max_length=20,
        choices=WithdrawalStatusChoices.choices,
        default=WithdrawalStatusChoices.PENDING,
        verbose_name=_('Status'),
        db_index=True, # Often queried by status
    )
    broadcast_tx_hash = models.CharField(
        max_length=255, # Generous length for various crypto tx hashes
        blank=True,
        null=True,
        verbose_name=_('Broadcast Transaction Hash'),
        db_index=True, # Useful for looking up by hash
        help_text=_("The transaction ID on the blockchain once broadcast.")
    )
    failure_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Failure Reason'),
        help_text=_("Reason if the withdrawal request failed or was cancelled.")
    )
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created At')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Last Updated At')
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Processed At'),
        help_text=_("Timestamp when the request reached a final state (Completed, Failed, Cancelled).")
    )

    class Meta:
        verbose_name = _('Withdrawal Request')
        verbose_name_plural = _('Withdrawal Requests')
        ordering = ['-created_at'] # Show newest requests first by default
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'currency']),
        ]

    def __str__(self):
        return f"Withdrawal {self.id} ({self.user.username} - {self.requested_amount} {self.currency} - {self.status})"

    def save(self, *args, **kwargs):
        # Update processed_at when reaching a final state
        if self.pk is not None: # Only check on updates, not creation
            orig = WithdrawalRequest.objects.get(pk=self.pk)
            final_states = [
                WithdrawalStatusChoices.COMPLETED,
                WithdrawalStatusChoices.FAILED,
                WithdrawalStatusChoices.CANCELLED,
            ]
            # If status changed *to* a final state and processed_at is not already set
            if self.status != orig.status and self.status in final_states and self.processed_at is None:
                self.processed_at = timezone.now()
        # Set processed_at on creation if created directly in a final state (less common)
        elif self.pk is None and self.status in [WithdrawalStatusChoices.COMPLETED, WithdrawalStatusChoices.FAILED, WithdrawalStatusChoices.CANCELLED]:
             self.processed_at = timezone.now()

        super().save(*args, **kwargs)