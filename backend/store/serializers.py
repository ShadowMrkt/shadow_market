# backend/store/serializers.py
# Revision: 3.6 (Ensure field validation errors are lists of strings for test compatibility)
# Date: 2025-05-17
# Author: Gemini
# Changes:
# - Rev 3.6:
#   - FeedbackSerializer.validate_order_id:
#     - Wrapped error messages for 'order_id' in a list to ensure compatibility
#       with test assertions expecting serializer.errors['field_name'][0].
#   - SupportTicketDetailSerializer.validate_related_order_id_write:
#     - Wrapped error messages for 'related_order_id_write' in a list for consistency
#       and to preempt potential issues with test assertions.
# - Rev 3.5: (Fix validation method naming and error messages for test compatibility)
#   - FeedbackSerializer: Renamed validation method `validate_order` to `validate_order_id`
#     to align with the field name `order_id` for DRF's automatic validation discovery.
#     This ensures custom checks for duplicate feedback and order status are triggered.
#   - EncryptCheckoutDataSerializer.validate:
#     - Modified error message for "both data and blob" to "Provide either structured data OR a pre_encrypted_blob"
#       to exactly match test assertion.
#     - Modified error message for "no data no blob" to "Provide either 'shipping_data', 'buyer_message', or 'pre_encrypted_blob'"
#       to exactly match test assertion.
#   - SupportTicketDetailSerializer: Renamed validation method `validate_related_order`
#     to `validate_related_order_id_write` to align with the field name `related_order_id_write`
#     for DRF's automatic validation discovery. This ensures custom checks for order relationship are triggered.
# - Rev 3.4: (Ensure robust validation for feedback and support ticket order linking)
#   - FeedbackSerializer.validate_order:
#     - Re-confirmed and ensured robust check for duplicate feedback: raises ValidationError if feedback from the reviewer to the recipient for the specific order already exists.
#     - Re-confirmed and ensured robust check for order status: raises ValidationError if the order's status is not in the list of statuses eligible for feedback (e.g., FINALIZED, DISPUTE_RESOLVED).
#   - SupportTicketDetailSerializer.validate_related_order:
#     - Re-confirmed and ensured robust check for order ownership: raises ValidationError if a non-staff user attempts to link a support ticket to an order they are not the buyer or vendor of.
# - Rev 3.3: (Refine FeedbackSerializer validation for status and duplicate checks)
#   - FeedbackSerializer.validate_order:
#     - Ensured `recipient_id` is correctly determined for duplicate feedback check.
#     - Corrected order status validation to compare `order_instance.status` (a string value)
#       against a list of eligible status *values* (e.g., `Order.StatusChoices.FINALIZED.value`).
#     - Used `.label` from enum members for more user-friendly error messages.
# - Rev 3.2:
#   - FeedbackSerializer.validate_order:
#     - Correctly determine `recipient_id` within the method scope before checking for duplicate feedback.
#     - Used `.label` for Order.StatusChoices to provide more user-friendly error messages for status validation.
# - Rev 3.1:
#   - SupportTicketDetailSerializer.validate_related_order: Changed user comparison
#     from direct object comparison (e.g., value.buyer != request_user) to
#     comparison by primary key (e.g., value.buyer_id != request_user.pk)
#     to make it more robust against potential object identity issues in tests.
# - (Older revisions omitted for brevity)

# Standard Library Imports
import logging
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Union, List, Type

# Third-Party Imports
from django.conf import settings
from django.db.models import Avg
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError as DjangoCoreValidationError
from rest_framework import serializers
from rest_framework.exceptions import ValidationError as DRFValidationError

# Local Application Imports
from backend.store.models import (
    User, Category, Product, Order, CryptoPayment, Feedback, Dispute,
    SupportTicket, TicketMessage,
    GlobalSettings, VendorApplication, WebAuthnCredential,
    Currency, FiatCurrency,
)
try:
    from backend.notifications.models import Notification
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.error("Failed to import Notification model from notifications app. Is the app installed and configured?")
    Notification = None

try:
    from backend.withdraw.models import WithdrawalRequest, WithdrawalStatusChoices
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.error("Failed to import models from withdraw app. Is the app installed and configured?")
    WithdrawalRequest = None
    WithdrawalStatusChoices = None

try:
    from backend.ledger.models import UserBalance
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.error("Failed to import models from ledger app. Is the app installed and configured?")
    UserBalance = None

try:
    from .validators import (
        validate_bitcoin_address, validate_ethereum_address, validate_monero_address,
        validate_pgp_public_key
    )
    _validators_available = True
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.critical(f"CRITICAL: Failed to import validators from .validators: {e}. Serializers requiring validation will fail.")
    _validators_available = False
    def validate_bitcoin_address(value): raise NotImplementedError("Validator not loaded")
    def validate_ethereum_address(value): raise NotImplementedError("Validator not loaded")
    def validate_monero_address(value): raise NotImplementedError("Validator not loaded")
    def validate_pgp_public_key(value): raise NotImplementedError("Validator not loaded")

logger = logging.getLogger(__name__)

CRYPTO_PRECISION_MAP = {
    Currency.XMR: 12,
    Currency.BTC: 8,
    Currency.ETH: 18,
}
DEFAULT_CRYPTO_PRECISION = 18
LEDGER_DECIMAL_PLACES = 12

class DecimalAsStringField(serializers.DecimalField):
    DEFAULT_MAX_DIGITS = 36
    DEFAULT_DECIMAL_PLACES = 18

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault('max_digits', self.DEFAULT_MAX_DIGITS)
        kwargs.setdefault('decimal_places', self.DEFAULT_DECIMAL_PLACES)
        kwargs.setdefault('coerce_to_string', False)
        super().__init__(*args, **kwargs)

    def to_representation(self, value: Optional[Union[Decimal, str, int, float]]) -> Optional[str]:
        if value is None: return None
        try:
            if not isinstance(value, Decimal):
                d_value = Decimal(str(value))
            else:
                d_value = value
            quantize_exp = Decimal('1e-' + str(self.decimal_places))
            quantized_value = d_value.quantize(quantize_exp)
            return f"{quantized_value:.{self.decimal_places}f}"
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not serialize value '{value}' as Decimal string: {e}")
            return str(value)

    def to_internal_value(self, data: Any) -> Optional[Decimal]:
        if data is None: return None
        try:
            str_data = str(data).strip()
            if not str_data: return None
            d_value = Decimal(str_data)
            if d_value.is_nan(): raise DRFValidationError("Input is Not a Number (NaN).")
            if d_value.is_infinite(): raise DRFValidationError("Input is infinite.")
            sign, digits, exponent = d_value.as_tuple()
            num_digits = len(digits)
            decimal_places = abs(exponent) if exponent < 0 else 0
            int_digits = num_digits - decimal_places
            if int_digits + decimal_places > self.max_digits:
                raise DRFValidationError(f"Ensure that there are no more than {self.max_digits} digits in total.")
            if decimal_places > self.decimal_places:
                raise DRFValidationError(f"Ensure that there are no more than {self.decimal_places} decimal places.")
            if not self.allow_null and d_value is None:
                raise DRFValidationError("This field may not be null.")
            return d_value
        except (InvalidOperation, TypeError, ValueError) as e:
            raise DRFValidationError(f"Invalid decimal value: {e}") from e

class UserPublicSerializer(serializers.ModelSerializer):
    vendor_level_display = serializers.CharField(source='vendor_level_name', read_only=True, required=False, help_text="Display name for the vendor level.")
    class Meta:
        model = User
        fields = ('id', 'username', 'date_joined', 'is_vendor', 'vendor_level_name', 'vendor_level_display', 'vendor_avg_rating', 'vendor_rating_count')
        read_only_fields = fields

class VendorPublicProfileSerializer(serializers.ModelSerializer):
    vendor_avg_rating = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's average rating (denormalized).")
    vendor_completion_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order completion rate % (denormalized).")
    vendor_dispute_rate_percent = DecimalAsStringField(read_only=True, decimal_places=2, help_text="Vendor's order dispute rate % (denormalized).")
    vendor_level_display = serializers.CharField(source='vendor_level_name', read_only=True, help_text="Display name for the vendor level.")
    class Meta:
        model = User
        fields = [
            'id', 'username', 'date_joined', 'approved_vendor_since', 'pgp_public_key',
            'vendor_level_name', 'vendor_level_display',
            'vendor_avg_rating', 'vendor_rating_count', 'vendor_total_orders',
            'vendor_completed_orders_30d', 'vendor_completion_rate_percent', 'vendor_dispute_rate_percent',
            'vendor_reputation_last_updated', 'profile_description',
        ]
        read_only_fields = fields

class CurrentUserSerializer(serializers.ModelSerializer):
    btc_withdrawal_address = serializers.CharField(validators=[validate_bitcoin_address] if _validators_available else [], required=False, allow_blank=True, allow_null=True, max_length=95)
    eth_withdrawal_address = serializers.CharField(validators=[validate_ethereum_address] if _validators_available else [], required=False, allow_blank=True, allow_null=True, max_length=42)
    xmr_withdrawal_address = serializers.CharField(validators=[validate_monero_address] if _validators_available else [], required=False, allow_blank=True, allow_null=True, max_length=106)
    pgp_public_key = serializers.CharField(style={'base_template': 'textarea.html', 'rows': 10}, validators=[validate_pgp_public_key] if _validators_available else [], required=False, allow_blank=True, allow_null=True)
    current_password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'}, min_length=getattr(settings, 'AUTH_PASSWORD_MIN_LENGTH', 12))
    password_confirm = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    vendor_application_status = serializers.CharField(source='vendor_application.get_status_display', read_only=True, required=False, allow_null=True)
    class Meta:
        model = User
        fields = (
            'id', 'username', 'pgp_public_key', 'is_vendor', 'vendor_level_name',
            'btc_withdrawal_address', 'eth_withdrawal_address', 'xmr_withdrawal_address',
            'login_phrase', 'date_joined', 'last_login',
            'current_password', 'password', 'password_confirm',
            'vendor_application_status',
        )
        read_only_fields = ('id', 'username', 'is_vendor', 'vendor_level_name', 'date_joined', 'last_login', 'login_phrase', 'vendor_application_status')

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        new_password = data.get('password')
        confirm_password = data.get('password_confirm')
        current_password = data.get('current_password')
        
        attempting_password_change = bool(new_password or confirm_password)

        if attempting_password_change:
            errors: Dict[str, List[str]] = {}
            if not new_password:
                errors.setdefault('password', []).append("This field is required when changing password.")
            if not confirm_password:
                errors.setdefault('password_confirm', []).append("This field is required when changing password.")
            if not current_password:
                errors.setdefault('current_password', []).append("This field is required to change the password.")
            
            if new_password and confirm_password and new_password != confirm_password:
                errors.setdefault('password_confirm', []).append("New passwords do not match.")
            
            if errors:
                raise DRFValidationError(errors)
        elif current_password and not (new_password or confirm_password):
            raise DRFValidationError({
                'password': ["This field is required when current_password is provided."],
                'password_confirm': ["This field is required when current_password is provided."]
            })
            
        return data

    def update(self, instance: User, validated_data: Dict[str, Any]) -> User:
        new_password = validated_data.pop('password', None)
        validated_data.pop('password_confirm', None) 
        current_password = validated_data.pop('current_password', None)
        password_changed = False

        if new_password:
            if not current_password:
                raise DRFValidationError({"current_password": ["Current password is required to set a new password."]})
            if not instance.check_password(current_password):
                raise DRFValidationError({"current_password": ["Current password is not correct."]}, code='invalid_current_password')
            try:
                instance.set_password(new_password)
                password_changed = True
                logger.info(f"Password updated successfully for user {instance.username} (ID: {instance.id})")
            except Exception as e:
                logger.error(f"Error setting new password for user {instance.username} (ID: {instance.id}): {e}")
                raise DRFValidationError({"password": ["An error occurred while updating the password."]})
        
        allowed_to_update = {k: v for k, v in validated_data.items() if k not in self.Meta.read_only_fields}
        
        for attr, value in allowed_to_update.items():
            setattr(instance, attr, value)

        update_fields_for_save = list(allowed_to_update.keys())
        if password_changed:
            update_fields_for_save.append('password') 

        if update_fields_for_save:
            instance.save(update_fields=update_fields_for_save)
            
        return instance

class CategorySerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:category-detail', lookup_field='slug')
    parent = serializers.HyperlinkedRelatedField(view_name='store:category-detail', lookup_field='slug', read_only=True, allow_null=True)
    class Meta:
        model = Category
        fields = ('id', 'url', 'name', 'slug', 'description', 'parent')
        read_only_fields = ('id', 'slug')

class ProductSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:product-detail', lookup_field='slug')
    vendor = UserPublicSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    price_xmr = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.XMR], required=False, allow_null=True)
    price_btc = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.BTC], required=False, allow_null=True)
    price_eth = DecimalAsStringField(decimal_places=CRYPTO_PRECISION_MAP[Currency.ETH], required=False, allow_null=True)
    category_id = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), source='category', write_only=True, required=True)
    shipping_options = serializers.JSONField(required=False, allow_null=True)
    average_rating = DecimalAsStringField(read_only=True, decimal_places=2, required=False)
    sales_count = serializers.IntegerField(read_only=True, required=False)
    is_digital = serializers.BooleanField(read_only=True, required=False)
    class Meta:
        model = Product
        fields = (
            'id', 'url', 'vendor', 'category', 'name', 'slug', 'description',
            'price_xmr', 'price_btc', 'price_eth', 'accepted_currencies',
            'quantity', 'ships_from', 'ships_to', 'shipping_options',
            'is_active', 'is_featured', 'is_digital',
            'sales_count', 'average_rating',
            'created_at', 'updated_at', 'category_id',
        )
        read_only_fields = ('id', 'slug', 'vendor', 'category', 'sales_count', 'average_rating', 'is_digital', 'created_at', 'updated_at')

    def validate_shipping_options(self, value: Optional[Any]) -> Optional[List[Dict[str, Any]]]:
        if value is None: return None
        if not isinstance(value, list): raise DRFValidationError("Shipping options must be a JSON list.")
        if not value: return value
        validated_options = []
        expected_price_keys = {f'price_{code.lower()}' for code, _ in Currency.choices}
        for index, option in enumerate(value):
            if not isinstance(option, dict): raise DRFValidationError(f"Item at index {index} is not a valid JSON object.")
            option_name = option.get('name')
            if not option_name or not isinstance(option_name, str) or not option_name.strip(): raise DRFValidationError(f"Item at index {index} must have a non-empty 'name' string.")
            has_at_least_one_price = False
            for key, price_str in option.items():
                if key.startswith('price_'):
                    if key not in expected_price_keys: logger.warning(f"Unexpected price key '{key}' found in shipping_options for product.")
                    if not isinstance(price_str, str): raise DRFValidationError(f"Price '{key}' in option '{option_name}' (index {index}) must be a string.")
                    try:
                        price_decimal = Decimal(price_str)
                        if price_decimal < Decimal('0.0'): raise DRFValidationError(f"Price '{key}' in option '{option_name}' (index {index}) cannot be negative.")
                    except InvalidOperation: raise DRFValidationError(f"Price '{key}' in option '{option_name}' (index {index}) is not a valid decimal string.")
                    has_at_least_one_price = True
            if not has_at_least_one_price: raise DRFValidationError(f"Shipping option '{option_name}' (index {index}) must define at least one valid price.")
            validated_options.append(option)
        return validated_options

class CryptoPaymentSerializer(serializers.ModelSerializer):
    expected_amount_native = serializers.SerializerMethodField()
    received_amount_native = serializers.SerializerMethodField()
    order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk')
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    class Meta:
        model = CryptoPayment
        fields = (
            'id', 'order', 'currency', 'currency_display', 'payment_address', 'payment_id_monero',
            'expected_amount_native', 'received_amount_native', 'is_confirmed',
            'confirmations_received', 'confirmations_needed', 'transaction_hash',
            'created_at', 'updated_at', 'derivation_index',
        )
        read_only_fields = fields

    def _format_crypto_amount(self, amount: Optional[Decimal], currency: Optional[str]) -> Optional[str]:
        if amount is None or currency is None: return None
        try:
            d_amount = Decimal(str(amount))
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            # Assuming native amount is stored in smallest unit (e.g., satoshis, wei)
            standard_amount = d_amount / (Decimal('10') ** decimal_places) 
            return f"{standard_amount.quantize(quantize_exp):.{decimal_places}f}"
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format crypto amount '{amount}' for currency '{currency}': {e}")
            try:
                decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
                # Fallback if formatting fails, still try to convert from smallest unit
                return str(Decimal(str(amount)) / (Decimal('10') ** decimal_places))
            except Exception: return str(amount) # Last resort, raw value

    def get_expected_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        return self._format_crypto_amount(obj.expected_amount_native, obj.currency)

    def get_received_amount_native(self, obj: CryptoPayment) -> Optional[str]:
        return self._format_crypto_amount(obj.received_amount_native, obj.currency)

class FeedbackSerializer(serializers.ModelSerializer):
    reviewer = UserPublicSerializer(read_only=True)
    recipient = UserPublicSerializer(read_only=True)
    order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk')
    product_name = serializers.CharField(source='order.product.name', read_only=True)
    order_id = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(), 
        write_only=True, 
        required=True, 
        source='order' # This makes DRF use 'validate_order_id' (formerly validate_order) for this field
    )
    rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    comment = serializers.CharField(max_length=2000, required=True, style={'base_template': 'textarea.html'})
    rating_quality = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    rating_shipping = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    rating_communication = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)
    class Meta:
        model = Feedback
        fields = ('id', 'order', 'product_name', 'reviewer', 'recipient', 'rating', 'comment', 'feedback_type', 'feedback_type_display', 'rating_quality', 'rating_shipping', 'rating_communication', 'created_at', 'order_id')
        read_only_fields = ('id', 'order', 'product_name', 'reviewer', 'recipient', 'feedback_type', 'feedback_type_display', 'created_at')

    def validate_order_id(self, order_instance: Order) -> Order: # RENAMED from validate_order
        """
        Validates the order associated with the feedback.
        Ensures:
        1. User is authenticated.
        2. User is the buyer of the order.
        3. Feedback for this order by this user to this recipient doesn't already exist.
        4. Order is in a status eligible for feedback (FINALIZED or DISPUTE_RESOLVED).
        """
        request_user = self.context.get('request', {}).user
        if not request_user or not request_user.is_authenticated:
            raise DRFValidationError({"detail": ["Authentication required to leave feedback."]}, code='authentication_required')

        if not isinstance(order_instance, Order): # Should be handled by PrimaryKeyRelatedField
                logger.error(f"FeedbackSerializer.validate_order_id received non-Order instance: {type(order_instance)}")
                raise DRFValidationError({"order_id": ["Invalid order ID provided."]}, code='invalid_order')

        # Ensure the request_user is the buyer of the order.
        is_buyer = (order_instance.buyer_id == request_user.pk)
        if not is_buyer:
            raise DRFValidationError({"order_id": ["You are not the buyer of this order and cannot leave feedback."]}, code='not_buyer')

        # Determine the recipient (vendor for this order).
        recipient_id = order_instance.vendor_id
        if recipient_id is None: 
            logger.error(f"FeedbackSerializer: Order {order_instance.id} (PK: {order_instance.pk}) is missing a vendor_id.")
            raise DRFValidationError({"order_id": ["Internal error: Cannot determine feedback recipient (order missing vendor)."]}, code='missing_vendor')

        # Check 1: Duplicate Feedback
        # Ensure feedback from this reviewer (request_user) to this recipient for this order doesn't already exist.
        if Feedback.objects.filter(order_id=order_instance.pk, reviewer_id=request_user.pk, recipient_id=recipient_id).exists():
            raise DRFValidationError({"order_id": ["You have already left feedback for this order."]}, code='duplicate_feedback')

        # Check 2: Order Status - Feedback can only be left for orders in specific statuses.
        # Compare against the *values* of the enum members.
        feedback_eligible_status_values = [
            Order.StatusChoices.FINALIZED.value, 
            Order.StatusChoices.DISPUTE_RESOLVED.value
        ]
        
        if order_instance.status not in feedback_eligible_status_values:
            eligible_statuses_for_message = [Order.StatusChoices.FINALIZED, Order.StatusChoices.DISPUTE_RESOLVED]
            allowed_statuses_str = ", ".join([s.label for s in eligible_statuses_for_message])
            current_status_display = order_instance.get_status_display()
            raise DRFValidationError(
                {"order_id": [f"Feedback can only be left for orders with status: {allowed_statuses_str}. Current status: '{current_status_display}'."]},
                code='invalid_order_status'
            )

        return order_instance

    def create(self, validated_data: Dict[str, Any]) -> Feedback:
        request_user = self.context['request'].user
        order: Order = validated_data['order'] # 'order' because source='order' on order_id field
        
        validated_data['reviewer'] = request_user
        
        # Determine recipient based on who the reviewer is (assuming only buyer reviews vendor)
        if order.buyer_id == request_user.pk:
            validated_data['recipient_id'] = order.vendor_id
        else:
            # This case should ideally be prevented by validate_order_id, but as a safeguard:
            logger.error(f"CRITICAL: User {request_user.id} is not buyer for order {order.id} in feedback create, but validate_order_id passed.")
            raise DRFValidationError({"detail": ["Internal error: Cannot determine feedback recipient during creation."]}, code='internal_error')
        
        if validated_data['recipient_id'] is None:
                logger.error(f"CRITICAL: recipient_id is None for order {order.id} when creating feedback by user {request_user.id}.")
                raise DRFValidationError({"detail": ["Internal error: Feedback recipient could not be determined."]}, code='internal_error')

        try:
            feedback = super().create(validated_data)
            logger.info(f"Feedback created (ID: {feedback.id}) for Order {order.id} by User {request_user.id}.")
            return feedback
        except Exception as e:
            logger.error(f"Error creating feedback for order {order.id} by user {request_user.id}: {e}")
            raise DRFValidationError({"detail": ["An error occurred while saving feedback."]}, code='create_failed')

class OrderBaseSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:order-detail', lookup_field='pk')
    product = ProductSerializer(read_only=True)
    total_price_native_selected = serializers.SerializerMethodField()
    selected_currency_display = serializers.CharField(source='get_selected_currency_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    release_signature_buyer_present = serializers.SerializerMethodField()
    release_signature_vendor_present = serializers.SerializerMethodField()
    class Meta:
        model = Order
        fields = ('id', 'url', 'product', 'quantity', 'selected_currency', 'selected_currency_display', 'total_price_native_selected', 'status', 'status_display', 'release_initiated', 'release_signature_buyer_present', 'release_signature_vendor_present', 'release_tx_broadcast_hash', 'created_at', 'updated_at', 'payment_deadline', 'auto_finalize_deadline', 'dispute_deadline')
        read_only_fields = fields

    def get_total_price_native_selected(self, obj: Order) -> Optional[str]:
        price = obj.total_price_native_selected
        currency = obj.selected_currency
        if price is None or currency is None: return None
        try:
            d_price = Decimal(str(price))
            decimal_places = CRYPTO_PRECISION_MAP.get(currency, DEFAULT_CRYPTO_PRECISION)
            quantize_exp = Decimal('1e-' + str(decimal_places))
            # Assuming native amount is stored in smallest unit
            standard_price = d_price / (Decimal('10') ** decimal_places) 
            return f"{standard_price.quantize(quantize_exp):.{decimal_places}f}"
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(f"Could not format total_price_native_selected '{price}' for order {obj.id}: {e}")
            return str(price)

    def get_release_signature_buyer_present(self, obj: Order) -> bool: return bool(obj.release_signature_buyer)
    def get_release_signature_vendor_present(self, obj: Order) -> bool: return bool(obj.release_signature_vendor)

class OrderBuyerSerializer(OrderBaseSerializer):
    vendor = UserPublicSerializer(read_only=True)
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True)
    feedback = FeedbackSerializer(read_only=True, allow_null=True)
    class Meta(OrderBaseSerializer.Meta):
        fields = OrderBaseSerializer.Meta.fields + ('vendor', 'payment', 'feedback')
        read_only_fields = fields

class OrderVendorSerializer(OrderBaseSerializer):
    buyer = UserPublicSerializer(read_only=True)
    payment = CryptoPaymentSerializer(read_only=True, allow_null=True)
    feedback = FeedbackSerializer(read_only=True, allow_null=True)
    has_shipping_info = serializers.SerializerMethodField()
    class Meta(OrderBaseSerializer.Meta):
        fields = OrderBaseSerializer.Meta.fields + ('buyer', 'payment', 'feedback', 'has_shipping_info')
        read_only_fields = fields
    def get_has_shipping_info(self, obj: Order) -> bool: return bool(obj.encrypted_shipping_info)

class PrepareReleaseTxSerializer(serializers.Serializer): pass
class SignReleaseSerializer(serializers.Serializer):
    signature_data = serializers.CharField(required=True, style={'base_template': 'textarea.html'})
    def validate_signature_data(self, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value: raise DRFValidationError("Signature data cannot be empty.")
        return cleaned_value
class OpenDisputeSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, max_length=2000, style={'base_template': 'textarea.html'})
    def validate_reason(self, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value: raise DRFValidationError("A reason must be provided for the dispute.")
        return cleaned_value

class TicketMessageSerializer(serializers.ModelSerializer):
    sender = UserPublicSerializer(read_only=True)
    decrypted_body = serializers.CharField(read_only=True, required=False, allow_null=True)
    message_body = serializers.CharField(write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000, label="Message Content")
    class Meta:
        model = TicketMessage
        fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body', 'message_body')
        read_only_fields = ('id', 'sender', 'sent_at', 'is_read', 'decrypted_body')

class SupportTicketBaseSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='store:ticket-detail', lookup_field='pk')
    requester = UserPublicSerializer(read_only=True)
    assigned_to = UserPublicSerializer(read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    related_order = serializers.HyperlinkedRelatedField(view_name='store:order-detail', read_only=True, lookup_field='pk', allow_null=True)
    related_order_product_name = serializers.CharField(source='related_order.product.name', read_only=True, allow_null=True)
    class Meta:
        model = SupportTicket
        fields = ('id', 'url', 'subject', 'requester', 'assigned_to', 'status', 'status_display', 'created_at', 'updated_at', 'related_order', 'related_order_product_name')
        read_only_fields = ('id', 'url', 'requester', 'assigned_to', 'status_display', 'created_at', 'updated_at', 'related_order', 'related_order_product_name')

class SupportTicketListSerializer(SupportTicketBaseSerializer):
    message_count = serializers.IntegerField(read_only=True, required=False)
    last_message_at = serializers.DateTimeField(read_only=True, required=False)
    class Meta(SupportTicketBaseSerializer.Meta):
        fields = SupportTicketBaseSerializer.Meta.fields + ('message_count', 'last_message_at')
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('message_count', 'last_message_at')

class SupportTicketDetailSerializer(SupportTicketBaseSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)
    subject = serializers.CharField(required=True, max_length=255)
    initial_message_body = serializers.CharField(write_only=True, required=True, style={'base_template': 'textarea.html'}, max_length=10000, label="Initial Message")
    related_order_id_write = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        source='related_order', # This makes DRF use 'validate_related_order_id_write' (formerly validate_related_order)
        label="Related Order ID (Optional)"
    )
    class Meta(SupportTicketBaseSerializer.Meta):
        fields = SupportTicketBaseSerializer.Meta.fields + ('messages', 'initial_message_body', 'related_order_id_write')
        read_only_fields = SupportTicketBaseSerializer.Meta.read_only_fields + ('messages',)
        extra_kwargs = {'subject': {'write_only': False, 'required': True}}

    def validate_related_order_id_write(self, order_instance: Optional[Order]) -> Optional[Order]: # RENAMED from validate_related_order
        """
        Validates the order linked to a support ticket.
        Ensures:
        1. User is authenticated.
        2. If user is not staff, they must be the buyer or vendor of the order.
        """
        if order_instance is None: 
            return None # Allowed if related_order_id_write is not provided or null

        request_user = self.context.get('request', {}).user
        if not request_user or not request_user.is_authenticated:
            raise DRFValidationError(
                {"related_order_id_write": ["Authentication required to validate related order."]},
                code='authentication_required'
            )
        
        if not isinstance(order_instance, Order): # Should be handled by PrimaryKeyRelatedField
                logger.error(f"SupportTicketDetailSerializer.validate_related_order_id_write received non-Order instance: {type(order_instance)}")
                raise DRFValidationError({"related_order_id_write": ["Invalid related order ID provided."]}, code='invalid_order')

        # Staff users can link any order to a ticket.
        if getattr(request_user, 'is_staff', False):
            return order_instance

        # For non-staff users, they must be associated with the order.
        is_buyer = (order_instance.buyer_id == request_user.pk)
        is_vendor = (order_instance.vendor_id == request_user.pk)

        if not (is_buyer or is_vendor):
            logger.warning(
                f"User {request_user.username} (ID: {request_user.pk}) attempting to link ticket to unrelated order {order_instance.id} (PK: {order_instance.pk}). "
                f"Order Buyer ID: {order_instance.buyer_id}, Order Vendor ID: {order_instance.vendor_id}"
            )
            raise DRFValidationError(
                {"related_order_id_write": ["You cannot link this ticket to an order you are not associated with (not buyer or vendor)."]},
                code='unrelated_order'
            )
            
        return order_instance

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
    vendor_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_vendor=True, is_active=True), required=True)
    shipping_data = ShippingDataSerializer(required=False, allow_null=True)
    buyer_message = serializers.CharField(required=False, allow_blank=True, style={'base_template': 'textarea.html'}, max_length=2000)
    pre_encrypted_blob = serializers.CharField(required=False, allow_blank=True, style={'base_template': 'textarea.html'})

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        vendor: Optional[User] = data.get('vendor_id')
        if not vendor: raise DRFValidationError({"vendor_id": ["Vendor validation failed."]}) # Should be caught by field validation
        self.context['target_vendor'] = vendor # For use in view
        has_structured_shipping = bool(data.get('shipping_data'))
        has_buyer_message = bool(data.get('buyer_message') and str(data['buyer_message']).strip())
        has_pre_encrypted = bool(data.get('pre_encrypted_blob') and str(data['pre_encrypted_blob']).strip())
        has_data_for_server_encryption = has_structured_shipping or has_buyer_message

        if has_data_for_server_encryption and has_pre_encrypted:
            # Adjusted to exactly match test expectation
            raise DRFValidationError("Provide either structured data OR a pre_encrypted_blob")
        if has_data_for_server_encryption and not vendor.pgp_public_key:
            raise DRFValidationError({"vendor_id": [f"Vendor '{vendor.username}' has no PGP key for server-side encryption of provided data."]}, code='vendor_pgp_key_missing')
        if has_pre_encrypted:
            blob_content = str(data['pre_encrypted_blob']).strip()
            if not blob_content.startswith('-----BEGIN PGP MESSAGE-----') or \
                not blob_content.endswith('-----END PGP MESSAGE-----'):
                raise DRFValidationError({"pre_encrypted_blob": ["Invalid PGP message format. Must start with '-----BEGIN PGP MESSAGE-----' and end with '-----END PGP MESSAGE-----'."]})
        elif not has_data_for_server_encryption: # No pre_encrypted_blob was given, so other data must exist
                # Adjusted to exactly match test expectation
            raise DRFValidationError("Provide either 'shipping_data', 'buyer_message', or 'pre_encrypted_blob'")
        return data

class CanarySerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalSettings
        fields = ('canary_content', 'canary_last_updated', 'canary_pgp_signature', 'canary_signing_key_fingerprint', 'canary_signing_key_url')
        read_only_fields = fields
class SiteInformationSerializer(serializers.ModelSerializer):
    registration_open = serializers.BooleanField(source='allow_new_registrations', read_only=True)
    vendor_applications_open = serializers.BooleanField(source='allow_new_vendors', read_only=True)
    class Meta:
        model = GlobalSettings
        fields = ('site_name', 'maintenance_mode', 'registration_open', 'vendor_applications_open')
        read_only_fields = fields
class ExchangeRateSerializer(serializers.Serializer):
    btc_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    eth_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    xmr_usd_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
    usd_eur_rate = DecimalAsStringField(max_digits=18, decimal_places=8, read_only=True, required=False)
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
            # Use a temporary DecimalAsStringField for consistent formatting
            temp_field = DecimalAsStringField(max_digits=36, decimal_places=places)
            return temp_field.to_representation(value)
        except Exception as e:
            logger.warning("Failed to format decimal %s to %d places: %s", value, places, e)
            return str(value) # Fallback


class NotificationSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    class Meta:
        if Notification is None: # Handle case where notifications app might not be installed
            model = Type[None] # Placeholder to satisfy Meta class structure
            fields: List[str] = ['id', 'message', 'created_at'] # Minimal fields
            read_only_fields: List[str] = fields
        else:
            model = Notification
            fields = ('id', 'level', 'level_display', 'message', 'link', 'is_read', 'created_at')
            read_only_fields = ('id', 'level', 'level_display', 'message', 'link', 'created_at')

class VendorApplicationSerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    bond_currency = serializers.ChoiceField(choices=Currency.choices, write_only=True, required=False) # Input field
    bond_amount_crypto = DecimalAsStringField(read_only=True, required=False) # Output field (actual crypto amount)
    bond_amount_usd = DecimalAsStringField(read_only=True, decimal_places=2, required=False) # Output field (USD value at time of bond setting)
    bond_payment_address = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = VendorApplication
        fields = ('id', 'user', 'status', 'status_display', 'bond_currency', 'bond_amount_usd', 'bond_amount_crypto', 'bond_payment_address', 'rejection_reason', 'created_at', 'updated_at')
        read_only_fields = ('id', 'user', 'status', 'status_display', 'bond_amount_usd', 'bond_amount_crypto', 'bond_payment_address', 'rejection_reason', 'created_at', 'updated_at')

    def to_representation(self, instance: VendorApplication) -> Dict[str, Any]:
        representation = super().to_representation(instance)
        # Only show bond payment address if status is PENDING_BOND
        if instance.status != VendorApplication.StatusChoices.PENDING_BOND.value: # Compare with .value
            representation.pop('bond_payment_address', None)
            # Also remove bond_currency if not pending bond, as it's a write_only field for initiation
            representation.pop('bond_currency', None) 
        return representation

class WebAuthnCredentialSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    class Meta:
        model = WebAuthnCredential
        fields = ('id', 'user', 'credential_id_b64', 'public_key_b64', 'sign_count', 'transports', 'nickname', 'created_at', 'last_used_at')
        read_only_fields = ('id', 'user', 'created_at', 'last_used_at')


# --- NEW: Withdrawal Serializers ---

class WithdrawalPrepareSerializer(serializers.Serializer):
    """Serializer for validating input to initiate a withdrawal request."""
    currency = serializers.ChoiceField(
        choices=Currency.choices,
        help_text="The cryptocurrency code to withdraw (e.g., BTC, XMR)."
    )
    amount = DecimalAsStringField(
        max_digits=30, # Sufficient for various crypto values
        decimal_places=18, # Sufficient for ETH/ERC20, BTC/XMR will be less
        validators=[MinValueValidator(Decimal('0.000000000000000001'))], # Smallest possible non-zero
        help_text="The amount to withdraw in standard units (e.g., 0.1 BTC)."
    )
    address = serializers.CharField(
        max_length=255, # Generous length for various address types
        trim_whitespace=True,
        help_text="The destination cryptocurrency address."
    )

    def validate(self, data):
        currency = data.get('currency')
        address = data.get('address')
        amount = data.get('amount') # Already a Decimal thanks to DecimalAsStringField

        # Basic presence checks (though DRF usually handles this for required=True fields)
        if not currency or not address or amount is None:
            # This typically won't be hit if fields are required, but as a safeguard.
            raise DRFValidationError("Currency, amount, and address are required.")

        if amount <= Decimal(0):
            raise DRFValidationError({"amount": ["Withdrawal amount must be positive."]})

        if not _validators_available:
            logger.error("Validators not available, skipping address validation in WithdrawalPrepareSerializer.")
            # Potentially raise an error or allow if this is acceptable in some environments
            # For now, we allow it to proceed but log an error.
            # raise DRFValidationError("Address validation service is unavailable.")
            return data

        try:
            if currency == Currency.BTC:
                validate_bitcoin_address(address)
            elif currency == Currency.XMR:
                validate_monero_address(address)
            elif currency == Currency.ETH:
                validate_ethereum_address(address)
            # Add other currencies here as needed
            else:
                # This should ideally be caught by ChoiceField, but good to have defense in depth.
                raise DRFValidationError({"currency": [f"Unsupported currency for withdrawal: {currency}"]})
        except DjangoCoreValidationError as e:
            # Convert Django's ValidationError to DRF's ValidationError
            error_detail = e.message if hasattr(e, 'message') else str(e.messages[0] if e.messages else str(e))
            logger.debug(f"Address validation failed for {currency} address '{address}': {error_detail}")
            raise DRFValidationError({"address": [f"Invalid {currency} address: {error_detail}"]}) from e
        except Exception as e: # Catch any other unexpected errors during validation
            logger.exception(f"Unexpected error during address validation for {currency} address '{address}'")
            raise DRFValidationError({"address": ["An unexpected error occurred during address validation."]}) from e
        return data

class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """Serializer for displaying WithdrawalRequest details."""
    # Dynamic decimal places based on currency might be complex here without custom field or more logic
    # For representation, using a sensible default (e.g., 8 or 12) or method fields.
    # Using method fields to apply specific precision.
    requested_amount = serializers.SerializerMethodField()
    fee_amount = serializers.SerializerMethodField()
    net_amount = serializers.SerializerMethodField()
    
    fee_percentage = DecimalAsStringField(max_digits=5, decimal_places=2, read_only=True) # e.g., 1.00 for 1%
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    user = UserPublicSerializer(read_only=True)

    class Meta:
        if WithdrawalRequest is None: # App not installed
            model = Type[None]
            fields = ['id', 'currency', 'requested_amount', 'status']
            read_only_fields = fields
        else:
            model = WithdrawalRequest
            fields = (
                'id', 'user', 'currency', 'currency_display', 'requested_amount',
                'fee_percentage', 'fee_amount', 'net_amount', 'withdrawal_address',
                'status', 'status_display', 'broadcast_tx_hash', 'failure_reason',
                'created_at', 'updated_at', 'processed_at',
            )
            read_only_fields = fields

    def _format_amount_by_currency(self, amount: Optional[Decimal], currency_code: Optional[str]) -> Optional[str]:
        if amount is None or currency_code is None:
            return None
        
        decimal_places = CRYPTO_PRECISION_MAP.get(currency_code, DEFAULT_CRYPTO_PRECISION)
        # Ensure amount is a Decimal
        try:
            d_amount = Decimal(str(amount))
        except InvalidOperation:
            logger.error(f"Invalid decimal value '{amount}' for currency '{currency_code}' in WithdrawalRequestSerializer.")
            return str(amount) # Fallback

        quantizer = Decimal('1e-' + str(decimal_places))
        return f"{d_amount.quantize(quantizer):.{decimal_places}f}"

    def get_requested_amount(self, obj: WithdrawalRequest) -> Optional[str]:
        return self._format_amount_by_currency(obj.requested_amount, obj.currency)

    def get_fee_amount(self, obj: WithdrawalRequest) -> Optional[str]:
        return self._format_amount_by_currency(obj.fee_amount, obj.currency)

    def get_net_amount(self, obj: WithdrawalRequest) -> Optional[str]:
        return self._format_amount_by_currency(obj.net_amount, obj.currency)


class WalletBalanceSerializer(serializers.Serializer):
    """Serializer for displaying user balances per currency."""
    currency = serializers.CharField(read_only=True) # e.g., 'BTC', 'XMR'
    balance = DecimalAsStringField(max_digits=30, decimal_places=LEDGER_DECIMAL_PLACES, read_only=True)
    locked_balance = DecimalAsStringField(max_digits=30, decimal_places=LEDGER_DECIMAL_PLACES, read_only=True)
    available_balance = DecimalAsStringField(max_digits=30, decimal_places=LEDGER_DECIMAL_PLACES, read_only=True)

#-----End Of File-----#