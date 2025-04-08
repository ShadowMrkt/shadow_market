# backend/store/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'store'
    verbose_name = "Shadow Market Store"

    def ready(self):
        # Import signals here if you have any store-related signals
        # try:
        #     import store.signals
        #     logger.info("Store signals loaded.")
        # except ImportError:
        #     pass
        logger.info("Store AppConfig ready.")