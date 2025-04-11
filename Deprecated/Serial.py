# backend/store/serializers.py
# Revision: 1
# Date: 2025-04-07
# Author: Gemini AI Assistant
# Changes:
# - [PRIORITY 1] Strengthened CurrentUserSerializer password validation logic in validate() and update().
# - [PRIORITY 2] Added critical dependency warning about denormalization risks in VendorPublicProfileSerializer docstring.
# - [PRIORITY 1] Added basic schema validation for shipping_options JSONField in ProductSerializer via validate_shipping_options().
# - [PRIORITY 1] Ensured EncryptCheckoutDataSerializer validate() explicitly checks for vendor PGP key for server encryption path.
# - Added json import for validation.

# Standard Library Imports
import logging
import json # Added for JSON validation
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Union, List # Added/Updated for type hinting

# Third-Party Imports
from django.conf import settings
from django.db.models import Avg # Keep if potentially used indirectly or planned
from rest_framework import serializers

# Local Application Imports
# Ensure models are correctly defined and accessible
from .models import (
    User, Category, Product, Order, CryptoPayment, Feedback,
    SupportTicket, TicketMessage, CURRENCY_CHOICES, # Assuming these exist and are correct
    Notification,
    GlobalSettings
)
# Ensure validators exist and are robust
from .validators import (
    validate_bitcoin_address, validate_ethereum_address, validate_monero_address,
    validate_pgp_public_key
)

# Setup logger for this module
logger = logging.getLogger(__name__)

# --- Constants ---
# Centralize precision mapping for consistency
# Consider moving to settings or a dedicated constants file if used widely
CRYPTO_PRECISION_MAP = {
    Order.CurrencyChoices.XMR: 12,
    Order.CurrencyChoices.BTC: 8,
    Order.CurrencyChoices.ETH: 18, # Full precision (Wei)
    # Add other supported currencies here
}
DEFAULT_CRYPTO_PRECISION = 12 # Fallback precision

# --- Custom Fields ---

class DecimalAsStringField(serializers.DecimalField):
    """
    Custom DecimalField that serializes Decimal values as precise strings.

    Prevents floating-point inaccuracies in JSON/JavaScript and ensures specific
    quantization (decimal places). Essential for financial/cryptocurrency values.
    Overrides standard DecimalField's reliance on the JSON renderer's default behavior.
    """
    # Define default precision suitable for high-precision crypto use cases
    DEFAULT_MAX_DIGITS = 30 # Maximum allowed digits
    DEFAULT_DECIMAL_PLACES = 18 # Default precision (e.g., sufficient for ETH)

    def __init__(self, *args: Any, **kwargs: Any):
        """Set default max_digits and decimal_places if not provided."""
        kwargs.setdefault('max_digits', self.DEFAULT_MAX_DIGITS)
        kwargs.setdefault('decimal_places', self.DEFAULT_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)

    def to_representation(self, value: Optional[Union[Decimal, str, int, float]]) -> Optional[str]:
        """Serialize Decimal to a fixed-precision string using quantization."""
        if value is None:
            return None
        try:
            # Ensure the value is a Decimal for accurate quantization
            d_value = Decimal(str(value)) # Convert via string to handle various inputs safely
            # Create the exponent for quantization based on configured decimal_places
            quantize_exp = Decimal('1e-' + str(self.decimal_places))
            # Quantize and use to_eng_string() to prevent scientific notation and trailing zeros issues.
            return d_value.quantize(quantize_exp).to_eng_string()
        except (InvalidOperation, TypeError, ValueError) as e:
            # Log the error for debugging unexpected input values
            logger.warning(f"Could not serialize value '{value}' as Decimal string: {e}")
            # Fallback to a simple string representation in case of critical error
            return str(value)

# --- User Serializers ---

class UserPublicSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for publicly viewable user data (vendors, buyers).
    Excludes sensitive information. Typically nested.
    """
    vendor_level_display = serializers.CharField(source='get_vendor_level_display', read_only=True, required=False, help_text="Display name for the vendor level.")

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'date_joined',
            'is_vendor',
            'vendor_level', # Raw level value
            'vendor_level_display', # Human-readable level name
            # Consider adding a public profile URL if applicable
        )
        read_only_fields = fields # All fields are read-only in this public context

class VendorPublicProfileSerializer(serializers.ModelSerializer):
    """
    Serializer for the dedicated Vendor Public Profile page.

    Relies heavily on denormalized fields stored on the User model (e.g.,
    `vendor_avg_rating`, `vendor_completion_rate_percent`, `vendor_rating_count`, etc.)
    for performance optimization.

    **CRITICAL DEPENDENCY:** The accuracy of this serializer's output is
    entirely dependent on the reliability and timeliness of the background
    processes (e.g., signals, periodic tasks) responsible for calculating and
    updating these denormalized fields on the User model. Ensure these update
    mechanisms are robust, monitored, and handle potential race conditions or
    errors gracefully. Failure in the update mechanism will result in stale or
    incorrect data being displayed on the vendor's public profile.

    Consider adding `vendor_reputation_last_updated` field to indicate data freshness.
    """
    # Use DecimalAsStringField for ratings/rates if the model uses DecimalField
    # to ensure consistent string representation across the API.
    # If the model uses FloatField, serializers.FloatField is technically correct,
    # but be mindful of potential float representation issues in frontend JS.
    # Assuming DecimalField in model for better precision:
    vendor_avg_rating = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's average rating (denormalized).")
    vendor_completion_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order completion rate % (denormalized).")
    vendor_dispute_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order dispute rate % (denormalized).")
    vendor_bond_amount_display = DecimalAsStringField(source='vendor_bond_amount', read_only=True, required=False, help_text="Amount of bond paid, if applicable (denormalized).")

    # Added fields for clarity and completeness
    vendor_level_display = serializers.CharField(source='get_vendor_level_display', read_only=True, help_text="Display name for the vendor level.")

    class Meta:
        model = User
        # Ensure these field names exactly match the User model's denormalized fields
        fields = [
            'id',
            'username',
            'date_joined',
            'approved_vendor_since', # Date vendor status was approved
            'pgp_public_key',        # Public PGP key for secure communication
            'vendor_level_display',  # Display name (e.g., "Gold")
            'vendor_avg_rating',
            'vendor_rating_count',
            'vendor_total_orders',   # Consider renaming for clarity if needed (e.g., vendor_lifetime_sales_count)
            'vendor_completed_orders_30d', # Optional: Recent performance indicator
            'vendor_completion_rate_percent',
            'vendor_dispute_rate_percent',
            'vendor_bond_paid',          # Boolean indicating if bond is currently active/paid
            'vendor_bond_amount_display', # Display the bond amount
            'vendor_reputation_last_updated', # Freshness of denormalized stats
            'profile_description', # Assuming a vendor profile description field exists
            # Add other relevant public vendor info fields (e.g., policies)
        ]
        # All fields exposed on a public profile should be read-only.
        read_only_fields = fields

class CurrentUserSerializer(serializers.ModelSerializer):
    """
    Serializer for the currently authenticated user's private data and settings.
    Handles profile updates including password change and withdrawal addresses.
    """
    # Withdrawal addresses with validation
    # Ensure model fields allow blank=True and null=True if these are set here.
    btc_withdrawal_address = serializers.CharField(
        validators=[validate_bitcoin_address], required=False, allow_blank=True, allow_null=True, max_length=95,
        help_text="Your Bitcoin withdrawal address (optional)."
    )
    eth_withdrawal_address = serializers.CharField(
        validators=[validate_ethereum_address], required=False, allow_blank=True, allow_null=True, max_length=42,
        help_text="Your Ethereum withdrawal address (optional)."
    )
    xmr_withdrawal_address = serializers.CharField(
        validators=[validate_monero_address], required=False, allow_blank=True, allow_null=True, max_length=106, # Check Monero address max length
        help_text="Your Monero withdrawal address (optional)."
    )
    # Add other crypto addresses as needed

    # PGP Key with validation and textarea widget hint
    pgp_public_key = serializers.CharField(
        style={'base_template': 'textarea.html', 'rows': 10},
        validators=[validate_pgp_public_key],
        required=False, allow_blank=True, allow_null=True, # Allow clearing PGP key
        help_text="Your PGP public key for encrypted communication (optional)."
    )

    # Password change fields (write-only, require current password)
    current_password = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        label="Current Password", help_text="Required to change your password."
    )
    # Ensure password validation (complexity) is handled either here,
    # in the validator, or via Django's AUTH_PASSWORD_VALIDATORS setting.
    password = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        min_length=getattr(settings, 'AUTH_PASSWORD_MIN_LENGTH', 12), # Use getattr for safety
        label="New Password", help_text=f"Enter your new password (min {getattr(settings, 'AUTH_PASSWORD_MIN_LENGTH', 12)} chars)."
    )
    password_confirm = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        label="Confirm New Password", help_text="Enter your new password again."
    )

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', # Email management depends on application rules (verify if changeable)
            'pgp_public_key', 'is_vendor', 'vendor_level',
            'btc_withdrawal_address', 'eth_withdrawal_address', 'xmr_withdrawal_address', # Add other cryptos
            'login_phrase', # Security feature, usually read-only after creation
            'date_joined', 'last_login',
            # Write-only fields for password change:
            'current_password', 'password', 'password_confirm',
            # Add other user-configurable settings fields here
            # E.g., 'preferred_currency', 'timezone', 'two_factor_enabled' (read-only status)
        )
        read_only_fields = (
            'id', 'username', # Typically not changeable after creation
            'is_vendor', 'vendor_level', # Status managed by admins/system
            'date_joined', 'last_login', 'login_phrase',
            'email', # Make writable only if users can change their email AND verification is implemented.
                     # Ensure it's set correctly during registration if read-only.
            # Add other read-only fields like 'two_factor_enabled' status
        )
        extra_kwargs = {
            # Ensure email read_only status matches the setting in read_only_fields for clarity
            'email': {'read_only': True}, # Example: Explicitly mark email as read-only
            # Define widgets or styles if needed (PGP key handled above)
        }

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles cross-field validation. Ensures password fields are consistent if provided.
        Password complexity beyond min_length should be enforced by Django settings (AUTH_PASSWORD_VALIDATORS)
        or added here if custom rules are needed.
        """
        new_password = data.get('password')
        confirm_password = data.get('password_confirm')
        current_password = data.get('current_password') # Still needed if password fields present

        # Determine if *any* password field was submitted in the request payload.
        # self.initial_data contains the raw request data before validation/processing.
        password_fields_in_request = any(
            field in self.initial_data for field in ['password', 'password_confirm', 'current_password']
        )

        # If any password field is present in the request, enforce all are present and match.
        if password_fields_in_request:
            errors: Dict[str, List[str]] = {} # Use list for potential multiple errors per field
            if not new_password:
                errors.setdefault('password', []).append("This field is required for password change.")
            if not confirm_password:
                errors.setdefault('password_confirm', []).append("This field is required for password change.")
            if not current_password:
                # Current password is required ONLY if changing the password.
                # If only other fields (e.g., address) are being updated, current_password is not needed.
                errors.setdefault('current_password', []).append("This field is required to change the password.")

            # Check password match only if both new passwords were provided (and potentially valid)
            if new_password and confirm_password and new_password != confirm_password:
                errors.setdefault('password_confirm', []).append("New passwords do not match.")

            # Add custom password complexity validation here if needed (beyond Django settings)
            # Example:
            # if new_password and not custom_password_policy(new_password):
            #     errors.setdefault('password', []).append("Password does not meet complexity requirements.")

            if errors:
                raise serializers.ValidationError(errors)
        elif any([new_password, confirm_password, current_password]):
             # Defensive check: if password fields are somehow present in `data` but weren't in `initial_data`
             # (shouldn't happen with standard DRF flow but good practice), raise an error.
             # Or, more likely, this means password fields were provided but validation above failed.
             # This branch might be redundant if the first `if errors:` block catches everything.
             logger.warning(f"Password fields present in validated data but inconsistency detected for user update.")
             # Consider raising a generic validation error if this state is reachable.

        # Add other cross-field validations if necessary
        # E.g., validate withdrawal addresses aren't identical if required

        return data

    def update(self, instance: User, validated_data: Dict[str, Any]) -> User:
        """
        Handles instance updates, including secure password setting and session hash update.
        Requires the associated view to call `update_session_auth_hash` after this update.
        """
        # Pop password fields - they are handled separately.
        new_password = validated_data.pop('password', None)
        validated_data.pop('password_confirm', None) # Never saved
        current_password = validated_data.pop('current_password', None) # Only used for check

        password_changed = False
        if new_password and current_password:
            # --- Password Change Logic ---
            # Validate current password *before* setting the new one.
            if not instance.check_password(current_password):
                # Use a specific error code or key for frontend handling if needed
                raise serializers.ValidationError(
                    {"current_password": ["Current password is not correct."]},
                    code='invalid_current_password' # Example code
                )

            # Set the new password securely using Django's built-in hashing
            try:
                instance.set_password(new_password)
                password_changed = True
                logger.info(f"Password updated successfully for user {instance.username} (ID: {instance.id})")
                # CRITICAL NOTE: The VIEW calling this MUST call update_session_auth_hash(request, instance)
                # AFTER instance.save() to invalidate other sessions. This serializer cannot do it.
            except Exception as e:
                logger.error(f"Error setting new password for user {instance.username} (ID: {instance.id}): {e}")
                raise serializers.ValidationError({"password": ["An error occurred while updating the password."]}) # Generic error to user

        elif new_password and not current_password:
             # This should have been caught by the `validate` method if password fields were in request.
             # Log and raise defensively.
             logger.error(f"Update attempt for user {instance.id} reached `update` with new_password but no current_password.")
             raise serializers.ValidationError({"current_password": ["Current password is required to set a new password."]})

        # --- Update Other Fields ---
        # Update other allowed fields provided in validated_data
        # Use super() for standard ModelSerializer field updates is generally safe,
        # but iterating allows finer control or pre/post save actions per field if needed.
        for attr, value in validated_data.items():
            # Ensure only allowed fields (not read-only) are set
            # This check might be redundant if serializer Meta is correct, but adds safety.
            if attr not in self.Meta.read_only_fields:
                setattr(instance, attr, value)
            else:
                # Log if an attempt is made to update a read-only field via validated_data
                # (shouldn't happen if serializer is configured correctly).
                logger.warning(f"Attempted to update read-only field '{attr}' during User update for {instance.username}.")

        # --- Save Instance ---
        # Only save fields that were actually updated or the password if changed.
        update_fields = list(validated_data.keys())
        if password_changed:
            # Ensure the 'password' field itself (which stores the hash) is included for saving.
            update_fields.append('password')

        # Avoid saving if no fields were changed (unless only password changed)
        if update_fields:
             # Filter out any fields that might have slipped through read-only check (defensive)
            allowed_update_fields = [f for f in update_fields if f not in self.Meta.read_only_fields or f == 'password']
            if allowed_update_fields:
                 instance.save(update_fields=allowed_update_fields)
            elif password_changed:
                 # Only password changed
                 instance.save(update_fields=['password'])
        elif password_changed:
             # Only password changed, no other fields
             instance.save(update_fields=['password'])

        return instance

# --- Category Serializer ---

class CategorySerializer(serializers.HyperlinkedModelSerializer):
    """Serializer for Product Categories, including hyperlinking."""
    # Performance: Consider adding 'product_count' via SerializerMethodField + annotation
    # in the ViewSet queryset if frequently needed in list views.
    # product_count = serializers.IntegerField(read_only=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='store:category-detail', # Ensure 'store' is the correct app_name namespace
        lookup_field='slug',
        help_text="URL link to this category resource."
    )
    parent = serializers.HyperlinkedRelatedField(
        view_name='store:category-detail', # Link to parent category
        lookup_field='slug',
        read_only=True,
        allow_null=True, # Root categories have no parent
        help_text="Link to the parent category, if any."
    )
    # Consider adding depth or child categories if needed for navigation structure

    class Meta:
        model = Category
        fields = ('id', 'url', 'name', 'slug', 'description', 'parent')
        read_only_fields = ('id', 'slug') # Slug typically auto-generated from name


# --- Product Serializer ---

class ProductSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Product details. Includes vendor and category info.
    Uses custom DecimalAsStringField for precise crypto price representation.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('vendor', 'category')
    """
    url = serializers.HyperlinkedIdentityField(
        view_name='store:product-detail',
        lookup_field='slug',
        help_text="URL link to this product resource."
    )
    # Use public representation for vendor
    vendor = UserPublicSerializer(read_only=True, help_text="Public information of the vendor selling this product.")
    # Use category serializer for readable category info
    category = CategorySerializer(read_only=True, help_text="Category this product belongs to.")

    # Use custom field for Decimal-to-String conversion with specific crypto precisions
    price_xmr = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Order.CurrencyChoices.XMR], required=False, allow_null=True, help_text="Price in Monero (XMR), as string.")
    price_btc = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Order.CurrencyChoices.BTC], required=False, allow_null=True, help_text="Price in Bitcoin (BTC), as string.")
    price_eth = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Order.CurrencyChoices.ETH], required=False, allow_null=True, help_text="Price in Ethereum (ETH), as string.")
    # Consider adding price_usd or another reference fiat currency if used for display/sorting
    # price_usd = DecimalAsStringField(decimal_places=2, required=False, allow_null=True, ...)

    # Allow setting category via ID during write operations (create/update)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), # Consider filtering queryset if needed (e.g., only active categories)
        source='category', write_only=True, required=True,
        help_text="ID of the category this product belongs to (required for create/update)."
    )
    # Basic validation for JSON field. Complex validation (e.g., schema checking)
    # should ideally occur in model clean() or serializer validate() methods.
    shipping_options = serializers.JSONField(
        required=False, allow_null=True,
        help_text=(
            "JSON list defining shipping options. Each item must be an object "
            "with 'name' (string), and price fields (e.g., 'price_xmr', 'price_btc') as strings. "
            "Example: [{'name': 'Standard', 'price_xmr': '0.05'}, {'name': 'Express', 'price_xmr': '0.15'}]"
        )
    )

    # Add average rating if denormalized on Product model
    # average_rating = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Average feedback rating for this product.")
    # sales_count = serializers.IntegerField(read_only=True, help_text="Number of times this product has been sold.")

    class Meta:
        model = Product
        fields = (
            'id', 'url', 'vendor', 'category', 'name', 'slug', 'description',
            'price_xmr', 'price_btc', 'price_eth', # Add other prices like price_usd
            'accepted_currencies', # Ensure this matches model choices/field type (e.g., MultiSelectField or similar if stored in DB)
            'quantity', 'ships_from', 'ships_to', 'shipping_options',
            'is_active', 'is_featured', 'is_digital', # Assuming is_digital field exists
            'sales_count', 'average_rating', # Assuming these are on the Product model (denormalized)
            'created_at', 'updated_at',
            'category_id', # Write-only field for setting category
            # Add other relevant product fields: 'weight', 'dimensions', 'tags', etc.
        )
        read_only_fields = (
            'id', 'slug', 'vendor', 'category', # Read representation uses nested serializers
            'sales_count', 'average_rating', # Typically calculated/managed by system
            'created_at', 'updated_at'
        )
        # Writable fields usually controlled by vendor: 'name', 'description', 'price_*', 'accepted_currencies',
        # 'quantity', 'ships_from', 'ships_to', 'shipping_options', 'is_active', 'is_featured', 'is_digital',
        # 'category_id' (via source)
        # Ensure view permissions correctly restrict who can write these fields.

    def validate_shipping_options(self, value: Optional[Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Validates the structure and content of the shipping_options JSON.
        Ensures it's a list of objects, each with a 'name' and valid price strings.
        """
        if value is None:
            return None # Allow null

        if not isinstance(value, list):
            raise serializers.ValidationError("Shipping options must be a JSON list.")

        if not value: # Allow empty list if appropriate for the model/logic
             return value

        validated_options = []
        for index, option in enumerate(value):
            if not isinstance(option, dict):
                raise serializers.ValidationError(f"Item at index {index} is not a valid JSON object.")

            option_name = option.get('name')
            if not option_name or not isinstance(option_name, str) or not option_name.strip():
                raise serializers.ValidationError(f"Item at index {index} must have a non-empty 'name' string.")

            # Validate price fields (presence and format)
            # Assuming prices are stored like 'price_xmr', 'price_btc', etc.
            # Get the list of supported currency price keys for validation
            # (This might need context or access to settings/model constants)
            # Example using CURRENCY_CHOICES if defined appropriately:
            expected_price_keys = {f'price_{code.lower()}' for code, _ in CURRENCY_CHOICES}
            has_at_least_one_price = False

            for key, price_str in option.items():
                 # Check only keys that look like price fields
                 if key.startswith('price_'):
                      # Validate it's an expected currency price key
                      if key not in expected_price_keys:
                           logger.warning(f"Unexpected price key '{key}' found in shipping_options for product.")
                           # Decide policy: ignore, warn, or raise error? Raising for stricter validation.
                           # raise serializers.ValidationError(f"Item at index {index} contains unexpected price key '{key}'.")
                           continue # Ignoring for now, adapt as needed

                      # Validate price format (must be string, represent non-negative decimal)
                      if not isinstance(price_str, str):
                          raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) must be a string.")
                      try:
                          price_decimal = Decimal(price_str)
                          if price_decimal < Decimal('0.0'):
                              raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) cannot be negative.")
                          # Optionally, check against max_digits/decimal_places if needed
                      except InvalidOperation:
                          raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) is not a valid decimal string.")

                      has_at_least_one_price = True

            if not has_at_least_one_price:
                 # Enforce that each shipping option must define at least one price
                 raise serializers.ValidationError(f"Shipping option '{option_name}' (index {index}) must define at least one valid price (e.g., 'price_xmr').")

            validated_options.append(option) # Keep original structure if valid

        return validated_options

# --- CryptoPayment Serializer ---

class CryptoPaymentSerializer(serializers.ModelSerializer):
    """
    Serializer for Cryptocurrency Payment details associated with an order.
    Typically read-only as payment status is managed by the backend payment monitoring system.
    """
    # Use custom field for displaying crypto amounts accurately as strings
    # Precision determined dynamically based on the payment's currency
    expected_amount_native = serializers.SerializerMethodField(help_text="Expected payment amount in the native cryptocurrency (string).")
    received_amount_native = serializers.SerializerMethodField(help_text="Received payment amount in the native cryptocurrency (string).")

    order = serializers.HyperlinkedRelatedField(
        view_name='store:order-detail', # Link to the order
        read_only=True,
        lookup_field='pk', # Assuming Order PK is used for lookup
        help_text="Link to the associated order."
    )
    # Provide display names for choices
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)

    class Meta:
        model = CryptoPayment
        fields = (
            'id',
            'order', # HyperlinkedRelatedField above
            'currency', # Raw currency code (e.g., XMR)
            'currency_display', # Human-readable name (e.g., Monero)
            'payment_address', # The address funds should be sent to
            'payment_id_monero', # Specific to XMR integrated addresses, null otherwise
            'expected_amount_native', # Formatted string via SerializerMethodField
            'received_amount_native', # Formatted string via SerializerMethodField
            'is_confirmed', # Boolean indicating if payment met confirmation threshold
            'confirmations_received', # Actual number of confirmations seen
            'confirmations_needed', # Required confirmations for this currency/payment
            'transaction_hash', # Blockchain transaction ID (if detected)
            'created_at',
            'updated_at',
        )
        # Payment details are system-generated and updated, not directly mutable by API users.
        read_only_fields = fields

    def _format_crypto_amount(self, amount: Optional[Decimal], currency: Optional[str]) -> Optional[str]:
        """Helper to format crypto amount based on currency."""
        if amount is None or currency is None:
            return None
        try:
            d_amount = Decimal(str(amount)) # Ensure Decimal via string
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            return d_amount.quantize(quantize_exp).to_eng_string()
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format crypto amount '{amount}' for currency '{currency}': {e}")
            return str(amount) # Fallback

    def get_expected_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        """Formats the expected amount based on the payment's currency."""
        return self._format_crypto_amount(obj.expected_amount_native, obj.currency)

    def get_received_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        """Formats the received amount based on the payment's currency."""
        return self._format_crypto_amount(obj.received_amount_native, obj.currency)


# --- Feedback Serializer ---

class FeedbackSerializer(serializers.ModelSerializer):
    """
    Serializer for Feedback provided on orders.
    Handles displaying feedback (read) and submitting new feedback (write).
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('reviewer', 'recipient', 'order', 'order__product')
    """
    reviewer = UserPublicSerializer(read_only=True, help_text="User who wrote the feedback.")
    recipient = UserPublicSerializer(read_only=True, help_text="User who received the feedback (vendor or buyer).")
    order = serializers.HyperlinkedRelatedField(
        view_name='store:order-detail',
        read_only=True, # Set via order_id on create
        lookup_field='pk', # Assuming Order PK
        help_text="Link to the order this feedback relates to."
    )
    # Include minimal product info for context
    product_name = serializers.CharField(source='order.product.name', read_only=True, help_text="Name of the product associated with the order.")

    # Write-only field to associate feedback with an order upon creation
    # Ensure Order PK type is UUID (recommended) or adjust field type
    order_id = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(), # Validation logic below ensures user/state eligibility
        write_only=True, required=True, source='order',
        help_text="The ID (PK) of the order this feedback is for (required on create)."
    )

    # Writable fields for submitting feedback
    # Ensure model fields have appropriate validators (MinValueValidator, MaxValueValidator)
    rating = serializers.IntegerField(min_value=1, max_value=5, required=True, help_text="Overall rating (1-5 stars).")
    comment = serializers.CharField(max_length=2000, required=True, style={'base_template': 'textarea.html'}, help_text="Feedback comment (max 2000 chars).")
    rating_quality = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True, help_text="Rating for product quality (1-5 stars, optional).")
    rating_shipping = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True, help_text="Rating for shipping (1-5 stars, optional).")
    rating_communication = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True, help_text="Rating for communication (1-5 stars, optional).")

    # Provide display name for feedback type
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)

    class Meta:
        model = Feedback
        fields = (
            'id', 'order', 'product_name', 'reviewer', 'recipient', # Read context fields
            'rating', 'comment',
            'feedback_type', # Raw type value
            'feedback_type_display', # Human-readable type
            'rating_quality', 'rating_shipping', 'rating_communication', # Granular ratings
            'created_at',
            'order_id', # Write-only field for creation
        )
        read_only_fields = (
            'id', 'order', 'product_name', 'reviewer', 'recipient', # `order` is read-only here, set via `order_id`
            'feedback_type', 'feedback_type_display', # Determined by system logic during creation
            'created_at'
        )
        # Writable on create: 'rating', 'comment', 'rating_*', and 'order_id' (source='order').

    def validate_order_id(self, order: Order) -> Order: # PrimaryKeyRelatedField returns the instance
        """Check if the order exists, is in a feedback-eligible state, and user can leave feedback."""
        request_user = self.context['request'].user
        if not request_user or not request_user.is_authenticated:
             raise serializers.ValidationError("Authentication required to leave feedback.") # Should be handled by permissions, but defensive check

        # Order instance is already fetched by PrimaryKeyRelatedField by this point.
        # Perform logic checks on the instance.

        # Check if the user is the buyer or vendor of this order
        is_buyer = order.buyer == request_user
        is_vendor = order.vendor == request_user
        if not is_buyer and not is_vendor:
            raise serializers.ValidationError("You are not the buyer or vendor associated with this order.")

        # Determine who the intended recipient is for duplicate check
        recipient = order.vendor if is_buyer else order.buyer

        # Check if feedback already exists for this order from this user about the recipient
        # Using related manager for efficiency
        if Feedback.objects.filter(order=order, reviewer=request_user, recipient=recipient).exists():
             raise serializers.ValidationError("You have already left feedback for this order.")

        # Define statuses eligible for feedback (move to settings or Order model constant?)
        FEEDBACK_ELIGIBLE_STATUSES = [Order.OrderStatus.FINALIZED, Order.OrderStatus.SHIPPED] # Adjust as per application logic
        if order.status not in FEEDBACK_ELIGIBLE_STATUSES:
            allowed_statuses_str = ", ".join([str(s) for s in FEEDBACK_ELIGIBLE_STATUSES])
            raise serializers.ValidationError(f"Feedback can only be left for orders with status: {allowed_statuses_str}. Current status: '{order.get_status_display()}'.")

        # Return the validated Order instance for use in create()
        return order

    def create(self, validated_data: Dict[str, Any]) -> Feedback:
        """Set reviewer, determine recipient and feedback type based on validated order and request user."""
        request_user = self.context['request'].user
        order: Order = validated_data['order'] # Order instance is set by validate_order_id via source='order'

        validated_data['reviewer'] = request_user

        # Determine recipient and feedback type
        if order.buyer == request_user:
            validated_data['recipient'] = order.vendor
            validated_data['feedback_type'] = Feedback.FeedbackTypeChoices.FROM_BUYER
        elif order.vendor == request_user:
            validated_data['recipient'] = order.buyer
            validated_data['feedback_type'] = Feedback.FeedbackTypeChoices.FROM_VENDOR
        else:
            # This state should be impossible if validate_order_id worked correctly.
            logger.error(f"CRITICAL: User {request_user.id} passed validation but is not buyer/vendor for order {order.id} during feedback creation.")
            raise serializers.ValidationError("Internal error: Cannot determine feedback recipient.")

        # Validation logic (e.g., duplicate feedback) moved to `validate_order_id`.
        # Any further logic before saving (e.g., triggering notifications) could go here.

        try:
            feedback = super().create(validated_data)
            # Potential post-creation actions (e.g., update denormalized vendor ratings via signal/task)
            # trigger_vendor_rating_update(feedback.recipient_id)
            logger.info(f"Feedback created (ID: {feedback.id}) for Order {order.id} by User {request_user.id}.")
            return feedback
        except Exception as e:
            logger.error(f"Error creating feedback for order {order.id} by user {request_user.id}: {e}")
            # Re-raise or wrap in a DRF validation error
            raise serializers.ValidationError("An error occurred while saving feedback.")


# --- Order Serializers ---

class OrderBaseSerializer(serializers.HyperlinkedModelSerializer):
    """
    Base serializer containing common fields and methods for Orders.
    Provides structure for Buyer and Vendor specific views.
    Performance Recommendation: Viewsets using derived serializers should use:
        queryset.select_related('product', 'product__vendor', 'buyer', 'vendor')
        and prefetch_related('payment', 'feedback_set') based on context.
    """
    url = serializers.HyperlinkedIdentityField(
        view_name='store:order-detail',
        lookup_field='pk', # Assuming Order PK is UUID or Int
        help_text="URL link to this order resource."
    )
    # Include essential product details directly for context
    product = ProductSerializer(read_only=True, help_text="Details of the product ordered.")

    total_price_native_selected = serializers.SerializerMethodField(
        help_text="Total price in the selected cryptocurrency, formatted as string for precision."
    )
    selected_currency_display = serializers.CharField(source='get_selected_currency_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True, help_text="Human-readable order status.")

    # Multisig release status indicators (avoids exposing raw signatures)
    release_signature_buyer_present = serializers.SerializerMethodField(help_text="Indicates if buyer's multisig release signature is present.")
    release_signature_vendor_present = serializers.SerializerMethodField(help_text="Indicates if vendor's multisig release signature is present.")

    class Meta:
        model = Order
        fields = (
            'id', 'url', 'product', 'quantity',
            'selected_currency', # Raw currency code
            'selected_currency_display', # Human-readable
            'total_price_native_selected', # Formatted string via method
            'status', # Raw status value
            'status_display', # Human-readable status
            'release_initiated', # Boolean flag indicating if release process started
            'release_signature_buyer_present', # Boolean representation
            'release_signature_vendor_present', # Boolean representation
            'release_tx_broadcast_hash', # Hash of the broadcasted release transaction (if applicable)
            'created_at', 'updated_at',
            'payment_deadline', # Datetime buyer must pay by
            'auto_finalize_deadline', # Datetime order finalizes if no dispute
            'dispute_deadline', # Datetime dispute window closes
            # Sensitive fields like escrow details (multisig addresses/keys),
            # raw signatures, encrypted shipping info, or dispute messages
            # are deliberately excluded from base representation and handled
            # in context-specific serializers or views.
        )
        read_only_fields = fields # Base fields are typically read-only representations

    def get_total_price_native_selected(self, obj: Order) -> Optional[str]:
        """Formats the total price based on the selected currency's precision."""
        price = obj.total_price_native_selected
        currency = obj.selected_currency
        if price is None or currency is None:
            return None

        try:
            d_price = Decimal(str(price)) # Ensure Decimal via string
            # Use centralized precision map
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            return d_price.quantize(quantize_exp).to_eng_string()
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format total_price_native_selected '{price}' for order {obj.id}: {e}")
            return str(price) # Fallback to simple string

    def get_release_signature_buyer_present(self, obj: Order) -> bool:
        """Checks if the buyer's release signature field is populated (non-empty)."""
        # Avoid exposing the signature itself, just its presence.
        return bool(obj.release_signature_buyer)

    def get_release_signature_vendor_present(self, obj: Order) -> bool:
        """Checks if the vendor's release signature field is populated (non-empty)."""
        # Avoid exposing the signature itself, just its presence.
        return bool(obj.release_signature_vendor)

class OrderBuyerSerializer(OrderBaseSerializer):
    """
    Serializer for the Buyer viewing their specific order details. Includes vendor info.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('product', 'product__vendor', 'vendor')
                .prefetch_related('payment', 'feedback_set') # Adjust feedback_set if needed
    """
    vendor = UserPublicSerializer(read_only=True, help_text="Public info of the vendor for this order.")
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True, help_text="Payment details for this order (if generated).")
    # Retrieve feedback given *by the buyer* for this order.
    # Assumes a method 'get_buyer_feedback' exists on the Order model that returns the relevant Feedback instance or None.
    feedback_given = FeedbackSerializer(source='get_buyer_feedback', read_only=True, allow_null=True, help_text="Feedback you (buyer) have given for this order.")

    class Meta(OrderBaseSerializer.Meta):
        # Inherit fields from base and add buyer-specific view fields
        fields = OrderBaseSerializer.Meta.fields + (
            'vendor',
            'payment',
            'feedback_given',
            # Carefully consider exposing escrow details (e.g., multisig redeem script)
            # if needed for buyer verification, balancing transparency with security.
            # 'escrow_details', # Example: Potentially add a dedicated EscrowSerializer if needed
            # Exclude sensitive vendor data or raw encrypted shipping info.
        )
        read_only_fields = fields # All fields read-only for buyer representation

class OrderVendorSerializer(OrderBaseSerializer):
    """
    Serializer for the Vendor viewing their specific sale details. Includes buyer info.
    IMPORTANT: Encrypted shipping info is NOT exposed directly. Decryption must happen
    server-side within the view, gated by authentication and PGP key access.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('product', 'product__vendor', 'buyer')
                .prefetch_related('payment', 'feedback_set') # Adjust feedback_set if needed
    """
    buyer = UserPublicSerializer(read_only=True, help_text="Public info of the buyer for this order.")
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True, help_text="Payment details for this order (if generated).")
    # Retrieve feedback received *by the vendor* for this order.
    # Assumes a method 'get_vendor_feedback' exists on the Order model.
    feedback_received = FeedbackSerializer(source='get_vendor_feedback', read_only=True, allow_null=True, help_text="Feedback received from the buyer for this order.")

    # Indicates presence of shipping info without exposing the encrypted blob.
    has_shipping_info = serializers.SerializerMethodField(help_text="Indicates if encrypted shipping information is present for this order.")
    # Placeholder for potentially adding decrypted shipping info *if* the view handles
    # secure decryption based on the authenticated vendor's PGP key.
    # decrypted_shipping_info = ShippingDataSerializer(read_only=True, required=False, allow_null=True) # Populated by view only!

    class Meta(OrderBaseSerializer.Meta):
        # Inherit fields from base and add vendor-specific view fields
        fields = OrderBaseSerializer.Meta.fields + (
            'buyer',
            'payment',
            'feedback_received',
            'has_shipping_info',
            # 'decrypted_shipping_info', # VERY CAREFULLY include only if view provides it securely
            # Exclude sensitive buyer info (e.g., full profile beyond public)
            # and never expose the raw encrypted shipping blob here.
        )
        read_only_fields = fields # All fields read-only for vendor representation

    def get_has_shipping_info(self, obj: Order) -> bool:
        """Checks if the encrypted shipping info field is populated (non-empty)."""
        return bool(obj.encrypted_shipping_info)


# --- Support Ticket Serializers ---

class TicketMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for individual messages within a support ticket.
    Handles secure message submission (write-only plaintext) and display (read-only decrypted).
    Encryption/Decryption logic MUST reside securely in the view or backend service,
    using the appropriate recipient's (user/staff) PGP key.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('sender')
    """
    sender = UserPublicSerializer(read_only=True, help_text="User who sent this message.")
    # This field is populated dynamically by the view *after* successful decryption
    # using the authenticated request user's PGP key. It's NOT stored in the DB.
    decrypted_body = serializers.CharField(read_only=True, required=False, allow_null=True, help_text="Decrypted message content (available only if view provides it).")

    # This field is used for submitting a *new* message (POST request to add message endpoint).
    # The view MUST encrypt this content using the *recipient's* PGP key before saving.
    message_body = serializers.CharField(
        write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000, # Limit message size
        label="Message Content", help_text="Enter your message here (it will be PGP encrypted before sending)."
    )

    class Meta:
        model = TicketMessage
        fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body', 'message_body')
        read_only_fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body')
        # `message_body` is write-only for sending.
        # `is_read` status updates should be handled via a separate 'mark as read' API action/endpoint.


class SupportTicketBaseSerializer(serializers.HyperlinkedModelSerializer):
    """
    Base serializer for Support Tickets, containing common fields for List and Detail views.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('requester', 'assigned_to', 'related_order', 'related_order__product')
    """
    url = serializers.HyperlinkedIdentityField(
        view_name='store:ticket-detail', # Ensure view name is correct
        lookup_field='pk', # Assuming Ticket PK is Int or UUID
        help_text="URL link to this support ticket resource."
    )
    requester = UserPublicSerializer(read_only=True, help_text="The user who created the ticket.")
    assigned_to = UserPublicSerializer(read_only=True, allow_null=True, help_text="The staff member assigned to the ticket (if any).")
    status_display = serializers.CharField(source='get_status_display', read_only=True, help_text="Human-readable ticket status.")
    # Link to related order if applicable
    related_order = serializers.HyperlinkedRelatedField(
        view_name='store:order-detail',
        read_only=True,
        lookup_field='pk', # Assuming Order PK
        allow_null=True, # Allow tickets not related to an order
        help_text="Link to the related order, if any."
    )
    # Include minimal product info for context if order is linked
    related_order_product_name = serializers.CharField(source='related_order.product.name', read_only=True, allow_null=True, help_text="Product name if ticket is linked to an order.")

    class Meta:
        model = SupportTicket
        fields = (
            'id', 'url', 'subject', 'requester', 'assigned_to',
            'status', # Raw status value
            'status_display', # Human-readable status
            'created_at', 'updated_at',
            'related_order', # Link to order
            'related_order_product_name', # Context field
            # Add other relevant base fields: 'priority', 'category', etc.
        )
        read_only_fields = (
            'id', 'url', 'requester', 'assigned_to', 'status_display',
            'created_at', 'updated_at', 'related_order', 'related_order_product_name',
            # 'status' and 'subject' might be updated by authorized users (staff, sometimes original requester)
            # via specific API actions (e.g., PATCH), so generally read-only in base GET representation.
        )

class SupportTicketListSerializer(SupportTicketBaseSerializer):
    """
    Serializer specifically for listing support tickets (concise view).
    Adds summary fields like message count and last updated time.
    Performance Recommendation: ViewSet should use annotation for counts:
        queryset.annotate(message_count=Count('messages'), last_message_at=Max('messages__sent_at'))
    """
    # Example summary fields requiring queryset annotation in the view
    message_count = serializers.IntegerField(read_only=True, required=False, help_text="Total number of messages in the ticket.")
    last_message_at = serializers.DateTimeField(read_only=True, required=False, help_text="Timestamp of the last message sent.")

    class Meta(SupportTicketBaseSerializer.Meta):
        # Inherit fields from Base, potentially refine for list view if Base is too verbose.
        fields = SupportTicketBaseSerializer.Meta.fields + ('message_count', 'last_message_at')
        # Inherit read_only_fields from Base. Counts/timestamps are also read-only.
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('message_count', 'last_message_at')


class SupportTicketDetailSerializer(SupportTicketBaseSerializer):
    """
    Serializer for viewing a single support ticket, including its messages.
    Also handles the *creation* of a new ticket with its initial message via POST.
    Security Note: Decryption of individual messages happens separately in the view or serializer's to_representation.
    Performance Recommendation: Associated ViewSet should use:
        queryset.select_related('requester', 'assigned_to', 'related_order', 'related_order__product')
                .prefetch_related(Prefetch('messages', queryset=TicketMessage.objects.select_related('sender').order_by('sent_at')))
    """
    # Messages associated with this ticket. Read-only representation.
    # The view is responsible for passing the decrypted body for each message if applicable.
    messages = TicketMessageSerializer(many=True, read_only=True, help_text="Messages within this ticket (decryption handled by view/serializer).")

    # --- Fields for CREATING a new ticket (used on POST to the ticket list endpoint) ---
    # 'subject' is inherited and should be writable on create.
    subject = serializers.CharField(required=True, max_length=255) # Make subject explicitly required on create

    # Initial message content (view MUST encrypt this before saving TicketMessage)
    # Renamed for clarity in perform_create hook
    initial_message_body = serializers.CharField(
        write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000,
        label="Initial Message", help_text="The first message for your new ticket (will be PGP encrypted)."
    )
    # Optional: Link to an order when creating the ticket
    # Use PrimaryKeyRelatedField for better validation and instance passing
    related_order_id_write = serializers.PrimaryKeyRelatedField( # Ensure this matches Order PK type
        queryset=Order.objects.all(), # Validation logic added below
        write_only=True, required=False, allow_null=True, source='related_order',
        label="Related Order ID (Optional)", help_text="ID (PK) of an order to link to this new ticket."
    )
    # --- End Create Fields ---

    class Meta(SupportTicketBaseSerializer.Meta):
        # Explicitly define fields to control order and include create/detail fields
        fields = SupportTicketBaseSerializer.Meta.fields + (
            'messages', # Read-only messages list for detail view (GET)
            # Fields specific to POST (create) request:
            'initial_message_body', # Write-only initial message
            'related_order_id_write', # Write-only order link
        )
        # Read-only fields inherited, plus 'messages' list itself for GET requests.
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('messages',)
        # Writable on create (POST): 'subject', 'initial_message_body', 'related_order_id_write' (source='related_order')
        # Status updates, assigning staff, closing tickets should be handled by separate API endpoints/actions
        # (e.g., PATCH /tickets/{id}/assign, POST /tickets/{id}/close) with appropriate permissions.
        extra_kwargs = {
            # Ensure subject is writable for create but also readable for detail
            # Allow subject modification via PATCH by removing it from read_only_fields if needed (staff only).
            'subject': {'write_only': False, 'required': True},
        }

    def validate_related_order_id_write(self, value: Optional[Order]) -> Optional[Order]:
        """Validate that the related order exists and belongs to the user creating the ticket (if not staff)."""
        if value is None:
            return None # Optional field

        request_user = self.context['request'].user
        if not request_user or not request_user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        # Order instance is already fetched by PrimaryKeyRelatedField
        order = value

        # Check if the user is the buyer or vendor for the related order OR if staff
        if not getattr(request_user, 'is_staff', False):
            if order.buyer != request_user and order.vendor != request_user:
                raise serializers.ValidationError("You can only link tickets to orders you are associated with.")
        return order

    # --- Potentially add to_representation for message decryption ---
    # def to_representation(self, instance):
    #     """ Optionally handle message decryption here based on request user. """
    #     representation = super().to_representation(instance)
    #     request_user = self.context.get('request').user
    #     if request_user and 'messages' in representation:
    #         # Attempt decryption for each message
    #         decrypted_messages = []
    #         for message_data in representation['messages']:
    #             # Assume message model has 'encrypted_body' and a method/service exists
    #             # `pgp_service.decrypt_message_if_recipient(encrypted_body, request_user)`
    #             try:
    #                 # Replace with actual decryption logic
    #                 # decrypted_text = attempt_decryption(message_data.get('encrypted_body'), request_user)
    #                 # message_data['decrypted_body'] = decrypted_text
    #                 pass # Placeholder for decryption logic
    #             except Exception as e:
    #                 logger.error(f"Error decrypting message {message_data.get('id')} for user {request_user.username}: {e}")
    #                 message_data['decrypted_body'] = "[Decryption Error]"
    #             decrypted_messages.append(message_data)
    #         representation['messages'] = decrypted_messages
    #     return representation

    # Note: The creation logic for a SupportTicket and its first TicketMessage
    # needs careful handling in the ViewSet's create() method. It should:
    # 1. Create the SupportTicket instance (setting requester).
    # 2. PGP Encrypt the 'initial_message_body' using the appropriate recipient's key
    #    (initially likely the general support/admin PGP key, or dynamically determined).
    # 3. Create the first TicketMessage instance, linking it to the new ticket and sender.


# --- Utility & Data Structure Serializers ---

class ShippingDataSerializer(serializers.Serializer):
    """
    Serializer to validate the structure of shipping address data.
    Used as nested data within other requests (e.g., encryption, order creation).
    Does NOT save data itself, only validates structure and types.
    """
    # Max lengths should align with corresponding Order model fields if stored denormalized,
    # or simply be reasonable limits for PGP encryption payload size.
    recipient_name = serializers.CharField(max_length=200, required=True, help_text="Full name of the recipient.")
    street_address = serializers.CharField(max_length=255, required=True, help_text="Street address line 1.")
    address_line_2 = serializers.CharField(max_length=255, required=False, allow_blank=True, help_text="Street address line 2 (optional).")
    city = serializers.CharField(max_length=100, required=True, help_text="City.")
    state_province_region = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text="State / Province / Region (optional where applicable).")
    postal_code = serializers.CharField(max_length=30, required=True, help_text="Postal code / ZIP code.")
    country = serializers.CharField(max_length=100, required=True, help_text="Country name or code.")
    phone_number = serializers.CharField(max_length=30, required=False, allow_blank=True, help_text="Phone number (optional, mainly for delivery purposes).")
    # Consider adding 'shipping_method_selected' if chosen at this stage.
    # shipping_method = serializers.CharField(max_length=100, required=False, allow_blank=True, help_text="Selected shipping method name (optional).")


class EncryptCheckoutDataSerializer(serializers.Serializer):
    """
    Validates a request payload intended for:
    1) Server-side encryption of checkout data (shipping, message) using a vendor's PGP key.
    2) Passing through a client-side pre-encrypted PGP message blob.

    Typically used by an intermediate API endpoint before order creation to obtain the
    encrypted blob needed for the Order.
    """
    # --- CRITICAL: Ensure User PK Type Matches ---
    # Use UUIDField if your User model uses UUIDs as primary keys.
    # vendor_id = serializers.UUIDField(required=True, help_text="The UUID of the target vendor.")
    vendor_id = serializers.PrimaryKeyRelatedField(
         queryset=User.objects.filter(is_vendor=True, is_active=True), # Validate vendor exists and is active
         required=True,
         help_text="The ID of the target vendor."
    )
    # --- End Critical Note ---

    # Option 1: Provide structured data for server-side encryption
    shipping_data = ShippingDataSerializer(required=False, allow_null=True, help_text="Structured shipping details to be encrypted (required for physical goods).")
    buyer_message = serializers.CharField(
        required=False, allow_blank=True, # Allow empty message
        style={'base_template': 'textarea.html'}, max_length=2000,
        help_text="Optional message to the vendor (will be PGP encrypted, max 2000 chars)."
    )

    # Option 2: Provide data already encrypted by the client (full PGP message block)
    pre_encrypted_blob = serializers.CharField(
        required=False, allow_blank=True,
        style={'base_template': 'textarea.html'},
        help_text="Full PGP message block, already encrypted client-side for the vendor's PGP key."
    )

    # Removed validate_vendor_id - PrimaryKeyRelatedField handles existence check.
    # We still need context['target_vendor'] in validate, set by the view or implicitly by PKRelatedField.

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensures the request provides either data for server-side encryption OR a pre-encrypted blob.
        Requires vendor to have a PGP key for server-side encryption.
        Requires *some* data if the endpoint's purpose is encryption/passthrough.
        """
        # PrimaryKeyRelatedField populates `data['vendor_id']` with the User instance if valid.
        vendor: Optional[User] = data.get('vendor_id')
        if not vendor:
             # This should not happen if PKRelatedField validation worked, but defensive check.
             raise serializers.ValidationError({"vendor_id": "Vendor validation failed unexpectedly. Ensure vendor exists and is active."})

        # Store vendor in context for potential use in the view (optional, as it's already in data)
        self.context['target_vendor'] = vendor

        shipping_data = data.get('shipping_data')
        buyer_message = data.get('buyer_message')
        pre_encrypted_blob = data.get('pre_encrypted_blob')

        # Use strip() to treat whitespace-only strings as empty/absent for validation logic
        has_structured_shipping = bool(shipping_data) # ShippingDataSerializer ensures structure if present
        has_buyer_message = bool(buyer_message and str(buyer_message).strip()) # Check strip after ensuring it's stringifiable
        has_pre_encrypted = bool(pre_encrypted_blob and str(pre_encrypted_blob).strip())

        # Determine if *any* data intended for server-side encryption was provided
        has_data_for_server_encryption = has_structured_shipping or has_buyer_message

        # --- Validation Logic ---

        # Rule 1: Cannot provide both methods
        if has_data_for_server_encryption and has_pre_encrypted:
            raise serializers.ValidationError(
                "Provide either structured data (shipping_data/buyer_message) for server-side encryption, "
                "OR a pre_encrypted_blob, but not both."
            )

        # Rule 2: Server-side encryption requires data and vendor PGP key
        if has_data_for_server_encryption:
            if not vendor.pgp_public_key:
                # Use a specific error code for frontend handling if needed
                raise serializers.ValidationError(
                    {"vendor_id": f"Vendor '{vendor.username}' does not have a PGP public key available for server-side encryption."},
                    code='vendor_pgp_key_missing'
                )
            # Potentially add validation: Physical goods require shipping_data
            # product_type = self.context.get('product_type') # Needs product context passed in from view
            # if product_type == 'physical' and not has_structured_shipping:
            #     raise serializers.ValidationError({"shipping_data": "Shipping data is required for physical products."})

        # Rule 3: Pre-encrypted blob requires basic format check
        elif has_pre_encrypted:
            # Basic format validation for the PGP blob (sanity check)
            blob_content = str(pre_encrypted_blob).strip() # Ensure string for startswith/endswith
            if not blob_content.startswith('-----BEGIN PGP MESSAGE-----') or \
               not blob_content.endswith('-----END PGP MESSAGE-----'):
                raise serializers.ValidationError({
                    "pre_encrypted_blob": "Invalid PGP message format. Ensure the complete block including header/footer was provided."
                })
            # Note: Server does NOT validate *who* the blob is encrypted for here.
            # The vendor will fail decryption later if it's wrong.

        # Rule 4: Must provide *some* data (either for server encrypt or pre-encrypted)
        else:
            # Scenario: No relevant data provided at all
            # Adjust this if the endpoint *can* legitimately receive no data (e.g., digital goods with no message).
            raise serializers.ValidationError(
                "You must provide either data to be encrypted ('shipping_data' and/or 'buyer_message') "
                "or a 'pre_encrypted_blob'."
            )

        # Replace vendor_id (User instance) with just the ID if needed by the view,
        # or the view can access vendor.id directly from the instance. Keeping instance for now.
        # data['vendor_id'] = vendor.id

        return data


# --- Global Settings / Site Info Serializers ---

class CanarySerializer(serializers.ModelSerializer):
    """
    Serializer for publicly displaying Warrant Canary details from GlobalSettings.
    Assumes a single GlobalSettings instance exists (e.g., fetched via GlobalSettings.load()).
    """
    class Meta:
        model = GlobalSettings
        fields = (
            'canary_content',             # The text content of the canary statement
            'canary_last_updated',        # Date the canary was last affirmed/updated
            'canary_pgp_signature',       # Detached PGP signature of (content + date)
            'canary_signing_key_fingerprint', # Fingerprint of the PGP key used for signing
            'canary_signing_key_url',     # Optional URL to fetch/verify the signing PGP key
        )
        read_only_fields = fields # Canary data is read-only via this API endpoint

class SiteInformationSerializer(serializers.ModelSerializer):
    """Serializer for general public site information stored in GlobalSettings."""
    # Example - adjust fields based on what's in GlobalSettings model
    class Meta:
        model = GlobalSettings
        fields = (
            'site_name',
            'maintenance_mode',
            'registration_open',
            'site_message', # General announcement message
            'supported_currencies', # List or JSON of active cryptos
            # Add other relevant public settings
        )
        read_only_fields = fields

class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for user-specific notifications.
    Assumes the corresponding API endpoint is restricted to the authenticated user
    (e.g., /api/me/notifications/) and fetches notifications for that user only.
    Performance Recommendation: ViewSet may use select_related('user') internally
    if needed, but 'user' field is typically excluded from the response.
    """
    level_display = serializers.CharField(source='get_level_display', read_only=True, help_text="Human-readable notification level (e.g., Info, Warning, Success, Error).")
    # Consider adding an action_required field if applicable

    class Meta:
        model = Notification
        fields = (
            'id',             # Notification unique ID
            # 'user',         # Excluded: Endpoint should be user-specific.
            'level',          # Raw level value (e.g., INFO, WARNING) stored in DB
            'level_display',  # Human-readable level for frontend
            'message',        # The notification text content
            'link',           # URL the notification links to, if any (relative or absolute)
            'is_read',        # Boolean status indicating if user has marked it read
            'created_at',     # Timestamp when the notification was generated
            # 'expires_at'    # Optional: Timestamp when notification should be auto-removed/hidden
        )
        read_only_fields = (
            'id',
            'level',
            'level_display',
            'message',
            'link',
            'created_at',
            # 'user', # Excluded
            # 'is_read' status is typically updated via a dedicated 'mark read' API action
            # (e.g., POST /notifications/mark-read or PATCH /notifications/{id}/read),
            # making it read-only in the standard GET/list representation.
        )

# --- Deprecated Serializers (Example - Keep only if needed for reference/migration planning) ---
# class EncryptForVendorRequestSerializer(serializers.Serializer):
#     """
#     DEPRECATED: Replaced by EncryptCheckoutDataSerializer which offers more flexibility.
#     Kept temporarily for reference during transition/migration if necessary.
#     """
#     vendor_id = serializers.IntegerField(required=True) # Ensure type matches User PK
#     shipping_data = ShippingDataSerializer(required=True)
#     # Removed on [Date] - Safe to delete after [Date + buffer]