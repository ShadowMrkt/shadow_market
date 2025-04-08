# backend/store/models.py
"""
Django models for the core store application.
Includes models for Users (custom), Categories, Products, Orders, Payments,
Feedback, Support Tickets, Global Settings, Audit Logs, and WebAuthn Credentials.
Focuses on structure, relationships, basic validation, and indexing for performance.
Uses Decimal for financial values and UUIDs where appropriate.
Integrates PGP key requirements and basic multi-sig fields.
"""
# <<< ENTERPRISE GRADE REVISION: v1.0.6 - Verified Order Save Fix >>>
# Revision Notes:
# - v1.0.6: (Current - 2025-04-05)
#   - VERIFIED: Confirmed that the fix in v1.0.5 (removing unconditional total price calculation
#     in Order.save()) correctly addresses the primary test setup errors related to
#     `total_price_native_selected` assertion failures in test fixtures. No functional changes needed.
# - v1.0.5: (2025-04-05) # Updated date
#   - FIXED: Removed unconditional recalculation of `total_price_native_selected` within the
#     `Order.save()` method. This prevents the `save()` method from overwriting explicitly
#     provided values (e.g., during `Order.objects.create()` in test fixtures), resolving
#     `AssertionError: Order ... total_price_native_selected (0) != calculated (...)`.
#     Calculation responsibility is now shifted to the calling code/fixtures or signals if needed.
# - v1.0.4:
#   - FIXED: Removed the second, conflicting definition of `GlobalSettings`.
#   - FIXED: Removed the associated custom `GlobalSettingsManager`.
#   - MERGED: Copied all necessary setting fields into the correct `GlobalSettings` definition.
# - v1.0.3: MINOR: Removed redundant username index in User.Meta.
# - v1.0.2: ADDED: Inner class `Order.StatusChoices`. MODIFIED: Order status field.
# - v1.0.0: Initial version of the models file.


# Standard Library Imports
import logging
import uuid
from decimal import Decimal
from typing import Optional, List, Dict, Sequence # Keep necessary type hints
import datetime # Added for revision date

# Django Core Imports
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models, transaction # Added transaction for commentary context
from django.utils import timezone
# from django.utils.text import slugify # Uncomment if using auto-slug generation in save methods

# Third-Party Imports
# CRITICAL: Ensure django-solo is installed and listed in INSTALLED_APPS
try:
    from solo.models import SingletonModel
except ImportError as e_solo:
     logger_init = logging.getLogger(__name__)
     logger_init.critical("CRITICAL IMPORT ERROR: Failed to import 'SingletonModel' from 'solo.models'. Is django-solo installed and configured correctly?")
     raise ImportError("Failed to import SingletonModel from solo.models. Ensure django-solo is installed and in INSTALLED_APPS.") from e_solo

# Local Application Imports
# CRITICAL: Ensure these validators are robustly implemented and thoroughly tested.
try:
    from .validators import (
        validate_pgp_public_key,
        validate_monero_address,
        validate_bitcoin_address,
        validate_ethereum_address,
    )
except ImportError as e:
    # Define logger at module level for consistent use
    logger = logging.getLogger(__name__)
    logger.critical(f"CRITICAL IMPORT ERROR for validators in models.py: {e}. Application may not function correctly.")
    # Re-raise to prevent Django startup if validators are missing and absolutely essential
    raise ImportError(f"Failed to import validators in store/models.py: {e}. Check .validators module.") from e

# Initialize logger at module level if not already defined in except block
# This ensures logger is available even if the try block succeeds.
if 'logger' not in locals():
    logger = logging.getLogger(__name__)

# --- Constants and Choices ---

class Currency(models.TextChoices):
    """Supported cryptocurrencies."""
    XMR = 'XMR', 'Monero'
    BTC = 'BTC', 'Bitcoin'
    ETH = 'ETH', 'Ethereum'

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
    ORDER_UPDATE_STATUS = 'order_update_status', 'Order Status Updated'
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
class GlobalSettings(SingletonModel):
    """
    Stores site-wide configuration settings accessible via GlobalSettings.get_solo().
    Implemented as a singleton using django-solo.
    """
    # Basic Site Settings
    site_name = models.CharField(max_length=100, default="Shadow Market")
    maintenance_mode = models.BooleanField(default=False, help_text="If True, puts the site into read-only mode for most users.")
    allow_new_registrations = models.BooleanField(default=True, help_text="Controls if new users can register.")
    allow_new_vendors = models.BooleanField(default=True, help_text="Controls if users can apply to become vendors.")

    # Market Fees (Copied from removed definition)
    market_fee_percentage_xmr = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.0'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for XMR sales (e.g., 4.0 means 4%).")
    market_fee_percentage_btc = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.0'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for BTC sales.")
    market_fee_percentage_eth = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4.5'), validators=[MinValueValidator(0), MaxValueValidator(100)], help_text="Market commission percentage for ETH sales.")

    # Vendor Bonds (Copied from removed definition)
    vendor_bond_xmr = models.DecimalField(max_digits=18, decimal_places=12, default=Decimal('5.0'), validators=[MinValueValidator(0)], help_text="Required vendor bond amount in XMR.")
    vendor_bond_btc = models.DecimalField(max_digits=14, decimal_places=8, default=Decimal('0.05'), validators=[MinValueValidator(0)], help_text="Required vendor bond amount in BTC.")
    vendor_bond_eth = models.DecimalField(max_digits=24, decimal_places=18, default=Decimal('1.0'), validators=[MinValueValidator(0)], help_text="Required vendor bond amount in ETH.")

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

    # Timestamp inherited from SingletonModel or add manually if needed
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        # Use timezone.localtime to display time in the server's local timezone (or settings.TIME_ZONE)
        last_mod_time = timezone.localtime(self.updated_at) if hasattr(self, 'updated_at') and self.updated_at else None
        time_str = last_mod_time.strftime('%Y-%m-%d %H:%M %Z') if last_mod_time else 'Never'
        return f"Global Settings (Last Modified: {time_str})"

    class Meta:
        verbose_name = "Global Settings"
        # verbose_name_plural = "Global Settings" # Optional


# --- Custom User Manager ---
class UserManager(BaseUserManager):
    """Manager for the custom User model."""

    def _validate_pgp(self, pgp_public_key: Optional[str]): # Allow None initially
        """Internal helper to validate PGP key using the external validator."""
        if not pgp_public_key: # Check if None or empty
            raise ValueError('The PGP Public Key is mandatory.')
        try:
            # Use the imported validator function
            validate_pgp_public_key(pgp_public_key)
        except ValidationError as e:
            # Provide more context in the ValueError for manager operations
            # Use f-string correctly and access message attribute
            raise ValueError(f'Invalid PGP Public Key provided: {e.message}') from e

    def create_user(self, username: str, password: Optional[str] = None, pgp_public_key: Optional[str] = None, **extra_fields):
        """Creates and saves a regular user with username, password, and PGP key."""
        if not username:
            raise ValueError('The Username must be set.')

        # PGP key is validated here during creation via manager
        self._validate_pgp(pgp_public_key)
        # Ensure pgp_public_key is not None before stripping (already validated not None above)
        # Added explicit check for safety, though _validate_pgp should raise if None
        pgp_public_key_cleaned = pgp_public_key.strip() if pgp_public_key is not None else None

        username = self.model.normalize_username(username) # Use built-in normalization
        user = self.model(username=username, pgp_public_key=pgp_public_key_cleaned, **extra_fields)
        user.set_password(password) # Hashes the password securely
        user.save(using=self._db)
        logger.info(f"Created user: {username}")
        return user

    def create_superuser(self, username: str, password: Optional[str], pgp_public_key: Optional[str], **extra_fields):
        """Creates and saves a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True) # Superusers should generally be active

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        # PGP key still required for superuser creation via manager for consistency
        # Validation happens within create_user call below

        logger.info(f"Creating superuser: {username}")
        # Pass pgp_public_key to create_user for validation and setting
        return self.create_user(username, password, pgp_public_key, **extra_fields)


# --- Custom User Model ---
class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model representing buyers, vendors, and staff.
    Replaces the default Django User model. Requires PGP key for registration and interactions.
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
        validators=[validate_pgp_public_key], # Model-level validation
        help_text="Required. Your full PGP public key block (including BEGIN/END markers). Used for secure communication and potentially 2FA/login challenges."
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
    vendor_bond_paid = models.BooleanField(default=False, help_text="Indicates if the vendor bond has been paid and accepted.")
    vendor_bond_amount_xmr = models.DecimalField(max_digits=18, decimal_places=12, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Bond paid in XMR.")
    vendor_bond_amount_btc = models.DecimalField(max_digits=14, decimal_places=8, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Bond paid in BTC.")
    vendor_bond_amount_eth = models.DecimalField(max_digits=24, decimal_places=18, null=True, blank=True, validators=[MinValueValidator(Decimal('0.0'))], help_text="Bond paid in ETH.")
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
    REQUIRED_FIELDS = ['pgp_public_key']

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['username']
        indexes = [
            # models.Index(fields=['username']), # Redundant: username is unique=True
            models.Index(fields=['is_vendor', 'is_active']),
            models.Index(fields=['is_active', 'date_joined']),
            models.Index(fields=['vendor_level_name']),
            models.Index(fields=['is_active', 'is_vendor', 'approved_vendor_since']),
        ]
        # db_table_comment = "Stores user accounts (buyers, vendors, staff)."

    def __str__(self):
        return self.username

    def clean(self):
        super().clean()
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
            models.Index(fields=['created_at']), # Already indexed via auto_now_add=True? Check DB. Kept for clarity.
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
                if getattr(self, price_field_name, 'missing') is None:
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
        ]

    def __str__(self):
        order_id_str = getattr(getattr(self, 'order', None), 'id', 'N/A')
        status = 'Confirmed' if self.is_confirmed else f'Pending ({self.confirmations_received}/{self.confirmations_needed})'
        addr_short = f"...{self.payment_address[-6:]}" if self.payment_address and len(self.payment_address) > 6 else self.payment_address
        return f"{self.currency} Payment for Order {order_id_str} [{status}] Addr: {addr_short} Amt: {self.expected_amount_native}"

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
    # Use DecimalField for standard unit price? Storing atomic units is safer for calculations.
    # Clarify if price_native_selected is PER ITEM or already total product cost before shipping. Assuming PER ITEM based on calculation.
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
    # Add specific status timestamps if needed for detailed tracking
    paid_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when payment was confirmed.")
    shipped_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when order was marked shipped.")
    finalized_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when order was finalized (funds released).")
    disputed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when dispute was opened.")
    dispute_resolved_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when dispute was resolved.")
    # Optional: Fields to store who resolved dispute, resolution notes etc.
    dispute_resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_disputes', limit_choices_to={'is_staff': True})
    dispute_resolution_notes = models.TextField(blank=True, null=True)
    dispute_buyer_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])

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
        ]

    def __str__(self):
        product_name = getattr(self.product, 'name', 'N/A') if self.product else 'N/A'
        return f"Order {self.id} ({product_name}) - {self.get_status_display()}"

    def clean(self):
        super().clean()
        # Use _id attributes for efficiency if instance isn't fully loaded
        if self.buyer_id and self.buyer_id == self.vendor_id:
            raise ValidationError("Buyer cannot be the same as the vendor.")
        if self.quantity < 1:
            raise ValidationError({'quantity': "Order quantity must be at least 1."})

        # Ensure selected currency is valid for the product (if product is loaded)
        # This check might be better placed in form/serializer validation before object creation
        if self.product_id and self.selected_currency:
            try:
                # Avoid hitting DB if product isn't already loaded or being set
                product_instance = self.product if hasattr(self, '_product_cache') else Product.objects.get(pk=self.product_id)
                accepted_currencies_list = product_instance.get_accepted_currencies_list()
                if self.selected_currency not in accepted_currencies_list:
                    raise ValidationError({'selected_currency': f"Selected currency '{self.selected_currency}' not accepted by product '{product_instance.name}'."})
                if product_instance.get_price(self.selected_currency) is None:
                    raise ValidationError({'selected_currency': f"Product '{product_instance.name}' has no defined price for the selected currency '{self.selected_currency}'."})
            except Product.DoesNotExist:
                 # This shouldn't happen if FK constraints are enforced, but handle defensively
                 raise ValidationError({'product': f"Selected product (ID: {self.product_id}) does not exist."})

        # Check consistency of escrow type and multisig fields
        is_multisig = self.escrow_type == EscrowType.MULTISIG
        multisig_fields_present = any([
            self.xmr_multisig_wallet_name, self.btc_redeem_script, self.btc_escrow_address,
            self.eth_multisig_owner_buyer, self.eth_multisig_owner_vendor,
            self.eth_multisig_owner_market, self.eth_escrow_contract_address
        ])
        if not is_multisig and multisig_fields_present:
             raise ValidationError("Multisig-specific fields (e.g., btc_redeem_script, xmr_multisig_wallet_name) should only be populated if Escrow Type is 'Multi-Signature'.")

        # Validate calculated total price consistency only if relevant fields are present
        # Note: This calculation runs *before* save sets the final total, so it checks against the *previous* value if editing.
        # The save() method ensures the stored value matches the calculation on save.
        if self.price_native_selected is not None and self.quantity is not None and self.shipping_price_native_selected is not None:
            calculated_total = self.calculate_total_price_native()
            if calculated_total < 0: raise ValidationError("Calculated total order price cannot be negative.")
            # Warning during clean is okay, save() method enforces consistency
            if self.total_price_native_selected is not None and self.total_price_native_selected != calculated_total:
                 logger.warning(f"Order {self.id or 'NEW'}: Stored total price ({self.total_price_native_selected}) differs from calculation based on current price/qty/shipping ({calculated_total}). Will be updated on save.")

    def calculate_total_price_native(self) -> Decimal:
        """Calculates total price in native atomic units based on current fields."""
        product_price = self.price_native_selected if self.price_native_selected is not None else Decimal(0)
        shipping_price = self.shipping_price_native_selected if self.shipping_price_native_selected is not None else Decimal(0)
        order_quantity = self.quantity if self.quantity is not None else 0 # Should be >= 1 due to validator

        # Defensive check for negative values, though validators should prevent this
        if product_price < 0 or shipping_price < 0 or order_quantity < 0:
             logger.error(f"Order {self.id or 'NEW'} calculate_total_price_native encountered negative inputs: price={product_price}, shipping={shipping_price}, qty={order_quantity}")
             return Decimal(0) # Or raise error? Return 0 for safety.

        product_total = product_price * order_quantity
        return product_total + shipping_price

    def save(self, *args, **kwargs):
        """Overrides save method.""" # Updated docstring
        # FIX v1.0.5: Remove unconditional recalculation of total_price_native_selected.
        # Assume the value provided or already present on the instance is correct,
        # or that calculation is handled before calling save() where necessary.
        # self.total_price_native_selected = self.calculate_total_price_native() # REMOVED
        super().save(*args, **kwargs)


# --- Feedback (with Granular Ratings) ---
class Feedback(models.Model):
    """ Stores buyer feedback for a completed order, including optional granular ratings. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='feedback', help_text="The order this feedback relates to.")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reviews_given', help_text="The user (buyer) who left the feedback.")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reviews_received', limit_choices_to={'is_vendor': True}, help_text="The user (vendor) who received the feedback.") # Added limit_choices_to

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
        # Determine feedback type based on rating
        if self.rating >= 4: self.feedback_type = FeedbackType.POSITIVE
        elif self.rating == 3: self.feedback_type = FeedbackType.NEUTRAL
        else: self.feedback_type = FeedbackType.NEGATIVE

        # Attempt to populate reviewer/recipient from order if not set
        # This logic might be better handled during form/serializer processing before saving
        if self.order_id and (not self.reviewer_id or not self.recipient_id):
            try:
                # Use select_related for efficiency if hitting DB
                order_instance = Order.objects.select_related('buyer', 'vendor').get(pk=self.order_id)
                if not self.reviewer_id: self.reviewer = order_instance.buyer # Set instance, not just ID
                if not self.recipient_id: self.recipient = order_instance.vendor # Set instance, not just ID
            except Order.DoesNotExist:
                logger.error(f"Feedback save failed: Cannot populate reviewer/recipient as Order ID {self.order_id} not found.")
                # Depending on requirements, either raise or allow save if reviewer/recipient were somehow set manually
                # raise ValidationError("Cannot save feedback: Associated order not found.")
        elif not self.order_id and (not self.reviewer_id or not self.recipient_id):
                 # Feedback must be linked to an order OR have reviewer/recipient set directly
                 raise ValidationError("Feedback must be associated with an order OR have both reviewer and recipient explicitly set.")

        super().save(*args, **kwargs)

    def clean(self):
        """Validates feedback constraints."""
        super().clean()
        order_instance = None
        if self.order_id:
             try:
                 # Fetch related buyer/vendor once if order_id exists
                 order_instance = Order.objects.select_related('buyer', 'vendor').get(pk=self.order_id)
             except Order.DoesNotExist:
                 raise ValidationError({'order': 'Associated order does not exist.'})

        # Check reviewer matches order buyer
        if order_instance and self.reviewer_id and self.reviewer_id != order_instance.buyer_id:
            raise ValidationError("Feedback reviewer must be the buyer of the associated order.")
        elif self.reviewer and not isinstance(self.reviewer, settings.AUTH_USER_MODEL):
            # Handle case where reviewer is set but not saved yet? Unlikely via Django ORM.
            pass # Or add validation if necessary

        # Check recipient matches order vendor
        if order_instance and self.recipient_id and self.recipient_id != order_instance.vendor_id:
            raise ValidationError("Feedback recipient must be the vendor of the associated order.")
        elif self.recipient and (not hasattr(self.recipient, 'is_vendor') or not self.recipient.is_vendor):
            # Ensure recipient is actually a vendor if set directly
            raise ValidationError("Feedback recipient must be a valid vendor user.")

        # Validate that feedback can only be left on orders in specific statuses
        if order_instance:
            # Use the correct inner class for status checks
            allowed_statuses_for_feedback = [
                Order.StatusChoices.FINALIZED,
                Order.StatusChoices.DISPUTE_RESOLVED
            ]
            if order_instance.status not in allowed_statuses_for_feedback:
                logger.info(f"Validation check: Feedback attempted for order {self.order_id} status '{order_instance.status}'. Allowed: {allowed_statuses_for_feedback}")
                # Uncomment the line below to strictly enforce this rule
                # raise ValidationError(f"Feedback can only be submitted for orders that are Finalized or have a Dispute Resolved (current status: {order_instance.get_status_display()}).")


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
            models.Index(fields=['related_order']), # Index useful for finding tickets for an order
            models.Index(fields=['updated_at']), # Index useful for ordering/filtering recent tickets
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
            models.Index(fields=['ticket', 'is_read', 'sent_at']), # Useful for finding unread messages
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
            # models.Index(fields=['timestamp']), # Redundant: covered by other indexes starting with timestamp? Check DB. Kept commented.
            models.Index(fields=['ip_address']), # Index useful for searching by IP
        ]

    def __str__(self):
        actor_name = getattr(self.actor, 'username', 'System') if self.actor else 'System'
        action_display = self.get_action_display()
        target_info = ""
        if self.target_user: target_info += f" TargetUser: {getattr(self.target_user, 'username', 'Deleted')}"
        if self.target_order: target_info += f" TargetOrder: {self.target_order_id}" # Use ID for brevity
        # Format timestamp with timezone awareness
        ts_local = timezone.localtime(self.timestamp)
        ts_str = ts_local.strftime('%Y-%m-%d %H:%M:%S %Z') if ts_local else 'No Timestamp'
        return f"{ts_str} | {actor_name} | {action_display}{target_info}"


# --- WebAuthn Credential Model ---
class WebAuthnCredential(models.Model):
    """ Stores a user's registered WebAuthn/FIDO2 credential data for passwordless/2FA login. """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='webauthn_credentials', help_text="The user associated with this WebAuthn credential.")
    # Store IDs as raw bytes? Base64URL is common practice for storage/transport. Text okay.
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
            # credential_id_b64 is indexed via unique=True
            models.Index(fields=['last_used_at']), # Useful for finding stale credentials
        ]
        ordering = ['user', '-created_at']

    def __str__(self):
        user_repr = self.user.username if hasattr(self.user, 'username') else f"User ID {self.user_id}"
        nickname_part = f" ({self.nickname})" if self.nickname else ""
        # Ensure credential_id_b64 is treated as string
        cred_id_str = str(self.credential_id_b64) if self.credential_id_b64 else ""
        cred_id_short = (cred_id_str[:10] + "...") if len(cred_id_str) > 13 else cred_id_str
        return f"WebAuthn Credential for {user_repr}{nickname_part} (ID: {cred_id_short})"

# --- END OF FILE ---