# backend/ledger/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class LedgerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ledger'
    verbose_name = "Internal Ledger"

    def ready(self):
        logger.info("Ledger AppConfig ready.")
        # Import signals here if ledger operations trigger signals
        # try:
        #     import ledger.signals
        # except ImportError:
        #     pass