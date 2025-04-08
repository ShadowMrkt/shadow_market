# backend/mymarketplace/settings/dev.py
"""
Django settings for the 'mymarketplace' project in LOCAL DEVELOPMENT mode.

WARNING: DEVELOPMENT MODE. DEBUG is enabled.
This configuration includes settings optimized for local development convenience
and debugging, such as relaxed security settings for HTTP, debug toolbar integration,
and verbose logging.

*** IT MUST NEVER BE USED FOR STAGING OR PRODUCTION ENVIRONMENTS. ***

Inherits base settings from .base and overrides specifics for development.
"""
# <<< ENTERPRISE GRADE REVISION: v1.0.2 - Set Console Handler Level to DEBUG >>>
# Revision Notes:
# - v1.0.2: (Current - 2025-04-06) # Updated date
#   - FIXED: Explicitly set the 'level' of the 'console' handler to 'DEBUG' within
#     the LOGGING dictionary modifications. This ensures that DEBUG level messages
#     processed by loggers (like 'store.services') are actually output to the console.
# - v1.0.1:
#   - FIXED: Explicitly configured the 'store.services' logger in the LOGGING dictionary
#     to ensure DEBUG level messages are captured and output to the console during
#     development and testing (when using appropriate pytest flags like -s).
#   - ADDED: More defensive checks around LOGGING dictionary modification to prevent KeyErrors.
# - v1.0.0: Initial development settings file, inheriting from base.

import sys
# print(f"DEBUG sys.path = {sys.path}") # Keep for initial debug if needed
import os
# import sys # Duplicate import removed
import warnings
from datetime import timedelta # Added import for timedelta
import datetime as dt_module # Added for revision date

# --- Inherit Base Settings ---
# Attempt to import base settings; handle potential import errors gracefully.
try:
    from .base import * # noqa: F403 (Ignore Flake8 'star import' warning)
except ImportError as e:
    print(f"ERROR: Could not import base settings (.base): {e}", file=sys.stderr)
    sys.exit(f"Base settings import failed. Ensure 'base.py' exists and is configured.")

# --- Core Development Settings ---

# DEVELOPMENT WARNING: Enables detailed error pages. NEVER True in production.
DEBUG = True

# Allow requests only from local machine.
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# --- Security Settings Adjustments for LOCAL HTTP Development ---
# These settings are intentionally relaxed ONLY to allow local testing over HTTP
# without requiring a complex local HTTPS setup.
# They MUST be reverted to secure defaults (True/enabled) in staging/production.

# Disable HTTPS enforcement (local dev server typically runs over HTTP)
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Disable HSTS (HTTP Strict Transport Security) for local development
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

warnings.warn(
    "DEVELOPMENT SETTINGS: HTTPS/HSTS/Secure Cookies are DISABLED for local HTTP development. "
    "Ensure these are ENABLED in staging/production."
)

# --- Database ---
# Development often uses SQLite or a local PostgreSQL instance.
# Ensure the DATABASES setting inherited from base.py is appropriate for dev,
# or override it here if needed (e.g., switch to SQLite for simplicity).
# Example override (uncomment and configure if needed):
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3', # noqa: F405 (BASE_DIR likely from base.py)
#     }
# }

# --- Password Hashers ---
# Keep the strong password hashers defined in base.py.
# Avoid weaker hashers like MD5 even in development for consistency and security hygiene.
# Example of what NOT to do:
# PASSWORD_HASHERS = [ 'django.contrib.auth.hashers.MD5PasswordHasher', ] # NEVER USE MD5!

# --- Static & Media Files ---
# Settings for staticfiles (like Whitenoise) might differ in development.
# Ensure STATIC_URL, STATIC_ROOT, MEDIA_URL, MEDIA_ROOT inherited from base.py
# are suitable, or override if necessary (e.g., no STATIC_ROOT needed if not collecting).

# --- Caching ---
# Use a simple local memory cache for speed during development.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'mymarketplace-dev-cache',  # Unique identifier for this project's dev cache
    }
}
warnings.warn("DEVELOPMENT SETTINGS: Using local memory cache (LocMemCache).")


# --- Logging Configuration ---
# Customize logging for better development visibility.
# Assumes LOGGING dictionary is defined in base.py.
try:
    # Ensure LOGGING dictionary exists (create if not, though it should come from base)
    if 'LOGGING' not in locals() or not isinstance(LOGGING, dict): # noqa: F405
        LOGGING = { # noqa: F405
             "version": 1,
             "disable_existing_loggers": False,
        }

    # Ensure formatters and handlers are defined before referencing in loggers
    if 'formatters' not in LOGGING: LOGGING['formatters'] = {} # noqa: F405
    if 'simple' not in LOGGING['formatters']: # noqa: F405
        LOGGING['formatters']['simple'] = { # noqa: F405
             "format": "{levelname} {name}:{lineno} {message}",
             "style": "{",
        }
    if 'handlers' not in LOGGING: LOGGING['handlers'] = {} # noqa: F405
    if 'console' not in LOGGING['handlers']: # noqa: F405
         LOGGING['handlers']['console'] = { # noqa: F405
             "class": "logging.StreamHandler",
             "formatter": "simple",
             # "level": "DEBUG", # Will be set below
         }

    # >>> FIX v1.0.2: Ensure console handler level is DEBUG <<<
    if 'console' in LOGGING['handlers']: # noqa: F405
        LOGGING['handlers']['console']['formatter'] = 'simple' # noqa: F405
        LOGGING['handlers']['console']['level'] = 'DEBUG' # <<< EXPLICITLY SET LEVEL
        # >>> END FIX v1.0.2 <<<
    else:
         # This case should ideally not happen if base.py defines a console handler
         warnings.warn("Could not find 'console' handler in LOGGING dict to set level and formatter.")


    # Ensure loggers dict exists
    if 'loggers' not in LOGGING: LOGGING['loggers'] = {} # noqa: F405

    # Increase verbosity for Django (optional, can keep INFO if desired)
    if 'django' not in LOGGING['loggers']: LOGGING['loggers']['django'] = {} # noqa: F405
    LOGGING['loggers']['django']['level'] = 'DEBUG' # noqa: F405
    # Ensure handler is assigned if logger exists but handler doesn't
    if 'handlers' not in LOGGING['loggers']['django']: LOGGING['loggers']['django']['handlers'] = ['console'] # noqa: F405


    # FIX v1.0.1: Explicitly configure 'store.services' logger for DEBUG output to console
    if 'store.services' not in LOGGING['loggers']: LOGGING['loggers']['store.services'] = {} # noqa: F405
    LOGGING['loggers']['store.services']['level'] = 'DEBUG' # noqa: F405
    LOGGING['loggers']['store.services']['handlers'] = ['console'] # noqa: F405
    LOGGING['loggers']['store.services']['propagate'] = False # Prevent duplicate logs if root is also configured

    # Optional: Configure root logger if needed, but be cautious not to make it too noisy
    # if '' not in LOGGING['loggers']: LOGGING['loggers'][''] = {}
    # LOGGING['loggers']['']['level'] = 'INFO' # Or DEBUG if necessary
    # LOGGING['loggers']['']['handlers'] = ['console']

    warnings.warn("DEVELOPMENT SETTINGS: Log levels potentially set to DEBUG. Console formatter set to 'simple'. Console handler level explicitly set to DEBUG.") # Adjusted warning
except KeyError as e:
    warnings.warn(f"Could not configure development logging overrides. Missing key in LOGGING dict from base.py: {e}")
except NameError:
    warnings.warn("Could not configure development logging overrides. 'LOGGING' dictionary not found (expected from base.py).")


# --- Django Debug Toolbar Configuration ---
# Provides valuable debugging information in the browser.
# Check if INSTALLED_APPS and MIDDLEWARE are available from base settings
DEBUG_TOOLBAR_ENABLED = False
if 'INSTALLED_APPS' in locals() and 'MIDDLEWARE' in locals(): # noqa: F405 (INSTALLED_APPS/MIDDLEWARE from base.py)
    try:
        import debug_toolbar # noqa: F401 (check import)

        # Add debug_toolbar to installed apps if not already present
        if 'debug_toolbar' not in INSTALLED_APPS: # noqa: F405
            INSTALLED_APPS.append('debug_toolbar') # noqa: F405

        # Add Debug Toolbar middleware. Insert *after* security/encoding middleware
        # but *before* middleware that might modify the response significantly.
        # CommonMiddleware or SessionMiddleware are typical insertion points.
        # This approach is more robust than using a fixed index.
        try:
            # Attempt to insert after GZipMiddleware if it exists
            gzip_index = MIDDLEWARE.index('django.middleware.gzip.GZipMiddleware') # noqa: F405
            if 'debug_toolbar.middleware.DebugToolbarMiddleware' not in MIDDLEWARE: # noqa: F405
                MIDDLEWARE.insert(gzip_index + 1, 'debug_toolbar.middleware.DebugToolbarMiddleware') # noqa: F405
        except ValueError:
            try:
                # Fallback: Attempt to insert after CommonMiddleware
                common_index = MIDDLEWARE.index('django.middleware.common.CommonMiddleware') # noqa: F405
                if 'debug_toolbar.middleware.DebugToolbarMiddleware' not in MIDDLEWARE: # noqa: F405
                    MIDDLEWARE.insert(common_index + 1, 'debug_toolbar.middleware.DebugToolbarMiddleware') # noqa: F405
            except ValueError:
                # Fallback: Add near the beginning if common targets aren't found (less ideal)
                if 'debug_toolbar.middleware.DebugToolbarMiddleware' not in MIDDLEWARE: # noqa: F405
                    warnings.warn("Could not find standard middleware (Gzip, Common) to position Debug Toolbar. Inserting early.")
                    MIDDLEWARE.insert(2, 'debug_toolbar.middleware.DebugToolbarMiddleware') # noqa: F405

        INTERNAL_IPS = ['127.0.0.1']  # IPs allowed to see the toolbar
        DEBUG_TOOLBAR_ENABLED = True
        warnings.warn("DEVELOPMENT SETTINGS: Django Debug Toolbar enabled and configured.")

    except ImportError:
        warnings.warn("Django Debug Toolbar not installed. Skipping configuration.")
    except NameError:
        warnings.warn("Could not configure Django Debug Toolbar. 'INSTALLED_APPS' or 'MIDDLEWARE' not found (expected from base.py).")
else:
    warnings.warn("Could not configure Django Debug Toolbar. 'INSTALLED_APPS' or 'MIDDLEWARE' not found (expected from base.py).")


# --- Django REST Framework (DRF) Development Settings ---
# Assumes REST_FRAMEWORK dictionary is defined in base.py
if 'rest_framework' in INSTALLED_APPS and 'REST_FRAMEWORK' in locals(): # noqa: F405
    try:
        # Ensure Browsable API is available for easy manual testing via browser
        if 'DEFAULT_RENDERER_CLASSES' in REST_FRAMEWORK: # noqa: F405
            renderers = list(REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']) # noqa: F405
            if 'rest_framework.renderers.BrowsableAPIRenderer' not in renderers:
                renderers.append('rest_framework.renderers.BrowsableAPIRenderer')
                REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = tuple(renderers) # noqa: F405
                warnings.warn("DEVELOPMENT SETTINGS: DRF BrowsableAPIRenderer enabled.")
        else:
            # If no renderers defined, add Browsable API as default (alongside JSON)
             REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = ( # noqa: F405
                 'rest_framework.renderers.JSONRenderer',
                 'rest_framework.renderers.BrowsableAPIRenderer',
             )
             warnings.warn("DEVELOPMENT SETTINGS: DRF DEFAULT_RENDERER_CLASSES not found in base, setting JSONRenderer and BrowsableAPIRenderer.")

    except NameError:
        warnings.warn("Could not configure DRF development settings. 'REST_FRAMEWORK' not found (expected from base.py).")
    except KeyError as e:
        warnings.warn(f"Could not configure DRF development settings. Missing key in REST_FRAMEWORK dict: {e}")


# --- Celery Development Settings (Optional) ---
# Uncomment to run Celery tasks synchronously in development for easier debugging.
# CELERY_TASK_ALWAYS_EAGER = True
# CELERY_TASK_EAGER_PROPAGATES = True # Propagate exceptions from eager tasks

# if 'CELERY_TASK_ALWAYS_EAGER' in locals() and CELERY_TASK_ALWAYS_EAGER:
#     warnings.warn(
#         "DEVELOPMENT SETTINGS: Celery tasks running synchronously "
#         "(CELERY_TASK_ALWAYS_EAGER=True). Disable for async testing."
#     )

# --- Django Axes (Brute Force Protection) Development Settings ---
# Assumes Axes settings (AXES_FAILURE_LIMIT, AXES_COOLOFF_TIME) are defined in base.py
# Relax limits slightly for development testing to avoid frequent lockouts,
# while still logging failed attempts.
try:
    AXES_FAILURE_LIMIT = 50  # Increased attempts allowed
    AXES_COOLOFF_TIME = timedelta(minutes=2)  # Shorter lockout period
    # Check if defaults exist before warning about relaxation
    # Requires defining base defaults (e.g., AXES_BASE_FAILURE_LIMIT in base.py)
    # Or, just warn unconditionally that relaxed values are in use:
    warnings.warn(
        f"DEVELOPMENT SETTINGS: Axes brute-force protection limits relaxed "
        f"(Limit: {AXES_FAILURE_LIMIT}, Cooloff: {AXES_COOLOFF_TIME}). "
        f"Ensure stricter limits in staging/production."
    )
except NameError:
    warnings.warn("Could not configure Axes development settings. Base Axes settings not found (expected from base.py).")

# --- WebAuthn Development Overrides ---
# REASON: Set explicit RP ID and Origin for local HTTP development environment.
# These values MUST match how your frontend is accessed locally during development.
# Consider using environment variables for more flexibility.
WEBAUTHN_RP_ID = os.environ.get('DEV_WEBAUTHN_RP_ID', 'localhost')

# IMPORTANT: Adjust port (e.g., 3000, 5173, 8080) if your frontend runs on a different port locally.
# Use an environment variable or update the default here.
_dev_frontend_origin_default = 'http://localhost:3000'
WEBAUTHN_EXPECTED_ORIGIN = os.environ.get('DEV_FRONTEND_ORIGIN', _dev_frontend_origin_default)

warnings.warn(
    f"DEVELOPMENT SETTINGS: WebAuthn configured for development. "
    f"RP_ID='{WEBAUTHN_RP_ID}', EXPECTED_ORIGIN='{WEBAUTHN_EXPECTED_ORIGIN}'. "
    f"Ensure these match your local frontend setup (hostname and port)."
)



# --- Final Startup Warning ---
# Ensure this prominent warning is always displayed when using development settings.
print("*" * 60, file=sys.stderr)
print("*" + " " * 58 + "*", file=sys.stderr)
print("**** CAUTION: RUNNING IN DEVELOPMENT MODE (dev.py) ****", file=sys.stderr)
print("**** DEBUG=True. Security settings relaxed for LOCAL  ****", file=sys.stderr)
print("**** HTTP testing ONLY. Review warnings above.      ****", file=sys.stderr)
print("**** ****", file=sys.stderr)
print("**** DO NOT use this configuration for staging,      ****", file=sys.stderr)
print("**** production, or any environment with real data.  ****", file=sys.stderr)
print("*" + " " * 58 + "*", file=sys.stderr)
print("*" * 60, file=sys.stderr)

# --- END OF backend/mymarketplace/settings/dev.py ---