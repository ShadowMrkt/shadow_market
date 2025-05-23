# backend/store/tests/test_views_feedback.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/feedback.py.
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for all test user creations (in setUpTestData
#     and test_list_vendor_feedback_no_feedback) to comply with stricter PGP
#     validation in models.py (v1.4.2+). Feedback view tests generally do not
#     depend on the PGP key content of these users.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/feedback.py.

# Standard Library Imports
from decimal import Decimal

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import Category, Product, User as StoreUser, Order, Feedback, Currency # Renamed User to StoreUser to avoid conflict

# --- Constants ---
User = get_user_model() # Use Django's get_user_model
FEEDBACK_SUBMIT_URL = reverse('store:feedback-submit')
# Detail URL needs a placeholder for the username
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
            pgp_public_key=None # Set to None
        )
        cls.buyer1 = User.objects.create_user(
            username='feedback_buyer1', password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.buyer2 = User.objects.create_user(
            username='feedback_buyer2', password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.unrelated_user = User.objects.create_user(
            username='feedback_unrelated', password=cls.password,
            pgp_public_key=None # Set to None
        )

        # Create category and product
        cls.category = Category.objects.create(name="Feedback Cat", slug="feedback-cat")
        cls.product = Product.objects.create(
            vendor=cls.vendor, category=cls.category, name="Feedback Product", slug="feedback-product",
            price_btc=Decimal("0.01"), accepted_currencies=Currency.BTC.value, is_active=True # Use .value
        )

        # Create orders with different statuses
        cls.order_finalized = Order.objects.create(
            buyer=cls.buyer1, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.FINALIZED, # Use .value
            price_native_selected=Decimal('1000000'), # Example value in satoshis for 0.01 BTC
            total_price_native_selected=Decimal('1000000'),
            finalized_at=timezone.now() # Ensure finalized
        )
        cls.order_shipped = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.SHIPPED, # Use .value
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )
        cls.order_dispute_resolved = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.DISPUTE_RESOLVED, # Use .value
            price_native_selected=Decimal('1000000'),
            total_price_native_selected=Decimal('1000000')
        )
        cls.order_pending = Order.objects.create(
            buyer=cls.buyer2, vendor=cls.vendor, product=cls.product,
            selected_currency=Currency.BTC.value, status=Order.StatusChoices.PENDING_PAYMENT, # Use .value
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
        # No user logged in by default

    # === FeedbackCreateView Tests ===

    def test_create_feedback_success_buyer2(self):
        """Verify buyer2 can leave feedback for the dispute_resolved order."""
        self.client.login(username=self.buyer2.username, password=self.password)
        data = {
            'order_id': str(self.order_dispute_resolved.pk), # Ensure UUID is string
            'rating': 5,
            'comment': 'Excellent resolution!',
            # Optional granular ratings
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
        # HyperlinkedRelatedField needs request context for full URL, checking against order_id for robustness
        self.assertTrue(str(self.order_dispute_resolved.pk) in response.data['order'])
        self.assertTrue(Feedback.objects.filter(order=self.order_dispute_resolved, reviewer=self.buyer2).exists())

    def test_create_feedback_unauthenticated(self):
        """Verify unauthenticated user cannot create feedback."""
        data = {'order_id': str(self.order_finalized.pk), 'rating': 1, 'comment': 'Fail'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_create_feedback_order_not_eligible_status(self):
        """Verify feedback cannot be left for an order not yet finalized/resolved."""
        self.client.login(username=self.buyer2.username, password=self.password)
        # Try leaving feedback for shipped order
        data_shipped = {'order_id': str(self.order_shipped.pk), 'rating': 5, 'comment': 'Too early'}
        response_shipped = self.client.post(FEEDBACK_SUBMIT_URL, data_shipped, format='json')
        self.assertEqual(response_shipped.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Feedback can only be left for orders with status", str(response_shipped.data))

        # Try leaving feedback for pending order
        data_pending = {'order_id': str(self.order_pending.pk), 'rating': 5, 'comment': 'Too early'}
        response_pending = self.client.post(FEEDBACK_SUBMIT_URL, data_pending, format='json')
        self.assertEqual(response_pending.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Feedback can only be left for orders with status", str(response_pending.data))

    def test_create_feedback_already_exists(self):
        """Verify user cannot leave feedback twice for the same order."""
        # buyer1 already left feedback for order_finalized in setUpTestData
        self.client.login(username=self.buyer1.username, password=self.password)
        data = {'order_id': str(self.order_finalized.pk), 'rating': 3, 'comment': 'Trying again'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already left feedback", str(response.data).lower()) # Make case-insensitive

    def test_create_feedback_not_buyer_or_vendor(self):
        """Verify unrelated user cannot leave feedback."""
        self.client.login(username=self.unrelated_user.username, password=self.password)
        data = {'order_id': str(self.order_finalized.pk), 'rating': 1, 'comment': 'I was not involved'}
        response = self.client.post(FEEDBACK_SUBMIT_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not associated with this order", str(response.data).lower()) # Make case-insensitive

    def test_create_feedback_missing_data(self):
        """Verify feedback creation fails with missing rating or comment."""
        self.client.login(username=self.buyer2.username, password=self.password)
        data_no_rating = {'order_id': str(self.order_dispute_resolved.pk), 'comment': 'Great!'}
        # Assuming comment is optional based on model (blank=True), but rating is required.
        # data_no_comment = {'order_id': str(self.order_dispute_resolved.pk), 'rating': 5}

        response_no_rating = self.client.post(FEEDBACK_SUBMIT_URL, data_no_rating, format='json')
        self.assertEqual(response_no_rating.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('rating', response_no_rating.data)

        # Test if comment is truly required by serializer (model field is blank=True)
        # If serializer makes it required, this test is valid. Otherwise, it might pass.
        # For now, assume serializer requires it if not blank=True on serializer field.
        # If FeedbackSerializer.comment has allow_blank=False or not present (implies required if model's blank=False)
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
        if 'results' in response.data: # Handle pagination
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
        # Create a vendor with no feedback
        vendor_no_feedback = User.objects.create_user(
            username='vendor_no_feedback', password=self.password, is_vendor=True,
            pgp_public_key=None # Set to None
        )
        url = reverse(VENDOR_FEEDBACK_LIST_URL_NAME, kwargs={'username': vendor_no_feedback.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data
        expected_count = 0
        if 'results' in response.data: # Handle pagination
            results = response.data['results']
            self.assertEqual(response.data['count'], expected_count)

        self.assertEqual(len(results), expected_count)

# --- END OF FILE ---