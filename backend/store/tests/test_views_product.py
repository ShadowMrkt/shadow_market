# backend/store/tests/test_views_product.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/product.py (ProductViewSet).
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for all test user creations in setUpTestData
#     to comply with stricter PGP validation in models.py (v1.4.2+).
#   - Ensured .value is used for Enum fields (Currency) during Product creation.
#   - Passed category PK as 'category' in POST data for product creation tests,
#     assuming serializer field name matches model field name.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/product.py (ProductViewSet).

# Standard Library Imports
from decimal import Decimal
import uuid

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import Category, Product, User as StoreUser, Currency # Renamed to avoid conflict

# --- Constants ---
User = get_user_model() # Use Django's recommended way
PRODUCT_LIST_URL = reverse('store:product-list')
# Detail URL needs a placeholder for the slug
PRODUCT_DETAIL_URL_NAME = 'store:product-detail'

# --- Test Cases ---

class ProductViewSetTests(APITestCase):
    """Tests for ProductViewSet (List, Retrieve, Permissions)."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.vendor_user = User.objects.create_user(
            username='product_vendor', password=cls.password, is_vendor=True,
            pgp_public_key=None # Set to None
        )
        cls.other_vendor = User.objects.create_user(
            username='other_vendor', password=cls.password, is_vendor=True,
            pgp_public_key=None # Set to None
        )
        cls.regular_user = User.objects.create_user(
            username='product_buyer', password=cls.password,
            pgp_public_key=None # Set to None
        )

        # Create category
        cls.category = Category.objects.create(name="Test Category", slug="test-category")

        # Create products
        cls.product1 = Product.objects.create(
            vendor=cls.vendor_user, category=cls.category, name="Test Product One", slug="test-product-one",
            description="First test product", price_btc=Decimal("0.01"), price_xmr=Decimal("0.5"),
            accepted_currencies=f"{Currency.BTC.value},{Currency.XMR.value}", quantity=10, is_active=True
        )
        cls.product2 = Product.objects.create(
            vendor=cls.vendor_user, category=cls.category, name="Test Product Two", slug="test-product-two",
            description="Second test product", price_eth=Decimal("0.1"),
            accepted_currencies=Currency.ETH.value, quantity=5, is_active=True, is_featured=True
        )
        cls.product_inactive = Product.objects.create(
            vendor=cls.vendor_user, category=cls.category, name="Inactive Product", slug="inactive-product",
            description="This one is inactive", price_btc=Decimal("0.005"),
            accepted_currencies=Currency.BTC.value, quantity=20, is_active=False # Inactive
        )
        cls.product_other_vendor = Product.objects.create(
            vendor=cls.other_vendor, category=cls.category, name="Other Vendor Product", slug="other-vendor-product",
            description="Belongs to other vendor", price_btc=Decimal("0.02"),
            accepted_currencies=Currency.BTC.value, quantity=15, is_active=True
        )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        # No user logged in by default

    # === List View Tests ===

    def test_list_products_unauthenticated(self):
        """Verify unauthenticated users can list active products."""
        response = self.client.get(PRODUCT_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data
        expected_count = 3 # product1, product2, product_other_vendor
        if 'results' in response.data: # Handle paginated response
            results = response.data['results']
            self.assertIn('count', response.data)
            self.assertEqual(response.data['count'], expected_count)

        self.assertEqual(len(results), expected_count)
        product_slugs = {p['slug'] for p in results}
        self.assertIn(self.product1.slug, product_slugs)
        self.assertIn(self.product2.slug, product_slugs)
        self.assertIn(self.product_other_vendor.slug, product_slugs)
        self.assertNotIn(self.product_inactive.slug, product_slugs) # Inactive should not be listed

    # === Retrieve View Tests ===

    def test_retrieve_active_product_success(self):
        """Verify any user can retrieve an active product."""
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.product1.id))
        self.assertEqual(response.data['name'], self.product1.name)
        self.assertEqual(response.data['slug'], self.product1.slug)
        self.assertEqual(response.data['vendor']['username'], self.vendor_user.username)
        self.assertEqual(response.data['category']['slug'], self.category.slug)
        self.assertEqual(response.data['price_btc'], "0.01000000")
        self.assertEqual(response.data['price_xmr'], "0.500000000000")

    def test_retrieve_inactive_product_404(self):
        """Verify inactive products return 404 for non-owner/non-staff."""
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product_inactive.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_nonexistent_product_404(self):
        """Verify non-existent slug returns 404."""
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': 'does-not-exist'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # === Create/Update/Delete Permission Tests ===

    def test_create_product_unauthenticated(self):
        """Verify unauthenticated user cannot create product."""
        data = {'name': 'Fail Create', 'category': self.category.id, 'price_btc': '0.1', 'accepted_currencies': Currency.BTC.value, 'slug': 'fail-create-slug'}
        response = self.client.post(PRODUCT_LIST_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_create_product_non_vendor(self):
        """Verify regular user cannot create product."""
        self.client.login(username=self.regular_user.username, password=self.password)
        data = {'name': 'Fail Create', 'category': self.category.id, 'price_btc': '0.1', 'accepted_currencies': Currency.BTC.value, 'slug': 'fail-create-slug-user'}
        response = self.client.post(PRODUCT_LIST_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_product_unauthenticated(self):
        """Verify unauthenticated user cannot update product."""
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        data = {'description': 'Updated Description'}
        response = self.client.patch(url, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_update_product_non_owner_vendor(self):
        """Verify vendor cannot update another vendor's product."""
        self.client.login(username=self.other_vendor.username, password=self.password)
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        data = {'description': 'Updated Description by other vendor'}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_product_regular_user(self):
        """Verify regular user cannot update product."""
        self.client.login(username=self.regular_user.username, password=self.password)
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        data = {'description': 'Updated Description by buyer'}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_product_unauthenticated(self):
        """Verify unauthenticated user cannot delete product."""
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        response = self.client.delete(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_delete_product_non_owner_vendor(self):
        """Verify vendor cannot delete another vendor's product."""
        self.client.login(username=self.other_vendor.username, password=self.password)
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Product.objects.filter(pk=self.product1.pk).exists())

    def test_delete_product_regular_user(self):
        """Verify regular user cannot delete product."""
        self.client.login(username=self.regular_user.username, password=self.password)
        url = reverse(PRODUCT_DETAIL_URL_NAME, kwargs={'slug': self.product1.slug})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Product.objects.filter(pk=self.product1.pk).exists())

# --- END OF FILE ---