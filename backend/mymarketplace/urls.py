# backend/mymarketplace/urls.py
# Revision History:
# 2025-05-03: (Gemini Rev 12): # <<< NEW REVISION >>>
#   - FIXED: Corrected import path for HealthCheckView from
#     'backend.store.views' to 'backend.store.views.utility'
#     to resolve ImportError during URL loading and test collection.
# 2025-05-03: (Gemini Rev 11):
#   - FIXED: Standardized include() paths for local apps to use the
#     'backend.' prefix (e.g., 'backend.store.urls') to ensure
#     consistent module path resolution and resolve conflicting model errors.
# 2025-05-03: (Gemini Rev 10): Corrected import path for HealthCheckView
#     (store.views -> backend.store.views) to resolve
#     ImportError during URL configuration loading.
#     This enforces consistent absolute imports.
# --- Older revisions omitted ---

from django.contrib import admin
from django.urls import path, include
from django.conf import settings # For serving media in dev
from django.conf.urls.static import static # For serving media in dev
# Use absolute import path starting from 'backend.'
from backend.store.views.utility import HealthCheckView # FIXED: Import from correct submodule

# --- Define admin_site based on OTP installation ---
admin_site = admin.site # Default to standard admin
if 'django_otp' in settings.INSTALLED_APPS:
    try:
        from django_otp.admin import OTPAdminSite
        # Use OTP-protected admin site if OTP enabled in settings
        admin_site = OTPAdminSite(name='OTPAdmin')
        # Note: You might need to manually register models here if default discovery isn't enough
        # or if you unregister the default admin's models first.
    except ImportError:
        # Handle case where django_otp is listed but not fully installed/configured
        pass # Fallback to default admin_site

# --- Main URL Patterns ---
urlpatterns = [
    # Health Check Endpoint (unauthenticated, often first)
    path('health/', HealthCheckView.as_view(), name='health_check'),

    # Admin site (Use /control/ for the secure admin interface, using the defined admin_site)
    path('control/', admin_site.urls),

    # Custom Admin Panel URLs (using 'backend.' prefix)
    path('panel/', include('backend.adminpanel.urls', namespace='adminpanel')), # FIXED PATH

    # Core Store API endpoints (using 'backend.' prefix)
    path('api/store/', include('backend.store.urls', namespace='store')), # FIXED PATH

    # Notifications API Endpoints (using 'backend.' prefix)
    path('api/notifications/', include('backend.notifications.urls', namespace='notifications')), # FIXED PATH

    # Forum URLs (using 'backend.' prefix)
    path('forum/', include('backend.forum.urls', namespace='forum')), # FIXED PATH

    # Captcha URLs
    path('captcha/', include('captcha.urls')),

    # --- Optional Authentication Endpoints (Uncomment if used) ---
    # path('api/auth/', include('djoser.urls')),
    # path('api/auth/', include('djoser.urls.authtoken')),
    # path('api/auth/', include('djoser.urls.jwt')),

    # from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
    # path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # --- Other potential app includes ---
    # Add paths for other apps like 'withdraw' if they have URL endpoints
    # path('api/withdraw/', include('backend.withdraw.urls', namespace='withdraw')), # Example FIXED PATH

]

# --- Development-Only URL Patterns ---
if settings.DEBUG:
    # Serve media files uploaded by users during development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Add Django Debug Toolbar URLs if installed
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        # Ensure debug_toolbar.urls is importable if included this way
        # Or use: import debug_toolbar; urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
        # Requires debug_toolbar to be installed: pip install django-debug-toolbar
        try:
            import debug_toolbar
            urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
        except ImportError:
            # Log or warn that debug toolbar is in INSTALLED_APPS but not installed?
            pass


    # Add Sentry debug trigger URL if Sentry is enabled and in DEBUG mode
    if hasattr(settings, 'SENTRY_DSN') and settings.SENTRY_DSN:
         urlpatterns += [path('sentry-debug/', lambda request: 1 / 0, name='sentry-debug')]

# <<< END OF FILE: backend/mymarketplace/urls.py >>>