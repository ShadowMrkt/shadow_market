# backend/store/tests/test_views_order.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/order.py.
# Changes:
# - Rev 1.1:
#   - Set VALID_PGP_ORDER to None. All test users in setUpTestData are now
#     created with pgp_public_key=None to comply with stricter PGP validation
#     in models.py (v1.4.2+).
#   - Ensured .value is used for Enum fields (Currency, Order.StatusChoices)
#     during model creation in setUpTestData.
#   - Ensured UUID PKs are passed as strings in data for POST/PATCH requests where appropriate.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-20
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/order.py.

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
import json
import uuid # Added for mock_saved_order.pk

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import (
    Category, Product, User as StoreUser, Order, Feedback, Currency, CryptoPayment, # Renamed User to avoid conflict
    Dispute # Import Dispute if testing dispute view
)
# Import exceptions raised/handled by views/services
from backend.store.exceptions import EscrowError, CryptoProcessingError
# Import permissions if needed for mocking
# from backend.store.permissions import IsPgpAuthenticated

# --- Constants ---
User = get_user_model() # Use Django's recommended way
ORDER_LIST_URL = reverse('store:order-list')
PLACE_ORDER_URL = reverse('store:order-place')
# Detail/Action URLs need placeholders
ORDER_DETAIL_URL_NAME = 'store:order-detail'
ORDER_SHIP_URL_NAME = 'store:order-ship'
ORDER_FINALIZE_URL_NAME = 'store:order-finalize'
ORDER_DISPUTE_URL_NAME = 'store:order-dispute'
# Add others as needed (prepare-release, sign-release)

VALID_PGP_ORDER = None # Set to None for test user creation

# --- Test Cases ---

@patch('backend.store.views.order.log_audit_event', MagicMock()) # Mock audit logging
@patch('backend.store.views.order.create_notification', MagicMock()) # Mock notifications
class OrderViewTests(APITestCase):
    """Tests for OrderViewSet and Order Action views."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.buyer1 = User.objects.create_user(
            username='order_buyer1', password=cls.password, pgp_public_key=VALID_PGP_ORDER
        )
        cls.vendor1 = User.objects.create_user(
            username='order_vendor1', password=cls.password, is_vendor=True, pgp_public_key=VALID_PGP_ORDER
        )
        cls.buyer2 = User.objects.create_user(
            username='order_buyer2', password=cls.password, pgp_public_key=VALID_PGP_ORDER
        )
        cls.vendor2 = User.objects.create_user(
            username='order_vendor2', password=cls.password, is_vendor=True, pgp_public_key=VALID_PGP_ORDER
        )
        cls.staff_user = User.objects.create_user(
            username='order_staff', password=cls.password, is_staff=True, pgp_public_key=VALID_PGP_ORDER
        )
        cls.unrelated_user = User.objects.create_user(
            username='order_unrelated', password=cls.password, pgp_public_key=VALID_PGP_ORDER
        )

        # Create category and products
        cls.cat = Category.objects.create(name="Order Test Cat", slug="order-test-cat")
        cls.product_btc = Product.objects.create(
            vendor=cls.vendor1, category=cls.cat, name="BTC Product", slug="btc-product",
            price_btc=Decimal("0.002"), accepted_currencies=Currency.BTC.value, quantity=10, is_active=True,
        )
        cls.product_xmr_physical = Product.objects.create(
            vendor=cls.vendor1, category=cls.cat, name="XMR Physical Product", slug="xmr-physical-product",
            price_xmr=Decimal("1.5"), accepted_currencies=Currency.XMR.value, quantity=5, is_active=True,
            ships_from="USA", ships_to="USA,CAN", # Mark as physical
            shipping_options=[{'name': 'Standard', 'price_xmr': '0.1', 'price_xmr_native': '100000000000'}]
        )
        cls.product_inactive = Product.objects.create(
            vendor=cls.vendor1, category=cls.cat, name="Order Inactive Product", slug="order-inactive-product",
            price_btc=Decimal("0.01"), accepted_currencies=Currency.BTC.value, quantity=10, is_active=False # Inactive
        )

        # Create Orders (Prices are example atomic units)
        cls.order1 = Order.objects.create(
            buyer=cls.buyer1, vendor=cls.vendor1, product=cls.product_btc, quantity=1,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.FINALIZED.value,
            price_native_selected=Decimal('200000'), shipping_price_native_selected=Decimal('0'), total_price_native_selected=Decimal('200000'),
            finalized_at=timezone.now()
        )
        Feedback.objects.create(order=cls.order1, reviewer=cls.buyer1, recipient=cls.vendor1, rating=5, comment="Order1 Feedback")

        cls.order2 = Order.objects.create(
            buyer=cls.buyer1, vendor=cls.vendor1, product=cls.product_xmr_physical, quantity=1,
            selected_currency=Currency.XMR.value, status=Order.StatusChoices.SHIPPED.value,
            price_native_selected=Decimal('1500000000000'), shipping_price_native_selected=Decimal('100000000000'), total_price_native_selected=Decimal('1600000000000'),
            selected_shipping_option={'name': 'Standard', 'price_xmr': '0.1', 'price_xmr_native': '100000000000'},
            encrypted_shipping_info="ENCRYPTED BLOB FOR ORDER 2",
            shipped_at=timezone.now()
        )
        CryptoPayment.objects.create(order=cls.order2, currency=Currency.XMR.value, payment_address="xmr_address_order2", expected_amount_native=Decimal('1600000000000'), is_confirmed=True)

        cls.order3 = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor1, product=cls.product_btc, quantity=2,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.PAYMENT_CONFIRMED.value,
            price_native_selected=Decimal('200000'), shipping_price_native_selected=Decimal('0'), total_price_native_selected=Decimal('400000'),
            paid_at=timezone.now()
        )
        CryptoPayment.objects.create(order=cls.order3, currency=Currency.BTC.value, payment_address="btc_address_order3", expected_amount_native=Decimal('400000'), is_confirmed=True)

        cls.order4 = Order.objects.create(
            buyer=cls.buyer1, vendor=cls.vendor2, product=cls.product_btc, quantity=1,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.PENDING_PAYMENT.value,
            price_native_selected=Decimal('200000'), shipping_price_native_selected=Decimal('0'), total_price_native_selected=Decimal('200000'),
        )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.client.login(username=self.buyer1.username, password=self.password)

    # === OrderViewSet Tests (List/Retrieve) ===

    def test_list_orders_buyer(self):
        response = self.client.get(ORDER_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 3)
        order_ids = {o['id'] for o in results}
        self.assertIn(str(self.order1.id), order_ids)
        self.assertIn(str(self.order2.id), order_ids)
        self.assertIn(str(self.order4.id), order_ids)

    def test_list_orders_vendor(self):
        self.client.login(username=self.vendor1.username, password=self.password)
        response = self.client.get(ORDER_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 3)
        order_ids = {o['id'] for o in results}
        self.assertIn(str(self.order1.id), order_ids)
        self.assertIn(str(self.order2.id), order_ids)
        self.assertIn(str(self.order3.id), order_ids)

    def test_list_orders_staff(self):
        self.client.login(username=self.staff_user.username, password=self.password)
        response = self.client.get(ORDER_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 4)

    def test_list_orders_filter_status(self):
        response = self.client.get(ORDER_LIST_URL + f'?status={Order.StatusChoices.SHIPPED.value}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], str(self.order2.id))

    def test_list_orders_unauthenticated(self):
        self.client.logout()
        response = self.client.get(ORDER_LIST_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_retrieve_order_buyer(self):
        url = reverse(ORDER_DETAIL_URL_NAME, kwargs={'pk': self.order1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.order1.id))
        self.assertEqual(response.data['buyer']['username'], self.buyer1.username)
        self.assertEqual(response.data['vendor']['username'], self.vendor1.username)
        self.assertIn('feedback', response.data)
        self.assertEqual(response.data['feedback']['comment'], "Order1 Feedback")

    def test_retrieve_order_vendor(self):
        self.client.login(username=self.vendor1.username, password=self.password)
        url = reverse(ORDER_DETAIL_URL_NAME, kwargs={'pk': self.order2.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.order2.id))
        self.assertEqual(response.data['vendor']['username'], self.vendor1.username)
        self.assertEqual(response.data['buyer']['username'], self.buyer1.username)
        self.assertIn('has_shipping_info', response.data) # Assuming serializer exposes this
        self.assertTrue(response.data['has_shipping_info'])
        self.assertIn('payment', response.data)
        self.assertTrue(response.data['payment']['is_confirmed'])

    def test_retrieve_order_unrelated_user(self):
        self.client.login(username=self.unrelated_user.username, password=self.password)
        url = reverse(ORDER_DETAIL_URL_NAME, kwargs={'pk': self.order1.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


    # === PlaceOrderView Tests ===
    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.order.escrow_service')
    def test_place_order_success(self, mock_escrow_service, mock_pgp_perm):
        mock_payment = CryptoPayment(currency=Currency.BTC.value, expected_amount_native=Decimal('200000'), is_confirmed=False, payment_address="testbtcaddress")
        mock_saved_order = Order(
            pk=uuid.uuid4(), buyer=self.buyer1, vendor=self.product_btc.vendor,
            product=self.product_btc, status=Order.StatusChoices.PENDING_PAYMENT.value,
            selected_currency=Currency.BTC.value, total_price_native_selected=Decimal('200000'),
            payment=mock_payment # Associate mock payment if serializer expects it
        )
        mock_escrow_service.create_escrow_for_order.return_value = mock_saved_order

        data = {
            'product_id': str(self.product_btc.pk),
            'quantity': 1,
            'selected_currency': Currency.BTC.value,
        }
        response = self.client.post(PLACE_ORDER_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_pgp_perm.assert_called_once()
        mock_escrow_service.create_escrow_for_order.assert_called_once()
        passed_order_arg = mock_escrow_service.create_escrow_for_order.call_args[0][0]
        self.assertIsInstance(passed_order_arg, Order)
        self.assertEqual(passed_order_arg.product_id, self.product_btc.pk)
        self.assertEqual(passed_order_arg.buyer, self.buyer1)
        self.assertEqual(response.data['id'], str(mock_saved_order.pk))
        self.assertEqual(response.data['status'], mock_saved_order.status)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_place_order_inactive_product(self, mock_pgp_perm):
        data = {'product_id': str(self.product_inactive.pk), 'quantity': 1, 'selected_currency': Currency.BTC.value}
        response = self.client.post(PLACE_ORDER_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_place_order_invalid_currency(self, mock_pgp_perm):
        data = {'product_id': str(self.product_btc.pk), 'quantity': 1, 'selected_currency': Currency.XMR.value}
        response = self.client.post(PLACE_ORDER_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not accepted for this product", str(response.data).lower())

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_place_order_missing_shipping_info(self, mock_pgp_perm):
        data = {
            'product_id': str(self.product_xmr_physical.pk),
            'quantity': 1,
            'selected_currency': Currency.XMR.value,
        }
        response = self.client.post(PLACE_ORDER_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("encrypted_shipping_blob", str(response.data).lower()) # Check for specific field name from serializer
        self.assertIn("shipping_option_name", str(response.data).lower())


    # === Order Action View Tests (Example: MarkShipped) ===
    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.order.escrow_service')
    def test_mark_shipped_success(self, mock_escrow_service, mock_pgp_perm):
        self.client.login(username=self.vendor1.username, password=self.password)
        mock_updated_order = self.order3
        mock_updated_order.status = Order.StatusChoices.SHIPPED.value
        mock_updated_order.shipped_at = timezone.now()
        mock_escrow_service.mark_order_shipped.return_value = mock_updated_order

        url = reverse(ORDER_SHIP_URL_NAME, kwargs={'pk': self.order3.pk})
        data = {'tracking_info': 'TRACK123'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_pgp_perm.assert_called()
        mock_escrow_service.mark_order_shipped.assert_called_once_with(
            order=ANY,
            vendor=self.vendor1,
            tracking_info=data['tracking_info'],
            shipping_address_decrypted=None # Assuming not passed if not PGP decryption required at this step
        )
        self.assertEqual(response.data['status'], Order.StatusChoices.SHIPPED.value)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_mark_shipped_buyer_forbidden(self, mock_pgp_perm):
        # Buyer1 is logged in by default (setUp)
        url = reverse(ORDER_SHIP_URL_NAME, kwargs={'pk': self.order3.pk})
        data = {'tracking_info': 'TRACK123'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.order.escrow_service')
    def test_mark_shipped_wrong_status(self, mock_escrow_service, mock_pgp_perm):
        self.client.login(username=self.vendor1.username, password=self.password)
        mock_escrow_service.mark_order_shipped.side_effect = EscrowError("Order cannot be marked as shipped in its current state.")

        url = reverse(ORDER_SHIP_URL_NAME, kwargs={'pk': self.order1.pk}) # order1 is FINALIZED
        data = {'tracking_info': 'TRACK123'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Order cannot be marked as shipped", response.data['detail'])

# --- END OF FILE ---