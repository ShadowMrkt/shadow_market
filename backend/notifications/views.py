# backend/notifications/views.py
import logging
from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

# Import Notification model and serializer safely
try:
    from .models import Notification
    from .serializers import NotificationSerializer
except ImportError as e:
    logging.critical(f"CRITICAL IMPORT ERROR in notifications/views.py: {e}")
    Notification = None
    NotificationSerializer = None

logger = logging.getLogger(__name__)

# Use ReadOnlyModelViewSet for listing/retrieving, add custom actions for marking read
class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """
    API endpoint that allows users to view their notifications.
    Provides actions to mark notifications as read.

    list: Return a list of all notifications for the current user (unread first).
    retrieve: Return a specific notification instance.
    mark_read: Mark a specific notification as read.
    mark_all_read: Mark all unread notifications for the user as read.
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated] # Only authenticated users access

    # Ensure Notification model loaded
    if Notification is None:
         queryset = None # Set queryset to None if model failed import
         logger.critical("Notification model not loaded, NotificationViewSet will not function.")
    else:
         queryset = Notification.objects.all() # Base queryset

    def get_queryset(self):
        """
        This view should only return notifications for the currently authenticated user.
        Orders by creation date, newest first. Shows unread first.
        """
        user = self.request.user
        if Notification is None or not user or not user.is_authenticated:
            # Return empty queryset if no user or model issue
            return Notification.objects.none() if Notification else None

        # Filter for the logged-in user and order by read status then date
        return Notification.objects.filter(user=user).order_by('is_read', '-created_at')

    @action(detail=True, methods=['post'], url_path='mark-read', permission_classes=[permissions.IsAuthenticated])
    def mark_read(self, request, pk=None):
        """Marks a specific notification as read."""
        try:
            # Use get_object_or_404 directly if mixing wasn't used, but since we inherit from GenericViewSet, self.get_object() works
            notification = self.get_object() # Gets notification based on pk, checks queryset perms
        except Http404: # Import Http404 if needed or rely on DRF exception handling
             return Response({'status': 'error', 'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Ensure the notification belongs to the request user (already handled by get_queryset in list/retrieve, double check here)
        if notification.user != request.user:
            return Response({'status': 'forbidden'}, status=status.HTTP_403_FORBIDDEN)

        if not notification.is_read:
            notification.mark_as_read() # Use the model method
            logger.info(f"Notification {pk} marked as read for user {request.user.username}")
            # Return the updated notification data? Or just status? Just status is fine.
            serializer = self.get_serializer(notification)
            return Response(serializer.data, status=status.HTTP_200_OK)
            # return Response({'status': 'notification marked as read'}, status=status.HTTP_200_OK)
        else:
            # Already read, still return success
            serializer = self.get_serializer(notification)
            return Response(serializer.data, status=status.HTTP_200_OK)
            # return Response({'status': 'notification already read'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='mark-all-read', permission_classes=[permissions.IsAuthenticated])
    def mark_all_read(self, request):
        """Marks all unread notifications for the current user as read."""
        user = request.user
        if Notification is None or not user or not user.is_authenticated:
            return Response({'status': 'error', 'detail': 'User or Notification model unavailable'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Efficiently update all unread notifications for the user
        updated_count = Notification.objects.filter(user=user, is_read=False).update(is_read=True)

        logger.info(f"{updated_count} notifications marked as read for user {user.username}")
        return Response({'status': 'success', 'updated_count': updated_count}, status=status.HTTP_200_OK)