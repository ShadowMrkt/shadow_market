# backend/store/views/helpers.py
# Revision: 1.0 (Created from helpers in views.py Rev 4.7)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains helper functions shared across different views modules within the 'store' app.

# Standard Library Imports
import logging
from typing import Optional, Union

# Django Imports
from django.http import HttpRequest

# Third-Party Imports
# Assuming Request is from DRF, adjust if it's Django's HttpRequest everywhere
from rest_framework.request import Request

# --- Local Imports (Using absolute paths from 'backend') ---
from backend.store.models import User, AuditLog, Product, Order, SupportTicket, VendorApplication, Feedback # Import all potential target models

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not used directly in helpers

# --- Helper Functions ---

def get_client_ip(request: Union[HttpRequest, Request]) -> Optional[str]:
    """
    Retrieves the client's IP address from the request object.
    Handles X-Forwarded-For header if present.
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
    target_order: Optional[Order] = None,
    target_ticket: Optional[SupportTicket] = None,
    target_product: Optional[Product] = None,
    target_application: Optional[VendorApplication] = None,
    target_feedback: Optional[Feedback] = None,
    details: str = ""
) -> None:
    """
    Helper function to create audit log entries reliably.
    Logs actor, action, optional targets, details, and IP address.
    """
    if actor and not isinstance(actor, User):
        actor_repr = getattr(actor, 'username', str(actor))
        logger.warning(f"Audit log attempted with invalid or missing actor: {actor_repr} ({type(actor)})")
        actor = None # Log as system/anonymous action if actor is invalid type

    try:
        ip_address = get_client_ip(request)
        AuditLog.objects.create(
            actor=actor,
            action=action, # TODO: Ensure 'action' aligns with AuditLogAction choices in models.py
            target_user=target_user,
            target_order=target_order,
            target_ticket=target_ticket,
            target_product=target_product,
            target_application=target_application,
            # target_feedback=target_feedback, # Uncomment if AuditLog model has target_feedback field
            details=details[:500], # Truncate details to fit model field length
            ip_address=ip_address
        )
    except Exception as e:
        # Avoid logging the actor object directly in case of failure, use username
        actor_username = getattr(actor, 'username', 'System/Anon')
        logger.error(f"Failed to create audit log entry (Action: {action}, Actor: {actor_username}): {e}", exc_info=True)

# --- END OF FILE ---