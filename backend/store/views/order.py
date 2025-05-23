# backend/store/views/order.py
# Revision: 1.6
# Date: 2025-05-18
# Author: Gemini
# Description: Contains Order creation, listing, detail, and action views.
# Changes:
# - Rev 1.6 (2025-05-18):
#   - Modified service imports due to the constraint that 'backend/store/services/__init__.py' must remain blank.
#   - Replaced `from backend.store.services import escrow_service, dispute_service` with logic to:
#     - Import `common_escrow_utils` directly from `backend.store.services` and alias it as `escrow_service`.
#     - Attempt to import `dispute_service` directly from `backend.store.services.dispute_service`.
#     - If `dispute_service.py` (the module) is not found, check if `common_escrow_utils` provides dispute functionality (e.g., an 'open_dispute' method).
#     - If `dispute_service` still cannot be sourced, a placeholder is assigned that will raise NotImplementedError upon use, guiding further fixes.
#   - This change directly addresses the ImportError for 'escrow_service' by removing reliance on a populated __init__.py for these names.
#   - Added _PlaceholderService class for robust handling of missing dispute_service.
# - Rev 1.5 (2025-05-03):
#   - Reverted service import back to package level (from backend.store.services import ...)
#     based on analysis that this is the intended pattern. Root cause likely in
#     services/__init__.py or missing service definitions.
# - Rev 1.4 (2025-05-03):
#   - Fixed ImportError by changing service imports to be direct from their assumed modules
#     (e.g., backend.store.services.escrow) instead of the services package itself. (Incorrect Assumption)
# - Rev 1.3 (2025-04-29):
#   - Updated helper imports to use backend.store.utils.utils.
# - Rev 1.2 (2025-04-29):
#   - ADDED: PrepareReleaseTxView, SignReleaseView, OpenDisputeView.
#   - ADDED: Imports for PrepareReleaseTxSerializer, SignReleaseSerializer, OpenDisputeSerializer.
#   - Ensured new views use the correct serializers.
#   - Updated docstrings and logging for new views.
# - Rev 1.0 (Split from views.py Rev 4.7):
#   - Initial split of PlaceOrderView, OrderViewSet, OrderActionBaseView, MarkShippedView, FinalizeOrderView.
#   - Using absolute imports from 'backend' root.
#   - Imported helpers get_client_ip, log_audit_event from backend.store.views.helpers. # Old path
# History from views.py Rev 4.7 relevant to these views:
# - (Relevant service call updates/exception handling improvements might apply from original file's history).

# Standard Library Imports
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Tuple, Type, Union, TYPE_CHECKING

# Django Imports
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models # Added for OrderActionBaseView PK type check
from django.db.models import Q, Prefetch
from django.http import Http404
from django.utils.module_loading import import_string
from django.utils import timezone # Added for dispute deadline check
from django.utils.translation import gettext_lazy as _ # For dispute messages
# --- Type Hinting ---
if TYPE_CHECKING:
    from django.db.models.query import QuerySet
    from backend.store.models import User # Ensure User type hint is available

# Third-Party Imports
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, viewsets, status, permissions as drf_permissions
from rest_framework import filters as drf_filters
from rest_framework.decorators import action # For custom actions on ViewSet if needed
from rest_framework.exceptions import (
    PermissionDenied, NotAuthenticated, NotFound, ValidationError as DRFValidationError,
    APIException
)
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User, Order, Product, Feedback, SupportTicket, CryptoPayment, Dispute # Added Dispute
# Define OrderStatusChoices alias for clarity if preferred
OrderStatusChoices = Order.StatusChoices
# --- Import Serializers ---
from backend.store.serializers import (
    OrderBuyerSerializer, OrderVendorSerializer, OrderBaseSerializer,
    PrepareReleaseTxSerializer, SignReleaseSerializer, OpenDisputeSerializer # Added Release/Dispute serializers
)
# --- Import Permissions ---
from backend.store.permissions import (
    IsPgpAuthenticated, IsBuyerOrVendorOfOrder, IsVendor, IsBuyer # Added IsBuyer
)

# --- Setup Loggers (early for _PlaceholderService) ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# --- Placeholder for missing services ---
class _PlaceholderService:
    def __init__(self, service_name="unknown_service"):
        self._service_name = service_name
        logger.error(
            f"Service '{self._service_name}' is using a placeholder. "
            f"Its actual module needs to be imported and assigned, or it's missing."
        )
    def __getattr__(self, name):
        raise NotImplementedError(
            f"The service '{self._service_name}' is not properly configured or is missing. "
            f"Attempted to access attribute/method '{name}'."
        )
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"The service '{self._service_name}' is not properly configured or is missing. "
            f"Attempted to call the service."
        )

# --- Import Services ---
# Due to blank services/__init__.py, we import specific modules directly.
try:
    from backend.store.services import common_escrow_utils
    escrow_service = common_escrow_utils
    logger.info("Successfully imported 'common_escrow_utils' as 'escrow_service'.")
except ImportError as e:
    logger.critical(f"Failed to import 'common_escrow_utils' from 'backend.store.services': {e}. Using placeholder for 'escrow_service'.")
    escrow_service = _PlaceholderService("escrow_service")

try:
    # Attempt to import a dedicated dispute_service.py module
    from backend.store.services import dispute_service as dispute_service_module
    dispute_service = dispute_service_module
    logger.info("Successfully imported 'dispute_service' module.")
except ImportError:
    # Fallback: Check if common_escrow_utils (already imported as escrow_service) handles disputes
    logger.warning("'dispute_service.py' module not found. Checking if 'common_escrow_utils' provides dispute functionality.")
    if hasattr(escrow_service, 'open_dispute') and callable(getattr(escrow_service, 'open_dispute')):
        logger.info("Using 'common_escrow_utils' (aliased as 'escrow_service') as the provider for 'dispute_service' functionality.")
        dispute_service = escrow_service # common_escrow_utils handles both
    else:
        logger.error("'common_escrow_utils' does not appear to provide 'open_dispute' method. Using placeholder for 'dispute_service'.")
        dispute_service = _PlaceholderService("dispute_service")


# --- Import Exceptions ---
from backend.store.exceptions import EscrowError, CryptoProcessingError, DisputeError # Added DisputeError
# --- Import Notifications (Optional) ---
try:
    from backend.notifications.services import create_notification
except ImportError:
    def create_notification(*args: Any, **kwargs: Any) -> None: pass
# --- Import Helpers ---
from backend.store.utils.utils import get_client_ip, log_audit_event # New path - Rev 1.3

# --- Constants ---
DEFAULT_PAGINATION_CLASS_SETTING: str = 'DEFAULT_PAGINATION_CLASS'


# --- Order Views ---

class PlaceOrderView(generics.CreateAPIView):
    """Handles the creation of a new order by a buyer (Requires PGP Auth)."""
    permission_classes = [drf_permissions.IsAuthenticated, IsPgpAuthenticated]
    serializer_class = OrderBuyerSerializer # Serializer for the response
    # throttle_classes = [PlaceOrderThrottle] # Apply rate limiting if scope defined

    # --- Helper methods for validation (Internal to this View) ---
    def _validate_request_data(self, data: Dict[str, Any]) -> Tuple[Union[int, str], int, str, Optional[str], Optional[str]]: # Allow Product ID to be str initially
        """ Validate basic incoming request data fields. Returns validated data or raises DRFValidationError. """
        product_id_str = data.get('product_id')
        quantity_str = data.get('quantity', '1') # Default quantity to 1
        selected_currency = data.get('selected_currency')
        shipping_option_name = data.get('shipping_option_name') # Optional, checked later
        encrypted_shipping_blob = data.get('encrypted_shipping_blob') # Optional, checked later

        errors: Dict[str, List[str]] = {}
        if not product_id_str: errors.setdefault('product_id', []).append("This field is required.")
        if not selected_currency: errors.setdefault('selected_currency', []).append("This field is required.")

        product_id: Optional[Union[int, str]] = None # Keep as string if UUID, convert to int if integer PK
        quantity: int = 1 # Default

        # Validate Product ID (Accept int or UUID-like string) - Actual type depends on Product model PK
        if product_id_str:
            # Basic check - adapt if PK is always int or always UUID
            if isinstance(product_id_str, int):
                product_id = product_id_str
            elif isinstance(product_id_str, str):
                # Add more specific validation if needed (e.g., isdigit() for int, regex for UUID)
                product_id = product_id_str # Keep as string for now, validation happens during Product.objects.get
            else:
                errors.setdefault('product_id', []).append("Invalid product ID format.")
        # else: # Covered by 'required' check above

        # Validate Quantity
        try:
            quantity = int(quantity_str)
            if quantity < 1:
                errors.setdefault('quantity', []).append("Quantity must be at least 1.")
        except (ValueError, TypeError):
            errors.setdefault('quantity', []).append("Invalid quantity provided.")

        # Basic currency format check (adjust if supporting non-standard codes)
        if selected_currency and (not isinstance(selected_currency, str) or len(selected_currency) > 10 or not selected_currency.isalnum()): # Allow numbers if needed
            errors.setdefault('selected_currency', []).append("Invalid currency format.")

        if errors:
            raise DRFValidationError(errors)

        # Ensure product_id was set
        if product_id is None:
            # This path shouldn't be reached if required validation works, but safety check.
            raise DRFValidationError({"product_id": "Product ID is required."})

        return product_id, quantity, str(selected_currency).upper(), shipping_option_name, encrypted_shipping_blob

    def _validate_product_and_options(
        self, user: 'User', product: Product, quantity: int, selected_currency: str,
        shipping_option_name: Optional[str], encrypted_shipping_blob: Optional[str]
    ) -> Tuple[Decimal, Optional[Dict[str, Any]], Decimal]:
        """ Validate product rules, stock, currency, shipping. Returns (price_native, shipping_option_dict, shipping_price_native) or raises DRFValidationError/NotFound. """

        if not product.is_active:
            raise NotFound(detail="The requested product is not active or available.")

        if product.vendor == user:
            raise DRFValidationError({"detail": "You cannot place an order for your own product."})

        # Check Stock
        # Ensure product.quantity is treated correctly (could be None for unlimited)
        if product.quantity is not None:
            try:
                if quantity > int(product.quantity):
                    raise DRFValidationError({"quantity": f"Insufficient stock. Only {product.quantity} available."})
            except (ValueError, TypeError):
                logger.error(f"Invalid stock quantity type for Product ID {product.id}: {product.quantity}")
                raise APIException("Internal error: Invalid product stock configuration.")


        # Check Currency Acceptance
        # Use safer getattr with default
        get_currencies_method = getattr(product, 'get_accepted_currencies_list', None)
        accepted_currencies = get_currencies_method() if callable(get_currencies_method) else []
        # accepted_currencies = getattr(product, 'get_accepted_currencies_list', lambda: [])() # Old way

        if not accepted_currencies:
            logger.warning(f"Product ID {product.id} has no accepted currencies defined.")
            # Depending on policy, either raise error or allow if price exists? Assuming error is safer.
            raise DRFValidationError({"selected_currency": "No currencies are configured for this product."})

        if selected_currency not in accepted_currencies:
            raise DRFValidationError({"selected_currency": f"The currency '{selected_currency}' is not accepted for this product. Accepted: {', '.join(accepted_currencies)}"})

        # Get Product Price (ATOMIC units)
        # Use helper method if available, otherwise access directly
        get_price_method = getattr(product, 'get_price_native', None)
        price_native_value: Optional[Union[Decimal, str, int, float]] = None
        if callable(get_price_method):
            try:
                price_native_value = get_price_method(selected_currency)
            except Exception as e:
                logger.error(f"Error calling get_price_native for P:{product.id}, C:{selected_currency}: {e}")
                raise DRFValidationError({"selected_currency": f"Error retrieving price for '{selected_currency}'."})
        else:
            # Fallback to direct access (ensure field name matches model)
            price_field_name = f'price_{selected_currency.lower()}_native' # Assuming model has this field
            price_native_value = getattr(product, price_field_name, None)

        # Validate the retrieved price
        if price_native_value is None:
            logger.error(f"Price configuration error for Product:{product.id}, Currency:{selected_currency}")
            raise DRFValidationError({"selected_currency": f"Price is not configured for '{selected_currency}' on this product."})

        price_native: Decimal
        try:
            # Convert robustly to Decimal, handling potential strings
            price_native = Decimal(str(price_native_value))
            if price_native < Decimal('0'): # Use Decimal for comparison
                raise ValueError("Price cannot be negative")
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.error(f"Invalid price value configured P:{product.id}, C:{selected_currency}, Value:'{price_native_value}': {e}")
            raise DRFValidationError({"detail": "Internal error: Invalid product price configured."})

        # Handle Shipping for Physical Products
        shipping_option_details: Optional[Dict[str, Any]] = None
        shipping_price_native = Decimal('0.0') # ATOMIC units
        # Use safer getattr with default
        is_physical_method = getattr(product, 'is_physical', None)
        requires_shipping = is_physical_method() if callable(is_physical_method) else False
        # requires_shipping = getattr(product, 'is_physical', lambda: False)() # Old way

        if requires_shipping:
            if not encrypted_shipping_blob:
                raise DRFValidationError({"encrypted_shipping_blob": "Encrypted shipping information is required for physical products."})
            if not shipping_option_name:
                raise DRFValidationError({"shipping_option_name": "A shipping option must be selected for physical products."})

            options = product.shipping_options or []
            if not isinstance(options, list):
                logger.error(f"Invalid shipping_options format for Product:{product.id} (not a list).")
                raise APIException("Internal error: Invalid shipping configuration.")

            found_option = None
            for opt in options:
                # Ensure opt is a dictionary and has a 'name' key before accessing
                if isinstance(opt, dict) and opt.get('name') == shipping_option_name:
                    found_option = opt
                    break

            if not found_option:
                available_options = [opt.get('name', 'Unnamed Option') for opt in options if isinstance(opt, dict)]
                raise DRFValidationError({"shipping_option_name": f"Invalid shipping option selected. Available options: {', '.join(name for name in available_options if name != 'Unnamed Option')}"})

            shipping_option_details = found_option
            # Ensure we look for the NATIVE price field first
            price_key_native = f'price_{selected_currency.lower()}_native'
            shipping_price_value = shipping_option_details.get(price_key_native)

            if shipping_price_value is None:
                # Fallback to non-native field if native not found (add conversion logic if needed)
                price_key = f'price_{selected_currency.lower()}'
                shipping_price_value = shipping_option_details.get(price_key)
                if shipping_price_value is None:
                    logger.error(f"Native and non-native shipping price missing P:{product.id}, Option:'{shipping_option_name}', Curr:{selected_currency}")
                    raise DRFValidationError({"shipping_option_name": f"Shipping price not configured for currency '{selected_currency}' in this option."})
                else:
                    # TODO: Implement conversion to native units if fallback is used
                    logger.warning(f"Using fallback (non-native) shipping price for P:{product.id}, Option:'{shipping_option_name}'. Conversion needed.")
                    # Placeholder - raise error until conversion is implemented
                    raise DRFValidationError({"shipping_option_name": f"Native shipping price missing, conversion needed for '{selected_currency}'."})

            try:
                # Convert robustly via string
                shipping_price_native = Decimal(str(shipping_price_value))
                if shipping_price_native < Decimal('0'): # Use Decimal for comparison
                    raise ValueError("Shipping price cannot be negative.")
            except (InvalidOperation, ValueError, TypeError) as e:
                logger.error(f"Invalid shipping price format P:{product.id}, Option:'{shipping_option_name}', Value:'{shipping_price_value}': {e}")
                raise DRFValidationError({"shipping_option_name": "Invalid shipping price configured for the selected option and currency."})
        else:
            # Ensure shipping blob is ignored/nulled for digital products
            if encrypted_shipping_blob:
                logger.warning(f"Encrypted shipping blob provided for digital Product:{product.id} by User:{user.id}. Ignoring.")
            encrypted_shipping_blob = None # Nullify for digital

        return price_native, shipping_option_details, shipping_price_native
    # --- End Helper Methods ---

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Handles the POST request to place an order."""
        user: 'User' = request.user
        ip_addr = get_client_ip(request)
        order: Optional[Order] = None

        try:
            # 1. Basic Input Validation (Product ID can be str or int here)
            product_id_input, quantity, selected_currency, shipping_option_name, encrypted_shipping_blob = \
                self._validate_request_data(request.data)

            # 2. Fetch Product (Handle int or UUID PK)
            try:
                # Assuming Product model uses 'pk' which could be int or UUID
                product: Product = Product.objects.select_related('vendor').get(pk=product_id_input)
            except Product.DoesNotExist:
                raise NotFound(detail=f"Product with ID {product_id_input} not found.")
            except (ValueError, TypeError, DjangoValidationError) as e: # Catch UUID format errors if PK is UUID
                logger.warning(f"Order placement: Invalid product ID format or value: {product_id_input}. Error: {e}")
                raise DRFValidationError({"product_id": "Invalid product ID format."})


            # 3. Validate Product Rules, Options, Stock, and Get Prices
            price_native, shipping_option_details, shipping_price_native = \
                self._validate_product_and_options(
                    user, product, quantity, selected_currency,
                    shipping_option_name, encrypted_shipping_blob
                )

            # 4. Calculate Total Price (ATOMIC units)
            try:
                total_price_native = (price_native * Decimal(quantity)) + shipping_price_native
                if total_price_native < Decimal('0'):
                    # Sanity check for negative total price
                    raise ValueError("Total price cannot be negative.")
            except (InvalidOperation, TypeError, ValueError) as e:
                logger.error(f"Order price calculation error P:{product.id} Q:{quantity} Pr:{price_native} ShPr:{shipping_price_native}: {e}")
                raise APIException("An error occurred during final price calculation.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 5. Create Order Data Dictionary
            order_data = {
                'buyer': user,
                'vendor': product.vendor,
                'product': product,
                'quantity': quantity,
                'selected_currency': selected_currency,
                'price_native_selected': price_native,
                'shipping_price_native_selected': shipping_price_native,
                'total_price_native_selected': total_price_native,
                'selected_shipping_option': shipping_option_details,
                'encrypted_shipping_info': encrypted_shipping_blob,
                'status': OrderStatusChoices.PENDING_PAYMENT,
                # escrow_type defaults in model, service might override
            }

            # 6. Create Order Instance (unsaved) & Validate
            order_instance = Order(**order_data)
            try:
                # Exclude fields that are expected to be populated by the service or later actions
                order_instance.full_clean(exclude=['payment', 'dispute', 'feedback'])
            except DjangoValidationError as clean_e:
                logger.warning(f"Order instance model validation failed before service call: {clean_e.message_dict}")
                # Convert Django validation error to DRF validation error for consistent API response
                raise DRFValidationError(clean_e.message_dict)

            # 7. Initialize Escrow (via Service Layer)
            try:
                # Ensure service is available (might fail if service itself has issues)
                if not callable(getattr(escrow_service, 'create_escrow_for_order', None)): # Check attribute on aliased/placeholder object
                    logger.critical("Escrow service function 'create_escrow_for_order' is not available or callable on the configured 'escrow_service' object!")
                    raise APIException("Order processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)

                order = escrow_service.create_escrow_for_order(order_instance)

                if not order or not order.pk:
                    logger.critical(f"Escrow service failed to return a saved order instance for P:{product.id} B:{user.id}/{user.username}")
                    raise APIException("Failed to initialize payment details for the order.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Handle specific exceptions from the service layer first
            except (DjangoValidationError, DRFValidationError) as e:
                # These are validation errors raised *during* the service call
                logger.warning(f"Order placement validation failed during escrow creation U:{user.id} (P:{product.id}): {e}")
                raise e # Re-raise directly
            except EscrowError as e:
                logger.error(f"Escrow service error during order creation P:{product.id} U:{user.id}: {e}", exc_info=settings.DEBUG) # Log traceback if debug
                # Provide a user-friendly message, potentially masking internal details
                raise APIException(f"Failed to create order: {e}", status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                # Catch broader exceptions during the service call
                logger.exception(f"Unexpected error during escrow creation P:{product.id} U:{user.id}: {e}")
                raise APIException("An unexpected error occurred while initializing the order.", status.HTTP_500_INTERNAL_SERVER_ERROR)

            # --- Success ---
            logger.info(f"Order created: ID:{order.id}, Buyer:{user.id}, Vendor:{order.vendor.id}, P:{order.product.id}, IP:{ip_addr}")
            security_logger.info(f"Order created: ID={order.id}, Buyer={user.username}, Vendor={order.vendor.username}, ProdID={order.product.id}, Qty={quantity}, Curr={selected_currency}, Total={total_price_native}, IP={ip_addr}")
            log_audit_event(request, user, 'order_place', target_order=order, target_product=order.product, details=f"Q:{quantity}, C:{selected_currency}")

            # --- Send Notification ---
            try:
                create_notification(
                    user_id=order.vendor.id,
                    level='info',
                    message=f"New order #{str(order.id)[:8]} placed by {user.username} for your product '{order.product.name[:30]}...'.",
                    link=f"/orders/{order.id}" # Adjust link as needed
                )
                logger.info(f"Sent 'new order' notification to V:{order.vendor.id} for O:{order.id}")
            except Exception as notify_e:
                # Log error but don't fail the order creation if notification fails
                logger.error(f"Failed to send 'new order' notification for O:{order.id} to V:{order.vendor.id}: {notify_e}")

            # --- Return Response ---
            serializer = self.get_serializer(order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        # --- Top-Level Exception Handling ---
        except (DRFValidationError, NotFound, PermissionDenied) as e:
            # Handle known DRF exceptions raised directly in the view logic
            product_id_req = request.data.get('product_id', 'N/A')
            logger.warning(f"Order placement failed (View Level) for User:{user.id} (Product Attempted:{product_id_req}): {getattr(e, 'detail', str(e))}")
            raise e # Re-raise to let DRF handle the response format
        except APIException as e:
            # Handle APIExceptions raised explicitly (e.g., from service layer handling)
            logger.warning(f"Order placement failed (APIException) for User:{user.id}: {e.detail}")
            raise e # Re-raise
        except Exception as e:
            # Catch any other unexpected exceptions not caught earlier
            logger.exception(f"Unexpected error placing order (Top Level) for User:{user.id}: {e}")
            # Return a generic 500 error
            raise APIException("An unexpected server error occurred.", status.HTTP_500_INTERNAL_SERVER_ERROR)


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Provides read-only access to orders, filtered by user role, with optimizations."""
    queryset = Order.objects.none() # Base queryset overridden in get_queryset
    permission_classes = [drf_permissions.IsAuthenticated]
    lookup_field = 'pk' # Assumes Order PK (e.g., UUIDField uses 'pk')
    lookup_url_kwarg = 'pk' # Explicitly state the URL keyword argument
    # Load pagination class safely from settings
    pagination_class_name = settings.REST_FRAMEWORK.get(DEFAULT_PAGINATION_CLASS_SETTING)
    pagination_class = import_string(pagination_class_name) if pagination_class_name else None
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter]
    filterset_fields = ['status', 'selected_currency'] # Use constants in frontend if possible
    ordering_fields = ['created_at', 'updated_at', 'status', 'total_price_native_selected']
    ordering = ['-created_at'] # Default ordering
    # throttle_scope = 'orders' # Add if throttling needed

    def get_serializer_class(self) -> Type[OrderBaseSerializer]:
        """Determine serializer based on user's relationship to the order or view context."""
        instance: Optional[Order] = None
        user: 'User' = self.request.user

        # For retrieve actions, determine role based on the specific instance
        if self.action == 'retrieve':
            try:
                # Use the internal helper for safe retrieval & permission check
                instance = self._get_object_or_none()
            except PermissionDenied:
                # If permission denied during retrieval, let DRF handle the final response
                pass
            # If instance is None after _get_object_or_none, it means not found (404)
            if instance is None:
                # Return a default serializer, DRF will handle the 404 response
                return OrderBuyerSerializer

        # Check if accessing via a specific vendor sales URL pattern
        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        # Determine serializer based on context and instance (if available)
        if is_vendor_sales_view:
            # If it's the vendor sales view, always use Vendor serializer
            return OrderVendorSerializer
        elif instance:
            # If viewing a specific order detail, determine role
            if instance.vendor_id == user.id: return OrderVendorSerializer
            if instance.buyer_id == user.id: return OrderBuyerSerializer
            if getattr(user, 'is_staff', False): return OrderVendorSerializer # Staff see vendor view
            # Fallback if somehow accessed detail without being buyer/vendor/staff
            logger.warning(f"User {user.id} accessed order detail {instance.id} inappropriately (should be caught by permissions).")
            return OrderBuyerSerializer # Default fallback
        else:
            # Default for LIST view (general '/orders/')
            # Sticking to Buyer view as default. Vendors see their sales mixed with their purchases.
            return OrderBuyerSerializer

    def get_queryset(self) -> 'QuerySet[Order]':
        """Filter orders based on user role and apply query optimizations."""
        user: 'User' = self.request.user
        if not user or not user.is_authenticated:
            logger.warning("Unauthenticated user attempted OrderViewSet access.")
            return Order.objects.none()

        # Base queryset with essential related objects for list/detail efficiency
        base_queryset = Order.objects.select_related(
            'product',        # Often needed for name/link
            'product__vendor',# Often needed for vendor name/link
            'buyer',          # Needed for filtering/display
            'vendor',         # Needed for filtering/display
            'payment',        # May be needed for payment status hints
            'dispute'         # Needed to show dispute status/link
        ).prefetch_related(
            # Prefetch feedback only if displayed in list/detail (consider .only() fields)
            Prefetch('feedback', queryset=Feedback.objects.select_related('reviewer').only('id', 'rating', 'reviewer__username', 'created_at')),
            # Prefetch tickets only if count/status needed (consider .only() fields)
            # Prefetch('support_tickets', queryset=SupportTicket.objects.only('id', 'status'))
        )

        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        if getattr(user, 'is_staff', False):
            logger.debug(f"Staff user {user.id}/{user.username} accessing all orders.")
            queryset = base_queryset.all() # Staff sees everything
        elif is_vendor_sales_view:
            # Vendor sales view: Filter for orders where user is the vendor
            if not getattr(user, 'is_vendor', False):
                logger.warning(f"Non-vendor user {user.id} attempted vendor sales view.")
                return Order.objects.none()
            logger.debug(f"Vendor user {user.id} accessing their vendor sales.")
            queryset = base_queryset.filter(vendor=user)
        else:
            # Standard user accessing general '/orders/' list/detail
            logger.debug(f"User {user.id} accessing their orders (buyer or vendor).")
            # Show orders where the user is either the buyer OR the vendor
            queryset = base_queryset.filter(Q(buyer=user) | Q(vendor=user))

        # Note: Filtering via DjangoFilterBackend and OrderingFilter happens *after* this method returns.
        # The base queryset returned here should contain all potentially relevant orders for the user/context.
        return queryset

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Determine permissions based on view type and action."""
        base_permissions = [drf_permissions.IsAuthenticated]
        permission_instances: List[drf_permissions.BasePermission] = [p() for p in base_permissions]

        is_vendor_sales_view = getattr(self.request.resolver_match, 'url_name', '').startswith('vendor-sales')

        if is_vendor_sales_view:
            permission_instances.append(IsVendor()) # Must be a vendor for this view
            # permission_instances.append(IsPgpAuthenticated()) # Add if PGP needed for sales view
        elif self.action == 'retrieve':
            # Viewing specific order requires involvement or staff status
            permission_instances.append(IsBuyerOrVendorOfOrder())

        return permission_instances

    # Helper method used by get_serializer_class
    def _get_object_or_none(self) -> Optional[Order]:
        """Safely retrieves the object based on lookup_field, checking permissions, returns None if not found or forbidden."""
        queryset = self.filter_queryset(self.get_queryset()) # Apply filters first
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        if lookup_url_kwarg not in self.kwargs:
            logger.error(f"Lookup URL kwarg '{lookup_url_kwarg}' not found in kwargs for OrderViewSet retrieve.")
            return None # Should not happen with standard routing

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        try:
            obj = generics.get_object_or_404(queryset, **filter_kwargs)
            # Run object-level permissions check AFTER retrieving the object
            self.check_object_permissions(self.request, obj)
            return obj
        except Http404:
            # Object not found based on lookup
            return None
        except PermissionDenied:
            # Object found, but user doesn't have permission
            # Let DRF handle the 403 response, return None here for get_serializer_class logic
            return None
        except (ValueError, TypeError, DjangoValidationError):
            # Handle invalid lookup value format (e.g., bad UUID string)
            # Although get_object_or_404 usually raises Http404 for this
            logger.warning(f"Invalid lookup value format for order: {self.kwargs[lookup_url_kwarg]}")
            return None


# --- Order Action Views ---

class OrderActionBaseView(APIView):
    """Base view for actions on a specific order (Requires PGP Auth & Order Involvement)."""
    permission_classes = [
        drf_permissions.IsAuthenticated,
        IsPgpAuthenticated,
        IsBuyerOrVendorOfOrder # Ensures user is buyer or vendor of the specific order OR staff
    ]
    # throttle_scope = 'order_actions' # Add if throttling needed

    def get_object(self, pk: Any) -> Order:
        """Retrieve the order, checking permissions. Raises NotFound or PermissionDenied."""
        queryset = Order.objects.select_related(
            'buyer', 'vendor', 'payment', 'product', 'dispute'
        )
        lookup_field = 'pk' # Assuming Order PK is the lookup field
        filter_kwargs = {lookup_field: pk}

        # Handle potential UUID conversion if PK is UUIDField
        from uuid import UUID # Import locally to avoid top-level if not always needed
        if isinstance(Order._meta.pk, models.UUIDField): # Check if PK is UUID
            if isinstance(pk, str):
                try:
                    filter_kwargs[lookup_field] = UUID(pk)
                except ValueError:
                    raise NotFound(detail="Invalid Order ID format.")
            elif not isinstance(pk, UUID):
                # If PK is UUID but input is not string or UUID, it's invalid
                raise NotFound(detail="Invalid Order ID format.")
        elif isinstance(Order._meta.pk, models.AutoField): # Check if PK is AutoField (int)
            try:
                filter_kwargs[lookup_field] = int(pk)
            except (ValueError, TypeError):
                raise NotFound(detail="Invalid Order ID format.")
        # Add checks for other PK types if necessary


        try:
            order: Order = generics.get_object_or_404(queryset, **filter_kwargs)
            # Check object-level permissions AFTER retrieving the object
            # This uses the permission_classes defined on the view (including IsBuyerOrVendorOfOrder)
            self.check_object_permissions(self.request, order)
            return order
        except Http404:
            # Re-raise standard NotFound if get_object_or_404 fails
            raise NotFound(detail="Order not found.")
        # Note: PermissionDenied will be raised by check_object_permissions if checks fail


class MarkShippedView(OrderActionBaseView):
    """Allows VENDOR to mark an order as shipped (Requires PGP Auth & Vendor role)."""
    permission_classes = OrderActionBaseView.permission_classes + [IsVendor]

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        """Handles POST request to mark an order as shipped."""
        # get_object handles retrieval, 404, and base permissions (IsAuth, PGP, IsBuyerOrVendor)
        # IsVendor permission is checked implicitly by DRF before view method runs
        order = self.get_object(pk)
        user: 'User' = request.user
        ip_addr = get_client_ip(request)
        tracking_info = request.data.get('tracking_info', '').strip()

        # Defense-in-depth check (already covered by IsVendor permission class)
        if user.id != order.vendor_id:
            logger.critical(f"CRITICAL: Permission bypass in MarkShippedView. User {user.id} (not vendor {order.vendor_id}) reached POST for O:{order.id}. IP:{ip_addr}")
            raise PermissionDenied("Internal permission configuration error.")

        try:
            # Ensure service is available
            if not callable(getattr(escrow_service, 'mark_order_shipped', None)):
                logger.critical("Escrow service function 'mark_order_shipped' is not available on the configured 'escrow_service' object!")
                raise APIException("Order processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)

            updated_order: Order = escrow_service.mark_order_shipped(
                order=order,
                vendor=user,
                tracking_info=tracking_info
            )

            serializer = OrderVendorSerializer(updated_order, context={'request': request})
            logger.info(f"Order shipped: ID:{order.id}, By V:{user.id}, IP:{ip_addr}, Tracking:{tracking_info or 'N/A'}")
            security_logger.info(f"Order shipped: ID={order.id}, By V={user.username}, IP={ip_addr}, Tracking:{tracking_info or 'N/A'}")
            log_audit_event(request, user, 'order_ship', target_order=updated_order, details=f"Tracking: {tracking_info or 'N/A'}")

            # --- Send Notification to Buyer ---
            try:
                create_notification(
                    user_id=updated_order.buyer.id,
                    level='info',
                    message=f"Your order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...') has been shipped.",
                    link=f"/orders/{updated_order.id}"
                )
                logger.info(f"Sent 'order shipped' notification to B:{updated_order.buyer.id} for O:{updated_order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'order shipped' notification for O:{updated_order.id} to B:{updated_order.buyer.id}: {notify_e}")

            return Response(serializer.data, status=status.HTTP_200_OK)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e:
            # Consolidate error handling
            error_detail = getattr(e, 'detail', None) or (getattr(e, 'message_dict', None) if isinstance(e, DjangoValidationError) else None) or str(e)
            status_code = status.HTTP_403_FORBIDDEN if isinstance(e, PermissionDenied) else status.HTTP_400_BAD_REQUEST
            log_level_func = logger.error if isinstance(e, (PermissionDenied, EscrowError, CryptoProcessingError)) else logger.warning # Assign function

            log_level_func(f"Mark shipped failed O:{order.id} by V:{user.id}. Type:{type(e).__name__}, Reason: {error_detail}") # Use assigned function

            if isinstance(e, (DRFValidationError, DjangoValidationError, ValueError)):
                # Raise as DRF validation error
                raise DRFValidationError(detail=error_detail)
            elif isinstance(e, PermissionDenied):
                raise PermissionDenied(detail=error_detail or "Permission denied by service.")
            else: # EscrowError, CryptoProcessingError
                # Raise as generic API exception for service failures
                raise APIException(f"Failed to mark order shipped: {error_detail}", code=status_code)

        except Exception as e:
            logger.exception(f"Unexpected error marking O:{order.id} shipped by V:{user.id}: {e}")
            raise APIException("An unexpected server error occurred.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FinalizeOrderView(OrderActionBaseView):
    """Allows BUYER to finalize an order (Requires PGP Auth & Buyer role)."""
    permission_classes = OrderActionBaseView.permission_classes + [IsBuyer]

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        """Handles POST request to finalize an order."""
        order = self.get_object(pk) # Handles retrieval, 404, base perms + IsBuyer check
        user: 'User' = request.user
        ip_addr = get_client_ip(request)

        # Defense-in-depth check
        if user.id != order.buyer_id:
            logger.critical(f"CRITICAL: Permission bypass in FinalizeOrderView. User {user.id} (not buyer {order.buyer_id}) reached POST for O:{order.id}. IP:{ip_addr}")
            raise PermissionDenied("Internal permission configuration error.")

        try:
            # Ensure service is available
            if not callable(getattr(escrow_service, 'finalize_order', None)):
                logger.critical("Escrow service function 'finalize_order' is not available on the configured 'escrow_service' object!")
                raise APIException("Order processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)

            updated_order: Order = escrow_service.finalize_order(order=order, user=user)

            serializer = OrderBuyerSerializer(updated_order, context={'request': request})
            final_status = OrderStatusChoices(updated_order.status).label
            logger.info(f"Order finalize action by Buyer: ID:{order.id}, By B:{user.id}, New Status:'{final_status}', IP:{ip_addr}")
            security_logger.info(f"Order finalize action: ID={order.id}, By B={user.username}, Status={final_status}, IP={ip_addr}")
            audit_action = 'order_finalize_complete' if updated_order.status == OrderStatusChoices.FINALIZED else 'order_finalize_request'
            log_audit_event(request, user, audit_action, target_order=updated_order)

            # --- Send Notification to Vendor ---
            try:
                notification_level = 'success' if updated_order.status == OrderStatusChoices.FINALIZED else 'info'
                notification_message = (
                    f"Order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...') has been finalized by the buyer."
                    if updated_order.status == OrderStatusChoices.FINALIZED else
                    f"Buyer has initiated finalization for order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...')."
                )
                create_notification(
                    user_id=updated_order.vendor.id,
                    level=notification_level,
                    message=notification_message,
                    link=f"/vendor/sales/{updated_order.id}"
                )
                logger.info(f"Sent 'order finalize' notification ({notification_level}) to V:{updated_order.vendor.id} for O:{updated_order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'order finalize' notification for O:{updated_order.id} to V:{updated_order.vendor.id}: {notify_e}")

            return Response(serializer.data, status=status.HTTP_200_OK)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e:
            # Consolidate error handling
            error_detail = getattr(e, 'detail', None) or (getattr(e, 'message_dict', None) if isinstance(e, DjangoValidationError) else None) or str(e)
            status_code = status.HTTP_403_FORBIDDEN if isinstance(e, PermissionDenied) else status.HTTP_400_BAD_REQUEST
            log_level_func = logger.error if isinstance(e, (PermissionDenied, EscrowError, CryptoProcessingError)) else logger.warning

            log_level_func(f"Finalize order failed O:{order.id} by B:{user.id}. Type:{type(e).__name__}, Reason: {error_detail}")

            if isinstance(e, (DRFValidationError, DjangoValidationError, ValueError)):
                raise DRFValidationError(detail=error_detail)
            elif isinstance(e, PermissionDenied):
                raise PermissionDenied(detail=error_detail or "Permission denied by service.")
            else: # EscrowError, CryptoProcessingError
                raise APIException(f"Failed to finalize order: {error_detail}", code=status_code)

        except Exception as e:
            logger.exception(f"Unexpected error finalizing O:{order.id} by B:{user.id}: {e}")
            raise APIException("Unexpected error during finalization.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- NEW: Release & Dispute Views ---

class PrepareReleaseTxView(OrderActionBaseView):
    """
    Prepares multisig release transaction data (e.g., PSBT). Requires PGP Auth & Order Involvement.
    Called by Buyer/Vendor/Staff to get unsigned data for their signature.
    """
    serializer_class = PrepareReleaseTxSerializer # Input serializer (may be empty)

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        """Handles POST request to prepare the release transaction."""
        order = self.get_object(pk) # Handles retrieval, 404, base perms
        user: 'User' = request.user
        ip_addr = get_client_ip(request)

        # Validate input using the serializer (allows for future input fields)
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        try:
            # Ensure service is available
            if not callable(getattr(escrow_service, 'prepare_release_transaction', None)):
                logger.critical("Escrow service function 'prepare_release_transaction' is not available on the configured 'escrow_service' object!")
                raise APIException("Order processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)

            release_metadata: Dict[str, Any] = escrow_service.prepare_release_transaction(
                order=order,
                initiator=user
            )

            role = "Buyer" if user.id == order.buyer_id else ("Vendor" if user.id == order.vendor_id else "Staff")
            logger.info(f"Release tx prepared: O:{order.id}, InitBy:{role}:{user.id}, IP:{ip_addr}")
            security_logger.info(f"Release prepare: ID={order.id}, By={user.username} ({role}), IP={ip_addr}, Type={order.escrow_type}")
            log_audit_event(request, user, 'order_release_prepare', target_order=order, details=f"Role: {role}")

            return Response(release_metadata, status=status.HTTP_200_OK)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e:
            error_detail = getattr(e, 'detail', None) or (getattr(e, 'message_dict', None) if isinstance(e, DjangoValidationError) else None) or str(e)
            status_code = status.HTTP_403_FORBIDDEN if isinstance(e, PermissionDenied) else status.HTTP_400_BAD_REQUEST
            log_level_func = logger.error if isinstance(e, (PermissionDenied, EscrowError, CryptoProcessingError)) else logger.warning

            log_level_func(f"Prepare release failed O:{order.id} by U:{user.id}. Type:{type(e).__name__}, Reason: {error_detail}")

            if isinstance(e, (DRFValidationError, DjangoValidationError, ValueError)):
                raise DRFValidationError(detail=error_detail)
            elif isinstance(e, PermissionDenied):
                raise PermissionDenied(detail=error_detail or "Permission denied by service.")
            else: # EscrowError, CryptoProcessingError
                raise APIException(f"Failed to prepare release: {error_detail}", code=status_code)

        except Exception as e:
            logger.exception(f"Unexpected error preparing release O:{order.id} by U:{user.id}: {e}")
            raise APIException("Unexpected error during release preparation.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SignReleaseView(OrderActionBaseView):
    """
    Accepts a signature contribution for a prepared multisig release. Requires PGP Auth & Order Involvement.
    Attempts broadcast if sufficient signatures are present.
    """
    serializer_class = SignReleaseSerializer # Validates signature_data field

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        """Handles POST request to submit a release signature."""
        order = self.get_object(pk) # Handles retrieval, 404, base perms
        user: 'User' = request.user
        ip_addr = get_client_ip(request)

        # Validate incoming signature data
        serializer = self.serializer_class(
            data=request.data,
            context={'request': request, 'order': order} # Pass order context if needed by validation
        )
        serializer.is_valid(raise_exception=True)
        signature_data: str = serializer.validated_data['signature_data']

        try:
            # Ensure service is available
            if not callable(getattr(escrow_service, 'submit_release_signature', None)):
                logger.critical("Escrow service function 'submit_release_signature' is not available on the configured 'escrow_service' object!")
                raise APIException("Order processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)

            updated_order: Order = escrow_service.submit_release_signature(
                order=order,
                user=user,
                signature_data=signature_data
            )

            # Determine response serializer based on user role
            response_serializer_class = OrderBuyerSerializer if user.id == updated_order.buyer_id else OrderVendorSerializer
            response_serializer = response_serializer_class(updated_order, context={'request': request})

            # Log success and audit
            role = "Buyer" if user.id == updated_order.buyer_id else ("Vendor" if user.id == updated_order.vendor_id else "Staff")
            logger.info(f"Release signature received: O:{order.id}, From {role}:{user.id}, IP:{ip_addr}")
            security_logger.info(f"Release sign: ID={order.id}, Role={role}, User={user.username}, IP={ip_addr}")
            log_audit_event(request, user, 'order_release_sign', target_order=updated_order, details=f"Role: {role}")

            # Check if broadcast occurred (compare new hash to original hash)
            broadcast_hash = getattr(updated_order, 'release_tx_broadcast_hash', None)
            original_broadcast_hash = getattr(order, 'release_tx_broadcast_hash', None) # Get from original order before service call
            if broadcast_hash and broadcast_hash != original_broadcast_hash:
                logger.info(f"Release Tx broadcasted: O:{updated_order.id}, TxHash: {broadcast_hash}")
                security_logger.info(f"Release broadcast: ID={updated_order.id}, TxHash={broadcast_hash}")
                log_audit_event(request, user, 'order_release_broadcast', target_order=updated_order, details=f"TxHash: {broadcast_hash}")

                # --- Send Notifications for Broadcast ---
                try:
                    buyer_msg = f"Funds released for order #{str(updated_order.id)[:8]}. Tx: {str(broadcast_hash)[:10]}..."
                    vendor_msg = f"Funds released for order #{str(updated_order.id)[:8]}. Tx: {str(broadcast_hash)[:10]}..."
                    create_notification(user_id=updated_order.buyer.id, level='success', message=buyer_msg, link=f"/orders/{updated_order.id}")
                    create_notification(user_id=updated_order.vendor.id, level='success', message=vendor_msg, link=f"/vendor/sales/{updated_order.id}")
                    logger.info(f"Sent 'release broadcast' notifications for O:{updated_order.id}")
                except Exception as notify_e:
                    logger.error(f"Failed to send 'release broadcast' notification for O:{updated_order.id}: {notify_e}")

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, EscrowError, CryptoProcessingError) as e:
            # Consolidate error handling
            error_detail = getattr(e, 'detail', None) or (getattr(e, 'message_dict', None) if isinstance(e, DjangoValidationError) else None) or str(e)
            status_code = status.HTTP_403_FORBIDDEN if isinstance(e, PermissionDenied) else status.HTTP_400_BAD_REQUEST
            log_level_func = logger.error if isinstance(e, (PermissionDenied, EscrowError, CryptoProcessingError)) else logger.warning

            log_level_func(f"Sign release failed O:{order.id} by U:{user.id}. Type:{type(e).__name__}, Reason: {error_detail}")

            if isinstance(e, (DRFValidationError, DjangoValidationError, ValueError)):
                raise DRFValidationError(detail=error_detail)
            elif isinstance(e, PermissionDenied):
                raise PermissionDenied(detail=error_detail or "Permission denied by service.")
            else: # EscrowError, CryptoProcessingError
                raise APIException(f"Failed to process signature: {error_detail}", code=status_code)

        except Exception as e:
            logger.exception(f"Unexpected error signing release O:{order.id} by U:{user.id}: {e}")
            raise APIException("Unexpected error during signature submission.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class OpenDisputeView(OrderActionBaseView):
    """Allows BUYER to open a dispute on an order (Requires PGP Auth & Buyer role)."""
    serializer_class = OpenDisputeSerializer # Validates 'reason' field
    permission_classes = OrderActionBaseView.permission_classes + [IsBuyer] # Only buyer can open

    def post(self, request: Request, pk: Any, *args: Any, **kwargs: Any) -> Response:
        """Handles POST request to open a dispute."""
        order = self.get_object(pk) # Handles retrieval, 404, base perms + IsBuyer check
        user: 'User' = request.user
        ip_addr = get_client_ip(request)

        # Defense-in-depth check
        if user.id != order.buyer_id:
            logger.critical(f"CRITICAL: Permission bypass in OpenDisputeView. User {user.id} (not buyer {order.buyer_id}) reached POST for O:{order.id}. IP:{ip_addr}")
            raise PermissionDenied("Internal permission configuration error.")

        # Validate input reason
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason: str = serializer.validated_data['reason']

        try:
            # Ensure service is available
            if not callable(getattr(dispute_service, 'open_dispute', None)):
                logger.critical("Dispute service function 'open_dispute' is not available on the configured 'dispute_service' object!")
                raise APIException("Dispute processing service is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)


            dispute_instance: Dispute = dispute_service.open_dispute(
                order=order,
                requester=user,
                reason=reason
            )

            # Fetch updated order with the dispute relation prefeched for the serializer
            updated_order = Order.objects.select_related('dispute', 'buyer', 'vendor', 'product').get(pk=order.pk)
            response_serializer = OrderBuyerSerializer(updated_order, context={'request': request})

            # Log success and audit
            logger.info(f"Dispute opened: O:{order.id}, D:{dispute_instance.id}, By B:{user.id}, Reason:'{reason[:50]}...', IP:{ip_addr}")
            security_logger.info(f"Dispute open: OrderID={order.id}, DisputeID={dispute_instance.id}, By={user.username}, IP={ip_addr}")
            log_audit_event(request, user, 'dispute_open', target_order=updated_order, target_dispute=dispute_instance, details=f"Reason: {reason}")

            # --- Send Notification ---
            try:
                # Notify Vendor
                create_notification(
                    user_id=updated_order.vendor.id,
                    level='warning',
                    message=f"A dispute has been opened by the buyer for order #{str(updated_order.id)[:8]} ('{updated_order.product.name[:30]}...').",
                    link=f"/vendor/sales/{updated_order.id}"
                )
                # Notify Staff/Admins (Example)
                # notify_staff(...)
                logger.info(f"Sent 'dispute opened' notification to V:{updated_order.vendor.id} for O:{updated_order.id}")
            except Exception as notify_e:
                logger.error(f"Failed to send 'dispute opened' notification for O:{updated_order.id}: {notify_e}")

            # Return 201 Created as a new Dispute resource was made
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except (DRFValidationError, DjangoValidationError, ValueError, PermissionDenied, DisputeError) as e:
            # Consolidate error handling
            error_detail = getattr(e, 'detail', None) or (getattr(e, 'message_dict', None) if isinstance(e, DjangoValidationError) else None) or str(e)
            status_code = status.HTTP_403_FORBIDDEN if isinstance(e, PermissionDenied) else status.HTTP_400_BAD_REQUEST
            log_level_func = logger.error if isinstance(e, (PermissionDenied, DisputeError)) else logger.warning

            log_level_func(f"Open dispute failed O:{order.id} by B:{user.id}. Type:{type(e).__name__}, Reason: {error_detail}")

            if isinstance(e, (DRFValidationError, DjangoValidationError, ValueError)):
                raise DRFValidationError(detail=error_detail)
            elif isinstance(e, PermissionDenied):
                raise PermissionDenied(detail=error_detail or "Permission denied by service.")
            else: # DisputeError
                raise APIException(f"Failed to open dispute: {error_detail}", code=status_code)

        except Exception as e:
            logger.exception(f"Unexpected error opening dispute O:{order.id} by B:{user.id}: {e}")
            raise APIException("Unexpected error opening dispute.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- END OF FILE ---