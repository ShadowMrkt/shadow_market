# backend/store/urls.py
# --- Revision History ---
# - v17 (2025-06-07): # <<< NEW REVISION >>>
#   - FIXED: Corrected the import for CategoryViewSet. It was being imported from
#     'product.py' which likely contained a read-only version. Changed the import
#     to use the full ModelViewSet from 'category.py', which resolves the
#     '405 Method Not Allowed' errors for POST, PATCH, and DELETE requests.
# - v16 (2025-05-03):
#   - FIXED: Corrected view alias for 'vendor-feedback-list' URL pattern.
#     Changed 'feedback_views.VendorFeedbackListView' to 'vendor_views.VendorFeedbackListView'
#     to resolve AttributeError during test collection. Assumes the view exists
#     in 'backend/store/views/vendor.py'.
# - v15 (2025-05-03):
#   - FIXED: Corrected import for CurrentUserView. Changed from non-existent
#     'backend.store.views.user' to use the existing 'auth_views' alias,
#     resolving ModuleNotFoundError during test collection. Assumes CurrentUserView
#     is defined within 'backend/store/views/auth.py'.
# - v14 (2025-05-03): Changed user view import to be direct class import from views.user. (Failed - ModuleNotFound)
# - v13 (2025-05-03): Attempted direct module import for user view (Failed). (Gemini)
# - v12 (2025-05-03): Changed all view imports back to 'import module as alias' (Failed for user). (Gemini)
# --- Older revisions omitted ---
# --- END Revision History ---

"""
URL Configuration for the 'store' application.
"""

from django.urls import path, include
from rest_framework_nested import routers

# --- Import View Modules/Classes ---
# Import modules for views used multiple times or with routers
from backend.store.views import application as application_views
from backend.store.views import auth as auth_views
from backend.store.views import canary as canary_views
from backend.store.views import category as category_views # FIX v17: Import category views
from backend.store.views import feedback as feedback_views
from backend.store.views import order as order_views
from backend.store.views import product as product_views
from backend.store.views import tickets as ticket_views
from backend.store.views import utility as utility_views
from backend.store.views import vendor as vendor_views # Alias for vendor views
from backend.store.views import wallet as wallet_views
from backend.store.views import webauthn as webauthn_views

# --- FIX v17: Remove incorrect direct import ---
# from backend.store.views.product import CategoryViewSet

# Define the application namespace
app_name = 'store'

# --- Router Configuration ---
router = routers.DefaultRouter()

# Register ViewSets
# --- FIX v17: Register the correct CategoryViewSet from its own module ---
router.register(r'categories', category_views.CategoryViewSet, basename='category')
router.register(r'products', product_views.ProductViewSet, basename='product')
router.register(r'orders', order_views.OrderViewSet, basename='order')
router.register(r'tickets', ticket_views.SupportTicketViewSet, basename='ticket')

# --- Nested Router Configuration ---
tickets_router = routers.NestedSimpleRouter(router, r'tickets', lookup='ticket')
tickets_router.register(r'messages', ticket_views.TicketMessageViewSet, basename='ticket-message')


# --- URL Patterns ---
urlpatterns = [
    # --- Authentication & Authorization ---
    path('auth/register/', auth_views.RegisterView.as_view(), name='register'),
    path('auth/login/init/', auth_views.LoginInitView.as_view(), name='login-init'),
    path('auth/login/pgp_verify/', auth_views.LoginPgpVerifyView.as_view(), name='login-pgp-verify'),
    path('auth/logout/', auth_views.LogoutView.as_view(), name='logout'),

    # --- WebAuthn (FIDO2) ---
    path('auth/webauthn/register/options/', webauthn_views.WebAuthnRegistrationOptionsView.as_view(), name='webauthn-register-options'),
    path('auth/webauthn/register/verify/', webauthn_views.WebAuthnRegistrationVerificationView.as_view(), name='webauthn-register-verify'),
    path('auth/webauthn/authenticate/options/', webauthn_views.WebAuthnAuthenticationOptionsView.as_view(), name='webauthn-authenticate-options'),
    path('auth/webauthn/authenticate/verify/', webauthn_views.WebAuthnAuthenticationVerificationView.as_view(), name='webauthn-authenticate-verify'),

    # --- User Management ---
    path('users/me/', auth_views.CurrentUserView.as_view(), name='user-me'),
    path('users/me/webauthn/credentials/', webauthn_views.WebAuthnCredentialListView.as_view(), name='webauthn-credential-list'),
    path('users/me/webauthn/credentials/<uuid:pk>/', webauthn_views.WebAuthnCredentialDetailView.as_view(), name='webauthn-credential-detail'),

    # --- Vendor Specific ---
    path('vendors/<str:username>/', vendor_views.VendorPublicProfileView.as_view(), name='vendor-detail'),
    path('vendor/stats/', vendor_views.VendorStatsView.as_view(), name='vendor-stats'),
    path('vendors/<str:username>/feedback/', vendor_views.VendorFeedbackListView.as_view(), name='vendor-feedback-list'),

    # --- Vendor Application ---
    path('vendor/applications/', application_views.VendorApplicationCreateView.as_view(), name='vendor-application-create'),
    path('vendor/applications/status/', application_views.VendorApplicationStatusView.as_view(), name='vendor-application-status'),

    # --- Order Specific Actions ---
    path('orders/place/', order_views.PlaceOrderView.as_view(), name='order-place'),
    path('orders/<uuid:pk>/ship/', order_views.MarkShippedView.as_view(), name='order-ship'),
    path('orders/<uuid:pk>/finalize/', order_views.FinalizeOrderView.as_view(), name='order-finalize'),
    path('orders/<uuid:pk>/prepare-release-tx/', order_views.PrepareReleaseTxView.as_view(), name='order-prepare-release-tx'),
    path('orders/<uuid:pk>/sign_release/', order_views.SignReleaseView.as_view(), name='order-sign-release'),
    path('orders/<uuid:pk>/dispute/', order_views.OpenDisputeView.as_view(), name='order-dispute'),

    # --- Wallet ---
    path('wallet/withdraw/prepare/', wallet_views.WithdrawalPrepareView.as_view(), name='withdrawal-prepare'),
    path('wallet/balances/', wallet_views.WalletBalanceView.as_view(), name='wallet-balances'),

    # --- Feedback ---
    path('feedback/submit/', feedback_views.FeedbackCreateView.as_view(), name='feedback-submit'),

    # --- Utilities & Misc ---
    path('utils/encrypt-for-vendor/', utility_views.EncryptForVendorView.as_view(), name='util-encrypt-shipping'),
    path('health/', utility_views.HealthCheckView.as_view(), name='health-check'),
    path('canary/', canary_views.CanaryDetailView.as_view(), name='canary-detail'),
    path('exchange-rates/', utility_views.ExchangeRateView.as_view(), name='exchange-rates'),

    # --- Include Router URLs ---
    path('', include(router.urls)),
    path('', include(tickets_router.urls)),
]

# --- END URL Configuration ---