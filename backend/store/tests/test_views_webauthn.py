# Revision: 1.5
# Date: 2025-06-17
# Author: Gemini
# Description: Contains tests for the WebAuthn API views in views/webauthn.py.
# Changes:
# - Rev 1.5:
#   - FIXED: Overhauled the entire test suite to align with the service-oriented
#     architecture in `views/webauthn.py` (Rev 2.1).
#   - FIXED: All `@patch` calls now correctly target `webauthn_service` methods instead
#     of outdated, direct library imports. This resolves all `AttributeError` failures.
#   - FIXED: Added missing imports for `json` and `WebAuthnException`, resolving all `NameError` failures.
#   - FIXED: Corrected mock return values for `encode_base64url` and mock verification
#     results to provide simple strings/integers, resolving the `ValueError` during `objects.create()`.
#   - REFACTOR: Simplified and clarified mock setups across all tests.
# - Rev 1.4 (2025-06-11, Gemini):
#   - FIXED: Corrected brittle assertion in `test_list_credentials_success`.
#   - FIXED: Updated assertion in `test_verify_reg_no_challenge_in_session`.
# - Rev 1.3 (2025-06-08, Gemini):
#   - FIXED: Corrected all `@patch` decorator paths targeting `webauthn_service`.
# - Rev 1.2 (2025-06-08, Gemini):
#   - FIXED: Corrected all `@patch` decorators for webauthn functions.
# - Rev 1.1 (2025-06-08, Gemini):
#   - Set pgp_public_key to None for test user creations.
# - Rev 1.0 (2025-04-29, Gemini):
#   - Initial creation with WebAuthnRegistrationOptionsView.

# Standard Library Imports
import uuid
from unittest.mock import patch, MagicMock, ANY
import base64
import secrets
import json

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# WebAuthn library helpers
try:
    from webauthn.helpers.exceptions import InvalidRegistrationResponse, InvalidAuthenticationResponse, WebAuthnException
except ImportError:
    # Define dummy exceptions if webauthn is not installed in the test environment
    class WebAuthnException(Exception): pass
    class InvalidRegistrationResponse(WebAuthnException): pass
    class InvalidAuthenticationResponse(WebAuthnException): pass

# Local Application Imports
from backend.store.models import WebAuthnCredential
from backend.store.models import User as StoreUser

# --- Constants ---
User = get_user_model()

WEBAUTHN_REG_OPTIONS_URL = reverse('store:webauthn-register-options')
WEBAUTHN_REG_VERIFY_URL = reverse('store:webauthn-register-verify')
WEBAUTHN_AUTH_OPTIONS_URL = reverse('store:webauthn-authenticate-options')
WEBAUTHN_AUTH_VERIFY_URL = reverse('store:webauthn-authenticate-verify')
WEBAUTHN_CRED_LIST_URL = reverse('store:webauthn-credential-list')
WEBAUTHN_CRED_DETAIL_URL_NAME = 'store:webauthn-credential-detail'

# Helper for base64url encoding
def base64url_encode(data_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(data_bytes).rstrip(b'=').decode('utf-8')

def base64url_decode(data_str: str) -> bytes:
    padding = b'=' * (4 - (len(data_str) % 4))
    return base64.urlsafe_b64decode(data_str.encode('utf-8') + padding)


# --- Test Cases ---
@patch('backend.store.views.webauthn.webauthn_service')
class WebAuthnViewTests(APITestCase):
    """Tests for WebAuthn views."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'
        cls.user = User.objects.create_user(
            username='webauthn_user',
            password=cls.password,
            pgp_public_key=None
        )
        cls.user_no_creds = User.objects.create_user(
            username='webauthn_user_no_creds',
            password=cls.password,
            pgp_public_key=None
        )

        cls.credential_id_bytes = secrets.token_bytes(16)
        cls.public_key_bytes = secrets.token_bytes(65)
        cls.credential_id_b64 = base64url_encode(cls.credential_id_bytes)
        cls.public_key_b64 = base64url_encode(cls.public_key_bytes)

        cls.existing_credential = WebAuthnCredential.objects.create(
            user=cls.user,
            credential_id_b64=cls.credential_id_b64,
            public_key_b64=cls.public_key_b64,
            sign_count=10,
            nickname="Test Key"
        )
        cls.other_user = User.objects.create_user(
            username='webauthn_other_user', password=cls.password, pgp_public_key=None
        )

    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.client.login(username=self.user.username, password=self.password)
        self.audit_log_patcher = patch('backend.store.utils.utils.log_audit_event')
        self.mock_audit_log = self.audit_log_patcher.start()
        self.addCleanup(self.audit_log_patcher.stop)


    # === Registration Options Tests ===

    def test_get_reg_options_success(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        challenge_bytes = secrets.token_bytes(32)
        mock_options = MagicMock(challenge=challenge_bytes)
        mock_webauthn_service.generate_registration_options.return_value = mock_options
        # Mock the service methods that will be called by the view
        mock_webauthn_service.encode_base64url.return_value = base64url_encode(challenge_bytes)
        mock_webauthn_service.decode_base64url.return_value = challenge_bytes
        mock_webauthn_service.options_to_json.return_value = json.dumps({"challenge": "test_challenge"})

        response = self.client.post(WEBAUTHN_REG_OPTIONS_URL, {})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_webauthn_service.generate_registration_options.assert_called_once()
        args, kwargs = mock_webauthn_service.generate_registration_options.call_args
        self.assertEqual(kwargs.get('user'), self.user)
        self.assertTrue(any(desc.id == self.credential_id_bytes for desc in kwargs.get('exclude_credentials', [])))

        session = self.client.session
        self.assertIn('webauthn_registration_challenge', session)
        self.assertEqual(session['webauthn_registration_user_pk'], str(self.user.pk))
        self.assertEqual(base64url_decode(session['webauthn_registration_challenge']), challenge_bytes)

    def test_get_reg_options_unauthenticated(self, mock_webauthn_service):
        self.client.logout()
        response = self.client.post(WEBAUTHN_REG_OPTIONS_URL, {})
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # === Registration Verification Tests ===

    def test_verify_reg_success(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        challenge_bytes = secrets.token_bytes(32)
        session = self.client.session
        session['webauthn_registration_challenge'] = base64url_encode(challenge_bytes)
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()

        mock_webauthn_service.decode_base64url.return_value = challenge_bytes
        mock_webauthn_service.parse_registration_credential.return_value = MagicMock()

        new_cred_id_bytes = secrets.token_bytes(16)
        mock_verify_result = MagicMock()
        mock_verify_result.credential_id = new_cred_id_bytes
        mock_verify_result.credential_public_key = secrets.token_bytes(65)
        mock_verify_result.sign_count = 0 # Must be a concrete value
        mock_webauthn_service.verify_registration_response.return_value = mock_verify_result
        mock_webauthn_service.encode_base64url.side_effect = lambda data: base64url_encode(data)

        verification_data = {"id": "new_id", "response": {}, "nickname": "My New Key"}
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {"verified": True})
        mock_webauthn_service.verify_registration_response.assert_called_once()
        self.assertTrue(WebAuthnCredential.objects.filter(user=self.user, credential_id_b64=base64url_encode(new_cred_id_bytes)).exists())

    def test_verify_reg_no_challenge_in_session(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        verification_data = {"id": "any_id", "response": {}}
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Challenge expired or missing", str(response.data))

    def test_verify_reg_verification_fails(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        session = self.client.session
        session['webauthn_registration_challenge'] = base64url_encode(secrets.token_bytes(32))
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()
        mock_webauthn_service.verify_registration_response.side_effect = WebAuthnException("Signature mismatch")

        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, {"id": "a", "response": {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Authenticator registration failed", str(response.data))

    def test_verify_reg_credential_already_exists(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        session = self.client.session
        session['webauthn_registration_challenge'] = base64url_encode(secrets.token_bytes(32))
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()

        # Mock the verification result with concrete values to avoid F() expression errors
        mock_verify_result = MagicMock()
        mock_verify_result.credential_id = self.credential_id_bytes # Use existing ID
        mock_verify_result.credential_public_key = self.public_key_bytes
        mock_verify_result.sign_count = 1
        mock_webauthn_service.verify_registration_response.return_value = mock_verify_result
        mock_webauthn_service.encode_base64url.return_value = self.credential_id_b64

        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, {"id": "a", "response": {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("This authenticator has already been registered", str(response.data))

    # === Authentication Options Tests ===

    def test_get_auth_options_success(self, mock_webauthn_service):
        self.client.logout()
        mock_webauthn_service.is_enabled.return_value = True
        mock_options = MagicMock(challenge=secrets.token_bytes(32))
        mock_webauthn_service.generate_authentication_options.return_value = mock_options
        mock_webauthn_service.options_to_json.return_value = json.dumps({"challenge": "test"})
        
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, {'username': self.user.username}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_webauthn_service.generate_authentication_options.assert_called_once()
        self.assertIn('webauthn_authentication_challenge', self.client.session)

    def test_get_auth_options_user_not_found(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        self.client.logout()
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, {'username': 'nonexistentuser'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_auth_options_user_no_credentials(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        self.client.logout()
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, {'username': self.user_no_creds.username}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # === Authentication Verification Tests ===

    @patch('django.contrib.auth.login')
    def test_verify_auth_success(self, mock_login, mock_webauthn_service):
        self.client.logout()
        mock_webauthn_service.is_enabled.return_value = True
        session = self.client.session
        session['webauthn_authentication_challenge'] = base64url_encode(secrets.token_bytes(32))
        session['webauthn_authentication_username'] = self.user.username
        session.save()
        
        mock_webauthn_service.parse_authentication_credential.return_value = MagicMock(raw_id=self.credential_id_bytes)
        mock_webauthn_service.encode_base64url.return_value = self.credential_id_b64
        new_sign_count = self.existing_credential.sign_count + 1
        mock_webauthn_service.verify_authentication_response.return_value = MagicMock(new_sign_count=new_sign_count)

        response = self.client.post(WEBAUTHN_AUTH_VERIFY_URL, {"id": "a", "response": {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_login.assert_called_once_with(ANY, self.user)
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.sign_count, new_sign_count)

    def test_verify_auth_verification_fails(self, mock_webauthn_service):
        self.client.logout()
        mock_webauthn_service.is_enabled.return_value = True
        session = self.client.session
        session['webauthn_authentication_challenge'] = base64url_encode(secrets.token_bytes(32))
        session['webauthn_authentication_username'] = self.user.username
        session.save()
        mock_webauthn_service.verify_authentication_response.side_effect = WebAuthnException("Invalid signature")
        mock_webauthn_service.parse_authentication_credential.return_value = MagicMock(raw_id=self.credential_id_bytes)
        mock_webauthn_service.encode_base64url.return_value = self.credential_id_b64

        response = self.client.post(WEBAUTHN_AUTH_VERIFY_URL, {"id": "a", "rawId": self.credential_id_b64}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Authentication failed", response.data['detail'])

    # === Credential List/Detail Tests ===

    def test_list_credentials_success(self, mock_webauthn_service):
        mock_webauthn_service.is_enabled.return_value = True
        response = self.client.get(WEBAUTHN_CRED_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_count = WebAuthnCredential.objects.filter(user=self.user).count()
        self.assertGreaterEqual(len(response.data), 1, "Should be at least one credential for this test user.")
        self.assertEqual(len(response.data), expected_count, "The number of credentials returned should match the DB count.")
        
        found_credential = next((cred for cred in response.data if cred['id'] == str(self.existing_credential.pk)), None)
        self.assertIsNotNone(found_credential, "The credential from setUpTestData was not in the list response.")
        self.assertEqual(found_credential['nickname'], self.existing_credential.nickname)

    def test_list_credentials_unauthenticated(self, mock_webauthn_service):
        self.client.logout()
        response = self.client.get(WEBAUTHN_CRED_LIST_URL)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_retrieve_credential_success(self, mock_webauthn_service):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.existing_credential.pk))

    def test_retrieve_credential_forbidden(self, mock_webauthn_service):
        self.client.login(username=self.other_user.username, password=self.password)
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_credential_name_success(self, mock_webauthn_service):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        new_name = "My YubiKey"
        data = {'nickname': new_name}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['nickname'], new_name)
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.nickname, new_name)

    def test_update_credential_other_field_fails(self, mock_webauthn_service):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        original_sign_count = self.existing_credential.sign_count
        data = {'sign_count': 999, 'nickname': 'Attempt Update'}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['nickname'], 'Attempt Update')
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.sign_count, original_sign_count)

    def test_delete_credential_success(self, mock_webauthn_service):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WebAuthnCredential.objects.filter(pk=self.existing_credential.pk).exists())

    def test_delete_credential_forbidden(self, mock_webauthn_service):
        self.client.login(username=self.other_user.username, password=self.password)
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WebAuthnCredential.objects.filter(pk=self.existing_credential.pk).exists())

# --- END OF FILE ---