# backend/notifications/apps.py
# <<< ENTERPRISE GRADE REVISION: v1.1.0 - Corrected AppConfig name >>> # <<< NEW REVISION
# Revision Notes:
# - v1.1.0 (2025-05-03): # <<< UPDATED DATE & NOTE
#   - FIXED: Changed `name = 'notifications'` to `name = 'backend.notifications'`
#     to ensure consistency with the application path used in INSTALLED_APPS
#     and standard project imports. This resolves the longstanding
#     `Conflicting 'notification' models` error during test collection.
# - v1.0.0 (Original): Initial version.

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _
import datetime # Added for revision date

class NotificationsConfig(AppConfig):
    """
    App configuration for the Notifications app.
    """
    # Use BigAutoField if default is set globally, otherwise specify here if needed
    # default_auto_field = 'django.db.models.BigAutoField'

    # <<< FIXED: Use the full Python path for the app name >>>
    name = 'backend.notifications'
    verbose_name = _("User Notifications")

    # No signals.py, so no ready() method needed for signal imports.
    # def ready(self):
    #     pass

# <<< END OF FILE: backend/notifications/apps.py >>>