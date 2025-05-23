# backend/store/views/auth.py
# Revision: 1.6 (Corrected Utils Import Path)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains authentication (Register, Login, Logout) and user profile (CurrentUser) views.
# Changes:
# - Rev 1.6:
#   - Corrected import path for helpers to use backend.store.utils.utils.
# - Rev 1.5:
#   - Updated imports to use get_client_ip and log_audit_event from backend.store.utils.
# - Rev 1.4:
#   - Removed local definitions of get_client_ip and log_audit_event.
#   - Imported get_client_ip and log_audit_event from .helpers (Incorrectly stated, was still local).
#   - Removed unused import HttpRequest.
# - Rev 1.3:
#   - Changed imports to absolute paths starting from 'backend' (e.g., `from backend.store.models`).
#   - Kept string literal type hint fixes (`'User'`).
# - Rev 1.0 (Split): Initial split.

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

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import (
    PermissionDenied, NotAuthenticated, NotFound, ValidationError as DRFValidationError,
    APIException
)
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User
# --- Import Serializers ---
from backend.store.serializers import UserPublicSerializer, CurrentUserSerializer
# --- Import Forms ---
from backend.store.forms import RegistrationForm, LoginForm, PGPChallengeResponseForm
# --- Import Permissions ---
from backend.store.permissions import IsPgpAuthenticated, PGP_AUTH_SESSION_KEY
# --- Import Services ---
from backend.store.services import pgp_service
# --- Import Utils (Refactored Helpers) --- # <<< CORRECTED IMPORT PATH >>>
from backend.store.utils.utils import get_client_ip, log_audit_event # <<< CORRECTED IMPORT PATH >>>

# --- Type Hinting Aliases ---
if TYPE_CHECKING:
    from backend.store.models import User # Ensure User type hint is available

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# --- Helper Functions ---
# <<< REMOVED LOCAL DEFINITIONS of get_client_ip and log_audit_event (Now imported from utils.utils) >>>


# --- Rate Limiting Throttles ---
# TODO: Consider moving these to a dedicated throttles.py
class LoginInitThrottle(ScopedRateThrottle): scope = 'login_init'
class LoginPgpThrottle(ScopedRateThrottle): scope = 'login_pgp'
class RegisterThrottle(ScopedRateThrottle): scope = 'register'

# --- Authentication Views ---

class RegisterView(generics.CreateAPIView):
    """Handles new user registration."""
    queryset = User.objects.all()
    permission_classes = [drf_permissions.AllowAny]
    serializer_class = UserPublicSerializer # Used for response on success
    throttle_classes = [RegisterThrottle] # Apply rate limiting

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        form = RegistrationForm(request.data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user: 'User' = form.save()
                    # Generate login phrase *after* user is saved and has an ID if needed
                    # Simple example:
                    login_phrase_base = f"{user.username[:5].lower()}-{secrets.token_hex(3)}"
                    user.login_phrase = f"Phrase-{secrets.token_hex(3)}-{login_phrase_base}"
                    # Ensure login phrase is unique if required by model constraints
                    # while User.objects.filter(login_phrase=user.login_phrase).exists():
                    #     user.login_phrase = f"Phrase-{secrets.token_hex(4)}-{login_phrase_base}"
                    user.save(update_fields=['login_phrase'])

                ip_addr = get_client_ip(request) # Uses imported helper
                logger.info(f"User registered: User:{user.id}/{user.username}, IP:{ip_addr}")
                security_logger.info(f"New user registration: Username={user.username}, IP={ip_addr}")
                log_audit_event(request, user, 'register_success', target_user=user) # Uses imported helper
                serializer = self.get_serializer(user)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            except IntegrityError as e:
                username_attempt = request.data.get('username', 'N/A')
                logger.warning(f"Registration integrity error for {username_attempt}: {e}")
                # Check specific constraint failure if DB backend provides details
                if 'UNIQUE constraint' in str(e) and ('username' in str(e) or 'auth_user_username_key' in str(e)):
                     raise DRFValidationError({"username": ["A user with that username already exists."]})
                elif 'login_phrase' in str(e): # Example if login_phrase needs unique constraint
                     logger.error(f"Login phrase collision during registration for {username_attempt}.")
                     raise APIException("A temporary registration issue occurred. Please try again.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
                else:
                     raise APIException("An internal database error occurred during registration.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                username_attempt = request.data.get('username', 'N/A')
                logger.exception(f"Error during user registration for {username_attempt}: {e}")
                raise APIException("An internal error occurred during registration.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            username_attempt = request.data.get('username', 'N/A')
            logger.warning(f"Registration failed for {username_attempt}: ValidationErrors={json.dumps(form.errors)}")
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginInitView(APIView):
    """Step 1: Password Verification. Generates a PGP challenge."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginInitThrottle]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        form = LoginForm(request.data)
        ip_addr = get_client_ip(request) # Uses imported helper

        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            # Use Django's authenticate which checks password and is_active
            user: Optional['User'] = authenticate(request, username=username, password=password)

            if user is not None: # authenticate returns None if creds wrong or user inactive
                if not user.pgp_public_key:
                    logger.warning(f"Login Step 1 failed for User:{user.id}/{username}: No PGP key configured.")
                    log_audit_event(request, user, 'login_fail', details="Login Step 1 Failed: No PGP Key") # Uses imported helper
                    raise DRFValidationError(
                        {"detail": "Login requires a PGP key configured on your profile."},
                        code='pgp_key_required'
                    )

                try:
                    challenge_text = pgp_service.generate_pgp_challenge(user)
                    if not challenge_text:
                        logger.error(f"PGP challenge generation returned empty for User:{user.id}/{username}.")
                        raise APIException("Failed to generate PGP challenge.", status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # Store pending user ID and challenge expiry in session
                    request.session['_login_user_id_pending_pgp'] = user.id
                    request.session.set_expiry(pgp_service.CHALLENGE_TIMEOUT_SECONDS)
                    logger.info(f"Login Step 1 OK for User:{user.id}/{user.username}. PGP challenge generated. IP:{ip_addr}")
                    return Response({
                        "message": "Credentials verified. Please sign the PGP challenge.",
                        "pgp_challenge": challenge_text,
                        "login_phrase": user.login_phrase or "Login phrase not set.",
                    }, status=status.HTTP_200_OK)

                except pgp_service.PGPError as e:
                    logger.exception(f"PGP service error generating challenge for User:{user.id}/{username}: {e}")
                    raise APIException(f"Failed to generate PGP challenge: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
                except Exception as e:
                    logger.exception(f"Unexpected error generating PGP challenge for User:{user.id}/{username}: {e}")
                    raise APIException("An internal error occurred during login initialization.", status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                # Authentication failed (wrong password or user inactive)
                logger.warning(f"Login Step 1 failed for username: {username} (Invalid credentials or inactive). IP:{ip_addr}")
                # Log audit event against the username if user exists but creds were wrong/inactive
                potential_user = User.objects.filter(username=username).first()
                if potential_user:
                    log_audit_event(request, potential_user, 'login_fail', details="Invalid credentials or inactive user") # Uses imported helper
                raise NotAuthenticated(detail="Invalid username or password.") # Generic message
        else:
            username_attempt = request.data.get('username', 'N/A')
            logger.warning(f"Login Step 1 failed: Invalid form data for {username_attempt}. Errors={json.dumps(form.errors)}")
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginPgpVerifyView(APIView):
    """Step 2: PGP Challenge Verification. Logs the user in."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginPgpThrottle]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ip_addr = get_client_ip(request) # Uses imported helper
        user_id_pending = request.session.get('_login_user_id_pending_pgp')

        if not user_id_pending:
            logger.warning(f"PGP verification attempt without pending session. IP:{ip_addr}")
            return Response({"detail": "Login process not initiated or session expired."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Ensure user exists and is active
            user: 'User' = User.objects.select_related(None).get(id=user_id_pending, is_active=True)
        except User.DoesNotExist:
            logger.error(f"User ID {user_id_pending} from session not found/inactive during PGP verify.")
            request.session.pop('_login_user_id_pending_pgp', None) # Clear invalid session data
            raise NotFound(detail="User associated with this login attempt not found or inactive.")

        form = PGPChallengeResponseForm(request.data)
        if form.is_valid():
            signed_challenge = form.cleaned_data['signed_challenge']
            try:
                pgp_verified = pgp_service.verify_pgp_challenge(user, signed_challenge)
                if not pgp_verified:
                    # Verification failed, raise specific error
                    raise pgp_service.PGPVerificationError("PGP signature verification failed.")

                # PGP Verified - Log the user in
                # Specify backend to avoid conflicts if multiple backends configured
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                # Set PGP authenticated timestamp in session
                request.session[PGP_AUTH_SESSION_KEY] = timezone.now().isoformat()
                # Clear the pending login marker
                request.session.pop('_login_user_id_pending_pgp', None)

                # Set session expiry based on role (Owner vs default)
                is_owner = user.is_staff and user.groups.filter(name=getattr(settings, 'OWNER_GROUP_NAME', 'Owner')).exists()
                default_age = getattr(settings, 'SESSION_COOKIE_AGE', 1209600) # Default Django setting
                owner_age = getattr(settings, 'OWNER_SESSION_COOKIE_AGE_SECONDS', 3600)
                session_age = owner_age if is_owner else default_age
                request.session.set_expiry(session_age)

                logger.info(f"Login Success (PGP verified): User:{user.id}/{user.username}. Session Age:{session_age}s. IP:{ip_addr}")
                security_logger.info(f"Successful login: Username={user.username}, IP={ip_addr}, Role={'Owner' if is_owner else 'Staff' if user.is_staff else 'User'}")
                log_audit_event(request, user, 'login_success', details="PGP Verified") # Uses imported helper

                # Return user data using appropriate serializer
                serializer = CurrentUserSerializer(user, context={'request': request})
                return Response(serializer.data, status=status.HTTP_200_OK)

            except pgp_service.PGPVerificationError as e:
                logger.warning(f"PGP verification failed for User:{user.id}/{user.username}. IP:{ip_addr}. Error: {e}")
                security_logger.warning(f"Failed login (PGP verification fail): Username={user.username}, IP={ip_addr}")
                log_audit_event(request, user, 'login_fail', details=f"PGP Verification Failed: {e}") # Uses imported helper
                request.session.pop('_login_user_id_pending_pgp', None) # Clear session on failure
                raise NotAuthenticated(detail=f"PGP signature verification failed: {e}")
            except Exception as e:
                logger.exception(f"Error verifying PGP challenge or logging in User:{user.id}/{user.username}: {e}")
                request.session.pop('_login_user_id_pending_pgp', None) # Clear session on error
                raise APIException("An internal error occurred during PGP verification.", status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.warning(f"PGP verification failed: Invalid form data for User:{user.id}/{user.username}. Errors={json.dumps(form.errors)}")
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    """Logs the current user out, invalidating their session."""
    permission_classes = [drf_permissions.IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user: 'User' = request.user
        user_id = user.id # Store before logout clears user
        username = user.username
        ip_addr = get_client_ip(request) # Uses imported helper

        log_audit_event(request, user, 'logout_success') # Uses imported helper
        logout(request) # Invalidates the session
        logger.info(f"User:{user_id}/{username} logged out. IP:{ip_addr}")
        return Response({"message": "Successfully logged out."}, status=status.HTTP_200_OK)


# --- Current User View ---

class CurrentUserView(generics.RetrieveUpdateAPIView):
    """Provides access/updates to the authenticated user's profile (Update requires PGP auth)."""
    serializer_class = CurrentUserSerializer
    permission_classes = [drf_permissions.IsAuthenticated]

    def get_object(self) -> 'User':
        """Returns the currently authenticated user."""
        # request.user is guaranteed to be authenticated due to permission_classes
        user: 'User' = self.request.user
        return user

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Require PGP authentication for PUT/PATCH requests."""
        if self.request.method in ['PUT', 'PATCH']:
            # Return instances of permission classes
            return [drf_permissions.IsAuthenticated(), IsPgpAuthenticated()]
        # For GET, just IsAuthenticated is needed (already checked by class attribute)
        return [permission() for permission in self.permission_classes]

    def perform_update(self, serializer: CurrentUserSerializer) -> None:
        """Handles profile update logic, including password change and logging."""
        instance: 'User' = self.get_object()
        ip_addr = get_client_ip(self.request) # Uses imported helper

        # Check if password fields were included in the request payload before validation
        # Note: serializer.validated_data won't contain write_only fields like 'current_password'
        password_updated_in_request = any(f in serializer.initial_data for f in ['password', 'password_confirm', 'current_password'])

        # Save the instance using the serializer (which handles password hashing via update method)
        updated_instance: 'User' = serializer.save()

        # --- Logging ---
        changed_fields = list(serializer.validated_data.keys()) # Fields that were valid and updated
        # Add password if it was part of the request (won't be in validated_data)
        if password_updated_in_request and 'password' not in changed_fields:
             changed_fields.append('password')

        log_details_list: List[str] = []
        sensitive_actions: List[str] = []

        if 'password' in changed_fields:
            security_logger.warning(f"Password changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            sensitive_actions.append("Password Changed")
            try:
                # Update session hash to prevent logout after password change
                update_session_auth_hash(self.request, updated_instance)
                logger.info(f"Session auth hash updated for User:{instance.id}/{instance.username} due to password change.")
            except Exception as e:
                logger.error(f"Failed to update session auth hash for User:{instance.id}/{instance.username} after password change: {e}")

        if 'pgp_public_key' in changed_fields:
            security_logger.warning(f"PGP key changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            sensitive_actions.append("PGP Key Changed")

        # Add other sensitive fields here if needed (e.g., withdrawal addresses)
        if any(f in changed_fields for f in ['btc_withdrawal_address', 'eth_withdrawal_address', 'xmr_withdrawal_address']):
             sensitive_actions.append("Withdrawal Address Changed")

        log_details_list.append(f"Fields updated: {', '.join(changed_fields)}")
        if sensitive_actions:
            log_details_list.append(f"Sensitive Actions: {', '.join(sensitive_actions)}")

        details_str = " | ".join(log_details_list)

        log_audit_event(self.request, updated_instance, 'profile_update', target_user=updated_instance, details=details_str) # Uses imported helper
        logger.info(f"User profile updated: User:{instance.id}/{instance.username}")

# --- END OF FILE ---