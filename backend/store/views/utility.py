# backend/store/views/utility.py
# <<< ENTERPRISE GRADE REVISION: v1.2.0 - Fixed PGP encryption call >>> # <<< NEW REVISION
# Revision Notes:
# - v1.2.0 (2025-05-03): # <<< UPDATED DATE & NOTE
#   - FIXED: Corrected call to pgp_service.encrypt_message_for_recipient in
#     EncryptForVendorView to include the required `recipient_fingerprint` argument.
#     Added logic to fetch the fingerprint using get_key_details.
# - v1.1.0 (2025-05-03):
#   - FIXED: Corrected permission import. Changed import from
#     `backend.store.permissions` to only import `IsPgpAuthenticated`.
#   - FIXED: Updated `EncryptForVendorView.permission_classes` to use
#     `drf_permissions.IsAuthenticated` (from rest_framework) and the
#     locally imported `IsPgpAuthenticated`. Resolves ImportError during test collection.
# - Rev 1.0: (2025-04-29)
#   - Initial split of HealthCheckView, EncryptForVendorView, ExchangeRateView.
#   - Using absolute imports from 'backend' root.
# History from views.py Rev 4.7 relevant to these views:
# - Rev 3: Added ExchangeRateView.

# Standard Library Imports
import logging
import json
import secrets
from typing import Dict, Any, Optional, List, Tuple, Type, Union
import datetime # Added for revision date

# Django Imports
from django.conf import settings
from django.core.cache import cache
from django.db import connection # For HealthCheckView
from django.utils import timezone

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import (
    ValidationError as DRFValidationError, APIException, NotFound # Added NotFound
)
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User, GlobalSettings
# --- Import Serializers ---
from backend.store.serializers import EncryptCheckoutDataSerializer, ExchangeRateSerializer
# --- Import Permissions ---
from rest_framework.permissions import IsAuthenticated # Import standard permission
from backend.store.permissions import IsPgpAuthenticated # Import custom permission
# --- Import Services ---
from backend.store.services import pgp_service
# --- Import Services/Config Checks ---
try: from backend.ledger import services as ledger_service
except ImportError: ledger_service = None # Handle optional ledger

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not used here

# --- Utility Views ---

class HealthCheckView(APIView):
    """Simple health check endpoint, checks DB and Cache."""
    permission_classes = [drf_permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        dependencies_status: Dict[str, str] = {}
        overall_ok = True

        # Check DB
        try:
            connection.ensure_connection()
            # Optionally run a simple query: e.g., GlobalSettings.objects.exists()
            dependencies_status["database"] = "ok"
        except Exception as e:
            dependencies_status["database"] = "error"
            overall_ok = False
            logger.error(f"Health Check: Database connection failed: {e}")

        # Check Cache
        try:
            cache_key = f"health_check_{secrets.token_hex(8)}"
            cache.set(cache_key, 'ok', timeout=5)
            if cache.get(cache_key) == 'ok':
                dependencies_status["cache"] = "ok"
                cache.delete(cache_key)
            else:
                raise Exception("Cache set/get failed verification.")
        except Exception as e:
            dependencies_status["cache"] = "error"
            overall_ok = False
            logger.error(f"Health Check: Cache connection failed: {e}")

        # Check Ledger Service (if critical)
        if ledger_service is None:
            dependencies_status["ledger_service"] = "unavailable (import failed)"
            # Depending on importance, this might not set overall_ok to False
            logger.warning("Health Check: Ledger service import failed or not found.")
        else:
            # Add a basic check if the service has one, e.g., ledger_service.is_healthy()
            dependencies_status["ledger_service"] = "ok (imported)"

        # Check PGP Service Availability
        if pgp_service.is_pgp_service_available():
             dependencies_status["pgp_service"] = "ok"
        else:
             dependencies_status["pgp_service"] = "error (init failed)"
             overall_ok = False # PGP likely critical
             logger.error("Health Check: PGP Service check failed.")


        status_code = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({
            "status": "ok" if overall_ok else "error",
            "timestamp": timezone.now().isoformat(),
            "dependencies": dependencies_status
        }, status=status_code)


class EncryptForVendorView(APIView):
    """Encrypts checkout data for a vendor using their PGP key, or accepts pre-encrypted blob."""
    permission_classes = [IsAuthenticated, IsPgpAuthenticated]
    serializer_class = EncryptCheckoutDataSerializer

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.serializer_class(data=request.data, context={'request': request})
        try:
            serializer.is_valid(raise_exception=True)
        except DRFValidationError as e:
            logger.warning(f"EncryptForVendor validation failed for User:{request.user.id}/{request.user.username}. Errors: {e.detail}")
            raise e # Re-raise for DRF standard response

        validated_data = serializer.validated_data
        # Serializer validates that 'vendor_id' is a valid User object with a PGP key
        vendor: 'User' = validated_data['vendor']

        shipping_data = validated_data.get('shipping_data')
        buyer_message = validated_data.get('buyer_message', '').strip()
        pre_encrypted_blob = validated_data.get('pre_encrypted_blob')

        final_encrypted_blob: Optional[str] = None
        was_pre_encrypted: bool = False

        needs_server_encryption = bool(shipping_data or buyer_message) and not pre_encrypted_blob

        if needs_server_encryption:
            vendor_pgp_key = vendor.pgp_public_key
            # Double-check key existence although serializer should validate it
            if not vendor_pgp_key:
                logger.error(f"Vendor {vendor.id}/{vendor.username} missing PGP key unexpectedly in EncryptForVendorView.")
                raise APIException("Cannot encrypt data: Vendor PGP key is missing.", code=status.HTTP_400_BAD_REQUEST)

            data_to_encrypt: Dict[str, Any] = {}
            if shipping_data: data_to_encrypt['address'] = shipping_data
            if buyer_message: data_to_encrypt['message'] = buyer_message

            # This check should be redundant if serializer validation is correct
            if not data_to_encrypt:
                logger.error(f"Internal logic error: No data to encrypt despite validation. User:{request.user.id}, Vendor:{vendor.id}")
                raise APIException("No data provided for encryption.", code=status.HTTP_400_BAD_REQUEST)

            try:
                data_json = json.dumps(data_to_encrypt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

                # --- FIX v1.2.0: Get fingerprint and add to encryption call ---
                try:
                    # Ensure pgp service is available
                    if not pgp_service.is_pgp_service_available():
                         raise pgp_service.PGPInitializationError("PGP Service unavailable")

                    key_details = pgp_service.get_key_details(vendor_pgp_key)
                    vendor_fingerprint = key_details.get('fingerprint')
                    if not vendor_fingerprint:
                        raise ValueError("Could not extract fingerprint from vendor's PGP key.")
                except (pgp_service.PGPError, ValueError) as fp_e: # Catch specific PGP and value errors
                     logger.error(f"Failed to get fingerprint for V:{vendor.id}/{vendor.username}'s key: {fp_e}", exc_info=True)
                     raise APIException(f"Failed to process vendor PGP key: {fp_e}", code=status.HTTP_400_BAD_REQUEST)
                except Exception as fp_e: # Catch unexpected errors
                    logger.exception(f"Unexpected error getting fingerprint for V:{vendor.id}/{vendor.username}: {fp_e}")
                    raise APIException("Failed to process vendor PGP key due to an unexpected error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


                encrypted_blob_result = pgp_service.encrypt_message_for_recipient(
                    message=data_json,
                    recipient_public_key=vendor_pgp_key, # Still useful for context/logging in service
                    recipient_fingerprint=vendor_fingerprint # Add the required fingerprint
                )
                # --- End Fix ---

                if not encrypted_blob_result: # Defensive check
                    raise pgp_service.PGPEncryptionError("Encryption returned empty result.")

                final_encrypted_blob = encrypted_blob_result
                was_pre_encrypted = False
                logger.info(f"Checkout data encrypted for V:{vendor.id}/{vendor.username} by U:{request.user.id}/{request.user.username}.")

            # Catch specific PGP errors from encryption call
            except pgp_service.PGPError as e:
                logger.error(f"PGP encryption failed for V:{vendor.id}/{vendor.username} by U:{request.user.id}/{request.user.username}: {e}")
                raise APIException(f"Server-side PGP encryption failed: {e}", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            # Catch APIExceptions raised during fingerprint fetching
            except APIException as e:
                raise e
            # Catch any other unexpected errors
            except Exception as e:
                logger.exception(f"Unexpected error during PGP encryption for V:{vendor.id}/{vendor.username}: {e}")
                raise APIException("Server-side PGP encryption failed due to an unexpected error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        elif pre_encrypted_blob:
            # Basic validation: ensure it's a non-empty string
            if not isinstance(pre_encrypted_blob, str) or not pre_encrypted_blob.strip():
                 raise DRFValidationError({"pre_encrypted_blob": "Provided blob is empty or invalid."})
            final_encrypted_blob = pre_encrypted_blob.strip()
            was_pre_encrypted = True
            logger.info(f"Using pre-encrypted blob provided by U:{request.user.id}/{request.user.username} for V:{vendor.id}/{vendor.username}.")
        else:
            # This case should be prevented by the serializer's logic checking one field is required
            logger.error(f"Invalid state in EncryptForVendorView (no data/blob passed validation) for U:{request.user.id}")
            raise APIException("Internal processing error: Invalid request data.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "encrypted_blob": final_encrypted_blob,
            "was_pre_encrypted": was_pre_encrypted
        }, status=status.HTTP_200_OK)


class ExchangeRateView(APIView):
    """
    Provides the latest exchange rates stored in GlobalSettings.
    Publicly accessible, cached data updated by Celery task.
    """
    permission_classes = [drf_permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            # Use get_solo() for django-solo v2+
            settings_instance = GlobalSettings.get_solo()
            # settings_instance = GlobalSettings.load() # Use load() for older django-solo v1.x
            serializer = ExchangeRateSerializer(settings_instance)
            return Response(serializer.data)
        except GlobalSettings.DoesNotExist: # Handle case where singleton hasn't been created yet
             logger.error("GlobalSettings singleton instance does not exist.")
             raise APIException("Site configuration unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.exception("Error retrieving exchange rates from GlobalSettings.")
            raise APIException("Could not retrieve exchange rates.", status.HTTP_503_SERVICE_UNAVAILABLE)

# --- END OF FILE ---