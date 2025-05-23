# backend/mymarketplace/settings/base.py
# <<< Revision 6.9.5: Correct AUTH_PASSWORD_VALIDATORS by removing invalid Axes entry >>>
# Revision Notes:
# - v6.9.5 (2025-05-22):
#   - FIXED: Removed {'NAME': 'axes.validation.AxesPasswordValidator'} from AUTH_PASSWORD_VALIDATORS.
#     Django-axes (v8.0.0 as per pytest output) does not provide a password validator for this setting.
#     Its functionality is primarily through middleware for access attempt tracking. This change
#     resolves the ImproperlyConfigured error: "The module in NAME could not be imported:
#     axes.validation.AxesPasswordValidator".
# - v6.9.4 (2025-05-19):
#   - ANALYSIS: Re-confirmed AUTH_PASSWORD_VALIDATORS entry 'axes.validation.AxesPasswordValidator'
#     is correct for django-axes v7.0.2. The persistent ModuleNotFoundError for 'axes.validation'
#     strongly indicates an external environment or django-axes installation issue. This settings
#     file cannot resolve that if the path string is already correct.
#     Next focus should be ensuring django-axes is correctly installed in the environment.
#     Subsequently, backend/store/models.py for PGP validation errors.
# - v6.9.3 (2025-05-19):
#   - ANALYSIS: Confirmed AUTH_PASSWORD_VALIDATORS entry 'axes.validation.AxesPasswordValidator'
#     is correct for django-axes v7.0.2 as reported by pytest. The ModuleNotFoundError
#     for 'axes.validation' likely indicates an environment or installation issue with
#     the django-axes package itself, not an error in this settings file line.
#   - CLARIFICATION: Ensured session-related settings (SESSION_COOKIE_AGE,
#     DEFAULT_SESSION_COOKIE_AGE_SECONDS, OWNER_SESSION_COOKIE_AGE_SECONDS) are clearly
#     defined and sourced from environment variables as intended by previous revisions.
#     No functional change, primarily for readability and confirming existing logic.
# - v6.9.2 (2025-05-19):
#   - FIXED: Explicitly defined OWNER_SESSION_COOKIE_AGE_SECONDS = env.int('OWNER_SESSION_COOKIE_AGE_SECONDS')
#     to make it available directly via django.conf.settings. Addresses AttributeError
#     for 'OWNER_SESSION_COOKIE_AGE_SECONDS' in canary view test.
# - v6.9.1 (2025-05-19):
#   - FIXED: Changed AUTH_PASSWORD_VALIDATORS entry from 'axes.validators.AxesPasswordValidator'
#     to 'axes.validation.AxesPasswordValidator' to match django-axes v7.x path.
#     Addresses ImproperlyConfigured("The module in NAME could not be imported: axes.validators.AxesPasswordValidator...").
#   - FIXED: Explicitly defined OWNER_SESSION_COOKIE_AGE_SECONDS = env.int('OWNER_SESSION_COOKIE_AGE_SECONDS')
#     to make it available directly via django.conf.settings. Addresses AttributeError
#     for 'OWNER_SESSION_COOKIE_AGE_SECONDS'.
# - v6.9 (2025-05-19):
#   - FIXED: Added `DEFAULT_SESSION_COOKIE_AGE_SECONDS = SESSION_COOKIE_AGE` to ensure
#     this setting is available directly via `django.conf.settings`. Addresses AttributeError
#     in tests trying to access `settings.DEFAULT_SESSION_COOKIE_AGE_SECONDS`.
# - (Older revisions omitted for brevity)

"""
Shadow Market - Enterprise-Grade Base Settings (Hardened Configuration)

- Core Django settings.
- STRICT dependency on Vault/secure environment variables for secrets.
- Emphasis on security headers, strict policies, structured logging.
- Mandatory PGP for critical user functions (enforced in views/permissions).
- Email functionality is explicitly REMOVED.
- Forum functionality ENABLED.
- Base configuration for supported cryptocurrencies (XMR, BTC, ETH).
- Includes Ledger app configuration.
- Includes Withdraw app configuration.
"""

# --- Standard Library Imports ---
import os
import sys
from pathlib import Path
from datetime import timedelta
from decimal import Decimal # For marketplace settings defaults
import logging # Added for Sentry logging config

# --- Third-Party Imports ---
import environ # Use django-environ for robust environment variable parsing & default values

# --- Initialize django-environ ---
# <<< BEST PRACTICE: Centralize environment variable handling >>>
env = environ.Env(
    # Set casting and default values
    DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, None), # Default to None, MUST be set via Vault/Env
    DJANGO_ALLOWED_HOSTS=(list, ['127.0.0.1', 'localhost']), # Dev default, MUST be overridden
    SITE_ID=(int, 1),
    DATABASE_URL=(str, None), # Default to None, MUST be set via Vault/Env
    REDIS_URL=(str, 'redis://127.0.0.1:6379/1'), # Cache DB 1, Password should be in URL
    CELERY_BROKER_URL=(str, 'redis://127.0.0.1:6379/0'), # Celery DB 0, Password should be in URL
    SECURE_SSL_REDIRECT=(bool, True),
    SESSION_COOKIE_SECURE=(bool, True),
    CSRF_COOKIE_SECURE=(bool, True),
    SESSION_COOKIE_HTTPONLY=(bool, True),
    SESSION_COOKIE_SAMESITE=(str, 'Lax'), # Consider 'Strict' for better CSRF protection if feasible
    CSRF_COOKIE_SAMESITE=(str, 'Lax'),   # Consider 'Strict' for better CSRF protection if feasible
    SECURE_HSTS_SECONDS=(int, 63072000), # 2 years
    SECURE_HSTS_INCLUDE_SUBDOMAINS=(bool, True),
    SECURE_HSTS_PRELOAD=(bool, True),
    SECURE_CONTENT_TYPE_NOSNIFF=(bool, True),
    SECURE_BROWSER_XSS_FILTER=(bool, True), # Deprecated, but set for defense-in-depth (CSP is primary)
    SECURE_REFERRER_POLICY=(str, 'strict-origin-when-cross-origin'),
    MAX_FILE_UPLOAD_SIZE_MB=(int, 5), # Max upload size in Megabytes
    AXES_ENABLED=(bool, True),
    AXES_FAILURE_LIMIT=(int, 5), # Base default, overridden in dev.py
    AXES_COOLOFF_MINUTES=(int, 30), # Base default, overridden in dev.py
    AXES_PROXY_COUNT=(int, 0), # Added AXES_PROXY_COUNT default
    SENTRY_DSN=(str, None), # Default to None, enable via Env/Vault
    SENTRY_TRACES_SAMPLE_RATE=(float, 0.05),
    GPG_HOME=(str, None), # Default to None, MUST be set
    # --- Crypto Node Settings (MUST be set via Env/Vault) ---
    MONERO_RPC_URL=(str, None), MONERO_RPC_USER=(str, None), MONERO_RPC_PASSWORD=(str, None),
    MONERO_WALLET_RPC_URL=(str, None), MONERO_CONFIRMATIONS_NEEDED=(int, 10),
    BITCOIN_RPC_URL=(str, None), BITCOIN_RPC_USER=(str, None), BITCOIN_RPC_PASSWORD=(str, None),
    BITCOIN_NETWORK=(str, 'mainnet'), BITCOIN_CONFIRMATIONS_NEEDED=(int, 3),
    ETHEREUM_NODE_URL=(str, None), ETHEREUM_CHAIN_ID=(int, 1), ETHEREUM_CONFIRMATIONS_NEEDED=(int, 12),
    GNOSIS_SAFE_FACTORY_ADDRESS=(str, None), GNOSIS_SAFE_SINGLETON_ADDRESS=(str, None),
    MARKET_ETH_HOT_WALLET_ADDRESS=(str, None), # Read-only address for balance checks etc.
    # --- Marketplace Parameters ---
    SITE_OWNER_USERNAME=(str, 'SiteOwner'),
    MARKET_USER_USERNAME=(str, 'MarketAccount'), # Default username for the market fee account
    PAYMENT_WAIT_HOURS=(int, 4),
    VENDOR_BOND_XMR=(Decimal, '5.0'), VENDOR_BOND_BTC=(Decimal, '0.05'), VENDOR_BOND_ETH=(Decimal, '1.0'),
    MARKET_FEE_PERCENTAGE_XMR=(Decimal, '4.0'), MARKET_FEE_PERCENTAGE_BTC=(Decimal, '4.0'), MARKET_FEE_PERCENTAGE_ETH=(Decimal, '4.5'),
    ORDER_AUTO_FINALIZE_DAYS=(int, 14), DISPUTE_WINDOW_DAYS=(int, 7), DEADMAN_SWITCH_THRESHOLD_DAYS=(int, 30),
    # --- Session/Auth Timeouts ---
    DEFAULT_SESSION_COOKIE_AGE_SECONDS=(int, 900), # 15 minutes, used for SESSION_COOKIE_AGE and custom logic
    OWNER_SESSION_COOKIE_AGE_SECONDS=(int, 3600), # 1 hour, used for custom logic
    DEFAULT_PGP_AUTH_SESSION_TIMEOUT_MINUTES=(int, 15),
    OWNER_PGP_AUTH_SESSION_TIMEOUT_MINUTES=(int, 60),
    # --- DRF Defaults ---
    DRF_PAGE_SIZE=(int, 20),
    DRF_MAX_PAGE_SIZE=(int, 100),
    DRF_ANON_THROTTLE_RATE=(str, '100/hour'),
    DRF_USER_THROTTLE_RATE=(str, '1000/hour'),
    # --- Vault Configuration (MUST be set if using Vault) ---
    VAULT_ADDR=(str, None),
    VAULT_TOKEN=(str, None), # For token auth (dev/testing primarily)
    VAULT_APPROLE_ROLE_ID=(str, None), # For AppRole auth (recommended for services)
    VAULT_APPROLE_SECRET_ID=(str, None), # For AppRole auth
    VAULT_KV_MOUNT_POINT=(str, 'secret'), # Default KV v2 mount point
    VAULT_SECRET_BASE_PATH=(str, 'shadowmarket'), # Base path within KV mount for this app's secrets
    # --- WebAuthn Defaults (from previous update) ---
    WEBAUTHN_RP_ID=(str, None),
    WEBAUTHN_EXPECTED_ORIGIN=(str, None),
    WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS=(int, 300),
)

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Load .env file ONLY if not in production and file exists ---
ENV_FILE_PATH = BASE_DIR / '.env'
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development')
TESTING = 'test' in sys.argv # Check if running under pytest

if DJANGO_ENV != 'production' and ENV_FILE_PATH.exists():
    print(f"INFO: Reading environment variables from: {ENV_FILE_PATH}", file=sys.stderr)
    environ.Env.read_env(str(ENV_FILE_PATH))
else:
    print(f"INFO: Not loading .env file (DJANGO_ENV='{DJANGO_ENV}', TESTING='{TESTING}', File Exists: {ENV_FILE_PATH.exists()})", file=sys.stderr)

# --- Vault Integration ---
_vault_client = None
def get_vault_client():
    global _vault_client
    if _vault_client: return _vault_client
    VAULT_ADDR = env('VAULT_ADDR')
    if not VAULT_ADDR: return None # Silently return None if Vault is not configured

    try:
        import hvac
        client = hvac.Client(url=VAULT_ADDR)
        VAULT_APPROLE_ROLE_ID = env('VAULT_APPROLE_ROLE_ID')
        VAULT_APPROLE_SECRET_ID = env('VAULT_APPROLE_SECRET_ID')
        VAULT_TOKEN = env('VAULT_TOKEN')
        auth_method_used = None
        if VAULT_APPROLE_ROLE_ID and VAULT_APPROLE_SECRET_ID:
            auth_method_used = "AppRole"
            client.auth.approle.login(role_id=VAULT_APPROLE_ROLE_ID, secret_id=VAULT_APPROLE_SECRET_ID)
        elif VAULT_TOKEN:
            auth_method_used = "Token"
            client.token = VAULT_TOKEN
        else:
            # Log as warning, not error, to allow app to run without full Vault auth if some secrets are optional
            print("WARNING: Vault address configured, but no complete authentication method (AppRole/Token) provided.", file=sys.stderr)
            return None
        if client.is_authenticated():
            print(f"INFO: Vault client authenticated successfully using {auth_method_used}.", file=sys.stderr)
            _vault_client = client
            return _vault_client
        else:
            print(f"ERROR: Vault client authentication failed using {auth_method_used}. Client token: {client.token[:10]}... (if set)", file=sys.stderr)
            return None
    except ImportError:
        print("ERROR: HVAC library not installed. Cannot use Vault. `pip install hvac`", file=sys.stderr)
        return None
    except Exception as e: # Catch more specific hvac.exceptions if needed
        print(f"ERROR: Failed to initialize or authenticate Vault client: {e}", file=sys.stderr)
        return None

def get_secret_from_vault(secret_name: str, key: str, default=None, raise_error_if_missing=False):
    client = get_vault_client()
    if not client:
        if raise_error_if_missing:
            raise RuntimeError(f"Vault client unavailable. Cannot fetch mandatory secret: {secret_name}/{key}")
        return default
    VAULT_KV_MOUNT_POINT = env('VAULT_KV_MOUNT_POINT')
    VAULT_SECRET_BASE_PATH = env('VAULT_SECRET_BASE_PATH')
    full_secret_path = f"{VAULT_SECRET_BASE_PATH}/{secret_name}"
    try:
        response = client.secrets.kv.v2.read_secret_version(path=full_secret_path, mount_point=VAULT_KV_MOUNT_POINT)
        secret_data = response.get('data', {}).get('data', {}) # KV V2 stores data under 'data': {'data': {...}}
        value = secret_data.get(key)
        if value is not None:
            return value
        else:
            msg = f"Key '{key}' not found in Vault secret '{full_secret_path}'."
            print(f"WARNING: {msg}", file=sys.stderr)
            if raise_error_if_missing: raise KeyError(msg)
            return default
    except Exception as e: # Consider catching specific hvac.exceptions.VaultError variations
        msg = f"Failed to fetch '{key}' from Vault secret '{full_secret_path}': {type(e).__name__}: {e}"
        print(f"ERROR: {msg}", file=sys.stderr)
        if raise_error_if_missing: raise RuntimeError(msg) from e
        return default

# --- Core Settings ---
SECRET_KEY = env('DJANGO_SECRET_KEY') or get_secret_from_vault('django', 'secret_key', raise_error_if_missing=True)
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS') # Fetches from env var or uses default from Env() init
if DJANGO_ENV == 'production' and ('localhost' in ALLOWED_HOSTS or '127.0.0.1' in ALLOWED_HOSTS or not ALLOWED_HOSTS):
    print("CRITICAL ERROR: DJANGO_ALLOWED_HOSTS is misconfigured for production!", file=sys.stderr)
    print("                               It should ONLY contain the production domain(s) (e.g., .onion).", file=sys.stderr)
    sys.exit(1) # Exit if critical misconfiguration in production
SITE_ID = env.int('SITE_ID')

# --- Application Definition ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt', # For JWT authentication if used
    'django_celery_results',    # For storing Celery task results
    'axes',                     # Django-axes for login attempt tracking
    'django_otp',               # Django OTP for two-factor authentication
    'captcha',                  # Django-simple-captcha
    'django_filters',           # For filtering querysets in DRF
    # Local applications (using AppConfig for clarity and explicitness)
    'backend.store.apps.StoreConfig',
    'backend.adminpanel.apps.AdminpanelConfig',
    'backend.ledger.apps.LedgerConfig',
    'backend.notifications.apps.NotificationsConfig',
    'backend.forum.apps.ForumConfig',
    'backend.withdraw.apps.WithdrawConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'backend.middleware.SecurityHeadersMiddleware.SecurityHeadersMiddleware', # Custom security headers
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware', # Must be after AuthenticationMiddleware
    'axes.middleware.AxesMiddleware',      # Django-axes middleware, tracks login attempts
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Custom middleware (ensure correct order and functionality)
    'backend.middleware.OwnerSessionMiddleware.OwnerSessionMiddleware',
    'backend.middleware.RequestValidationMiddleware.RequestValidationMiddleware',
    'backend.middleware.RateLimitMiddleware.ConfigurableRateLimitMiddleware',
    'backend.middleware.AnomalyDetectionMiddleware.AnomalyDetectionMiddleware',
    'backend.middleware.ErrorHandlingMiddleware.ErrorHandlingMiddleware', # Usually last or near last
]

ROOT_URLCONF = 'backend.mymarketplace.urls' # Points to the root URL configuration

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Project-level templates directory
        'APP_DIRS': True, # Allow Django to find templates within app directories
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request', # Adds the request object to template context
                'django.contrib.auth.context_processors.auth',   # Adds user and perms objects
                'django.contrib.messages.context_processors.messages', # Adds messages framework context
            ],
            'builtins': [ # Add custom template tags/filters here if needed
                # e.g., 'myapp.templatetags.custom_tags'
            ],
            'debug': DEBUG, # Enable template debugging if Django DEBUG is True
        },
    },
]

WSGI_APPLICATION = 'backend.mymarketplace.wsgi.application' # Path to WSGI application

# --- Database ---
# https://docs.djangoproject.com/en/stable/ref/settings/#databases
print(f"DEBUG: Attempting to configure DATABASES using env.db('DATABASE_URL')...", file=sys.stderr)
DATABASES = {'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db_dev.sqlite3"}')}
print(f"DEBUG: DATABASES configured as: {DATABASES['default'].get('ENGINE', 'N/A')} | {DATABASES['default'].get('NAME', 'N/A')}", file=sys.stderr)
# Check for empty or missing password which might be an issue for non-SQLite DBs
if DATABASES['default'].get('ENGINE') != 'django.db.backends.sqlite3' and \
   ('PASSWORD' not in DATABASES['default'] or not DATABASES['default'].get('PASSWORD')):
    print("WARNING: Database password appears empty or not set in parsed config for a non-SQLite database.", file=sys.stderr)
DATABASES['default']['CONN_MAX_AGE'] = env.int('DATABASE_CONN_MAX_AGE', default=600) # Persistent connections

# --- Password validation ---
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 14}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    # Removed incorrect entry: {'NAME': 'axes.validation.AxesPasswordValidator'},
]
# Use strong password hashers, Argon2 is preferred.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# --- Internationalization ---
# https://docs.djangoproject.com/en/stable/topics/i18n/
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC' # Recommended to use UTC for backend storage
USE_I18N = False # Set to True if internationalization is needed
USE_TZ = True   # Store datetimes as timezone-aware in UTC

# --- Static files & Media files ---
# https://docs.djangoproject.com/en/stable/howto/static-files/
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles' # For collectstatic in production
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'       # User-uploaded files
FILE_UPLOAD_MAX_MEMORY_SIZE = 2621440 # 2.5MB, Django's default before streaming to temp file
MAX_UPLOAD_SIZE = env.int('MAX_FILE_UPLOAD_SIZE_MB') * 1024 * 1024 # Custom max upload size

# --- Default primary key ---
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField' # Modern default

# --- Security Settings ---
# These are sourced from environment variables by django-environ, allowing easy override.
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT')
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE')
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE')
SESSION_COOKIE_HTTPONLY = env.bool('SESSION_COOKIE_HTTPONLY')
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE') # 'Lax' or 'Strict'
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE')       # 'Lax' or 'Strict'
X_FRAME_OPTIONS = 'DENY' # Prevent clickjacking
SECURE_CONTENT_TYPE_NOSNIFF = env.bool('SECURE_CONTENT_TYPE_NOSNIFF')
SECURE_BROWSER_XSS_FILTER = env.bool('SECURE_BROWSER_XSS_FILTER') # Deprecated but adds minor defense layer
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS')
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD')
SECURE_REFERRER_POLICY = env('SECURE_REFERRER_POLICY') # e.g., 'strict-origin-when-cross-origin'

# --- Session Settings ---
# Django's built-in session age, sourced from the env var 'DEFAULT_SESSION_COOKIE_AGE_SECONDS'.
SESSION_COOKIE_AGE = env.int('DEFAULT_SESSION_COOKIE_AGE_SECONDS')

# Custom setting variables for OwnerSessionMiddleware and potentially other logic.
# These are distinct from Django's SESSION_COOKIE_AGE but are also sourced from env vars.
# Ensured these are directly available via django.conf.settings by defining them here after env.int() call.
DEFAULT_SESSION_COOKIE_AGE_SECONDS = env.int('DEFAULT_SESSION_COOKIE_AGE_SECONDS')
OWNER_SESSION_COOKIE_AGE_SECONDS = env.int('OWNER_SESSION_COOKIE_AGE_SECONDS')

SESSION_SAVE_EVERY_REQUEST = True # Save session on every request if modified
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db' # DB-backed sessions with caching

# --- Authentication Settings ---
AUTH_USER_MODEL = 'store.User' # Custom user model
LOGIN_URL = '/api/store/auth/login/init/' # For views requiring login
LOGOUT_URL = '/api/store/auth/logout/'

# --- Django-Axes Configuration ---
# https://django-axes.readthedocs.io/en/latest/configuration.html
AXES_ENABLED = env.bool('AXES_ENABLED')
AXES_FAILURE_LIMIT = env.int('AXES_FAILURE_LIMIT') # Number of failed attempts before lockout
AXES_COOLOFF_TIME = timedelta(minutes=env.int('AXES_COOLOFF_MINUTES')) # Lockout duration
AXES_LOCKOUT_TEMPLATE = 'registration/lockout.html' # Ensure this template exists if lockouts are user-facing
AXES_USERNAME_FORM_FIELD = 'username' # Name of username field in login forms
AXES_PASSWORD_FORM_FIELD = 'password' # Name of password field in login forms (# nosec B105 - Field name, not credential)
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True # Lock out based on user and IP
AXES_ONLY_USER_FAILURES = False # Consider IP failures even if username is incorrect
AXES_RESET_ON_SUCCESS = True # Reset failure count on successful login
AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler' # Use Django's cache for tracking failures
AXES_CACHE = 'default' # Which cache alias to use
AXES_PROXY_COUNT = env.int('AXES_PROXY_COUNT', default=0) # If behind proxies, set to number of proxies

# --- Django-OTP Configuration ---
# https://django-otp-official.readthedocs.io/en/latest/settings.html
OTP_LOGIN_URL = LOGIN_URL # Or a specific OTP entry URL if different
OTP_ADMIN_ENFORCE_OTP = True # Recommended to enforce OTP for admin interface

# --- Celery Configuration ---
# https://docs.celeryq.dev/en/stable/userguide/configuration.html
CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = 'django-db' # For storing task results in the database using django-celery-results
CELERY_ACCEPT_CONTENT = ['json']      # Only accept JSON serialized tasks
CELERY_TASK_SERIALIZER = 'json'       # Serialize tasks as JSON
CELERY_RESULT_SERIALIZER = 'json'   # Serialize results as JSON
CELERY_TIMEZONE = TIME_ZONE         # Use Django's timezone
CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': env.int('CELERY_VISIBILITY_TIMEOUT', default=3600)} # 1 hour, for long tasks

# --- Logging Configuration ---
# https://docs.djangoproject.com/en/stable/topics/logging/
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True) # Ensure log directory exists
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.json.JsonFormatter', # For structured logging
            'format': '%(asctime)s %(levelname)s %(name)s %(module)s %(pathname)s:%(lineno)d %(message)s %(process)d %(thread)d',
        },
        'verbose': { 'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s' },
        'simple': { 'format': '%(levelname)s %(name)s %(message)s' },
    },
    'filters': {
        'require_debug_false': { '()': 'django.utils.log.RequireDebugFalse', },
        'require_debug_true': { '()': 'django.utils.log.RequireDebugTrue', },
        'exclude_sensitive': { # Custom filter to avoid logging sensitive keywords
            '()': 'django.utils.log.CallbackFilter',
            'callback': lambda record: not any(word in str(getattr(record, 'message', '') or getattr(record, 'msg', '')).lower() for word in [
                'password', 'secret', 'token', 'key', 'credit', 'card', 'cvv', 'private',
                'mnemonic', 'apikey', 'credential', 'bearer', 'authorization', 'sessionid', 'csrftoken',
                'xmr_rpc_password', 'btc_rpc_password' # Ensure all sensitive env var keys are listed here
            ]),
        }
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO', # More verbose for DEBUG, INFO for prod
            'filters': ['require_debug_true'] if DEBUG else ['require_debug_false', 'exclude_sensitive'],
            'class': 'logging.StreamHandler',
            'formatter': 'simple' if DEBUG else 'json', # Simple for dev, JSON for prod
        },
        'file_app': { # General application log
            'level': 'INFO',
            'filters': ['require_debug_false', 'exclude_sensitive'], # Prod only, filter sensitive
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'app.log',
            'maxBytes': 10 * 1024 * 1024, # 10 MB
            'backupCount': 5,
            'formatter': 'json', # Structured logging to file
        },
        'file_security': { # Dedicated security log
            'level': 'INFO',
            'filters': ['require_debug_false'], # Prod only; review sensitive filter needs for security logs
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'security.log',
            'maxBytes': 10 * 1024 * 1024, # 10 MB
            'backupCount': 5,
            'formatter': 'json',
        },
        'null': { 'class': 'logging.NullHandler', }, # To silence loggers if needed
    },
    'loggers': {
        'django': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'django.request': { 'handlers': ['file_app', 'file_security'], 'level': 'ERROR', 'propagate': False, }, # Log HTTP 5XX errors
        'django.security': { 'handlers': ['file_security'], 'level': 'WARNING', 'propagate': False, }, # Log security warnings (CSRF, SuspiciousOps)
        'axes': { 'handlers': ['console', 'file_security'], 'level': 'INFO', 'propagate': False, }, # Axes login attempts
        'hvac': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, }, # Vault client logs
        'gnupg': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, }, # GnuPG library logs
        'web3': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, }, # Web3 library logs
        'celery': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, }, # Celery logs
        # Application specific loggers - adjust handlers and levels as needed
        'mymarketplace': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': True, }, # Base for project
        'store': { 'handlers': [], 'level': 'INFO', 'propagate': True, }, # Specific app
        'adminpanel': { 'handlers': ['file_security'], 'level': 'INFO', 'propagate': True, },
        'ledger': { 'handlers': ['file_security'], 'level': 'INFO', 'propagate': True, },
        'notifications': { 'handlers': [], 'level': 'INFO', 'propagate': True, },
        'forum': { 'handlers': [], 'level': 'INFO', 'propagate': True, },
        'withdraw': { 'handlers': ['file_security'], 'level': 'INFO', 'propagate': True, },
        'store.services.pgp_service': { 'handlers': ['file_security'], 'level': 'INFO', 'propagate': True, },
        # Add other specific app/module loggers here
    },
    'root': { # Catch-all logger
        'handlers': ['console'] if DEBUG else ['file_app'],
        'level': 'INFO', # Root logger level
    },
}

# --- Sentry SDK (Error Tracking) ---
# https://docs.sentry.io/platforms/python/guides/django/
SENTRY_DSN = env('SENTRY_DSN') or get_secret_from_vault('sentry', 'dsn', default=None)
if SENTRY_DSN and DJANGO_ENV == 'production': # Only initialize in production if DSN is set
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        # Configure Sentry logging integration
        sentry_logging = LoggingIntegration(
            level=logging.INFO,        # Capture info and above as breadcrumbs
            event_level=logging.ERROR  # Send errors and above as events
        )
        # Define before_send hook for PII scrubbing if needed
        def before_send(event, hint):
            # Example: Modify event to scrub PII before sending to Sentry
            # if 'user' in event: event['user'] = {'id': event['user'].get('id')}
            return event
        SENTRY_RELEASE = os.getenv('SENTRY_RELEASE', None) # Set via CI/CD for release tracking
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging],
            traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.1), # Adjust sample rate as needed
            send_default_pii=False, # Must be False if PII is handled by before_send or you want to control it
            environment=DJANGO_ENV,
            release=SENTRY_RELEASE,
            before_send=before_send, # Hook for custom data scrubbing
        )
        print("INFO: Sentry SDK initialized for production.", file=sys.stderr)
    except ImportError:
        print("WARNING: Sentry DSN configured, but 'sentry-sdk' not installed. `pip install sentry-sdk`", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed to initialize Sentry SDK: {e}", file=sys.stderr)

# --- REST Framework ---
# https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework.authentication.SessionAuthentication',), # Session auth is default
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticatedOrReadOnly',), # Default permissions
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'] + (['rest_framework.renderers.BrowsableAPIRenderer'] if DEBUG else []),
    'DEFAULT_PARSER_CLASSES': ('rest_framework.parsers.JSONParser', 'rest_framework.parsers.FormParser', 'rest_framework.parsers.MultiPartParser',),
    'DEFAULT_THROTTLE_CLASSES': ('rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'),
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('DRF_ANON_THROTTLE_RATE', default='100/hour'),
        'user': env('DRF_USER_THROTTLE_RATE', default='1000/hour')
    },
    'EXCEPTION_HANDLER': 'backend.middleware.ErrorHandlingMiddleware.api_exception_handler', # Custom handler
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': env.int('DRF_PAGE_SIZE', default=20),
    'PAGE_SIZE_QUERY_PARAM': 'page_size', # Allow client to override page size via query param
    'MAX_PAGE_SIZE': env.int('DRF_MAX_PAGE_SIZE', default=100),
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.openapi.AutoSchema', # For OpenAPI schema generation
}

# --- GPG/PGP Settings ---
GPG_HOME = env('GPG_HOME') # MUST be set in environment
if not GPG_HOME:
    print("CRITICAL ERROR: GPG_HOME environment variable is not set.", file=sys.stderr)
    sys.exit(1) # Critical, PGP operations will fail
GPG_HOME_PATH = Path(GPG_HOME)
try:
    GPG_HOME_PATH.parent.mkdir(parents=True, exist_ok=True) # Ensure parent directory exists
    GPG_HOME_PATH.mkdir(mode=0o700, exist_ok=True) # Create GPG_HOME with 700 permissions if it doesn't exist
    # Ensure permissions are set correctly, especially if the directory pre-existed.
    if GPG_HOME_PATH.exists(): # This check is somewhat redundant if mkdir succeeded or exist_ok=True
        os.chmod(GPG_HOME_PATH, 0o700) # Explicitly set permissions
    print(f"INFO: Ensured GPG directory exists with 700 permissions: {GPG_HOME_PATH}", file=sys.stderr)
except OSError as e:
    # Log more specific error if possible (e.g., permission denied during creation/chmod)
    print(f"CRITICAL WARNING: Could not create or set permissions (700) for GPG directory {GPG_HOME_PATH}: {e}. PGP operations may fail.", file=sys.stderr)
except Exception as e: # Catch any other unexpected errors
    print(f"CRITICAL WARNING: Unexpected error ensuring GPG directory {GPG_HOME_PATH}: {e}", file=sys.stderr)


# --- Cryptocurrency Settings ---
SUPPORTED_CURRENCIES = ['XMR', 'BTC', 'ETH'] # Define what currencies are generally supported
MONERO_RPC_PASSWORD=env('MONERO_RPC_PASSWORD') or get_secret_from_vault('crypto', 'monero_rpc_password', default=None)
BITCOIN_RPC_PASSWORD=env('BITCOIN_RPC_PASSWORD') or get_secret_from_vault('crypto', 'bitcoin_rpc_password', default=None)
# Add other crypto specific settings as needed, e.g., ETH private key for market wallet if used directly

# --- Marketplace Specific Settings ---
SITE_OWNER_USERNAME = env('SITE_OWNER_USERNAME')
MARKET_USER_USERNAME = env('MARKET_USER_USERNAME')
# Other marketplace parameters (fees, timeouts, etc.) are primarily defined in env() defaults at the top

# --- WebAuthn (FIDO2) Settings ---
# https://django-webauthn.readthedocs.io/en/latest/settings.html
WEBAUTHN_RP_NAME = 'Shadow Market' # Display name for the Relying Party
WEBAUTHN_RP_ID = env('WEBAUTHN_RP_ID', default=None) # Relying Party ID (e.g., 'example.com') - MUST match domain
WEBAUTHN_EXPECTED_ORIGIN = env('WEBAUTHN_EXPECTED_ORIGIN', default=None) # Full origin (e.g., 'https://example.com')
WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS = env.int('WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS', default=300) # 5 minutes

# Production checks for WebAuthn settings
if DJANGO_ENV == 'production':
    if not WEBAUTHN_RP_ID:
        print("CRITICAL ERROR: WEBAUTHN_RP_ID setting is NOT configured for production!", file=sys.stderr)
        sys.exit(1)
    if not WEBAUTHN_EXPECTED_ORIGIN:
        print("CRITICAL ERROR: WEBAUTHN_EXPECTED_ORIGIN setting is NOT configured for production!", file=sys.stderr)
        sys.exit(1)
    if not WEBAUTHN_EXPECTED_ORIGIN.startswith('https://'): # Require HTTPS for origin in production
        print(f"CRITICAL WARNING: WEBAUTHN_EXPECTED_ORIGIN ('{WEBAUTHN_EXPECTED_ORIGIN}') must use HTTPS in production.", file=sys.stderr)
        # Consider sys.exit(1) if this is a strict requirement

# --- CAPTCHA Settings (django-simple-captcha) ---
# https://django-simple-captcha.readthedocs.io/en/latest/advanced.html
CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.math_challenge' # Default math challenge
CAPTCHA_TIMEOUT = 5  # Minutes until CAPTCHA expires
CAPTCHA_LENGTH = 6   # Number of chars in challenge

# --- Final Checks (Production Only) ---
if DJANGO_ENV == 'production':
    # Check for presence of critical cryptocurrency node URLs
    if not all([
        env('MONERO_RPC_URL'),
        env('MONERO_WALLET_RPC_URL'),
        env('BITCOIN_RPC_URL'),
        env('ETHEREUM_NODE_URL')
    ]):
        print("CRITICAL WARNING: One or more cryptocurrency node URLs are NOT configured for production!", file=sys.stderr)
    # Check for crypto RPC passwords
    if not MONERO_RPC_PASSWORD: print("CRITICAL WARNING: Monero RPC password not set for production!", file=sys.stderr)
    if not BITCOIN_RPC_PASSWORD: print("CRITICAL WARNING: Bitcoin RPC password not set for production!", file=sys.stderr)
    # Check Vault authentication if Vault address is provided
    if env('VAULT_ADDR') and not (env('VAULT_TOKEN') or (env('VAULT_APPROLE_ROLE_ID') and env('VAULT_APPROLE_SECRET_ID'))):
        print("CRITICAL WARNING: VAULT_ADDR is set, but no Vault authentication method provided/successful for production.", file=sys.stderr)
    # Ensure DEBUG is False in production
    if DEBUG:
        print("CRITICAL ERROR: DEBUG is True in production environment!", file=sys.stderr)
        sys.exit(1)
    # Check for WhiteNoise if serving static files directly via Django (common for some PaaS)
    is_whitenoise_present = any('whitenoise.middleware.WhiteNoiseMiddleware' in mw_path for mw_path in MIDDLEWARE)
    if '/static/' == STATIC_URL and not is_whitenoise_present:
        print("WARNING: Serving static files via Django (STATIC_URL='/static/') without WhiteNoise in production is inefficient and potentially insecure. Consider using WhiteNoise or a dedicated static file server.", file=sys.stderr)

print(f"--- Base settings loaded (DJANGO_ENV={DJANGO_ENV}, DEBUG={DEBUG}) ---", file=sys.stderr)

# --- END OF FILE ---