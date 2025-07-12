# backend/store/views/product.py

# Revision: 1.4 (Fixed Critical Data Leak)
# Date: 2025-06-23
# Author: Gemini
# Description: Contains Product and Category related views (ViewSets).
# Changes:
# - Rev 1.4:
#   - SECURITY FIX: Corrected a critical data leak in `ProductViewSet.get_queryset`.
#     The method now correctly filters out inactive products for non-staff/non-owner users
#     on 'retrieve' and other detail-level actions, ensuring they return a 404 as expected.
# - Rev 1.3:
#   - Corrected import path for helpers to use backend.store.utils.utils.
# - Rev 1.2:
#   - Updated imports to use get_client_ip and log_audit_event from backend.store.utils.
# - Rev 1.1:
#   - Removed local definitions of get_client_ip and log_audit_event.
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
    APIException, PermissionDenied
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
# --- Import Utils (Refactored Helpers) ---
from backend.store.utils.utils import get_client_ip, log_audit_event

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')


# --- Product Views ---

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Provides read-only access to active product categories."""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [drf_permissions.AllowAny]
    lookup_field = 'slug'
    pagination_class = None

    def get_queryset(self) -> 'QuerySet[Category]':
        """ Optionally filter categories, e.g., only show top-level or those with active products """
        # For now, return all categories with their children prefetched.
        return self.queryset.prefetch_related('children').all()


class ProductViewSet(viewsets.ModelViewSet):
    """
    Manages products (listings). Handles creation, update, deletion, listing, retrieval.
    Permissions vary by action. Listing/Retrieval is generally open, modifications require auth/ownership.
    """
    queryset = Product.objects.select_related(
        'vendor', 'category'
    ).prefetch_related(
        'orders'
    )
    serializer_class = ProductSerializer
    lookup_field = 'slug'
    permission_classes = [drf_permissions.IsAuthenticatedOrReadOnly] # Default permission
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'vendor__username', 'category__name', 'category__slug']
    ordering_fields = ['created_at', 'updated_at', 'price_xmr', 'price_btc', 'price_eth', 'average_rating', 'sales_count', 'name']
    ordering = ['-created_at']

    def get_queryset(self) -> 'QuerySet[Product]':
        """
        Dynamically filters the queryset.

        - For list views, it shows only active products from active vendors.
        - For retrieve views, it shows an active product to anyone, but will only
          show an INACTIVE product to its owner (vendor) or a staff member.
        - Staff can use the 'include_inactive' query parameter to override filters.
        """
        user = self.request.user
        queryset = super().get_queryset()

        is_staff = user.is_authenticated and user.is_staff
        show_inactive = is_staff and self.request.query_params.get('include_inactive', 'false').lower() == 'true'

        # If a staff member explicitly asks for inactive items, show everything.
        if show_inactive:
            return queryset

        # For all other users (or staff not asking for inactive), filter by active status.
        # This creates a base of only active products from active vendors.
        active_queryset = queryset.filter(is_active=True, vendor__is_active=True)

        if self.action == 'list':
            # For the list view, this is all we need.
            return active_queryset
        else:
            # For detail views (retrieve, update, etc.), we need a more nuanced filter.
            # A user might be the owner of an inactive product and should be able to see it.
            if user.is_authenticated:
                # The user can see ANY product that is active, OR any product they own (regardless of active status).
                return queryset.filter(
                    Q(is_active=True, vendor__is_active=True) | Q(vendor=user)
                )
            else:
                # Unauthenticated users can only see active products from active vendors.
                return active_queryset

    def get_permissions(self) -> List[drf_permissions.BasePermission]:
        """Set permissions dynamically based on the action."""
        if self.action in ['list', 'retrieve']:
            # Listing and retrieving are public, but get_queryset handles what is visible.
            permission_classes_list = [drf_permissions.AllowAny]
        elif self.action == 'create':
            permission_classes_list = [drf_permissions.IsAuthenticated, IsVendor, IsPgpAuthenticated]
        elif self.action in ['update', 'partial_update', 'destroy']:
            # IsOwnerOrVendorReadOnly handles ownership check for modifications and deletion.
            permission_classes_list = [drf_permissions.IsAuthenticated, IsOwnerOrVendorReadOnly, IsPgpAuthenticated]
        else:
            permission_classes_list = self.permission_classes

        return [permission() for permission in permission_classes_list]

    def perform_create(self, serializer: ProductSerializer) -> None:
        """Set the vendor to the current user upon product creation and log."""
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request)
        try:
            instance: Product = serializer.save(vendor=user)
            logger.info(f"Product created: ID:{instance.id}, Name='{instance.name}', Vendor:{user.id}/{user.username}, IP:{ip_addr}")
            security_logger.info(f"Product created: ID={instance.id}, Name='{instance.name}', Vendor={user.username}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_create', target_product=instance, details=f"P:'{instance.name}' Cat:{instance.category.slug if instance.category else 'N/A'}")
        except Exception as e:
            logger.exception(f"Error saving new product for Vendor:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_update(self, serializer: ProductSerializer) -> None:
        """Log product updates."""
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request)
        try:
            instance: Product = serializer.save()
            changed_fields = list(serializer.validated_data.keys())
            logger.info(f"Product updated: ID:{instance.id}, Name='{instance.name}', By:{user.id}/{user.username}, Fields:{changed_fields}, IP:{ip_addr}")
            security_logger.info(f"Product updated: ID={instance.id}, Name='{instance.name}', By={user.username}, Fields={changed_fields}, IP={ip_addr}")
            log_audit_event(self.request, user, 'product_update', target_product=instance, details=f"Fields:{','.join(changed_fields)}")
        except Exception as e:
            instance_id = getattr(serializer.instance, 'id', 'N/A')
            logger.exception(f"Error updating product ID:{instance_id} for User:{user.id}/{user.username}: {e}")
            raise APIException("Failed to save product update due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_destroy(self, instance: Product) -> None:
        """Log product deletion attempt before deleting."""
        user: 'User' = self.request.user
        ip_addr = get_client_ip(self.request)
        product_id = instance.id
        product_name = instance.name
        vendor_username = getattr(instance.vendor, 'username', 'N/A')

        logger.warning(f"Product DELETE initiated: ID:{product_id}, Name='{product_name}', Vendor={vendor_username}, By:{user.id}/{user.username}, IP:{ip_addr}")
        security_logger.warning(f"Product DELETE initiated: ID={product_id}, Name='{product_name}', Vendor={vendor_username}, By={user.username}, IP={ip_addr}")
        log_audit_event(self.request, user, 'product_delete_attempt', target_product=instance, details=f"P:'{product_name}'")

        try:
            instance.delete()
            logger.info(f"Product deleted successfully: ID:{product_id}, Name='{product_name}', By:{user.id}/{user.username}")
            log_audit_event(self.request, user, 'product_delete_success', target_product=None, details=f"Deleted Product ID:{product_id}, Name:'{product_name}'")
        except Exception as e:
            logger.exception(f"Error deleting product ID:{product_id} for User:{user.id}/{user.username}: {e}")
            log_audit_event(self.request, user, 'product_delete_fail', target_product=instance, details=f"P:'{product_name}', Error:{e}")
            raise APIException("Failed to delete product due to a server error.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- END OF FILE ---