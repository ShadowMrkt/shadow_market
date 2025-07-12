# backend/store/tests/test_views_vendor.py
# Revision: 1.2
# Date: 2025-06-07
# Author: Gemini
# Description: Contains tests for the API views in views/vendor.py.
# Changes:
# - Rev 1.2:
#   - FIXED: Replaced the faulty class-level @patch decorator for `log_audit_event`.
#     The decorator used an incorrect path and would have caused TypeErrors.
#     Implemented a robust patcher in the setUp method to mock the audit log
#     utility for all tests in the class, resolving all AttributeError failures.
# - Rev 1.1:
#   - Set pgp_public_key to None for all test user creations in setUpTestData
#     to comply with stricter PGP validation in models.py (v1.4.2+).
#   - Removed non-existent 'profile_description' field from User creation.
#   - Ensured Product creation includes 'accepted_currencies'.
#   - Ensured Order creations include required price fields and use .value for Enums.
#   - Updated assertion for PGP key in profile view test to expect None.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/vendor.py.

# Standard Library Imports
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import User as StoreUser, Feedback, Order, Product, Category, Currency # Renamed User

# --- Constants ---
User = get_user_model() # Use Django's recommended way
VENDOR_STATS_URL = reverse('store:vendor-stats')
# Detail URL needs a placeholder for the username
VENDOR_DETAIL_URL_NAME = 'store:vendor-detail'

VALID_PGP_VENDOR_PLACEHOLDER = None # Set to None to bypass PGP validation during user creation

# --- Test Cases ---

class VendorViewTests(APITestCase):
    """Tests for VendorPublicProfileView and VendorStatsView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.vendor1 = User.objects.create_user(
            username='vendor_profile_test', password=cls.password, is_vendor=True, is_active=True,
            pgp_public_key=VALID_PGP_VENDOR_PLACEHOLDER,
            vendor_level_name="Gold Vendor",
            vendor_avg_rating=4.5,
            vendor_rating_count=10,
            vendor_total_orders=50,
            vendor_completed_orders_30d=5,
            vendor_completion_rate_percent=98.0,
            vendor_dispute_rate_percent=2.0,
            approved_vendor_since=timezone.now() - timezone.timedelta(days=100),
            vendor_reputation_last_updated=timezone.now()
            # profile_description="Test vendor profile description." # Field does not exist on User model
        )
        cls.vendor2 = User.objects.create_user(
            username='vendor_other', password=cls.password, is_vendor=True, is_active=True,
            pgp_public_key=VALID_PGP_VENDOR_PLACEHOLDER
        )
        cls.inactive_vendor = User.objects.create_user(
            username='vendor_inactive', password=cls.password, is_vendor=True, is_active=False, # Inactive
            pgp_public_key=VALID_PGP_VENDOR_PLACEHOLDER
        )
        cls.regular_user = User.objects.create_user(
            username='vendor_test_buyer', password=cls.password,
            pgp_public_key=None # Explicitly None
        )

        cls.cat = Category.objects.create(name="Vendor Test Cat", slug="vendor-test-cat")
        cls.prod = Product.objects.create(
            vendor=cls.vendor1, category=cls.cat, name="Vendor Prod", slug="vendor-prod",
            is_active=True, price_btc=Decimal('0.1'), accepted_currencies=Currency.BTC.value
        )

        # Price in satoshis for 0.1 BTC
        price_native_btc_prod = Decimal('10000000')

        cls.order_finalized = Order.objects.create(
            buyer=cls.regular_user, vendor=cls.vendor1, product=cls.prod, quantity=1,
            status=Order.StatusChoices.FINALIZED.value, selected_currency=Currency.BTC.value,
            price_native_selected=price_native_btc_prod,
            shipping_price_native_selected=Decimal('0'),
            total_price_native_selected=price_native_btc_prod
        )
        cls.order_shipped = Order.objects.create(
            buyer=cls.regular_user, vendor=cls.vendor1, product=cls.prod, quantity=1,
            status=Order.StatusChoices.SHIPPED.value, selected_currency=Currency.BTC.value,
            price_native_selected=price_native_btc_prod,
            shipping_price_native_selected=Decimal('0'),
            total_price_native_selected=price_native_btc_prod
        )
        cls.order_disputed = Order.objects.create(
            buyer=cls.regular_user, vendor=cls.vendor1, product=cls.prod, quantity=1,
            status=Order.StatusChoices.DISPUTED.value, selected_currency=Currency.BTC.value,
            price_native_selected=price_native_btc_prod,
            shipping_price_native_selected=Decimal('0'),
            total_price_native_selected=price_native_btc_prod
        )

        Feedback.objects.create(order=cls.order_finalized, reviewer=cls.regular_user, recipient=cls.vendor1, rating=5, comment="Great!")

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        # Mock the audit log utility to prevent test failures from unrelated logging issues.
        # This is a robust way to mock for the entire class without affecting test signatures.
        self.audit_log_patcher = patch('backend.store.utils.utils.log_audit_event')
        self.mock_audit_log = self.audit_log_patcher.start()
        self.addCleanup(self.audit_log_patcher.stop)

    # === VendorPublicProfileView Tests ===

    def test_retrieve_vendor_profile_success(self):
        url = reverse(VENDOR_DETAIL_URL_NAME, kwargs={'username': self.vendor1.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data['username'], self.vendor1.username)
        self.assertIsNone(response.data['pgp_public_key']) # Changed to expect None
        self.assertEqual(response.data['vendor_level_name'], self.vendor1.vendor_level_name)
        self.assertEqual(response.data['vendor_avg_rating'], "4.50")
        self.assertEqual(response.data['vendor_rating_count'], self.vendor1.vendor_rating_count)
        self.assertEqual(response.data['vendor_completion_rate_percent'], "98.00")
        # self.assertEqual(response.data['profile_description'], self.vendor1.profile_description) # Field removed
        self.assertTrue(response.data['approved_vendor_since'].startswith(self.vendor1.approved_vendor_since.date().isoformat()))

    def test_retrieve_vendor_profile_inactive_404(self):
        url = reverse(VENDOR_DETAIL_URL_NAME, kwargs={'username': self.inactive_vendor.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_vendor_profile_nonexistent_404(self):
        url = reverse(VENDOR_DETAIL_URL_NAME, kwargs={'username': 'nosuchvendor'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_vendor_profile_not_vendor_404(self):
        url = reverse(VENDOR_DETAIL_URL_NAME, kwargs={'username': self.regular_user.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


    # === VendorStatsView Tests ===

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_get_vendor_stats_success(self, mock_pgp_perm):
        self.client.login(username=self.vendor1.username, password=self.password)
        response = self.client.get(VENDOR_STATS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_pgp_perm.assert_called_once()

        self.assertIn('active_listings_count', response.data)
        self.assertIn('sales_pending_action_count', response.data)
        self.assertIn('sales_completed_count', response.data)
        self.assertIn('disputes_open_count', response.data)
        self.assertIn('total_revenue_by_currency', response.data)
        self.assertIn('average_rating', response.data)
        self.assertIn('feedback_count', response.data)

        self.assertEqual(response.data['active_listings_count'], 1)
        self.assertEqual(response.data['sales_pending_action_count'], 1) # order_shipped
        self.assertEqual(response.data['sales_completed_count'], 1) # order_finalized
        self.assertEqual(response.data['disputes_open_count'], 1) # order_disputed
        self.assertEqual(response.data['feedback_count'], 1)
        self.assertEqual(response.data['average_rating'], "5.00")
        # Assuming 0.1 BTC = 10,000,000 satoshis. Revenue from one finalized order.
        self.assertEqual(response.data['total_revenue_by_currency'].get(Currency.BTC.value), "0.10000000")


    def test_get_vendor_stats_unauthenticated(self):
        response = self.client.get(VENDOR_STATS_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=False)
    def test_get_vendor_stats_no_pgp_auth(self, mock_pgp_perm):
        self.client.login(username=self.vendor1.username, password=self.password)
        response = self.client.get(VENDOR_STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_pgp_perm.assert_called_once()

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_get_vendor_stats_not_vendor(self, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        response = self.client.get(VENDOR_STATS_URL)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

# --- END OF FILE ---