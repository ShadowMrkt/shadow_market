# backend/mymarketplace/settings/prod.py
# Revision History:
# 2025-04-08: Addressed Bandit B105 warning by Gemini.
#           - Added '# nosec B105' to the SECRET_KEY check line to suppress the
#             warning, as the check against the default key is intentional.
# 2025-04-07: Initial update for production hardening.
#           - Added HTTPS security headers (HSTS, Secure Cookies, SSL Redirect).
#           - Uncommented SECURE_PROXY_SSL_HEADER (assuming proxy).
#           - Uncommented Whitenoise staticfiles storage.
#           - Added explicit AXES failure limits.
#           - Replaced print statement with logger info.
#           - Added comments emphasizing secure env var loading in base.py.
#           - Kept existing critical setting checks as safeguards.
#           - Ensured BrowsableAPIRenderer removal.

from .base import * # noqa: F403, F401
import os
import sys
import logging
from datetime import timedelta # Added missing timedelta import

logger = logging.getLogger(__name__)

# --- Production Specific Settings ---
DEBUG = False

# Set environment variable for other parts of the system to know
os.environ['DJANGO_ENV'] = 'production'

# --- Critical Setting Validation ---
# These checks act as safeguards. The primary mechanism for loading these
# MUST be via environment variables or a secure vault integration configured
# in base.py (e.g., using django-environ). Never commit default/dev values.

# Ensure SECRET_KEY is properly set via environment or vault
if not SECRET_KEY or SECRET_KEY == 'dev-secret-key-replace-me-if-not-using-vault': # noqa: F405 # nosec B105
    sys.stderr.write("CRITICAL: Production SECRET_KEY is not set or is insecure! Ensure DJANGO_SECRET_KEY env var is set.\n")
    sys.exit(1)

# Ensure Database connection is properly configured via environment or vault
# Check a key setting like USER, assuming it's populated from env vars like DATABASE_USER
if not DATABASES['default'].get('USER') or DATABASES['default']['USER'] == 'user': # noqa: F405
    sys.stderr.write("CRITICAL: Production Database is not configured correctly! Check DATABASE_* env vars.\n")
    sys.exit(1)
# Add similar checks for other critical DB settings if necessary (PASSWORD, HOST, etc.)

# Ensure ALLOWED_HOSTS is correctly populated via DJANGO_ALLOWED_HOSTS env var
# It should ONLY contain the production domain(s) / .onion address(es).
# Example: DJANGO_ALLOWED_HOSTS=.your-onion-domain.onion,www.your-clearnet-domain.com
# The env var should be parsed in base.py, e.g., using env.list('DJANGO_ALLOWED_HOSTS')
if 'localhost' in ALLOWED_HOSTS or '127.0.0.1' in ALLOWED_HOSTS or not ALLOWED_HOSTS: # noqa: F405
    sys.stderr.write("CRITICAL: DJANGO_ALLOWED_HOSTS is not configured correctly for production!\n")
    sys.stderr.write(f"           Current value: {ALLOWED_HOSTS}\n") # noqa: F405
    sys.stderr.write("           Ensure DJANGO_ALLOWED_HOSTS env var is set and contains ONLY production hostnames.\n")
    sys.exit(1)


# --- Production Security Enhancements ---

# HTTPS Security Settings (Assuming TLS termination at a proxy like Nginx/Tor)
# Trust the X-Forwarded-Proto header from the proxy to determine scheme
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Redirect all HTTP requests to HTTPS
SECURE_SSL_REDIRECT = True
# Ensure session cookies are only sent over HTTPS
SESSION_COOKIE_SECURE = True
# Ensure CSRF cookies are only sent over HTTPS
CSRF_COOKIE_SECURE = True
# Enable HTTP Strict Transport Security (HSTS)
# Set a long duration (e.g., 1 year = 31536000 seconds) once confident
SECURE_HSTS_SECONDS = 31536000  # Start with a smaller value (e.g., 3600) during initial deployment
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# Consider adding your domain to the HSTS preload list after thorough testing
# SECURE_HSTS_PRELOAD = True


# Use a more robust cache backend like Redis in production
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        # Ensure REDIS_URL is set via environment variable
        'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379/1'), # noqa: F405 Use DB 1 for cache
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            # Load password from environment if Redis requires authentication
            # 'PASSWORD': env('REDIS_PASSWORD', default=None), # noqa: F405
            # Consider adding connection pool settings for high load
            # 'CONNECTION_POOL_KWARGS': {'max_connections': 50}
        }
    }
}

# Ensure Axes uses cache handler for distributed environments and set limits
AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler'
AXES_CACHE = 'default' # Use the default Redis cache
AXES_FAILURE_LIMIT = env.int('AXES_FAILURE_LIMIT', 5)  # Lock out after 5 failures # noqa: F405
AXES_COOLOFF_TIME = timedelta(minutes=env.int('AXES_COOLOFF_MINUTES', 15)) # Lockout duration # noqa: F405 F821

# Session engine: Cached DB backend recommended for security
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'

# Static files storage: Use Whitenoise for serving static files directly from Python
# Ensure 'whitenoise.middleware.WhiteNoiseMiddleware' is high up in MIDDLEWARE (base.py)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
# STATIC_ROOT must be set in base.py and `collectstatic` must be run during deployment


# Logging configuration for production
# Recommendation: Configure a JSON formatter in base.py for structured logging
# Recommendation: Send logs to a central aggregation system (e.g., ELK, Splunk, Datadog)
# Ensure sensitive information (passwords, tokens, PII) is NOT logged anywhere.
LOGGING['handlers']['console']['level'] = 'INFO'  # Or WARNING # noqa: F405
LOGGING['loggers']['django']['level'] = 'INFO' # noqa: F405
LOGGING['loggers']['myapp'] = {  # Example: Set level for your specific app # noqa: F405
    'handlers': ['console'], # Add file/remote handlers as needed
    'level': 'INFO',
    'propagate': False,
}
# Example (assuming JSON formatter 'json_formatter' is defined in base.py LOGGING dict):
# LOGGING['handlers']['console']['formatter'] = 'json_formatter'


# Remove DRF's Browsable API Renderer in production for security/cleanliness
# Check if REST_FRAMEWORK is defined and has DEFAULT_RENDERER_CLASSES
if 'REST_FRAMEWORK' in locals() and 'DEFAULT_RENDERER_CLASSES' in REST_FRAMEWORK: # noqa: F405 F821
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = tuple( # noqa: F405 F821
        cls for cls in REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] # noqa: F405 F821
        if cls != 'rest_framework.renderers.BrowsableAPIRenderer'
    )
else:
    # If REST_FRAMEWORK is not defined here, ensure it's handled correctly in base.py
    # or define it here specifically for production without the BrowsableAPIRenderer.
    # Example:
    # REST_FRAMEWORK = {
    #     'DEFAULT_RENDERER_CLASSES': (
    #         'rest_framework.renderers.JSONRenderer',
    #         # Other production renderers...
    #     ),
    #     # Other production DRF settings...
    # }
    pass # Assuming REST_FRAMEWORK is defined and handled in base.py


# Log startup mode
logger.info("--- Running Django Configuration: Production Mode ---")

# --- END Production Settings ---