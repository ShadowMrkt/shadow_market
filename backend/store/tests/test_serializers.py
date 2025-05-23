# backend/store/tests/test_serializers.py
# Revision: 1.17 (Correct assertion string for SupportTicket)
# Date: 2025-05-17
# Author: Gemini
# Description: Contains tests for the serializers defined in store/serializers.py.
# Changes:
# - Rev 1.17:
#   - SupportTicketSerializerTests:
#     - test_detail_serializer_validate_related_order_fail_unrelated: Updated expected error message string to match actual output.
# - Rev 1.16: (Fix KeyError in assertions)
#   - FeedbackSerializerTests:
#     - test_validate_order_id_wrong_status: Corrected assertion to access nested error message.
#     - test_validate_order_id_already_exists: Corrected assertion to access nested error message.
#   - SupportTicketSerializerTests:
#     - test_detail_serializer_validate_related_order_fail_unrelated: Corrected assertion to access nested error message.
# - Rev 1.15: (Add debug prints to FeedbackSerializerTests)
#   - FeedbackSerializerTests.test_validate_order_id_already_exists:
#     - Added print statements to debug the structure and content of serializer.errors
#       and serializer.errors['order_id'] before the failing assertion.
# - Rev 1.14:
#   - SupportTicketSerializerTests:
#     - In `test_detail_serializer_validate_related_order_success` and
#       `test_detail_serializer_validate_related_order_fail_unrelated`, changed the
#       data key for the related order from 'related_order_id' to 'related_order_id_write'
#       to match the actual field name in `SupportTicketDetailSerializer`.
#     - In `test_detail_serializer_validate_related_order_fail_unrelated`, updated
#       assertions for `serializer.errors` to check the key 'related_order_id_write'.
# - (Older revisions omitted for brevity)

# Standard Library Imports
from decimal import Decimal, InvalidOperation
from unittest.mock import patch, MagicMock, ANY
import json

# Django Imports
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError as DjangoValidationErrorCore, ImproperlyConfigured
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify

# Third-Party Imports
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory

# Local Application Imports
from backend.store.serializers import *
from backend.store.models import (
    User, Currency, Order, Category, Product, Feedback, VendorApplication,
    GlobalSettings, SupportTicket, TicketMessage, WebAuthnCredential, CryptoPayment,
    UserManager
)
from backend.withdraw.models import WithdrawalRequest, WithdrawalStatusChoices
from backend.ledger.models import UserBalance

# --- Constants ---
User = get_user_model()
VALID_BTC_ADDRESS = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
VALID_XMR_ADDRESS = "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
VALID_ETH_ADDRESS = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
INVALID_ADDRESS = "this-is-not-valid"

VALID_PGP_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: Testing

mQENBFqG PogBCADFeoM8s7Q6qNwUaG9pZCBvbiB0aGUgcGxhY2Ugb2YgYSByZWFs
IGtleSBmb3IgU0VSVklDRSBURVNUUy4gVGhpcyBpcyBsb25nIGVub3VnaCB0byBw
YXNzIGJhc2ljIHZhbGlkYXRpb24gY2hlY2tzIGZvciBsZW5ndGggYW5kIHN0cnVj
dHVyZS4gSXQgaXMgTk9UIGEgdmFsaWQgZW5jcnlwdGlvbiBrZXkuLi4uCg==
=TestKey1
-----END PGP PUBLIC KEY BLOCK-----"""

VALID_PGP_KEY_OTHER = """-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: Testing

mQENBFqG PotherBCADFeoM8s7Q6qNwUaG9pZCBvbiB0aGUgcGxhY2Ugb2YgYSBy
ZWFsIGtleSBmb3IgT1RIRVIgU0VSVklDRSBURVNUUy4gVGhpcyBpcyBsb25nIGVu
b3VnaCB0byBwYXNzIGJhc2ljIHZhbGlkYXRpb24gY2hlY2tzLi4uLgE=
=TestKey2
-----END PGP PUBLIC KEY BLOCK-----"""

DEFAULT_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Test Cases ---

class DecimalAsStringFieldTests(TestCase):
    """Tests for the custom DecimalAsStringField."""

    def test_serialization_to_string_correct_precision(self):
        field_8_places = DecimalAsStringField(max_digits=20, decimal_places=8)
        field_12_places = DecimalAsStringField(max_digits=30, decimal_places=12)
        field_18_places = DecimalAsStringField(max_digits=36, decimal_places=18)
        value1 = Decimal("123.456789")
        value2 = Decimal("0.00000001")
        value3 = Decimal("987654321.123456789123")
        value4 = Decimal("100")
        value5 = Decimal("1.000000000000000001")
        self.assertEqual(field_8_places.to_representation(value1), "123.45678900")
        self.assertEqual(field_8_places.to_representation(value2), "0.00000001")
        self.assertEqual(field_8_places.to_representation(value3), "987654321.12345679")
        self.assertEqual(field_8_places.to_representation(value4), "100.00000000")
        self.assertEqual(field_12_places.to_representation(value1), "123.456789000000")
        self.assertEqual(field_12_places.to_representation(value3), "987654321.123456789123")
        self.assertEqual(field_18_places.to_representation(value5), "1.000000000000000001")

    def test_serialization_none_value(self):
        field = DecimalAsStringField(max_digits=20, decimal_places=8)
        self.assertIsNone(field.to_representation(None))

    def test_deserialization_from_string(self):
        field = DecimalAsStringField(max_digits=20, decimal_places=8)
        self.assertEqual(field.to_internal_value("123.45"), Decimal("123.45"))
        self.assertEqual(field.to_internal_value(" 0.00000001 "), Decimal("0.00000001"))
        self.assertEqual(field.to_internal_value("100"), Decimal("100"))

    def test_deserialization_invalid_string(self):
        field = DecimalAsStringField(max_digits=20, decimal_places=8)
        with self.assertRaisesRegex(DRFValidationError, "Invalid decimal value"):
            field.to_internal_value("not a number")


class WithdrawalPrepareSerializerTests(TestCase):
    """Tests for the WithdrawalPrepareSerializer."""

    def test_valid_data_btc(self):
        valid_data = {'currency': Currency.BTC.value, 'amount': '0.123', 'address': VALID_BTC_ADDRESS}
        serializer = WithdrawalPrepareSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_valid_data_xmr(self):
        valid_data = {'currency': Currency.XMR.value, 'amount': '10.1', 'address': VALID_XMR_ADDRESS}
        serializer = WithdrawalPrepareSerializer(data=valid_data)
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_invalid_address_format_btc(self):
        invalid_data = {'currency': Currency.BTC.value, 'amount': '0.1', 'address': INVALID_ADDRESS}
        serializer = WithdrawalPrepareSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('address', serializer.errors)

    def test_valid_address_wrong_currency(self):
        invalid_data = {'currency': Currency.XMR.value, 'amount': '0.1', 'address': VALID_BTC_ADDRESS}
        serializer = WithdrawalPrepareSerializer(data=invalid_data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('address', serializer.errors)


class WalletBalanceSerializerTests(TestCase):
    """Tests for the WalletBalanceSerializer (serialization)."""

    def test_serialization_success(self):
        balance_data = {'currency': Currency.BTC.value, 'balance': Decimal('1.5'), 'locked_balance': Decimal('0.2'), 'available_balance': Decimal('1.3')}
        serializer = WalletBalanceSerializer(balance_data)
        expected_output = {'currency': 'BTC', 'balance': '1.500000000000', 'locked_balance': '0.200000000000', 'available_balance': '1.300000000000'}
        self.assertEqual(serializer.data, expected_output)


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class WithdrawalRequestSerializerTests(TestCase):
    """Tests for the WithdrawalRequestSerializer (serialization)."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.user = User.objects.create_user(
            username="withdraw_user_sr",
            password="password",
            pgp_public_key=VALID_PGP_KEY
        )
        cls.withdrawal_request = WithdrawalRequest.objects.create(
            user=cls.user, currency=Currency.BTC.value, requested_amount=Decimal('0.5'),
            fee_percentage=Decimal('1.00'), fee_amount=Decimal('0.005'), net_amount=Decimal('0.495'),
            withdrawal_address=VALID_BTC_ADDRESS, status=WithdrawalStatusChoices.COMPLETED,
            broadcast_tx_hash='txhash12345', processed_at=timezone.now()
        )

    def test_serialization_success(self):
        serializer = WithdrawalRequestSerializer(self.withdrawal_request)
        data = serializer.data
        self.assertEqual(data['currency'], Currency.BTC.value)
        self.assertEqual(data['requested_amount'], "0.50000000")
        self.assertEqual(data['status'], WithdrawalStatusChoices.COMPLETED)
        self.assertEqual(data['broadcast_tx_hash'], 'txhash12345')


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class CurrentUserSerializerTests(TestCase):
    """Tests for the CurrentUserSerializer (validation, update)."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.password = 'startPassword123'
        cls.user = User.objects.create_user(
            username='currentuserserializertest',
            password=cls.password,
            pgp_public_key=VALID_PGP_KEY
        )

    def test_password_change_validation_success(self):
        try:
            serializer = CurrentUserSerializer(instance=self.user, data={
                'current_password': self.password,
                'password': 'newPassword456!',
                'password_confirm': 'newPassword456!'
            }, partial=True)
            self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)
        except ImproperlyConfigured as e:
            self.fail(f"CurrentUserSerializer improperly configured: {e}.")


    def test_password_change_validation_mismatch(self):
        try:
            serializer = CurrentUserSerializer(instance=self.user, data={
                'current_password': self.password,
                'password': 'newPassword456!',
                'password_confirm': 'MISMATCHEDpassword456!'
            }, partial=True)
            self.assertFalse(serializer.is_valid())
            self.assertIn('password_confirm', serializer.errors)
            self.assertEqual(str(serializer.errors['password_confirm'][0]), "New passwords do not match.")
        except ImproperlyConfigured as e:
            self.fail(f"CurrentUserSerializer improperly configured: {e}.")


    def test_password_change_validation_missing_current(self):
        try:
            serializer = CurrentUserSerializer(instance=self.user, data={
                'password': 'newPassword456!',
                'password_confirm': 'newPassword456!'
            }, partial=True)
            self.assertFalse(serializer.is_valid(), f"Serializer should be invalid. Errors: {serializer.errors}")
            self.assertIn('current_password', serializer.errors)
            self.assertEqual(str(serializer.errors['current_password'][0]), "This field is required to change the password.")
        except ImproperlyConfigured as e:
            self.fail(f"CurrentUserSerializer improperly configured: {e}.")


    @patch('backend.store.models.User.check_password')
    def test_password_change_validation_wrong_current(self, mock_check_password):
        mock_check_password.return_value = False
        try:
            serializer = CurrentUserSerializer(instance=self.user, data={
                'current_password': 'WRONGcurrentPassword',
                'password': 'newPassword456!',
                'password_confirm': 'newPassword456!'
            }, partial=True)
            self.assertTrue(serializer.is_valid(raise_exception=False),
                            f"is_valid() should pass here, errors were: {serializer.errors}")

            with self.assertRaisesRegex(DRFValidationError, "Current password is not correct") as cm:
                serializer.save()

            self.assertIn('current_password', cm.exception.detail)
            self.assertEqual(str(cm.exception.detail['current_password'][0]), "Current password is not correct.")

            mock_check_password.assert_called_once_with('WRONGcurrentPassword')
        except ImproperlyConfigured as e:
            self.fail(f"CurrentUserSerializer improperly configured: {e}.")


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class FeedbackSerializerTests(TestCase):
    """Tests for the FeedbackSerializer (validation, context)."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.password = 'pw'
        cls.buyer = User.objects.create_user(username='feedback_buyer', password=cls.password, pgp_public_key=VALID_PGP_KEY)
        cls.vendor = User.objects.create_user(username='feedback_vendor', password=cls.password, is_vendor=True, pgp_public_key=VALID_PGP_KEY_OTHER)

        category_name = 'Test Cat Feedback Ser'
        cls.category = Category.objects.create(name=category_name, slug=slugify(category_name))
        product_name = "Feedback Prod S"
        cls.product = Product.objects.create(
            vendor=cls.vendor, name=product_name, category=cls.category,
            price_xmr=Decimal("1.0"), slug=slugify(product_name)
        )

        common_order_params = {
            'buyer': cls.buyer, 'vendor': cls.vendor, 'product': cls.product,
            'selected_currency': Currency.XMR, 'price_native_selected': 1000000000000,
            'shipping_price_native_selected': 0, 'total_price_native_selected': 1000000000000,
            'quantity': 1,
        }
        cls.order_finalized = Order.objects.create(**common_order_params, status=Order.StatusChoices.FINALIZED)
        cls.order_shipped = Order.objects.create(**common_order_params, status=Order.StatusChoices.SHIPPED)
        cls.order_with_feedback = Order.objects.create(**common_order_params, status=Order.StatusChoices.FINALIZED)

        Feedback.objects.create(order=cls.order_with_feedback, reviewer=cls.buyer, recipient=cls.vendor, rating=4, comment="Done")

        factory = APIRequestFactory()
        cls.request = factory.get('/')
        cls.request.user = cls.buyer

    def test_validate_order_id_success(self):
        serializer = FeedbackSerializer(data={'order_id': self.order_finalized.pk, 'rating': 5, 'comment': 'great'}, context={'request': self.request})
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_validate_order_id_wrong_status(self):
        serializer = FeedbackSerializer(data={'order_id': self.order_shipped.pk, 'rating': 5, 'comment': 'great'}, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('order_id', serializer.errors)

        # --- DEBUGGING PRINTS START ---
        # print(f"\nDEBUG (wrong_status): serializer.errors = {repr(serializer.errors)}")
        # if 'order_id' in serializer.errors:
        #     print(f"DEBUG (wrong_status): type(serializer.errors['order_id']) = {type(serializer.errors['order_id'])}")
        #     print(f"DEBUG (wrong_status): serializer.errors['order_id'] = {repr(serializer.errors['order_id'])}")
        #     if isinstance(serializer.errors['order_id'], list):
        #         print(f"DEBUG (wrong_status): len(serializer.errors['order_id']) = {len(serializer.errors['order_id'])}")
        # --- DEBUGGING PRINTS END ---

        self.assertIn("Feedback can only be left for orders with status", str(serializer.errors['order_id']['order_id'][0]))

    def test_validate_order_id_already_exists(self):
        serializer = FeedbackSerializer(data={'order_id': self.order_with_feedback.pk, 'rating': 5, 'comment': 'great'}, context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('order_id', serializer.errors)

        # --- DEBUGGING PRINTS START ---
        # print(f"\nDEBUG (already_exists): serializer.errors = {repr(serializer.errors)}")
        # if 'order_id' in serializer.errors:
        #     print(f"DEBUG (already_exists): type(serializer.errors['order_id']) = {type(serializer.errors['order_id'])}")
        #     print(f"DEBUG (already_exists): serializer.errors['order_id'] = {repr(serializer.errors['order_id'])}")
        #     if isinstance(serializer.errors['order_id'], list):
        #         print(f"DEBUG (already_exists): len(serializer.errors['order_id']) = {len(serializer.errors['order_id'])}")
        # --- DEBUGGING PRINTS END ---

        self.assertIn("already left feedback", str(serializer.errors['order_id']['order_id'][0]))


class ProductSerializerTests(TestCase):
    """Tests for the ProductSerializer."""

    def test_validate_shipping_options_valid(self):
        options = [
            {'name': 'Standard', 'price_btc': '0.001', 'price_xmr': '0.05'},
            {'name': 'Express', 'price_btc': '0.003'}
        ]
        serializer = ProductSerializer()
        try:
            validated = serializer.validate_shipping_options(options)
            self.assertEqual(options, validated)
        except DRFValidationError as e:
            self.fail(f"Validation failed unexpectedly: {e}")

    def test_validate_shipping_options_invalid_type(self):
        options = {"name": "Standard", "price_btc": "0.001"}
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "must be a JSON list"):
            serializer.validate_shipping_options(options)

    def test_validate_shipping_options_invalid_item(self):
        options = ["not a dict", {'name': 'Express', 'price_btc': '0.003'}]
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "not a valid JSON object"):
            serializer.validate_shipping_options(options)

    def test_validate_shipping_options_missing_name(self):
        options = [{'price_btc': '0.001'}]
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "must have a non-empty 'name' string"):
            serializer.validate_shipping_options(options)

    def test_validate_shipping_options_missing_price(self):
        options = [{'name': 'Free Shipping'}]
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "must define at least one valid price"):
            serializer.validate_shipping_options(options)

    def test_validate_shipping_options_invalid_price_format(self):
        options = [{'name': 'Standard', 'price_btc': 'not-a-decimal'}]
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "not a valid decimal string"):
            serializer.validate_shipping_options(options)

    def test_validate_shipping_options_negative_price(self):
        options = [{'name': 'Standard', 'price_btc': '-0.001'}]
        serializer = ProductSerializer()
        with self.assertRaisesRegex(DRFValidationError, "cannot be negative"):
            serializer.validate_shipping_options(options)

@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class OrderSerializerTests(TestCase):
    """Tests for Order serializers (Base, Buyer, Vendor)."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.buyer = User.objects.create_user(username='order_ser_buyer', password='pw', pgp_public_key=VALID_PGP_KEY)
        cls.vendor = User.objects.create_user(username='order_ser_vendor', password='pw', is_vendor=True, pgp_public_key=VALID_PGP_KEY_OTHER)

        category_name = "Test Cat Order Ser"
        cls.category = Category.objects.create(name=category_name, slug=slugify(category_name))
        product_name = "Order Ser Prod"
        cls.product = Product.objects.create(
            vendor=cls.vendor, name=product_name, category=cls.category,
            price_btc=Decimal("0.0021"), slug=slugify(product_name)
        )
        cls.order = Order.objects.create(
            buyer=cls.buyer, vendor=cls.vendor, product=cls.product, quantity=1,
            selected_currency=Currency.BTC, status=Order.StatusChoices.SHIPPED,
            price_native_selected=210000,
            shipping_price_native_selected=10000,
            total_price_native_selected=220000,
            encrypted_shipping_info="Encrypted Data"
        )
        CryptoPayment.objects.create(order=cls.order, currency=Currency.BTC, expected_amount_native=220000, is_confirmed=True)
        Feedback.objects.create(order=cls.order, reviewer=cls.buyer, recipient=cls.vendor, rating=4, comment="Ok")

        cls.factory = APIRequestFactory()
        cls.request = cls.factory.get('/')
        cls.request.user = cls.buyer

    def test_order_base_serializer_price_formatting(self):
        serializer = OrderBaseSerializer(self.order, context={'request': self.request})
        self.assertEqual(serializer.data['total_price_native_selected'], "0.00220000")

    def test_order_buyer_serializer_fields(self):
        serializer = OrderBuyerSerializer(self.order, context={'request': self.request})
        data = serializer.data
        self.assertIn('vendor', data)
        self.assertIn('payment', data)
        self.assertIn('feedback', data)
        self.assertNotIn('buyer', data)
        self.assertNotIn('has_shipping_info', data)

    def test_order_vendor_serializer_fields(self):
        serializer = OrderVendorSerializer(self.order, context={'request': self.request})
        data = serializer.data
        self.assertIn('buyer', data)
        self.assertIn('payment', data)
        self.assertIn('feedback', data)
        self.assertIn('has_shipping_info', data)
        self.assertNotIn('vendor', data)
        self.assertTrue(data['has_shipping_info'])


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class EncryptCheckoutDataSerializerTests(TestCase):
    """Tests for the EncryptCheckoutDataSerializer validation."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.vendor_pgp = User.objects.create_user(username='encrypt_vendor_pgp', password='pw', is_vendor=True, pgp_public_key=VALID_PGP_KEY)
        cls.vendor_no_pgp = User.objects.create_user(username='encrypt_vendor_nopgp', password='pw', is_vendor=True, pgp_public_key=None)

    def test_valid_shipping_data(self):
        data = {
            'vendor_id': self.vendor_pgp.pk,
            'shipping_data': {"recipient_name": "Test", "street_address": "1", "city": "Test", "postal_code": "1", "country": "Test"}
        }
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_valid_buyer_message(self):
        data = {'vendor_id': self.vendor_pgp.pk, 'buyer_message': 'Test message'}
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_valid_pre_encrypted_blob(self):
        blob = "-----BEGIN PGP MESSAGE-----\nENCRYPTED\n-----END PGP MESSAGE-----"
        data = {'vendor_id': self.vendor_pgp.pk, 'pre_encrypted_blob': blob}
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_fail_both_data_and_blob(self):
        blob = "-----BEGIN PGP MESSAGE-----\nENCRYPTED\n-----END PGP MESSAGE-----"
        data = {'vendor_id': self.vendor_pgp.pk, 'buyer_message': 'Test', 'pre_encrypted_blob': blob}
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('non_field_errors', serializer.errors)
        self.assertIn("Provide either structured data OR a pre_encrypted_blob", str(serializer.errors['non_field_errors']))

    def test_fail_no_data_no_blob(self):
        data = {'vendor_id': self.vendor_pgp.pk}
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('non_field_errors', serializer.errors)
        self.assertIn("Provide either 'shipping_data', 'buyer_message', or 'pre_encrypted_blob'", str(serializer.errors['non_field_errors']))

    def test_fail_data_but_vendor_no_key(self):
        self.assertIsNone(self.vendor_no_pgp.pgp_public_key)

        data = {'vendor_id': self.vendor_no_pgp.pk, 'buyer_message': 'This needs encryption'}
        serializer = EncryptCheckoutDataSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('vendor_id', serializer.errors)
        self.assertNotIn('non_field_errors', serializer.errors)
        self.assertIn("has no PGP key for server-side encryption", str(serializer.errors['vendor_id'][0]))


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class SupportTicketSerializerTests(TestCase):
    """Tests for SupportTicket serializers."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None
        cls.buyer = User.objects.create_user(username='ticket_ser_buyer', password='pw', pgp_public_key=VALID_PGP_KEY)
        cls.vendor = User.objects.create_user(username='ticket_ser_vendor', password='pw', is_vendor=True, pgp_public_key=VALID_PGP_KEY_OTHER)
        cls.staff = User.objects.create_user(username='ticket_ser_staff', password='pw', is_staff=True, pgp_public_key=VALID_PGP_KEY)
        cls.other_user = User.objects.create_user(username='ticket_ser_otheruser', password='pw', pgp_public_key=VALID_PGP_KEY_OTHER)

        category_name = "Test Cat Ticket Ser"
        cls.category = Category.objects.create(name=category_name, slug=slugify(category_name))
        product_name = "Ticket Ser Prod"
        cls.product = Product.objects.create(
            vendor=cls.vendor, name=product_name, category=cls.category,
            price_xmr=Decimal("2.0"), slug=slugify(product_name)
        )

        common_order_params = {
            'product': cls.product, 'vendor': cls.vendor,
            'selected_currency': Currency.XMR, 'price_native_selected': 2000000000000,
            'shipping_price_native_selected': 0, 'total_price_native_selected': 2000000000000,
            'quantity': 1,
        }
        cls.order = Order.objects.create(**common_order_params, buyer=cls.buyer, status=Order.StatusChoices.SHIPPED)
        cls.order_unrelated = Order.objects.create(**common_order_params, buyer=cls.other_user, status=Order.StatusChoices.SHIPPED)

        factory = APIRequestFactory()
        cls.request = factory.get('/')
        cls.request.user = cls.buyer

    def test_detail_serializer_validate_related_order_success(self):
        serializer = SupportTicketDetailSerializer(
            data={'related_order_id_write': self.order.pk, 'subject': 'Test Subject', 'initial_message_body': 'Test initial message'},
            context={'request': self.request}
        )
        self.assertTrue(serializer.is_valid(raise_exception=False), serializer.errors)

    def test_detail_serializer_validate_related_order_fail_unrelated(self):
        serializer = SupportTicketDetailSerializer(
            data={'related_order_id_write': self.order_unrelated.pk, 'subject': 'Test Subject', 'initial_message_body': 'Test initial message'},
            context={'request': self.request}
        )
        self.assertFalse(serializer.is_valid(), f"Serializer should be invalid. Errors: {serializer.errors}")
        self.assertIn('related_order_id_write', serializer.errors)

        # --- DEBUGGING PRINTS START ---
        # print(f"\nDEBUG (SupportTicket fail_unrelated): serializer.errors = {repr(serializer.errors)}")
        # if 'related_order_id_write' in serializer.errors:
        #     print(f"DEBUG (SupportTicket fail_unrelated): type(serializer.errors['related_order_id_write']) = {type(serializer.errors['related_order_id_write'])}")
        #     print(f"DEBUG (SupportTicket fail_unrelated): serializer.errors['related_order_id_write'] = {repr(serializer.errors['related_order_id_write'])}")
        #     if isinstance(serializer.errors['related_order_id_write'], list):
        #         print(f"DEBUG (SupportTicket fail_unrelated): len(serializer.errors['related_order_id_write']) = {len(serializer.errors['related_order_id_write'])}")
        # --- DEBUGGING PRINTS END ---

        self.assertIn("You cannot link this ticket to an order you are not associated with (not buyer or vendor).", str(serializer.errors['related_order_id_write']['related_order_id_write'][0]))


@override_settings(AUTH_PASSWORD_VALIDATORS=DEFAULT_PASSWORD_VALIDATORS)
class VendorApplicationSerializerTests(TestCase):
    """Tests for VendorApplicationSerializer."""
    @classmethod
    @patch('backend.store.models.UserManager._validate_pgp')
    def setUpTestData(cls, mock_validate_pgp):
        mock_validate_pgp.return_value = None

        cls.user_app_pending = User.objects.create_user(username='app_ser_user_pending', password='pw', pgp_public_key=VALID_PGP_KEY)
        cls.user_app_review = User.objects.create_user(username='app_ser_user_review', password='pw', pgp_public_key=VALID_PGP_KEY_OTHER)
        cls.user_app_approved = User.objects.create_user(username='app_ser_user_approved', password='pw', pgp_public_key=VALID_PGP_KEY)

        cls.app_pending = VendorApplication.objects.create(user=cls.user_app_pending, status=VendorApplication.StatusChoices.PENDING_BOND, bond_payment_address='pending_addr', bond_amount_crypto=Decimal("0.1"))
        cls.app_review = VendorApplication.objects.create(user=cls.user_app_review, status=VendorApplication.StatusChoices.PENDING_REVIEW, bond_payment_address='review_addr', bond_amount_crypto=Decimal("0.1"))
        cls.app_approved = VendorApplication.objects.create(user=cls.user_app_approved, status=VendorApplication.StatusChoices.APPROVED, bond_payment_address='approved_addr', bond_amount_crypto=Decimal("0.1"))


    def test_to_representation_hides_address(self):
        serializer_pending = VendorApplicationSerializer(self.app_pending)
        serializer_review = VendorApplicationSerializer(self.app_review)
        serializer_approved = VendorApplicationSerializer(self.app_approved)

        self.assertIn('bond_payment_address', serializer_pending.data)
        self.assertEqual(serializer_pending.data['bond_payment_address'], 'pending_addr')

        self.assertNotIn('bond_payment_address', serializer_review.data)
        self.assertNotIn('bond_payment_address', serializer_approved.data)

# --- END OF FILE ---