# backend/store/urls.py
# Revision: 2
# Date: 2025-04-09 # Updated Date
# Changes:
# - Rev 2:
#   - ADDED: URL patterns for ExchangeRateView, VendorApplicationCreateView, VendorApplicationStatusView.
#   - Imported the new views.
# - Rev 1 (Original):
#   - Initial setup with routers and paths for existing views.

"""
URL Configuration for the 'store' application.

Defines URL patterns for API endpoints related to authentication, users,
vendors, products, categories, orders, wallets, support tickets,
feedback, utilities, and warrant canary. Uses Django REST Framework's
routers for standard ViewSet actions and explicit paths for custom actions.
"""

from django.urls import path, include
from rest_framework_nested import routers

# Explicitly import all views used in this urls.py for clarity
# This makes dependencies easier to track than `from . import views`
from .views import (
    # Authentication & User
    RegisterView,
    LoginInitView,
    LoginPgpVerifyView,
    LogoutView,
    CurrentUserView,
    # WebAuthn (FIDO2)
    WebAuthnRegistrationOptionsView,
    WebAuthnRegistrationVerificationView,
    WebAuthnAuthenticationOptionsView,
    WebAuthnAuthenticationVerificationView,
    WebAuthnCredentialListView,
    WebAuthnCredentialDetailView,
    # Vendor
    VendorPublicProfileView,
    VendorStatsView,
    # Vendor Applications (NEW)
    VendorApplicationCreateView,
    VendorApplicationStatusView,
    # Core Resources (ViewSets)
    CategoryViewSet,
    ProductViewSet,
    OrderViewSet, # Used for both user orders and vendor sales lists
    SupportTicketViewSet,
    # TicketMessageViewSet, # This seems unused in Rev 1 urls.py, imported from views though. Keep commented?
    # Order Actions
    PlaceOrderView,
    MarkShippedView,
    FinalizeOrderView,
    PrepareReleaseTxView,
    SignReleaseView,
    OpenDisputeView,
    # Wallet
    WithdrawalPrepareView,
    WithdrawalExecuteView,
    # TODO: Implement and add view for '/wallet/balances/'
    # Feedback
    FeedbackCreateView,
    # TODO: Implement and add view for vendor feedback: 'vendors/<str:username>/feedback/'
    # Utilities & Misc
    EncryptForVendorView,
    HealthCheckView,
    CanaryDetailView,
    ExchangeRateView, # <-- Add import
)

# Define the application namespace for URL reversing (e.g., {% url 'store:product-list' %})
app_name = 'store'

# --- Router Configuration ---
# Use DefaultRouter to get the default API root view
router = routers.DefaultRouter()

# Register ViewSets with the main router
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'tickets', SupportTicketViewSet, basename='ticket')
router.register(r'vendor/sales', OrderViewSet, basename='vendor-sales')

# --- Nested Router Configuration ---
# Nested router for messages within support tickets
# Generates URLs like: /tickets/{ticket_pk}/messages/
# Re-enabling based on TicketMessageViewSet import, assuming it's needed later or was accidentally excluded.
tickets_router = routers.NestedSimpleRouter(router, r'tickets', lookup='ticket')
# tickets_router.register(r'messages', TicketMessageViewSet, basename='ticket-message') # Needs TicketMessageViewSet defined/imported


# --- URL Patterns ---
# Define specific URL paths that map to individual views (non-ViewSet or custom actions)
urlpatterns = [
    # --- Authentication & Authorization ---
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/init/', LoginInitView.as_view(), name='login-init'),
    path('auth/login/pgp_verify/', LoginPgpVerifyView.as_view(), name='login-pgp-verify'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),

    # --- WebAuthn (FIDO2) ---
    path('auth/webauthn/register/options/', WebAuthnRegistrationOptionsView.as_view(), name='webauthn-register-options'),
    path('auth/webauthn/register/verify/', WebAuthnRegistrationVerificationView.as_view(), name='webauthn-register-verify'),
    path('auth/webauthn/authenticate/options/', WebAuthnAuthenticationOptionsView.as_view(), name='webauthn-authenticate-options'),
    path('auth/webauthn/authenticate/verify/', WebAuthnAuthenticationVerificationView.as_view(), name='webauthn-authenticate-verify'),

    # --- User Management ---
    path('users/me/', CurrentUserView.as_view(), name='user-me'),
    path('users/me/webauthn/credentials/', WebAuthnCredentialListView.as_view(), name='webauthn-credential-list'),
    path('users/me/webauthn/credentials/<str:credential_id_b64>/', WebAuthnCredentialDetailView.as_view(), name='webauthn-credential-detail'),

    # --- Vendor Specific ---
    path('vendors/<str:username>/', VendorPublicProfileView.as_view(), name='vendor-detail'),
    path('vendor/stats/', VendorStatsView.as_view(), name='vendor-stats'),
    # TODO: Implement Vendor feedback list/detail endpoint: 'vendors/<str:username>/feedback/'

    # --- NEW: Vendor Application ---
    path('vendor/applications/', VendorApplicationCreateView.as_view(), name='vendor-application-create'),
    path('vendor/applications/status/', VendorApplicationStatusView.as_view(), name='vendor-application-status'),

    # --- Order Specific Actions ---
    path('orders/place/', PlaceOrderView.as_view(), name='order-place'),
    path('orders/<uuid:pk>/ship/', MarkShippedView.as_view(), name='order-ship'),
    path('orders/<uuid:pk>/finalize/', FinalizeOrderView.as_view(), name='order-finalize'),
    path('orders/<uuid:pk>/prepare-release-tx/', PrepareReleaseTxView.as_view(), name='order-prepare-release-tx'),
    path('orders/<uuid:pk>/sign_release/', SignReleaseView.as_view(), name='order-sign-release'),
    path('orders/<uuid:pk>/dispute/', OpenDisputeView.as_view(), name='order-dispute'),

    # --- Wallet ---
    path('wallet/withdraw/prepare/', WithdrawalPrepareView.as_view(), name='withdrawal-prepare'),
    path('wallet/withdraw/execute/', WithdrawalExecuteView.as_view(), name='withdrawal-execute'),
    # TODO: Add Balance URL '/wallet/balances/' view

    # --- Feedback ---
    path('feedback/submit/', FeedbackCreateView.as_view(), name='feedback-submit'),

    # --- Utilities & Misc ---
    path('utils/encrypt-for-vendor/', EncryptForVendorView.as_view(), name='util-encrypt-shipping'),
    path('health/', HealthCheckView.as_view(), name='health-check'),
    path('canary/', CanaryDetailView.as_view(), name='canary-detail'),
    # --- NEW: Exchange Rates ---
    path('exchange-rates/', ExchangeRateView.as_view(), name='exchange-rates'),

    # --- Include Router URLs ---
    path('', include(router.urls)),
    path('', include(tickets_router.urls)), # Includes nested message URLs
]

# --- Sanity Check ---
# Ensure all explicitly imported views are used in the patterns above.
# Ensure all ViewSets registered with routers are imported.