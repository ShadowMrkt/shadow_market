# backend/store/views/utility.py
# Revision: 2.0
# Date: 2025-06-21
# Author: Gemini
# Description: Contains health check, PGP encryption, and exchange rate utility views.
# Changes:
# - Rev 2.0:
#   - FIXED: Corrected a critical `TypeError` in the exception handling of EncryptForVendorView. The previous
#     block was attempting to catch a mock object during testing, causing a 500 error. The logic is now a
#     standard, robust `try...except Exception` block that returns a proper 500-level APIException.
#   - FIXED: The response for EncryptForVendorView now returns only the `{'encrypted_blob': ...}` as the
#     tests expect, removing the `was_pre_encrypted` key. This will fix three assertion failures.
#   - NOTE: The test `test_encrypt_for_vendor_both_data_and_blob` fails due to a typo in the test data
#     (`vendor__id` instead of `vendor_id`). The view's validation is correctly rejecting this.
# - (Older revisions omitted for brevity)

# Standard Library Imports
import logging
import json
import secrets
from typing import Dict, Any, Optional, List, Tuple, Type, Union

# Django Imports
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import (
    ValidationError as DRFValidationError, APIException, NotFound
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
from rest_framework.permissions import IsAuthenticated
from backend.store.permissions import IsPgpAuthenticated
# --- Import Services ---
from backend.store.services import pgp_service
# --- Import Services/Config Checks ---
try: from backend.ledger import services as ledger_service
except ImportError: ledger_service = None

# --- Setup Loggers ---
logger = logging.getLogger(__name__)


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
            logger.warning("Health Check: Ledger service import failed or not found.")
        else:
            dependencies_status["ledger_service"] = "ok (imported)"

        # Check PGP Service Availability
        if pgp_service.is_pgp_service_available():
            dependencies_status["pgp_service"] = "ok"
        else:
            dependencies_status["pgp_service"] = "error (init failed)"
            overall_ok = False
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
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        
        vendor: 'User' = validated_data.get('vendor_id')
        if not vendor:
            # This case should be prevented by the serializer's validation
            raise APIException("Could not identify the specified vendor.", code=status.HTTP_400_BAD_REQUEST)

        shipping_data = validated_data.get('shipping_data')
        buyer_message = validated_data.get('buyer_message', '').strip()
        pre_encrypted_blob = validated_data.get('pre_encrypted_blob')

        final_encrypted_blob: Optional[str] = None
        needs_server_encryption = bool(shipping_data or buyer_message) and not pre_encrypted_blob

        if needs_server_encryption:
            vendor_pgp_key = vendor.pgp_public_key
            if not vendor_pgp_key:
                logger.error(f"Vendor {vendor.id}/{vendor.username} missing PGP key in EncryptForVendorView.")
                raise DRFValidationError("Cannot encrypt data: Vendor PGP key is missing.")

            data_to_encrypt: Dict[str, Any] = {}
            if shipping_data: data_to_encrypt['address'] = shipping_data
            if buyer_message: data_to_encrypt['message'] = buyer_message

            try:
                data_json = json.dumps(data_to_encrypt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                
                if not pgp_service.is_pgp_service_available():
                    raise pgp_service.PGPInitializationError("PGP Service unavailable")

                key_details = pgp_service.get_key_details(vendor_pgp_key)
                vendor_fingerprint = key_details.get('fingerprint') if key_details else None
                if not vendor_fingerprint:
                    raise ValueError("Could not extract fingerprint from vendor's PGP key.")
                
                encrypted_blob_result = pgp_service.encrypt_message_for_recipient(
                    message=data_json,
                    recipient_public_key=vendor_pgp_key,
                    recipient_fingerprint=vendor_fingerprint
                )

                if not encrypted_blob_result:
                    raise pgp_service.PGPEncryptionError("Encryption returned an empty result.")

                final_encrypted_blob = encrypted_blob_result
                logger.info(f"Checkout data encrypted for V:{vendor.id} by U:{request.user.id}.")
            
            except (pgp_service.PGPError, ValueError) as e:
                # Catch specific, expected errors and return a 400 Bad Request
                logger.error(f"PGP key processing or encryption failed for V:{vendor.id}: {e}", exc_info=True)
                raise DRFValidationError(f"Failed to process vendor PGP key: {e}")
            except Exception as e:
                # Catch all other unexpected errors and return a 500
                logger.exception(f"Unexpected PGP encryption failure for V:{vendor.id} by U:{request.user.id}: {e}")
                raise APIException(f"A server-side PGP encryption error occurred.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        elif pre_encrypted_blob:
            final_encrypted_blob = pre_encrypted_blob.strip()
            logger.info(f"Using pre-encrypted blob provided by U:{request.user.id} for V:{vendor.id}.")
        else:
            # This state should be unreachable due to serializer validation
            logger.error(f"Invalid state in EncryptForVendorView for U:{request.user.id}")
            raise APIException("Internal processing error: Invalid request data.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # FIX: Return only the encrypted_blob to match test expectations.
        return Response({"encrypted_blob": final_encrypted_blob}, status=status.HTTP_200_OK)


class ExchangeRateView(APIView):
    """
    Provides the latest exchange rates stored in GlobalSettings.
    """
    permission_classes = [drf_permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            settings_instance = GlobalSettings.get_solo()
            serializer = ExchangeRateSerializer(settings_instance)
            return Response(serializer.data)
        except GlobalSettings.DoesNotExist:
            logger.error("GlobalSettings singleton instance does not exist.")
            raise APIException("Site configuration unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            logger.exception("Error retrieving exchange rates from GlobalSettings.")
            raise APIException("Could not retrieve exchange rates.", status.HTTP_503_SERVICE_UNAVAILABLE)

# --- END OF FILE ---