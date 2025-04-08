# backend/withdraw/apps.py
# Revision 1: Initial creation.

from django.apps import AppConfig


class WithdrawConfig(AppConfig):
    """
    AppConfig for the 'withdraw' application.

    Specifies the default auto field and the application name.
    This configuration is referenced in settings.INSTALLED_APPS.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'withdraw'
    verbose_name = 'Withdrawal Management' # Optional: A more human-readable name for admin