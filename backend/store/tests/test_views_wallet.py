# backend/store/tests/test_views_wallet.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the API views in views/wallet.py.
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for test user creations in setUpTestData
#     to comply with stricter PGP validation in models.py (v1.4.2+).
#   - Ensured .value is used for Enum fields (Currency, WithdrawalStatusChoices)
#     when assigning to mock objects or comparing with response data.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the API views in views/wallet.py.

# Standard Library Imports
from unittest.mock import patch, MagicMock
from decimal import Decimal
import uuid # Added for potential UUIDs in mock IDs

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.models import Currency # Assuming Currency enum is here
# Import models needed for setup
from backend.ledger.models import UserBalance
from backend.withdraw.models import WithdrawalRequest, WithdrawalStatusChoices
# Import exceptions raised by services/views
from backend.ledger.exceptions import InsufficientFundsError # Corrected from services
from backend.withdraw.exceptions import WithdrawalError # Check actual exception source
# Import permissions if mocking them directly
# from backend.store.permissions import IsPgpAuthenticated

# --- Constants ---
User = get_user_model()
WALLET_BALANCES_URL = reverse('store:wallet-balances')
WITHDRAWAL_PREPARE_URL = reverse('store:withdrawal-prepare')

# --- Test Cases ---

class WalletViewTests(APITestCase):
    """Tests for WalletBalanceView and WithdrawalPrepareView."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        # Create users
        cls.password = 'strongpassword123'
        cls.user1 = User.objects.create_user(
            username='testuser1',
            password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.user2 = User.objects.create_user(
            username='testuser2',
            password=cls.password,
            pgp_public_key=None # Set to None
        )

        # Create initial balances for user1
        cls.user1_btc_balance = UserBalance.objects.create(
            user=cls.user1, currency=Currency.BTC.value, # Use .value
            balance=Decimal('1.500000000000'), locked_balance=Decimal('0.200000000000')
        ) # Available = 1.3
        cls.user1_xmr_balance = UserBalance.objects.create(
            user=cls.user1, currency=Currency.XMR.value, # Use .value
            balance=Decimal('10.000000000000'), locked_balance=Decimal('1.000000000000')
        ) # Available = 9.0

        # No ETH balance for user1 initially

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.client.login(username=self.user1.username, password=self.password)

    # === WalletBalanceView Tests ===

    def test_get_balances_authenticated_user(self):
        """Verify authenticated user can retrieve their balances."""
        response = self.client.get(WALLET_BALANCES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), len(Currency.choices))

        balances = {item['currency']: item for item in response.data}

        self.assertIn(Currency.BTC.value, balances)
        self.assertEqual(balances[Currency.BTC.value]['balance'], '1.500000000000')
        self.assertEqual(balances[Currency.BTC.value]['locked_balance'], '0.200000000000')
        self.assertEqual(balances[Currency.BTC.value]['available_balance'], '1.300000000000')

        self.assertIn(Currency.XMR.value, balances)
        self.assertEqual(balances[Currency.XMR.value]['balance'], '10.000000000000')
        self.assertEqual(balances[Currency.XMR.value]['locked_balance'], '1.000000000000')
        self.assertEqual(balances[Currency.XMR.value]['available_balance'], '9.000000000000')

        self.assertIn(Currency.ETH.value, balances)
        self.assertEqual(balances[Currency.ETH.value]['balance'], '0.000000000000') # Assuming 12 decimal places default
        self.assertEqual(balances[Currency.ETH.value]['locked_balance'], '0.000000000000')
        self.assertEqual(balances[Currency.ETH.value]['available_balance'], '0.000000000000')

    def test_get_balances_unauthenticated(self):
        self.client.logout()
        response = self.client.get(WALLET_BALANCES_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # === WithdrawalPrepareView Tests ===
    patch_pgp_authenticated = patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    patch_request_withdrawal = patch('backend.withdraw.services.request_withdrawal') # Path to the service function

    @patch_pgp_authenticated
    @patch_request_withdrawal
    def test_withdraw_prepare_success(self, mock_request_withdrawal, mock_has_permission):
        mock_withdrawal = MagicMock(spec=WithdrawalRequest)
        mock_withdrawal.id = uuid.uuid4() # Use UUID if model field is UUIDField
        mock_withdrawal.user = self.user1
        mock_withdrawal.currency = Currency.BTC.value # Store the string value
        mock_withdrawal.requested_amount = Decimal('0.5')
        mock_withdrawal.status = WithdrawalStatusChoices.COMPLETED.value # Store the string value
        # For display methods, they would return the label
        mock_withdrawal.get_currency_display.return_value = Currency.BTC.label
        mock_withdrawal.get_status_display.return_value = WithdrawalStatusChoices.COMPLETED.label
        mock_request_withdrawal.return_value = mock_withdrawal

        withdrawal_data = {
            'currency': Currency.BTC.value,
            'amount': '0.5',
            'address': 'bc1qtestaddressvalidformat',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_has_permission.assert_called_once()
        mock_request_withdrawal.assert_called_once_with(
            user=self.user1,
            currency=Currency.BTC.value,
            amount_standard=Decimal('0.5'),
            withdrawal_address='bc1qtestaddressvalidformat'
        )
        self.assertIn('id', response.data)
        self.assertEqual(response.data['id'], str(mock_withdrawal.id)) # Compare string UUID
        self.assertEqual(response.data['currency'], mock_withdrawal.currency) # Should be 'BTC'
        self.assertEqual(response.data['status'], mock_withdrawal.status) # Should be 'completed'

    def test_withdraw_prepare_unauthenticated(self):
        self.client.logout()
        withdrawal_data = {
            'currency': Currency.BTC.value, 'amount': '0.1', 'address': 'bc1q...',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=False)
    def test_withdraw_prepare_no_pgp_auth(self, mock_has_permission):
        withdrawal_data = {
            'currency': Currency.BTC.value, 'amount': '0.1', 'address': 'bc1q...',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_has_permission.assert_called_once()

    @patch_pgp_authenticated
    @patch_request_withdrawal
    def test_withdraw_prepare_insufficient_funds(self, mock_request_withdrawal, mock_has_permission):
        mock_request_withdrawal.side_effect = InsufficientFundsError("Not enough BTC available.")
        withdrawal_data = {
            'currency': Currency.BTC.value,
            'amount': '2.0',
            'address': 'bc1qinsufficientfunds',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_request_withdrawal.assert_called_once()
        self.assertIn('detail', response.data)
        self.assertIn("Not enough BTC available.", response.data['detail'])

    @patch_pgp_authenticated
    @patch_request_withdrawal
    def test_withdraw_prepare_invalid_amount(self, mock_request_withdrawal, mock_has_permission):
        withdrawal_data = {
            'currency': Currency.BTC.value,
            'amount': '-0.5',
            'address': 'bc1qinvalidamount',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)
        mock_request_withdrawal.assert_not_called()

    @patch_pgp_authenticated
    @patch_request_withdrawal
    def test_withdraw_prepare_invalid_address(self, mock_request_withdrawal, mock_has_permission):
        withdrawal_data = {
            'currency': Currency.BTC.value,
            'amount': '0.1',
            'address': 'invalid-btc-address',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('address', response.data)
        mock_request_withdrawal.assert_not_called()

    @patch_pgp_authenticated
    @patch_request_withdrawal
    def test_withdraw_prepare_service_error(self, mock_request_withdrawal, mock_has_permission):
        mock_request_withdrawal.side_effect = WithdrawalError("Unexpected service failure") # Use specific error type if possible
        withdrawal_data = {
            'currency': Currency.XMR.value,
            'amount': '1.0',
            'address': '4AddressXMRServiceErrorVeryLongAndValidLookingButWillFail',
        }
        response = self.client.post(WITHDRAWAL_PREPARE_URL, withdrawal_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST) # Assuming WithdrawalError maps to 400
        mock_request_withdrawal.assert_called_once()
        self.assertIn('detail', response.data)
        self.assertIn("Unexpected service failure", response.data['detail'])

# --- END OF FILE ---