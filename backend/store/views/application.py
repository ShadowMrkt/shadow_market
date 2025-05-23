# backend/store/views/application.py
# --- Revision History ---
# - v1.2 (2025-05-03): Correct import for IsAuthenticated to use rest_framework.permissions. (Gemini)
# - v1.1 (2025-04-29): Updated helper imports to use backend.store.utils.utils. (Gemini)
# - v1.0 (2025-04-29): Initial split, absolute imports, old helper path. (Gemini)
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
# --- Import Models ---
from backend.store.models import User, VendorApplication, GlobalSettings, Currency
# --- Import Serializers ---
from backend.store.serializers import VendorApplicationSerializer
# --- Import Permissions ---
# from backend.store.permissions import IsAuthenticated, IsPgpAuthenticated # Old combined import
from rest_framework.permissions import IsAuthenticated # Standard DRF permission
from backend.store.permissions import IsPgpAuthenticated # Custom permission
# --- Import Services ---
# Assuming bitcoin_service exists and has the required methods
# If exchange_rate_service is a separate module/class, import it properly
from backend.store.services import bitcoin_service
from backend.store.services import exchange_rate_service # Make sure this service exists and is importable
# --- Import Helpers ---
# from backend.store.views.helpers import get_client_ip, log_audit_event # Old path - Rev 1.0
from backend.store.utils.utils import get_client_ip, log_audit_event # New path - Rev 1.1

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not directly used here


# --- Vendor Application Views ---

class VendorApplicationCreateView(generics.CreateAPIView):
    """
    Allows authenticated users to initiate a vendor application.
    Requires PGP authenticated session.
    Handles bond calculation (USD), BTC address generation, and record creation.
    Bond is payable ONLY in BTC.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [IsAuthenticated, IsPgpAuthenticated] # Secure endpoint

    def perform_create(self, serializer: VendorApplicationSerializer) -> None:
        """
        Custom logic executed before saving the serializer instance.
        Validates user status, gets bond amount, generates BTC address, saves application.
        """
        user: 'User' = self.request.user
        log_prefix = f"[VendorApp Create U:{user.id}/{user.username}]"

        # 1. Validation Checks (Prevent duplicates, staff application)
        if user.is_vendor: raise DRFValidationError({"detail": "You are already an approved vendor."})
        if user.is_staff: raise DRFValidationError({"detail": "Staff members cannot apply to be vendors via this form."})

        existing_app = VendorApplication.objects.filter(user=user).exclude(
            status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]
        ).first()
        if existing_app:
            logger.warning(f"{log_prefix} Attempted new app, found existing App:{existing_app.id} Status:{existing_app.status}")
            existing_serializer = self.get_serializer(existing_app);
            raise DRFValidationError({
                "detail": "You already have a vendor application in progress or approved.",
                "existing_application": existing_serializer.data
            })

        # 2. Get Bond Amount (USD) from Settings
        try:
            settings_instance = GlobalSettings.load();
            bond_usd = settings_instance.default_vendor_bond_usd
            if not bond_usd or bond_usd <= Decimal('0.0'):
                raise ValueError("Vendor bond USD amount not configured or invalid.")
        except Exception as e:
            logger.error(f"{log_prefix} Error loading vendor bond USD setting: {e}")
            raise APIException("Vendor bond amount not configured correctly.", status.HTTP_503_SERVICE_UNAVAILABLE)

        # 3. Calculate BTC equivalent using Exchange Rate Service
        bond_btc_amount: Optional[Decimal] = None
        try:
            bond_btc_amount = exchange_rate_service.convert_usd_to_crypto(bond_usd, Currency.BTC)
            if bond_btc_amount is None or bond_btc_amount <= Decimal('0.0'):
                raise ValueError(f"Could not convert USD bond to BTC or result was invalid.")
            logger.info(f"{log_prefix} Calculated BTC bond: {bond_btc_amount} BTC (for ${bond_usd} USD)")
        except ValueError as ve:
            logger.error(f"{log_prefix} Error converting bond to BTC: {ve}")
            raise APIException("Could not calculate bond amount in BTC. Rates unavailable?", status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error converting bond: {e}")
            raise APIException("Could not calculate bond amount in BTC. Service error.", status.HTTP_503_SERVICE_UNAVAILABLE)

        # 4. Save Initial Application Record (within a transaction) to get ID
        instance: Optional[VendorApplication] = None
        btc_payment_address: Optional[str] = None
        try:
            with transaction.atomic():
                # Save initial instance without address first
                instance = serializer.save(
                    user=user,
                    status=VendorApplication.StatusChoices.PENDING_BOND,
                    bond_currency=Currency.BTC, # Hardcoded to BTC
                    bond_amount_usd=bond_usd,
                    bond_amount_crypto=bond_btc_amount,
                    bond_payment_address=None # Temporarily None
                )
                logger.info(f"{log_prefix} VendorApplication {instance.id} initial save OK.")

                # 5. Generate Unique BTC Deposit Address using the new instance ID
                try:
                    logger.debug(f"{log_prefix} Requesting BTC deposit address for App ID: {instance.id}...")
                    # Assumes bitcoin_service provides this function
                    btc_payment_address = bitcoin_service.get_new_vendor_bond_deposit_address(instance.id)
                    if not btc_payment_address:
                        raise ValueError(f"Bitcoin service failed to generate a deposit address for App ID: {instance.id}.")
                    logger.info(f"{log_prefix} Generated BTC deposit address: {btc_payment_address[:10]}...")

                    # 6. CRITICAL: Import address to Bitcoin node with label
                    label = f"VendorAppBond_{instance.id}"
                    # Assumes bitcoin_service provides this function
                    import_success = bitcoin_service.import_btc_address_to_node(address=btc_payment_address, label=label)
                    if not import_success:
                        logger.critical(f"{log_prefix} FAILED to import BTC address '{btc_payment_address}' label '{label}' to node for App ID: {instance.id}. Rolling back.")
                        raise APIException("Failed to register payment address with node.", status.HTTP_500_INTERNAL_SERVER_ERROR)
                    else:
                        logger.info(f"{log_prefix} Imported BTC address '{btc_payment_address}' label '{label}' to node for App ID: {instance.id}.")

                    # 7. Update the application record with the generated address
                    instance.bond_payment_address = btc_payment_address
                    instance.save(update_fields=['bond_payment_address'])
                    logger.info(f"{log_prefix} Updated VendorApplication {instance.id} with payment address.")

                except Exception as crypto_e:
                    logger.exception(f"{log_prefix} Error during BTC address generation/import for App ID: {instance.id}. Rolling back.")
                    # Raise specific error if possible, otherwise generic APIException
                    raise APIException("Failed to generate or register payment address.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # If transaction successful
            log_audit_event(self.request, user, 'vendor_app_initiate', target_application=instance, details=f"AppID:{instance.id} Curr:BTC")

        except IntegrityError as ie:
            logger.error(f"{log_prefix} Database integrity error saving application: {ie}")
            raise APIException("Failed to save application due to data conflict.", status.HTTP_409_CONFLICT)
        except APIException as ae:
            # Re-raise APIExceptions from inner blocks
            raise ae
        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error saving VendorApplication instance.")
            raise APIException("Failed to save vendor application record.", status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Ensure the serializer instance used for the response is the final, updated one
        serializer.instance = instance


class VendorApplicationStatusView(generics.RetrieveAPIView):
    """
    Allows an authenticated user to check the status of their vendor application.
    Returns the latest non-cancelled/non-rejected application, or latest rejected.
    """
    serializer_class = VendorApplicationSerializer
    permission_classes = [IsAuthenticated] # Use DRF's IsAuthenticated here

    def get_object(self) -> VendorApplication: # Specify return type
        user = self.request.user
        try:
            # Prioritize active/pending applications
            application = VendorApplication.objects.filter(user=user).exclude(
                status__in=[VendorApplication.StatusChoices.REJECTED, VendorApplication.StatusChoices.CANCELLED]
            ).order_by('-created_at').first()

            if not application:
                # If no active/pending, check for the latest rejected one
                rejected_app = VendorApplication.objects.filter(
                    user=user, status=VendorApplication.StatusChoices.REJECTED
                ).order_by('-created_at').first()
                if rejected_app:
                    return rejected_app
                else:
                    # No application found at all
                    raise NotFound("No vendor application found for your account.")
            return application
        except NotFound:
             # Re-raise NotFound specifically so DRF handles it as 404
            raise
        except Exception as e:
            logger.exception(f"Error retrieving vendor app status for U:{user.id}")
            raise APIException("Could not retrieve application status.", status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- END OF FILE ---