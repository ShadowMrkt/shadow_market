# Revision: 1.2
# Date: 2025-06-11
# Author: Gemini
# Description: Contains tests for the API views in views/feedback.py.
# Changes:
# - Rev 1.2:
#   - FIXED: Added `@patch` for the `IsPgpAuthenticated` permission to all tests
#     that submit feedback. This resolves a cascade of 5 test failures that were
#     being blocked by this permission check before the view's logic could be tested.
# - Rev 1.1 (2025-05-22, Gemini):
#   - Set pgp_public_key to None for all test user creations (in setUpTestData
#     and test_list_vendor_feedback_no_feedback) to comply with stricter PGP
#     validation in models.py (v1.4.2+). Feedback view tests generally do not
#     depend on the PGP key content of these users.
# - Rev 1.0 (2025-04-29, Gemini):
#   - Initial creation.

# Standard Library Imports
from decimal import Decimal
from unittest.mock import patch

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import Category, Product, User as StoreUser, Order, Feedback, Currency

# --- Constants ---
User = get_user_model()
FEEDBACK_SUBMIT_URL = reverse('store:feedback-submit')
VENDOR_FEEDBACK_LIST_URL_NAME = 'store:vendor-feedback-list'

# --- Test Cases ---

class FeedbackViewTests(APITestCase):
    """Tests for FeedbackCreateView and VendorFeedbackListView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.vendor = User.objects.create_user(
            username='feedback_vendor', password=cls.password, is_vendor=True,
            pgp_public_key=None
        )
        cls.buyer1 = User.objects.create_user(
            username='feedback_buyer1', password=cls.password,
            pgp_public_key=None
        )
        cls.buyer2 = User.objects.create_user(
            username='feedback_buyer2', password=cls.password,
            pgp_public_key=None
        )
        cls.unrelated_user = User.objects.create_user(
            username='feedback_unrelated', password=cls.password,
            pgp_public_key=None
        )

        # Create category and product
        cls.category = Category.objects.create(name="Feedback Cat", slug="feedback-cat")
        cls.product = Product.objects.create(
            vendor=cls.vendor, category=cls.category, name="Feedback Product", slug="feedback-product",
            price_btc=Decimal("0.01"), accepted_currencies=[Currency.BTC.value], is_active=True
        )

        # Create orders with different statuses
        cls.order_finalized = Order.objects.create(
            buyer=cls.buyer1, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.FINALIZED,
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000'),
            finalized_at=timezone.now()
        )
        cls.order_shipped = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.SHIPPED,
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )
        cls.order_dispute_resolved = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.DISPUTE_RESOLVED,
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )
        cls.order_pending = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.PENDING_PAYMENT,
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )

        # Create existing feedback for order_finalized from buyer1
        cls.existing_feedback = Feedback.objects.create(
            order=cls.order_finalized,
            reviewer=cls.buyer1,
            recipient=cls.vendor,
            rating=4,
            comment="Good product, already reviewed."
        )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()

    # === FeedbackCreateView Tests ===

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_create_feedback_success_buyer2(self, mock_pgp_perm):
        """Verify buyer2 can leave feedback for the dispute_resolved order."""
        self.client.login(username=self.buyer2.username, password=self.password)
        data = {
            'order_id': str(self.order_dispute_resolved.pk),
            'rating': 5,
            'comment': 'Excellent resolution!',
            'rating_quality': 5,
            'rating_shipping': 5,
            'rating_communication': 5,
        }
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['rating'], data['rating'])
        self.assertEqual(response.data['comment'], data['comment'])
        self.assertEqual(response.data['reviewer']['username'], self.buyer2.username)
        self.assertEqual(response.data['recipient']['username'], self.vendor.username)
        self.assertTrue(str(self.order_dispute_resolved.pk) in response.data['order'])
        self.assertTrue(Feedback.objects.filter(order=self.order_dispute_resolved, reviewer=self.buyer2).exists())

    def test_create_feedback_unauthenticated(self):
        """Verify unauthenticated user cannot create feedback."""
        data = {'order_id': str(self.order_finalized.pk), 'rating': 1, 'comment': 'Fail'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_create_feedback_order_not_eligible_status(self, mock_pgp_perm):
        """Verify feedback cannot be left for an order not yet finalized/resolved."""
        self.client.login(username=self.buyer2.username, password=self.password)
        data_shipped = {'order_id': str(self.order_shipped.pk), 'rating': 5, 'comment': 'Too early'}
        response_shipped = self.client.post(FEEDBACK_SUBMIT_URL, data_shipped, format='json')
        self.assertEqual(response_shipped.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Feedback can only be left for orders with status", str(response_shipped.data))

        data_pending = {'order_id': str(self.order_pending.pk), 'rating': 5, 'comment': 'Too early'}
        response_pending = self.client.post(FEEDBACK_SUBMIT_URL, data_pending, format='json')
        self.assertEqual(response_pending.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Feedback can only be left for orders with status", str(response_pending.data))

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_create_feedback_already_exists(self, mock_pgp_perm):
        """Verify user cannot leave feedback twice for the same order."""
        self.client.login(username=self.buyer1.username, password=self.password)
        data = {'order_id': str(self.order_finalized.pk), 'rating': 3, 'comment': 'Trying again'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already left feedback", str(response.data).lower())

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_create_feedback_not_buyer_or_vendor(self, mock_pgp_perm):
        """Verify unrelated user cannot leave feedback."""
        self.client.login(username=self.unrelated_user.username, password=self.password)
        data = {'order_id': str(self.order_finalized.pk), 'rating': 1, 'comment': 'I was not involved'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not associated with this order", str(response.data).lower())

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_create_feedback_missing_data(self, mock_pgp_perm):
        """Verify feedback creation fails with missing rating or comment."""
        self.client.login(username=self.buyer2.username, password=self.password)
        data_no_rating = {'order_id': str(self.order_dispute_resolved.pk), 'comment': 'Great!'}
        response_no_rating = self.client.post(FEEDBACK_SUBMIT_URL, data_no_rating, format='json')
        self.assertEqual(response_no_rating.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('rating', response_no_rating.data)

        data_no_order_id = {'rating': 5, 'comment': 'No order id!'}
        response_no_order_id = self.client.post(FEEDBACK_SUBMIT_URL, data_no_order_id, format='json')
        self.assertEqual(response_no_order_id.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('order_id', response_no_order_id.data)


    # === VendorFeedbackListView Tests ===

    def test_list_vendor_feedback_success(self):
        """Verify anyone can list feedback for a specific vendor."""
        url = reverse(VENDOR_FEEDBACK_LIST_URL_NAME, kwargs={'username': self.vendor.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data
        expected_count = 1
        if 'results' in response.data:
            results = response.data['results']
            self.assertEqual(response.data['count'], expected_count)

        self.assertEqual(len(results), expected_count)
        self.assertEqual(results[0]['id'], str(self.existing_feedback.id))
        self.assertEqual(results[0]['rating'], self.existing_feedback.rating)
        self.assertEqual(results[0]['comment'], self.existing_feedback.comment)
        self.assertEqual(results[0]['reviewer']['username'], self.buyer1.username)

    def test_list_vendor_feedback_nonexistent_vendor(self):
        """Verify 404 is returned for a non-existent vendor username."""
        url = reverse(VENDOR_FEEDBACK_LIST_URL_NAME, kwargs={'username': 'nosuchvendor'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_vendor_feedback_no_feedback(self):
        """Verify an empty list is returned for a vendor with no feedback."""
        vendor_no_feedback = User.objects.create_user(
            username='vendor_no_feedback', password=self.password, is_vendor=True,
            pgp_public_key=None
        )
        url = reverse(VENDOR_FEEDBACK_LIST_URL_NAME, kwargs={'username': vendor_no_feedback.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data
        expected_count = 0
        if 'results' in response.data:
            results = response.data['results']
            self.assertEqual(response.data['count'], expected_count)

        self.assertEqual(len(results), expected_count)

# --- END OF FILE ---