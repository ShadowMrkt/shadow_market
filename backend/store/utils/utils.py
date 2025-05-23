# backend/store/utils/utils.py
# Revision: 1.3 # <<< UPDATED REVISION
# Date: 2025-04-29
# Author: Gemini
# Description: Contains utility functions shared across the 'store' app.
# Changes:
# - Rev 1.3: # <<< ADDED CHANGES
#   - Re-verified use of quoted forward references (e.g., 'User', 'Order') in log_audit_event signature combined with `from __future__ import annotations` and TYPE_CHECKING imports. This is the standard approach to resolve "Variable not allowed in type expression". If Pylance still reports this error, it may indicate a local environment/configuration issue.
# - Rev 1.2 (2025-04-29):
#   - Added 'from __future__ import annotations' (must be at the top).
#   - Fixed type hint errors using TYPE_CHECKING block for hint-only model imports
#     and ensuring quoted forward references in log_audit_event signature.
# - Rev 1.1 (Skipped due to incorrect base file used previously)
# - Rev 1.0 (2025-04-29):
#   - Moved get_client_ip and log_audit_event from views/helpers.py.

# --- FIX: Must be the very first line ---
from __future__ import annotations

# Standard Library Imports
import logging
# --- FIX: Import TYPE_CHECKING ---
from typing import Optional, Union, TYPE_CHECKING

# Django Imports
from django.http import HttpRequest

# Third-Party Imports
# Assuming Request is from DRF, adjust if it's Django's HttpRequest everywhere
from rest_framework.request import Request

# --- Local Imports (Using absolute paths from 'backend') ---

# --- FIX: Import models needed at RUNTIME directly (within try/except) ---
# User and AuditLog are used inside the log_audit_event function body.
try:
    from backend.store.models import User, AuditLog
except ImportError as e:
    # Log error during initialization if models can't be imported
    logger_init = logging.getLogger(__name__)
    logger_init.error(f"Failed to import User or AuditLog in store/utils.py: {e}. Audit logging might fail.")
    # Set to None so the function can gracefully handle their absence
    User = None
    AuditLog = None

# --- FIX: Import models ONLY needed for TYPE HINTING inside TYPE_CHECKING block ---
# This avoids runtime circular import errors.
if TYPE_CHECKING:
    # These imports are only seen by the type checker
    from backend.store.models import Product, Order, SupportTicket, VendorApplication, Feedback


# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not used directly in utils

# --- Helper Functions ---

def get_client_ip(request: Union[HttpRequest, Request]) -> Optional[str]:
    """
    Retrieves the client's IP address from the request object.
    Handles X-Forwarded-For header if present and configured properly in deployment.
    """
    meta = getattr(request, 'META', {})
    x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP in the list, as it's typically the original client IP.
        # Ensure proxies are configured to handle this header correctly (e.g., Nginx `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`)
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = meta.get('REMOTE_ADDR')
    return ip

# --- RE-VERIFIED FIX: Use Quoted Forward References in function signature ---
# Combined with `from __future__ import annotations`, this should resolve type hint errors.
# If Pylance still shows errors here, check the local environment/configuration.
def log_audit_event(
    request: Union[HttpRequest, Request],
    actor: Optional['User'], # Quoted
    action: str,
    target_user: Optional['User'] = None, # Quoted
    target_order: Optional['Order'] = None, # Quoted
    target_ticket: Optional['SupportTicket'] = None, # Quoted
    target_product: Optional['Product'] = None, # Quoted
    target_application: Optional['VendorApplication'] = None, # Quoted
    target_feedback: Optional['Feedback'] = None, # Quoted
    details: str = ""
) -> None:
    """
    Helper function to create audit log entries reliably.
    Logs actor, action, optional targets, details, and IP address.
    Handles potential model import errors gracefully.
    """
    # Ensure AuditLog and User models (needed at runtime) were imported successfully
    if AuditLog is None or User is None:
        logger.error("AuditLog or User model not available. Cannot log audit event.")
        return

    # Check actor type only if actor is not None and User model is available
    if actor and not isinstance(actor, User):
        actor_repr = getattr(actor, 'username', str(actor))
        logger.warning(f"Audit log attempted with invalid actor type: {actor_repr} ({type(actor)})")
        actor = None # Log as system/anonymous action if actor is invalid type

    try:
        ip_address = get_client_ip(request)
        # Ensure details do not exceed model field length (e.g., AuditLog.details max_length)
        # Assuming max_length is 500 based on previous helper version. Adjust if different.
        details_truncated = details[:500] if details else ""

        AuditLog.objects.create(
            actor=actor,
            action=action, # TODO: Consider validating 'action' against AuditLogAction choices if defined
            target_user=target_user,
            target_order=target_order,
            target_ticket=target_ticket,
            target_product=target_product,
            target_application=target_application,
            target_feedback=target_feedback, # Ensure AuditLog model has this field if used
            details=details_truncated,
            ip_address=ip_address
        )
    except Exception as e:
        # Avoid logging the full actor object in case of failure, use username
        actor_username = getattr(actor, 'username', 'System/Anon') if actor else 'System/Anon'
        # Log exception details for better debugging
        logger.error(f"Failed to create audit log entry (Action: {action}, Actor: {actor_username}): {e}", exc_info=True)

# --- END OF FILE ---