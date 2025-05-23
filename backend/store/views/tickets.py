# backend/store/views/tickets.py
# Revision: 1.3 (Fixed DRF IsAdminUser Import) # <<< UPDATED REVISION
# Date: 2025-05-03
# Author: Gemini
# Description: Contains API ViewSets for managing Support Tickets and Ticket Messages.
# Changes:
# - Rev 1.3: # <<< ADDED CHANGES
#   - FIXED: Imported IsAdminUser from drf_permissions instead of local permissions.py.
#   - Updated permission_classes decorator for 'assign' action.
# - Rev 1.2:
#   - FIXED: Imported IsAuthenticated from rest_framework.permissions instead of local permissions.py.
#   - Standardized DRF permission import as drf_permissions.
# - Rev 1.1:
#   - FIXED: Corrected `log_audit_event` call in `TicketMessageViewSet.perform_create` to use `self.request` instead of undefined `request`.
# - Rev 1.0 (2025-04-29):
#   - Initial Creation with SupportTicketViewSet and TicketMessageViewSet.
#   - Includes basic permissions, filtering, PGP encryption/decryption integration, and notifications.

# Standard Library Imports
import logging
from typing import TYPE_CHECKING, Any, Optional, List # Added List for type hint

# Django Imports
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings
from django.db import transaction, models # Import models for OrderActionBaseView PK check
# Required for potential reverse() usage in notifications
# from django.urls import reverse

# Third-Party Imports
# Corrected import for IsAuthenticated & IsAdminUser
from rest_framework import status, viewsets, mixins, permissions as drf_permissions
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError, NotFound, APIException
from rest_framework.request import Request
from rest_framework.response import Response

# Local Application Imports
from backend.store.models import SupportTicket, TicketMessage, User
from backend.store.serializers import (
    SupportTicketListSerializer,
    SupportTicketDetailSerializer,
    TicketMessageSerializer,
)
# Import only CUSTOM permissions from local file
# Removed IsAdminUser from this import
from backend.store.permissions import IsTicketRequesterAssigneeOrStaff
from backend.store.utils.utils import log_audit_event

# Import services and handle potential errors
try:
    # Assuming pgp_service is defined in backend.store.services.pgp_service
    # Adjust if it's exposed differently via __init__.py eventually
    from backend.store.services import pgp_service
    PGP_SERVICE_AVAILABLE = pgp_service.is_pgp_service_available() # Check if service loaded correctly
except (ImportError, AttributeError) as e: # Catch AttributeError if placeholder has no 'is_pgp_service_available'
    logger_init = logging.getLogger(__name__)
    logger_init.error(f"Failed to import or check PGP service in tickets view: {e}")
    pgp_service = None
    PGP_SERVICE_AVAILABLE = False

try:
    from backend.notifications.services import create_notification
except ImportError as e:
     logger_init = logging.getLogger(__name__)
     logger_init.warning(f"Notification service not found or import failed in tickets view: {e}. Notifications disabled.")
     # Define a dummy function so calls don't break
     def create_notification(*args, **kwargs): pass


# --- Type Hinting ---
if TYPE_CHECKING:
    from django.db.models.query import QuerySet

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security') # For sensitive actions


# --- Constants ---
# Assume a setting exists for the PGP key used by support staff
MARKET_SUPPORT_PGP_FINGERPRINT = getattr(settings, 'MARKET_SUPPORT_PGP_FINGERPRINT', None)
MARKET_SUPPORT_PGP_PUBLIC_KEY = getattr(settings, 'MARKET_SUPPORT_PGP_PUBLIC_KEY', None) # Needed for initial encryption to support

# --- ViewSets ---

class SupportTicketViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing Support Tickets.
    Allows creation, listing, retrieval, and potentially status changes/assignment.
    Permissions are handled by get_queryset and specific actions.
    """
    queryset = SupportTicket.objects.none() # Base queryset overridden in get_queryset
    # Corrected permission import usage
    permission_classes = [drf_permissions.IsAuthenticated] # Base permission

    def get_serializer_class(self):
        """Return appropriate serializer class based on action."""
        if self.action == 'list':
            return SupportTicketListSerializer
        return SupportTicketDetailSerializer

    def get_queryset(self) -> 'QuerySet[SupportTicket]':
        """
        Filter tickets based on user role.
        - Regular users see only tickets they requested.
        - Staff users see all tickets.
        Includes prefetching for optimization.
        """
        user = self.request.user
        # Return empty queryset if user is not authenticated (should be caught by permissions anyway)
        if not user or not user.is_authenticated:
             return SupportTicket.objects.none()

        # Use select_related for FKs, prefetch_related for reverse FKs/M2Ms
        base_qs = SupportTicket.objects.select_related(
            'requester', 'assigned_to', 'related_order', 'related_order__product'
        ).prefetch_related(
            # Prefetch messages and their senders - optimize if needed
            Prefetch('messages', queryset=TicketMessage.objects.select_related('sender').order_by('sent_at'))
        ).order_by('-updated_at') # Order by most recently updated

        if getattr(user, 'is_staff', False):
            # Staff can see all tickets
            logger.debug(f"Staff user {user.id} accessing all support tickets.")
            return base_qs
        else:
            # Regular users see only their tickets
            logger.debug(f"User {user.id} accessing their support tickets.")
            return base_qs.filter(requester=user)

    @transaction.atomic
    def perform_create(self, serializer) -> None:
        """
        Set requester, encrypt initial message for support, create message object.
        """
        user = self.request.user
        log_prefix = f"[TicketCreate U:{user.id}]"

        # Check PGP availability more robustly
        if not PGP_SERVICE_AVAILABLE or not hasattr(pgp_service, 'encrypt_message_for_recipient'):
             logger.error(f"{log_prefix} PGP service unavailable or missing required methods. Cannot create ticket.")
             # Use 503 Service Unavailable for configuration/dependency issues
             raise APIException("Ticket creation failed due to PGP service configuration error.", code=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not MARKET_SUPPORT_PGP_FINGERPRINT or not MARKET_SUPPORT_PGP_PUBLIC_KEY:
            logger.error(f"{log_prefix} Market support PGP fingerprint/key not configured. Cannot encrypt initial message.")
            raise APIException("Ticket creation failed due to support PGP configuration error.", code=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Ensure initial_message_body is provided (Serializer should handle this, but double-check)
        initial_message_body = serializer.validated_data.pop('initial_message_body', None)
        if not initial_message_body:
            # This should ideally be caught by serializer validation
            logger.warning(f"{log_prefix} initial_message_body missing from validated_data.")
            raise DRFValidationError({'initial_message_body': 'This field is required.'})

        # Save the ticket first to get an ID
        # Pass request context to serializer if needed for validation/defaults
        ticket = serializer.save(requester=user) # Removed context, add back if serializer needs it
        logger.info(f"{log_prefix} Created SupportTicket ID {ticket.id}.")

        try:
            # Encrypt the initial message for the market support key
            encrypted_body = pgp_service.encrypt_message_for_recipient(
                recipient_public_key=MARKET_SUPPORT_PGP_PUBLIC_KEY,
                recipient_fingerprint=MARKET_SUPPORT_PGP_FINGERPRINT,
                message=initial_message_body
            )
            logger.debug(f"{log_prefix} Encrypted initial message for Ticket ID {ticket.id} using support key.")

            # Create the first message linked to the ticket
            TicketMessage.objects.create(
                ticket=ticket,
                sender=user,
                encrypted_body=encrypted_body
                # sent_at is auto_now_add
            )
            logger.info(f"{log_prefix} Created initial TicketMessage for Ticket ID {ticket.id}.")

            log_audit_event(self.request, user, 'support_ticket_created', target_ticket=ticket, details=f"Subject: {ticket.subject}")

            # Optional: Notify support staff
            # Check if the function is callable (might be the dummy function)
            if callable(create_notification) and not isinstance(create_notification, type(lambda: None)):
                # Find staff users to notify (e.g., all staff, or a specific group/role)
                staff_users = User.objects.filter(is_staff=True, is_active=True)
                for staff_user in staff_users:
                     # Avoid notifying the creator if they happen to be staff creating a ticket
                     if staff_user.id != user.id:
                         try:
                              create_notification(
                                   user_id=staff_user.id,
                                   level='info',
                                   message=f"New support ticket #{ticket.id} created by {user.username}: '{ticket.subject[:50]}...'",
                                   # link=reverse('admin:store_supportticket_change', args=[ticket.id]) # Example admin link
                              )
                         except Exception as notify_err:
                              logger.error(f"{log_prefix} Failed to send staff notification to {staff_user.id}: {notify_err}")

        except pgp_service.PGPError as pgp_err: # Catch specific PGP errors if pgp_service defines them
             logger.exception(f"{log_prefix} PGP error creating initial message for Ticket ID {ticket.id}: {pgp_err}")
             # Raise DRF validation error to provide feedback to the user
             raise DRFValidationError(f"Failed to process initial message due to PGP error: {pgp_err}")
        except Exception as e:
            # If message creation/encryption fails after ticket is created,
            # the transaction.atomic will roll back the ticket creation.
            logger.exception(f"{log_prefix} Failed to encrypt/create initial message for Ticket ID {ticket.id}: {e}")
            # Raise DRF validation error
            raise DRFValidationError(f"Failed to process initial message: {e}")


    # --- Optional Custom Actions ---
    # Corrected permission import usage for IsAdminUser
    @action(detail=True, methods=['post'], permission_classes=[drf_permissions.IsAuthenticated, drf_permissions.IsAdminUser])
    def assign(self, request: Request, pk: Optional[str] = None) -> Response:
        """Assigns a staff member to the ticket."""
        ticket = self.get_object() # Ensures ticket exists and base permissions pass
        assignee_id_input = request.data.get('assignee_id')
        log_prefix = f"[TicketAssign U:{request.user.id} T:{ticket.id}]"

        if not assignee_id_input:
            raise DRFValidationError({'assignee_id': 'Assignee user ID is required.'})

        # Validate assignee_id format based on User PK type
        assignee_id = None
        try:
            # Adapt this based on your User model's primary key type (int, UUID, etc.)
            if isinstance(User._meta.pk, models.AutoField):
                 assignee_id = int(assignee_id_input)
            # Add elif for UUIDField if needed
            # elif isinstance(User._meta.pk, models.UUIDField):
            #      from uuid import UUID
            #      assignee_id = UUID(assignee_id_input)
            else:
                 # Assume string or other type if not AutoField/UUIDField - adjust as necessary
                 assignee_id = assignee_id_input
        except (ValueError, TypeError):
             raise DRFValidationError({'assignee_id': 'Invalid Assignee user ID format.'})


        try:
            # Ensure the assignee is actually staff and active
            assignee = User.objects.get(pk=assignee_id, is_staff=True, is_active=True)
        except User.DoesNotExist:
            logger.warning(f"{log_prefix} Attempted to assign ticket to non-existent/non-staff user ID {assignee_id}.")
            # Use NotFound for consistency with object retrieval failures
            raise NotFound(f"Staff user with ID {assignee_id} not found or is inactive.")

        old_assignee_username = getattr(ticket.assigned_to, 'username', 'None')
        ticket.assigned_to = assignee
        ticket.updated_at = timezone.now() # Manually update timestamp
        ticket.save(update_fields=['assigned_to', 'updated_at'])

        logger.info(f"{log_prefix} Ticket assigned to {assignee.username} by {request.user.username}.")
        log_audit_event(request, request.user, 'ticket_assign', target_ticket=ticket, target_user=assignee, details=f"Old Assignee: {old_assignee_username}")

        # Notify assignee and potentially requester
        # Check if the function is callable (might be the dummy function)
        if callable(create_notification) and not isinstance(create_notification, type(lambda: None)):
             try:
                  # Notify new assignee
                  create_notification(user_id=assignee.id, level='info', message=f"You have been assigned to support ticket #{ticket.id}.")
                  # Notify requester only if they are not the one assigning (unlikely for admin action)
                  if ticket.requester.id != request.user.id:
                       create_notification(
                            user_id=ticket.requester.id,
                            level='info',
                            message=f"Ticket #{ticket.id} ('{ticket.subject[:30]}...') has been assigned to a staff member."
                       )
             except Exception as notify_err:
                  logger.error(f"{log_prefix} Failed to send assignment notifications: {notify_err}")

        serializer = self.get_serializer(ticket)
        return Response(serializer.data)

    # Corrected permission import usage
    @action(detail=True, methods=['post'], permission_classes=[drf_permissions.IsAuthenticated, IsTicketRequesterAssigneeOrStaff])
    def close(self, request: Request, pk: Optional[str] = None) -> Response:
        """Closes the ticket. Can be done by requester or assigned staff."""
        ticket = self.get_object() # Permission checked here by DRF + get_object's internal check
        log_prefix = f"[TicketClose U:{request.user.id} T:{ticket.id}]"

        if ticket.status == SupportTicket.StatusChoices.CLOSED:
            # Use 400 Bad Request if already closed
            return Response({'detail': 'Ticket is already closed.'}, status=status.HTTP_400_BAD_REQUEST)

        ticket.status = SupportTicket.StatusChoices.CLOSED
        ticket.updated_at = timezone.now() # Manually update timestamp
        ticket.save(update_fields=['status', 'updated_at'])

        logger.info(f"{log_prefix} Ticket closed by {request.user.username}.")
        log_audit_event(request, request.user, 'ticket_close', target_ticket=ticket)

        # Notify relevant participants
        # Check if the function is callable (might be the dummy function)
        if callable(create_notification) and not isinstance(create_notification, type(lambda: None)):
            participants_notified = {request.user.id}
            # Notify requester if not the closer
            if ticket.requester.id not in participants_notified:
                 try:
                      create_notification(user_id=ticket.requester.id, level='info', message=f"Your support ticket #{ticket.id} ('{ticket.subject[:30]}...') has been closed.")
                      participants_notified.add(ticket.requester.id)
                 except Exception as notify_err:
                      logger.error(f"{log_prefix} Failed to notify requester {ticket.requester.id}: {notify_err}")

            # Notify assignee if exists and not the closer
            if ticket.assigned_to and ticket.assigned_to.id not in participants_notified:
                 try:
                      create_notification(user_id=ticket.assigned_to.id, level='info', message=f"Support ticket #{ticket.id} ('{ticket.subject[:30]}...') has been closed.")
                 except Exception as notify_err:
                      logger.error(f"{log_prefix} Failed to notify assignee {ticket.assigned_to.id}: {notify_err}")


        serializer = self.get_serializer(ticket)
        return Response(serializer.data)


class TicketMessageViewSet(mixins.CreateModelMixin,
                           mixins.ListModelMixin,
                           mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """
    ViewSet for managing Messages within a Support Ticket.
    Nested under /tickets/{ticket_pk}/messages/.
    Handles message encryption/decryption. Requires PGP setup.
    """
    serializer_class = TicketMessageSerializer
    # Corrected permission import usage
    permission_classes = [drf_permissions.IsAuthenticated] # Specific object permissions checked in methods

    def _get_parent_ticket(self) -> SupportTicket:
        """Helper to get the parent ticket and check base permissions."""
        ticket_pk_input = self.kwargs.get('ticket_pk')
        if not ticket_pk_input:
             logger.error("TicketMessageViewSet accessed without ticket_pk in URL kwargs.")
             raise NotFound("Ticket not specified.")

        # Convert ticket_pk based on SupportTicket PK type (adjust if UUID etc.)
        try:
             if isinstance(SupportTicket._meta.pk, models.AutoField):
                  ticket_pk = int(ticket_pk_input)
             # Add elif for UUIDField etc. if needed
             # elif isinstance(SupportTicket._meta.pk, models.UUIDField):
             #     from uuid import UUID
             #     ticket_pk = UUID(ticket_pk_input)
             else:
                  ticket_pk = ticket_pk_input # Assume correct type if not AutoField/UUID
        except (ValueError, TypeError):
             raise NotFound("Invalid ticket ID format in URL.")


        # Get the parent ticket - raises 404 if not found
        # Use select_related for efficiency when checking permissions
        try:
            parent_ticket = SupportTicket.objects.select_related(
                 'requester', 'assigned_to'
            ).get(pk=ticket_pk)
        except SupportTicket.DoesNotExist:
             logger.warning(f"Attempt to access messages for non-existent ticket {ticket_pk}.")
             raise NotFound("Ticket not found.")


        # Check permissions on the PARENT ticket using the dedicated permission class
        # This ensures the user can interact with this ticket's messages
        permission_checker = IsTicketRequesterAssigneeOrStaff()
        if not permission_checker.has_object_permission(self.request, self, parent_ticket):
             # Log sensitive action attempt
             security_logger.warning(f"User {self.request.user.id} denied access to messages for ticket {ticket_pk} via object permission check.")
             # Raise permission denied early
             raise PermissionDenied("You do not have permission to access messages for this ticket.")
        return parent_ticket

    def get_queryset(self) -> 'QuerySet[TicketMessage]':
        """
        Get messages for the specific ticket identified in the URL.
        Ensures user has permission to view the parent ticket via _get_parent_ticket.
        """
        parent_ticket = self._get_parent_ticket() # Handles permission check on parent ticket

        # Return messages for this specific, authorized ticket
        return TicketMessage.objects.filter(
            ticket=parent_ticket
        ).select_related('sender').order_by('sent_at') # Order chronologically

    def _decrypt_message_instance(self, message: TicketMessage) -> None:
        """
        Helper to attempt decryption for the requesting user and attach result.
        Should decrypt if the user is either the sender or the intended recipient (requester or assigned staff).
        """
        user = self.request.user
        log_prefix = f"[MsgDecrypt U:{user.id} M:{message.id} T:{message.ticket_id}]"

        # Always show placeholder if PGP service fails fundamentally
        if not PGP_SERVICE_AVAILABLE or not hasattr(pgp_service, 'decrypt_message'):
            logger.warning(f"{log_prefix} PGP Service unavailable or missing methods, cannot decrypt.")
            message._decrypted_body = "[Decryption unavailable]"
            return

        # Determine if the current user should be able to decrypt
        # This logic assumes messages are encrypted either for the requester OR the assigned_to/market support.
        # A more robust system might store recipient fingerprint with the message.
        can_decrypt = False
        if message.sender == user:
            can_decrypt = True # Sender can always decrypt their own messages (assuming service key is available)
        elif user.id == message.ticket.requester_id:
            can_decrypt = True # Requester can decrypt messages sent to them
        elif message.ticket.assigned_to and user.id == message.ticket.assigned_to_id:
            can_decrypt = True # Assigned staff can decrypt messages sent to them
        elif getattr(user, 'is_staff', False) and not message.ticket.assigned_to:
            # If staff and no specific assignee, assume message might be for general support pool
            # This might require checking against MARKET_SUPPORT_PGP_FINGERPRINT if stored per-message
            can_decrypt = True # Tentative: Allow staff to attempt decryption if unassigned

        if can_decrypt:
             try:
                 # Assuming decrypt_message uses the *current user's* key or the service key
                 # This might need refinement: how does pgp_service know which key to use?
                 # Does it try the user's key first, then the market key?
                 decrypted_content = pgp_service.decrypt_message(message.encrypted_body)
                 message._decrypted_body = decrypted_content # Use temporary attribute
                 logger.debug(f"{log_prefix} Successfully decrypted message.")
             except Exception as e:
                 # Log specific PGPError if available
                 pgp_err_type = getattr(pgp_service, 'PGPError', Exception)
                 if isinstance(e, pgp_err_type):
                      logger.warning(f"{log_prefix} PGP decryption failed: {e}")
                 else:
                      logger.exception(f"{log_prefix} Unexpected error during decryption: {e}")
                 message._decrypted_body = "[Decryption Failed]"
        else:
             # User is likely not the intended recipient or sender
             logger.debug(f"{log_prefix} User is not sender or intended recipient. Decryption not attempted.")
             message._decrypted_body = "[Encrypted for recipient]"


    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List messages, attempting decryption for the current user."""
        queryset = self.filter_queryset(self.get_queryset()) # Apply pagination/filtering first

        # Process decryption before serialization
        processed_queryset = []
        for message in queryset:
            self._decrypt_message_instance(message) # Attempt decryption based on requesting user
            processed_queryset.append(message)

        # Handle pagination
        page = self.paginate_queryset(processed_queryset)
        if page is not None:
             serializer = self.get_serializer(page, many=True)
             return self.get_paginated_response(serializer.data)

        # Non-paginated response
        serializer = self.get_serializer(processed_queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Retrieve a single message, attempting decryption."""
        instance = self.get_object() # get_object uses get_queryset, ensuring parent ticket permission
        self._decrypt_message_instance(instance) # Attempt decryption
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def perform_create(self, serializer) -> None:
        """
        Create a new message, encrypting for the appropriate recipient.
        """
        user = self.request.user
        parent_ticket = self._get_parent_ticket() # Gets ticket and checks permission
        ticket_pk = parent_ticket.pk # Get PK after fetching
        log_prefix = f"[TicketMessageCreate U:{user.id} T:{ticket_pk}]"

        # Check PGP service health
        if not PGP_SERVICE_AVAILABLE or not hasattr(pgp_service, 'encrypt_message_for_recipient') or not hasattr(pgp_service, 'get_key_details'):
            logger.error(f"{log_prefix} PGP service unavailable or missing required methods. Cannot create message.")
            raise APIException("Cannot send message due to PGP service configuration error.", code=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Ensure message body is present (should be handled by serializer's validation)
        message_body = serializer.validated_data.get('message_body')
        if not message_body:
             logger.warning(f"{log_prefix} message_body missing from validated_data in perform_create.")
             raise DRFValidationError({'message_body': 'Message cannot be empty.'})

        # --- Determine recipient and encrypt ---
        recipient_user: Optional[User] = None
        recipient_fingerprint: Optional[str] = None
        recipient_public_key: Optional[str] = None
        notify_user_ids: List[int] = [] # Can be multiple staff
        notification_message: str = ""
        log_recipient_info = "N/A" # For logging

        try: # Wrap key fetching and encryption logic
            if getattr(user, 'is_staff', False):
                # Staff is replying -> encrypt for the ticket requester
                recipient_user = parent_ticket.requester
                notify_user_ids.append(recipient_user.id)
                notification_message = f"Staff ({user.username}) replied to your support ticket #{ticket_pk}."
                log_recipient_info = f"Requester:{recipient_user.id}"

                if not recipient_user.pgp_public_key:
                      logger.error(f"{log_prefix} Cannot encrypt message: Requester {recipient_user.id} has no PGP key.")
                      raise DRFValidationError({"detail": "Cannot send reply: Ticket requester does not have a PGP key configured."})
                recipient_public_key = recipient_user.pgp_public_key

                # Fetch fingerprint for encryption context
                key_details = pgp_service.get_key_details(recipient_public_key)
                recipient_fingerprint = key_details.get('fingerprint')
                if not recipient_fingerprint: raise ValueError("Could not extract fingerprint for requester key")

            else:
                # Requester is replying
                notification_message = f"User {user.username} replied to support ticket #{ticket_pk}."
                recipient_set = False
                # Prioritize assigned staff member
                if parent_ticket.assigned_to and parent_ticket.assigned_to.pgp_public_key:
                    recipient_user = parent_ticket.assigned_to
                    notify_user_ids.append(recipient_user.id)
                    notification_message = f"User {user.username} replied to ticket #{ticket_pk} (assigned to you)."
                    log_recipient_info = f"Assigned Staff:{recipient_user.id}"
                    recipient_public_key = recipient_user.pgp_public_key

                    key_details = pgp_service.get_key_details(recipient_public_key)
                    recipient_fingerprint = key_details.get('fingerprint')
                    if not recipient_fingerprint: raise ValueError(f"Could not extract fingerprint for assigned staff {recipient_user.id}")
                    recipient_set = True

                # Fallback to general market support key if no suitable assigned staff
                elif MARKET_SUPPORT_PGP_FINGERPRINT and MARKET_SUPPORT_PGP_PUBLIC_KEY:
                    log_recipient_info = f"Market Support Key (FP:{MARKET_SUPPORT_PGP_FINGERPRINT[:8]}...)"
                    recipient_fingerprint = MARKET_SUPPORT_PGP_FINGERPRINT
                    recipient_public_key = MARKET_SUPPORT_PGP_PUBLIC_KEY
                    recipient_set = True
                    # Notify all relevant staff (example: all active staff)
                    staff_to_notify = User.objects.filter(is_staff=True, is_active=True)
                    for staff_user in staff_to_notify:
                         if staff_user.id != user.id: # Don't notify sender
                              notify_user_ids.append(staff_user.id)
                else:
                    # If neither assigned staff nor market key available
                    logger.error(f"{log_prefix} Cannot determine recipient PGP key for message: No assigned staff with PGP key and no market support key configured.")
                    raise DRFValidationError({"detail": "Cannot send message: No recipient PGP key found for support staff."})

            # --- Encrypt message ---
            encrypted_body = pgp_service.encrypt_message_for_recipient(
                 recipient_public_key=recipient_public_key, # Pass key for context
                 recipient_fingerprint=recipient_fingerprint, # Use fingerprint for encryption
                 message=message_body
            )
            logger.debug(f"{log_prefix} Encrypted message body for {log_recipient_info}")

        # Catch specific errors during key fetching or encryption
        except pgp_service.PGPError as pgp_err: # Catch specific PGP errors if defined
             logger.exception(f"{log_prefix} PGP Error preparing/encrypting message: {pgp_err}")
             raise DRFValidationError(f"Failed to process/encrypt message due to PGP error: {pgp_err}")
        except ValueError as val_err: # Catch fingerprint/key processing errors
             logger.error(f"{log_prefix} Value error preparing recipient key: {val_err}")
             raise DRFValidationError(f"Failed to process recipient PGP key: {val_err}")
        except Exception as e: # Catch any other unexpected errors during setup/encryption
             logger.exception(f"{log_prefix} Unexpected error preparing/encrypting message: {e}")
             raise APIException("Failed to encrypt message due to an unexpected error.", status.HTTP_500_INTERNAL_SERVER_ERROR)


        # --- Save the message instance ---
        message = serializer.save(
             ticket=parent_ticket,
             sender=user,
             encrypted_body=encrypted_body
             # message_body is write-only, not saved directly
        )
        logger.info(f"{log_prefix} Saved new TicketMessage ID {message.id}.")

        # --- Update parent ticket's timestamp and potentially status ---
        original_status = parent_ticket.status
        needs_save = False
        if parent_ticket.updated_at < message.sent_at: # Only update if new message is later
            parent_ticket.updated_at = message.sent_at
            needs_save = True

        # Update status based on sender and current status
        if getattr(user, 'is_staff', False) and original_status != SupportTicket.StatusChoices.CLOSED:
             if original_status != SupportTicket.StatusChoices.ANSWERED:
                 parent_ticket.status = SupportTicket.StatusChoices.ANSWERED
                 needs_save = True
        elif not getattr(user, 'is_staff', False) and original_status != SupportTicket.StatusChoices.CLOSED:
             if original_status != SupportTicket.StatusChoices.OPEN:
                 parent_ticket.status = SupportTicket.StatusChoices.OPEN # User replied, needs attention again
                 needs_save = True

        if needs_save:
             update_fields = ['updated_at']
             if parent_ticket.status != original_status:
                  update_fields.append('status')
             parent_ticket.save(update_fields=update_fields)
             logger.info(f"{log_prefix} Updated parent ticket {ticket_pk}. Status: {original_status} -> {parent_ticket.status}")


        # --- Send Notifications ---
        # Check if the function is callable (might be the dummy function)
        if callable(create_notification) and not isinstance(create_notification, type(lambda: None)):
             unique_notify_ids = set(notify_user_ids) # Ensure unique IDs
             for user_id in unique_notify_ids:
                 # Avoid notifying the sender
                 if user_id == user.id:
                     continue
                 try:
                     # Adjust message slightly if notifying general staff vs specific user
                     msg = notification_message
                     # TODO: Refine link generation
                     # ticket_link = reverse('ticket-detail', kwargs={'pk': ticket_pk}) # Example link
                     create_notification(
                          user_id=user_id,
                          level='info',
                          message=msg,
                          # link=ticket_link
                     )
                 except Exception as notify_err:
                      logger.error(f"{log_prefix} Failed to send notification to user {user_id}: {notify_err}")

        # --- Log Audit Event ---
        # FIX Rev 1.1: Use self.request here
        log_audit_event(self.request, user, 'ticket_message_sent', target_ticket=parent_ticket, details=f"Msg ID: {message.id}")


# --- END OF FILE ---