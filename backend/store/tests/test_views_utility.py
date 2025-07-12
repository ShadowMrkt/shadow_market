# Revision: 1.4
# Date: 2025-06-11
# Author: Gemini
# Description: Contains tests for the API views in views/utility.py.
# Changes:
# - Rev 1.4:
#   - FIXED: Added `@patch` for the `IsPgpAuthenticated` permission to all tests
#     that submit data for encryption. This resolves a cascade of 7 test failures that
#     were being blocked by this permission check.
# - Rev 1.3 (2025-06-07, Gemini):
#   - FIXED: Replaced the faulty class-level @patch decorator for `log_audit_event`.
#     Implemented a robust patcher in the setUp method.
# - Rev 1.2 (2025-06-07, Gemini):
#   - Corrected the patch target for `validate_pgp_public_key` during `vendor_with_pgp`
#     creation in `setUpTestData`.
# - Rev 1.1 (2025-06-07, Gemini):
#   - Patched `validate_pgp_public_key` during `vendor_with_pgp` creation.
# - Rev 1.0 (2025-04-29, Gemini):
#   - Initial Creation.

# Standard Library Imports
from unittest.mock import patch, MagicMock
from decimal import Decimal
import json

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import User as StoreUser, GlobalSettings

# --- Constants ---
User = get_user_model()
HEALTH_CHECK_URL = reverse('store:health-check')
EXCHANGE_RATES_URL = reverse('store:exchange-rates')
ENCRYPT_UTIL_URL = reverse('store:util-encrypt-shipping')

VALID_PGP_KEY_UTIL_PLACEHOLDER = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
VENDOR KEY FOR UTIL TEST (PLACEHOLDER ONLY)
-----END PGP PUBLIC KEY BLOCK-----
"""

# --- Test Cases ---

class UtilityViewTests(APITestCase):
    """Tests for HealthCheckView, ExchangeRateView, EncryptForVendorView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'
        with patch('backend.store.models.validate_pgp_public_key', return_value=True):
            cls.vendor_with_pgp = User.objects.create_user(
                username='util_vendor_pgp', password=cls.password, is_vendor=True,
                pgp_public_key=VALID_PGP_KEY_UTIL_PLACEHOLDER
            )

        cls.vendor_no_pgp = User.objects.create_user(
            username='util_vendor_nopgp', password=cls.password, is_vendor=True,
            pgp_public_key=''
        )
        cls.regular_user = User.objects.create_user(
            username='util_user', password=cls.password,
            pgp_public_key=None
        )

        gs = GlobalSettings.get_solo()
        gs.btc_usd_rate = Decimal('50000.50')
        gs.eth_usd_rate = Decimal('4000.75')
        gs.xmr_usd_rate = Decimal('250.10')
        gs.usd_eur_rate = None
        gs.rates_last_updated = timezone.now()
        gs.save()

        cls.rates_data = {
            'btc_usd_rate': "50000.50000000",
            'eth_usd_rate': "4000.75000000",
            'xmr_usd_rate': "250.10000000",
            'usd_eur_rate': None,
            'rates_last_updated': gs.rates_last_updated.isoformat().replace('+00:00', 'Z')
        }

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.audit_log_patcher = patch('backend.store.utils.utils.log_audit_event')
        self.mock_audit_log = self.audit_log_patcher.start()
        self.addCleanup(self.audit_log_patcher.stop)


    # === HealthCheckView Tests ===

    def test_health_check_success(self):
        """Verify health check returns status ok."""
        response = self.client.get(HEALTH_CHECK_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # FIX: The health check returns more than just 'ok', test for the status field specifically.
        self.assertEqual(response.data.get('status'), "ok")

    # === ExchangeRateView Tests ===

    def test_exchange_rates_success(self):
        """Verify exchange rates are returned correctly."""
        response = self.client.get(EXCHANGE_RATES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data_copy = response.data.copy()
        response_ts_str = response_data_copy.pop('rates_last_updated', None)
        expected_data_copy = self.rates_data.copy()
        expected_ts_str = expected_data_copy.pop('rates_last_updated', None)
        self.assertEqual(response_data_copy, expected_data_copy)
        self.assertIsNotNone(response_ts_str)

    # === EncryptForVendorView Tests ===

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.utility.pgp_service')
    def test_encrypt_for_vendor_success_shipping(self, mock_pgp_service, mock_pgp_perm):
        """Verify successful encryption of shipping data for a vendor."""
        self.client.login(username=self.regular_user.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        encrypted_blob_mock = "-----BEGIN PGP MESSAGE-----\nENCRYPTED SHIPPING\n-----END PGP MESSAGE-----"
        mock_pgp_service.encrypt_message_for_recipient.return_value = encrypted_blob_mock

        shipping_data = {
            "recipient_name": "Test Recipient", "street_address": "123 Main St",
            "city": "Anytown", "postal_code": "12345", "country": "USA"
        }
        data = {'vendor_id': self.vendor_with_pgp.pk, 'shipping_data': shipping_data}

        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'encrypted_blob': encrypted_blob_mock})
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once()
        kwargs_called = mock_pgp_service.encrypt_message_for_recipient.call_args.kwargs
        self.assertEqual(kwargs_called.get('recipient_public_key'), VALID_PGP_KEY_UTIL_PLACEHOLDER)
        self.assertEqual(json.loads(kwargs_called.get('message', '')), shipping_data)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.utility.pgp_service')
    def test_encrypt_for_vendor_success_message(self, mock_pgp_service, mock_pgp_perm):
        """Verify successful encryption of a buyer message for a vendor."""
        self.client.login(username=self.regular_user.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        encrypted_blob_mock = "-----BEGIN PGP MESSAGE-----\nENCRYPTED MESSAGE\n-----END PGP MESSAGE-----"
        mock_pgp_service.encrypt_message_for_recipient.return_value = encrypted_blob_mock

        buyer_message = "Please ship discreetly."
        data = {'vendor_id': self.vendor_with_pgp.pk, 'buyer_message': buyer_message}

        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'encrypted_blob': encrypted_blob_mock})
        mock_pgp_service.encrypt_message_for_recipient.assert_called_once_with(
            recipient_public_key=VALID_PGP_KEY_UTIL_PLACEHOLDER,
            message=buyer_message,
            recipient_fingerprint=None
        )

    def test_encrypt_for_vendor_unauthenticated(self):
        data = {'vendor_id': self.vendor_with_pgp.pk, 'buyer_message': 'test'}
        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_encrypt_for_vendor_missing_data(self, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        data1 = {'buyer_message': 'test'}
        response1 = self.client.post(ENCRYPT_UTIL_URL, data1, format='json')
        self.assertEqual(response1.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('vendor_id', response1.data)

        data2 = {'vendor_id': self.vendor_with_pgp.pk}
        response2 = self.client.post(ENCRYPT_UTIL_URL, data2, format='json')
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provide either 'shipping_data', 'buyer_message', or 'pre_encrypted_blob'", str(response2.data))

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_encrypt_for_vendor_no_pgp_key(self, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        data = {'vendor_id': self.vendor_no_pgp.pk, 'buyer_message': 'This will fail'}
        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('has no pgp key', str(response.data).lower())

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.utility.pgp_service')
    def test_encrypt_for_vendor_pgp_error(self, mock_pgp_service, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        mock_pgp_service.is_pgp_service_available.return_value = True
        mock_pgp_service.encrypt_message_for_recipient.side_effect = Exception("GPG Encryption Failed")

        data = {'vendor_id': self.vendor_with_pgp.pk, 'buyer_message': 'test'}
        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Failed to encrypt data', response.data.get('detail', ''))

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    @patch('backend.store.views.utility.pgp_service')
    def test_encrypt_for_vendor_pre_encrypted_blob(self, mock_pgp_service, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        pre_encrypted = "-----BEGIN PGP MESSAGE-----\nPRE-ENCRYPTED\n-----END PGP MESSAGE-----"
        data = {'vendor_id': self.vendor_with_pgp.pk, 'pre_encrypted_blob': pre_encrypted}
        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'encrypted_blob': pre_encrypted})
        mock_pgp_service.encrypt_message_for_recipient.assert_not_called()

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_encrypt_for_vendor_both_data_and_blob(self, mock_pgp_perm):
        self.client.login(username=self.regular_user.username, password=self.password)
        pre_encrypted = "-----BEGIN PGP MESSAGE-----\nPRE-ENCRYPTED\n-----END PGP MESSAGE-----"
        data = {
            'vendor__id': self.vendor_with_pgp.pk,
            'buyer_message': 'Some message',
            'pre_encrypted_blob': pre_encrypted
        }
        response = self.client.post(ENCRYPT_UTIL_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provide either structured data OR a pre_encrypted_blob, not both", str(response.data))

# --- END OF FILE ---