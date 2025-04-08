# backend/store/permissions.py
# <<< ENTERPRISE GRADE REVISION: v1.1.0 - Permissions Clarity & Best Practices >>>
# Revision Notes:
# - v1.1.0 (2025-04-07):
#   - ENHANCED: Updated docstrings for object-level permissions (IsOwnerOrVendorReadOnly,
#     IsBuyerOrVendorOfOrder, IsTicketRequesterAssigneeOrStaff) to strongly recommend using
#     `select_related` or `prefetch_related` in associated views/viewsets to prevent N+1 query issues.
#   - CLARIFIED: Strengthened the docstring and `message` for `IsPgpAuthenticated` to explicitly state
#     that it ONLY verifies recent session authentication via PGP and is NOT sufficient alone for
#     high-risk operations. Emphasized the need for per-action PGP confirmation decorators elsewhere.
#   - ADDED: Comment to `IsVendor` permission class noting potential future refactoring if User model changes
#     from `is_vendor` boolean to a role-based system.
#   - MINOR: Added more specific type hints (e.g., User type instead of Any where feasible, though Any kept for obj).
#   - MINOR: Cleaned up imports and added timezone to datetime imports.
# - v1.0.0 (Original): Initial version of the permissions file.

"""
Custom permission classes for the DRF application.

Ensures appropriate access control based on user roles (admin, vendor, owner),
authentication status, object ownership, and PGP session authentication status.

**IMPORTANT**: For production environments, ensure Django REST Framework's default
permission policy in `settings.py` (`DEFAULT_PERMISSION_CLASSES`) is restrictive,
e.g., `[rest_framework.permissions.IsAuthenticated]` or even `[DenyAll]`,
forcing explicit permission declarations on all views/viewsets.
"""

import logging
from datetime import datetime, timedelta, timezone # Added timezone
from typing import Any, TYPE_CHECKING

from django.conf import settings
# Use settings.AUTH_USER_MODEL for robustness if needed, but AbstractBaseUser is common
# Also allows for static type checking if TYPE_CHECKING block is used
# from django.contrib.auth.models import AnonymousUser, AbstractBaseUser # Using Custom User now
from django.contrib.auth.models import AnonymousUser # Keep explicit check for clarity
from django.http import HttpRequest
from django.utils import timezone as django_timezone # Use explicit alias
from rest_framework import permissions
from rest_framework.views import APIView # For type hinting view

# Import the User model for type hinting if possible, avoiding circular imports
# Recommended approach: Use settings.AUTH_USER_MODEL string when defining FKs/M2Ms
# and use TYPE_CHECKING block for type hints in permissions/serializers etc.
if TYPE_CHECKING:
    # Adjust the import path based on your project structure
    from store.models import User as UserModelType
else:
    # Provide a fallback type or Any if full model import isn't feasible/safe here
    UserModelType = Any # Or consider importing AbstractBaseUser if applicable


logger = logging.getLogger(__name__)

# --- Constants ---
PGP_AUTH_SESSION_KEY: str = '_pgp_authenticated_at'
OWNER_GROUP_NAME: str = getattr(settings, 'OWNER_GROUP_NAME', 'Owner') # Use setting or default

# Default timeout if specific settings aren't defined (fallback)
# Ensure these are DEFINED in your settings.py for production!
DEFAULT_PGP_AUTH_MINUTES: int = getattr(settings, 'DEFAULT_PGP_AUTH_SESSION_TIMEOUT_MINUTES', 30)
OWNER_PGP_AUTH_MINUTES: int = getattr(settings, 'OWNER_PGP_AUTH_SESSION_TIMEOUT_MINUTES', 10)


# --- Helper Functions ---

def _is_owner(user: UserModelType) -> bool:
    """
    Check if the user is authenticated, staff, and in the 'Owner' group.

    Args:
        user: The user object from the request (can be AnonymousUser).

    Returns:
        True if the user meets all owner criteria, False otherwise.
    """
    # Explicitly handle AnonymousUser or unauthenticated users first
    if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
        return False
    # Check staff status and group membership (requires user.groups relation)
    # Ensure the user object has the 'groups' manager (standard Django User does)
    if not hasattr(user, 'groups'):
        logger.warning(f"User {user.pk} missing 'groups' attribute for Owner check.")
        return False
    return bool(user.is_staff and user.groups.filter(name=OWNER_GROUP_NAME).exists())


# --- Permission Classes ---

class DenyAll(permissions.BasePermission):
    """
    Denies all access unconditionally. Useful as a restrictive default or for disabled views.
    """
    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        """Denies all list/create access."""
        return False

    def has_object_permission(self, request: HttpRequest, view: APIView, obj: Any) -> bool:
        """Denies all detail/update/delete access."""
        return False


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Allows read-only access (GET, HEAD, OPTIONS) to anyone (authenticated or not).
    Allows write access (POST, PUT, PATCH, DELETE) only to authenticated admin (staff) users.
    """
    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        """Check permission for list/create actions."""
        # Allow safe methods for everyone
        if request.method in permissions.SAFE_METHODS:
            return True
        # For unsafe methods, require authenticated staff user
        # Ensure user object is correctly populated by authentication backend
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, 'is_staff', False))


class IsVendor(permissions.BasePermission):
    """
    Allows access only to authenticated users who are marked as vendors.

    NOTE: Assumes a boolean field `is_vendor` exists on the user model.
          If the User model is refactored to use a dedicated `role` field,
          this permission MUST be updated accordingly (e.g., check `user.role == UserRole.VENDOR`).
    """
    message = 'You must be an approved vendor to perform this action.'

    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        """Check if the user is an authenticated vendor."""
        user = request.user
        # Ensure user is authenticated and has the 'is_vendor' attribute/flag set to True
        # Using getattr provides resilience if the attribute is missing, though it should exist.
        return bool(user and user.is_authenticated and getattr(user, 'is_vendor', False))


class IsOwnerOrVendorReadOnly(permissions.BasePermission):
    """
    Allows read-only access (GET, HEAD, OPTIONS) to any authenticated user.
    Allows write access (PUT, PATCH, DELETE) only to the authenticated vendor
    who owns the specific object (`obj.vendor == request.user`).

    **Performance Note:** Views using this permission for object-level checks
    should use `select_related('vendor')` in their `get_queryset()` method
    to avoid excessive database queries (N+1 problem) when checking multiple objects.
    """
    message = 'Write access restricted to the vendor owner of this resource.'

    def has_object_permission(self, request: HttpRequest, view: APIView, obj: Any) -> bool:
        """Check permission for detail/update/delete actions on a specific object."""
        user = request.user

        # Must be authenticated for any access
        if not (user and user.is_authenticated):
            return False

        # Allow safe methods for any authenticated user
        if request.method in permissions.SAFE_METHODS:
            return True

        # For unsafe methods, check if the object has a 'vendor' attribute
        if not hasattr(obj, 'vendor'):
            logger.warning(f"Object {type(obj).__name__} (PK: {getattr(obj, 'pk', 'N/A')}) lacks 'vendor' attribute for IsOwnerOrVendorReadOnly check.")
            return False # Cannot determine ownership

        # Write permissions require the user to be the vendor associated with the object
        # AND the user must generally have the 'is_vendor' flag (defense in depth).
        is_object_vendor = (obj.vendor == user)
        user_is_vendor = getattr(user, 'is_vendor', False) # Check user's general vendor status

        # Log if owner matches but user lacks vendor flag (potential inconsistency)
        if is_object_vendor and not user_is_vendor:
             logger.warning(f"User {user.pk} matches obj.vendor for {type(obj).__name__} (PK: {getattr(obj, 'pk', 'N/A')}) but user.is_vendor is False.")

        return bool(is_object_vendor and user_is_vendor)


class IsPgpAuthenticated(permissions.BasePermission):
    """
    **SECURITY CRITICAL:** Checks if the user is authenticated AND has completed a PGP
    challenge *within their current session* recently, respecting role-based inactivity timeouts.

    - **THIS PERMISSION IS NOT SUFFICIENT ON ITS OWN FOR HIGH-RISK ACTIONS.**
      Actions like withdrawals, changing security settings, finalizing orders, etc.,
      MUST **ALSO** be protected by a separate mechanism that forces a *per-action*
      PGP challenge/response (e.g., a dedicated API endpoint or decorator).
      This permission only verifies recent *session-level* PGP authentication.
    - Requires standard authentication (e.g., `permissions.IsAuthenticated`) to run first.
    - Checks for a specific timestamp (`PGP_AUTH_SESSION_KEY`) in the session.
    - Validates the timestamp against a timeout period (different for Owners vs others).
    - Refreshes the timestamp upon successful validation (sliding window).
    - Requires `SESSION_SAVE_EVERY_REQUEST = True` in Django settings for the
      sliding window refresh to persist reliably across requests.
    """
    SESSION_KEY = PGP_AUTH_SESSION_KEY
    message = ('Recent PGP authentication required or your PGP-verified session has expired due to inactivity. '
               'This check does not authorize high-risk actions on its own.')

    def _get_timeout_minutes(self, user: UserModelType) -> int:
        """Determine the correct session timeout duration based on user role."""
        if _is_owner(user):
            return OWNER_PGP_AUTH_MINUTES
        else:
            return DEFAULT_PGP_AUTH_MINUTES

    def has_permission(self, request: HttpRequest, view: APIView) -> bool:
        """Verify active PGP authentication status in the session."""
        user = request.user
        user_identifier = getattr(user, 'username', getattr(user, 'pk', 'N/A')) # For logging

        # Step 1: Basic Authentication Check (defense in depth, assumes IsAuthenticated ran first)
        if not (user and user.is_authenticated):
            # Should typically not be reached if IsAuthenticated is used first in view permissions
            logger.debug(f"IsPgpAuthenticated check skipped for user '{user_identifier}': User not authenticated.")
            return False

        # Step 2: Session Check (ensure session middleware is active)
        if not hasattr(request, 'session'):
            logger.error(f"IsPgpAuthenticated check failed for user '{user_identifier}': Request has no session attribute. Is SessionMiddleware enabled?")
            # Set a more specific message if possible, otherwise default is used
            self.message = "Session context not found. Cannot verify PGP authentication status."
            return False # Cannot proceed without a session

        # Step 3: Retrieve PGP Timestamp from Session
        try:
            pgp_auth_timestamp_str = request.session.get(self.SESSION_KEY)
            if not pgp_auth_timestamp_str:
                logger.debug(f"User '{user_identifier}' access denied by IsPgpAuthenticated: PGP auth session key ('{self.SESSION_KEY}') not found.")
                # Keep the default message or set a specific one
                # self.message = "PGP authentication session not found. Please perform PGP verification."
                return False

            # Step 4: Parse Timestamp and Check Expiry
            try:
                pgp_auth_time = datetime.fromisoformat(pgp_auth_timestamp_str)
            except ValueError:
                 logger.error(f"User '{user_identifier}' access denied by IsPgpAuthenticated: Could not parse timestamp '{pgp_auth_timestamp_str}' from session key '{self.SESSION_KEY}'. Removing invalid key.")
                 request.session.pop(self.SESSION_KEY, None)
                 return False

            # Ensure the stored time is timezone-aware for comparison with django_timezone.now()
            if not pgp_auth_time.tzinfo:
                logger.warning(f"PGP auth timestamp for user '{user_identifier}' is timezone-naive. Assuming UTC.")
                # Or apply default timezone from settings: pgp_auth_time = timezone.make_aware(pgp_auth_time)
                pgp_auth_time = pgp_auth_time.replace(tzinfo=timezone.utc) # Or settings.TIME_ZONE

            timeout_minutes = self._get_timeout_minutes(user)
            expiration_time = pgp_auth_time + timedelta(minutes=timeout_minutes)
            now_aware = django_timezone.now() # Use Django's timezone helper

            if now_aware > expiration_time:
                logger.warning(
                    f"User '{user_identifier}' access denied by IsPgpAuthenticated: PGP auth session expired "
                    f"(authenticated at {pgp_auth_time.isoformat()}, timeout: {timeout_minutes}m, expired at {expiration_time.isoformat()}, now: {now_aware.isoformat()})."
                )
                # Clear the expired key to force re-authentication
                request.session.pop(self.SESSION_KEY, None)
                # Set a more specific message
                self.message = f"Your PGP-verified session expired after {timeout_minutes} minutes of inactivity. Please re-verify with PGP."
                return False

            # --- Activity Detected: Refresh the PGP Auth Timer ---
            # Only refresh if SESSION_SAVE_EVERY_REQUEST is True, otherwise this won't reliably persist.
            request.session[self.SESSION_KEY] = now_aware.isoformat()
            logger.debug(f"User '{user_identifier}' access granted by IsPgpAuthenticated: Session valid until {expiration_time.isoformat()} and refreshed.")
            return True

        except (TypeError) as e: # Catches issues in _get_timeout_minutes or timedelta
            # Error parsing timestamp or getting timeout
            logger.error(
                f"Type error processing PGP auth status for user '{user_identifier}': {e}. "
                f"Raw session value: '{request.session.get(self.SESSION_KEY)}'. Denying access."
            )
            # Remove potentially corrupted key
            request.session.pop(self.SESSION_KEY, None)
            self.message = "Error processing PGP authentication status. Please try again."
            return False
        except AttributeError as e:
            # Error accessing user attributes (e.g., in _is_owner or if user object is malformed)
            logger.error(
                f"Attribute error checking PGP auth user '{user_identifier}': {e}. Denying access."
            )
            self.message = "Error verifying user details for PGP authentication status."
            return False


class IsBuyerOrVendorOfOrder(permissions.BasePermission):
    """
    Allows access only to the authenticated buyer or the authenticated vendor
    associated with the specific order object.
    Assumes the object `obj` has `buyer` and `vendor` attributes linking to user objects.

    **Performance Note:** Views using this permission should use `select_related('buyer', 'vendor')`
    in their `get_queryset()` method to avoid excessive database queries (N+1 problem)
    when checking multiple order objects.
    """
    message = 'You must be the buyer or vendor associated with this order to access it.'

    def has_object_permission(self, request: HttpRequest, view: APIView, obj: Any) -> bool:
        """Check if the user is the buyer or vendor of the order object."""
        user = request.user

        # Must be authenticated
        if not (user and user.is_authenticated):
            return False

        # Check if object has required attributes (robust check)
        # Assuming 'obj' is an Order instance or similar structure
        obj_pk = getattr(obj, 'pk', 'N/A') # For logging
        if not hasattr(obj, 'buyer') or not hasattr(obj, 'vendor'):
            logger.warning(f"Object {type(obj).__name__} (PK: {obj_pk}) lacks 'buyer' or 'vendor' attribute for IsBuyerOrVendorOfOrder check.")
            return False # Cannot determine relationship

        # Check if user matches buyer or vendor
        # Ensure buyer/vendor attributes are user instances or at least comparable by PK
        # obj.buyer == user comparison should work correctly with Django models/users
        is_buyer = (obj.buyer == user)
        is_vendor = (obj.vendor == user)

        return bool(is_buyer or is_vendor)


class IsTicketRequesterAssigneeOrStaff(permissions.BasePermission):
    """
    Allows access to a support ticket object based on user role:
    - The user who requested the ticket (`obj.requester`).
    - The staff user assigned to the ticket (`obj.assigned_to`).
    - Any other authenticated staff user.
    Assumes `obj` has `requester` and potentially `assigned_to` attributes linking to user objects.

    **Performance Note:** Views using this permission should use `select_related('requester', 'assigned_to')`
    in their `get_queryset()` method to avoid excessive database queries (N+1 problem)
    when checking multiple ticket objects.
    """
    message = 'You must be the ticket requester, the assigned staff member, or other authorized staff to access this ticket.'

    def has_object_permission(self, request: HttpRequest, view: APIView, obj: Any) -> bool:
        """Check if user is requester, assignee, or general staff."""
        user = request.user

        # Must be authenticated
        if not (user and user.is_authenticated):
            return False

        # Check required attributes on object and user
        obj_pk = getattr(obj, 'pk', 'N/A') # For logging
        if not hasattr(obj, 'requester'):
            logger.warning(f"Object {type(obj).__name__} (PK: {obj_pk}) lacks 'requester' attribute for IsTicketRequesterAssigneeOrStaff check.")
            return False # Cannot determine requester
        if not hasattr(user, 'is_staff'):
             logger.warning(f"User {getattr(user, 'pk', 'N/A')} lacks 'is_staff' attribute for IsTicketRequesterAssigneeOrStaff check.")
             # Decide behavior: deny access if staff status cannot be determined? Assume False? Deny seems safer.
             return False # Cannot check staff status

        # Determine access rights
        is_requester = (obj.requester == user)

        # Assigned staff: must exist, match user, and user must be staff
        is_assignee = False
        if hasattr(obj, 'assigned_to') and obj.assigned_to:
            # obj.assigned_to == user handles the user matching
            # user.is_staff checks if the *requesting user* is staff
            # Redundant check? If obj.assigned_to is staff, request.user must be that same staff user.
            # Let's simplify: If user matches assigned_to, they have access (assuming assigned_to are always staff).
            # If non-staff can be assigned, the check `and user.is_staff` is needed.
            # Assuming only staff can be assigned:
            is_assignee = (obj.assigned_to == user)
            # If non-staff *could* be assigned but only *staff* assignees get access via this rule:
            # is_assignee = (obj.assigned_to == user and user.is_staff) # Keep original logic if non-staff can be assigned

        # General staff access (any staff user can access)
        is_general_staff = user.is_staff

        # Grant access if any condition is met
        return bool(is_requester or is_assignee or is_general_staff)

# --- End of Permission Classes ---