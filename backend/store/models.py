# backend/store/models.py
"""
Django models for the core store application.
Includes models for Users (custom), Categories, Products, Orders, Payments,
Feedback, Support Tickets, Global Settings, Audit Logs, WebAuthn Credentials,
Vendor Applications, and Disputes.
Focuses on structure, relationships, basic validation, and indexing for performance.
Uses Decimal for financial values and UUIDs where appropriate.
Integrates PGP key requirements and basic multi-sig fields.
"""
# <<< ENTERPRISE GRADE REVISION: v1.4.3 - Ensure Order Total Price Consistency >>>
# Revision Notes:
# - v1.4.3 (2025-05-22):
#   - Order.save():
#     - MODIFIED: Ensured that `total_price_native_selected` is recalculated and set
#       based on `price_native_selected`, `quantity`, and `shipping_price_native_selected`
#       before saving the Order instance. This addresses a potential inconsistency where
#       the `clean()` method might log a warning about a differing price, but `save()`
#       didn't enforce the update.
#     - Rationale: Guarantees data integrity for order totals at the model level.
# - v1.4.2 (2025-05-19):
#   - UserManager._validate_pgp & User.clean:
#     - REMOVED: The temporary workaround logic that skipped PGP validation for certain placeholder
#       test PGP keys (identified by strings like "USER TEST KEY", "APPLICATION TEST KEY", etc.).
#     - Rationale: This change aligns with the requirement for production-grade code, which should
#       not contain test-specific validation bypasses. All PGP keys provided to user creation
#       or model cleaning will now be subject to `validate_pgp_public_key`.
#     - IMPACT: Tests relying on the workaround with invalid PGP keys will now fail. These tests
#       must be updated to either use valid (minimal) PGP keys, mock the PGP validation appropriately,
#       or pass `None` for `pgp_public_key` if the user is intended to not have one (as the field is optional).
#     - CLEANUP: Slightly refactored the conditional PGP validation call for clarity.
# - v1.4.1 (2025-05-18)
#   - UserManager._validate_pgp:
#     - Expanded the temporary workaround to identify more placeholder PGP key patterns used in tests
#       (e.g., "APPLICATION TEST KEY", "USER TEST KEY", "ADMIN KEY", "VENDOR KEY").
#     - Added stripping of the PGP key string before checking for placeholder content to handle
#       variations in test data (like leading/trailing newlines).
#   - User.clean:
#     - Applied a similar expanded workaround to the PGP validation logic within the User model's
#       clean method to ensure consistency.
#   - Rationale: This addresses a large number of `ValueError` exceptions raised during test `setUpTestData`
#       phases due to invalid placeholder PGP keys being rejected by the PGP validator. This allows
#       more tests to proceed. This remains a workaround; tests should ideally use valid minimal PGP keys
#       or mock the PGP validation directly.
# - v1.4.0 (2025-05-12)
#   - User model:
#     - Modified `pgp_public_key` field to allow `null=True` and `blank=True`, making it optional.
#     - Updated help_text for `pgp_public_key` to reflect it's optional.
#     - Removed `pgp_public_key` from `REQUIRED_FIELDS` to align with its optional nature.
#   - UserManager:
#     - Modified `_validate_pgp` to only validate the PGP key if it's actually provided (non-empty string).
#       If `pgp_public_key` is None or an empty string, validation is skipped.
#     - Adjusted `create_user` to ensure that if an empty string is passed for `pgp_public_key`,
#       `None` is stored in the database (respecting `null=True`).
#   - Rationale: This resolves the `IntegrityError: NOT NULL constraint failed: store_user.pgp_public_key`
#     encountered in tests when attempting to create a user with `pgp_public_key=None`. It allows
#     the system to represent users (e.g., vendors) who may not have configured a PGP key yet.
#     A database migration will be required after this model change.
# - v1.3.9 (2025-05-04)
#   - FIXED: Added a temporary workaround in `UserManager._validate_pgp` to skip PGP validation
#     *only* for the specific invalid key string ("-----BEGIN...SERIALIZER TEST KEY...END-----")
#     used in numerous test setups. This directly addresses the `ValueError` causing 156 test errors
#     during user creation in test `setUp` methods.
#   - NOTE: This is a workaround. The ideal long-term fix is to modify the tests to use a valid
#     dummy PGP key or mock the validation step appropriately. This change allows tests to proceed
#     without compromising production PGP key validation.
# - (Older revisions omitted for brevity)


# Standard Library Imports
import logging
import uuid # Ensure UUID is imported
from decimal import Decimal # Ensure Decimal is imported
from typing import Optional, List, Dict, Sequence # Keep necessary type hints
import datetime # Added for revision date

# Django Core Imports
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models, transaction # Added transaction for commentary context
from django.utils import timezone
from django.utils.translation import gettext_lazy as _ # Added for VendorApplication, Dispute
# from django.utils.text import slugify # Uncomment if using auto-slug generation in save methods

# Third-Party Imports
# CRITICAL: Ensure django-solo is installed and listed in INSTALLED_APPS
try:
    from solo.models import SingletonModel
except ImportError as e_solo:
    # Initialize logger here for early critical error logging if needed
    logger_solo_init = logging.getLogger(__name__)
    logger_solo_init.critical("CRITICAL IMPORT ERROR: Failed to import 'SingletonModel' from 'solo.models'. Is django-solo installed and configured correctly?")
    raise ImportError("Failed to import SingletonModel from solo.models. Ensure django-solo is installed and in INSTALLED_APPS.") from e_solo

# Initialize logger at module level for consistent use
logger = logging.getLogger(__name__)

# Local Application Imports
# IMPORTANT: To avoid model conflicts (e.g., "Conflicting '...' models"), ensure ALL imports
# of models from this app (store) throughout the project use the absolute path:
# `from backend.store.models import YourModel`
# Avoid relative imports like `from .models import ...` or `from store.models import ...`
# CRITICAL: Ensure these validators are robustly implemented and thoroughly tested.
try:
    from .validators import (
        validate_pgp_public_key,
        validate_monero_address,
        validate_bitcoin_address,
        validate_ethereum_address,
    )
except ImportError as e:
    logger.critical(f"CRITICAL IMPORT ERROR for validators in models.py: {e}. Application may not function correctly.")
    # Re-raise to prevent Django startup if validators are missing and absolutely essential
    raise ImportError(f"Failed to import validators in store/models.py: {e}. Check .validators module.") from e


# --- Constants and Choices ---

class Currency(models.TextChoices):
    """Supported cryptocurrencies."""
    XMR = 'XMR', 'Monero'
    BTC = 'BTC', 'Bitcoin'
    ETH = 'ETH', 'Ethereum'

# Provides the expected choices tuple
CURRENCY_CHOICES = Currency.choices

class FiatCurrency(models.TextChoices):
    """Supported fiat currencies for display/reference."""
    USD = 'USD', 'United States Dollar'
    EUR = 'EUR', 'Euro'
    # Add others as needed (GBP, CAD, JPY, etc.)

# NOTE: This top-level enum is potentially deprecated in favor of Order.StatusChoices below.
# It is kept for now to avoid breaking potential imports elsewhere in the codebase.
# Consider refactoring other code to use Order.StatusChoices directly.
class OrderStatus(models.TextChoices):
    """Status codes for the order lifecycle."""
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
    PAYMENT_CONFIRMED = 'payment_confirmed', 'Payment Confirmed / In Escrow'
    SHIPPED = 'shipped', 'Shipped'
    FINALIZED = 'finalized', 'Finalized'
    DISPUTED = 'disputed', 'Disputed'
    DISPUTE_RESOLVED = 'dispute_resolved', 'Dispute Resolved'
    CANCELLED_TIMEOUT = 'cancelled_timeout', 'Cancelled (Timeout)'
    CANCELLED_BUYER = 'cancelled_buyer', 'Cancelled (Buyer)'
    CANCELLED_VENDOR = 'cancelled_vendor', 'Cancelled (Vendor)'
    CANCELLED_UNDERPAID = 'cancelled_underpaid', 'Cancelled (Underpaid)'
    REFUNDED = 'refunded', 'Refunded'

class FeedbackType(models.TextChoices):
    """Overall sentiment derived from feedback rating."""
    POSITIVE = 'positive', 'Positive'
    NEUTRAL = 'neutral', 'Neutral'
    NEGATIVE = 'negative', 'Negative'

class SupportTicketStatus(models.TextChoices):
    """Status codes for support tickets."""
    OPEN = 'open', 'Open'
    ANSWERED = 'answered', 'Answered'
    CLOSED = 'closed', 'Closed'

class AuditLogAction(models.TextChoices):
    """Actions recorded in the audit log for staff/system events."""
    LOGIN_SUCCESS = 'login_success', 'Staff Login Success'
    LOGIN_FAIL = 'login_fail', 'Staff Login Fail'
    USER_BAN = 'user_ban', 'User Banned'
    USER_UNBAN = 'user_unban', 'User Unbanned'
    VENDOR_APPROVE = 'vendor_approve', 'Vendor Approved'
    VENDOR_REJECT = 'vendor_reject', 'Vendor Rejected'
    VENDOR_APP_APPROVE = 'vendor_app_approve', 'Vendor Application Approved' # New
    VENDOR_APP_REJECT = 'vendor_app_reject', 'Vendor Application Rejected' # New
    ORDER_UPDATE_STATUS = 'order_update_status', 'Order Status Updated'
    DISPUTE_OPEN = 'dispute_open', 'Dispute Opened' # New
    DISPUTE_RESOLVE = 'dispute_resolve', 'Dispute Resolved'
    SETTINGS_CHANGE = 'settings_change', 'Global Settings Changed'
    FUNDS_FREEZE = 'funds_freeze', 'Funds Frozen'
    FUNDS_UNFREEZE = 'funds_unfreeze', 'Funds Unfrozen'
    FUNDS_TRANSFER_OWNER = 'funds_transfer_owner', 'Funds Transfer Initiated'
    PRODUCT_DEACTIVATE = 'product_deactivate', 'Product Deactivated'
    PRODUCT_ACTIVATE = 'product_activate', 'Product Activated'
    TICKET_ASSIGN = 'ticket_assign', 'Ticket Assigned'
    TICKET_CLOSE = 'ticket_close', 'Ticket Closed'
    WITHDRAWAL_SUCCESS = 'withdrawal_success', 'Withdrawal Processed'
    CANARY_UPDATE = 'canary_update', 'Warrant Canary Updated'
    ADMIN_ACTION = 'admin_action', 'Generic Admin Action'

class EscrowType(models.TextChoices):
    """Available escrow mechanisms for orders."""
    BASIC = 'basic', 'Basic Centralized Escrow'
    MULTISIG = 'multisig', 'Multi-Signature Escrow'


# --- CORRECT Global Settings (Singleton Pattern using django-solo) ---
# IMPORTANT: Ensure this model is always imported using the full absolute path:
# `from backend.store.models import GlobalSettings`
# Avoid `from store.models import GlobalSettings` to prevent Django app loading conflicts.
class GlobalSettings(SingletonModel):
    """
    Stores site-wide configuration settings accessible via GlobalSettings.get_solo().
    Implemented as a singleton using django-solo.
    """
    # Basic Site Settings
    site_name = models.CharField(max_length=100, default="Shadow Market")
    maintenance_mode = models.BooleanField(default=False, help_text="If True, puts the site into read-only mode for most users.")
    allow_new_registrations = models.BooleanField(default=True, help_text="Controls if new users can register.")
    allow_new_vendors = models.BooleanField(default=True, help_text="Controls if users can apply to become vendors (via the new application process).") # Updated help text
    default_vendor_bond_usd = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1500.00'), validators=[MinValueValidator(0)], help_text="Default required vendor application bond amount in USD.")

    # Market Fees (Copied from removed definition)
    market_fee_percentage_xmr = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.0'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for XMR sales (e.g., 4.0 means 4%).")
    market_fee_percentage_btc = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.0'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for BTC sales.")
    market_fee_percentage_eth = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.5'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for ETH sales.")

    # Vendor Bonds (LEGACY - Copied from removed definition - May be deprecated by VendorApplication)
    # Consider removing these if vendor_bond_usd + VendorApplication is the sole mechanism now.
    vendor_bond_xmr = models.DecimalField(max_digits=18, decimal_places=12, default=Decimal('5.0'), validators=[MinValueValidator(0)], help_text="LEGACY: Required vendor bond amount in XMR.")
    vendor_bond_btc = models.DecimalField(max_digits=14, decimal_places=8, default=Decimal('0.05'), validators=[MinValueValidator(0)], help_text="LEGACY: Required vendor bond amount in BTC.")
    vendor_bond_eth = models.DecimalField(max_digits=24, decimal_places=18, default=Decimal('1.0'), validators=[MinValueValidator(0)], help_text="LEGACY: Required vendor bond amount in ETH.")

    # Payment/Order Timing (Copied from removed definition)
    confirmations_needed_xmr = models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(1)], help_text="Required confirmations for XMR payments.")
    confirmations_needed_btc = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)], help_text="Required confirmations for BTC payments.")
    confirmations_needed_eth = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1)], help_text="Required confirmations for ETH payments.")
    payment_wait_hours = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(1)], help_text="Hours allowed for buyer to make payment before order times out.")
    order_auto_finalize_days = models.PositiveIntegerField(default=14, validators=[MinValueValidator(1)], help_text="Days after shipping before an order auto-finalizes.")
    dispute_window_days = models.PositiveIntegerField(default=7, validators=[MinValueValidator(1)], help_text="Days after shipping (or other trigger) allowed for opening a dispute.")

    # Security / Emergency (Copied from removed definition)
    freeze_funds = models.BooleanField(default=False, help_text="EMERGENCY: If True, halts withdrawals and automatic payouts/finalizations.")
    deadman_switch_threshold_days = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)], help_text="Maximum days allowed between admin Dead Man's Switch check-ins before triggering alert.")
    last_dms_check_in_ts = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last successful Dead Man's Switch check-in by admin.")

    # Warrant Canary (Copied from removed definition)
    canary_content = models.TextField(blank=True, help_text="Warrant canary text. MUST include the current date and be updated regularly.")
    canary_last_updated = models.DateField(null=True, blank=True, help_text="Date the canary_content was last confirmed/updated. MUST match date in content.")
    canary_pgp_signature = models.TextField(blank=True, help_text="Detached PGP signature verifying the authenticity of (canary_content + canary_last_updated date string).")
    canary_signing_key_fingerprint = models.CharField(max_length=40, blank=True, null=True, validators=[RegexValidator(regex=r'^[0-9A-Fa-f]{40}$', message='Enter a valid 40-character PGP key fingerprint.')], help_text="The 40-character PGP key fingerprint of the key used to sign the canary.")
    canary_signing_key_url = models.URLField(max_length=512, blank=True, null=True, help_text="URL where the signing PGP public key can be reliably obtained.")

    # --- NEW: Exchange Rate Fields ---
    btc_usd_rate = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True, help_text="Latest BTC to USD exchange rate.")
    eth_usd_rate = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True, help_text="Latest ETH to USD exchange rate.")
    xmr_usd_rate = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True, help_text="Latest XMR to USD exchange rate.")
    usd_eur_rate = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True, help_text="Latest USD to EUR exchange rate (optional, can be derived).")
    rates_last_updated = models.DateTimeField(null=True, blank=True, help_text="Timestamp when exchange rates were last fetched and updated.")
    # --- End Exchange Rate Fields ---

    # --- NEW FIELD for ETH HD Wallet ---
    last_eth_hd_index = models.IntegerField(
        default=-1, # Start before the first index (0), ensures first generated index is 0
        db_index=True, # Index for faster lookup/locking
        help_text="Internal counter for the last used Ethereum HD wallet derivation index (m/44'/60'/0'/0/i)."
    )
    # --- END NEW FIELD ---

    # Timestamp inherited from SingletonModel or add manually if needed
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        # Use timezone.localtime to display time in the server's local timezone (or settings.TIME_ZONE)
        last_mod_time = timezone.localtime(self.updated_at) if hasattr(self, 'updated_at') and self.updated_at else None
        time_str = last_mod_time.strftime('%Y-%m-%d %H:%M %Z') if last_mod_time else 'Never'
        return f"Global Settings (Last Modified: {time_str})"

    class Meta:
        app_label = 'store' # Correctly identifies the app for this model
        verbose_name = "Global Settings"
        # verbose_name_plural = "Global Settings" # Optional


# --- Custom User Manager ---
class UserManager(BaseUserManager):
    """Manager for the custom User model."""

    def _validate_pgp(self, pgp_public_key: Optional[str]):
        """
        Internal helper to validate PGP key using the external validator.
        Skips validation if pgp_public_key is None or an empty/whitespace-only string.
        """
        if pgp_public_key and pgp_public_key.strip(): # Only validate if a non-empty key string is provided
            try:
                validate_pgp_public_key(pgp_public_key) # Call the main validator from validators.py
            except ValidationError as e:
                error_message = getattr(e, 'message', str(e))
                if isinstance(error_message, list):
                    error_message = "; ".join(str(item) for item in error_message)
                elif not isinstance(error_message, str):
                    error_message = str(error_message)
                # Raise as ValueError to be caught by create_user or signal issues in .clean()
                raise ValueError(f'Invalid PGP Public Key provided: {error_message}') from e
        # If pgp_public_key is None or an empty string after stripping, it's considered optional and validation is skipped.

    def create_user(self, username: str, password: Optional[str] = None, pgp_public_key: Optional[str] = None, **extra_fields):
        """Creates and saves a regular user with username, password, and PGP key."""
        if not username:
            raise ValueError('The Username must be set.')

        # Validate PGP key if provided (non-empty string)
        # _validate_pgp will raise ValueError on invalid key, which will propagate out of create_user
        self._validate_pgp(pgp_public_key)

        # Clean pgp_public_key: store None if it's an empty string after stripping, or None initially
        pgp_public_key_cleaned = pgp_public_key.strip() if isinstance(pgp_public_key, str) else None
        if pgp_public_key_cleaned == "": # Treat truly empty string (after strip) as None for storage
            pgp_public_key_cleaned = None

        username = self.model.normalize_username(username)
        user = self.model(username=username, pgp_public_key=pgp_public_key_cleaned, **extra_fields)
        user.set_password(password) # Hashes the password securely
        user.save(using=self._db)
        logger.info(f"Created user: {username}")
        return user

    def create_superuser(self, username: str, password: Optional[str], pgp_public_key: Optional[str] = None, **extra_fields):
        """Creates and saves a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True) # Superusers should generally be active

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        logger.info(f"Creating superuser: {username}")
        # PGP key is passed to create_user; its optional nature and validation are handled there.
        return self.create_user(username, password, pgp_public_key, **extra_fields)


# --- Custom User Model ---
class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model representing buyers, vendors, and staff.
    Replaces the default Django User model. PGP key is optional.
    """
    id = models.BigAutoField(primary_key=True) # Standard BigAutoField for PK
    username = models.CharField(
        max_length=150,
        unique=True, # unique=True implies db index
        validators=[RegexValidator(
            regex=r'^[\w.-]+$', # Allow word chars, dots, hyphens
            message='Username can only contain letters, numbers, periods, hyphens, or underscores.'
        )],
        error_messages={
            'unique': "A user with that username already exists.",
        },
        help_text="Required. 150 characters or fewer. Letters, digits, periods, hyphens, underscores."
    )
    pgp_public_key = models.TextField(
        null=True,  # Allow NULL in the database
        blank=True, # Allow empty in forms/admin
        validators=[validate_pgp_public_key], # Model-level validation (will only apply if value is not blank and not null)
        help_text="Optional. Your full PGP public key block (including BEGIN/END markers). Used for secure communication and potentially 2FA/login challenges."
    )

    # Roles and Status
    is_vendor = models.BooleanField(
        default=False, db_index=True, help_text="Designates whether the user is an approved vendor."
    )
    is_staff = models.BooleanField(
        default=False, help_text="Designates whether the user can log into the admin site (/control/)."
    )
    is_active = models.BooleanField(
        default=True, db_index=True, help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts."
    )
    date_joined = models.DateTimeField(default=timezone.now, editable=False)

    # Security Fields
    login_phrase = models.CharField(
        max_length=100, blank=True, null=True,
        help_text="Optional unique phrase shown during login (step 2) to help prevent phishing. Keep this secret."
    )
    last_activity = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last recorded user activity (Updated via middleware recommended).")
    last_pgp_challenge_ts = models.DateTimeField(
        null=True, blank=True, help_text="Timestamp of the last successfully verified PGP login challenge (session)."
    )
    require_password_change = models.BooleanField(
        default=False, help_text="Force user to change password on next login."
    )

    # Vendor Specific Fields
    vendor_level = models.PositiveSmallIntegerField(default=1, help_text="Legacy/Simple Vendor trust level (may be derived from reputation metrics).")
    vendor_bond_paid = models.BooleanField(default=False, help_text="Indicates if the vendor bond has been paid and accepted (LEGACY - check VendorApplication status).") # Updated help text
    vendor_bond_amount_xmr = models.DecimalField(max_digits=18, decimal_places=12, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="LEGACY: Bond paid in XMR.")
    vendor_bond_amount_btc = models.DecimalField(max_digits=14, decimal_places=8, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="LEGACY: Bond paid in BTC.")
    vendor_bond_amount_eth = models.DecimalField(max_digits=24, decimal_places=18, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="LEGACY: Bond paid in ETH.")
    approved_vendor_since = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the user was approved as a vendor.")

    # --- Denormalized Vendor Reputation Metrics ---
    vendor_level_name = models.CharField(max_length=50, default="New Vendor", db_index=True, help_text="DENORMALIZED: Calculated vendor level name (e.g., New, Bronze, Silver, Gold). Updated periodically.")
    vendor_total_orders = models.PositiveIntegerField(default=0, help_text="DENORMALIZED: Total count of completed/resolved orders as vendor.")
    vendor_completed_orders_30d = models.PositiveIntegerField(default=0, help_text="DENORMALIZED: Count of completed orders in the last 30 days.")
    vendor_completion_rate_percent = models.FloatField(default=100.0, validators=[MinValueValidator(0.0), MaxValueValidator(100.0)], help_text="DENORMALIZED: Percentage of non-disputed/non-cancelled orders.")
    vendor_dispute_rate_percent = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(100.0)], help_text="DENORMALIZED: Percentage of orders that ended in dispute.")
    vendor_avg_rating = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(5.0)], help_text="DENORMALIZED: Calculated average overall feedback rating.")
    vendor_rating_count = models.PositiveIntegerField(default=0, help_text="DENORMALIZED: Total number of feedback ratings received.")
    vendor_reputation_last_updated = models.DateTimeField(null=True, blank=True, help_text="Timestamp when reputation metrics were last calculated.")
    # --- End Denormalized Fields ---

    # Withdrawal Addresses (Optional, must be validated)
    btc_withdrawal_address = models.CharField(max_length=95, blank=True, null=True, validators=[validate_bitcoin_address], help_text="Optional BTC address for receiving payouts.")
    eth_withdrawal_address = models.CharField(max_length=42, blank=True, null=True, validators=[validate_ethereum_address], help_text="Optional ETH address (checksummed) for receiving payouts.")
    xmr_withdrawal_address = models.CharField(max_length=106, blank=True, null=True, validators=[validate_monero_address], help_text="Optional XMR address for receiving payouts.")

    # Multi-Sig Contribution Fields
    btc_multisig_pubkey = models.CharField(max_length=66, null=True, blank=True, help_text="User's compressed public key (hex 02/03...) for BTC multi-sig participation.")
    xmr_multisig_info = models.TextField(null=True, blank=True, help_text="User's 'prepare_multisig' output hex string or similar data required for XMR multi-sig setup.")
    eth_multisig_owner_address = models.CharField(max_length=42, null=True, blank=True, validators=[validate_ethereum_address], help_text="User's designated Externally Owned Account (EOA) address for ETH Gnosis Safe participation.")

    objects = UserManager() # Use the custom manager

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS: List[str] = [] # PGP key is optional, so not in REQUIRED_FIELDS

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['username']
        indexes = [
            models.Index(fields=['is_vendor', 'is_active']),
            models.Index(fields=['is_active', 'date_joined']),
            models.Index(fields=['vendor_level_name']),
            models.Index(fields=['is_active', 'is_vendor', 'approved_vendor_since']),
        ]

    def __str__(self):
        return self.username

    def clean(self):
        """
        Custom validation for the User model.
        Ensures PGP key validity if one is provided.
        """
        super().clean()

        # Validate PGP key if provided (non-empty string)
        # The model field itself uses `validate_pgp_public_key` via validators=[...],
        # but calling it here ensures validation logic is centralized if called before model's full_clean.
        # This also aligns with how UserManager._validate_pgp works.
        if self.pgp_public_key and self.pgp_public_key.strip():
            try:
                validate_pgp_public_key(self.pgp_public_key)
            except ValidationError as e:
                # Conform to how model validation errors are typically raised in .clean()
                error_message = getattr(e, 'message', str(e))
                if isinstance(error_message, list): error_message = "; ".join(str(item) for item in error_message)
                elif not isinstance(error_message, str): error_message = str(error_message)
                raise ValidationError({'pgp_public_key': f"Invalid PGP Public Key provided: {error_message}"}) from e

        # Validate multi-sig contribution fields if provided
        if self.btc_multisig_pubkey:
            if not isinstance(self.btc_multisig_pubkey, str) or len(self.btc_multisig_pubkey) != 66 or not self.btc_multisig_pubkey.lower().startswith(('02', '03')):
                raise ValidationError({'btc_multisig_pubkey': "Invalid compressed Bitcoin public key format (must be 66 hex chars starting with 02 or 03)."})
            try: bytes.fromhex(self.btc_multisig_pubkey)
            except ValueError: raise ValidationError({'btc_multisig_pubkey': "Bitcoin public key must be a valid hex string."})
        if self.xmr_multisig_info:
            if not isinstance(self.xmr_multisig_info, str) or len(self.xmr_multisig_info) < 100: # Arbitrary minimum length check
                raise ValidationError({'xmr_multisig_info': "Monero multisig info appears too short or invalid."})
            try: bytes.fromhex(self.xmr_multisig_info)
            except ValueError: raise ValidationError({'xmr_multisig_info': "Monero multisig info must be a valid hex string."})

    def get_full_name(self):
        return self.username

    def get_short_name(self):
        return self.username

# --- Product Category ---
class Category(models.Model):
    """ Represents product categories, allowing a hierarchical structure. """
    id = models.BigAutoField(primary_key=True) # Standard PK
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, db_index=True, help_text="URL-friendly name. Usually set automatically from name.") # Added db_index=True
    description = models.TextField(blank=True, help_text="Optional description of the category.")
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='children',
        on_delete=models.SET_NULL, # Allow parent deletion without deleting children categories
        help_text="Optional parent category for creating hierarchies."
    )

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ['name']
        indexes = [
            # models.Index(fields=['slug']), # Redundant: slug is unique=True (which implies index)
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        return self.name

# --- Product ---
class Product(models.Model):
    """ Represents a product listing offered by a vendor. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT, # Prevent deleting vendor from deleting their products. Handle deactivation separately.
        related_name='products',
        limit_choices_to={'is_vendor': True}, # Ensure only vendors can be assigned
        help_text="The vendor offering this product."
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT, # Protect products if category is deleted. Requires admin action.
        related_name='products',
        help_text="The category this product belongs to."
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=255, unique=True, db_index=True, # unique=True implies db_index
        help_text="URL-friendly name. Usually set automatically from name."
    )
    description = models.TextField(help_text="Detailed description of the product. Sanitize before rendering if allowing HTML/Markdown.")

    # Pricing Fields
    price_xmr = models.DecimalField(max_digits=18, decimal_places=12, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Price in Monero (XMR).")
    price_btc = models.DecimalField(max_digits=14, decimal_places=8, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Price in Bitcoin (BTC).")
    price_eth = models.DecimalField(max_digits=24, decimal_places=18, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Price in Ethereum (ETH).")

    accepted_currencies = models.CharField(
        max_length=50,
        default=','.join(c.value for c in Currency),
        help_text=f"Comma-separated list of accepted currency codes (e.g., XMR,BTC,ETH)."
    )
    quantity = models.PositiveIntegerField(
        default=1, help_text="Available stock quantity. Use a very large number or specific logic for effectively unlimited stock (e.g., digital items)."
    )
    ships_from = models.CharField(max_length=100, blank=True, help_text="Origin Country or Region (e.g., 'USA', 'EU', 'Digital').")
    ships_to = models.TextField(blank=True, help_text="Comma-separated list of allowed destination countries/regions (e.g., 'USA,CAN,GB'). Blank implies worldwide or not applicable (digital).")
    shipping_options = models.JSONField(
        default=list, blank=True,
        help_text='List of shipping options as JSON array, e.g., [{"name": "Standard", "price_xmr": "0.01", ...}]'
    )

    # Status and Metadata
    is_active = models.BooleanField(default=True, db_index=True, help_text="Controls if the product is visible and purchasable.")
    is_featured = models.BooleanField(default=False, db_index=True, help_text="Mark as a featured product.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Denormalized Fields ---
    sales_count = models.PositiveIntegerField(default=0, help_text="DENORMALIZED: Count of successful sales.")
    average_rating = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(5.0)], help_text="DENORMALIZED: Average feedback rating for this product.")
    # --- End Denormalized Fields ---

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'is_active']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['is_active', 'price_xmr']),
            models.Index(fields=['is_active', 'price_btc']),
            models.Index(fields=['is_active', 'price_eth']),
            # models.Index(fields=['slug']), # Redundant: slug is unique=True
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        vendor_username = getattr(self.vendor, 'username', 'N/A') if self.vendor else 'N/A'
        return f"{self.name} by {vendor_username}"

    def get_accepted_currencies_list(self) -> List[str]:
        if not self.accepted_currencies: return []
        return [c.strip().upper() for c in self.accepted_currencies.split(',') if c.strip()]

    def get_price(self, currency: str) -> Optional[Decimal]:
        currency_upper = currency.upper()
        if currency_upper in self.get_accepted_currencies_list():
            price_field_name = f'price_{currency_upper.lower()}'
            return getattr(self, price_field_name, None)
        return None

    def is_physical(self) -> bool:
        # Simplified logic: physical if ships_from is set and not explicitly 'digital'
        # Assumes quantity > 0 is handled by purchase logic.
        return bool(self.ships_from) and self.ships_from.strip().lower() != 'digital'

    def clean(self):
        super().clean()
        accepted_currencies_list = self.get_accepted_currencies_list()
        if not accepted_currencies_list:
            raise ValidationError({'accepted_currencies': "Product must accept at least one currency."})

        valid_currency_codes = Currency.values
        for code in accepted_currencies_list:
            if code not in valid_currency_codes:
                raise ValidationError({'accepted_currencies': f"Invalid currency code '{code}' found."})

        has_at_least_one_price = False
        for currency_code in accepted_currencies_list:
            price = self.get_price(currency_code)
            if price is not None:
                # MinValueValidator handles negative check, but explicit check is fine too
                if price < 0: raise ValidationError({f'price_{currency_code.lower()}': "Price cannot be negative."})
                has_at_least_one_price = True
            else:
                # Check if price field exists but is None while currency is accepted
                price_field_name = f'price_{currency_code.lower()}'
                if getattr(self, price_field_name, 'missing') is None: # 'missing' is a sentinel if field doesn't exist
                    logger.warning(f"Product {self.id or 'NEW'}: Currency {currency_code} is accepted but its price field ({price_field_name}) is None.")


        # Check for consistency: if price field is set, currency must be accepted
        if self.price_xmr is not None and Currency.XMR.value not in accepted_currencies_list:
            raise ValidationError({'accepted_currencies': f"XMR price is set, but {Currency.XMR.value} not accepted."})
        if self.price_btc is not None and Currency.BTC.value not in accepted_currencies_list:
            raise ValidationError({'accepted_currencies': f"BTC price is set, but {Currency.BTC.value} not accepted."})
        if self.price_eth is not None and Currency.ETH.value not in accepted_currencies_list:
            raise ValidationError({'accepted_currencies': f"ETH price is set, but {Currency.ETH.value} not accepted."})

        # Active products must have a price defined for at least one accepted currency
        if self.is_active and not has_at_least_one_price:
            raise ValidationError("Active product must have a defined price for at least one accepted currency.")

        # Validate shipping options structure
        if self.shipping_options:
            if not isinstance(self.shipping_options, list):
                raise ValidationError({'shipping_options': "Shipping options must be a list (JSON array)."})
            for i, option in enumerate(self.shipping_options):
                if not isinstance(option, dict):
                    raise ValidationError({'shipping_options': f"Option at index {i} is not a valid JSON object."})
                if 'name' not in option or not isinstance(option['name'], str) or not option['name'].strip():
                    raise ValidationError({'shipping_options': f"Option at index {i} must have a non-empty 'name' string."})
                # Optionally validate price keys exist and are numeric strings/numbers

# --- Crypto Payment Tracking ---
class CryptoPayment(models.Model):
    """ Tracks the status of a cryptocurrency payment associated with an order. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField('Order', on_delete=models.PROTECT, related_name='payment', help_text="The order associated with this payment.")
    currency = models.CharField(max_length=3, choices=Currency.choices, db_index=True, help_text="The cryptocurrency used for this payment.")
    payment_address = models.CharField(max_length=200, unique=True, db_index=True, help_text="Deposit address generated for this specific payment.")
    payment_id_monero = models.CharField(max_length=16, blank=True, null=True, unique=True, db_index=True, help_text="DEPRECATED (usually): Legacy Short Payment ID for Monero.")
    # --- NEW FIELD: Add derivation index ---
    derivation_index = models.IntegerField(
        null=True, blank=True, db_index=True,
        help_text="[ETH HD Wallet] The derivation index (i in m/44'/60'/0'/0/i) used to generate this address."
    )
    # --- END NEW FIELD ---
    expected_amount_native = models.DecimalField(max_digits=36, decimal_places=0, validators=[MinValueValidator(Decimal('0'))], help_text="The exact amount expected in the smallest atomic unit (e.g., satoshis, piconeros, wei).")
    received_amount_native = models.DecimalField(max_digits=36, decimal_places=0, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))], help_text="The total amount received in the smallest atomic unit.")
    confirmations_needed = models.PositiveSmallIntegerField(default=10, validators=[MinValueValidator(0)], help_text="Number of blockchain confirmations required.")
    confirmations_received = models.PositiveSmallIntegerField(default=0, help_text="Number of confirmations detected.")
    transaction_hash = models.TextField(blank=True, null=True, db_index=True, help_text="Blockchain Transaction Hash(es). Comma-separate if multiple partial payments (consider separate model if complex).")
    block_height_received = models.PositiveIntegerField(blank=True, null=True, help_text="Block height at which payment was confirmed.")
    is_confirmed = models.BooleanField(default=False, db_index=True, help_text="True once required confirmations are met and amount is sufficient.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Crypto Payment"
        verbose_name_plural = "Crypto Payments"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['currency', 'is_confirmed', 'created_at']),
            # models.Index(fields=['transaction_hash']), # Indexing TextField can be inefficient; consider prefix index if needed or search differently. Kept commented.
            models.Index(fields=['is_confirmed', 'updated_at']),
            models.Index(fields=['order']), # Implied by OneToOneField? Check DB. Kept for clarity.
            # --- ADDED Index for derivation_index ---
            models.Index(fields=['currency', 'derivation_index']),
            # --- END ADDED Index ---
        ]

    def __str__(self):
        order_id_str = getattr(getattr(self, 'order', None), 'id', 'N/A')
        status = 'Confirmed' if self.is_confirmed else f'Pending ({self.confirmations_received}/{self.confirmations_needed})'
        addr_short = f"...{self.payment_address[-6:]}" if self.payment_address and len(self.payment_address) > 6 else self.payment_address
        index_info = f" Idx:{self.derivation_index}" if self.derivation_index is not None else ""
        return f"{self.currency}{index_info} Payment for Order {order_id_str} [{status}] Addr: {addr_short} Amt: {self.expected_amount_native}"

    def clean(self):
        super().clean()
        if self.currency != Currency.XMR and self.payment_id_monero:
            raise ValidationError({'payment_id_monero': "Monero Payment ID should only be used for legacy XMR payments."})
        # Validate payment address format based on currency
        try:
            if self.currency == Currency.XMR: validate_monero_address(self.payment_address)
            elif self.currency == Currency.BTC: validate_bitcoin_address(self.payment_address)
            elif self.currency == Currency.ETH: validate_ethereum_address(self.payment_address)
        except ValidationError as e: raise ValidationError({'payment_address': e.message}) from e
        # MinValueValidators handle negative checks, but explicit is okay too
        if self.expected_amount_native < 0: raise ValidationError({'expected_amount_native': "Expected amount cannot be negative."})
        if self.received_amount_native < 0: raise ValidationError({'received_amount_native': "Received amount cannot be negative."})

        # --- ADDED validation for derivation_index ---
        if self.currency != Currency.ETH and self.derivation_index is not None:
            raise ValidationError({'derivation_index': f"Derivation index should only be set for ETH payments, not {self.currency}."})
        # --- END ADDED validation ---

        # Logic checks (might belong in service layer depending on desired enforcement)
        if self.confirmations_received >= self.confirmations_needed and not self.is_confirmed:
                if self.received_amount_native >= self.expected_amount_native:
                    logger.warning(f"Payment {self.id}: Confs received >= needed and amount sufficient, but is_confirmed=False. Should be confirmed.")
                else:
                    logger.info(f"Payment {self.id}: Confs received >= needed but amount insufficient ({self.received_amount_native} < {self.expected_amount_native}), is_confirmed=False (Correct).")
        if self.is_confirmed and self.received_amount_native < self.expected_amount_native:
                logger.warning(f"Payment {self.id}: is_confirmed=True but received amount ({self.received_amount_native}) is less than expected ({self.expected_amount_native}). Potential issue.")

# --- Order ---
class Order(models.Model):
    """ Represents a purchase transaction between a buyer and a vendor. """

    # --- INNER CLASS for Status Choices ---
    class StatusChoices(models.TextChoices):
        """Status codes for the order lifecycle (used by status field)."""
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment' # CORRECT STATUS for initial state
        PAYMENT_CONFIRMED = 'payment_confirmed', 'Payment Confirmed / In Escrow'
        SHIPPED = 'shipped', 'Shipped'
        FINALIZED = 'finalized', 'Finalized'
        DISPUTED = 'disputed', 'Disputed'
        DISPUTE_RESOLVED = 'dispute_resolved', 'Dispute Resolved'
        CANCELLED_TIMEOUT = 'cancelled_timeout', 'Cancelled (Timeout)'
        CANCELLED_BUYER = 'cancelled_buyer', 'Cancelled (Buyer)'
        CANCELLED_VENDOR = 'cancelled_vendor', 'Cancelled (Vendor)'
        CANCELLED_UNDERPAID = 'cancelled_underpaid', 'Cancelled (Underpaid)'
        REFUNDED = 'refunded', 'Refunded'
    # --- End INNER CLASS ---

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_as_buyer', help_text="The user who placed the order.")
    vendor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_as_vendor', limit_choices_to={'is_vendor': True}, help_text="The vendor fulfilling the order.")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='orders', help_text="The product being purchased at the time of order.")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)], help_text="Quantity of the product ordered.")

    # Pricing and Currency (Captured at time of order)
    selected_currency = models.CharField(max_length=3, choices=Currency.choices, help_text="The cryptocurrency chosen by the buyer for payment.")
    price_native_selected = models.DecimalField(max_digits=36, decimal_places=0, validators=[MinValueValidator(Decimal('0'))], help_text="Product price per item in the smallest atomic unit of the selected currency at time of order.")
    shipping_price_native_selected = models.DecimalField(max_digits=36, decimal_places=0, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))], help_text="Shipping price in the smallest atomic unit of the selected currency.")
    total_price_native_selected = models.DecimalField(max_digits=36, decimal_places=0, validators=[MinValueValidator(Decimal('0'))], help_text="Calculated Total order price (product * quantity + shipping) in the smallest atomic unit.")

    # Order Status and Lifecycle
    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices, # Use inner class choices
        default=StatusChoices.PENDING_PAYMENT, # Use inner class default
        db_index=True,
        help_text="The current stage of the order."
    )
    selected_shipping_option = models.JSONField(blank=True, null=True, help_text='Details of the shipping option chosen by the buyer (snapshot from Product).')

    # Escrow Details
    escrow_type = models.CharField(max_length=10, choices=EscrowType.choices, default=EscrowType.MULTISIG, db_index=True, help_text="The type of escrow mechanism used for this order.")

    # --- NEW: Simple Escrow Field ---
    simple_escrow_deposit_address = models.CharField(
        max_length=255, # Max length for various address types
        null=True, blank=True,
        unique=True, # Ensure unique address per simple escrow order
        db_index=True,
        help_text="[Basic Escrow Only] Unique market-controlled deposit address generated for this order."
    )
    # --- End Simple Escrow Field ---

    # Multi-Sig Escrow Fields
    xmr_multisig_wallet_name = models.CharField(max_length=100, null=True, blank=True, unique=True, help_text="[Multisig Only] Unique identifier/name for the Monero multisig setup.")
    btc_redeem_script = models.TextField(null=True, blank=True, help_text="[Multisig Only] Hex-encoded Bitcoin P2WSH redeem script.")
    btc_escrow_address = models.CharField(max_length=95, null=True, blank=True, db_index=True, validators=[validate_bitcoin_address], help_text="[Multisig Only] Generated Bitcoin P2WSH address.")
    eth_multisig_owner_buyer = models.CharField(max_length=42, null=True, blank=True, validators=[validate_ethereum_address], help_text="[Multisig Only] Buyer's EOA owner address for the Safe.")
    eth_multisig_owner_vendor = models.CharField(max_length=42, null=True, blank=True, validators=[validate_ethereum_address], help_text="[Multisig Only] Vendor's EOA owner address for the Safe.")
    eth_multisig_owner_market = models.CharField(max_length=42, null=True, blank=True, validators=[validate_ethereum_address], help_text="[Multisig Only] Market's EOA signer/owner address for the Safe.")
    eth_escrow_contract_address = models.CharField(max_length=42, null=True, blank=True, db_index=True, validators=[validate_ethereum_address], help_text="[Multisig Only] Deployed address of the Gnosis Safe contract.")

    # Shipping and Communication
    encrypted_shipping_info = models.TextField(blank=True, null=True, help_text="[Physical Products Only] Buyer's shipping address, PGP encrypted for the vendor.")

    # Deadlines and Timeouts
    payment_deadline = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Time by which the payment must be initiated/confirmed.")
    auto_finalize_deadline = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Time after shipping when the order may be automatically finalized.")
    dispute_deadline = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Time after relevant event by which a dispute must be opened.")

    # Release Process Fields
    release_initiated = models.BooleanField(default=False, help_text="Flag indicating the funds release process has been started.")
    release_signature_buyer = models.TextField(blank=True, null=True, help_text="[Multisig] Buyer's signature contribution (e.g., signed PSBT partial, Monero txset).")
    release_signature_vendor = models.TextField(blank=True, null=True, help_text="[Multisig] Vendor's signature contribution (e.g., signed PSBT partial, Monero txset).")
    release_tx_broadcast_hash = models.CharField(max_length=256, blank=True, null=True, db_index=True, help_text="Transaction Hash of the final broadcasted release transaction (longer for some chains).") # Increased length
    release_metadata = models.JSONField(null=True, blank=True, help_text="Stores intermediate release transaction data (e.g., unsigned PSBT, Monero key images). Sensitive.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when payment was confirmed.")
    shipped_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when order was marked shipped.")
    finalized_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when order was finalized (funds released).")
    disputed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when dispute was opened.")

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['buyer', 'status']),
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['payment_deadline', 'status']),
            models.Index(fields=['auto_finalize_deadline', 'status']),
            models.Index(fields=['dispute_deadline', 'status']),
            models.Index(fields=['selected_currency', 'status']),
            models.Index(fields=['escrow_type', 'status']),
            models.Index(fields=['release_tx_broadcast_hash']),
            models.Index(fields=['simple_escrow_deposit_address']),
        ]

    def __str__(self):
        product_name = getattr(self.product, 'name', 'N/A') if self.product else 'N/A'
        return f"Order {self.id} ({product_name}) - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.buyer_id and self.buyer_id == self.vendor_id:
            raise ValidationError("Buyer cannot be the same as the vendor.")
        if self.quantity < 1:
            raise ValidationError({'quantity': "Order quantity must be at least 1."})

        if self.product_id and self.selected_currency:
            try:
                product_instance = self.product if hasattr(self, '_product_cache') else Product.objects.get(pk=self.product_id)
                accepted_currencies_list = product_instance.get_accepted_currencies_list()
                if self.selected_currency not in accepted_currencies_list:
                    raise ValidationError({'selected_currency': f"Selected currency '{self.selected_currency}' not accepted by product '{product_instance.name}'."})
                if product_instance.get_price(self.selected_currency) is None:
                    raise ValidationError({'selected_currency': f"Product '{product_instance.name}' has no defined price for the selected currency '{self.selected_currency}'."})
            except Product.DoesNotExist:
                raise ValidationError({'product': f"Selected product (ID: {self.product_id}) does not exist."})

        is_multisig = self.escrow_type == EscrowType.MULTISIG
        is_basic = self.escrow_type == EscrowType.BASIC

        multisig_fields_present = any([
            self.xmr_multisig_wallet_name, self.btc_redeem_script, self.btc_escrow_address,
            self.eth_multisig_owner_buyer, self.eth_multisig_owner_vendor,
            self.eth_multisig_owner_market, self.eth_escrow_contract_address,
            self.release_signature_buyer, self.release_signature_vendor
        ])

        if is_basic:
            if multisig_fields_present:
                raise ValidationError("Multi-signature specific fields (e.g., btc_redeem_script, xmr_multisig_wallet_name, release_signatures) must be empty for Basic Escrow.")
            if not self.simple_escrow_deposit_address:
                logger.warning(f"Order {self.id or 'NEW'} is Basic Escrow but 'simple_escrow_deposit_address' is not yet set.")
            if self.simple_escrow_deposit_address and self.selected_currency:
                try:
                    if self.selected_currency == Currency.XMR: validate_monero_address(self.simple_escrow_deposit_address)
                    elif self.selected_currency == Currency.BTC: validate_bitcoin_address(self.simple_escrow_deposit_address)
                    elif self.selected_currency == Currency.ETH: validate_ethereum_address(self.simple_escrow_deposit_address)
                except ValidationError as e: raise ValidationError({'simple_escrow_deposit_address': e.message}) from e
        elif is_multisig:
            if self.simple_escrow_deposit_address:
                raise ValidationError("'simple_escrow_deposit_address' must be empty for Multi-Signature Escrow.")
        else:
            raise ValidationError(f"Invalid escrow_type: {self.escrow_type}")

        if self.price_native_selected is not None and self.quantity is not None and self.shipping_price_native_selected is not None:
            calculated_total = self.calculate_total_price_native()
            if calculated_total < 0: raise ValidationError("Calculated total order price cannot be negative.")
            if self.total_price_native_selected is not None and self.total_price_native_selected != calculated_total:
                logger.warning(f"Order {self.id or 'NEW'}: Stored total price ({self.total_price_native_selected}) differs from calculation based on current price/qty/shipping ({calculated_total}). Will be updated on save.")

    def calculate_total_price_native(self) -> Decimal:
        """Calculates total price in native atomic units based on current fields."""
        product_price = self.price_native_selected if self.price_native_selected is not None else Decimal(0)
        shipping_price = self.shipping_price_native_selected if self.shipping_price_native_selected is not None else Decimal(0)
        order_quantity = self.quantity if self.quantity is not None else 0

        if product_price < 0 or shipping_price < 0 or order_quantity < 0:
            logger.error(f"Order {self.id or 'NEW'} calculate_total_price_native encountered negative inputs: price={product_price}, shipping={shipping_price}, qty={order_quantity}")
            return Decimal(0)

        product_total = product_price * order_quantity
        return product_total + shipping_price

    def save(self, *args, **kwargs):
        """
        Overrides save method to ensure total_price_native_selected is correctly
        calculated and set before saving.
        """
        # Ensure dependent fields are populated or default appropriately for calculation
        if self.price_native_selected is not None and \
           self.quantity is not None and \
           self.shipping_price_native_selected is not None:
            self.total_price_native_selected = self.calculate_total_price_native()
        elif self.total_price_native_selected is None: # Only set to 0 if not already set by some other logic and components are missing
            self.total_price_native_selected = Decimal('0')
            logger.warning(
                f"Order {self.id or 'NEW'}: One or more base price components (product price, quantity, or shipping price) "
                f"are None. Total price defaulted to 0. Review order creation logic. "
                f"Product Price: {self.price_native_selected}, Qty: {self.quantity}, Ship Price: {self.shipping_price_native_selected}"
            )
        # If total_price_native_selected was already set (e.g., by a serializer),
        # and the components are missing, we trust the pre-set total for now,
        # but clean() should have warned if there was a discrepancy.

        super().save(*args, **kwargs)

# --- DEFINE CONSTANT FOR EXTERNAL USE (Order Status) ---
ORDER_STATUS_CHOICES = Order.StatusChoices.choices
# --- END CONSTANT DEFINITION ---


# --- Feedback (with Granular Ratings) ---
class Feedback(models.Model):
    """ Stores buyer feedback for a completed order, including optional granular ratings. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='feedback', help_text="The order this feedback relates to.")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reviews_given', help_text="The user (buyer) who left the feedback.")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reviews_received', limit_choices_to={'is_vendor': True}, help_text="The user (vendor) who received the feedback.")

    # Overall Rating and Comment
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], help_text="Overall satisfaction rating (1-5 stars).")
    comment = models.TextField(blank=True, help_text="Optional public comment about the transaction.")
    feedback_type = models.CharField(max_length=10, choices=FeedbackType.choices, editable=False, db_index=True, help_text="Overall sentiment derived from the rating.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Granular Rating Fields (Optional)
    rating_quality = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True, help_text="Optional: Rating specifically for product quality (1-5).")
    rating_shipping = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True, help_text="Optional: Rating specifically for shipping speed/packaging (1-5).")
    rating_communication = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True, help_text="Optional: Rating specifically for vendor communication (1-5).")

    class Meta:
        verbose_name = "Feedback"
        verbose_name_plural = "Feedback"
        ordering = ['-created_at']
        unique_together = ('order', 'reviewer') # Ensures one feedback per order from the buyer
        indexes = [
            models.Index(fields=['recipient', 'created_at']),
            models.Index(fields=['reviewer', 'created_at']),
            models.Index(fields=['recipient', 'rating']),
            models.Index(fields=['feedback_type', 'recipient']),
        ]

    def __str__(self):
        order_id_str = getattr(self.order, 'id', 'N/A') if self.order else 'N/A'
        return f"Feedback for Order {order_id_str} ({self.rating}/5 stars)"

    def save(self, *args, **kwargs):
        """Sets feedback_type based on rating and populates reviewer/recipient if missing."""
        if self.rating >= 4: self.feedback_type = FeedbackType.POSITIVE
        elif self.rating == 3: self.feedback_type = FeedbackType.NEUTRAL
        else: self.feedback_type = FeedbackType.NEGATIVE

        if self.order_id and (not self.reviewer_id or not self.recipient_id):
            try:
                order_instance = Order.objects.select_related('buyer', 'vendor').get(pk=self.order_id)
                if not self.reviewer_id: self.reviewer = order_instance.buyer
                if not self.recipient_id: self.recipient = order_instance.vendor
            except Order.DoesNotExist:
                logger.error(f"Feedback save failed: Cannot populate reviewer/recipient as Order ID {self.order_id} not found.")
        elif not self.order_id and (not self.reviewer_id or not self.recipient_id):
            raise ValidationError("Feedback must be associated with an order OR have both reviewer and recipient explicitly set.")
        super().save(*args, **kwargs)

    def clean(self):
        """Validates feedback constraints."""
        super().clean()
        order_instance = None
        if self.order_id:
            try:
                order_instance = Order.objects.select_related('buyer', 'vendor').get(pk=self.order_id)
            except Order.DoesNotExist:
                raise ValidationError({'order': 'Associated order does not exist.'})

        if order_instance and self.reviewer_id and self.reviewer_id != order_instance.buyer_id:
            raise ValidationError("Feedback reviewer must be the buyer of the associated order.")
        elif self.reviewer and not isinstance(self.reviewer, settings.AUTH_USER_MODEL):
            pass

        if order_instance and self.recipient_id and self.recipient_id != order_instance.vendor_id:
            raise ValidationError("Feedback recipient must be the vendor of the associated order.")
        elif self.recipient and (not hasattr(self.recipient, 'is_vendor') or not self.recipient.is_vendor):
            raise ValidationError("Feedback recipient must be a valid vendor user.")

        if order_instance:
            allowed_statuses_for_feedback = [
                Order.StatusChoices.FINALIZED,
                Order.StatusChoices.DISPUTE_RESOLVED
            ]
            if order_instance.status not in allowed_statuses_for_feedback:
                logger.info(f"Validation check: Feedback attempted for order {self.order_id} status '{order_instance.status}'. Allowed: {allowed_statuses_for_feedback}")
                raise ValidationError(f"Feedback can only be submitted for orders that are Finalized or have a Dispute Resolved (current status: {order_instance.get_status_display()}).")

# --- NEW: Dispute Model ---
class Dispute(models.Model):
    """ Represents a dispute opened for an order. """

    class StatusChoices(models.TextChoices):
        OPEN = 'open', _('Open')
        UNDER_REVIEW = 'under_review', _('Under Review')
        RESOLVED = 'resolved', _('Resolved')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='dispute',
        help_text=_("The order being disputed.")
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='disputes_opened',
        help_text=_("The user (usually buyer) who opened the dispute.")
    )
    reason = models.TextField(
        help_text=_("Reason provided by the requester for opening the dispute.")
    )
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.OPEN,
        db_index=True,
        help_text=_("The current status of the dispute.")
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='disputes_resolved',
        limit_choices_to={'is_staff': True},
        help_text=_("The staff member who resolved the dispute.")
    )
    resolution_notes = models.TextField(
        blank=True, null=True,
        help_text=_("Notes explaining the resolution decision.")
    )
    resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text=_("Timestamp when the dispute was resolved.")
    )
    buyer_percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.0')), MaxValueValidator(Decimal('100.0'))],
        help_text=_("Percentage of escrow released to buyer as part of resolution (0-100).")
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Dispute')
        verbose_name_plural = _('Disputes')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['requester', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['resolved_by']),
        ]

    def __str__(self):
        order_id_str = getattr(self.order, 'id', 'N/A') if self.order else 'N/A'
        return f"Dispute for Order {order_id_str} [{self.get_status_display()}]"

    def clean(self):
        super().clean()
        if self.order_id and self.requester_id:
            order_buyer_id = Order.objects.filter(pk=self.order_id).values_list('buyer_id', flat=True).first()
            if order_buyer_id and self.requester_id != order_buyer_id:
                logger.warning(f"Dispute {self.id} opened by user {self.requester_id}, but order buyer is {order_buyer_id}.")

# --- Support Ticket / Encrypted Message System ---
class SupportTicket(models.Model):
    """ Represents a support request or dispute communication thread. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.CharField(max_length=255)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='support_tickets', help_text="The user who initiated the ticket.")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_tickets', limit_choices_to={'is_staff': True}, help_text="The staff member currently assigned.")
    related_order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name='support_tickets', help_text="Optional: The order this ticket is related to.")
    status = models.CharField(max_length=20, choices=SupportTicketStatus.choices, default=SupportTicketStatus.OPEN, db_index=True, help_text="Current status of the support ticket.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = "Support Ticket"
        verbose_name_plural = "Support Tickets"
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['requester', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['related_order']),
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        requester_name = getattr(self.requester, 'username', 'Deleted User')
        return f"Ticket {self.id} by {requester_name}: {self.subject} [{self.get_status_display()}]"


class TicketMessage(models.Model):
    """ An individual message within a support ticket thread, content is PGP encrypted. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages', help_text="The support ticket this message belongs to.")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='sent_ticket_messages', help_text="The user who sent this message.")
    encrypted_body = models.TextField(help_text="Message content, PGP encrypted for the intended recipient(s). Requires application-level logic for encryption/decryption.")
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_read = models.BooleanField(default=False, help_text="Basic flag indicating if the message has been viewed by the recipient (requires application logic to set).")

    class Meta:
        verbose_name = "Ticket Message"
        verbose_name_plural = "Ticket Messages"
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['ticket', 'sent_at']),
            models.Index(fields=['sender']),
            models.Index(fields=['ticket', 'is_read', 'sent_at']),
        ]

    def __str__(self):
        sender_name = getattr(self.sender, 'username', 'Deleted User')
        ticket_id_str = getattr(self.ticket, 'id', 'N/A') if self.ticket else 'N/A'
        return f"Message by {sender_name} on Ticket {ticket_id_str} at {self.sent_at.strftime('%Y-%m-%d %H:%M')}"


# --- Audit Log ---
class AuditLog(models.Model):
    """ Records significant actions performed by staff or the system for accountability. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions_performed', help_text="The staff user who performed the action, or null if system initiated.")
    action = models.CharField(max_length=30, choices=AuditLogAction.choices, db_index=True, help_text="The type of action performed.")
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions_received', help_text="Optional: The user who was the target of the action.")
    target_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_log_entries', help_text="Optional: The order related to the action.")
    details = models.TextField(blank=True, help_text="Additional details about the action, context, or reasons (e.g., ban reason, changed fields).")
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="IP address from which the action originated, if available/logged.")

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['actor', 'timestamp']),
            models.Index(fields=['target_user', 'timestamp']),
            models.Index(fields=['target_order', 'timestamp']),
            models.Index(fields=['ip_address']),
        ]

    def __str__(self):
        actor_name = getattr(self.actor, 'username', 'System') if self.actor else 'System'
        action_display = self.get_action_display()
        target_info = ""
        if self.target_user: target_info += f" TargetUser: {getattr(self.target_user, 'username', 'Deleted')}"
        if self.target_order: target_info += f" TargetOrder: {self.target_order_id}"
        ts_local = timezone.localtime(self.timestamp)
        ts_str = ts_local.strftime('%Y-%m-%d %H:%M:%S %Z') if ts_local else 'No Timestamp'
        return f"{ts_str} | {actor_name} | {action_display}{target_info}"


# --- WebAuthn Credential Model ---
class WebAuthnCredential(models.Model):
    """ Stores a user's registered WebAuthn/FIDO2 credential data for passwordless/2FA login. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='webauthn_credentials', help_text="The user associated with this WebAuthn credential.")
    credential_id_b64 = models.TextField(unique=True, help_text="Base64URL-encoded credential ID provided by the authenticator.")
    public_key_b64 = models.TextField(help_text="Base64URL-encoded COSE public key associated with the credential.")
    sign_count = models.PositiveIntegerField(default=0, help_text="Signature counter provided by the authenticator. MUST be validated during authentication.")
    transports = models.CharField(max_length=255, blank=True, null=True, help_text="Optional: Comma-separated list of transport methods reported (e.g., usb, nfc, ble, internal).")
    nickname = models.CharField(max_length=100, blank=True, null=True, help_text="User-defined friendly name for this credential (e.g., 'Yubikey', 'Phone').")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when this credential was registered.")
    last_used_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Timestamp when this credential was last successfully used.")

    class Meta:
        verbose_name = "WebAuthn Credential"
        verbose_name_plural = "WebAuthn Credentials"
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['last_used_at']),
        ]
        ordering = ['user', '-created_at']

    def __str__(self):
        user_repr = self.user.username if hasattr(self.user, 'username') else f"User ID {self.user_id}"
        nickname_part = f" ({self.nickname})" if self.nickname else ""
        cred_id_str = str(self.credential_id_b64) if self.credential_id_b64 else ""
        cred_id_short = (cred_id_str[:10] + "...") if len(cred_id_str) > 13 else cred_id_str
        return f"WebAuthn Credential for {user_repr}{nickname_part} (ID: {cred_id_short})"


# --- NEW: Vendor Application Model ---
class VendorApplication(models.Model):
    """Tracks the process for a user applying to become a vendor and paying the bond."""

    class StatusChoices(models.TextChoices):
        PENDING_BOND = 'pending_bond', _('Pending Bond Payment')
        PENDING_REVIEW = 'pending_review', _('Pending Review')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        CANCELLED = 'cancelled', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_application',
        help_text=_("The user applying to become a vendor.")
    )
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING_BOND,
        db_index=True,
        help_text=_("The current status of the vendor application.")
    )
    bond_currency = models.CharField(
        max_length=10,
        choices=Currency.choices,
        help_text=_("The cryptocurrency chosen for the bond payment.")
    )
    bond_amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1500.00'),
        validators=[MinValueValidator(Decimal('0.0'))],
        help_text=_("Required bond amount in USD equivalent at time of application.")
    )
    bond_amount_crypto = models.DecimalField(
        max_digits=24,
        decimal_places=18,
        validators=[MinValueValidator(Decimal('0.0'))],
        help_text=_("Required bond amount calculated in the chosen cryptocurrency.")
    )
    bond_payment_address = models.CharField(
        max_length=255,
        unique=True,
        blank=True, null=True,
        db_index=True,
        help_text=_("The unique cryptocurrency address generated for this bond payment.")
    )
    received_amount_crypto_atomic = models.DecimalField(
        max_digits=36,
        decimal_places=0,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text=_("Total amount received for the bond in the smallest atomic unit of the chosen currency.")
    )
    payment_txids = models.JSONField(
        default=list,
        blank=True,
        help_text=_("List of transaction IDs contributing to the bond payment.")
    )
    rejection_reason = models.TextField(
        blank=True,
        null=True,
        help_text=_("Reason provided by admin if the application is rejected.")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Vendor Application')
        verbose_name_plural = _('Vendor Applications')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['bond_currency', 'status']),
            models.Index(fields=['bond_payment_address']),
        ]

    def __str__(self):
        user_repr = self.user.username if hasattr(self.user, 'username') else f"User ID {self.user_id}"
        return f"Vendor Application for {user_repr} [{self.get_status_display()}]"

    def clean(self):
        super().clean()
        if self.user_id:
            user_instance = getattr(self, 'user', None) or User.objects.filter(pk=self.user_id).first()
            if user_instance and user_instance.is_vendor:
                raise ValidationError(_("This user is already a vendor."))
        if self.bond_amount_crypto is not None and self.bond_amount_crypto <= 0:
            raise ValidationError({'bond_amount_crypto': _("Calculated bond amount must be positive.")})
        if self.received_amount_crypto_atomic is not None and self.received_amount_crypto_atomic < 0:
            raise ValidationError({'received_amount_crypto_atomic': _("Received amount cannot be negative.")})
        if self.bond_payment_address and self.bond_currency:
            try:
                if self.bond_currency == Currency.XMR: validate_monero_address(self.bond_payment_address)
                elif self.bond_currency == Currency.BTC: validate_bitcoin_address(self.bond_payment_address)
                elif self.bond_currency == Currency.ETH: validate_ethereum_address(self.bond_payment_address)
            except ValidationError as e: raise ValidationError({'bond_payment_address': e.message}) from e

# --- DEFINE CONSTANTS FOR EXTERNAL USE (Vendor App Status) ---
VENDOR_APP_STATUS_PENDING_BOND = VendorApplication.StatusChoices.PENDING_BOND.value
VENDOR_APP_STATUS_PENDING_REVIEW = VendorApplication.StatusChoices.PENDING_REVIEW.value
VENDOR_APP_STATUS_APPROVED = VendorApplication.StatusChoices.APPROVED.value
VENDOR_APP_STATUS_REJECTED = VendorApplication.StatusChoices.REJECTED.value
VENDOR_APP_STATUS_CANCELLED = VendorApplication.StatusChoices.CANCELLED.value
VENDOR_APP_STATUS_CHOICES = VendorApplication.StatusChoices.choices
# --- END CONSTANT DEFINITION ---

# --- END OF FILE ---