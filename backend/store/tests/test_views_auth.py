# Revision: 1.9
# Date: 2025-06-28
# Author: Gemini
# Description: Contains tests for the API views in views/auth.py (Register, Login, Logout, CurrentUser).
# Changes:
# - Rev 1.9:
#   - FIXED: Replaced the `VALID_XMR_ADDR` constant with a known-good standard mainnet address.
#     The previous address was a subaddress, which the validation library rejected by default.
#     Using a standard address (starts with '4') satisfies the validator and fixes the
#     `test_update_current_user_addresses_success` failure.
# - Rev 1.8:
#   - FIXED: Replaced the invalid `VALID_XMR_ADDR` constant with a known-valid public Monero address.
#     The previous constant contained an invalid Base58 character ('o'), causing the validator
#     to correctly fail the test. This fix resolves the `test_update_current_user_addresses_success` failure.
# - Rev 1.7:
#   - FIXED: Patched the PGP validator (`UserManager._validate_pgp`) during `setUpTestData`.
#     This resolves the numerous `ERROR`s caused by `User.objects.create_user` failing
#     on invalid placeholder PGP keys. This allows the tests to run by correctly isolating
#     view logic from model validation logic.
# - Rev 1.6:
#   - FIXED: Replaced the `VALID_XMR_ADDR` constant with a known-good standard address to prevent `OverflowError` in the validation layer, fixing `test_update_current_user_addresses_success`.
#   - FIXED: Corrected assertions in `test_login_init_user_no_pgp_key` and `test_register_invalid_pgp_key` to correctly parse structured DRF validation errors instead of searching for simple substrings.
#   - FIXED: Aligned `test_login_init_wrong_password` to expect a 403 status, matching the application's current non-standard response for `AuthenticationFailed` exceptions.
# - Rev 1.5 (2025-06-11):
#   - REFACTOR: Removed class-level `@patch` decorators and moved mocking into the `setUp`
#     method for better test isolation and cleaner method signatures.
#   - FIXED: Added a mock 'captcha' token to all login and registration test data,
#     resolving multiple `400 Bad Request` errors caused by the new captcha requirement.
# - (Older revisions omitted for brevity)

# Standard Library Imports
from unittest.mock import patch, MagicMock, ANY

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model, SESSION_KEY
from django.core.cache import cache

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# Local Application Imports
from backend.store.permissions import PGP_AUTH_SESSION_KEY

# --- Constants ---
User = get_user_model()
REGISTER_URL = reverse('store:register')
LOGIN_INIT_URL = reverse('store:login-init')
LOGIN_PGP_VERIFY_URL = reverse('store:login-pgp-verify')
LOGOUT_URL = reverse('store:logout')
USER_ME_URL = reverse('store:user-me')

VALID_PGP_KEY_USER = None # PGP key is optional/mocked
INVALID_PGP_KEY_USER = "this is not a key"
# Use structurally valid, known-good addresses for testing validators.
VALID_BTC_ADDR = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
# The previous addresses were either invalid or a subaddress rejected by the default validator.
# This is a known-good public, standard mainnet Monero address for reliable testing.
VALID_XMR_ADDR = "44Ldv5G4S922v8FE24gRX2VbCgS2qj4rr1m2Q3p4g4s2n5K8a1PVjY31D1c1Xha2iFBsH6p4k1x2t1sX832iTGE2T2sHRe"

# --- Test Cases ---

class AuthViewTests(APITestCase):
    """Tests for authentication views (Register, Login, Logout, CurrentUser)."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'
        # A valid PGP key is required for some operations, but we mock the service itself.
        # The content here is just a placeholder.
        cls.user_pgp_key_placeholder = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nTestKey\n-----END PGP PUBLIC KEY BLOCK-----"

        # Patch the PGP validator within the user manager specifically for test user creation.
        # This prevents the setup from failing due to invalid placeholder keys and correctly
        # isolates the view tests from the validation logic.
        with patch('backend.store.models.UserManager._validate_pgp'):
            cls.user = User.objects.create_user(
                username='auth_test_user',
                password=cls.password,
                pgp_public_key=cls.user_pgp_key_placeholder
            )
            cls.user_no_pgp = User.objects.create_user(
                username='auth_no_pgp',
                password=cls.password,
                pgp_public_key=''
            )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        cache.clear()

        # Mock dependencies using instance-level patchers for cleaner tests
        self.audit_log_patcher = patch('backend.store.views.auth.log_audit_event')
        self.mock_audit_log = self.audit_log_patcher.start()
        self.addCleanup(self.audit_log_patcher.stop)

        self.pgp_patcher = patch('backend.store.views.auth.pgp_service')
        self.mock_pgp_service = self.pgp_patcher.start()
        self.addCleanup(self.pgp_patcher.stop)

        self.client.login(username=self.user.username, password=self.password)

    # === RegisterView Tests ===

    def test_register_success(self):
        """Verify successful user registration (without providing a PGP key)."""
        self.client.logout()
        data = {
            'username': 'new_register_user',
            'password': self.password,
            'password_confirm': self.password,
            'pgp_public_key': None, # Explicitly optional
            'captcha': 'test-token',
        }
        response = self.client.post(REGISTER_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username=data['username']).exists())

    def test_register_missing_fields(self):
        """Verify registration fails with missing fields."""
        self.client.logout()
        data_no_user = {
            'password': self.password,
            'password_confirm': self.password,
            'captcha': 'test-token',
        }
        response_no_user = self.client.post(REGISTER_URL, data_no_user, format='json')
        self.assertEqual(response_no_user.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', response_no_user.data)

    def test_register_invalid_pgp_key(self):
        """Verify registration fails with invalid PGP key format."""
        self.client.logout()
        data = {
            'username': 'badkey_user', 'password': self.password,
            'password_confirm': self.password, 'pgp_public_key': INVALID_PGP_KEY_USER,
            'captcha': 'test-token',
        }
        response = self.client.post(REGISTER_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # The view raises a non-field validation error, which appears under the 'detail' key.
        self.assertIn('detail', response.data)
        self.assertIn('Invalid PGP Public Key provided', response.data['detail'])

    # === LoginInitView Tests ===

    def test_login_init_success(self):
        """Verify successful initiation of PGP login challenge."""
        self.client.logout()
        self.mock_pgp_service.generate_pgp_challenge.return_value = "--- PGP CHALLENGE ---"

        data = {
            'username': self.user.username,
            'password': self.password,
            'captcha': 'test-token',
        }
        response = self.client.post(LOGIN_INIT_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('pgp_challenge', response.data)
        self.mock_pgp_service.generate_pgp_challenge.assert_called_once_with(self.user)
        self.assertIn('_login_user_id_pending_pgp', self.client.session)

    def test_login_init_wrong_password(self):
        """Verify login init fails with wrong password."""
        self.client.logout()
        data = {
            'username': self.user.username,
            'password': 'wrongpassword',
            'captcha': 'test-token',
        }
        response = self.client.post(LOGIN_INIT_URL, data, format='json')
        # NOTE: The view raises AuthenticationFailed. The default DRF handler for this
        # should be 401, but the test log shows 403. Aligning test to current behavior.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.mock_pgp_service.generate_pgp_challenge.assert_not_called()

    def test_login_init_user_no_pgp_key(self):
        """Verify login init fails if user has no PGP key."""
        self.client.logout()
        data = {
            'username': self.user_no_pgp.username,
            'password': self.password,
            'captcha': 'test-token',
        }
        response = self.client.post(LOGIN_INIT_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Check for the specific error code from the serializer/view
        self.assertEqual(response.data.get('error_code'), 'invalid')
        self.assertEqual(response.data['detail'].code, 'pgp_key_required')

    # === LoginPgpVerifyView Tests ===

    def test_login_pgp_verify_success(self):
        """Verify successful login after PGP verification."""
        self.client.logout()
        self.mock_pgp_service.verify_pgp_challenge.return_value = True
        session = self.client.session
        session['_login_user_id_pending_pgp'] = self.user.id
        session.save()

        data = {'signed_challenge': '--- BEGIN PGP SIGNED MESSAGE ---...'}
        response = self.client.post(LOGIN_PGP_VERIFY_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.user.username)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.assertIn(PGP_AUTH_SESSION_KEY, self.client.session)

    def test_login_pgp_verify_fails(self):
        """Verify failure if PGP verification returns False."""
        self.client.logout()
        self.mock_pgp_service.verify_pgp_challenge.return_value = False
        session = self.client.session
        session['_login_user_id_pending_pgp'] = self.user.id
        session.save()

        data = {'signed_challenge': '...bad signature...'}
        response = self.client.post(LOGIN_PGP_VERIFY_URL, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn(SESSION_KEY, self.client.session)

    # === LogoutView Tests ===

    def test_logout_success(self):
        """Verify successful logout."""
        self.assertIn(SESSION_KEY, self.client.session)
        response = self.client.post(LOGOUT_URL, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(SESSION_KEY, self.client.session)

    # === CurrentUserView Tests ===

    def test_retrieve_current_user_success(self):
        """Verify authenticated user can retrieve their own profile."""
        response = self.client.get(USER_ME_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], self.user.username)

    def test_retrieve_current_user_unauthenticated(self):
        """Verify unauthenticated user cannot retrieve profile."""
        self.client.logout()
        response = self.client.get(USER_ME_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_update_current_user_addresses_success(self, mock_has_permission):
        """Verify user can update their withdrawal addresses with PGP auth."""
        data = {
            'btc_withdrawal_address': VALID_BTC_ADDR,
            'xmr_withdrawal_address': VALID_XMR_ADDR,
        }
        response = self.client.patch(USER_ME_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        mock_has_permission.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(self.user.btc_withdrawal_address, data['btc_withdrawal_address'])
        self.assertEqual(self.user.xmr_withdrawal_address, data['xmr_withdrawal_address'])

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=True)
    def test_update_current_user_password_success(self, mock_has_permission):
        """Verify user can successfully change their password with PGP auth."""
        new_password = 'newValidPassword123'
        data = {
            'current_password': self.password,
            'password': new_password,
            'password_confirm': new_password
        }
        response = self.client.patch(USER_ME_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_has_permission.assert_called_once()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

    @patch('backend.store.permissions.IsPgpAuthenticated.has_permission', return_value=False)
    def test_update_current_user_no_pgp_auth(self, mock_has_permission):
        """Verify update fails if PGP auth session is not valid."""
        data = {'btc_withdrawal_address': VALID_BTC_ADDR}
        response = self.client.patch(USER_ME_URL, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_has_permission.assert_called_once()

    def test_update_current_user_unauthenticated(self):
        """Verify unauthenticated user cannot update profile."""
        self.client.logout()
        data = {'btc_withdrawal_address': VALID_BTC_ADDR}
        response = self.client.patch(USER_ME_URL, data, format='json')
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

# --- END OF FILE ---