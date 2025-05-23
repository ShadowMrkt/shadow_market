# backend/store/views/feedback.py
# --- Revision History ---
# - v1.3 (2025-05-03): Correct import for IsAuthenticated to use rest_framework.permissions. (Gemini)
# - v1.2 (2025-04-29): Updated Helper Import (Gemini)
# - v1.1 (2025-04-29): Added missing APIException import. (Gemini)
# - v1.0 (Split from views.py Rev 4.7): Initial split. (Gemini)
# --- END Revision History ---
# Description: Contains views for creating Feedback.

# Standard Library Imports
import logging
from typing import Dict, Any, Optional, List, Tuple, Type, Union

# Django Imports
# (No specific Django imports needed directly by this view)

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import APIException # <-- ADDED MISSING IMPORT in Rev 1.1
# from rest_framework.response import Response # Not directly used
# from rest_framework.request import Request # Not directly used

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User, Order, Feedback # Added Order for logging
# --- Import Serializers ---
from backend.store.serializers import FeedbackSerializer
# --- Import Permissions ---
# from backend.store.permissions import IsAuthenticated, IsPgpAuthenticated # Old combined import
from rest_framework.permissions import IsAuthenticated # Standard DRF permission
from backend.store.permissions import IsPgpAuthenticated # Custom permission
# --- Import Helpers ---
# from backend.store.views.helpers import log_audit_event # Old path - Rev 1.0
from backend.store.utils.utils import log_audit_event # New path - Rev 1.2

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not used here


# --- Feedback Views ---

class FeedbackCreateView(generics.CreateAPIView):
    """
    Allows authenticated buyers/vendors to submit feedback for eligible orders.
    Requires a PGP-authenticated session.
    Relies on FeedbackSerializer for validation (order status, ownership, duplicates).
    """
    serializer_class = FeedbackSerializer
    # Use the correctly imported permission classes
    permission_classes = [IsAuthenticated, IsPgpAuthenticated]
    # Add throttle class if desired, e.g., throttle_classes = [FeedbackSubmitThrottle]

    # perform_create is slightly modified from the original to include audit logging
    def perform_create(self, serializer: FeedbackSerializer):
        """ Saves the feedback instance and logs the action. """
        try:
            instance: Feedback = serializer.save() # Serializer handles setting reviewer/recipient
            logger.info(f"Feedback submitted via FeedbackCreateView: ID:{instance.id}, Order:{instance.order_id}, By:{self.request.user.id}")

            # Add audit log event
            # Assumes log_audit_event can handle target_feedback if model supports it
            # Need to confirm AuditLog model and log_audit_event signature
            log_audit_event(
                self.request,
                self.request.user,
                'feedback_submit', # TODO: Verify action choice string
                target_order=instance.order,
                target_feedback=instance # Pass feedback instance if supported
            )
        except Exception as e:
            # Log error if saving or audit logging fails
            logger.error(f"Error during FeedbackCreateView perform_create for Order {getattr(serializer.validated_data.get('order'), 'id', 'N/A')}: {e}", exc_info=True)
            # Re-raise the exception to let DRF handle it (usually results in 500)
            # Now that APIException is imported, this will raise the correct exception type
            raise APIException("An error occurred while saving or logging feedback.")


# --- END OF FILE ---