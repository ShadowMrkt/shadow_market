# backend/store/views/vendor.py
# Revision: 2.0
# Date: 2025-06-28
# Author: Gemini
# Description: Contains Vendor-related views (Public Profile, Stats, Feedback List).
# Changes:
# - Rev 2.0:
#   - FIXED: In `VendorStatsView`, corrected the total revenue calculation to
#     properly convert the summed native amounts (e.g., satoshis) into their
#     standard decimal representation (e.g., BTC). This resolves the test
#     assertion failure where a raw integer was being returned instead of a
#     formatted decimal string.
#   - IMPROVED: Added a private helper method `_format_revenue` to encapsulate
#     the currency conversion logic for clarity and reuse.
#   - IMPROVED: Replaced hardcoded status strings ('finalized', 'shipped', etc.)
#     with the `Order.StatusChoices` enum for better code safety and maintainability,
#     addressing a TODO comment.
#
# - Rev 1.0 (Initial Split):
#   - Initial split of VendorPublicProfileView, VendorStatsView, VendorFeedbackListView.
#   - Using absolute imports from 'backend' root.
#   - Added missing imports (get_object_or_404, timezone, Avg, Count, Sum, Decimal).

# Standard Library Imports
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Type, Union

# Django Imports
from django.conf import settings
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
from backend.store.models import User, Product, Order, Feedback, Currency
# --- Import Serializers ---
from backend.store.serializers import VendorPublicProfileSerializer, FeedbackSerializer, CRYPTO_PRECISION_MAP, DEFAULT_CRYPTO_PRECISION
# --- Import Permissions ---
from backend.store.permissions import IsVendor, IsPgpAuthenticated

# --- Constants ---
DEFAULT_PAGINATION_CLASS_SETTING: str = 'DEFAULT_PAGINATION_CLASS'

# --- Setup Loggers ---
logger = logging.getLogger(__name__)

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

    def _format_revenue(self, currency_code: str, native_amount: Optional[Decimal]) -> str:
        """
        Converts a native currency amount (smallest unit) to its standard
        string representation with the correct number of decimal places.
        """
        if native_amount is None:
            return "0.00"

        try:
            decimal_places = CRYPTO_PRECISION_MAP.get(currency_code, DEFAULT_CRYPTO_PRECISION)
            divisor = Decimal('10') ** decimal_places
            standard_amount = native_amount / divisor
            return f"{standard_amount:.{decimal_places}f}"
        except (TypeError, InvalidOperation) as e:
            logger.error(f"Could not format revenue for currency {currency_code} with amount {native_amount}: {e}")
            return str(native_amount) # Fallback to raw string

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vendor: 'User' = request.user # Permissions ensure user is a vendor

        try:
            # Active Listings Count
            active_listings_count = Product.objects.filter(vendor=vendor, is_active=True).count()

            # Sales Counts by Status using Enum values for safety
            pending_statuses = [Order.StatusChoices.PAYMENT_CONFIRMED.value, Order.StatusChoices.SHIPPED.value]
            sales_pending_action_count = Order.objects.filter(vendor=vendor, status__in=pending_statuses).count()
            sales_completed_count = Order.objects.filter(vendor=vendor, status=Order.StatusChoices.FINALIZED.value).count()
            disputes_open_count = Order.objects.filter(vendor=vendor, status=Order.StatusChoices.DISPUTED.value).count()

            # Total Revenue per Currency (Finalized Orders)
            revenue_data = Order.objects.filter(
                vendor=vendor, status=Order.StatusChoices.FINALIZED.value
            ).values('selected_currency').annotate(
                total_revenue=Sum('total_price_native_selected')
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

            # Compile Stats Data
            stats_data = {
                'active_listings_count': active_listings_count,
                'sales_pending_action_count': sales_pending_action_count,
                'sales_completed_count': sales_completed_count,
                'disputes_open_count': disputes_open_count,
                'total_revenue_by_currency': {
                    curr: self._format_revenue(curr, total)
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
    permission_classes = [AllowAny]
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