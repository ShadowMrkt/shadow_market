# backend/store/views/vendor.py
# Revision: 1.0 (Split from views.py Rev 4.7)
# Date: 2025-04-29
# Author: Gemini
# Description: Contains Vendor-related views (Public Profile, Stats, Feedback List).
# Changes:
# - Rev 1.0:
#   - Initial split of VendorPublicProfileView, VendorStatsView, VendorFeedbackListView.
#   - Using absolute imports from 'backend' root.
#   - Added missing imports (get_object_or_404, timezone, Avg, Count, Sum, Decimal).
# History from views.py Rev 4.7 relevant to these views:
# - Rev 4.4: Added VendorFeedbackListView.

# Standard Library Imports
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List, Type, Union

# Django Imports
from django.conf import settings
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone # Needed for VendorStatsView
from django.utils.module_loading import import_string

# Third-Party Imports
from rest_framework import generics, status, permissions as drf_permissions
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

# --- Local Imports (Using absolute paths from 'backend') ---
# --- Import Models ---
from backend.store.models import User, Product, Order, Feedback
# --- Import Serializers ---
from backend.store.serializers import VendorPublicProfileSerializer, FeedbackSerializer
# --- Import Permissions ---
from backend.store.permissions import IsVendor, IsPgpAuthenticated

# --- Constants ---
DEFAULT_PAGINATION_CLASS_SETTING: str = 'DEFAULT_PAGINATION_CLASS'

# --- Setup Loggers ---
logger = logging.getLogger(__name__)
# security_logger = logging.getLogger('security') # Not used in these views


# --- Vendor Views ---

class VendorPublicProfileView(generics.RetrieveAPIView):
    """Displays a vendor's public profile information."""
    queryset = User.objects.filter(is_vendor=True, is_active=True)
    serializer_class = VendorPublicProfileSerializer
    permission_classes = [AllowAny] # Publicly viewable
    lookup_field = 'username'
    lookup_url_kwarg = 'username'


class VendorStatsView(APIView):
    """Provides aggregated statistics for the requesting vendor (Requires Vendor & PGP Auth)."""
    permission_classes = [drf_permissions.IsAuthenticated, IsVendor, IsPgpAuthenticated]
    # throttle_classes = [PGPActionThrottle] # Apply PGP action throttle if defined

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vendor: 'User' = request.user # Permissions ensure user is a vendor

        try:
            # Active Listings Count
            active_listings_count = Product.objects.filter(vendor=vendor, is_active=True).count()

            # Sales Counts by Status
            # Use constants imported from models (OrderStatusChoices not needed here, use strings)
            # TODO: Replace hardcoded status strings with constants from Order model if possible
            pending_statuses = ['payment_confirmed', 'shipped'] # Assuming these are the values
            sales_pending_action_count = Order.objects.filter(vendor=vendor, status__in=pending_statuses).count()
            sales_completed_count = Order.objects.filter(vendor=vendor, status='finalized').count()
            disputes_open_count = Order.objects.filter(vendor=vendor, status='disputed').count()

            # Total Revenue per Currency (Finalized Orders)
            revenue_data = Order.objects.filter(
                vendor=vendor, status='finalized'
            ).values('selected_currency').annotate(
                total_revenue=Sum('total_price_native_selected') # Assumes native price field exists
            ).order_by('selected_currency')

            total_revenue_by_currency: Dict[str, Optional[Decimal]] = {
                item['selected_currency']: item['total_revenue']
                for item in revenue_data if item['selected_currency']
            }

            # Average Rating and Feedback Count
            feedback_agg = Feedback.objects.filter(recipient=vendor).aggregate(
                average_rating=Avg('rating'),
                feedback_count=Count('id')
            )
            avg_rating: Optional[Decimal] = feedback_agg.get('average_rating')
            feedback_count: int = feedback_agg.get('feedback_count', 0)

            # Compile Stats Data (Format Decimals safely)
            stats_data = {
                'active_listings_count': active_listings_count,
                'sales_pending_action_count': sales_pending_action_count,
                'sales_completed_count': sales_completed_count,
                'disputes_open_count': disputes_open_count,
                'total_revenue_by_currency': {
                    # TODO: Formatting should ideally use DecimalAsStringField logic or utils
                    curr: f"{total:.8f}" if total is not None else "0.00" # Example formatting
                    for curr, total in total_revenue_by_currency.items()
                },
                'average_rating': f"{avg_rating:.2f}" if avg_rating is not None else None,
                'feedback_count': feedback_count,
                'username': vendor.username,
                'joined_date': vendor.date_joined.date().isoformat() if vendor.date_joined else None,
            }
            logger.info(f"Fetched stats for Vendor:{vendor.id}/{vendor.username}")
            return Response(stats_data)

        except Exception as e:
            logger.exception(f"Error fetching stats for Vendor:{vendor.id}/{vendor.username}: {e}")
            raise APIException("Failed to retrieve vendor statistics.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VendorFeedbackListView(generics.ListAPIView):
    """
    Provides a list of feedback received by a specific vendor.
    Publicly accessible.
    """
    serializer_class = FeedbackSerializer
    permission_classes = [AllowAny] # Feedback is generally public
    pagination_class = import_string(settings.REST_FRAMEWORK.get(DEFAULT_PAGINATION_CLASS_SETTING)) if settings.REST_FRAMEWORK.get(DEFAULT_PAGINATION_CLASS_SETTING) else None

    def get_queryset(self):
        """
        Filter feedback based on the username provided in the URL.
        """
        vendor_username = self.kwargs.get('username')
        if not vendor_username:
            logger.error("Vendor username missing in URL kwargs for feedback list.")
            return Feedback.objects.none()

        # Find the active vendor user
        target_vendor = get_object_or_404(
            User,
            username=vendor_username,
            is_vendor=True,
            is_active=True
        )

        # Fetch feedback where the recipient is the target vendor
        # Optimize by selecting related reviewer data needed by the serializer
        queryset = Feedback.objects.filter(
            recipient=target_vendor
        ).select_related('reviewer').order_by('-created_at') # Order newest first

        return queryset

# --- END OF FILE ---