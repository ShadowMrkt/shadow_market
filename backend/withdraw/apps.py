# backend/withdraw/apps.py
# <<< ENTERPRISE GRADE REVISION: v1.0.1 - Correct app name attribute >>>
# Revision Notes:
# - v1.0.1: (Current - 2025-05-03) # Updated date
#   - FIXED: Changed the 'name' attribute from 'withdraw' to 'backend.withdraw'.
#     This ensures the AppConfig correctly identifies the application's Python
#     path, aligning it with how it's referenced in INSTALLED_APPS
#     ('backend.withdraw.apps.WithdrawConfig') and resolving model registration errors.
# - v1.0.0: Initial creation.

from django.apps import AppConfig

class WithdrawConfig(AppConfig):
    """
    AppConfig for the 'withdraw' application.

    Specifies the default auto field and the application name.
    This configuration is referenced in settings.INSTALLED_APPS.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend.withdraw' # <<< CORRECTED THIS LINE
    verbose_name = 'Withdrawal Management' # Optional: A more human-readable name for admin