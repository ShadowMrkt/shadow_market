# backend/mymarketplace/settings/prod.py
# <<< Revision v1.1.0 (Enterprise Polish) >>>
# Revision History:
# - v1.1.0 (Current - 2025-04-10):
#   - REFACTOR: Removed redundant settings definitions (Cache URL, HSTS, Axes); rely on base.py + environ.
#   - REFACTOR: Refined critical setting checks to ensure values are loaded (not None/empty), not checking specific defaults.
#   - REFACTOR: Removed redundant ALLOWED_HOSTS check (present in base.py).
#   - REFACTOR: Removed direct manipulation of LOGGING and REST_FRAMEWORK dicts; rely on base.py logic based on DEBUG=False.
#   - IMPROVEMENT: Use logger for critical errors before sys.exit.
#   - STYLE: Removed unused imports (os, sys, timedelta).
# - v1.0.1 (2025-04-08): Addressed Bandit B105 warning by Gemini.
# - v1.0.0 (2025-04-07): Initial update for production hardening.

from .base import * # noqa: F403, F401 - Import base settings (includes environ 'env')
import logging
import sys

# Acquire the logger configured in base.py
# Use 'django' or a specific logger name if preferred over root
logger = logging.getLogger(__name__) # Use __name__ for this file's logger

# --- Production Specific Settings ---
DEBUG = False

# Set environment variable for other parts of the system (redundant if DJANGO_ENV is already set externally)
# os.environ['DJANGO_ENV'] = 'production' # This should ideally be set in the deployment environment itself

# --- Critical Setting Validation ---
# These checks act as safeguards ensuring that settings loaded via Vault/Environment
# in base.py are actually present and not empty/None in the production context.

# Ensure SECRET_KEY was successfully loaded
# base.py already exits if it's None after trying env/Vault. This is an extra check.
if not SECRET_KEY:  # noqa: F405
    logger.critical("CRITICAL: Production SECRET_KEY is missing after loading base settings!")
    sys.exit(1)

# Ensure essential Database connection parameters were loaded
# Check essential keys that should be present in a production URL/config
# Note: base.py env.db() provides defaults, so these checks ensure prod values were likely sourced.
db_default = DATABASES.get('default', {}) # noqa: F405
if not all([db_default.get('ENGINE'), db_default.get('NAME'), db_default.get('USER')]): # Add HOST/PORT if needed
    logger.critical(
        "CRITICAL: Production Database seems incorrectly configured "
        f"(ENGINE: {db_default.get('ENGINE')}, NAME: {db_default.get('NAME')}, USER: {db_default.get('USER')}). "
        "Check DATABASE_URL env var/Vault secret."
    )
    sys.exit(1)

# Note: ALLOWED_HOSTS check is performed in base.py and exits if misconfigured for production.

# --- Production Security Enhancements ---
# These settings rely on values potentially loaded from environment variables in base.py.
# Ensure the respective env vars (e.g., SECURE_PROXY_SSL_HEADER_SETTING, REDIS_URL) are set in production.

# Assuming TLS termination at a proxy (Nginx/Tor) that sets X-Forwarded-Proto
# Use value configured via env var in base.py (defaults to ('HTTP_X_FORWARDED_PROTO', 'https'))
# SECURE_PROXY_SSL_HEADER = env.tuple('SECURE_PROXY_SSL_HEADER_SETTING', default=('HTTP_X_FORWARDED_PROTO', 'https')) # Configured in base

# Ensure HTTPS settings loaded from base.py are active (True by default via env)
# SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
# SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
# CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)

# Ensure HSTS settings loaded from base.py are active
# SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=63072000) # 2 years default in base
# SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
# SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)

# --- Production Cache ---
# Rely on CACHES configuration defined in base.py, which uses env('REDIS_URL').
# Ensure REDIS_URL environment variable is set correctly in production.
if 'default' not in CACHES or 'django_redis.cache.RedisCache' not in CACHES['default'].get('BACKEND', ''): # noqa: F405
    logger.warning("WARNING: Default cache backend does not appear to be Redis. Check CACHES in base.py and REDIS_URL env var.")

# --- Axes Handler ---
# Rely on AXES_HANDLER ('axes.handlers.cache.AxesCacheHandler') set in base.py.
# Ensure AXES_ENABLED=True and cache is working.

# --- Session Engine ---
# Ensure secure session engine is used (cached_db recommended)
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db' # Explicitly set for production

# --- Static Files ---
# Use Whitenoise for serving static files directly from Python application
# Ensure 'whitenoise.middleware.WhiteNoiseMiddleware' is correctly placed in MIDDLEWARE (base.py)
# Ensure STATIC_ROOT is defined (base.py) and `collectstatic` is run during deployment.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# --- Logging ---
# Rely on the LOGGING configuration defined in base.py.
# base.py should configure formatters (JSON) and handlers (file rotation, console)
# based on the DEBUG setting (which is False here). Ensure Sentry is configured there if used.
logger.info("Production logging configuration active (check base.py for details).")

# --- REST Framework ---
# Rely on REST_FRAMEWORK configuration in base.py.
# base.py should remove the BrowsableAPIRenderer when DEBUG is False.
logger.info("Production DRF configuration active (check base.py for details).")


# --- Final Startup Log ---
logger.info(f"--- Django Configuration Loaded: Production Mode (PID: {os.getpid()}) ---") # noqa: F405 Added PID for clarity

# --- END Production Settings ---