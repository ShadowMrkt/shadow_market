# backend/store/views/webauthn.py
# Revision: 1.8 (Fix UserSerializer ImportError) # <<< UPDATED REVISION
# Date: 2025-05-03
# Author: Gemini
# Description: Contains views for WebAuthn (FIDO2) registration, authentication, and credential management.
# Changes:
# - Rev 1.8: # <<< ADDED CHANGES
#   - FIXED: Changed import from non-existent 'UserSerializer' to existing
#     'CurrentUserSerializer' in 'backend.store.serializers' to resolve ImportError.
#   - FIXED: Updated usage in WebAuthnAuthenticationVerificationView to use
#     CurrentUserSerializer for the successful login response.
# - Rev 1.7 (2025-05-03, Gemini):
#   - FIXED: Changed import for 'IsAuthenticated' from local 'backend.store.permissions'
#     to 'rest_framework.permissions' to resolve ImportError during test collection.
# - Rev 1.6 (2025-04-29, Gemini):
#   - FIXED: Added quotes around type hints (e.g., 'PublicKeyCredentialDescriptor', 'RegistrationVerificationResult', 'WebAuthnCredential') to resolve Pylance "Variable not allowed in type expression" errors.
#   - ADDED: Comments to WebAuthn library imports noting the dependency ('webauthn') and potential environment issues if Pylance still reports unresolved imports.
# - Rev 1.5 (2025-04-29):
#   - Added WebAuthnCredentialDetailView (Retrieve, Update Name, Destroy).
#   - Implemented user-scoped queryset for detail view.
#   - Overrode update method to only allow changing the 'name' field.
# - Rev 1.4 (2025-04-29):
#   - Added WebAuthnCredentialListView.
#   - Added placeholder import for WebAuthnCredentialSerializer (needs creation).
# - Rev 1.3 (2025-04-29):
#   - Added WebAuthnAuthenticationVerificationView.
#   - Implemented authentication verification, sign count check, user login.
# - Rev 1.2 (2025-04-29):
#   - Added WebAuthnAuthenticationOptionsView.
#   - Implemented credential lookup by username and challenge generation for login.
# - Rev 1.1 (2025-04-29):
#   - Added WebAuthnRegistrationVerificationView.
#   - Implemented challenge retrieval, response verification, and credential saving.
# - Rev 1.0 (2025-04-29):
#   - Initial creation with WebAuthnRegistrationOptionsView.

# Standard Library Imports
import logging
from typing import TYPE_CHECKING, Any # Added Any
import json

# Django Imports
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import login

# Third-Party Imports
from rest_framework import status, permissions as drf_permissions, generics
from rest_framework.exceptions import APIException, ValidationError as DRFValidationError, AuthenticationFailed, PermissionDenied, NotFound, MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
# --- FIX: Import IsAuthenticated directly from DRF ---
from rest_framework.permissions import IsAuthenticated, AllowAny # AllowAny might be useful too
# TODO: Add throttling

# WebAuthn Library Imports
# --- NOTE: These imports require the 'webauthn' library to be installed. ---
# --- If Pylance reports unresolved imports, check your virtual environment. ---
try:
    import webauthn
    # Import specific structs/functions as needed by the views below
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement,
        PublicKeyCredentialDescriptor, AttestationConveyancePreference, PublicKeyCredential,
        AuthenticatorAttestationResponse, RegistrationVerificationResult,
        AuthenticationVerificationResult, AuthenticatorAssertionResponse,
    )
    from webauthn.helpers.exceptions import WebAuthnException
    from webauthn.helpers.parse_registration_credential_json import parse_registration_credential_json
    from webauthn.helpers.parse_authentication_credential_json import parse_authentication_credential_json
    from webauthn.helpers.generate_registration_options import generate_registration_options
    from webauthn.helpers.generate_authentication_options import generate_authentication_options
    from webauthn.helpers.verify_registration_response import verify_registration_response
    from webauthn.helpers.verify_authentication_response import verify_authentication_response
    from webauthn.helpers.options_to_json import options_to_json
    from webauthn.helpers.base64url_to_bytes import base64url_decode
    from webauthn.helpers.bytes_to_base64url import base64url_encode

except ImportError:
    # Define dummies if library is missing
    webauthn = None; WebAuthnException = Exception
    AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement = None, None, None
    PublicKeyCredentialDescriptor, AttestationConveyancePreference, PublicKeyCredential = None, None, None
    AuthenticatorAttestationResponse, RegistrationVerificationResult = None, None
    AuthenticationVerificationResult, AuthenticatorAssertionResponse = None, None
    def parse_registration_credential_json(json_str): return None
    def parse_authentication_credential_json(json_str): return None
    def generate_registration_options(**kwargs): return None
    def generate_authentication_options(**kwargs): return None
    def verify_registration_response(**kwargs): return None
    def verify_authentication_response(**kwargs): return None
    def options_to_json(options): return None
    def base64url_decode(val): return None
    def base64url_encode(val): return None


# --- Local Imports ---
# --- FIX: Use TYPE_CHECKING for User model import ---
if TYPE_CHECKING:
    from backend.store.models import User
# --- REMOVED incorrect import: from backend.store.permissions import IsAuthenticated ---
from backend.store.utils.utils import log_audit_event
# --- FIX: Import CurrentUserSerializer instead of non-existent UserSerializer ---
from backend.store.serializers import CurrentUserSerializer

# Assume WebAuthnCredential model exists
try:
    from backend.store.models import WebAuthnCredential
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.error("Failed to import WebAuthnCredential model. WebAuthn views will likely fail.")
    WebAuthnCredential = None

# Import the *correct* serializer created in serializers.py (Rev 2.5 or later)
try:
    from backend.store.serializers import WebAuthnCredentialSerializer
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.error("WebAuthnCredentialSerializer not found. List/Detail views will fail.")
    # Define a dummy serializer class to prevent startup errors if needed
    class WebAuthnCredentialSerializer: pass # Dummy
    WebAuthnCredentialSerializer = None


# --- Type Hinting ---
# --- FIX: Use quotes for forward references ---
if TYPE_CHECKING:
    from django.db.models.query import QuerySet
    # Import webauthn structs needed only for type hints here
    from webauthn.helpers.structs import (
        PublicKeyCredentialCreationOptions, # Needed for hint in RegistrationOptionsView
        PublicKeyCredentialRequestOptions, # Needed for hint in AuthenticationOptionsView
        RegistrationCredential, # Needed for hint in RegistrationVerificationView
        AuthenticationCredential, # Needed for hint in AuthenticationVerificationView
    )


# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')


# --- Constants / Settings ---
WEBAUTHN_RP_ID = getattr(settings, 'WEBAUTHN_RP_ID', 'localhost')
WEBAUTHN_RP_NAME = getattr(settings, 'WEBAUTHN_RP_NAME', 'Shadow Market')
WEBAUTHN_EXPECTED_ORIGIN = getattr(settings, 'WEBAUTHN_EXPECTED_ORIGIN', 'http://localhost:3000')
# --- FIX: Use quotes for type hints ---
WEBAUTHN_ATTESTATION = getattr(settings, 'WEBAUTHN_ATTESTATION', AttestationConveyancePreference.NONE if AttestationConveyancePreference else 'none')
WEBAUTHN_USER_VERIFICATION = getattr(settings, 'WEBAUTHN_USER_VERIFICATION', UserVerificationRequirement.PREFERRED if UserVerificationRequirement else 'preferred')
WEBAUTHN_REQUIRE_RESIDENT_KEY = getattr(settings, 'WEBAUTHN_REQUIRE_RESIDENT_KEY', False)


# --- Helper Function ---
def get_credential_name(request_data: dict, default_prefix: str = "Credential") -> str:
    """Gets or generates a name for the credential."""
    name = request_data.get('name', '').strip() # Use 'name' field
    if not name:
        name = f'{default_prefix} {timezone.now().strftime("%Y-%m-%d %H:%M")}'
    return name[:100] # Limit length


# --- WebAuthn Views ---

class WebAuthnRegistrationOptionsView(APIView):
    """(Rev 1.0) Generates registration options."""
    permission_classes = [IsAuthenticated] # Now uses the imported DRF permission
    def post(self, request: Request, *args, **kwargs) -> Response:
        user: 'User' = request.user # Use quotes for forward ref
        log_prefix = f"[WebAuthnRegOpt U:{user.id}/{user.username}]"

        if not webauthn or not PublicKeyCredentialDescriptor or not generate_registration_options:
            logger.critical(f"{log_prefix} 'webauthn' library not installed or helpers missing.")
            raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WebAuthnCredential:
             logger.critical(f"{log_prefix} WebAuthnCredential model not found.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WEBAUTHN_RP_ID or not WEBAUTHN_RP_NAME:
             logger.critical(f"{log_prefix} WEBAUTHN_RP_ID/Name not configured.")
             raise APIException("WebAuthn config missing.", status.HTTP_503_SERVICE_UNAVAILABLE)

        exclude_credentials: list['PublicKeyCredentialDescriptor'] = [] # Use quotes
        try:
            existing_creds_qs = WebAuthnCredential.objects.filter(user=user)
            for cred in existing_creds_qs:
                try:
                    cred_id_bytes = base64url_decode(cred.credential_id_b64)
                    # --- FIX: Use quotes for type hint ---
                    exclude_credentials.append(PublicKeyCredentialDescriptor(id=cred_id_bytes))
                except Exception as desc_err:
                     logger.warning(f"{log_prefix} Error processing existing credential PK {cred.pk} for exclusion: {desc_err}")
        except Exception as db_err:
            logger.error(f"{log_prefix} Error fetching existing WebAuthn credentials: {db_err}")

        authenticator_selection = None
        if AuthenticatorSelectionCriteria:
            # --- FIX: Use quotes for type hints ---
            resident_key_req = ResidentKeyRequirement.REQUIRED if WEBAUTHN_REQUIRE_RESIDENT_KEY else ResidentKeyRequirement.DISCOURAGED
            authenticator_selection = AuthenticatorSelectionCriteria(
                resident_key=resident_key_req, user_verification=WEBAUTHN_USER_VERIFICATION,
                require_resident_key=WEBAUTHN_REQUIRE_RESIDENT_KEY
            )

        try:
            # Safely handle user PK conversion if not UUID
            try:
                user_id_bytes = user.pk.bytes if hasattr(user.pk, 'bytes') else str(user.pk).encode('utf-8')
            except Exception as pk_err:
                logger.critical(f"{log_prefix} Failed to convert user PK ({user.pk}) to bytes: {pk_err}.")
                raise APIException("Internal server error processing user identifier.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- FIX: Use quotes for type hint ---
            options: 'PublicKeyCredentialCreationOptions' = generate_registration_options(
                rp_id=WEBAUTHN_RP_ID, rp_name=WEBAUTHN_RP_NAME, user_id=user_id_bytes,
                user_name=user.username, user_display_name=user.username,
                attestation=WEBAUTHN_ATTESTATION, authenticator_selection=authenticator_selection,
                exclude_credentials=exclude_credentials,
            )

            request.session['webauthn_registration_challenge'] = base64url_encode(options.challenge)
            request.session['webauthn_registration_user_pk'] = str(user.pk)
            logger.info(f"{log_prefix} Generated registration options.")

            options_json = options_to_json(options)
            log_audit_event(request, user, 'webauthn_register_options_generated')
            return Response(options_json, status=status.HTTP_200_OK)
        except WebAuthnException as e:
            logger.error(f"{log_prefix} WebAuthn library error: {e}")
            raise APIException(f"Could not generate options: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error: {e}")
            raise APIException("Unexpected error preparing registration.", status.HTTP_500_INTERNAL_SERVER_ERROR)


class WebAuthnRegistrationVerificationView(APIView):
    """(Rev 1.1) Verifies registration response and saves credential."""
    permission_classes = [IsAuthenticated] # Now uses the imported DRF permission
    def post(self, request: Request, *args, **kwargs) -> Response:
        user: 'User' = request.user # Use quotes
        log_prefix = f"[WebAuthnRegVerify U:{user.id}/{user.username}]"

        if not webauthn or not parse_registration_credential_json or not verify_registration_response:
             logger.critical(f"{log_prefix} 'webauthn' library missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WebAuthnCredential:
             logger.critical(f"{log_prefix} WebAuthnCredential model missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WEBAUTHN_RP_ID or not WEBAUTHN_EXPECTED_ORIGIN:
             logger.critical(f"{log_prefix} WebAuthn RP ID/Origin missing.")
             raise APIException("WebAuthn config missing.", status.HTTP_503_SERVICE_UNAVAILABLE)

        challenge_b64 = request.session.pop('webauthn_registration_challenge', None)
        expected_user_pk_str = request.session.pop('webauthn_registration_user_pk', None)

        if not challenge_b64 or not expected_user_pk_str:
            logger.warning(f"{log_prefix} No challenge/user pk in session.")
            raise DRFValidationError("Challenge expired/missing. Try again.")
        if expected_user_pk_str != str(user.pk):
             logger.error(f"{log_prefix} Session user PK ({expected_user_pk_str}) != current user ({user.pk}).")
             raise PermissionDenied("User mismatch.")

        try: expected_challenge = base64url_decode(challenge_b64)
        except Exception as e:
             logger.error(f"{log_prefix} Failed to decode challenge: {e}")
             raise DRFValidationError("Invalid challenge. Try again.")

        try:
            # --- FIX: Use quotes for type hint ---
            credential: 'RegistrationCredential' = parse_registration_credential_json(request.data)
            if not credential: raise ValueError("Failed to parse credential.")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to parse registration response: {e}.")
            raise DRFValidationError(f"Invalid registration data: {e}")

        try:
            # --- FIX: Use quotes for type hints ---
            require_uv = (WEBAUTHN_USER_VERIFICATION == UserVerificationRequirement.REQUIRED)
            verification_result: 'RegistrationVerificationResult' = verify_registration_response(
                credential=credential, expected_challenge=expected_challenge,
                expected_origin=WEBAUTHN_EXPECTED_ORIGIN, expected_rp_id=WEBAUTHN_RP_ID,
                require_user_verification=require_uv,
            )
            logger.info(f"{log_prefix} Registration response verified. CredID: {base64url_encode(verification_result.credential_id)[:10]}...")
        except WebAuthnException as e:
            logger.warning(f"{log_prefix} Registration verification failed: {e}")
            raise DRFValidationError(f"Authenticator registration failed: {e}")
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected verification error: {e}")
            raise APIException("Unexpected error during verification.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            credential_name = get_credential_name(request.data, default_prefix=f"{user.username}'s Key") # Use 'name'
            credential_id_b64 = base64url_encode(verification_result.credential_id)
            public_key_b64 = base64url_encode(verification_result.credential_public_key)

            new_credential = WebAuthnCredential.objects.create(
                user=user, name=credential_name, credential_id_b64=credential_id_b64,
                public_key_b64=public_key_b64, sign_count=verification_result.sign_count,
                last_used_at=timezone.now()
            )
            logger.info(f"{log_prefix} New WebAuthnCredential {new_credential.pk} saved for CredID {credential_id_b64[:10]}...")
            log_audit_event(request, user, 'webauthn_register_verify_success', target_user=user, details=f"CredID: {credential_id_b64[:10]} Name: {credential_name}")
        except IntegrityError:
            logger.warning(f"{log_prefix} Credential ID {credential_id_b64[:10]} already exists.")
            raise DRFValidationError("Authenticator already registered.")
        except Exception as e:
            logger.exception(f"{log_prefix} Failed to save credential: {e}")
            raise APIException("Failed to save security key.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"verified": True}, status=status.HTTP_201_CREATED)


class WebAuthnAuthenticationOptionsView(APIView):
    """(Rev 1.2) Generates authentication options challenge for a given username."""
    permission_classes = [AllowAny] # Public endpoint to get challenge
    # throttle_classes = [AnonRateThrottle]
    def post(self, request: Request, *args, **kwargs) -> Response:
        username = request.data.get('username', '').strip()
        log_prefix = f"[WebAuthnAuthOpt U:{username}]"

        if not username:
            raise DRFValidationError({"username": ["This field is required."]})

        if not webauthn or not generate_authentication_options:
             logger.critical(f"{log_prefix} 'webauthn' library missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        # --- FIX: Need User model from Django auth or local models ---
        # Determine where User model comes from (django.contrib.auth.models or backend.store.models)
        # Let's assume it's a custom user model for now:
        try:
            from backend.store.models import User
        except ImportError:
            logger.critical(f"{log_prefix} User model cannot be imported.")
            raise APIException("User model configuration error.", status.HTTP_503_SERVICE_UNAVAILABLE)

        if not WebAuthnCredential:
             logger.critical(f"{log_prefix} WebAuthnCredential model missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WEBAUTHN_RP_ID:
             logger.critical(f"{log_prefix} WebAuthn RP ID missing.")
             raise APIException("WebAuthn config missing.", status.HTTP_503_SERVICE_UNAVAILABLE)

        try: user = User.objects.get(username__iexact=username)
        except ObjectDoesNotExist:
             logger.warning(f"{log_prefix} User not found.")
             raise NotFound("User not found or no security keys registered.")

        allow_credentials: list['PublicKeyCredentialDescriptor'] = [] # Use quotes
        try:
            user_creds_qs = WebAuthnCredential.objects.filter(user=user)
            if not user_creds_qs.exists():
                 logger.warning(f"{log_prefix} User found but has no credentials.")
                 raise NotFound("User not found or no security keys registered.")
            for cred in user_creds_qs:
                try:
                    cred_id_bytes = base64url_decode(cred.credential_id_b64)
                    # --- FIX: Use quotes for type hint ---
                    allow_credentials.append(PublicKeyCredentialDescriptor(id=cred_id_bytes))
                except Exception as desc_err:
                     logger.warning(f"{log_prefix} Error processing credential PK {cred.pk} for allow list: {desc_err}")
        except Exception as db_err:
            logger.error(f"{log_prefix} Error fetching credentials: {db_err}")
            raise APIException("Error retrieving security key info.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not allow_credentials:
             logger.error(f"{log_prefix} User {user.id} has entries but none processable.")
             raise APIException("Error processing security key info.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            # --- FIX: Use quotes for type hint ---
            options: 'PublicKeyCredentialRequestOptions' = generate_authentication_options(
                rp_id=WEBAUTHN_RP_ID, allow_credentials=allow_credentials,
                user_verification=WEBAUTHN_USER_VERIFICATION,
            )

            request.session['webauthn_authentication_challenge'] = base64url_encode(options.challenge)
            request.session['webauthn_authentication_username'] = username
            logger.info(f"{log_prefix} Generated authentication options.")

            options_json = options_to_json(options)
            return Response(options_json, status=status.HTTP_200_OK)
        except WebAuthnException as e:
            logger.error(f"{log_prefix} WebAuthn library error: {e}")
            raise APIException(f"Could not generate options: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error: {e}")
            raise APIException("Unexpected error preparing authentication.", status.HTTP_500_INTERNAL_SERVER_ERROR)


class WebAuthnAuthenticationVerificationView(APIView):
    """(Rev 1.3) Verifies authentication response and logs user in."""
    permission_classes = [AllowAny] # Public endpoint to verify challenge
    # throttle_classes = [AnonRateThrottle]
    @transaction.atomic
    def post(self, request: Request, *args, **kwargs) -> Response:
        if not webauthn or not verify_authentication_response or not parse_authentication_credential_json:
             logger.critical(f"'webauthn' library/helpers missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        # --- FIX: Need User model from Django auth or local models ---
        try:
            from backend.store.models import User
        except ImportError:
            logger.critical("User model cannot be imported.")
            raise APIException("User model configuration error.", status.HTTP_503_SERVICE_UNAVAILABLE)

        if not WebAuthnCredential:
             logger.critical(f"WebAuthnCredential model missing.")
             raise APIException("WebAuthn service is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE)
        if not WEBAUTHN_RP_ID or not WEBAUTHN_EXPECTED_ORIGIN:
             logger.critical(f"WebAuthn RP ID/Origin missing.")
             raise APIException("WebAuthn config missing.", status.HTTP_503_SERVICE_UNAVAILABLE)

        challenge_b64 = request.session.pop('webauthn_authentication_challenge', None)
        username = request.session.pop('webauthn_authentication_username', None)
        log_prefix = f"[WebAuthnAuthVerify U:{username or 'UNKNOWN'}]"

        if not challenge_b64 or not username:
            logger.warning(f"{log_prefix} No challenge/username in session.")
            raise AuthenticationFailed("Challenge expired/missing. Try again.")

        try: expected_challenge = base64url_decode(challenge_b64)
        except Exception as e:
             logger.error(f"{log_prefix} Failed to decode challenge: {e}")
             raise AuthenticationFailed("Invalid challenge. Try again.")

        try:
            # --- FIX: Use quotes for type hint ---
            credential: 'AuthenticationCredential' = parse_authentication_credential_json(request.data)
            if not credential: raise ValueError("Failed to parse credential.")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to parse auth response: {e}.")
            raise AuthenticationFailed(f"Invalid authentication data: {e}")

        credential_id_b64 = base64url_encode(credential.raw_id) # Needed for lookup & logging
        try:
            user = User.objects.get(username__iexact=username)
            # --- FIX: Use quotes for type hint ---
            stored_credential: 'WebAuthnCredential' = WebAuthnCredential.objects.select_for_update().get(
                user=user, credential_id_b64=credential_id_b64
            )
            logger.debug(f"{log_prefix} Found stored credential PK {stored_credential.pk} for ID {credential_id_b64[:10]}...")

        except ObjectDoesNotExist:
             logger.warning(f"{log_prefix} User or credential not found for ID {credential_id_b64[:10]}...")
             raise AuthenticationFailed("Authentication failed. User/key not recognized.")
        except Exception as e:
             logger.error(f"{log_prefix} Error fetching user/credential for ID {credential_id_b64[:10]}: {e}")
             raise APIException("Error retrieving key info.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            # --- FIX: Use quotes for type hint ---
            require_uv = (WEBAUTHN_USER_VERIFICATION == UserVerificationRequirement.REQUIRED)
            stored_public_key_bytes = base64url_decode(stored_credential.public_key_b64)

            # --- FIX: Use quotes for type hint ---
            verification_result: 'AuthenticationVerificationResult' = verify_authentication_response(
                credential=credential, expected_challenge=expected_challenge,
                expected_rp_id=WEBAUTHN_RP_ID, expected_origin=WEBAUTHN_EXPECTED_ORIGIN,
                credential_public_key=stored_public_key_bytes,
                credential_current_sign_count=stored_credential.sign_count,
                require_user_verification=require_uv,
            )
            logger.info(f"{log_prefix} Authentication response verified.")

        except WebAuthnException as e:
            logger.warning(f"{log_prefix} Authentication verification failed: {e}")
            log_audit_event(request, None, 'webauthn_auth_verify_failed', target_user=user, details=f"CredID: {credential_id_b64[:10]} Reason: {e}")
            raise AuthenticationFailed(f"Authentication failed: {e}")
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected auth verification error: {e}")
            raise APIException("Unexpected error during authentication.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        if verification_result.new_sign_count <= stored_credential.sign_count:
            logger.critical(f"{log_prefix} Possible replay attack! New sign count ({verification_result.new_sign_count}) <= stored ({stored_credential.sign_count}) for Cred PK {stored_credential.pk}.")
            log_audit_event(request, None, 'webauthn_auth_replay_detected', target_user=user, details=f"CredPK: {stored_credential.pk}")
            raise AuthenticationFailed("Authentication failed (security check).")

        stored_credential.sign_count = verification_result.new_sign_count
        stored_credential.last_used_at = timezone.now()
        stored_credential.save(update_fields=['sign_count', 'last_used_at'])
        logger.info(f"{log_prefix} Updated sign count to {verification_result.new_sign_count} for Cred PK {stored_credential.pk}.")

        login(request, user)
        logger.info(f"{log_prefix} User successfully authenticated via WebAuthn and logged in.")

        request.session.pop('pgp_auth_status', None)
        request.session.pop('pgp_auth_challenge', None)
        request.session.pop('pgp_auth_username', None)

        log_audit_event(request, user, 'webauthn_auth_verify_success', target_user=user, details=f"CredPK: {stored_credential.pk}")
        security_logger.info(f"Successful WebAuthn login for user {user.username} (ID: {user.id}) using Credential PK {stored_credential.pk}")

        # --- FIX: Use CurrentUserSerializer ---
        if CurrentUserSerializer:
            serializer = CurrentUserSerializer(user, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
             logger.error(f"{log_prefix} CurrentUserSerializer not found, cannot serialize user data.")
             # Return a generic success response if serializer is missing
             return Response({"message": "Login successful"}, status=status.HTTP_200_OK)


class WebAuthnCredentialListView(generics.ListAPIView):
    """(Rev 1.4) Lists WebAuthn credentials for the current user."""
    permission_classes = [IsAuthenticated] # Now uses the imported DRF permission
    serializer_class = WebAuthnCredentialSerializer # Use the corrected serializer

    # --- FIX: Use quotes for type hint ---
    def get_queryset(self) -> 'QuerySet[WebAuthnCredential]':
        """Returns credentials belonging to the current user."""
        user = self.request.user
        # Check if model/serializer were imported correctly
        if not WebAuthnCredential or not WebAuthnCredentialSerializer:
             logger.error(f"WebAuthnCredential model or serializer missing for user {user.id}")
             # Check if WebAuthnCredential exists before trying to query
             if WebAuthnCredential: return WebAuthnCredential.objects.none()
             else: return [] # Return empty list if model itself is missing

        return WebAuthnCredential.objects.filter(user=user).order_by('name', '-created_at')


class WebAuthnCredentialDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Allows retrieving, updating (name only), and deleting a specific
    WebAuthn credential for the currently authenticated user. (Rev 1.5)
    """
    permission_classes = [IsAuthenticated] # Now uses the imported DRF permission
    serializer_class = WebAuthnCredentialSerializer # Use the corrected serializer
    queryset = WebAuthnCredential.objects.all() # Base queryset
    lookup_field = 'pk' # Identify credential by its primary key

    # --- FIX: Use quotes for type hint ---
    def get_queryset(self) -> 'QuerySet[WebAuthnCredential]':
        """Ensures users can only access their own credentials."""
        user = self.request.user
        # Check if model was imported correctly
        if not WebAuthnCredential:
            logger.error(f"WebAuthnCredential model missing for user {user.id} in detail view.")
            return [] # Should not happen if List view worked, but safe check
        return self.queryset.filter(user=user)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Override update to only allow changing the 'name' field."""
        # --- FIX: Use quotes for type hint ---
        instance: 'WebAuthnCredential' = self.get_object() # Performs permission checks via get_queryset
        new_name = request.data.get('name', '').strip()
        log_prefix = f"[WebAuthnCredDetail U:{request.user.id}]"

        # Basic validation for the name
        if not new_name:
            raise DRFValidationError({'name': 'Credential name cannot be empty.'})
        if len(new_name) > 100: # Match helper function limit
             raise DRFValidationError({'name': 'Credential name cannot exceed 100 characters.'})

        if instance.name == new_name:
             # No change, just return existing data
             serializer = self.get_serializer(instance)
             return Response(serializer.data)

        old_name = instance.name
        instance.name = new_name
        try:
            instance.save(update_fields=['name'])
            logger.info(f"{log_prefix} Renamed WebAuthn credential PK {instance.pk} from '{old_name}' to '{new_name}'.")
            log_audit_event(request, request.user, 'webauthn_credential_rename', target_user=request.user, details=f"CredPK: {instance.pk}, Old: {old_name}, New: {new_name}")
            serializer = self.get_serializer(instance)
            return Response(serializer.data)
        except Exception as e:
            logger.exception(f"{log_prefix} Failed to rename WebAuthn credential PK {instance.pk}: {e}")
            raise APIException("Failed to update credential name.", status.HTTP_500_INTERNAL_SERVER_ERROR)

    # --- FIX: Use quotes for type hint ---
    def perform_destroy(self, instance: 'WebAuthnCredential') -> None:
        """Log before deleting."""
        log_prefix = f"[WebAuthnCredDetail U:{self.request.user.id}]"
        cred_pk = instance.pk
        cred_name = instance.name
        cred_id_b64_short = instance.credential_id_b64[:10] if instance.credential_id_b64 else 'N/A'

        logger.info(f"{log_prefix} Deleting WebAuthn credential PK {cred_pk} (Name: '{cred_name}', ID: {cred_id_b64_short}...).")
        log_audit_event(self.request, self.request.user, 'webauthn_credential_delete', target_user=self.request.user, details=f"CredPK: {cred_pk}, Name: {cred_name}, ID: {cred_id_b64_short}")
        security_logger.warning(f"User {self.request.user.username} deleted WebAuthn credential PK {cred_pk} (Name: '{cred_name}')")

        super().perform_destroy(instance)


# --- END OF FILE ---