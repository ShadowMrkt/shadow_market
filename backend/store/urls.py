# backend/store/urls.py

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
    # Core Resources (ViewSets)
    CategoryViewSet,
    ProductViewSet,
    OrderViewSet, # Used for both user orders and vendor sales lists
    SupportTicketViewSet,
    TicketMessageViewSet,
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
)

# Define the application namespace for URL reversing (e.g., {% url 'store:product-list' %})
app_name = 'store'

# --- Router Configuration ---
# Use DefaultRouter to get the default API root view
router = routers.DefaultRouter()

# Register ViewSets with the main router
# Basenames are explicitly set for clarity and consistency, especially important
# if the queryset or serializer_class is dynamic or customized.
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
# Endpoint for users to manage/view their own orders
router.register(r'orders', OrderViewSet, basename='order')
# Endpoint for users to manage/view their own support tickets
router.register(r'tickets', SupportTicketViewSet, basename='ticket')
# Endpoint specifically for vendors to view their sales (filtered OrderViewSet)
# Note: Ensure OrderViewSet filters appropriately based on the requesting user (vendor)
router.register(r'vendor/sales', OrderViewSet, basename='vendor-sales')

# --- Nested Router Configuration ---
# Nested router for messages within support tickets
# Generates URLs like: /tickets/{ticket_pk}/messages/
tickets_router = routers.NestedSimpleRouter(router, r'tickets', lookup='ticket')
tickets_router.register(r'messages', TicketMessageViewSet, basename='ticket-message')


# --- URL Patterns ---
# Define specific URL paths that map to individual views (non-ViewSet or custom actions)
# Grouped logically for readability.
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
    # WebAuthn Credential Management (associated with the current user)
    path('users/me/webauthn/credentials/', WebAuthnCredentialListView.as_view(), name='webauthn-credential-list'),
    # Use <str:..> for the credential ID as it's typically Base64URL encoded
    path('users/me/webauthn/credentials/<str:credential_id_b64>/', WebAuthnCredentialDetailView.as_view(), name='webauthn-credential-detail'),

    # --- Vendor Specific ---
    # Public vendor profile view
    path('vendors/<str:username>/', VendorPublicProfileView.as_view(), name='vendor-detail'),
    # Vendor-specific statistics (requires vendor authentication)
    path('vendor/stats/', VendorStatsView.as_view(), name='vendor-stats'),
    # TODO: Implement Vendor feedback list/detail endpoint: 'vendors/<str:username>/feedback/'

    # --- Order Specific Actions ---
    # Note: List/Detail/Update/Delete provided by router above ('orders/')
    path('orders/place/', PlaceOrderView.as_view(), name='order-place'), # Create a new order
    path('orders/<uuid:pk>/ship/', MarkShippedView.as_view(), name='order-ship'), # Mark order as shipped (Vendor action)
    path('orders/<uuid:pk>/finalize/', FinalizeOrderView.as_view(), name='order-finalize'), # Finalize order (Buyer action)
    path('orders/<uuid:pk>/prepare-release-tx/', PrepareReleaseTxView.as_view(), name='order-prepare-release-tx'), # Prepare tx for releasing funds
    path('orders/<uuid:pk>/sign_release/', SignReleaseView.as_view(), name='order-sign-release'), # Sign tx to release funds
    path('orders/<uuid:pk>/dispute/', OpenDisputeView.as_view(), name='order-dispute'), # Open a dispute for an order

    # --- Wallet ---
    path('wallet/withdraw/prepare/', WithdrawalPrepareView.as_view(), name='withdrawal-prepare'), # Prepare withdrawal transaction
    path('wallet/withdraw/execute/', WithdrawalExecuteView.as_view(), name='withdrawal-execute'), # Execute withdrawal transaction
    # TODO: Add Balance URL '/wallet/balances/' view

    # --- Feedback ---
    path('feedback/submit/', FeedbackCreateView.as_view(), name='feedback-submit'), # Submit feedback for an order/vendor

    # --- Utilities ---
    path('utils/encrypt-for-vendor/', EncryptForVendorView.as_view(), name='util-encrypt-shipping'), # Utility to encrypt shipping info
    path('health/', HealthCheckView.as_view(), name='health-check'), # Basic health check endpoint

    # --- Warrant Canary ---
    path('canary/', CanaryDetailView.as_view(), name='canary-detail'), # Display warrant canary details

    # --- Include Router URLs ---
    # It's generally best practice to include router URLs *after* specific paths
    # to ensure specific paths are matched first.
    path('', include(router.urls)),
    path('', include(tickets_router.urls)), # Includes nested message URLs
]

# --- Sanity Check ---
# Ensure all explicitly imported views are used in the patterns above.
# Ensure all ViewSets registered with routers are imported.