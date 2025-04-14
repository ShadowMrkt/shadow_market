# backend/store/views.py
# Revision: 4.3 (Corrected Permission Import)
# Date: 2025-04-13
# Author: Gemini
# Changes:
# - Rev 4.3:
#   - FIXED: Corrected permission import from IsTicketRequesterOrAssignee to IsTicketRequesterAssigneeOrStaff based on permissions.py definition.
# - Rev 4.2:
#   - FIXED: Corrected the import and usage of Vendor Application Status choices.
#     Removed import alias `VendorApplicationStatus as VendorApplicationStatusChoices`.
#     Updated references to use the correct nested class `VendorApplication.StatusChoices`.
# - Rev 4.1:
#   - FIXED: Corrected import location for IntegrityError (from django.db).
# - Rev 4:
#   - UPDATED: VendorApplicationCreateView:
#     - Removed bond currency selection logic (BTC only now).
#     - Changed address generation to use bitcoin_service exclusively.
#     - Corrected workflow: Save app first to get ID, then generate address, then import address with label, then update app with address.
#     - Updated related logging and error handling.
# - Rev 3 (2025-04-09): The Void
#   - ADDED: ExchangeRateView to expose current rates from GlobalSettings.
#   - ADDED: VendorApplicationCreateView for users to initiate vendor applications.
#   - ADDED: VendorApplicationStatusView for users to check their application status.
#   - Included necessary imports (permissions, models, serializers, services).
#   - Added basic logic for validation, bond calculation, address generation (conceptual), and saving.
# - Rev 2 (2025-04-07): The Void
#   - Applied global dark theme classes, used CSS Module for custom styles, used PGP constants.
# - Rev 1 (High Priority): The Void
#   - Refactored WithdrawalExecuteView.post atomicity (moved crypto call out).
#   - Added update_session_auth_hash call in CurrentUserView.perform_update.
#   - Applied improved service exception handling pattern (illustrated in examples).
#   - Applied improved PGP key availability check pattern (illustrated in examples).

# Standard Library Imports
import logging
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Tuple, Type, Union, TYPE_CHECKING

# Django Imports
from django.conf import settings
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError, ImproperlyConfigured
# from django.db import transaction # Imported below with IntegrityError
from django.db.models import Sum, Count, Q, Avg, F, Prefetch # <-- CORRECTED: Removed IntegrityError
from django.db import transaction, IntegrityError # <<<--- CORRECTED: Imported IntegrityError here ---<<<
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.module_loading import import_string

# Third-Party Imports
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, viewsets, status, permissions as drf_permissions
from rest_framework import filters as drf_filters
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied, NotAuthenticated, NotFound, ValidationError as DRFValidationError,
    APIException
)
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

# --- Local Imports ---
try:
    from notifications.services import create_notification
    # from notifications.tasks import send_notification_task # Use if async preferred
except ImportError:
    # Provide dummy functions if notifications app is optional/missing
    def create_notification(*args: Any, **kwargs: Any) -> None: pass
    # def send_notification_task(*args: Any, **kwargs: Any) -> None: pass

# --- Import Models ---
from .models import (
    User, Category, Product, Order, CryptoPayment, Feedback,
    SupportTicket, TicketMessage, GlobalSettings, AuditLog, WebAuthnCredential,
    VendorApplication, Currency, # <-- Added VendorApplication, Currency
    # Import constants directly for clarity (Ensure these exist in models.py or constants file)
    Order as OrderModel, # Use alias to access inner class below if needed, e.g. OrderModel.StatusChoices
    # No direct import for VendorApplicationStatus; use VendorApplication.StatusChoices
)
# Define OrderStatusChoices alias for clarity if preferred
OrderStatusChoices = OrderModel.StatusChoices

# --- Import Serializers ---
from .serializers import (
    UserPublicSerializer, CurrentUserSerializer, CategorySerializer, ProductSerializer,
    OrderBuyerSerializer, OrderVendorSerializer, FeedbackSerializer, CryptoPaymentSerializer,
    SupportTicketListSerializer, SupportTicketDetailSerializer, TicketMessageSerializer,
    VendorPublicProfileSerializer, EncryptCheckoutDataSerializer, CanarySerializer,
    WebAuthnCredentialSerializer, OrderBaseSerializer, # Added OrderBaseSerializer
    # ConceptualLoginInitSerializer # Add if refactoring auth views
    ExchangeRateSerializer, VendorApplicationSerializer # <-- Added new serializers
)
# --- Import Forms (Keep if Auth views not refactored) ---
from .forms import (
    RegistrationForm, LoginForm, PGPChallengeResponseForm
)
# --- Import Permissions ---
from .permissions import (
    IsAdminOrReadOnly, IsVendor, IsOwnerOrVendorReadOnly, IsPgpAuthenticated,
    IsBuyerOrVendorOfOrder,
    IsTicketRequesterAssigneeOrStaff, # <<<--- CORRECTED IMPORT NAME HERE ---<<<
    DenyAll, PGP_AUTH_SESSION_KEY
)
# --- Import Services ---
from .services import (
    pgp_service, escrow_service, reputation_service, webauthn_service,
    monero_service, bitcoin_service, ethereum_service,
    exchange_rate_service # <-- Added exchange_rate_service
)
from .services.escrow_service import get_market_user # Keep if used directly

# --- Import Filters ---
from .filters import ProductFilter

# --- Import Validators ---
from .validators import (
    validate_monero_address, validate_bitcoin_address, validate_ethereum_address,
    ValidationError as CustomValidationError
)
# --- Import Exceptions ---
from .exceptions import EscrowError, CryptoProcessingError # Assuming defined in exceptions.py


# --- Import Ledger Services ---
try:
    from ledger import services as ledger_service
    from ledger.models import TransactionTypeChoices # Example import path for constants
    from ledger.services import InsufficientFundsError, LedgerError, InvalidLedgerOperationError # Added missing imports
    from ledger.exceptions import LedgerError as LedgerExceptionBase # Alias if needed
except ImportError:
    logging.basicConfig() # Ensure logging is configured if import fails early
    logging.getLogger(__name__).critical("CRITICAL: 'ledger' application not found or failed to import. This is required.")
    raise ImproperlyConfigured("'ledger' application is missing or improperly configured.")


# --- Constants ---
MARKET_SUPPORT_PGP_KEY_SETTING: str = 'MARKET_SUPPORT_PGP_PUBLIC_KEY'
SUPPORTED_CURRENCIES_SETTING: str = 'SUPPORTED_CURRENCIES'
OWNER_SESSION_AGE_SETTING: str = 'OWNER_SESSION_COOKIE_AGE_SECONDS'
DEFAULT_SESSION_AGE_SETTING: str = 'DEFAULT_SESSION_COOKIE_AGE_SECONDS'
DEFAULT_PAGINATION_CLASS_SETTING: str = 'DEFAULT_PAGINATION_CLASS'
DEFAULT_THROTTLE_RATES_SETTING: str = 'DEFAULT_THROTTLE_RATES'


# --- Type Hinting Aliases ---
UserModel = User # Use the imported User model


# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security') # Use 'security' as defined in base settings logging

# --- Helper Functions ---
# (Keep get_client_ip and log_audit_event functions as they are)
def get_client_ip(request: Union[HttpRequest, Request]) -> Optional[str]:
    meta = getattr(request, 'META', {})
    x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = meta.get('REMOTE_ADDR')
    return ip

def log_audit_event(
    request: Union[HttpRequest, Request],
    actor: Optional[UserModel], # Actor might be None in some edge cases
    action: str, # Consider using an Enum here based on AuditLogAction choices
    target_user: Optional[UserModel] = None,
    target_order: Optional[Order] = None,
    target_ticket: Optional[SupportTicket] = None, # Added ticket
    target_product: Optional[Product] = None, # Added product
    target_application: Optional[VendorApplication] = None, # Added VendorApplication target
    details: str = ""
) -> None:
    """Helper function to create audit log entries reliably."""
    if actor and not isinstance(actor, User): # Check if actor exists and is the correct type
        actor_repr = getattr(actor, 'username', str(actor))
        logger.warning(f"Audit log attempted with invalid or missing actor: {actor_repr} ({type(actor)})")
        actor = None # Log as system/anonymous action

    try:
        ip_address = get_client_ip(request)
        AuditLog.objects.create(
            actor=actor,
            action=action, # TODO: Ensure 'action' aligns with AuditLogAction choices
            target_user=target_user,
            target_order=target_order,
            target_ticket=target_ticket, # Added
            target_product=target_product, # Added
            target_application=target_application, # Added VendorApplication target
            details=details[:500], # Limit details length
            ip_address=ip_address
        )
    except Exception as e:
        actor_username = getattr(actor, 'username', 'System/Anon')
        logger.error(f"Failed to create audit log entry (Action: {action}, Actor: {actor_username}): {e}", exc_info=True)


# --- Authentication Views (Example using Forms) ---
# NOTE: Consider refactoring using DRF Serializers (Priority 14) for consistency

# --- Rate Limiting Throttles (Apply these to relevant views) ---
class LoginInitThrottle(ScopedRateThrottle): scope = 'login_init'
class LoginPgpThrottle(ScopedRateThrottle): scope = 'login_pgp'
class RegisterThrottle(ScopedRateThrottle): scope = 'register'
# Define other scopes as needed (e.g., PGPActionThrottle, WithdrawalPrepareThrottle...)

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
                    user: UserModel = form.save()
                    # Generate login phrase securely
                    user.login_phrase = f"Phrase-{secrets.token_hex(3)}-{user.username[:5].lower()}-{secrets.token_hex(3)}"
                    user.save(update_fields=['login_phrase'])

                ip_addr = get_client_ip(request)
                logger.info(f"User registered: User:{user.id}/{user.username}, IP:{ip_addr}")
                security_logger.info(f"New user registration: Username={user.username}, IP={ip_addr}")
                # Ensure action string matches AuditLogAction choices
                log_audit_event(request, user, 'register_success', target_user=user) # TODO: Verify 'register_success' action choice
                serializer = self.get_serializer(user)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

            except Exception as e:
                username_attempt = request.data.get('username', 'N/A')
                logger.exception(f"Error during user registration for {username_attempt}: {e}")
                # Use DRF exception for consistent error response
                raise APIException("An internal error occurred during registration.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            username_attempt = request.data.get('username', 'N/A')
            logger.warning(f"Registration failed for {username_attempt}: ValidationErrors={json.dumps(form.errors)}")
            # DRFValidationError is automatically raised by is_valid if using serializers
            # With forms, return the errors manually in a standard DRF format
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginInitView(APIView):
    """Step 1: Password Verification. Generates a PGP challenge."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginInitThrottle] # Apply rate limiting

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        form = LoginForm(request.data)
        ip_addr = get_client_ip(request)

        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password'] # noqa S105 - variable name is clear
            # Use request context for authentication backend flexibility
            user: Optional[UserModel] = authenticate(request, username=username, password=password)

            if user is not None and user.is_active:
                # --- PGP Key Check ---
                if not user.pgp_public_key:
                    logger.warning(f"Login Step 1 failed for User:{user.id}/{username}: No PGP key configured.")
                    log_audit_event(request, user, 'login_fail', details="Login Step 1 Failed: No PGP Key") # TODO: Verify action choice
                    # Raise specific error for missing PGP key
                    raise DRFValidationError(
                        {"detail": "Login requires a PGP key configured on your profile."},
                        code='pgp_key_required'
                    )
                # --- End Check ---

                try:
                    challenge_text = pgp_service.generate_pgp_challenge(user)
                    if not challenge_text: # Service should ideally raise exception
                        logger.error(f"PGP challenge generation returned empty for User:{user.id}/{username}.")
                        raise APIException("Failed to generate PGP challenge.", status.HTTP_500_INTERNAL_SERVER_ERROR)

                    request.session['_login_user_id_pending_pgp'] = user.id
                    request.session.set_expiry(pgp_service.CHALLENGE_TIMEOUT_SECONDS) # Use constant from service
                    logger.info(f"Login Step 1 OK for User:{user.id}/{user.username}. PGP challenge generated. IP:{ip_addr}")
                    return Response({
                        "message": "Credentials verified. Please sign the PGP challenge.",
                        "pgp_challenge": challenge_text,
                        "login_phrase": user.login_phrase or "Login phrase not set.",
                    }, status=status.HTTP_200_OK)

                except pgp_service.PGPError as e: # Catch specific PGP service errors
                    logger.exception(f"PGP service error generating challenge for User:{user.id}/{username}: {e}")
                    raise APIException(f"Failed to generate PGP challenge: {e}", status.HTTP_500_INTERNAL_SERVER_ERROR)
                except Exception as e:
                    # Catch other unexpected errors from PGP service
                    logger.exception(f"Unexpected error generating PGP challenge for User:{user.id}/{username}: {e}")
                    raise APIException("An internal error occurred during login initialization.", status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                # Authentication failed or user inactive
                logger.warning(f"Login Step 1 failed for username: {username} (Invalid credentials or inactive). IP:{ip_addr}")
                # Log audit for failed attempt if user exists
                potential_user = User.objects.filter(username=username).first()
                if potential_user:
                    log_audit_event(request, potential_user, 'login_fail', details="Invalid credentials or inactive user") # TODO: Verify action choice
                raise NotAuthenticated(detail="Invalid username or password.") # Consistent 401
        else:
            username_attempt = request.data.get('username', 'N/A')
            logger.warning(f"Login Step 1 failed: Invalid form data for {username_attempt}. Errors={json.dumps(form.errors)}")
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginPgpVerifyView(APIView):
    """Step 2: PGP Challenge Verification. Logs the user in."""
    permission_classes = [drf_permissions.AllowAny]
    throttle_classes = [LoginPgpThrottle] # Apply rate limiting

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ip_addr = get_client_ip(request)
        user_id_pending = request.session.get('_login_user_id_pending_pgp')

        if not user_id_pending:
            logger.warning(f"PGP verification attempt without pending session. IP:{ip_addr}")
            return Response({"detail": "Login process not initiated or session expired."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Use select_related if accessing related fields (like groups)
            user: UserModel = User.objects.select_related(None).get(id=user_id_pending, is_active=True)
        except User.DoesNotExist:
            logger.error(f"User ID {user_id_pending} from session not found/inactive during PGP verify.")
            request.session.pop('_login_user_id_pending_pgp', None)
            # Use NotFound for clarity, though 400 could also work
            raise NotFound(detail="User associated with this login attempt not found or inactive.")

        form = PGPChallengeResponseForm(request.data)
        if form.is_valid():
            signed_challenge = form.cleaned_data['signed_challenge']
            try:
                # Service should raise exception on failure
                pgp_verified = pgp_service.verify_pgp_challenge(user, signed_challenge)
                if not pgp_verified: # Should ideally be caught by exception from service
                    raise pgp_service.PGPVerificationError("PGP signature verification failed.")

                # --- Login Success ---
                # User is already guaranteed active from initial query
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                request.session[PGP_AUTH_SESSION_KEY] = timezone.now().isoformat()
                request.session.pop('_login_user_id_pending_pgp', None)

                is_owner = user.is_staff and user.groups.filter(name='Owner').exists() # TODO: Use constant for group name
                default_age = getattr(settings, DEFAULT_SESSION_AGE_SETTING, 1209600) # 2 weeks
                owner_age = getattr(settings, OWNER_SESSION_AGE_SETTING, 3600) # 1 hour
                session_age = owner_age if is_owner else default_age
                request.session.set_expiry(session_age)
                # NOTE: Consider request.session.cycle_key() here for added security

                logger.info(f"Login Success (PGP verified): User:{user.id}/{user.username}. Session Age:{session_age}s. IP:{ip_addr}")
                security_logger.info(f"Successful login: Username={user.username}, IP={ip_addr}, Role={'Owner' if is_owner else 'User'}")
                log_audit_event(request, user, 'login_success', details="PGP Verified") # TODO: Verify action choice

                serializer = CurrentUserSerializer(user, context={'request': request})
                return Response(serializer.data, status=status.HTTP_200_OK)

            except pgp_service.PGPVerificationError as e: # Catch specific PGP error
                logger.warning(f"PGP verification failed for User:{user.id}/{user.username}. IP:{ip_addr}. Error: {e}")
                security_logger.warning(f"Failed login (PGP verification fail): Username={user.username}, IP={ip_addr}")
                log_audit_event(request, user, 'login_fail', details=f"PGP Verification Failed: {e}") # TODO: Verify action choice
                request.session.pop('_login_user_id_pending_pgp', None)
                raise NotAuthenticated(detail=f"PGP signature verification failed: {e}") # 401
            except Exception as e:
                # Catch unexpected errors during verification/login
                logger.exception(f"Error verifying PGP challenge or logging in User:{user.id}/{user.username}: {e}")
                request.session.pop('_login_user_id_pending_pgp', None)
                raise APIException("An internal error occurred during PGP verification.", status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            logger.warning(f"PGP verification failed: Invalid form data for User:{user.id}/{user.username}. Errors={json.dumps(form.errors)}")
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    """Logs the current user out, invalidating their session."""
    permission_classes = [drf_permissions.IsAuthenticated]
    # No specific rate limit needed unless logout is abused

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user: UserModel = request.user
        user_id = user.id
        username = user.username
        ip_addr = get_client_ip(request)

        log_audit_event(request, user, 'logout_success') # TODO: Verify action choice
        logout(request) # Invalidates session
        logger.info(f"User:{user_id}/{username} logged out. IP:{ip_addr}")
        return Response({"message": "Successfully logged out."}, status=status.HTTP_200_OK)


# --- Current User View ---

# Define throttle scope if needed (e.g., for profile updates)
# class PGPActionThrottle(ScopedRateThrottle): scope = 'pgp_action'

class CurrentUserView(generics.RetrieveUpdateAPIView):
    """Provides access/updates to the authenticated user's profile (Update requires PGP auth)."""
    serializer_class = CurrentUserSerializer
    permission_classes = [drf_permissions.IsAuthenticated]
    # Apply stricter throttle for updates?
    # throttle_classes = [PGPActionThrottle] # Apply if updates are sensitive/frequent

    def get_object(self) -> UserModel:
        """Returns the user associated with the current request."""
        # Type hint ensures return type is User
        user: UserModel = self.request.user
        return user

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Require PGP authentication for PUT/PATCH requests."""
        if self.request.method in ['PUT', 'PATCH']:
            # Instantiate permission classes
            return [drf_permissions.IsAuthenticated(), IsPgpAuthenticated()]
        # Use list comprehension to instantiate for GET
        return [permission() for permission in self.permission_classes]

    def perform_update(self, serializer: CurrentUserSerializer) -> None:
        """
        Saves updated profile, logs changes, invalidates sessions if password changed.
        """
        instance: UserModel = self.get_object() # Get instance before save for comparison if needed
        ip_addr = get_client_ip(self.request)
        # Use initial_data to accurately detect if password fields were sent
        password_updated_in_request = any(f in serializer.initial_data for f in ['password', 'password_confirm', 'current_password'])

        # Serializer's update method handles saving the instance and password hashing
        updated_instance: UserModel = serializer.save()

        # --- Log Changes ---
        log_details: List[str] = []
        changed_fields_in_request = list(serializer.initial_data.keys())

        if password_updated_in_request:
            security_logger.warning(f"Password changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            log_details.append("Password Changed")
            # --- CRITICAL: Invalidate other sessions on password change ---
            try:
                update_session_auth_hash(self.request, updated_instance)
                logger.info(f"Session auth hash updated for User:{instance.id}/{instance.username} due to password change.")
            except Exception as e:
                # Log error if session update fails, but don't fail the main request
                logger.error(f"Failed to update session auth hash for User:{instance.id}/{instance.username} after password change: {e}")
            # --- End Session Invalidation ---

        if 'pgp_public_key' in changed_fields_in_request:
            security_logger.warning(f"PGP key changed: User:{instance.id}/{instance.username}, IP:{ip_addr}")
            log_details.append("PGP Key Changed")

        details_str = f"Updated fields in request: {', '.join(changed_fields_in_request)}"
        if log_details:
            details_str += f" (Sensitive Actions: {', '.join(log_details)})"

        log_audit_event(self.request, updated_instance, 'profile_update', target_user=updated_instance, details=details_str) # TODO: Verify action choice
        logger.info(f"User profile updated: User:{instance.id}/{instance.username}")


# --- Utility Views ---

class HealthCheckView(APIView):
    """Simple health check endpoint, checks DB and Cache."""
    permission_classes = [drf_permissions.AllowAny]
    # No rate limiting typically needed

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dependencies_status: Dict[str, str] = {}
        overall_ok = True

        # Check DB
        try:
            from django.db import connection
            connection.ensure_connection()
            dependencies_status["database"] = "ok"
        except Exception as e:
            dependencies_status["database"] = "error"
            overall_ok = False
            logger.error(f"Health Check: Database connection failed: {e}")

        # Check Cache
        try:
            cache_key = f"health_check_{secrets.token_hex(8)}"
            cache.set(cache_key, 'ok', timeout=5)
            if cache.get(cache_key) == 'ok':
                dependencies_status["cache"] = "ok"
                cache.delete(cache_key)
            else:
                raise Exception("Cache set/get failed verification.")
        except Exception as e:
            dependencies_status["cache"] = "error"
            overall_ok = False
            logger.error(f"Health Check: Cache connection failed: {e}")

        # Check Ledger Service (if critical)
        if ledger_service is None:
            dependencies_status["ledger_service"] = "error"
            overall_ok = False
            logger.error("Health Check: Ledger service unavailable.")
        else:
            # Optional: Add a lightweight ping method to ledger_service if possible
            dependencies_status["ledger_service"] = "ok" # Assuming ok if import succeeded

        # Add other critical service checks (PGP backend?, Crypto nodes?)

        status_code = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({
            "status": "ok" if overall_ok else "error",
            "timestamp": timezone.now().isoformat(),
            "dependencies": dependencies_status
        }, status=status_code)


# Define throttle scope if needed
# class PGPActionThrottle(ScopedRateThrottle): scope = 'pgp_action'

class EncryptForVendorView(APIView):
    """Encrypts checkout data for a vendor using their PGP key, or accepts pre-encrypted blob."""
    permission_classes = [drf_permissions.IsAuthenticated, IsPgpAuthenticated]
    serializer_class = EncryptCheckoutDataSerializer
    # throttle_classes = [PGPActionThrottle] # Apply PGP action throttle

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Serializer validates input structure, vendor existence, and PGP key presence if needed.
        serializer = self.serializer_class(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
        except DRFValidationError as e:
            # Log validation errors with user context
            logger.warning(f"EncryptForVendor validation failed for User:{request.user.id}/{request.user.username}. Errors: {e.detail}")
            raise e # Re-raise for DRF standard response

        validated_data = serializer.validated_data
        vendor: UserModel = validated_data['vendor_id'] # Serializer ensures this is a valid User instance

        shipping_data = validated_data.get('shipping_data')
        buyer_message = validated_data.get('buyer_message', '').strip()
        pre_encrypted_blob = validated_data.get('pre_encrypted_blob')

        final_encrypted_blob: Optional[str] = None
        was_pre_encrypted: bool = False

        needs_server_encryption = bool(shipping_data or buyer_message) and not pre_encrypted_blob

        if needs_server_encryption:
            # Serializer already validated that vendor has a PGP key.
            vendor_pgp_key = vendor.pgp_public_key
            if not vendor_pgp_key: # Double-check for safety
                logger.error(f"Vendor {vendor.id}/{vendor.username} missing PGP key unexpectedly.")
                raise APIException("Cannot encrypt data: Vendor PGP key is missing.", code=status.HTTP_400_BAD_REQUEST)

            data_to_encrypt: Dict[str, Any] = {}
            if shipping_data: data_to_encrypt['address'] = shipping_data
            if buyer_message: data_to_encrypt['message'] = buyer_message

            # This check should be redundant if serializer validation is correct
            if not data_to_encrypt:
                logger.error(f"Internal logic error: No data to encrypt despite validation. User:{request.user.id}, Vendor:{vendor.id}")
                raise APIException("No data provided for encryption.", code=status.HTTP_400_BAD_REQUEST)

            try:
                # Use compact separators, sort keys for deterministic output if needed
                data_json = json.dumps(data_to_encrypt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                # Service should raise exception on failure
                encrypted_blob_result = pgp_service.encrypt_message_for_recipient(
                    message=data_json, recipient_public_key=vendor_pgp_key
                )
                if not encrypted_blob_result: # Defensive check if service doesn't raise
                    raise pgp_service.PGPEncryptionError("Encryption returned empty result.")

                final_encrypted_blob = encrypted_blob_result
                was_pre_encrypted = False
                logger.info(f"Checkout data encrypted for V:{vendor.id}/{vendor.username} by U:{request.user.id}/{request.user.username}.")

            except pgp_service.PGPError as e: # Catch specific service error
                logger.error(f"PGP encryption failed for V:{vendor.id}/{vendor.username} by U:{request.user.id}/{request.user.username}: {e}")
                raise APIException(f"Server-side PGP encryption failed: {e}", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e: # Catch JSON errors or unexpected PGP errors
                logger.exception(f"Error during PGP encryption preparation for V:{vendor.id}/{vendor.username}: {e}")
                raise APIException("Server-side PGP encryption failed.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        elif pre_encrypted_blob:
            # Serializer validated basic blob format. Use the blob.
            final_encrypted_blob = str(pre_encrypted_blob).strip()
            was_pre_encrypted = True
            logger.info(f"Using pre-encrypted blob provided by U:{request.user.id}/{request.user.username} for V:{vendor.id}/{vendor.username}.")
        else:
            # Should be caught by serializer validation
            logger.error(f"Invalid state in EncryptForVendorView (no data/blob) for U:{request.user.id}")
            raise APIException("Internal processing error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "encrypted_blob": final_encrypted_blob,
            "was_pre_encrypted": was_pre_encrypted
        }, status=status.HTTP_200_OK)


# --- Vendor Views ---

class VendorPublicProfileView(generics.RetrieveAPIView):
    """Displays a vendor's public profile information."""
    # Queryset filters for active vendors
    queryset = User.objects.filter(is_vendor=True, is_active=True)
    serializer_class = VendorPublicProfileSerializer
    permission_classes = [drf_permissions.AllowAny]
    lookup_field = 'username'
    lookup_url_kwarg = 'username'
    # No rate limiting typically needed

class VendorStatsView(APIView):
    """Provides aggregated statistics for the requesting vendor (Requires Vendor & PGP Auth)."""
    permission_classes = [drf_permissions.IsAuthenticated, IsVendor, IsPgpAuthenticated]
    # throttle_classes = [PGPActionThrottle] # Apply PGP action throttle

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vendor: UserModel = request.user # Permissions ensure user is a vendor

        try:
            # Active Listings Count
            active_listings_count = Product.objects.filter(vendor=vendor, is_active=True).count()

            # Sales Counts by Status
            # Use constants imported from models (OrderStatusChoices)
            pending_statuses = [OrderStatusChoices.PAYMENT_CONFIRMED, OrderStatusChoices.SHIPPED]
            sales_pending_action_count = Order.objects.filter(vendor=vendor, status__in=pending_statuses).count()
            sales_completed_count = Order.objects.filter(vendor=vendor, status=OrderStatusChoices.FINALIZED).count()
            disputes_open_count = Order.objects.filter(vendor=vendor, status=OrderStatusChoices.DISPUTED).count()

            # Total Revenue per Currency (Finalized Orders)
            revenue_data = Order.objects.filter(
                vendor=vendor, status=OrderStatusChoices.FINALIZED
            ).values('selected_currency').annotate(
                total_revenue=Sum('total_price_native_selected')
            ).order_by('selected_currency')

            total_revenue_by_currency: Dict[str, Optional[Decimal]] = {
                item['selected_currency']: item['total_revenue']
                for item in revenue_data if item['selected_currency'] # Ensure currency is not null/empty
                # Note: Sum might return None if no orders exist for a currency, handled below
            }

            # Average Rating and Feedback Count
            feedback_agg = Feedback.objects.filter(recipient=vendor).aggregate(
                average_rating=Avg('rating'),
                feedback_count=Count('id')
            )
            avg_rating: Optional[Decimal] = feedback_agg.get('average_rating')
            feedback_count: int = feedback_agg.get('feedback_count', 0)

            # Compile Stats Data (Format Decimals safely)
            stats_data = {
                'active_listings_count': active_listings_count,
                'sales_pending_action_count': sales_pending_action_count,
                'sales_completed_count': sales_completed_count,
                'disputes_open_count': disputes_open_count,
                'total_revenue_by_currency': { # Ensure Decimal amounts are serialized correctly if needed
                    curr: f"{total:.8f}" if total is not None else "0.00" # Example formatting, adjust precision
                    for curr, total in total_revenue_by_currency.items()
                },
                'average_rating': f"{avg_rating:.2f}" if avg_rating is not None else None,
                'feedback_count': feedback_count,
                'username': vendor.username,
                'joined_date': vendor.date_joined.date().isoformat() if vendor.date_joined else None,
            }
            logger.info(f"Fetched stats for Vendor:{vendor.id}/{vendor.username}")
            return Response(stats_data)

        except Exception as e:
            # Catch unexpected errors during aggregation
            logger.exception(f"Error fetching stats for Vendor:{vendor.id}/{vendor.username}: {e}")
            raise APIException("Failed to retrieve vendor statistics.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- Product Views ---

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Provides read-only access to active product categories."""
    # Optimize: Prefetch children for potential hierarchical display
    queryset = Category.objects.filter(
        parent__isnull=True #, is_active=True # Assuming Category has no is_active field based on models.py
    ).prefetch_related('children') # Assuming 'children' is the related_name
    serializer_class = CategorySerializer
    permission_classes = [drf_permissions.AllowAny]
    lookup_field = 'slug'
    pagination_class = None # No pagination for categories usually


class ProductViewSet(viewsets.ModelViewSet):
    """Manages products (listings)."""
    # Base queryset with optimizations needed by ProductSerializer
    queryset = Product.objects.select_related(
        'vendor', 'category'
    ).filter(
        vendor__is_active=True # Only show products from active vendors by default
    )
    serializer_class = ProductSerializer
    lookup_field = 'slug'
    permission_classes = [drf_permissions.IsAuthenticatedOrReadOnly] # Base permission
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'vendor__username', 'category__name']
    ordering_fields = ['created_at', 'updated_at', 'price_xmr', 'price_btc', 'price_eth', 'average_rating', 'sales_count', 'name']
    ordering = ['-created_at']
    # Add appropriate throttling (e.g., UserRateThrottle, AnonRateThrottle)
    # throttle_classes = [...]

    def get_queryset(self) -> 'QuerySet[Product]': # Type hint for return
        """Filter queryset based on user role and apply optimizations."""
        # Start with the class queryset which includes select_related
        queryset = self.queryset.all()
        user: Optional[UserModel] = getattr(self.request, 'user', None) # Handle AnonymousUser

        is_staff = getattr(user, 'is_staff', False)
        # Allow staff to request inactive products via query parameter
        show_inactive = is_staff and self.request.query_params.get('include_inactive') == 'true'

        if self.action == 'list' and not show_inactive:
            # Default list view only shows active products
            queryset = queryset.filter(is_active=True)
        elif self.action != 'list' and not is_staff:
            # Detail views for non-staff require product to be active
            # (Owner check happens in permissions)
            queryset = queryset.filter(is_active=True)

        # Example custom action for vendor's own products
        # if self.action == 'my_products':
        #     if user and user.is_authenticated and getattr(user, 'is_vendor', False):
        #         queryset = queryset.filter(vendor=user)
        #     else: # Return empty if not authenticated vendor
        #         queryset = queryset.none()

        # No additional prefetch needed typically for ProductSerializer unless it accesses m2m deeply
        return queryset

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Set permissions dynamically based on the action."""
        # Instantiate permission classes
        if self.action in ['list', 'retrieve']:
            permission_classes = [drf_permissions.AllowAny]
        elif self.action == 'create':
            # Only PGP-authenticated vendors can create
            permission_classes = [drf_permissions.IsAuthenticated, IsVendor, IsPgpAuthenticated]
        elif self.action in ['update', 'partial_update', 'destroy']:
            # Owner (vendor) or Admin/Staff can modify/delete, PGP required for sensitive changes.
            # IsOwnerOrVendorReadOnly ensures only owner/staff can write.
            # IsPgpAuthenticated ensures secure session for modification.
            permission_classes = [drf_permissions.IsAuthenticated, IsOwnerOrVendorReadOnly, IsPgpAuthenticated]
        else:
            # Default deny or admin only for custom actions (like 'my_products' if added)
            permission_classes = [drf_permissions.IsAdminUser] # Stricter default
        return [permission() for permission in permission_classes]

    def perform_create(self, serializer: ProductSerializer) -> None:
        """Set the vendor to the current user upon product creation and log."""
        user: UserModel = self.request.user
        ip_addr = get_client_ip(self.request)
        try:
            # Serializer validated data, vendor=user ensures ownership
            instance: Product = serializer.save(vendor=user)
            logger.info(f"Product created: ID:{instance.id}, Name='{instance.name}', Vendor:{user.id}/{user.username}, IP:{ip_addr}")
            security_logger.info(f"Product created: ID={instance.id}, Name='{instance.name}', Vendor={user.username}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_create', target_product=instance, details=f"P:{instance.name}") # TODO: Verify action choice
        except Exception as e:
            # Catch potential DB errors during save
            logger.exception(f"Error saving new product for Vendor:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_update(self, serializer: ProductSerializer) -> None:
        """Log product updates."""
        user: UserModel = self.request.user
        ip_addr = get_client_ip(self.request)
        try:
            instance: Product = serializer.save()
            changed_fields = list(serializer.validated_data.keys()) # Fields included in PATCH/PUT
            logger.info(f"Product updated: ID:{instance.id}, Name='{instance.name}', By:{user.id}/{user.username}, Fields:{changed_fields}, IP:{ip_addr}")
            security_logger.info(f"Product updated: ID={instance.id}, Name='{instance.name}', By={user.username}, Fields={changed_fields}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_update', target_product=instance, details=f"Fields:{','.join(changed_fields)}") # TODO: Verify action choice
        except Exception as e:
            logger.exception(f"Error updating product ID:{serializer.instance.id} for User:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product update due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_destroy(self, instance: Product) -> None:
        """Log product deletion before deleting."""
        user: UserModel = self.request.user
        ip_addr = get_client_ip(self.request)
        product_id = instance.id
        product_name = instance.name
        vendor_username = instance.vendor.username

        # Log before deletion attempt
        logger.warning(f"Product DELETE initiated: ID:{product_id}, Name='{product_name}', Vendor={vendor_username}, By:{user.id}/{user.username}, IP:{ip_addr}")
        security_logger.warning(f"Product DELETE initiated: ID={product_id}, Name='{product_name}', Vendor={vendor_username}, By={user.username}, IP={ip_addr}")
        log_audit_event(self.request, user, 'product_delete_attempt', target_product=instance, details=f"P:{product_name}") # TODO: Verify action choice

        try:
            instance.delete()
            logger.info(f"Product deleted successfully: ID:{product_id}, Name='{product_name}', By:{user.id}/{user.username}")
            # No separate audit log for success needed if attempt is logged and delete succeeds
        except Exception as e:
            # Catch potential DB errors during delete (e.g., protected relations)
            logger.exception(f"Error deleting product ID:{product_id} for User:{user.id}/{user.username}: {e}")
            log_audit_event(self.request, user, 'product_delete_fail', target_product=instance, details=f"P:{product_name}, Error:{e}") # TODO: Verify action choice
            raise APIException("Failed to delete product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- Order Views ---

# Define throttle scope if needed
# class PlaceOrderThrottle(ScopedRateThrottle): scope = 'place_order' # Example

class PlaceOrderView(generics.CreateAPIView):
    """Handles the creation of a new order by a buyer (Requires PGP Auth)."""
    permission_classes = [drf_permissions.IsAuthenticated, IsPgpAuthenticated]
    serializer_class = OrderBuyerSerializer # Serializer for the response
    # throttle_classes = [PlaceOrderThrottle] # Apply rate limiting

    # --- Helper methods for validation (can be moved to a separate validation module/service) ---
    def _validate_request_data(self, data: Dict[str, Any]) -> Tuple[int, int, str, Optional[str], Optional[str]]:
        """ Validate basic incoming request data fields. Returns validated data or raises DRFValidationError. """
        product_id_str = data.get('product_id')
        quantity_str = data.get('quantity', '1') # Default quantity to 1
        selected_currency = data.get('selected_currency')
        shipping_option_name = data.get('shipping_option_name') # Optional, checked later
        encrypted_shipping_blob = data.get('encrypted_shipping_blob') # Optional, checked later

        errors: Dict[str, List[str]] = {}
        if not product_id_str: errors.setdefault('product_id', []).append("This field is required.")
        if not selected_currency: errors.setdefault('selected_currency', []).append("This field is required.")

        product_id: Optional[int] = None
        quantity: int = 1 # Default

        try:
            if product_id_str: product_id = int(product_id_str)
        except (ValueError, TypeError):
            errors.setdefault('product_id', []).append("Invalid product ID format.")

        try:
            quantity = int(quantity_str)
            if quantity < 1:
                errors.setdefault('quantity', []).append("Quantity must be at least 1.")
        except (ValueError, TypeError):
            errors.setdefault('quantity', []).append("Invalid quantity provided.")

        # Basic currency format check (adjust if supporting non-standard codes)
        if selected_currency and (not isinstance(selected_currency, str) or len(selected_currency) > 10 or not selected_currency.isalpha()):
            errors.setdefault('selected_currency', []).append("Invalid currency format.")

        if errors:
            raise DRFValidationError(errors)

        # Ensure product_id was validated
        if product_id is None:
            # This case should be caught by required field check, but defensive programming
            raise DRFValidationError({"product_id": "Product ID is required and must be valid."})


        return product_id, quantity, str(selected_currency).upper(), shipping_option_name, encrypted_shipping_blob

    def _validate_product_and_options(
        self, user: UserModel, product: Product, quantity: int, selected_currency: str,
        shipping_option_name: Optional[str], encrypted_shipping_blob: Optional[str]
    ) -> Tuple[Decimal, Optional[Dict[str, Any]], Decimal]:
        """ Validate product rules, stock, currency, shipping. Returns (price_native, shipping_option_dict, shipping_price_native) or raises DRFValidationError/NotFound. """

        if not product.is_active:
            raise NotFound(detail="The requested product is not active or available.")

        if product.vendor == user:
            raise DRFValidationError({"detail": "You cannot place an order for your own product."})

        # Check Stock (handle None quantity for unlimited)
        # Assume product.quantity is PositiveIntegerField, None means unlimited? Model needs clarity.
        # For now, assume PositiveIntegerField means >= 1 required.
        if product.quantity is not None and quantity > product.quantity:
            raise DRFValidationError({"quantity": f"Insufficient stock. Only {product.quantity} available."})

        # Check Currency Acceptance (using method assumed on Product model)
        accepted_currencies = getattr(product, 'get_accepted_currencies_list', lambda: [])()
        if selected_currency not in accepted_currencies:
            raise DRFValidationError({"selected_currency": f"The currency '{selected_currency}' is not accepted for this product. Accepted: {', '.join(accepted_currencies)}"})

        # Get Product Price (using method assumed on Product model)
        # price_native refers to ATOMIC units as per model field names/comments
        price_native = getattr(product, 'get_price', lambda curr: None)(selected_currency)
        if price_native is None:
            logger.error(f"Price configuration error for Product:{product.id}, Currency:{selected_currency}")
            raise DRFValidationError({"selected_currency": f"Price is not configured for '{selected_currency}' on this product."})
        try:
            # Ensure price is a valid Decimal
            price_native = Decimal(str(price_native))
            if price_native < Decimal('0.0'): raise ValueError("Price cannot be negative")
        except (InvalidOperation, TypeError, ValueError):
            logger.error(f"Invalid price value configured for Product:{product.id}, Currency:{selected_currency}, Value:'{price_native}'")
            raise DRFValidationError({"detail": "Internal error: Invalid product price configured."})


        # Handle Shipping for Physical Products
        shipping_option_details: Optional[Dict[str, Any]] = None
        shipping_price_native = Decimal('0.0') # ATOMIC units

        # Check if product requires shipping (using model method)
        requires_shipping = getattr(product, 'is_physical', lambda: False)() # Use model method

        if requires_shipping:
            if not encrypted_shipping_blob:
                raise DRFValidationError({"encrypted_shipping_blob": "Encrypted shipping information is required for physical products."})
            if not shipping_option_name:
                raise DRFValidationError({"shipping_option_name": "A shipping option must be selected for physical products."})

            # Find selected shipping option from product's definition (assuming JSON field)
            options = product.shipping_options or []
            if not isinstance(options, list):
                logger.error(f"Invalid shipping_options format for Product:{product.id} (not a list).")
                raise APIException("Internal error: Invalid shipping configuration.")

            found_option = None
            for opt in options:
                if isinstance(opt, dict) and opt.get('name') == shipping_option_name:
                    found_option = opt
                    break

            if not found_option:
                available_options = [opt.get('name') for opt in options if isinstance(opt, dict) and opt.get('name')]
                raise DRFValidationError({"shipping_option_name": f"Invalid shipping option selected. Available: {', '.join(available_options)}"})

            shipping_option_details = found_option

            # Get Shipping Price for Selected Currency (Expect ATOMIC units from Product model/shipping options JSON)
            price_key_native = f'price_{selected_currency.lower()}_native' # Assume native price key convention
            shipping_price_str = shipping_option_details.get(price_key_native)
            if shipping_price_str is None:
                # Fallback to non-native if native key is missing (legacy?)
                price_key = f'price_{selected_currency.lower()}'
                shipping_price_str = shipping_option_details.get(price_key)
                if shipping_price_str is None:
                    logger.error(f"Shipping price (native or std) missing P:{product.id}, Option:'{shipping_option_name}', Curr:{selected_currency}")
                    raise DRFValidationError({"shipping_option_name": f"Shipping price not configured for currency '{selected_currency}' in this option."})
                # If using non-native, conversion logic would be needed here, complex.
                # For now, assume price is stored in ATOMIC units in shipping options.
                # Raise error if only non-native found and conversion not handled.
                logger.error(f"Only non-native shipping price found {price_key} P:{product.id}, Option:'{shipping_option_name}'. Native required.")
                raise DRFValidationError({"shipping_option_name": "Internal Error: Native shipping price configuration missing."})


            try:
                shipping_price_native = Decimal(shipping_price_str)
                if shipping_price_native < Decimal('0.0'):
                    raise ValueError("Shipping price cannot be negative.")
                # TODO: Consider currency precision for shipping price using CRYPTO_PRECISION_MAP? (Likely already atomic)
            except (InvalidOperation, ValueError, TypeError):
                logger.error(f"Invalid shipping price format P:{product.id}, Option:'{shipping_option_name}', Key:{price_key_native}, Value:'{shipping_price_str}'")
                raise DRFValidationError({"shipping_option_name": "Invalid shipping price configured for the selected option and currency."})
        else:
            # Ensure shipping blob is ignored/nulled for digital products
            if encrypted_shipping_blob:
                logger.warning(f"Encrypted shipping blob provided for digital Product:{product.id} by User:{user.id}. Ignoring.")
            encrypted_shipping_blob = None # Nullify for digital


        return price_native, shipping_option_details, shipping_price_native
    # --- End Helper Methods ---

    # --- End Helper Methods for PlaceOrderView ---

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handles the POST request to place an order."""
        user: UserModel = request.user
        ip_addr = get_client_ip(request)
        order: Optional[Order] = None # Initialize order variable

        try:
            # 1. Basic Input Validation
            product_id, quantity, selected_currency, shipping_option_name, encrypted_shipping_blob = \
                self._validate_request_data(request.data)

            # 2. Fetch Product (efficiently)
            try:
                # Include vendor info needed for validation/order creation
                product: Product = Product.objects.select_related('vendor').get(id=product_id)
            except Product.DoesNotExist:
                raise NotFound(detail=f"Product with ID {product_id} not found.")

            # 3. Validate Product Rules, Options, Stock, and Get Prices (prices are ATOMIC)
            price_native, shipping_option_details, shipping_price_native = \
                self._validate_product_and_options(
                    user, product, quantity, selected_currency,
                    shipping_option_name, encrypted_shipping_blob
                )

            # 4. Calculate Total Price (in ATOMIC units)
            try:
                total_price_native = (price_native * Decimal(quantity)) + shipping_price_native
                # No quantization needed here as we are dealing with atomic units
            except (InvalidOperation, TypeError) as e:
                logger.error(f"Order price calculation error P:{product.id} Q:{quantity} Pr:{price_native} ShPr:{shipping_price_native}: {e}")
                raise APIException("An error occurred during final price calculation.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 5. Create Order Data Dictionary
            order_data = {
                'buyer': user,
                'vendor': product.vendor,
                'product': product,
                'quantity': quantity,
                'selected_currency': selected_currency,
                'price_native_selected': price_native, # Atomic
                'shipping_price_native_selected': shipping_price_native, # Atomic
                'total_price_native_selected': total_price_native, # Atomic
                'selected_shipping_option': shipping_option_details, # Store chosen option details
                'encrypted_shipping_info': encrypted_shipping_blob if not getattr(product, 'is_digital', False) else None,
                'status': OrderStatusChoices.PENDING_PAYMENT, # Initial status
            }

            # 6. Create Order Instance (but don't save yet)
            # Use Order model directly or a serializer if preferred for initial creation
            # This approach allows passing validated data directly
            # Note: This bypasses OrderSerializer if one exists for creation, which might be desired or not.
            order = Order(**order_data)
            # order.full_clean() # Optional: Run full model validation before saving

            # 7. Initialize Escrow (via Service Layer) - This handles saving the order atomically
            try:
                # Service should handle saving Order, creating Payment, etc. and return the saved Order instance
                order = escrow_service.create_escrow_for_order(order) # Pass unsaved instance

                if not order or not order.pk: # Service should raise exception on failure
                    logger.critical(f"Escrow service failed to return saved order for P:{product.id} B:{user.id}/{user.username}")
                    raise APIException("Failed to initialize payment details for the order.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            except (DjangoValidationError, DRFValidationError) as e: # Catch validation errors raised by the service
                logger.warning(f"Order placement validation failed during escrow creation U:{user.id}/{user.username} (P:{product.id}): {e}")
                raise e # Re-raise validation error for 400 response
            except EscrowError as e: # Catch specific escrow errors
                logger.error(f"Escrow service error during order creation P:{product.id} U:{user.id}/{user.username}: {e}", exc_info=True)
                raise APIException(f"Failed to create order: {e}", status.HTTP_400_BAD_REQUEST)
            except Exception as e: # Catch unexpected service errors
                logger.exception(f"Unexpected error during escrow creation P:{product.id} U:{user.id}/{user.username}: {e}")
                raise APIException("An unexpected error occurred while initializing the order.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- Success ---
            logger.info(f"Order created: ID:{order.id}, Buyer:{user.id}/{user.username}, Vendor:{product.vendor.id}/{product.vendor.username}, P:{product.id}, IP:{ip_addr}")
            security_logger.info(f"Order created: ID={order.id}, Buyer={user.username}, Vendor={product.vendor.username}, ProdID={product.id}, Qty={quantity}, Curr={selected_currency}, Total={total_price_native}, IP={ip_addr}")
            log_audit_event(request, user, 'order_place', target_order=order, target_product=product, details=f"Q:{quantity}, C:{selected_currency}") # TODO: Verify action choice

            # --- Send Notification (Async Recommended) ---
            try:
                # from notifications.tasks import send_notification_task # Use async task
                # order_url = f"/orders/{order.pk}/" # Use reverse() ideally
                # send_notification_task.delay( # Trigger async task
                create_notification( # Sync call example
                        user_id=product.vendor.id,
                        level='info',
                        message=f"New order #{str(order.id)[:8]} placed by {user.username} for your product '{product.name[:30]}...'.", # Use slice of UUID
                        # link=order_url
                    )
                logger.info(f"Sent 'new order' notification to V:{product.vendor.id} for O:{order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'new order' notification for O:{order.id} to V:{product.vendor.id}: {notify_e}")
            # --- End Notification ---

            # Use the appropriate serializer for the response (buyer's view)
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except (DRFValidationError, NotFound, PermissionDenied) as e:
            # Log anticipated validation/permission errors
            product_id_req = request.data.get('product_id', 'N/A')
            logger.warning(f"Order placement failed for User:{user.id}/{user.username} (Product Attempted:{product_id_req}): {getattr(e, 'detail', str(e))}") # Use detail if available
            raise e # Re-raise DRF exception for standard response handling
        except Exception as e:
            # Handle unexpected errors during validation/setup
            logger.exception(f"Unexpected error placing order for User:{user.id}/{user.username}: {e}")
            raise APIException("An unexpected server error occurred while placing the order.", status.HTTP_500_INTERNAL_SERVER_ERROR)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Provides read-only access to orders, filtered by user role, with optimizations."""
    queryset = Order.objects.none() # Base queryset overridden in get_queryset
    permission_classes = [drf_permissions.IsAuthenticated]
    lookup_field = 'pk'
    # Load pagination class safely from settings
    pagination_class = import_string(settings.REST_FRAMEWORK.get(DEFAULT_PAGINATION_CLASS_SETTING)) if settings.REST_FRAMEWORK.get(DEFAULT_PAGINATION_CLASS_SETTING) else None
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter]
    filterset_fields = ['status', 'selected_currency'] # Use constants in frontend if possible
    ordering_fields = ['created_at', 'updated_at', 'status', 'total_price_native_selected']
    ordering = ['-created_at']
    # Add appropriate throttling

    def get_serializer_class(self) -> Type[OrderBaseSerializer]:
        """Determine serializer based on user's relationship to the order or view context."""
        instance: Optional[Order] = None
        if self.action == 'retrieve':
            try:
                instance = self.get_object()
            except (Http404, PermissionDenied, NotFound):
                pass # Let DRF error handling proceed

        user: UserModel = self.request.user
        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        if is_vendor_sales_view:
            return OrderVendorSerializer # Explicit vendor sales view
        elif instance: # If viewing a specific order instance
            if instance.vendor_id == user.id: return OrderVendorSerializer # Use _id for efficiency
            if instance.buyer_id == user.id: return OrderBuyerSerializer
            if getattr(user, 'is_staff', False): return OrderVendorSerializer # Staff default
        # Default for list view or if instance checks fail (should be caught by perms)
        return OrderBuyerSerializer

    def get_queryset(self) -> 'QuerySet[Order]':
        """Filter orders based on user role and apply query optimizations."""
        user: UserModel = self.request.user

        # Define base optimizations needed by serializers
        base_queryset = Order.objects.select_related(
            'product', 'product__vendor', 'product__category',
            'buyer', 'vendor', 'payment'
        ).prefetch_related(
            # Prefetch related feedback (assuming related_name='feedback_set' or 'feedback')
            Prefetch('feedback', queryset=Feedback.objects.select_related('reviewer')),
            'support_tickets' # Prefetch related tickets
        )

        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        if getattr(user, 'is_staff', False):
            logger.debug(f"Staff user {user.id}/{user.username} accessing orders.")
            queryset = base_queryset.all() # Staff sees all
        elif is_vendor_sales_view:
            if not getattr(user, 'is_vendor', False):
                logger.warning(f"Non-vendor user {user.id}/{user.username} attempted vendor sales view.")
                return Order.objects.none()
            logger.debug(f"Vendor user {user.id}/{user.username} accessing vendor sales.")
            queryset = base_queryset.filter(vendor=user)
        elif user.is_authenticated:
            logger.debug(f"Authenticated user {user.id}/{user.username} accessing their orders.")
            queryset = base_queryset.filter(Q(buyer=user) | Q(vendor=user))
        else:
            logger.warning("Unauthenticated user attempted OrderViewSet access.")
            queryset = Order.objects.none()

        return queryset

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Determine permissions based on view type and action."""
        permissions = [drf_permissions.IsAuthenticated()]
        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        if is_vendor_sales_view:
            # Vendor sales view requires vendor status and PGP auth
            permissions.extend([IsVendor(), IsPgpAuthenticated()])
        elif self.action == 'retrieve':
            # Detail view requires user to be buyer, vendor, or staff
            permissions.append(IsBuyerOrVendorOfOrder())

        return [p() for p in permissions] # Instantiate permissions

    # No custom retrieve needed if permissions handle object access


# --- Order Action Views ---

class OrderActionBaseView(APIView):
    """Base view for actions on a specific order (Requires PGP Auth & Order Involvement)."""
    permission_classes = [
        drf_permissions.IsAuthenticated,
        IsPgpAuthenticated,
        IsBuyerOrVendorOfOrder # Ensures user is buyer, vendor, or staff for the target order
    ]
    # Add throttle class using pgp_action scope?
    # throttle_classes = [PGPActionThrottle]

    def get_object(self, pk: Any) -> Order:
        """Retrieve the order, run permissions, handle not found."""
        try:
            # Optimize by fetching related objects commonly needed by actions/services
            order: Order = Order.objects.select_related(
                'buyer', 'vendor', 'payment', 'product'
            ).get(pk=pk)
            # Run DRF's object-level permission checks (IsBuyerOrVendorOfOrder)
            self.check_object_permissions(self.request, order)
            return order
        except Order.DoesNotExist:
            # Use DRF's NotFound for standard 404 response
            raise NotFound(detail="Order not found.")
        # PermissionDenied raised automatically by check_object_permissions


class MarkShippedView(OrderActionBaseView):
    """Allows VENDOR to mark an order as shipped (Requires PGP Auth)."""
    # Add specific permission for this action
    permission_classes = OrderActionBaseView.permission_classes + [IsVendor]

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        order = self.get_object(pk) # Fetches order and runs all permissions
        user: UserModel = request.user
        ip_addr = get_client_ip(request)
        # Assume service layer handles validation/sanitization of tracking info
        tracking_info = request.data.get('tracking_info', '').strip()

        try:
            # Delegate to service layer, expect exceptions on failure
            # Service should return the updated order instance
            # Pass actor explicitly for clarity
            updated_order: Order = escrow_service.mark_order_shipped(
                order=order,
                vendor=user, # Actor is the request user (validated by permissions)
                tracking_info=tracking_info
            )

            serializer = OrderVendorSerializer(updated_order, context={'request': request})
            logger.info(f"Order shipped: ID:{order.id}, By:{user.id}/{user.username}, IP:{ip_addr}, Tracking:{tracking_info or 'N/A'}")
            security_logger.info(f"Order shipped: ID={order.id}, By={user.username}, IP={ip_addr}, Tracking:{tracking_info or 'N/A'}")
            log_audit_event(request, user, 'order_ship', target_order=updated_order, details=f"Tracking: {tracking_info or 'N/A'}") # TODO: Verify action choice

            # --- Send Notification (Async Recommended) ---
            try:
                # from notifications.tasks import send_notification_task
                # order_url = f"/orders/{updated_order.pk}/"
                # send_notification_task.delay(...)
                create_notification( # Sync example
                    user_id=updated_order.buyer.id,
                    level='info',
                    message=f"Your order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...') has been shipped.", # Use slice of UUID
                    # link=order_url
                )
                logger.info(f"Sent 'order shipped' notification to B:{updated_order.buyer.id} for O:{updated_order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'order shipped' notification for O:{updated_order.id} to B:{updated_order.buyer.id}: {notify_e}")
            # --- End Notification ---

            return Response(serializer.data)

        # --- Specific Exception Handling ---
        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e: # Catch known errors
            # Log appropriately based on exception type
            if isinstance(e, PermissionDenied):
                logger.error(f"Permission denied during mark shipped service call O:{order.id} by V:{user.id}/{user.username}: {getattr(e, 'detail', str(e))}")
                raise e # Re-raise DRF permission error
            elif isinstance(e, (DjangoValidationError, ValueError)):
                logger.warning(f"Mark shipped validation failed O:{order.id} by V:{user.id}/{user.username}. Reason: {e}")
                if isinstance(e, DjangoValidationError):
                    raise DRFValidationError(detail=getattr(e, 'message_dict', str(e)))
                else:
                    raise DRFValidationError(detail=str(e))
            elif isinstance(e, (EscrowError, CryptoProcessingError)):
                logger.error(f"Service error marking shipped O:{order.id} by V:{user.id}/{user.username}. Type:{type(e).__name__}, Reason: {e}")
                raise APIException(f"Failed to mark order shipped: {e}", code=status.HTTP_400_BAD_REQUEST) # Return 400 or 500 based on error type
            else: # Should be DRFValidationError from raise_exception=True in serializer implicitly
                logger.warning(f"Mark shipped input validation failed O:{order.id} by V:{user.id}/{user.username}. Reason: {getattr(e, 'detail', str(e))}")
                raise e # Re-raise DRF validation error

        except Exception as e: # Catch unexpected errors
            logger.exception(f"Unexpected error marking O:{order.id} shipped by V:{user.id}/{user.username}: {e}")
            raise APIException("An unexpected server error occurred while marking the order as shipped.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FinalizeOrderView(OrderActionBaseView):
    """Allows BUYER to finalize an order (Requires PGP Auth)."""
    # Base permissions (IsAuth, IsPgpAuth, IsBuyerOrVendor) are sufficient, logic checks buyer role.

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        order = self.get_object(pk) # Fetches order and runs base permissions
        user: UserModel = request.user
        ip_addr = get_client_ip(request)

        # Explicit check: Only the buyer can finalize
        if user.id != order.buyer_id:
            logger.warning(f"User {user.id}/{user.username} (not buyer) attempted to finalize Order:{order.id}. IP:{ip_addr}")
            raise PermissionDenied("Only the buyer of this order can finalize it.")

        try:
            # Delegate to service layer - Expects service to check state and permissions again if needed
            # Service might return the updated order or raise exceptions
            # Assuming finalize_order returns the updated order
            updated_order: Order = escrow_service.finalize_order(order=order, user=user) # Pass user as actor

            serializer = OrderBuyerSerializer(updated_order, context={'request': request})
            logger.info(f"Order finalize initiated/completed: ID:{order.id}, By:{user.id}/{user.username}, IP:{ip_addr}")
            security_logger.info(f"Order finalize: ID={order.id}, By={user.username}, IP={ip_addr}")
            log_audit_event(request, user, 'order_finalize_request', target_order=updated_order) # TODO: Verify action choice

            # --- Send Notification (Async Recommended) ---
            try:
                # from notifications.tasks import send_notification_task
                # order_url = f"/orders/{updated_order.pk}/"
                # send_notification_task.delay( # To Vendor
                create_notification( # Sync example
                    user_id=updated_order.vendor.id,
                    level='success' if updated_order.status == OrderStatusChoices.FINALIZED else 'info',
                    message=f"Order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...') has been finalized by the buyer.", # Use slice of UUID
                    # link=order_url
                )
                logger.info(f"Sent 'order finalized' notification to V:{updated_order.vendor.id} for O:{updated_order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'order finalized' notification for O:{updated_order.id} to V:{updated_order.vendor.id}: {notify_e}")
            # --- End Notification ---

            # Optional: Prompt for feedback handled client-side based on status change

            return Response(serializer.data)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e: # Catch specific errors
            logger.warning(f"Finalize order failed O:{order.id} by B:{user.id}/{user.username}. Type:{type(e).__name__}, Reason: {e}")
            if isinstance(e, PermissionDenied): raise e
            if isinstance(e, (DjangoValidationError, ValueError)): # Treat ValueError from service as Bad Request
                raise DRFValidationError(detail=getattr(e, 'message_dict', str(e)))
            if isinstance(e, (EscrowError, CryptoProcessingError)):
                raise APIException(f"Failed to finalize order: {e}", code=status.HTTP_400_BAD_REQUEST) # Or 500?
            # Assume DRFValidationError if no other type matched
            raise e if isinstance(e, DRFValidationError) else DRFValidationError(detail=str(e))

        except Exception as e:
            logger.exception(f"Unexpected error finalizing O:{order.id} by B:{user.id}/{user.username}: {e}")
            raise APIException("Unexpected error during finalization.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ... (Rest of the views - SignReleaseView, PrepareReleaseTxView, OpenDisputeView, Withdrawal Views, Feedback, Tickets, Canary, WebAuthn etc. - follow similar patterns) ...

# --- ===================================== ---
# --- NEW VIEWS FOR VENDOR APP & RATES      ---
# --- ===================================== ---

# --- Exchange Rate View ---
class ExchangeRateView(APIView):
    """
    Provides the latest exchange rates stored in GlobalSettings.
    Publicly accessible, cached data updated by Celery task.
    """
    permission_classes = [drf_permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            settings_instance = GlobalSettings.load() # Load singleton settings
            serializer = ExchangeRateSerializer(settings_instance) # Use the dedicated serializer
            return Response(serializer.data)
        except Exception as e:
            logger.exception("Error retrieving exchange rates from GlobalSettings.")
            raise APIException("Could not retrieve exchange rates.", status.HTTP_503_SERVICE_UNAVAILABLE)


# --- Vendor Application Views ---

class VendorApplicationCreateView(generics.CreateAPIView):
    """
    Allows authenticated users to initiate a vendor application.
    Requires PGP authenticated session.
    Handles bond calculation (USD), BTC address generation, and record creation.
    Bond is payable ONLY in BTC.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [drf_permissions.IsAuthenticated, IsPgpAuthenticated] # Secure endpoint

    def perform_create(self, serializer: VendorApplicationSerializer) -> None:
        """
        Custom logic executed before saving the serializer instance.
        Validates user status, gets bond amount, generates BTC address, saves application.
        """
        user: UserModel = self.request.user
        log_prefix = f"[VendorApp Create U:{user.id}/{user.username}]"

        # 1. Validation Checks (Prevent duplicates, staff application)
        if user.is_vendor: raise DRFValidationError({"detail": "You are already an approved vendor."})
        if user.is_staff: raise DRFValidationError({"detail": "Staff members cannot apply to be vendors via this form."})
        # --- CORRECTED STATUS CHECK ---
        existing_app = VendorApplication.objects.filter(user=user).exclude(status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]).first()
        if existing_app:
            logger.warning(f"{log_prefix} Attempted new app, found existing App:{existing_app.id} Status:{existing_app.status}")
            existing_serializer = self.get_serializer(existing_app);
            raise DRFValidationError({
                "detail": "You already have a vendor application in progress or approved.",
                "existing_application": existing_serializer.data
            })

        # 2. Get Bond Amount (USD) from Settings
        try:
            settings_instance = GlobalSettings.load();
            bond_usd = settings_instance.default_vendor_bond_usd
            if not bond_usd or bond_usd <= Decimal('0.0'):
                raise ValueError("Vendor bond USD amount not configured or invalid.")
        except Exception as e:
            logger.error(f"{log_prefix} Error loading vendor bond USD setting: {e}")
            raise APIException("Vendor bond amount not configured correctly.", status.HTTP_503_SERVICE_UNAVAILABLE)

        # 3. Calculate BTC equivalent using Exchange Rate Service
        bond_btc_amount: Optional[Decimal] = None
        try:
            bond_btc_amount = exchange_rate_service.convert_usd_to_crypto(bond_usd, Currency.BTC)
            if bond_btc_amount is None or bond_btc_amount <= Decimal('0.0'):
                raise ValueError(f"Could not convert USD bond to BTC or result was invalid.")
            logger.info(f"{log_prefix} Calculated BTC bond: {bond_btc_amount} BTC (for ${bond_usd} USD)")
        except ValueError as ve:
            logger.error(f"{log_prefix} Error converting bond to BTC: {ve}")
            raise APIException("Could not calculate bond amount in BTC. Rates unavailable?", status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error converting bond: {e}")
            raise APIException("Could not calculate bond amount in BTC. Service error.", status.HTTP_503_SERVICE_UNAVAILABLE)

        # 4. Save Initial Application Record (within a transaction) to get ID
        instance: Optional[VendorApplication] = None
        btc_payment_address: Optional[str] = None
        try:
            with transaction.atomic():
                # Save initial instance without address first
                instance = serializer.save(
                    user=user,
                    # --- CORRECTED STATUS ---
                    status=VendorApplication.StatusChoices.PENDING_BOND,
                    bond_currency=Currency.BTC, # Hardcoded to BTC #<-- Corrected field name based on model? check your models.py
                    bond_amount_usd=bond_usd,
                    bond_amount_crypto=bond_btc_amount,
                    bond_payment_address=None # Temporarily None
                )
                logger.info(f"{log_prefix} VendorApplication {instance.id} initial save OK.")

                # 5. Generate Unique BTC Deposit Address using the new instance ID
                try:
                    logger.debug(f"{log_prefix} Requesting BTC deposit address for App ID: {instance.id}...")
                    btc_payment_address = bitcoin_service.get_new_vendor_bond_deposit_address(instance.id)
                    if not btc_payment_address:
                        raise ValueError(f"Bitcoin service failed to generate a deposit address for App ID: {instance.id}.")
                    logger.info(f"{log_prefix} Generated BTC deposit address: {btc_payment_address[:10]}...")

                    # 6. CRITICAL: Import address to Bitcoin node with label
                    label = f"VendorAppBond_{instance.id}"
                    import_success = bitcoin_service.import_btc_address_to_node(address=btc_payment_address, label=label)
                    if not import_success:
                        logger.critical(f"{log_prefix} FAILED to import BTC address '{btc_payment_address}' label '{label}' to node for App ID: {instance.id}. Rolling back.")
                        raise APIException("Failed to register payment address with node.", status.HTTP_500_INTERNAL_SERVER_ERROR)
                    else:
                        logger.info(f"{log_prefix} Imported BTC address '{btc_payment_address}' label '{label}' to node for App ID: {instance.id}.")

                    # 7. Update the application record with the generated address
                    instance.bond_payment_address = btc_payment_address
                    instance.save(update_fields=['bond_payment_address'])
                    logger.info(f"{log_prefix} Updated VendorApplication {instance.id} with payment address.")

                except Exception as crypto_e:
                    logger.exception(f"{log_prefix} Error during BTC address generation/import for App ID: {instance.id}. Rolling back.")
                    raise APIException("Failed to generate or register payment address.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # If transaction successful
            log_audit_event(self.request, user, 'vendor_app_initiate', target_application=instance, details=f"AppID:{instance.id} Curr:BTC")

        except IntegrityError as ie:
            logger.error(f"{log_prefix} Database integrity error saving application: {ie}")
            raise APIException("Failed to save application due to data conflict.", status.HTTP_409_CONFLICT)
        except APIException as ae:
            raise ae
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error saving VendorApplication instance.")
            raise APIException("Failed to save vendor application record.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer.instance = instance # Make sure serializer uses the final instance


class VendorApplicationStatusView(generics.RetrieveAPIView):
    """
    Allows an authenticated user to check the status of their vendor application.
    Returns the latest non-cancelled/non-rejected application, or latest rejected.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [drf_permissions.IsAuthenticated]

    def get_object(self) -> VendorApplication: # Specify return type
        user = self.request.user
        try:
            # Prioritize active/pending applications
            # --- CORRECTED STATUS CHECK ---
            application = VendorApplication.objects.filter(user=user).exclude(
                status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]
            ).order_by('-created_at').first()

            if not application:
                # If no active/pending, check for the latest rejected one
                # --- CORRECTED STATUS CHECK ---
                rejected_app = VendorApplication.objects.filter(
                    user=user, status=VendorApplication.StatusChoices.REJECTED
                ).order_by('-created_at').first()
                if rejected_app:
                    return rejected_app
                else:
                    # No application found at all
                    raise NotFound("No vendor application found for your account.")
            return application
        except NotFound:
            raise
        except Exception as e:
            logger.exception(f"Error retrieving vendor app status for U:{user.id}")
            raise APIException("Could not retrieve application status.", status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- Final Cleanup / TODOs ---
# - [STRUCTURE] Split this file into smaller modules (e.g., views/auth.py, views/orders.py etc.).
# - [SERVICE ERRORS] Ensure *all* service layer functions consistently raise specific, documented exceptions.
# - [ASYNC TASKS] Implement asynchronous tasks (Celery) for: Crypto node communication, Notifications, Reputation updates, Stats recalculation.
# - [TESTING] Add comprehensive unit and integration tests covering views, services, permissions, and edge cases.
# - [LOGGING] Perform a final review of all logging statements for consistency, appropriate levels, and context. Ensure log security.
# - [CONSTANTS] Replace *all* magic strings (statuses, types) with constants imported from models/constants.py.
# - [SECURITY] Review/Implement CSRF protection if using session auth with web frontend. Secure PGP key handling. Review all permission checks.
# - [DB INDEXES] Ensure database indexes are optimized for query patterns used in get_queryset and service layers.
# - [TYPE HINTS] Add/Complete type hinting across the entire project (models, services, serializers, views).

# --- END OF FILE ---