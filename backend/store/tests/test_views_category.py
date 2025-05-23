# backend/store/tests/test_views_category.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/category.py (CategoryViewSet).
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for test user creation in setUpTestData
#     to comply with stricter PGP validation in models.py (v1.4.2+).
#     Category view tests typically do not rely on user PGP key content.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/category.py (CategoryViewSet).

# Standard Library Imports
# from decimal import Decimal # Likely not needed for category tests
# import uuid

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import Category # User is retrieved via get_user_model

# --- Constants ---
User = get_user_model()
CATEGORY_LIST_URL = reverse('store:category-list')
# Detail URL needs a placeholder for the slug
CATEGORY_DETAIL_URL_NAME = 'store:category-detail'

# --- Test Cases ---

class CategoryViewSetTests(APITestCase):
    """Tests for CategoryViewSet (List, Retrieve, CUD Permissions)."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.admin_user = User.objects.create_user(
            username='cat_admin', password=cls.password, is_staff=True, is_superuser=True, # Make admin
            pgp_public_key=None # Set to None to pass new PGP validation
        )
        cls.regular_user = User.objects.create_user(
            username='cat_user', password=cls.password,
            pgp_public_key=None # Set to None to pass new PGP validation
        )

        # Create categories
        cls.parent_cat = Category.objects.create(name="Parent Category", slug="parent-category")
        cls.child_cat = Category.objects.create(name="Child Category", slug="child-category", parent=cls.parent_cat)
        cls.other_cat = Category.objects.create(name="Other Category", slug="other-category")


    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        # No user logged in by default

    # === List View Tests ===

    def test_list_categories_unauthenticated(self):
        """Verify unauthenticated users can list categories."""
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data
        expected_count = 3 # parent_cat, child_cat, other_cat
        if 'results' in response.data: # Handle pagination
            results = response.data['results']
            self.assertEqual(response.data['count'], expected_count)

        self.assertEqual(len(results), expected_count)
        category_slugs = {c['slug'] for c in results}
        self.assertIn(self.parent_cat.slug, category_slugs)
        self.assertIn(self.child_cat.slug, category_slugs)
        self.assertIn(self.other_cat.slug, category_slugs)

    def test_list_categories_authenticated_user(self):
        """Verify authenticated regular users can list categories."""
        self.client.login(username=self.regular_user.username, password=self.password)
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results'] if 'results' in response.data else response.data
        self.assertEqual(len(results), 3)

    # === Retrieve View Tests ===

    def test_retrieve_category_success(self):
        """Verify any user can retrieve a category by slug."""
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.parent_cat.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.parent_cat.id)
        self.assertEqual(response.data['name'], self.parent_cat.name)
        self.assertEqual(response.data['slug'], self.parent_cat.slug)
        # Check parent/child relationship representation if applicable
        self.assertIsNone(response.data.get('parent')) # Parent cat has no parent

        # Retrieve child
        child_url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.child_cat.slug})
        child_response = self.client.get(child_url)
        self.assertEqual(child_response.status_code, status.HTTP_200_OK)

        # Assuming parent is represented by its detail URL (HyperlinkedRelatedField)
        # or by its primary key (PrimaryKeyRelatedField)
        parent_representation = child_response.data.get('parent')
        self.assertIsNotNone(parent_representation)

        # If parent is a URL string:
        # from django.test.client import RequestFactory
        # factory = RequestFactory()
        # request = factory.get('/') # A dummy request is needed for context
        # expected_parent_url = request.build_absolute_uri(reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.parent_cat.slug}))
        # self.assertEqual(parent_representation, expected_parent_url)
        # Or if it's just the slug or ID (depending on serializer depth/config)
        # For now, we'll assume the parent ID is what might be present or its slug.
        # If it's nested, then we might check:
        # if isinstance(parent_representation, dict):
        # self.assertEqual(parent_representation.get('slug'), self.parent_cat.slug)
        # else: # Assuming it's a PK or URL string
        # self.assertTrue(str(self.parent_cat.pk) in str(parent_representation) or self.parent_cat.slug in str(parent_representation))


    def test_retrieve_nonexistent_category_404(self):
        """Verify non-existent slug returns 404."""
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': 'does-not-exist'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # === Create/Update/Delete Permission Tests ===
    # Assuming IsAdminUserOrReadOnly permission on the ViewSet

    def test_create_category_unauthenticated(self):
        """Verify unauthenticated user cannot create category."""
        data = {'name': 'Fail Create', 'slug': 'fail-create'}
        response = self.client.post(CATEGORY_LIST_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_create_category_regular_user(self):
        """Verify regular user cannot create category."""
        self.client.login(username=self.regular_user.username, password=self.password)
        data = {'name': 'Fail Create User', 'slug': 'fail-create-user'}
        response = self.client.post(CATEGORY_LIST_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_category_unauthenticated(self):
        """Verify unauthenticated user cannot update category."""
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.other_cat.slug})
        data = {'name': 'Updated Name'}
        response = self.client.patch(url, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_update_category_regular_user(self):
        """Verify regular user cannot update category."""
        self.client.login(username=self.regular_user.username, password=self.password)
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.other_cat.slug})
        data = {'name': 'Updated Name User'}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_category_unauthenticated(self):
        """Verify unauthenticated user cannot delete category."""
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.other_cat.slug})
        response = self.client.delete(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_delete_category_regular_user(self):
        """Verify regular user cannot delete category."""
        self.client.login(username=self.regular_user.username, password=self.password)
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.other_cat.slug})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Category.objects.filter(pk=self.other_cat.pk).exists()) # Ensure not deleted

    # === Create/Update/Delete Success Tests (Admin) ===

    def test_create_category_admin_success(self):
        """Verify admin user can create a category."""
        self.client.login(username=self.admin_user.username, password=self.password)
        data = {'name': 'New Admin Category', 'slug': 'new-admin-category-slug'} # Ensure slug is provided if not auto-generated by model
        response = self.client.post(CATEGORY_LIST_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], data['name'])
        self.assertTrue(Category.objects.filter(name=data['name']).exists())
        self.assertIn('slug', response.data)
        self.assertEqual(response.data['slug'], data['slug']) # Verify provided slug or auto-generated one

    def test_update_category_admin_success(self):
        """Verify admin user can update a category."""
        self.client.login(username=self.admin_user.username, password=self.password)
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': self.other_cat.slug})
        new_name = "Updated by Admin"
        new_slug = "updated-by-admin" # If slug can be updated
        data = {'name': new_name, 'slug': new_slug, 'description': 'Admin description'}
        response = self.client.patch(url, data, format='json') # PATCH for partial update
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], new_name)
        self.assertEqual(response.data['slug'], new_slug)
        self.assertEqual(response.data['description'], data['description'])

        self.other_cat.refresh_from_db()
        self.assertEqual(self.other_cat.name, new_name)
        self.assertEqual(self.other_cat.slug, new_slug)
        self.assertEqual(self.other_cat.description, data['description'])

    def test_delete_category_admin_success(self):
        """Verify admin user can delete a category."""
        # Create a category specifically for this test to avoid FK issues
        cat_to_delete = Category.objects.create(name="Delete Me", slug="delete-me")
        cat_id = cat_to_delete.id
        url = reverse(CATEGORY_DETAIL_URL_NAME, kwargs={'slug': cat_to_delete.slug})

        self.client.login(username=self.admin_user.username, password=self.password)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Category.objects.filter(pk=cat_id).exists())

# --- END OF FILE ---