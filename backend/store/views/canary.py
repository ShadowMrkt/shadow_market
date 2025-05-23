# backend/store/views/canary.py
# Revision: 1.0 (Initial Creation)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains the API view for displaying the Warrant Canary.

# Standard Library Imports
import logging
from typing import TYPE_CHECKING

# Django Imports
# from django.shortcuts import get_object_or_404 # Not needed for SingletonModel usually

# Third-Party Imports
from rest_framework import generics, permissions
from rest_framework.exceptions import APIException, NotFound

# Local Application Imports
from backend.store.models import GlobalSettings # Import the Singleton model
from backend.store.serializers import CanarySerializer # Import the specific serializer

# --- Type Hinting ---
if TYPE_CHECKING:
    # Pass # No specific complex types needed for hints here yet
    pass

# --- Setup Loggers ---
logger = logging.getLogger(__name__)

# --- Canary View ---

class CanaryDetailView(generics.RetrieveAPIView):
    """
    API view to retrieve the Warrant Canary details.

    Uses the GlobalSettings singleton model as the source.
    Accessible publicly.
    """
    permission_classes = [permissions.AllowAny] # Canary should be public
    serializer_class = CanarySerializer
    queryset = GlobalSettings.objects.all() # Required by DRF, even for singleton

    def get_object(self) -> GlobalSettings:
        """
        Retrieve the single GlobalSettings instance.
        Handles potential errors if the singleton instance doesn't exist.
        """
        try:
            # Use the standard method provided by django-solo to get the instance
            instance = GlobalSettings.get_solo()
            return instance
        except GlobalSettings.DoesNotExist:
            # This should ideally not happen if solo is set up correctly and migrations run,
            # as solo typically creates the instance if it doesn't exist on first access.
            logger.critical("CRITICAL: GlobalSettings singleton instance not found! Has it been created/migrated?")
            raise NotFound("Warrant canary information is currently unavailable (Settings object missing).")
        except Exception as e:
            logger.exception("Unexpected error retrieving GlobalSettings singleton for Canary view.")
            raise APIException("An error occurred while retrieving canary information.")

# --- END OF FILE ---