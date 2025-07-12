# backend/store/views/application.py
# --- Revision History ---
# - v2.0 (2025-06-21): Implemented robust error handling and data validation. (Gemini)
#   - FIXED: Added a specific `except ValueError` block for bond calculation to ensure a 503 Service Unavailable is raised if the exchange rate service fails, preventing a generic 500 error.
#   - FIXED: Added a validation check after the `bitcoin_service.get_new_vendor_bond_deposit_address` call. The view now ensures the returned address is a valid string before attempting to save it, preventing a FieldError crash when the service returns an unexpected type (like a mock object in tests).
# - v1.4 (2025-06-11): Refactored exception handling in perform_create to be more specific. (Gemini)
# - (Older revisions omitted for brevity)
# --- END Revision History ---
# Description: Contains views for creating and checking Vendor Applications.

# Standard Library Imports
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple, Type, Union

# Django Imports
from django.conf import settings
from django.db import transaction, IntegrityError

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import (
    ValidationError as DRFValidationError, APIException, NotFound
)
from rest_framework.response import Response
from rest_framework.request import Request

# --- Local Imports (Using absolute paths from 'backend') ---
from backend.store.models import User, VendorApplication, GlobalSettings, Currency
from backend.store.serializers import VendorApplicationSerializer
from rest_framework.permissions import IsAuthenticated
from backend.store.permissions import IsPgpAuthenticated
from backend.store.services import bitcoin_service
from backend.store.services import exchange_rate_service
from backend.store.utils.utils import get_client_ip, log_audit_event

logger = logging.getLogger(__name__)

# --- Vendor Application Views ---

class VendorApplicationCreateView(generics.CreateAPIView):
    """
    Allows authenticated users to initiate a vendor application.
    Requires PGP authenticated session.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [IsAuthenticated, IsPgpAuthenticated]

    def perform_create(self, serializer: VendorApplicationSerializer) -> None:
        """
        Custom logic to validate user status, calculate bond, generate address, and save application.
        """
        user: 'User' = self.request.user
        log_prefix = f"[VendorApp Create U:{user.id}/{user.username}]"

        # 1. Validation Checks
        if user.is_vendor:
            raise DRFValidationError({"detail": "You are already an approved vendor."})
        if user.is_staff:
            raise DRFValidationError({"detail": "Staff members cannot apply to be vendors via this form."})

        existing_app = VendorApplication.objects.filter(user=user).exclude(
            status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]
        ).first()
        if existing_app:
            logger.warning(f"{log_prefix} Attempted new app, found existing App:{existing_app.id} Status:{existing_app.status}")
            raise DRFValidationError({
                "detail": "You already have a vendor application in progress or approved.",
                "existing_application": self.get_serializer(existing_app).data
            })

        # 2. Get Bond Amount (USD) and Calculate BTC equivalent
        try:
            settings_instance = GlobalSettings.get_solo()
            bond_usd = settings_instance.default_vendor_bond_usd
            if not bond_usd or bond_usd <= Decimal('0.0'):
                raise ValueError("Vendor bond USD amount not configured or invalid.")

            bond_btc_amount = exchange_rate_service.convert_usd_to_crypto(bond_usd, Currency.BTC)
            if bond_btc_amount is None or bond_btc_amount <= Decimal('0.0'):
                raise ValueError("Could not convert USD bond to BTC or result was invalid.")
            logger.info(f"{log_prefix} Calculated BTC bond: {bond_btc_amount} BTC (for ${bond_usd} USD)")

        # FIX: Catch specific ValueError from bond calculation and raise a 503.
        except ValueError as e:
            logger.error(f"{log_prefix} Error calculating bond, likely an exchange rate service issue: {e}")
            raise APIException("Could not calculate bond amount. Rates may be unavailable or settings misconfigured.", status.HTTP_503_SERVICE_UNAVAILABLE) from e
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error during bond calculation: {e}")
            raise APIException("An unexpected service error occurred while calculating the bond.", status.HTTP_500_INTERNAL_SERVER_ERROR) from e

        # 3. Create Application and Deposit Address within a single transaction
        try:
            with transaction.atomic():
                instance = serializer.save(
                    user=user,
                    status=VendorApplication.StatusChoices.PENDING_BOND,
                    bond_currency=Currency.BTC,
                    bond_amount_usd=bond_usd,
                    bond_amount_crypto=bond_btc_amount
                )
                logger.info(f"{log_prefix} VendorApplication {instance.id} initial save OK.")

                # Generate and import BTC address
                try:
                    btc_payment_address = bitcoin_service.get_new_vendor_bond_deposit_address(instance.id)
                    # FIX: Validate the output from the service before using it.
                    if not isinstance(btc_payment_address, str) or not btc_payment_address:
                        logger.error(f"{log_prefix} Bitcoin service returned invalid address: type={type(btc_payment_address).__name__}. Rolling back.")
                        raise APIException("Bitcoin service failed to generate a valid deposit address.", status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
                    label = f"VendorAppBond_{instance.id}"
                    import_success = bitcoin_service.import_btc_address_to_node(address=btc_payment_address, label=label)
                    if not import_success:
                        raise APIException("Failed to register payment address with node.", status.HTTP_500_INTERNAL_SERVER_ERROR)

                    instance.bond_payment_address = btc_payment_address
                    instance.save(update_fields=['bond_payment_address'])
                    logger.info(f"{log_prefix} Updated VendorApplication {instance.id} with payment address.")
                
                except APIException:
                    raise # Re-raise specific APIExceptions from the crypto service to preserve status/detail
                except Exception as crypto_e:
                    logger.exception(f"{log_prefix} Unexpected crypto service error for App ID: {instance.id}. Rolling back.")
                    raise APIException("An unexpected error occurred with the payment service.", status.HTTP_500_INTERNAL_SERVER_ERROR) from crypto_e

            # If transaction is successful, log the audit event
            log_audit_event(self.request, user, 'vendor_app_initiate', target_application=instance)
            serializer.instance = instance # Ensure the final response uses the updated instance

        except (IntegrityError, APIException):
            # Let DRF handle IntegrityError or re-raise our specific APIException
            raise
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error saving VendorApplication instance.")
            raise APIException("An unexpected internal error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)


class VendorApplicationStatusView(generics.RetrieveAPIView):
    """
    Allows an authenticated user to check the status of their vendor application.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self) -> VendorApplication:
        user = self.request.user
        try:
            # Prioritize active/pending applications
            application = VendorApplication.objects.filter(user=user).exclude(
                status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]
            ).order_by('-created_at').first()

            if not application:
                # If no active/pending, check for the latest rejected one
                application = VendorApplication.objects.filter(
                    user=user, status=VendorApplication.StatusChoices.REJECTED
                ).order_by('-created_at').first()

            if not application:
                raise NotFound("No vendor application found for your account.")
            
            return application
        except NotFound:
            raise
        except Exception as e:
            logger.exception(f"Error retrieving vendor app status for U:{user.id}")
            raise APIException("Could not retrieve application status.", status.HTTP_500_INTERNAL_SERVER_ERROR) from e

# --- END OF FILE ---