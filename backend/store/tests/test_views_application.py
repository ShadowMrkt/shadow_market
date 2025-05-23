# backend/store/tests/test_views_application.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/application.py.
# Changes:
#   - v1.1: Set pgp_public_key to None for test user creation in setUpTestData
#           to comply with stricter PGP validation in models.py (v1.4.2+).
#           PGP authentication is globally mocked for these view tests.

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import User, VendorApplication, GlobalSettings, Currency # User already get_user_model

# --- Constants ---
User = get_user_model() # Consistent User retrieval
VENDOR_APP_CREATE_URL = reverse('store:vendor-application-create')
VENDOR_APP_STATUS_URL = reverse('store:vendor-application-status')

# Set to None as PGP auth is mocked and models.py now strictly validates provided keys.
# Users will be created without a PGP key for these view tests.
VALID_PGP_KEY_APP = None

# --- Test Cases ---

# Mock services used by the views
@patch('backend.store.views.application.exchange_rate_service')
@patch('backend.store.views.application.bitcoin_service')
@patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True) # Mock PGP auth globally
@patch('backend.store.views.application.log_audit_event', MagicMock())
class VendorApplicationViewTests(APITestCase):
    """Tests for VendorApplicationCreateView and VendorApplicationStatusView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'

        # Create users
        cls.applicant_user = User.objects.create_user(
            username='app_applicant', password=cls.password,
            pgp_public_key=VALID_PGP_KEY_APP # Will be None
        )
        cls.existing_vendor = User.objects.create_user(
            username='app_existing_vendor', password=cls.password, is_vendor=True,
            pgp_public_key=VALID_PGP_KEY_APP # Will be None
        )
        cls.staff_user = User.objects.create_user(
            username='app_staff', password=cls.password, is_staff=True,
            pgp_public_key=VALID_PGP_KEY_APP # Will be None
        )
        cls.user_with_pending_app = User.objects.create_user(
            username='app_pending_user', password=cls.password,
            pgp_public_key=VALID_PGP_KEY_APP # Will be None
        )
        cls.user_with_rejected_app = User.objects.create_user(
            username='app_rejected_user', password=cls.password,
            pgp_public_key=VALID_PGP_KEY_APP # Will be None
        )

        # Setup GlobalSettings
        gs = GlobalSettings.get_solo()
        gs.default_vendor_bond_usd = Decimal('150.00')
        # Add dummy rate needed for calculation (ensure service mock returns it too)
        gs.btc_usd_rate = Decimal('50000.00')
        gs.save()

        # Create existing applications for testing duplicates/status retrieval
        cls.pending_app = VendorApplication.objects.create(
            user=cls.user_with_pending_app,
            status=VendorApplication.StatusChoices.PENDING_REVIEW, # Example status
            bond_currency=Currency.BTC.value, # Use .value for choices
            bond_amount_usd=gs.default_vendor_bond_usd,
            bond_amount_crypto=Decimal('0.003'), # Example calculated value
            bond_payment_address='existing_pending_address'
        )
        cls.rejected_app = VendorApplication.objects.create(
            user=cls.user_with_rejected_app,
            status=VendorApplication.StatusChoices.REJECTED,
            bond_currency=Currency.BTC.value, # Use .value for choices
            bond_amount_usd=gs.default_vendor_bond_usd,
            bond_amount_crypto=Decimal('0.003'),
            rejection_reason="Test rejection"
        )


    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        # Log in applicant_user by default
        self.client.login(username=self.applicant_user.username, password=self.password)


    # === VendorApplicationCreateView Tests ===

    def test_create_app_success(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log): # Renamed mock_audit
        """Verify successful vendor application creation."""
        # Mock service calls
        mock_exchange_service.convert_usd_to_crypto.return_value = Decimal('0.003') # Mock BTC amount
        mock_generated_address = "bc1qgeneratedaddress"
        mock_btc_service.get_new_vendor_bond_deposit_address.return_value = mock_generated_address
        mock_btc_service.import_btc_address_to_node.return_value = True

        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json') # No data needed if currency is fixed

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Check response data
        self.assertEqual(response.data['status'], VendorApplication.StatusChoices.PENDING_BOND.value)
        self.assertEqual(response.data['user']['username'], self.applicant_user.username)
        self.assertEqual(response.data['bond_currency'], Currency.BTC.value)
        self.assertEqual(response.data['bond_amount_usd'], "150.00") # Matches setting
        self.assertEqual(response.data['bond_amount_crypto'], "0.00300000") # Matches mock, formatted
        self.assertEqual(response.data['bond_payment_address'], mock_generated_address)

        # Check DB object
        app = VendorApplication.objects.get(user=self.applicant_user)
        self.assertEqual(app.status, VendorApplication.StatusChoices.PENDING_BOND)
        self.assertEqual(app.bond_payment_address, mock_generated_address)
        self.assertEqual(app.bond_amount_crypto, Decimal('0.003'))

        # Check mocks called
        mock_pgp_perm.assert_called_once()
        mock_exchange_service.convert_usd_to_crypto.assert_called_once_with(Decimal('150.00'), Currency.BTC.value)
        mock_btc_service.get_new_vendor_bond_deposit_address.assert_called_once_with(app.id)
        mock_btc_service.import_btc_address_to_node.assert_called_once_with(address=mock_generated_address, label=f"VendorAppBond_{app.id}")
        mock_audit_log.assert_called_once()


    def test_create_app_unauthenticated(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify unauthenticated user cannot create application."""
        self.client.logout()
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
        mock_audit_log.assert_not_called()

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=False) # Override global mock
    def test_create_app_no_pgp_auth(self, mock_pgp_perm_specific, mock_pgp_perm_global, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if user's PGP session is not authenticated."""
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_pgp_perm_specific.assert_called_once() # Check specific mock was used
        mock_exchange_service.convert_usd_to_crypto.assert_not_called()
        mock_audit_log.assert_not_called()

    def test_create_app_already_vendor(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if user is already a vendor."""
        self.client.login(username=self.existing_vendor.username, password=self.password)
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already an approved vendor", response.data['detail'])
        mock_audit_log.assert_not_called()

    def test_create_app_existing_application(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if user already has a pending/active application."""
        self.client.login(username=self.user_with_pending_app.username, password=self.password)
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already have a vendor application", response.data['detail'])
        # Check that the existing application data is included in the response
        self.assertIn("existing_application", response.data)
        self.assertEqual(response.data["existing_application"]["id"], str(self.pending_app.id))
        mock_audit_log.assert_not_called()

    def test_create_app_exchange_rate_fail(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if exchange rate conversion fails."""
        mock_exchange_service.convert_usd_to_crypto.return_value = None # Simulate failure
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("Could not calculate bond amount", response.data['detail'])
        mock_audit_log.assert_not_called()

    def test_create_app_address_gen_fail(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if BTC address generation fails."""
        mock_exchange_service.convert_usd_to_crypto.return_value = Decimal('0.003')
        mock_btc_service.get_new_vendor_bond_deposit_address.return_value = None # Simulate failure
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to generate or register payment address", response.data['detail'])
        mock_audit_log.assert_not_called() # Should not log audit if application object creation failed before saving

    def test_create_app_address_import_fail(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify failure if importing BTC address to node fails."""
        mock_exchange_service.convert_usd_to_crypto.return_value = Decimal('0.003')
        mock_generated_address = "bc1qgeneratedaddress"
        mock_btc_service.get_new_vendor_bond_deposit_address.return_value = mock_generated_address
        mock_btc_service.import_btc_address_to_node.return_value = False # Simulate failure
        
        # Ensure an application object would be created to get an ID for the label
        # This means we expect get_new_vendor_bond_deposit_address to be called
        # before the import_btc_address_to_node failure causes a rollback or deletion.
        
        response = self.client.post(VENDOR_APP_CREATE_URL, {}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to register payment address with node", response.data['detail'])
        # Audit log might or might not be called depending on exact failure point and transaction handling in view
        # For consistency, if the app isn't fully finalized, it's safer to assert_not_called or check conditions.
        # Given the 500 error, it's likely the transaction for app creation was rolled back.
        mock_audit_log.assert_not_called() 


    # === VendorApplicationStatusView Tests ===

    def test_get_status_success_pending(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify user with pending app can retrieve its status."""
        self.client.login(username=self.user_with_pending_app.username, password=self.password)
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.pending_app.id))
        self.assertEqual(response.data['status'], self.pending_app.status)
        self.assertEqual(response.data['bond_payment_address'], self.pending_app.bond_payment_address) # Address shown if pending bond

    def test_get_status_success_rejected(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify user with only a rejected app retrieves its status."""
        self.client.login(username=self.user_with_rejected_app.username, password=self.password)
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.rejected_app.id))
        self.assertEqual(response.data['status'], self.rejected_app.status)
        self.assertEqual(response.data['rejection_reason'], self.rejected_app.rejection_reason)
        self.assertNotIn('bond_payment_address', response.data) # Address not shown if rejected

    def test_get_status_success_none_found(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify 404 if user has no applications."""
        # Using applicant_user who has no apps created in setUpTestData
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_status_unauthenticated(self, mock_pgp_perm, mock_btc_service, mock_exchange_service, mock_audit_log):
        """Verify unauthenticated user cannot get application status."""
        self.client.logout()
        response = self.client.get(VENDOR_APP_STATUS_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

# --- END OF FILE ---