# backend/store/tests/test_views_application.py
# Revision: 1.2
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/application.py.
# Changes:
#   - v1.2:
#     - Corrected test method signatures to properly accept mock arguments injected by
#       class-level decorators in the correct order. Renamed mock parameters for clarity.
#       This resolves TypeError for missing 'mock_audit_log'.
#   - v1.1: Set pgp_public_key to None for test user creation in setUpTestData
#           to comply with stricter PGP validation in models.py (v1.4.2+).
#           PGP authentication is globally mocked for these view tests.

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
# from django.conf import settings # Not directly used

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import VendorApplication, GlobalSettings, Currency

# --- Constants ---
User = get_user_model() # Consistent User retrieval
VENDOR_APP_CREATE_URL = reverse('store:vendor-application-create')
VENDOR_APP_STATUS_URL = reverse('store:vendor-application-status')

VALID_PGP_KEY_APP = None

# --- Test Cases ---

@patch('backend.store.views.application.exchange_rate_service')         # Will be mock_exchange_service_arg
@patch('backend.store.views.application.bitcoin_service')             # Will be mock_bitcoin_service_arg
@patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True) # Will be mock_is_pgp_authenticated_arg
@patch('backend.store.views.application.log_audit_event', MagicMock()) # Will be mock_log_audit_event_arg
class VendorApplicationViewTests(APITestCase):
    """Tests for VendorApplicationCreateView and VendorApplicationStatusView."""

    @classmethod
    def setUpTestData(cls):
        cls.password = 'strongpassword123'
        cls.applicant_user = User.objects.create_user(
            username='app_applicant', password=cls.password, pgp_public_key=VALID_PGP_KEY_APP
        )
        cls.existing_vendor = User.objects.create_user(
            username='app_existing_vendor', password=cls.password, is_vendor=True, pgp_public_key=VALID_PGP_KEY_APP
        )
        # cls.staff_user = User.objects.create_user( # Not used in current tests, can be omitted or kept
        #     username='app_staff', password=cls.password, is_staff=True, pgp_public_key=VALID_PGP_KEY_APP
        # )
        cls.user_with_pending_app = User.objects.create_user(
            username='app_pending_user', password=cls.password, pgp_public_key=VALID_PGP_KEY_APP
        )
        cls.user_with_rejected_app = User.objects.create_user(
            username='app_rejected_user', password=cls.password, pgp_public_key=VALID_PGP_KEY_APP
        )

        gs = GlobalSettings.get_solo()
        gs.default_vendor_bond_usd = Decimal('150.00')
        gs.btc_usd_rate = Decimal('50000.00')
        gs.save()

        cls.pending_app = VendorApplication.objects.create(
            user=cls.user_with_pending_app, status=VendorApplication.StatusChoices.PENDING_REVIEW.value,
            bond_currency=Currency.BTC.value, bond_amount_usd=gs.default_vendor_bond_usd,
            bond_amount_crypto=Decimal('0.003'), bond_payment_address='existing_pending_address'
        )
        cls.rejected_app = VendorApplication.objects.create(
            user=cls.user_with_rejected_app, status=VendorApplication.StatusChoices.REJECTED.value,
            bond_currency=Currency.BTC.value, bond_amount_usd=gs.default_vendor_bond_usd,
            bond_amount_crypto=Decimal('0.003'), rejection_reason="Test rejection"
        )

    def setUp(self):
        self.client = APIClient()
        self.client.login(username=self.applicant_user.username, password=self.password)

    def test_create_app_success(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        mock_exchange_rate_service_arg.convert_usd_to_crypto.return_value = Decimal('0.003')
        mock_generated_address = "bc1qgeneratedaddress"
        mock_bitcoin_service_arg.get_new_vendor_bond_deposit_address.return_value = mock_generated_address
        mock_bitcoin_service_arg.import_btc_address_to_node.return_value = True

        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], VendorApplication.StatusChoices.PENDING_BOND.value)
        self.assertEqual(response.data['user']['username'], self.applicant_user.username)
        self.assertEqual(response.data['bond_currency'], Currency.BTC.value)
        self.assertEqual(response.data['bond_amount_usd'], "150.00")
        self.assertEqual(response.data['bond_amount_crypto'], "0.00300000")
        self.assertEqual(response.data['bond_payment_address'], mock_generated_address)

        app = VendorApplication.objects.get(user=self.applicant_user)
        self.assertEqual(app.status, VendorApplication.StatusChoices.PENDING_BOND)
        self.assertEqual(app.bond_payment_address, mock_generated_address)
        self.assertEqual(app.bond_amount_crypto, Decimal('0.003'))

        mock_is_pgp_authenticated_arg.assert_called_once()
        mock_exchange_rate_service_arg.convert_usd_to_crypto.assert_called_once_with(Decimal('150.00'), Currency.BTC.value)
        mock_bitcoin_service_arg.get_new_vendor_bond_deposit_address.assert_called_once_with(app.id)
        mock_bitcoin_service_arg.import_btc_address_to_node.assert_called_once_with(address=mock_generated_address, label=f"VendorAppBond_{app.id}")
        mock_log_audit_event_arg.assert_called_once()

    def test_create_app_unauthenticated(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.logout()
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        mock_log_audit_event_arg.assert_not_called()

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=False)
    def test_create_app_no_pgp_auth(self, mock_pgp_perm_specific_arg, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg): # Outer mocks still passed
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_pgp_perm_specific_arg.assert_called_once()
        mock_exchange_rate_service_arg.convert_usd_to_crypto.assert_not_called()
        mock_log_audit_event_arg.assert_not_called()

    def test_create_app_already_vendor(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.login(username=self.existing_vendor.username, password=self.password)
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already an approved vendor", response.data['detail'])
        mock_log_audit_event_arg.assert_not_called()

    def test_create_app_existing_application(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.login(username=self.user_with_pending_app.username, password=self.password)
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already have a vendor application", response.data['detail'])
        self.assertIn("existing_application", response.data)
        self.assertEqual(response.data["existing_application"]["id"], str(self.pending_app.id))
        mock_log_audit_event_arg.assert_not_called()

    def test_create_app_exchange_rate_fail(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        mock_exchange_rate_service_arg.convert_usd_to_crypto.return_value = None
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("Could not calculate bond amount", response.data['detail'])
        mock_log_audit_event_arg.assert_not_called()

    def test_create_app_address_gen_fail(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        mock_exchange_rate_service_arg.convert_usd_to_crypto.return_value = Decimal('0.003')
        mock_bitcoin_service_arg.get_new_vendor_bond_deposit_address.return_value = None
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to generate or register payment address", response.data['detail'])
        mock_log_audit_event_arg.assert_not_called()

    def test_create_app_address_import_fail(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        mock_exchange_rate_service_arg.convert_usd_to_crypto.return_value = Decimal('0.003')
        mock_generated_address = "bc1qgeneratedaddress"
        mock_bitcoin_service_arg.get_new_vendor_bond_deposit_address.return_value = mock_generated_address
        mock_bitcoin_service_arg.import_btc_address_to_node.return_value = False
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to register payment address with node", response.data['detail'])
        mock_log_audit_event_arg.assert_not_called()

    # === VendorApplicationStatusView Tests ===
    def test_get_status_success_pending(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.login(username=self.user_with_pending_app.username, password=self.password)
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.pending_app.id))
        self.assertEqual(response.data['status'], self.pending_app.status)
        self.assertEqual(response.data['bond_payment_address'], self.pending_app.bond_payment_address)

    def test_get_status_success_rejected(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.login(username=self.user_with_rejected_app.username, password=self.password)
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.rejected_app.id))
        self.assertEqual(response.data['status'], self.rejected_app.status)
        self.assertEqual(response.data['rejection_reason'], self.rejected_app.rejection_reason)
        self.assertNotIn('bond_payment_address', response.data)

    def test_get_status_success_none_found(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        response = self.client.get(VENDOR_APP_STATUS_URL) # Uses self.applicant_user by default
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_status_unauthenticated(self, mock_log_audit_event_arg, mock_is_pgp_authenticated_arg, mock_bitcoin_service_arg, mock_exchange_rate_service_arg):
        self.client.logout()
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

# --- END OF FILE ---