# backend/store/utils/utils.py
# Revision: 2.0
# Date: 2025-06-21
# Author: Gemini
# Description: Contains utility functions shared across the 'store' app.
# Changes:
# - Rev 2.0:
#   - Modified `log_audit_event` to correctly handle Generic Foreign Keys for target objects.
#   - The function now dynamically identifies the single target object provided (e.g., order, ticket) and stores its content type and primary key, resolving the `TypeError: AuditLog() got unexpected keyword arguments`.
#   - This assumes the `AuditLog` model uses `target_user` as a direct ForeignKey and a GenericForeignKey (`content_type`, `object_id`) for all other targets.
#   - Added `ContentType` import.
# - Rev 1.3:
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
from typing import Optional, Union, TYPE_CHECKING

# Django Imports
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest

# Third-Party Imports
from rest_framework.request import Request

# --- Local Imports (Using absolute paths from 'backend') ---
try:
    from backend.store.models import User, AuditLog
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.error(f"Failed to import User or AuditLog in store/utils.py: {e}. Audit logging might fail.")
    User = None
    AuditLog = None

if TYPE_CHECKING:
    from backend.store.models import Product, Order, SupportTicket, VendorApplication, Feedback

# --- Setup Loggers ---
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def get_client_ip(request: Union[HttpRequest, Request]) -> Optional[str]:
    """
    Retrieves the client's IP address from the request object.
    Handles X-Forwarded-For header if present and configured properly in deployment.
    """
    meta = getattr(request, 'META', {})
    x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = meta.get('REMOTE_ADDR')
    return ip

def log_audit_event(
    request: Union[HttpRequest, Request],
    actor: Optional['User'],
    action: str,
    target_user: Optional['User'] = None,
    target_order: Optional['Order'] = None,
    target_ticket: Optional['SupportTicket'] = None,
    target_product: Optional['Product'] = None,
    target_application: Optional['VendorApplication'] = None,
    target_feedback: Optional['Feedback'] = None,
    details: str = ""
) -> None:
    """
    Helper function to create audit log entries reliably.
    This version handles a direct ForeignKey to `target_user` and a
    GenericForeignKey for all other potential target object types.
    """
    if AuditLog is None or User is None:
        logger.error("AuditLog or User model not available. Cannot log audit event.")
        return

    if actor and not isinstance(actor, User):
        actor_repr = getattr(actor, 'username', str(actor))
        logger.warning(f"Audit log attempted with invalid actor type: {actor_repr} ({type(actor)})")
        actor = None

    try:
        ip_address = get_client_ip(request)
        details_truncated = details[:500] if details else ""

        create_kwargs = {
            'actor': actor,
            'action': action,
            'target_user': target_user, # Assumes 'target_user' is a direct FK field.
            'details': details_truncated,
            'ip_address': ip_address
        }

        # --- FIX: Handle Generic Foreign Key for other targets ---
        # List other potential targets. Find the one that was passed.
        other_targets = [
            target_order,
            target_ticket,
            target_product,
            target_application,
            target_feedback
        ]

        # Find the first non-None target from the list.
        # This assumes only one generic target is logged per event.
        target_object = next((t for t in other_targets if t is not None), None)

        if target_object:
            # If a generic target was found, get its ContentType and PK.
            # This assumes the AuditLog model has 'content_type' and 'object_id' fields.
            create_kwargs['content_type'] = ContentType.objects.get_for_model(target_object)
            create_kwargs['object_id'] = target_object.pk

        AuditLog.objects.create(**create_kwargs)

    except Exception as e:
        actor_username = getattr(actor, 'username', 'System/Anon') if actor else 'System/Anon'
        logger.error(f"Failed to create audit log entry (Action: {action}, Actor: {actor_username}): {e}", exc_info=True)

# --- END OF FILE ---