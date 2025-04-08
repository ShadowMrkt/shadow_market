# backend/notifications/models.py
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError

# --- Choices ---
NOTIFICATION_LEVEL_CHOICES = [
    ('info', 'Info'),
    ('success', 'Success'),
    ('warning', 'Warning'),
    ('error', 'Error'),
]

# --- Notification Model ---

class Notification(models.Model):
    """
    Represents a notification message for a specific user.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Link to the user who should receive the notification
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Delete notifications if user is deleted
        related_name='notifications',
        db_index=True
    )
    # Level/type of notification (for styling/filtering on frontend)
    level = models.CharField(
        max_length=10,
        choices=NOTIFICATION_LEVEL_CHOICES,
        default='info',
        db_index=True
    )
    # The actual message content
    message = models.TextField(
        help_text="The notification message content."
    )
    # Optional link to a relevant page within the application
    link = models.URLField(
        blank=True, null=True, max_length=500, # Allow longer URLs if needed
        help_text="Optional URL link related to the notification (e.g., an order or ticket)."
    )
    # Read status
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Indicates if the user has marked this notification as read."
    )
    # Timestamp
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        editable=False
    )

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at'] # Show newest first by default
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
        ]

    def __str__(self):
        user_str = getattr(self.user, 'username', str(self.user_id))
        read_status = "Read" if self.is_read else "Unread"
        return f"[{self.level.upper()}] To: {user_str} - {self.message[:50]}... ({read_status})"

    def mark_as_read(self):
        """Marks the notification as read."""
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])

    def mark_as_unread(self):
        """Marks the notification as unread."""
        if self.is_read:
            self.is_read = False
            self.save(update_fields=['is_read'])

    def clean(self):
        """ Add basic validation """
        super().clean()
        if not self.message:
            raise ValidationError("Notification message cannot be empty.")
        # Potentially validate link format more strictly if needed