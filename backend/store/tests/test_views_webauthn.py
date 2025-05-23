# backend/store/tests/test_views_webauthn.py
# Revision: 1.1
# Date: 2025-05-22
# Author: Gemini
# Description: Contains tests for the WebAuthn API views in views/webauthn.py.
# Changes:
# - Rev 1.1:
#   - Set pgp_public_key to None for test user creations in setUpTestData
#     to comply with stricter PGP validation in models.py (v1.4.2+).
#     WebAuthn view tests do not typically depend on user PGP key content for these flows.
# - Rev 1.0 (Initial Creation):
#   - Date: 2025-04-29
#   - Author: Gemini
#   - Description: Contains tests for the WebAuthn API views in views/webauthn.py.

# Standard Library Imports
import uuid
from unittest.mock import patch, MagicMock, ANY # Import ANY for flexible mocking assertions
import base64
import secrets # For challenge generation simulation

# Django Imports
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone # Added for consistency, though not directly used yet

# Third-Party Imports
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

# WebAuthn library helpers (import for type hints if needed, but we'll mock them)
# from webauthn.helpers.structs import PublicKeyCredentialDescriptor, RegistrationCredential, AuthenticationCredential
# from webauthn.helpers.exceptions import WebAuthnException

# Local Application Imports
from backend.store.models import WebAuthnCredential, User as StoreUser # Renamed User

# --- Constants ---
User = get_user_model()

# URLs (adjust based on actual URL names in urls.py)
WEBAUTHN_REG_OPTIONS_URL = reverse('store:webauthn-register-options')
WEBAUTHN_REG_VERIFY_URL = reverse('store:webauthn-register-verify')
WEBAUTHN_AUTH_OPTIONS_URL = reverse('store:webauthn-authenticate-options')
WEBAUTHN_AUTH_VERIFY_URL = reverse('store:webauthn-authenticate-verify')
WEBAUTHN_CRED_LIST_URL = reverse('store:webauthn-credential-list')
# Detail URL needs a placeholder for the PK/ID
WEBAUTHN_CRED_DETAIL_URL_NAME = 'store:webauthn-credential-detail' # Name to use with reverse

# Helper for base64url encoding (Python's base64 uses + and /)
def base64url_encode(data_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(data_bytes).rstrip(b'=').decode('utf-8')

def base64url_decode(data_str: str) -> bytes:
    padding = b'=' * (4 - (len(data_str) % 4))
    return base64.urlsafe_b64decode(data_str.encode('utf-8') + padding)

# --- Test Cases ---

@patch('backend.store.views.webauthn.log_audit_event', MagicMock()) # Mock audit logging globally for these tests
class WebAuthnViewTests(APITestCase):
    """Tests for WebAuthn views."""

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.password = 'strongpassword123'
        cls.user = User.objects.create_user(
            username='webauthn_user',
            password=cls.password,
            pgp_public_key=None # Set to None
        )
        cls.user_no_creds = User.objects.create_user(
            username='webauthn_user_no_creds',
            password=cls.password,
            pgp_public_key=None # Set to None
        )

        # Create a sample existing credential for user1
        cls.credential_id_bytes = secrets.token_bytes(16)
        cls.public_key_bytes = secrets.token_bytes(65) # Example length
        cls.credential_id_b64 = base64url_encode(cls.credential_id_bytes)
        cls.public_key_b64 = base64url_encode(cls.public_key_bytes)

        cls.existing_credential = WebAuthnCredential.objects.create(
            user=cls.user,
            credential_id_b64=cls.credential_id_b64,
            public_key_b64=cls.public_key_b64,
            sign_count=10,
            nickname="Test Key"
        )
        # Create another user for permission checks on credential detail/delete
        cls.other_user = User.objects.create_user(
            username='webauthn_other_user', password=cls.password, pgp_public_key=None
        )


    def setUp(self):
        """Set up for each test method."""
        self.client = APIClient()
        self.client.login(username=self.user.username, password=self.password)

    # === Registration Options Tests ===

    @patch('backend.store.views.webauthn.generate_registration_options')
    def test_get_reg_options_success(self, mock_generate_options):
        mock_options = MagicMock()
        mock_options.challenge = secrets.token_bytes(32)
        # Ensure options_to_json returns a dict directly, or mock its structure
        mock_options.dict.return_value = {
            "rp": {"name": "Shadow Market", "id": "localhost"},
            "user": {"id": str(self.user.id).encode(), "name": self.user.username, "displayName": self.user.username},
            "challenge": base64url_encode(mock_options.challenge),
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "excludeCredentials": [{"type": "public-key", "id": self.credential_id_b64}],
            "authenticatorSelection": {"userVerification": "preferred"},
            "timeout": 300000,
            "attestation": "none"
        }
        mock_generate_options.return_value = mock_options

        response = self.client.post(WEBAUTHN_REG_OPTIONS_URL, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_generate_options.assert_called_once()
        args, kwargs = mock_generate_options.call_args
        self.assertEqual(kwargs.get('rp_id'), 'localhost') # Check against settings used in view
        self.assertEqual(kwargs.get('rp_name'), 'Shadow Market')
        self.assertEqual(kwargs.get('user_name'), self.user.username)
        # Check if existing credential ID was excluded (WebAuthn lib expects bytes for id here)
        self.assertTrue(any(desc.id == self.credential_id_bytes for desc in kwargs.get('exclude_credentials', [])))

        session = self.client.session
        self.assertIn('webauthn_registration_challenge', session)
        self.assertEqual(session['webauthn_registration_user_pk'], str(self.user.pk))
        self.assertEqual(base64url_decode(session['webauthn_registration_challenge']), mock_options.challenge)
        self.assertIn('challenge', response.data)
        self.assertEqual(response.data['challenge'], base64url_encode(mock_options.challenge))


    def test_get_reg_options_unauthenticated(self):
        self.client.logout()
        response = self.client.post(WEBAUTHN_REG_OPTIONS_URL, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # === Registration Verification Tests ===

    @patch('backend.store.views.webauthn.verify_registration_response')
    @patch('backend.store.views.webauthn.parse_registration_credential_json')
    def test_verify_reg_success(self, mock_parse_json, mock_verify_response):
        challenge_bytes = secrets.token_bytes(32)
        challenge_b64 = base64url_encode(challenge_bytes)
        session = self.client.session
        session['webauthn_registration_challenge'] = challenge_b64
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()

        mock_parsed_credential = MagicMock()
        mock_parse_json.return_value = mock_parsed_credential

        new_cred_id_bytes = secrets.token_bytes(16)
        new_pub_key_bytes = secrets.token_bytes(65)
        mock_verify_result = MagicMock(
            credential_id=new_cred_id_bytes,
            credential_public_key=new_pub_key_bytes,
            sign_count=0
        )
        mock_verify_response.return_value = mock_verify_result

        verification_data = {
            "id": base64url_encode(new_cred_id_bytes), "rawId": base64url_encode(new_cred_id_bytes),
            "response": {"clientDataJSON": "mockClientData", "attestationObject": "mockAttestationObject"},
            "type": "public-key", "name": "My New Key"
        }
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {"verified": True})
        mock_parse_json.assert_called_once_with(verification_data)
        mock_verify_response.assert_called_once()
        # More specific check on mock_verify_response args
        args, kwargs_verify = mock_verify_response.call_args
        self.assertEqual(kwargs_verify.get('expected_challenge'), challenge_bytes)

        self.assertTrue(WebAuthnCredential.objects.filter(user=self.user, credential_id_b64=base64url_encode(new_cred_id_bytes)).exists())
        new_cred = WebAuthnCredential.objects.get(credential_id_b64=base64url_encode(new_cred_id_bytes))
        self.assertEqual(new_cred.nickname, "My New Key") # Check correct field name
        self.assertEqual(new_cred.sign_count, 0)
        self.assertNotIn('webauthn_registration_challenge', self.client.session)
        self.assertNotIn('webauthn_registration_user_pk', self.client.session)

    def test_verify_reg_no_challenge_in_session(self):
        verification_data = { "id": "any_id", "response": {} }
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Challenge expired/missing", response.data['detail'])

    @patch('backend.store.views.webauthn.verify_registration_response')
    @patch('backend.store.views.webauthn.parse_registration_credential_json')
    def test_verify_reg_verification_fails(self, mock_parse_json, mock_verify_response):
        challenge_bytes = secrets.token_bytes(32)
        session = self.client.session
        session['webauthn_registration_challenge'] = base64url_encode(challenge_bytes)
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()
        mock_parse_json.return_value = MagicMock()
        from webauthn.helpers.exceptions import InvalidRegistrationResponse # Import actual exception
        mock_verify_response.side_effect = InvalidRegistrationResponse("Signature mismatch")

        verification_data = { "id": "any_id", "response": {} }
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Authenticator registration failed", response.data['detail'])

    @patch('backend.store.views.webauthn.verify_registration_response')
    @patch('backend.store.views.webauthn.parse_registration_credential_json')
    def test_verify_reg_credential_already_exists(self, mock_parse_json, mock_verify_response):
        challenge_bytes = secrets.token_bytes(32)
        session = self.client.session
        session['webauthn_registration_challenge'] = base64url_encode(challenge_bytes)
        session['webauthn_registration_user_pk'] = str(self.user.pk)
        session.save()
        mock_parse_json.return_value = MagicMock()
        mock_verify_result = MagicMock(credential_id=self.credential_id_bytes, credential_public_key=self.public_key_bytes, sign_count=0)
        mock_verify_response.return_value = mock_verify_result

        verification_data = { "id": self.credential_id_b64, "response": {} }
        response = self.client.post(WEBAUTHN_REG_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Authenticator already registered", response.data['detail'])

    # === Authentication Options Tests ===

    @patch('backend.store.views.webauthn.generate_authentication_options')
    def test_get_auth_options_success(self, mock_generate_options):
        self.client.logout()
        mock_options = MagicMock()
        mock_options.challenge = secrets.token_bytes(32)
        # Ensure options_to_json returns a dict directly, or mock its structure
        mock_options.dict.return_value = {
            "challenge": base64url_encode(mock_options.challenge),
            "rpId": "localhost",
            "allowCredentials": [{"type": "public-key", "id": self.credential_id_b64}],
            "userVerification": "preferred",
            "timeout": 300000
        }
        mock_generate_options.return_value = mock_options

        request_data = {'username': self.user.username}
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, request_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_generate_options.assert_called_once()
        args, kwargs = mock_generate_options.call_args
        self.assertEqual(kwargs.get('rp_id'), 'localhost')
        self.assertTrue(any(desc.id == self.credential_id_bytes for desc in kwargs.get('allow_credentials', [])))

        session = self.client.session
        self.assertIn('webauthn_authentication_challenge', session)
        self.assertEqual(session['webauthn_authentication_username'], self.user.username)
        self.assertEqual(base64url_decode(session['webauthn_authentication_challenge']), mock_options.challenge)
        self.assertEqual(response.data['challenge'], base64url_encode(mock_options.challenge))


    def test_get_auth_options_user_not_found(self):
        self.client.logout()
        request_data = {'username': 'nonexistentuser'}
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, request_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_auth_options_user_no_credentials(self):
        self.client.logout()
        request_data = {'username': self.user_no_creds.username}
        response = self.client.post(WEBAUTHN_AUTH_OPTIONS_URL, request_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # === Authentication Verification Tests ===

    @patch('django.contrib.auth.login')
    @patch('backend.store.views.webauthn.verify_authentication_response')
    @patch('backend.store.views.webauthn.parse_authentication_credential_json')
    def test_verify_auth_success(self, mock_parse_json, mock_verify_response, mock_login):
        self.client.logout()
        challenge_bytes = secrets.token_bytes(32)
        session = self.client.session
        session['webauthn_authentication_challenge'] = base64url_encode(challenge_bytes)
        session['webauthn_authentication_username'] = self.user.username
        session.save()

        mock_parsed_credential = MagicMock(raw_id=self.credential_id_bytes)
        mock_parse_json.return_value = mock_parsed_credential
        new_sign_count = self.existing_credential.sign_count + 1
        mock_verify_result = MagicMock(new_sign_count=new_sign_count)
        mock_verify_response.return_value = mock_verify_result

        verification_data = {
            "id": self.credential_id_b64, "rawId": self.credential_id_b64,
            "response": {"clientDataJSON": "c", "authenticatorData": "a", "signature": "s"},
            "type": "public-key"
        }
        response = self.client.post(WEBAUTHN_AUTH_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_parse_json.assert_called_once_with(verification_data)
        mock_verify_response.assert_called_once()
        args_verify, kwargs_verify = mock_verify_response.call_args
        self.assertEqual(kwargs_verify.get('expected_challenge'), challenge_bytes)
        self.assertEqual(kwargs_verify.get('credential_public_key'), self.public_key_bytes)
        self.assertEqual(kwargs_verify.get('credential_current_sign_count'), self.existing_credential.sign_count)

        mock_login.assert_called_once_with(ANY, self.user)
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.sign_count, new_sign_count)
        self.assertIsNotNone(self.existing_credential.last_used_at)
        self.assertNotIn('webauthn_authentication_challenge', self.client.session)
        self.assertNotIn('webauthn_authentication_username', self.client.session)

    @patch('backend.store.views.webauthn.verify_authentication_response')
    def test_verify_auth_verification_fails(self, mock_verify_response):
        self.client.logout()
        challenge_bytes = secrets.token_bytes(32)
        session = self.client.session
        session['webauthn_authentication_challenge'] = base64url_encode(challenge_bytes)
        session['webauthn_authentication_username'] = self.user.username
        session.save()
        from webauthn.helpers.exceptions import InvalidAuthenticationResponse # Import actual exception
        mock_verify_response.side_effect = InvalidAuthenticationResponse("Invalid signature")

        verification_data = { "id": self.credential_id_b64, "rawId": self.credential_id_b64, "response": {} }
        response = self.client.post(WEBAUTHN_AUTH_VERIFY_URL, verification_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Authentication failed", response.data['detail'])

    # === Credential List/Detail Tests ===

    def test_list_credentials_success(self):
        response = self.client.get(WEBAUTHN_CRED_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(self.existing_credential.pk))
        self.assertEqual(response.data[0]['nickname'], self.existing_credential.nickname)

    def test_list_credentials_unauthenticated(self):
        self.client.logout()
        response = self.client.get(WEBAUTHN_CRED_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_credential_success(self):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.existing_credential.pk))
        self.assertEqual(response.data['credential_id_b64'], self.existing_credential.credential_id_b64)

    def test_retrieve_credential_forbidden(self):
        self.client.login(username=self.other_user.username, password=self.password) # Log in as different user
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_credential_name_success(self):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        new_name = "My YubiKey"
        data = {'nickname': new_name} # Serializer expects 'nickname'
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['nickname'], new_name)
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.nickname, new_name)

    def test_update_credential_other_field_fails(self):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        data = {'sign_count': 999, 'nickname': 'Attempt Update'}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['nickname'], 'Attempt Update')
        self.existing_credential.refresh_from_db()
        self.assertEqual(self.existing_credential.nickname, 'Attempt Update')
        self.assertNotEqual(self.existing_credential.sign_count, 999)

    def test_delete_credential_success(self):
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WebAuthnCredential.objects.filter(pk=self.existing_credential.pk).exists())

    def test_delete_credential_forbidden(self):
        self.client.login(username=self.other_user.username, password=self.password) # Log in as different user
        url = reverse(WEBAUTHN_CRED_DETAIL_URL_NAME, kwargs={'pk': self.existing_credential.pk})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WebAuthnCredential.objects.filter(pk=self.existing_credential.pk).exists())

# --- END OF FILE ---