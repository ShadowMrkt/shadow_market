# backend/store/apps.py
# <<< ENTERPRISE GRADE REVISION: v1.1.0 - Corrected AppConfig name >>>
# Revision Notes:
# - v1.1.0 (2025-04-29):
#   - FIXED: Changed `name = 'store'` to `name = 'backend.store'` to ensure
#     consistency with the application path used in INSTALLED_APPS and resolve
#     conflicting model loading errors (`RuntimeError`).
# - v1.0.0 (Previous Version): Initial version.

from django.apps import AppConfig
import logging
import datetime # Added for revision date

logger = logging.getLogger(__name__)

class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # <<< FIXED: Use the full Python path for the app name >>>
    name = 'backend.store'
    verbose_name = "Shadow Market Store"

    def ready(self):
        # Import signals here using the consistent absolute path if uncommented
        # try:
        #     # Use 'backend.store.signals' if you reactivate this
        #     import backend.store.signals
        #     logger.info("Store signals loaded using absolute path.")
        # except ImportError:
        #     logger.debug("Store signals module not found or not needed.")
        #     pass
        # except Exception as e:
        #     logger.error(f"Error importing store signals: {e}", exc_info=True)

        logger.info(f"{self.verbose_name} (App: {self.name}) AppConfig ready.")