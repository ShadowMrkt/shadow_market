# backend/ledger/apps.py
# --- Revision History ---
# v1.0.0 (2025-05-03): # <<< NEW REVISION HISTORY ADDED >>>
#   - Initial Version.
#   - FIXED: Set AppConfig `name` to 'backend.ledger' instead of just 'ledger'
#     to align with project structure and standardized import paths, resolving
#     persistent 'Conflicting models' errors during test collection.
# ------------------------
from django.apps import AppConfig
import logging
import datetime # Added for revision date

logger = logging.getLogger(__name__)

class LedgerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    # name = 'ledger' # OLD - Caused conflicts with 'backend.ledger' imports
    name = 'backend.ledger' # FIXED - Match the actual import path
    verbose_name = "Internal Ledger"

    def ready(self):
        logger.info(f"{self.verbose_name} ({self.name}) AppConfig ready.") # Log with correct name
        # Import signals here if ledger operations trigger signals
        # Use the correct path relative to this AppConfig's location if needed:
        # try:
        #     import backend.ledger.signals
        # except ImportError:
        #     pass

# --- END OF FILE ---