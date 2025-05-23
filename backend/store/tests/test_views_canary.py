# backend/store/tests/test_views_canary.py
# Revision: 1.0 (Initial Creation)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains tests for the API view in views/canary.py (CanaryDetailView).

# Standard Library Imports
# (No specific standard library imports needed beyond testing framework)

# Django Imports
from django.urls import reverse
from django.utils import timezone
# from django.contrib.auth import get_user_model # Not needed for canary tests

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import GlobalSettings # Import the Singleton model
# from backend.store.serializers import CanarySerializer # Import if needed for validation

# --- Constants ---
# User = get_user_model() # Not needed
CANARY_URL = reverse('store:canary-detail')

# --- Test Cases ---

class CanaryViewTests(APITestCase):
    """Tests for CanaryDetailView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        # Ensure the GlobalSettings singleton exists and set canary data
        # get_solo() creates the instance if it doesn't exist
        settings_instance = GlobalSettings.get_solo()
        cls.canary_content = "Test canary content statement."
        cls.canary_last_updated = timezone.now().date()
        cls.canary_pgp_signature = "-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----"
        cls.canary_signing_key_fingerprint = "FINGERPRINT1234567890ABCDEF1234567890ABCDEF"
        cls.canary_signing_key_url = "http://example.com/key.asc"

        settings_instance.canary_content = cls.canary_content
        settings_instance.canary_last_updated = cls.canary_last_updated
        settings_instance.canary_pgp_signature = cls.canary_pgp_signature
        settings_instance.canary_signing_key_fingerprint = cls.canary_signing_key_fingerprint
        settings_instance.canary_signing_key_url = cls.canary_signing_key_url
        settings_instance.save()

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        # No authentication needed as the view uses AllowAny

    def test_retrieve_canary_success(self):
        """Verify any user (authenticated or not) can retrieve the canary details."""
        response = self.client.get(CANARY_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the data matches the fields set in setUpTestData
        # These field names come from CanarySerializer
        self.assertEqual(response.data['canary_content'], self.canary_content)
        self.assertEqual(response.data['canary_last_updated'], self.canary_last_updated.isoformat())
        self.assertEqual(response.data['canary_pgp_signature'], self.canary_pgp_signature)
        self.assertEqual(response.data['canary_signing_key_fingerprint'], self.canary_signing_key_fingerprint)
        self.assertEqual(response.data['canary_signing_key_url'], self.canary_signing_key_url)

    # Optional: Test case if GlobalSettings somehow doesn't exist, though difficult to force with django-solo
    # def test_retrieve_canary_no_settings_instance(self):
    #     """Verify behavior if GlobalSettings instance is missing (should raise 404/500)."""
    #     # Need a way to reliably delete the singleton instance *before* the request
    #     # This might require direct DB manipulation or mocking get_solo()
    #     with patch('backend.store.models.GlobalSettings.get_solo') as mock_get_solo:
    #         mock_get_solo.side_effect = GlobalSettings.DoesNotExist
    #         response = self.client.get(CANARY_URL)
    #         # The view maps DoesNotExist to NotFound (404)
    #         self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# --- END OF FILE ---