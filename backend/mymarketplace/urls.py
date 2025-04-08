# backend/mymarketplace/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings # For serving media in dev
from django.conf.urls.static import static # For serving media in dev
from django_otp.admin import OTPAdminSite # For OTP admin
from store.views import HealthCheckView # Import HealthCheckView

# Use OTP-protected admin site if OTP enabled in settings
if 'django_otp' in settings.INSTALLED_APPS:
    admin_site = OTPAdminSite(name='OTPAdmin') # Use custom name if needed
    # Register models manually if default discovery isn't enough
    # from django.contrib.auth.models import User, Group
    # admin_site.register(User) # Example
    # admin_site.register(Group) # Example
else:
    admin_site = admin.site # Use default admin

urlpatterns = [
    # Use /control/ for the secure admin interface
    path('control/', admin_site.urls),

    # Custom Admin Panel (ensure 'adminpanel.urls' exists and defines necessary paths)
    path('panel/', include('adminpanel.urls')),

    # Core Store API endpoints
    path('api/store/', include('store.urls')),
    
    path('control/', admin_site.urls),
    path('panel/', include('adminpanel.urls')),
    path('api/store/', include('store.urls')),

    # --- Include Notifications API Endpoints ---
    path('api/notifications/', include('notifications.urls')), # Add this line

    # Include djoser auth endpoints if using it
    # path('api/auth/', include('djoser.urls')),
    # path('api/auth/', include('djoser.urls.authtoken')),

    path('captcha/', include('captcha.urls')),
    path('health/', HealthCheckView.as_view(), name='health_check'),

    # Maybe JWT paths?
    # path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # --- Add Notifications API Endpoint ---
    path('api/', include('notifications.urls')), # Include notification URLs under /api/

    # Include djoser auth endpoints if using it (adjust prefix as needed)
    # path('api/auth/', include('djoser.urls')),
    # path('api/auth/', include('djoser.urls.authtoken')), # If using TokenAuth

    # CAPTCHA URLs
    path('captcha/', include('captcha.urls')),

    # Health Check
    path('health/', HealthCheckView.as_view(), name='health_check'),

    # Maybe JWT paths if using SimpleJWT?
    # path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# In mymarketplace/urls.py
urlpatterns = [
    # ... other paths ...
    path('forum/', include('forum.urls', namespace='forum')), # Add this
    # ... rest of paths ...
]

# Use OTP-protected admin site if not DEBUG
if not settings.DEBUG:
    admin.site.__class__ = OTPAdminSite

urlpatterns = [
    # Health Check Endpoint (unauthenticated)
    path('health/', HealthCheckView.as_view(), name='health_check'),

    # Admin site (use OTP-protected admin in production)
    path('control/', admin.site.urls), # Changed path from 'admin/' for slight obscurity

    # Core application URLs
    path('api/store/', include('store.urls', namespace='store')), # API endpoints under /api/
    path('api/auth/', include('djoser.urls')), # If using Djoser for user management endpoints
    path('api/auth/', include('djoser.urls.authtoken')), # If using Djoser token auth

    # OTP URLs (modify paths as needed)
    # path('account/two_factor/', include('two_factor.urls', 'two_factor')), # Using custom PGP OTP, remove this?
    # Add URLs for custom PGP OTP setup/verification here

    # Admin Panel URLs (secured in views)
    path('panel/', include('adminpanel.urls', namespace='adminpanel')),

    # Captcha URLs
    path('captcha/', include('captcha.urls')),

    # Frontend should handle UI routing; these might be legacy or backend-rendered pages
    # path('', include('frontend_rendering_app.urls')), # Example if Django serves some UI pages

]

# Serve media files during development ONLY
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Add Sentry debug trigger URL if Sentry is enabled and in DEBUG mode
if settings.DEBUG and settings.SENTRY_DSN:
     urlpatterns += [path('sentry-debug/', lambda request: 1 / 0, name='sentry-debug')]