# backend/notifications/apps.py
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class NotificationsConfig(AppConfig):
    """
    App configuration for the Notifications app.
    """
    # Use BigAutoField if default is set globally, otherwise specify here if needed
    # default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'
    verbose_name = _("User Notifications")