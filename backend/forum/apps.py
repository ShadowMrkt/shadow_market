# shadow_market/backend/forum/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class ForumConfig(AppConfig):
    # default_auto_field = 'django.db.models.BigAutoField' # Keep if needed
    name = 'forum'
    verbose_name = "Community Forum" # Changed verbose name

    def ready(self):
        # Import signals here to connect them
        try:
            import forum.signals
            logger.info("Forum signals imported successfully.")
        except ImportError as e:
            logger.error(f"Could not import forum signals: {e}")