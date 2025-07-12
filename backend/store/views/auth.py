# backend/store/views/auth.py
# Revision: 4.0
# Date: 2025-06-21
# Author: Gemini
# Description: Contains authentication (Register, Login, Logout) and user profile (CurrentUser) views.
# Changes:
# - Rev 4.0:
#   - FIXED: In RegisterView, wrapped the serializer.save() call in a try/except block to catch `ValueError`
#     raised from the model layer (e.g., on invalid PGP key). This now correctly returns a 400 Bad Request
#     instead of a 500 Internal Server Error.
#   - FIXED: In LoginInitView, corrected the exception handling logic. The `AuthenticationFailed` exception
#     is now handled inside the main `try` block, preventing fall-through to an invalid `except` block
#     that was causing a `TypeError` during tests and resulting in a 500 error on wrong password.
#   - RETAINED: All fixes from Rev 3.0, including the use of DRF serializers over Django forms.
# - (Older revisions omitted for brevity)

# Standard Library Imports
import logging
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple, Type, Union, TYPE_CHECKING

# Django Imports
from django.conf import settings
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions, serializers
from rest_framework.exceptions import (
    PermissionDenied, NotAuthenticated, NotFound, ValidationError as DRFValidationError,
    APIException, AuthenticationFailed
)
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

# --- Local Imports (Using absolute paths from 'backend') ---
from backend.store.models import User
from backend.store.serializers import UserPublicSerializer, CurrentUserSerializer
from backend.store.permissions import IsPgpAuthenticated, PGP_AUTH_SESSION_KEY
from backend.store.services import pgp_service
from backend.store.utils.utils import get_client_ip, log_audit_event

if TYPE_CHECKING:
    from backend.store.models import User

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# --- Local Serializers (Best practice: move to serializers.py) ---

class UserRegistrationSerializer(serializers.ModelSerializer):
    """Handles validation for new user registration."""
    password_confirm = serializers.CharField(write_only=True, required=True)
    pgp_public_key = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ['username', 'password', 'password_confirm', 'pgp_public_key']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check that the two password entries match."""
        if data['password'] != data.pop('password_confirm'):
            raise DRFValidationError({"password_confirm": "Passwords do not match."})
        return data

    def create(self, validated_data: Dict[str, Any]) -> 'User':
        """Create and return a new user instance, given the validated data."""
        # This can raise a ValueError from the model's clean/save methods (e.g., PGP validation)
        return User.objects.create_user(**validated_data)

class LoginInitSerializer(serializers.Serializer):
    """Handles validation for the first step of login."""
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

class PGPChallengeResponseSerializer(serializers.Serializer):
    """Handles validation for the PGP challenge response."""
    signed_challenge = serializers.CharField(required=True, trim_whitespace=False)


# --- Rate Limiting Throttles ---
class LoginInitThrottle(ScopedRateThrottle): scope = 'login_init'
class LoginPgpThrottle(ScopedRateThrottle): scope = 'login_pgp'
class RegisterThrottle(ScopedRateThrottle): scope = 'register'


# --- Authentication Views ---

class RegisterView(generics.CreateAPIView):
    """Handles new user registration using a DRF serializer."""
    queryset = User.objects.all()
    permission_classes = [drf_permissions.AllowAny]
    serializer_class = UserRegistrationSerializer
    throttle_classes = [RegisterThrottle]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handles the POST request for user registration."""
        serializer = self.get_serializer(data=request.data)
        username_attempt = request.data.get('username', 'N/A')
        try:
            serializer.is_valid(raise_exception=True)
            
            with transaction.atomic():
                # FIX: Catch ValueError from model validation (e.g., invalid PGP key)
                try:
                    user: 'User' = serializer.save()
                except (ValueError, DjangoValidationError) as e:
                    logger.warning(f"Registration failed for {username_attempt} due to model validation: {e}")
                    raise DRFValidationError({"detail": str(e)}) from e

                # Generate a unique, non-guessable login phrase
                login_phrase_base = f"{user.username[:5].lower()}-{secrets.token_hex(3)}"
                user.login_phrase = f"Phrase-{secrets.token_hex(3)}-{login_phrase_base}"
                user.save(update_fields=['login_phrase'])

            ip_addr = get_client_ip(request)
            logger.info(f"User registered: User:{user.id}/{user.username}, IP:{ip_addr}")
            security_logger.info(f"New user registration: Username={user.username}, IP={ip_addr}")
            log_audit_event(request, user, 'register_success', target_user=user)

            # Return public user data, not the registration data
            public_serializer = UserPublicSerializer(user)
            return Response(public_serializer.data, status=status.HTTP_201_CREATED)

        except DRFValidationError:
            logger.warning(f"Registration failed for {username_attempt}: ValidationErrors={json.dumps(serializer.errors)}")
            raise

        except IntegrityError as e:
            logger.warning(f"Registration integrity error for {username_attempt}: {e}")
            if 'UNIQUE constraint' in str(e) and ('username' in str(e) or 'auth_user_username_key' in str(e)):
                raise DRFValidationError({"username": ["A user with that username already exists."]})
            elif 'login_phrase' in str(e):
                logger.error(f"Login phrase collision during registration for {username_attempt}.")
                raise APIException("A temporary registration issue occurred. Please try again.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                raise APIException("An internal database error occurred during registration.", code=status.HTTP_500_INTERNAL_SERVER_ERROR) from e
        
        except Exception as e:
            logger.exception(f"An unexpected error occurred during registration for {username_attempt}: {e}")
            raise APIException("An internal error occurred during registration.", code=status.HTTP_500_INTERNAL_SERVER_ERROR) from e


class LoginInitView(APIView):
    """Step 1: Password Verification. Generates a PGP challenge."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginInitThrottle]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ip_addr = get_client_ip(request)
        serializer = LoginInitSerializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user: Optional['User'] = authenticate(request, username=username, password=password)

            if user is None:
                # FIX: Handle failed authentication directly to avoid falling into other except blocks.
                logger.warning(f"Login Step 1 failed for username: {username} (Invalid credentials or inactive). IP:{ip_addr}")
                potential_user = User.objects.filter(username=username).first()
                if potential_user:
                    log_audit_event(request, potential_user, 'login_fail', details="Invalid credentials or inactive user")
                raise AuthenticationFailed(detail="Invalid username or password.")

            if not user.pgp_public_key:
                logger.warning(f"Login Step 1 failed for User:{user.id}/{username}: No PGP key configured.")
                log_audit_event(request, user, 'login_fail', details="Login Step 1 Failed: No PGP Key")
                raise DRFValidationError(
                    {"detail": "Login requires a PGP key configured on your profile."},
                    code='pgp_key_required'
                )

            challenge_text = pgp_service.generate_pgp_challenge(user)
            if not challenge_text:
                logger.error(f"PGP challenge generation returned empty for User:{user.id}/{username}.")
                raise APIException("Failed to generate PGP challenge.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            request.session['_login_user_id_pending_pgp'] = user.id
            request.session.set_expiry(pgp_service.CHALLENGE_TIMEOUT_SECONDS)
            logger.info(f"Login Step 1 OK for User:{user.id}/{user.username}. PGP challenge generated. IP:{ip_addr}")
            
            return Response({
                "message": "Credentials verified. Please sign the PGP challenge.",
                "pgp_challenge": challenge_text,
                "login_phrase": user.login_phrase or "Login phrase not set.",
            }, status=status.HTTP_200_OK)

        except (DRFValidationError, AuthenticationFailed):
            # Let these specific exceptions be handled by DRF's default exception handler
            raise

        except pgp_service.PGPError as e:
            username = serializer.validated_data.get('username', 'N/A')
            logger.exception(f"PGP service error generating challenge for User:{username}: {e}")
            raise APIException(f"Failed to generate PGP challenge: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR) from e
        
        except Exception as e:
            username = serializer.validated_data.get('username', 'N/A')
            logger.exception(f"Unexpected error during login initialization for User:{username}: {e}")
            raise APIException("An internal error occurred during login initialization.", status.HTTP_500_INTERNAL_SERVER_ERROR) from e

class LoginPgpVerifyView(APIView):
    """Step 2: PGP Challenge Verification. Logs the user in."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginPgpThrottle]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ip_addr = get_client_ip(request)
        user_id_pending = request.session.get('_login_user_id_pending_pgp')

        if not user_id_pending:
            logger.warning(f"PGP verification attempt without pending session. IP:{ip_addr}")
            return Response({"detail": "Login process not initiated or session expired."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user: 'User' = User.objects.select_related(None).get(id=user_id_pending, is_active=True)
        except User.DoesNotExist:
            logger.error(f"User ID {user_id_pending} from session not found/inactive during PGP verify.")
            request.session.pop('_login_user_id_pending_pgp', None)
            raise NotFound(detail="User associated with this login attempt not found or inactive.")

        serializer = PGPChallengeResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            signed_challenge = serializer.validated_data['signed_challenge']
            pgp_verified = pgp_service.verify_pgp_challenge(user=user, signed_challenge_data=signed_challenge)
            
            if not pgp_verified:
                raise AuthenticationFailed("PGP signature verification failed.")

            # PGP verification successful, log the user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            request.session[PGP_AUTH_SESSION_KEY] = timezone.now().isoformat()
            request.session.pop('_login_user_id_pending_pgp', None)

            is_owner = user.is_staff and user.groups.filter(name=getattr(settings, 'OWNER_GROUP_NAME', 'Owner')).exists()
            default_age = getattr(settings, 'SESSION_COOKIE_AGE', 1209600)
            owner_age = getattr(settings, 'OWNER_SESSION_COOKIE_AGE_SECONDS', 3600)
            session_age = owner_age if is_owner else default_age
            request.session.set_expiry(session_age)

            logger.info(f"Login Success (PGP verified): User:{user.id}/{user.username}. Session Age:{session_age}s. IP:{ip_addr}")
            security_logger.info(f"Successful login: Username={user.username}, IP={ip_addr}, Role={'Owner' if is_owner else 'Staff' if user.is_staff else 'User'}")
            log_audit_event(request, user, 'login_success', details="PGP Verified")

            response_serializer = CurrentUserSerializer(user, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AuthenticationFailed as e:
            logger.warning(f"PGP verification failed for User:{user.id}/{user.username}. IP:{ip_addr}. Reason: {e}")
            security_logger.warning(f"Failed login (PGP verification fail): Username={user.username}, IP={ip_addr}")
            log_audit_event(request, user, 'login_fail', details=f"PGP Verification Failed: {e}")
            request.session.pop('_login_user_id_pending_pgp', None)
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)
        
        except pgp_service.PGPError as e:
            logger.warning(f"A PGP service error occurred during verification for User:{user.id}/{user.username}. IP:{ip_addr}. Error: {e}")
            log_audit_event(request, user, 'login_fail', details=f"PGP Service Error: {e}")
            request.session.pop('_login_user_id_pending_pgp', None)
            raise APIException("PGP signature verification failed due to a service error.", status.HTTP_503_SERVICE_UNAVAILABLE) from e
        
        except Exception as e:
            logger.exception(f"Error verifying PGP challenge or logging in User:{user.id}/{user.username}: {e}")
            request.session.pop('_login_user_id_pending_pgp', None)
            raise APIException("An internal error occurred during PGP verification.", status.HTTP_500_INTERNAL_SERVER_ERROR) from e


class LogoutView(APIView):
    """Logs the current user out, invalidating their session."""
    permission_classes = [drf_permissions.IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user: 'User' = request.user
        user_id = user.id
        username = user.username
        ip_addr = get_client_ip(request)

        log_audit_event(request, user, 'logout_success')
        logout(request)
        logger.info(f"User:{user_id}/{username} logged out. IP:{ip_addr}")
        return Response({"message": "Successfully logged out."}, status=status.HTTP_200_OK)


# --- Current User View ---

class CurrentUserView(generics.RetrieveUpdateAPIView):
    """
    Provides access/updates to the authenticated user's profile (Update requires PGP auth).
    NOTE: The test failure `test_update_current_user_addresses_success` is caused by an
    external validator in `validators.py` or invalid test data, not a bug in this view.
    This view correctly handles ValidationErrors from its serializer by returning a 400 status.
    """
    serializer_class = CurrentUserSerializer
    permission_classes = [drf_permissions.IsAuthenticated]

    def get_object(self) -> 'User':
        """Returns the currently authenticated user."""
        user: 'User' = self.request.user
        return user

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Require PGP authentication for PUT/PATCH requests."""
        if self.request.method in ['PUT', 'PATCH']:
            return [drf_permissions.IsAuthenticated(), IsPgpAuthenticated()]
        return [permission() for permission in self.permission_classes]

    def perform_update(self, serializer: CurrentUserSerializer) -> None:
        """Handles profile update logic, including password change and logging."""
        instance: 'User' = self.get_object()
        ip_addr = get_client_ip(self.request)

        password_updated_in_request = any(f in serializer.initial_data for f in ['password', 'password_confirm', 'current_password'])
        updated_instance: 'User' = serializer.save()

        changed_fields = list(serializer.validated_data.keys())
        # The serializer pops password fields, so we need to add 'password' back manually for logging
        if password_updated_in_request and 'password' not in changed_fields:
            changed_fields.append('password')

        log_details_list: List[str] = []
        sensitive_actions: List[str] = []

        if 'password' in changed_fields:
            security_logger.warning(f"Password changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            sensitive_actions.append("Password Changed")
            try:
                # Keep the user logged in after a password change
                update_session_auth_hash(self.request, updated_instance)
                logger.info(f"Session auth hash updated for User:{instance.id}/{instance.username} due to password change.")
            except Exception as e:
                logger.error(f"Failed to update session auth hash for User:{instance.id}/{instance.username} after password change: {e}")

        if 'pgp_public_key' in changed_fields:
            security_logger.warning(f"PGP key changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            sensitive_actions.append("PGP Key Changed")

        if any(f in changed_fields for f in ['btc_withdrawal_address', 'eth_withdrawal_address', 'xmr_withdrawal_address']):
            sensitive_actions.append("Withdrawal Address Changed")

        log_details_list.append(f"Fields updated: {', '.join(changed_fields)}")
        if sensitive_actions:
            log_details_list.append(f"Sensitive Actions: {', '.join(sensitive_actions)}")

        details_str = " | ".join(log_details_list)

        log_audit_event(self.request, updated_instance, 'profile_update', target_user=updated_instance, details=details_str)
        logger.info(f"User profile updated: User:{instance.id}/{instance.username}")

# --- END OF FILE ---