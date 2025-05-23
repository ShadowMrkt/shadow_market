# backend/forum/apps.py
# --- Revision History ---
# - v1.1 (2025-05-04): # <<< NEW REVISION >>>
#   - FIXED: Changed AppConfig 'name' from 'forum' to 'backend.forum' to match
#     the path used in INSTALLED_APPS and resolve RuntimeError during model loading.
#   - BEST PRACTICE: Changed relative import in ready() to absolute import
#     ('forum.signals' -> 'backend.forum.signals').
# - v1.0 (Initial): Basic AppConfig.
# --- END Revision History ---

from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class ForumConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField' # Good practice to set explicitly
    # --- FIX: Use the full Python path to the app ---
    name = 'backend.forum'
    verbose_name = "Community Forum" # Changed verbose name

    def ready(self):
        """Import signals when the app is ready."""
        # Import signals here to connect them
        try:
            # --- BEST PRACTICE: Use absolute import path ---
            import backend.forum.signals
            logger.info("Forum signals imported successfully.")
        except ImportError as e:
            logger.error(f"Could not import forum signals: {e}")
        except Exception as e: # Catch other potential errors during ready()
            logger.error(f"Unexpected error during ForumConfig.ready(): {e}", exc_info=True)

# --- END OF FILE ---