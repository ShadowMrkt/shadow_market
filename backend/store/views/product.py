# backend/store/views/product.py
# Revision: 1.3 (Corrected Utils Import Path)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains Product and Category related views (ViewSets).
# Changes:
# - Rev 1.3:
#   - Corrected import path for helpers to use backend.store.utils.utils.
# - Rev 1.2:
#   - Updated imports to use get_client_ip and log_audit_event from backend.store.utils.
# - Rev 1.1:
#   - Removed local definitions of get_client_ip and log_audit_event.
#   - Imported get_client_ip and log_audit_event from .helpers (Incorrectly stated, was still local).
#   - Removed unused import HttpRequest.
# - Rev 1.0 (Split): Initial split.

# Standard Library Imports
import logging
from typing import Dict, Any, Optional, List, Tuple, Type, Union, TYPE_CHECKING

# Django Imports
from django.conf import settings
from django.db.models import Q
# --- Type Hinting ---
if TYPE_CHECKING:
    from django.db.models.query import QuerySet
    from backend.store.models import User # Ensure User type hint is available

# Third-Party Imports
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status, permissions as drf_permissions
from rest_framework import filters as drf_filters
from rest_framework.exceptions import (
    APIException, PermissionDenied # Added PermissionDenied
)
from rest_framework.response import Response
from rest_framework.request import Request

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User, Category, Product
# --- Import Serializers ---
from backend.store.serializers import CategorySerializer, ProductSerializer
# --- Import Permissions ---
from backend.store.permissions import (
    IsAdminOrReadOnly, IsVendor, IsOwnerOrVendorReadOnly, IsPgpAuthenticated
)
# --- Import Filters ---
from backend.store.filters import ProductFilter
# --- Import Utils (Refactored Helpers) --- # <<< CORRECTED IMPORT PATH >>>
from backend.store.utils.utils import get_client_ip, log_audit_event # <<< CORRECTED IMPORT PATH >>>

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

# --- Helper Functions ---
# <<< REMOVED LOCAL DEFINITIONS of get_client_ip and log_audit_event (Now imported from utils.utils) >>>


# --- Product Views ---

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Provides read-only access to active product categories."""
    # Provide a base queryset, filtering can happen dynamically if needed
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [drf_permissions.AllowAny]
    lookup_field = 'slug'
    # Disable pagination by default for categories unless specifically needed
    pagination_class = None

    def get_queryset(self) -> 'QuerySet[Category]':
         """ Optionally filter categories, e.g., only show top-level or those with active products """
         # Example: Only show top-level categories
         # return self.queryset.filter(parent__isnull=True).prefetch_related('children')
         # For now, return all categories
         return self.queryset.prefetch_related('children').all()


class ProductViewSet(viewsets.ModelViewSet):
    """
    Manages products (listings). Handles creation, update, deletion, listing, retrieval.
    Permissions vary by action. Listing/Retrieval is generally open, modifications require auth/ownership.
    """
    # Base queryset - further filtered in get_queryset
    queryset = Product.objects.select_related(
        'vendor', 'category'
    ).prefetch_related(
        'orders' # Example prefetch if needed often
    )
    serializer_class = ProductSerializer
    lookup_field = 'slug' # Use slug for retrieving individual products
    permission_classes = [drf_permissions.IsAuthenticatedOrReadOnly] # Default permission
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'vendor__username', 'category__name', 'category__slug'] # Added category slug
    ordering_fields = ['created_at', 'updated_at', 'price_xmr', 'price_btc', 'price_eth', 'average_rating', 'sales_count', 'name']
    ordering = ['-created_at'] # Default ordering
    # throttle_classes = [...] # Add appropriate throttling scopes

    def get_queryset(self) -> 'QuerySet[Product]':
        """Filter queryset based on user role (staff see inactive) and apply optimizations."""
        # Start with the base queryset defined on the class
        queryset = super().get_queryset() # Inherits select/prefetch_related

        user: Optional['User'] = getattr(self.request, 'user', None)
        is_staff = getattr(user, 'is_staff', False)

        # Allow staff to see inactive products via query param, otherwise filter active only for lists
        show_inactive = is_staff and self.request.query_params.get('include_inactive', 'false').lower() == 'true'

        # Filter by vendor active status unless staff requests inactive included
        # This prevents products from inactive vendors showing up in general lists
        if not show_inactive:
             queryset = queryset.filter(vendor__is_active=True)

        # For list view, only show active products unless staff requests inactive
        if self.action == 'list' and not show_inactive:
            queryset = queryset.filter(is_active=True)
        # For retrieve/update/delete, non-staff can only see active products
        elif self.action != 'list' and not is_staff:
             # Allow retrieving inactive product *if* the user is the owner (vendor)
             # This check is better handled by permissions (IsOwnerOrVendorReadOnly)
             # queryset = queryset.filter(is_active=True) # Keep commented, let permissions handle detail view access
             pass


        return queryset

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Set permissions dynamically based on the action."""
        # Default to class permissions
        permission_classes_list = self.permission_classes

        if self.action in ['list', 'retrieve']:
             # Allow anyone to list or retrieve (queryset filters handle active status)
             permission_classes_list = [drf_permissions.AllowAny]
        elif self.action == 'create':
             # Must be authenticated, a vendor, and PGP authenticated
             permission_classes_list = [drf_permissions.IsAuthenticated, IsVendor, IsPgpAuthenticated]
        elif self.action in ['update', 'partial_update']:
             # Must be authenticated, the product owner (vendor), and PGP authenticated
             permission_classes_list = [drf_permissions.IsAuthenticated, IsOwnerOrVendorReadOnly, IsPgpAuthenticated]
        elif self.action == 'destroy':
            # Must be authenticated, the product owner (vendor), and PGP authenticated
            # Or potentially IsAdminUser if admins should bypass ownership check for deletion
             permission_classes_list = [drf_permissions.IsAuthenticated, IsOwnerOrVendorReadOnly, IsPgpAuthenticated]
             # Example: Allow Admins to delete anything:
             # permission_classes = [drf_permissions.IsAuthenticated, (IsOwnerOrVendorReadOnly | drf_permissions.IsAdminUser), IsPgpAuthenticated]

        # Instantiate and return the permissions
        return [permission() for permission in permission_classes_list]

    def perform_create(self, serializer: ProductSerializer) -> None:
        """Set the vendor to the current user upon product creation and log."""
        # Permissions (IsVendor) ensure request.user is a vendor
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request) # Uses imported helper
        try:
            # Pass vendor explicitly, serializer might not have it in validated_data if read_only
            instance: Product = serializer.save(vendor=user)
            logger.info(f"Product created: ID:{instance.id}, Name='{instance.name}', Vendor:{user.id}/{user.username}, IP:{ip_addr}")
            security_logger.info(f"Product created: ID={instance.id}, Name='{instance.name}', Vendor={user.username}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_create', target_product=instance, details=f"P:'{instance.name}' Cat:{instance.category.slug if instance.category else 'N/A'}") # Uses imported helper
        except Exception as e:
            logger.exception(f"Error saving new product for Vendor:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_update(self, serializer: ProductSerializer) -> None:
        """Log product updates."""
        # Permissions (IsOwnerOrVendorReadOnly) ensure user owns the product
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request) # Uses imported helper
        try:
            instance: Product = serializer.save()
            # Determine changed fields for logging (compare initial_data to instance before save if needed)
            # validated_data only contains fields submitted in the request
            changed_fields = list(serializer.validated_data.keys())
            logger.info(f"Product updated: ID:{instance.id}, Name='{instance.name}', By:{user.id}/{user.username}, Fields:{changed_fields}, IP:{ip_addr}")
            security_logger.info(f"Product updated: ID={instance.id}, Name='{instance.name}', By={user.username}, Fields={changed_fields}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_update', target_product=instance, details=f"Fields:{','.join(changed_fields)}") # Uses imported helper
        except Exception as e:
            instance_id = getattr(serializer.instance, 'id', 'N/A')
            logger.exception(f"Error updating product ID:{instance_id} for User:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product update due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_destroy(self, instance: Product) -> None:
        """Log product deletion attempt before deleting."""
        # Permissions (IsOwnerOrVendorReadOnly) ensure user owns the product
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request) # Uses imported helper
        product_id = instance.id
        product_name = instance.name
        vendor_username = getattr(instance.vendor, 'username', 'N/A')

        logger.warning(f"Product DELETE initiated: ID:{product_id}, Name='{product_name}', Vendor={vendor_username}, By:{user.id}/{user.username}, IP:{ip_addr}")
        security_logger.warning(f"Product DELETE initiated: ID={product_id}, Name='{product_name}', Vendor={vendor_username}, By={user.username}, IP={ip_addr}")
        log_audit_event(self.request, user, 'product_delete_attempt', target_product=instance, details=f"P:'{product_name}'") # Uses imported helper

        try:
            # Instead of deleting, consider deactivating first?
            # instance.is_active = False
            # instance.save(update_fields=['is_active'])
            # logger.info(f"Product deactivated instead of deleted: ID:{product_id}, Name='{product_name}'")
            # If hard delete is intended:
            instance.delete()
            logger.info(f"Product deleted successfully: ID:{product_id}, Name='{product_name}', By:{user.id}/{user.username}")
            # Log successful deletion *after* it happens
            log_audit_event(self.request, user, 'product_delete_success', target_product=None, details=f"Deleted Product ID:{product_id}, Name:'{product_name}'") # Target is gone
        except Exception as e:
            logger.exception(f"Error deleting product ID:{product_id} for User:{user.id}/{user.username}: {e}")
            # Log failure, target_product still exists here
            log_audit_event(self.request, user, 'product_delete_fail', target_product=instance, details=f"P:'{product_name}', Error:{e}") # Uses imported helper
            raise APIException("Failed to delete product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- END OF FILE ---