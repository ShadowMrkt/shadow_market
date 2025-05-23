# backend/notifications/services.py
# --- Revision History ---
# v1.0.0 (2025-05-03): # <<< NEW REVISION HISTORY ADDED >>>
#   - Initial Version.
#   - FIXED: Changed relative model import `from .models import ...` to
#     absolute import `from backend.notifications.models import ...` to
#     resolve conflicting model errors during test collection.
# ------------------------
import logging
from typing import Optional
import datetime # Added for revision date

from django.conf import settings
from django.urls import reverse # For potentially generating links

# Import the Notification model and User model safely
# <<< FIX v1.0.0: Use absolute import path >>>
try:
    # from .models import Notification, NOTIFICATION_LEVEL_CHOICES # OLD
    from backend.notifications.models import Notification, NOTIFICATION_LEVEL_CHOICES # FIXED
    User = settings.AUTH_USER_MODEL # Get User model string correctly ('store.User')
except ImportError as e:
    logging.critical(f"CRITICAL IMPORT ERROR in notifications/services.py: {e}")
    Notification = None
    User = None # This will be the string from settings or None if settings fail
    NOTIFICATION_LEVEL_CHOICES = [] # Define as empty list on import error

logger = logging.getLogger(__name__)

def create_notification(
    user_id: int, # Use user ID to avoid potential circular imports or heavy User object passing
    level: str,
    message: str,
    link: Optional[str] = None
) -> Optional[Notification]:
    """
    Creates and saves a new notification for a specified user.

    Args:
        user_id: The ID of the User who should receive the notification.
        level: The notification level ('info', 'success', 'warning', 'error').
        message: The notification message content.
        link: An optional internal URL path (e.g., using reverse()) or external URL.

    Returns:
        The created Notification object, or None if creation failed.
    """
    # Check if models loaded correctly
    if Notification is None or User is None: # User check is for settings.AUTH_USER_MODEL string availability
        logger.error("Notification model or AUTH_USER_MODEL setting not available in create_notification.")
        return None

    # Validate level
    valid_levels = [choice[0] for choice in NOTIFICATION_LEVEL_CHOICES]
    if level not in valid_levels:
        logger.warning(f"Invalid notification level '{level}' used. Defaulting to 'info'.")
        level = 'info'

    if not message:
        logger.error("Cannot create notification with an empty message.")
        return None

    try:
        # Use user_id directly assuming it's valid. Avoid fetching User object here for performance.
        # If User object needed for validation, fetch it carefully.
        notification = Notification.objects.create(
            user_id=user_id, # Assign directly using user_id
            level=level,
            message=message,
            link=link
        )
        logger.info(f"Notification created for User ID {user_id}: Level={level}, Message='{message[:50]}...'")
        return notification
    except Exception as e:
        # Catch potential errors like invalid user_id (ForeignKey constraint) or DB issues
        logger.exception(f"Failed to create notification for User ID {user_id}: {e}")
        return None

# Example Usage (to be added in other views/services):
# from backend.notifications.services import create_notification # Use correct path
# from django.urls import reverse
# ...
# if order.status == 'shipped':
#     link_to_order = reverse('order-detail', kwargs={'pk': order.pk}) # Assuming DRF router name
#     create_notification(
#         user_id=order.buyer.id, # Pass the user's ID
#         level='success',
#         message=f"Your order '{order.product.name}' has been shipped!",
#         link=link_to_order
#     )

# --- END OF FILE ---