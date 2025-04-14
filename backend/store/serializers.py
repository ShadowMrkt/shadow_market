# backend/store/serializers.py
# Revision: 2.3 (Added WebAuthnCredential Import)
# Date: 2025-04-13 # Updated Date based on current time
# Author: The Void # Corrected Author based on user request
# Changes:
# - Rev 2.3:
#   - FIXED: Added missing import for `WebAuthnCredential` from .models.
# - Rev 2.2:
#   - FIXED: Corrected reference to Currency choices in CRYPTO_PRECISION_MAP.
#     Changed `Order.CurrencyChoices` to the correct top-level `Currency` class.
# - Rev 2.1:
#   - FIXED: Corrected import for Notification model. Moved from store.models to notifications.models.
# - Rev 2:
#   - ADDED: VendorApplicationSerializer for vendor application API endpoints.
#   - ADDED: ExchangeRateSerializer for exchange rate API endpoint.
#   - ADDED BACK: SiteInformationSerializer (was present in Rev 1).
#   - Ensured DecimalAsStringField used for crypto amounts in new serializers.
#   - Adjusted UserPublicSerializer field 'vendor_level_name' based on Rev 1 code.
#   - Ensured models required by new serializers are imported.
# - Rev 1 (2025-04-07):
#   - Strengthened CurrentUserSerializer password validation logic in validate() and update().
#   - Added critical dependency warning about denormalization risks in VendorPublicProfileSerializer docstring.
#   - Added basic schema validation for shipping_options JSONField in ProductSerializer via validate_shipping_options().
#   - Ensured EncryptCheckoutDataSerializer validate() explicitly checks for vendor PGP key for server encryption path.
#   - Added json import for validation.


# Standard Library Imports
import logging
import json # Added for JSON validation
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Union, List, Type # Added/Updated Type

# Third-Party Imports
from django.conf import settings
from django.db.models import Avg # Keep if potentially used indirectly or planned
from django.core.exceptions import ImproperlyConfigured # Added for Notification import handling
from rest_framework import serializers

# Local Application Imports
# Ensure models are correctly defined and accessible
from .models import (
    User, Category, Product, Order, CryptoPayment, Feedback,
    SupportTicket, TicketMessage, # Removed Notification
    GlobalSettings, VendorApplication, WebAuthnCredential, # <-- ADDED WebAuthnCredential
    Currency, FiatCurrency, # Assuming Currency choices are in models or constants
    # ORDER_STATUS_PENDING_PAYMENT etc. constants (if needed directly)
)
# Import models from OTHER apps
try:
    from notifications.models import Notification # <-- IMPORTED FROM notifications APP
except ImportError:
    # Handle case where notifications app might be missing if it's optional
    # Or raise an error if it's required
    logger = logging.getLogger(__name__) # Define logger if needed
    logger.error("Failed to import Notification model from notifications app. Is the app installed and configured?")
    # Depending on requirements, you might fallback or raise:
    Notification = None # Fallback if Notification usage is conditional
    # raise ImproperlyConfigured("Notification model is required but notifications app is missing or model not found.")

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
# --- Using Currency choices from models --- <-- CORRECTED COMMENT
CRYPTO_PRECISION_MAP = {
    Currency.XMR: 12, # Use the top-level Currency class <-- CORRECTED
    Currency.BTC: 8,  # Use the top-level Currency class <-- CORRECTED
    Currency.ETH: 18, # Use the top-level Currency class <-- CORRECTED
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
    DEFAULT_MAX_DIGITS = 36 # Maximum allowed digits (increased for atomic units) - Adjusted from Rev 1
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
    # --- Adjusted based on Rev 1 code: using vendor_level_name from model directly ---
    vendor_level_display = serializers.CharField(source='vendor_level_name', read_only=True, required=False, help_text="Display name for the vendor level.")

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'date_joined',
            'is_vendor',
            'vendor_level_name', # Use denormalized name field from model
            'vendor_avg_rating', # Show public rating (Assuming exists on User model)
            'vendor_rating_count', # Show number of ratings (Assuming exists on User model)
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
    vendor_avg_rating = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's average rating (denormalized).")
    vendor_completion_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order completion rate % (denormalized).")
    vendor_dispute_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order dispute rate % (denormalized).")
    # Removed vendor_bond_amount_display from Rev 1 as new VendorApplication model handles bond details

    # --- Adjusted based on Rev 1 code ---
    vendor_level_display = serializers.CharField(source='vendor_level_name', read_only=True, help_text="Display name for the vendor level.")

    class Meta:
        model = User
        # Ensure these field names exactly match the User model's denormalized fields
        fields = [
            'id',
            'username',
            'date_joined',
            'approved_vendor_since', # Date vendor status was approved
            'pgp_public_key',       # Public PGP key for secure communication
            'vendor_level_name',    # Display name (e.g., "Gold") - Adjusted from Rev 1
            'vendor_avg_rating',
            'vendor_rating_count',
            'vendor_total_orders',   # Consider renaming for clarity if needed (e.g., vendor_lifetime_sales_count)
            'vendor_completed_orders_30d', # Optional: Recent performance indicator
            'vendor_completion_rate_percent',
            'vendor_dispute_rate_percent',
            # 'vendor_bond_paid',          # Check VendorApplication status instead
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
    password = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        min_length=getattr(settings, 'AUTH_PASSWORD_MIN_LENGTH', 12),
        label="New Password", help_text=f"Enter your new password (min {getattr(settings, 'AUTH_PASSWORD_MIN_LENGTH', 12)} chars)."
    )
    password_confirm = serializers.CharField(
        write_only=True, required=False, style={'input_type': 'password'},
        label="Confirm New Password", help_text="Enter your new password again."
    )

    # --- NEW: Read-only field to show vendor application status ---
    # Assuming VendorApplication has a OneToOne relationship with User (related_name='vendor_application')
    # If it's ForeignKey from App -> User, adjust source.
    vendor_application_status = serializers.CharField(
        source='vendor_application.get_status_display', # Access related obj and get display value
        read_only=True,
        required=False,
        allow_null=True, # Allow null if no application exists
        help_text="Status of your vendor application, if any."
    )
    # --- END NEW ---

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', # Email management depends on application rules (verify if changeable)
            'pgp_public_key', 'is_vendor',
            # --- Adjusted based on Rev 1 code ---
            'vendor_level_name', # Changed vendor_level to vendor_level_name
            'btc_withdrawal_address', 'eth_withdrawal_address', 'xmr_withdrawal_address', # Add other cryptos
            'login_phrase', # Security feature, usually read-only after creation
            'date_joined', 'last_login',
            # Write-only fields for password change:
            'current_password', 'password', 'password_confirm',
            # --- NEW ---
            'vendor_application_status', # Added read-only status field
            # Add other user-configurable settings fields here
        )
        read_only_fields = (
            'id', 'username',
            'is_vendor', 'vendor_level_name', # Status managed by admins/system - Adjusted
            'date_joined', 'last_login', 'login_phrase',
            'vendor_application_status', # Status is read-only
            'email', # Make writable only if users can change their email AND verification is implemented.
        )
        extra_kwargs = {
            'email': {'read_only': True}, # Example: Explicitly mark email as read-only
        }

    # --- validate() and update() methods from Rev 1 ---
    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # (Keep the improved validation logic from Revision 1)
        new_password = data.get('password')
        confirm_password = data.get('password_confirm')
        current_password = data.get('current_password')
        password_fields_in_request = any(
            field in self.initial_data for field in ['password', 'password_confirm', 'current_password']
        )
        if password_fields_in_request:
            errors: Dict[str, List[str]] = {}
            if not new_password: errors.setdefault('password', []).append("This field is required for password change.")
            if not confirm_password: errors.setdefault('password_confirm', []).append("This field is required for password change.")
            if not current_password: errors.setdefault('current_password', []).append("This field is required to change the password.")
            if new_password and confirm_password and new_password != confirm_password:
                errors.setdefault('password_confirm', []).append("New passwords do not match.")
            if errors:
                raise serializers.ValidationError(errors)
        return data

    def update(self, instance: User, validated_data: Dict[str, Any]) -> User:
        # (Keep the improved update logic from Revision 1)
        new_password = validated_data.pop('password', None)
        validated_data.pop('password_confirm', None)
        current_password = validated_data.pop('current_password', None)
        password_changed = False
        if new_password and current_password:
            if not instance.check_password(current_password):
                raise serializers.ValidationError({"current_password": ["Current password is not correct."]}, code='invalid_current_password')
            try:
                instance.set_password(new_password)
                password_changed = True
                logger.info(f"Password updated successfully for user {instance.username} (ID: {instance.id})")
            except Exception as e:
                logger.error(f"Error setting new password for user {instance.username} (ID: {instance.id}): {e}")
                raise serializers.ValidationError({"password": ["An error occurred while updating the password."]})
        elif new_password and not current_password:
            logger.error(f"Update attempt for user {instance.id} reached `update` with new_password but no current_password.")
            raise serializers.ValidationError({"current_password": ["Current password is required to set a new password."]})

        update_fields = list(validated_data.keys())
        for attr, value in validated_data.items():
            if attr not in self.Meta.read_only_fields:
                setattr(instance, attr, value)
            else:
                logger.warning(f"Attempted to update read-only field '{attr}' during User update for {instance.username}.")

        allowed_update_fields = [f for f in update_fields if f not in self.Meta.read_only_fields]
        if password_changed:
            allowed_update_fields.append('password')
        if allowed_update_fields:
            instance.save(update_fields=allowed_update_fields)
        elif password_changed: # Handle case where ONLY password changed
            instance.save(update_fields=['password'])

        return instance

# --- Category Serializer ---
# (Keep CategorySerializer as is from Revision 1)
class CategorySerializer(serializers.HyperlinkedModelSerializer):
    """Serializer for Product Categories, including hyperlinking."""
    url = serializers.HyperlinkedIdentityField(
        view_name='store:category-detail',
        lookup_field='slug',
        help_text="URL link to this category resource."
    )
    parent = serializers.HyperlinkedRelatedField(
        view_name='store:category-detail',
        lookup_field='slug',
        read_only=True,
        allow_null=True,
        help_text="Link to the parent category, if any."
    )
    class Meta:
        model = Category
        fields = ('id', 'url', 'name', 'slug', 'description', 'parent')
        read_only_fields = ('id', 'slug')

# --- Product Serializer ---
# (Keep ProductSerializer as is from Revision 1, including validate_shipping_options)
class ProductSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name='store:product-detail',
        lookup_field='slug',
        help_text="URL link to this product resource."
    )
    vendor = UserPublicSerializer(read_only=True, help_text="Public information of the vendor selling this product.")
    category = CategorySerializer(read_only=True, help_text="Category this product belongs to.")

    # --- CORRECTED CURRENCY REFERENCE ---
    price_xmr = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.XMR], required=False, allow_null=True, help_text="Price in Monero (XMR), as string.")
    price_btc = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.BTC], required=False, allow_null=True, help_text="Price in Bitcoin (BTC), as string.")
    price_eth = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.ETH], required=False, allow_null=True, help_text="Price in Ethereum (ETH), as string.")

    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category', write_only=True, required=True,
        help_text="ID of the category this product belongs to (required for create/update)."
    )
    shipping_options = serializers.JSONField(
        required=False, allow_null=True,
        help_text=(
            "JSON list defining shipping options. Each item must be an object "
            "with 'name' (string), and price fields (e.g., 'price_xmr', 'price_btc') as strings. "
            "Example: [{'name': 'Standard', 'price_xmr': '0.05'}, {'name': 'Express', 'price_xmr': '0.15'}]"
        )
    )
    average_rating = DecimalAsStringField(read_only=True, decimal_places=2, required=False, help_text="Average feedback rating for this product.")
    sales_count = serializers.IntegerField(read_only=True, required=False, help_text="Number of times this product has been sold.")
    is_digital = serializers.BooleanField(read_only=True, required=False, help_text="Indicates if the product is digital (derived from shipping info).") # Added is_digital

    class Meta:
        model = Product
        fields = (
            'id', 'url', 'vendor', 'category', 'name', 'slug', 'description',
            'price_xmr', 'price_btc', 'price_eth',
            'accepted_currencies',
            'quantity', 'ships_from', 'ships_to', 'shipping_options',
            'is_active', 'is_featured', 'is_digital', # Added is_digital
            'sales_count', 'average_rating',
            'created_at', 'updated_at',
            'category_id',
        )
        read_only_fields = (
            'id', 'slug', 'vendor', 'category',
            'sales_count', 'average_rating', 'is_digital', # Added is_digital
            'created_at', 'updated_at'
        )

    def validate_shipping_options(self, value: Optional[Any]) -> Optional[List[Dict[str, Any]]]:
        # (Keep validation logic from Revision 1)
        if value is None: return None
        if not isinstance(value, list): raise serializers.ValidationError("Shipping options must be a JSON list.")
        if not value: return value

        validated_options = []
        expected_price_keys = {f'price_{code.lower()}' for code, _ in Currency.choices} # Use Currency model

        for index, option in enumerate(value):
            if not isinstance(option, dict): raise serializers.ValidationError(f"Item at index {index} is not a valid JSON object.")
            option_name = option.get('name')
            if not option_name or not isinstance(option_name, str) or not option_name.strip(): raise serializers.ValidationError(f"Item at index {index} must have a non-empty 'name' string.")

            has_at_least_one_price = False
            for key, price_str in option.items():
                if key.startswith('price_'):
                    if key not in expected_price_keys: logger.warning(f"Unexpected price key '{key}' found in shipping_options for product.")
                    if not isinstance(price_str, str): raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) must be a string.")
                    try:
                        price_decimal = Decimal(price_str)
                        if price_decimal < Decimal('0.0'): raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) cannot be negative.")
                    except InvalidOperation: raise serializers.ValidationError(f"Price '{key}' in option '{option_name}' (index {index}) is not a valid decimal string.")
                    has_at_least_one_price = True

            if not has_at_least_one_price: raise serializers.ValidationError(f"Shipping option '{option_name}' (index {index}) must define at least one valid price.")
            validated_options.append(option)
        return validated_options

# --- CryptoPayment Serializer ---
# (Keep CryptoPaymentSerializer as is from Revision 1)
class CryptoPaymentSerializer(serializers.ModelSerializer):
    expected_amount_native = serializers.SerializerMethodField(help_text="Expected payment amount in the native cryptocurrency (string).")
    received_amount_native = serializers.SerializerMethodField(help_text="Received payment amount in the native cryptocurrency (string).")
    order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk', help_text="Link to the associated order.")
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)

    class Meta:
        model = CryptoPayment
        fields = (
            'id', 'order', 'currency', 'currency_display', 'payment_address',
            'payment_id_monero', 'expected_amount_native', 'received_amount_native',
            'is_confirmed', 'confirmations_received', 'confirmations_needed',
            'transaction_hash', 'created_at', 'updated_at',
        )
        read_only_fields = fields

    def _format_crypto_amount(self, amount: Optional[Decimal], currency: Optional[str]) -> Optional[str]:
        if amount is None or currency is None: return None
        try:
            d_amount = Decimal(str(amount))
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            return d_amount.quantize(quantize_exp).to_eng_string()
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format crypto amount '{amount}' for currency '{currency}': {e}")
            return str(amount)

    def get_expected_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        return self._format_crypto_amount(obj.expected_amount_native, obj.currency)

    def get_received_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        return self._format_crypto_amount(obj.received_amount_native, obj.currency)

# --- Feedback Serializer ---
# (Keep FeedbackSerializer as is from Revision 1)
class FeedbackSerializer(serializers.ModelSerializer):
    reviewer = UserPublicSerializer(read_only=True, help_text="User who wrote the feedback.")
    recipient = UserPublicSerializer(read_only=True, help_text="User who received the feedback (vendor or buyer).")
    order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk', help_text="Link to the order this feedback relates to.")
    product_name = serializers.CharField(source='order.product.name', read_only=True, help_text="Name of the product associated with the order.")
    order_id = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(), # Validation logic ensures eligibility
        write_only=True, required=True, source='order',
        help_text="The ID (PK) of the order this feedback is for (required on create)."
    )
    rating = serializers.IntegerField(min_value=1, max_value=5, required=True, help_text="Overall rating (1-5 stars).")
    comment = serializers.CharField(max_length=2000, required=True, style={'base_template': 'textarea.html'}, help_text="Feedback comment (max 2000 chars).")
    rating_quality = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    rating_shipping = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    rating_communication = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)

    class Meta:
        model = Feedback
        fields = (
            'id', 'order', 'product_name', 'reviewer', 'recipient',
            'rating', 'comment', 'feedback_type', 'feedback_type_display',
            'rating_quality', 'rating_shipping', 'rating_communication',
            'created_at', 'order_id',
        )
        read_only_fields = (
            'id', 'order', 'product_name', 'reviewer', 'recipient',
            'feedback_type', 'feedback_type_display', 'created_at'
        )

    def validate_order_id(self, order: Order) -> Order:
        request_user = self.context['request'].user
        if not request_user or not request_user.is_authenticated: raise serializers.ValidationError("Auth required.")
        is_buyer = order.buyer == request_user
        is_vendor = order.vendor == request_user
        if not is_buyer and not is_vendor: raise serializers.ValidationError("You are not associated with this order.")
        recipient = order.vendor if is_buyer else order.buyer
        if Feedback.objects.filter(order=order, reviewer=request_user, recipient=recipient).exists():
            raise serializers.ValidationError("You have already left feedback for this order.")

        # Use correct Order Status inner class
        FEEDBACK_ELIGIBLE_STATUSES = [Order.StatusChoices.FINALIZED, Order.StatusChoices.DISPUTE_RESOLVED] # Adjusted based on models.py

        if order.status not in FEEDBACK_ELIGIBLE_STATUSES:
            allowed_statuses_str = ", ".join([str(s) for s in FEEDBACK_ELIGIBLE_STATUSES])
            raise serializers.ValidationError(f"Feedback can only be left for orders with status: {allowed_statuses_str}.")
        return order

    def create(self, validated_data: Dict[str, Any]) -> Feedback:
        request_user = self.context['request'].user
        order: Order = validated_data['order']
        validated_data['reviewer'] = request_user

        # Use correct Feedback Type inner class (assuming it exists in models.py)
        if order.buyer == request_user:
            validated_data['recipient'] = order.vendor
            # Assuming FeedbackType.FROM_BUYER exists:
            # validated_data['feedback_type'] = Feedback.FeedbackType.FROM_BUYER
        elif order.vendor == request_user:
            validated_data['recipient'] = order.buyer
            # Assuming FeedbackType.FROM_VENDOR exists:
            # validated_data['feedback_type'] = Feedback.FeedbackType.FROM_VENDOR
        else:
            logger.error(f"CRITICAL: User {request_user.id} is not buyer/vendor for order {order.id} in feedback create.")
            raise serializers.ValidationError("Internal error: Cannot determine feedback recipient.")
        try:
            feedback = super().create(validated_data)
            logger.info(f"Feedback created (ID: {feedback.id}) for Order {order.id} by User {request_user.id}.")
            # Note: FeedbackType calculation happens in Feedback.save() override based on rating
            return feedback
        except Exception as e:
            logger.error(f"Error creating feedback for order {order.id} by user {request_user.id}: {e}")
            raise serializers.ValidationError("An error occurred while saving feedback.")

# --- Order Serializers ---
# (Keep OrderBaseSerializer, OrderBuyerSerializer, OrderVendorSerializer as is from Revision 1)
class OrderBaseSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:order-detail', lookup_field='pk', help_text="URL link to this order resource.")
    product = ProductSerializer(read_only=True, help_text="Details of the product ordered.")
    total_price_native_selected = serializers.SerializerMethodField(help_text="Total price in the selected cryptocurrency, formatted as string for precision.")
    selected_currency_display = serializers.CharField(source='get_selected_currency_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True, help_text="Human-readable order status.")
    release_signature_buyer_present = serializers.SerializerMethodField(help_text="Indicates if buyer's multisig release signature is present.")
    release_signature_vendor_present = serializers.SerializerMethodField(help_text="Indicates if vendor's multisig release signature is present.")

    class Meta:
        model = Order
        fields = (
            'id', 'url', 'product', 'quantity',
            'selected_currency', 'selected_currency_display',
            'total_price_native_selected', 'status', 'status_display',
            'release_initiated', 'release_signature_buyer_present', 'release_signature_vendor_present',
            'release_tx_broadcast_hash',
            'created_at', 'updated_at',
            'payment_deadline', 'auto_finalize_deadline', 'dispute_deadline',
        )
        read_only_fields = fields

    def get_total_price_native_selected(self, obj: Order) -> Optional[str]:
        price = obj.total_price_native_selected
        currency = obj.selected_currency
        if price is None or currency is None: return None
        try:
            d_price = Decimal(str(price))
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            return d_price.quantize(quantize_exp).to_eng_string()
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format total_price_native_selected '{price}' for order {obj.id}: {e}")
            return str(price)

    def get_release_signature_buyer_present(self, obj: Order) -> bool: return bool(obj.release_signature_buyer)
    def get_release_signature_vendor_present(self, obj: Order) -> bool: return bool(obj.release_signature_vendor)

class OrderBuyerSerializer(OrderBaseSerializer):
    vendor = UserPublicSerializer(read_only=True, help_text="Public info of the vendor for this order.")
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True, help_text="Payment details for this order (if generated).")
    feedback = FeedbackSerializer(read_only=True, allow_null=True, help_text="Feedback associated with this order.") # Renamed from feedback_given
    class Meta(OrderBaseSerializer.Meta):
        fields = OrderBaseSerializer.Meta.fields + ('vendor', 'payment', 'feedback')
        read_only_fields = fields

class OrderVendorSerializer(OrderBaseSerializer):
    buyer = UserPublicSerializer(read_only=True, help_text="Public info of the buyer for this order.")
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True, help_text="Payment details for this order (if generated).")
    feedback = FeedbackSerializer(read_only=True, allow_null=True, help_text="Feedback associated with this order.") # Renamed from feedback_received
    has_shipping_info = serializers.SerializerMethodField(help_text="Indicates if encrypted shipping information is present for this order.")
    class Meta(OrderBaseSerializer.Meta):
        fields = OrderBaseSerializer.Meta.fields + ('buyer', 'payment', 'feedback', 'has_shipping_info')
        read_only_fields = fields
    def get_has_shipping_info(self, obj: Order) -> bool: return bool(obj.encrypted_shipping_info)

# --- Support Ticket Serializers ---
# (Keep SupportTicket serializers as is from Revision 1)
class TicketMessageSerializer(serializers.ModelSerializer):
    sender = UserPublicSerializer(read_only=True, help_text="User who sent this message.")
    decrypted_body = serializers.CharField(read_only=True, required=False, allow_null=True, help_text="Decrypted message content (available only if view provides it).")
    message_body = serializers.CharField(write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000, label="Message Content", help_text="Enter your message here (it will be PGP encrypted before sending).")
    class Meta:
        model = TicketMessage
        fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body', 'message_body')
        read_only_fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body')

class SupportTicketBaseSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:ticket-detail', lookup_field='pk', help_text="URL link to this support ticket resource.")
    requester = UserPublicSerializer(read_only=True, help_text="The user who created the ticket.")
    assigned_to = UserPublicSerializer(read_only=True, allow_null=True, help_text="The staff member assigned.")
    status_display = serializers.CharField(source='get_status_display', read_only=True, help_text="Human-readable ticket status.")
    related_order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk', allow_null=True, help_text="Link to the related order.")
    related_order_product_name = serializers.CharField(source='related_order.product.name', read_only=True, allow_null=True, help_text="Product name if ticket is linked.")
    class Meta:
        model = SupportTicket
        fields = ('id', 'url', 'subject', 'requester', 'assigned_to', 'status', 'status_display', 'created_at', 'updated_at', 'related_order', 'related_order_product_name')
        read_only_fields = ('id', 'url', 'requester', 'assigned_to', 'status_display', 'created_at', 'updated_at', 'related_order', 'related_order_product_name')

class SupportTicketListSerializer(SupportTicketBaseSerializer):
    message_count = serializers.IntegerField(read_only=True, required=False, help_text="Total number of messages in the ticket.")
    last_message_at = serializers.DateTimeField(read_only=True, required=False, help_text="Timestamp of the last message sent.")
    class Meta(SupportTicketBaseSerializer.Meta):
        fields = SupportTicketBaseSerializer.Meta.fields + ('message_count', 'last_message_at')
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('message_count', 'last_message_at')

class SupportTicketDetailSerializer(SupportTicketBaseSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True, help_text="Messages within this ticket (decryption handled by view/serializer).")
    subject = serializers.CharField(required=True, max_length=255)
    initial_message_body = serializers.CharField(write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000, label="Initial Message", help_text="The first message for your new ticket (will be PGP encrypted).")
    related_order_id_write = serializers.PrimaryKeyRelatedField(queryset=Order.objects.all(), write_only=True, required=False, allow_null=True, source='related_order', label="Related Order ID (Optional)")
    class Meta(SupportTicketBaseSerializer.Meta):
        fields = SupportTicketBaseSerializer.Meta.fields + ('messages', 'initial_message_body', 'related_order_id_write')
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('messages',)
        extra_kwargs = {'subject': {'write_only': False, 'required': True}}
    def validate_related_order_id_write(self, value: Optional[Order]) -> Optional[Order]:
        if value is None: return None
        request_user = self.context['request'].user
        if not request_user or not request_user.is_authenticated: raise serializers.ValidationError("Auth required.")
        if not getattr(request_user, 'is_staff', False):
            if value.buyer != request_user and value.vendor != request_user:
                raise serializers.ValidationError("Cannot link ticket to order you aren't associated with.")
        return value

# --- Utility & Data Structure Serializers ---
# (Keep ShippingDataSerializer and EncryptCheckoutDataSerializer as is from Revision 1)
class ShippingDataSerializer(serializers.Serializer):
    recipient_name = serializers.CharField(max_length=200, required=True)
    street_address = serializers.CharField(max_length=255, required=True)
    address_line_2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=True)
    state_province_region = serializers.CharField(max_length=100, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=30, required=True)
    country = serializers.CharField(max_length=100, required=True)
    phone_number = serializers.CharField(max_length=30, required=False, allow_blank=True)

class EncryptCheckoutDataSerializer(serializers.Serializer):
    vendor_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_vendor=True, is_active=True), required=True, help_text="The ID of the target vendor.")
    shipping_data = ShippingDataSerializer(required=False, allow_null=True)
    buyer_message = serializers.CharField(required=False, allow_blank=True, style={'base_template': 'textarea.html'}, max_length=2000)
    pre_encrypted_blob = serializers.CharField(required=False, allow_blank=True, style={'base_template': 'textarea.html'})

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        vendor: Optional[User] = data.get('vendor_id')
        if not vendor: raise serializers.ValidationError({"vendor_id": "Vendor validation failed."})
        self.context['target_vendor'] = vendor
        has_structured_shipping = bool(data.get('shipping_data'))
        has_buyer_message = bool(data.get('buyer_message') and str(data['buyer_message']).strip())
        has_pre_encrypted = bool(data.get('pre_encrypted_blob') and str(data['pre_encrypted_blob']).strip())
        has_data_for_server_encryption = has_structured_shipping or has_buyer_message

        if has_data_for_server_encryption and has_pre_encrypted:
            raise serializers.ValidationError("Provide either structured data OR a pre_encrypted_blob, not both.")
        if has_data_for_server_encryption and not vendor.pgp_public_key:
            raise serializers.ValidationError({"vendor_id": f"Vendor '{vendor.username}' has no PGP key for server-side encryption."}, code='vendor_pgp_key_missing')
        if has_pre_encrypted:
            blob_content = str(data['pre_encrypted_blob']).strip()
            if not blob_content.startswith('-----BEGIN PGP MESSAGE-----') or not blob_content.endswith('-----END PGP MESSAGE-----'):
                raise serializers.ValidationError({"pre_encrypted_blob": "Invalid PGP message format."})
        elif not has_data_for_server_encryption:
            raise serializers.ValidationError("Provide either 'shipping_data', 'buyer_message', or 'pre_encrypted_blob'.")
        return data

# --- Global Settings / Site Info Serializers ---
# (Keep CanarySerializer as is from Revision 1)
class CanarySerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalSettings
        fields = ('canary_content', 'canary_last_updated', 'canary_pgp_signature', 'canary_signing_key_fingerprint', 'canary_signing_key_url')
        read_only_fields = fields

# --- ADDED BACK: SiteInformationSerializer ---
class SiteInformationSerializer(serializers.ModelSerializer):
    """Serializer for general public site information stored in GlobalSettings."""
    # Example - adjust fields based on what's in GlobalSettings model
    # Need to match field names from GlobalSettings model
    registration_open = serializers.BooleanField(source='allow_new_registrations', read_only=True)
    vendor_applications_open = serializers.BooleanField(source='allow_new_vendors', read_only=True) # Added field based on model
    # site_message = serializers.CharField(read_only=True) # Add if GlobalSettings has this field
    # supported_currencies = serializers.JSONField(read_only=True) # Add if GlobalSettings has this field

    class Meta:
        model = GlobalSettings
        fields = (
            'site_name',
            'maintenance_mode',
            'registration_open',
            'vendor_applications_open', # Added
            # 'site_message', # Uncomment if field exists
            # 'supported_currencies', # Uncomment if field exists
            # Add other relevant public settings fields here
        )
        read_only_fields = fields
# --- END ADDED BACK ---

# --- Notification Serializer ---
# (Keep NotificationSerializer as is from Revision 1)
class NotificationSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True, help_text="Human-readable notification level.")
    class Meta:
        # Check if Notification variable is None due to failed import
        if Notification is None:
             # Optionally raise an error or define dummy fields if fallback is needed
             # raise ImproperlyConfigured("Notification model could not be imported for NotificationSerializer.")
             # Dummy setup:
             model = None
             fields = ('id', 'message', 'created_at') # Minimal dummy fields
             read_only_fields = fields
        else:
             model = Notification # Uses the Notification model imported from notifications.models
             fields = ('id', 'level', 'level_display', 'message', 'link', 'is_read', 'created_at')
             read_only_fields = ('id', 'level', 'level_display', 'message', 'link', 'created_at')

# --- ADDED: Exchange Rate Serializer ---
class ExchangeRateSerializer(serializers.Serializer):
    """ Serializer for displaying exchange rates fetched from GlobalSettings. """
    btc_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    eth_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    xmr_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    usd_eur_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    # Add other rates as needed (e.g., crypto-to-crypto if fetched)
    rates_last_updated = serializers.DateTimeField(read_only=True, required=False)

    def to_representation(self, instance):
        if not isinstance(instance, GlobalSettings):
            logger.error("ExchangeRateSerializer received unexpected instance type: %s", type(instance))
            return {}
        return {
            'btc_usd_rate': self._format_decimal(instance.btc_usd_rate, 8),
            'eth_usd_rate': self._format_decimal(instance.eth_usd_rate, 8),
            'xmr_usd_rate': self._format_decimal(instance.xmr_usd_rate, 8),
            'usd_eur_rate': self._format_decimal(instance.usd_eur_rate, 8),
            'rates_last_updated': instance.rates_last_updated.isoformat() if instance.rates_last_updated else None,
        }

    def _format_decimal(self, value: Optional[Decimal], places: int) -> Optional[str]:
        if value is None: return None
        try:
            temp_field = DecimalAsStringField(max_digits=36, decimal_places=places)
            return temp_field.to_representation(value)
        except Exception as e:
            logger.warning("Failed to format decimal %s to %d places: %s", value, places, e)
            return str(value)


# --- ADDED: Vendor Application Serializer ---
class VendorApplicationSerializer(serializers.ModelSerializer):
    """ Serializer for viewing Vendor Application status and initiating applications. """
    user = UserPublicSerializer(read_only=True, help_text="The user associated with this application.")
    status_display = serializers.CharField(source='get_status_display', read_only=True, help_text="Human-readable application status.")
    bond_currency = serializers.ChoiceField(
        choices=Currency.choices, # Use Currency model from store.models
        write_only=True, # Made write_only as it's used only for initiation in CreateView
        required=False, # Set required=False as CreateView handles logic
        help_text="Select the cryptocurrency for the bond payment (Currently BTC only)."
    )
    bond_amount_crypto = DecimalAsStringField(read_only=True, required=False, help_text="Required bond amount in the chosen crypto (calculated by server).")
    bond_amount_usd = DecimalAsStringField(read_only=True, decimal_places=2, required=False, help_text="Required bond amount in USD equivalent.")
    bond_payment_address = serializers.CharField(read_only=True, required=False, help_text="Cryptocurrency address to send the bond payment to.")

    class Meta:
        model = VendorApplication # Use VendorApplication model from store.models
        fields = (
            'id', 'user', 'status', 'status_display', 'bond_currency',
            'bond_amount_usd', 'bond_amount_crypto', 'bond_payment_address',
            'rejection_reason', 'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'user', 'status', 'status_display', 'bond_amount_usd',
            'bond_amount_crypto', 'bond_payment_address', 'rejection_reason',
            'created_at', 'updated_at',
        )
        # Removed 'bond_currency' from read_only as it's write_only now

    def to_representation(self, instance: VendorApplication) -> Dict[str, Any]:
        representation = super().to_representation(instance)
        # Hide payment address if bond is not pending
        if instance.status != VendorApplication.StatusChoices.PENDING_BOND:
            representation.pop('bond_payment_address', None)
            # representation.pop('bond_amount_crypto', None) # Optional: hide amount too
        return representation

# --- WebAuthn Serializer ---
# (Keep WebAuthnCredentialSerializer as is from Revision 1)
class WebAuthnCredentialSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    class Meta:
        model = WebAuthnCredential # <-- This will now work because WebAuthnCredential is imported
        fields = ('id', 'user', 'credential_id_b64', 'public_key_b64', 'sign_count', 'transports', 'nickname', 'created_at', 'last_used_at')
        read_only_fields = ('id', 'user', 'created_at', 'last_used_at') # Make fields read-only that shouldn't be set directly by client

#-----End Of File-----#