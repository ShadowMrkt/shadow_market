# backend/mymarketplace/settings/base.py
# <<< Revision 4: Suppress Bandit B105 warning >>>
# Revision Notes:
# - v1.1.2 (Current - 2025-04-08):
#   - SECURITY: Suppressed Bandit B105 (hardcoded_password_string) finding for AXES_PASSWORD_FORM_FIELD
#             on line 410 (was 407) as it's a form field name, not a credential (# nosec B105).
# - v1.1.1 (2025-04-06):
#   - FIXED: Removed invalid non-printable character (U+00A0 Non-Breaking Space) from line 88
#            that was causing a SyntaxError during pytest collection/settings loading.
# - v1.1.0:
#   - FIXED: Added 'withdraw.apps.WithdrawConfig' to INSTALLED_APPS to resolve ModuleNotFoundError.
# - v1.0.1:
#   - FIXED: Corrected DATABASES configuration logic using env.db().
#   - CHANGE: Updated Forum app status comment and added Forum logger.
#   - ADDED: WebAuthn settings section and required checks.
#   - CHANGE: Made GPG_HOME mandatory and added directory checks.
#   - CHANGE: Refined .env loading logic.
#   - BEST PRACTICE: Centralized Vault client logic, stricter SECRET_KEY/ALLOWED_HOSTS.
#   - BEST PRACTICE: Explicit AppConfig paths in INSTALLED_APPS.
# - v1.0.0: Initial enterprise base settings.

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
    SESSION_COOKIE_SAMESITE=(str, 'Lax'),
    CSRF_COOKIE_SAMESITE=(str, 'Lax'),
    SECURE_HSTS_SECONDS=(int, 63072000), # 2 years
    SECURE_HSTS_INCLUDE_SUBDOMAINS=(bool, True),
    SECURE_HSTS_PRELOAD=(bool, True),
    SECURE_CONTENT_TYPE_NOSNIFF=(bool, True),
    SECURE_BROWSER_XSS_FILTER=(bool, True), # Deprecated, but set for defense-in-depth
    SECURE_REFERRER_POLICY=(str, 'strict-origin-when-cross-origin'),
    MAX_FILE_UPLOAD_SIZE_MB=(int, 5), # Max upload size in Megabytes
    AXES_ENABLED=(bool, True),
    AXES_FAILURE_LIMIT=(int, 5),
    AXES_COOLOFF_MINUTES=(int, 30),
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
    SITE_OWNER_USERNAME=(str, 'SiteOwner'), # <<< ADDED Site Owner Username >>>
    MARKET_USER_USERNAME=(str, 'MarketAccount'), # Default username for the market fee account
    PAYMENT_WAIT_HOURS=(int, 4),
    VENDOR_BOND_XMR=(Decimal, '5.0'), VENDOR_BOND_BTC=(Decimal, '0.05'), VENDOR_BOND_ETH=(Decimal, '1.0'),
    MARKET_FEE_PERCENTAGE_XMR=(Decimal, '4.0'), MARKET_FEE_PERCENTAGE_BTC=(Decimal, '4.0'), MARKET_FEE_PERCENTAGE_ETH=(Decimal, '4.5'),
    ORDER_AUTO_FINALIZE_DAYS=(int, 14), DISPUTE_WINDOW_DAYS=(int, 7), DEADMAN_SWITCH_THRESHOLD_DAYS=(int, 30),
    # --- Session/Auth Timeouts ---
    DEFAULT_SESSION_COOKIE_AGE_SECONDS=(int, 900), # 15 minutes
    OWNER_SESSION_COOKIE_AGE_SECONDS=(int, 3600), # <<< FIX v1.1.1: Removed non-breaking space before comment -> # 1 hour
    DEFAULT_PGP_AUTH_SESSION_TIMEOUT_MINUTES=(int, 15),
    OWNER_PGP_AUTH_SESSION_TIMEOUT_MINUTES=(int, 60),
    # --- DRF Defaults ---
    DRF_PAGE_SIZE=(int, 20), # Increased default page size slightly
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
# <<< BEST PRACTICE: Use Pathlib for path manipulation >>>
# BASE_DIR points to the 'backend/' directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Load .env file ONLY if not in production and file exists ---
# <<< CHANGE: Stricter check for loading .env files >>>
ENV_FILE_PATH = BASE_DIR / '.env'
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development') # Assume development if not set
TESTING = 'test' in sys.argv # Check if running tests
# Around line 93 - ensure it looks like this:
if DJANGO_ENV != 'production' and ENV_FILE_PATH.exists(): # <<< Corrected line (no 'not TESTING')
    print(f"INFO: Reading environment variables from: {ENV_FILE_PATH}", file=sys.stderr)
    environ.Env.read_env(str(ENV_FILE_PATH))
else:
    print(f"INFO: Not loading .env file (DJANGO_ENV='{DJANGO_ENV}', TESTING='{TESTING}', File Exists: {ENV_FILE_PATH.exists()})", file=sys.stderr) # <<< CHANGE: Added TESTING to log >>>

# --- Vault Integration ---
# <<< BEST PRACTICE: Centralize Vault fetching logic >>>
_vault_client = None
def get_vault_client():
    global _vault_client
    if _vault_client: return _vault_client
    VAULT_ADDR = env('VAULT_ADDR')
    if not VAULT_ADDR: return None # Vault not configured

    try:
        import hvac
        client = hvac.Client(url=VAULT_ADDR)
        # --- Authentication: Prioritize AppRole, then Token ---
        VAULT_APPROLE_ROLE_ID = env('VAULT_APPROLE_ROLE_ID')
        VAULT_APPROLE_SECRET_ID = env('VAULT_APPROLE_SECRET_ID')
        VAULT_TOKEN = env('VAULT_TOKEN')

        if VAULT_APPROLE_ROLE_ID and VAULT_APPROLE_SECRET_ID:
            print("INFO: Authenticating to Vault using AppRole.", file=sys.stderr)
            client.auth.approle.login(
                role_id=VAULT_APPROLE_ROLE_ID,
                secret_id=VAULT_APPROLE_SECRET_ID,
            )
        elif VAULT_TOKEN:
            print("INFO: Authenticating to Vault using Token.", file=sys.stderr)
            client.token = VAULT_TOKEN
        else:
            print("ERROR: Vault address configured, but no authentication method (AppRole/Token) provided.", file=sys.stderr)
            return None # Cannot authenticate

        if client.is_authenticated():
            print("INFO: Vault client authenticated successfully.", file=sys.stderr)
            _vault_client = client
            return _vault_client
        else:
            print("ERROR: Vault client authentication failed.", file=sys.stderr)
            return None
    except ImportError:
        print("ERROR: HVAC library not installed. Cannot use Vault. `pip install hvac`", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: Failed to initialize or authenticate Vault client: {e}", file=sys.stderr)
        return None

def get_secret_from_vault(secret_name: str, key: str, raise_error=True):
    """Fetches a specific key from a secret in Vault KV v2 store."""
    client = get_vault_client()
    if not client:
        if raise_error: raise RuntimeError("Vault client unavailable.")
        return None

    VAULT_KV_MOUNT_POINT = env('VAULT_KV_MOUNT_POINT')
    VAULT_SECRET_BASE_PATH = env('VAULT_SECRET_BASE_PATH')
    full_secret_path = f"{VAULT_SECRET_BASE_PATH}/{secret_name}"

    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=full_secret_path,
            mount_point=VAULT_KV_MOUNT_POINT,
        )
        secret_data = response['data']['data']
        value = secret_data.get(key)
        if value:
            # print(f"INFO: Fetched '{key}' from Vault secret '{full_secret_path}'.", file=sys.stderr)
            return value
        else:
            msg = f"Key '{key}' not found in Vault secret '{full_secret_path}'."
            print(f"ERROR: {msg}", file=sys.stderr)
            if raise_error: raise KeyError(msg)
            return None
    except Exception as e:
        msg = f"Failed to fetch '{key}' from Vault secret '{full_secret_path}': {e}"
        print(f"ERROR: {msg}", file=sys.stderr)
        if raise_error: raise RuntimeError(msg) from e
        return None

# --- Core Settings ---
# <<< CHANGE: Strict SECRET_KEY handling - MUST come from Vault or Env >>>
SECRET_KEY = env('DJANGO_SECRET_KEY') or get_secret_from_vault('django', 'secret_key', raise_error=False)
if not SECRET_KEY:
    print("CRITICAL ERROR: DJANGO_SECRET_KEY is not set via environment variable or Vault.", file=sys.stderr)
    sys.exit(1) # Exit if secret key is missing

DEBUG = env('DEBUG')

# <<< CHANGE: Stricter ALLOWED_HOSTS - MUST be set via env for prod >>>
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS')
if DJANGO_ENV == 'production' and ('localhost' in ALLOWED_HOSTS or '127.0.0.1' in ALLOWED_HOSTS or not ALLOWED_HOSTS):
    print("CRITICAL ERROR: DJANGO_ALLOWED_HOSTS is misconfigured for production!", file=sys.stderr)
    print("                     It should ONLY contain the .onion domain(s).", file=sys.stderr)
    sys.exit(1)

SITE_ID = env.int('SITE_ID')

# --- Application Definition ---
# <<< BEST PRACTICE: Define app configs explicitly >>>
INSTALLED_APPS = [
    # Django Core Apps First
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party Apps
    'rest_framework',
    # 'rest_framework.authtoken', # Prefer Session/JWT over basic token auth
    'rest_framework_simplejwt', # Included if needed for API tokens
    'django_celery_results',
    'axes', # Login attempt tracking
    'django_otp', # Base OTP framework
    'django_otp.plugins.otp_static', # Static backup codes (discouraged in production)
    'captcha', # CAPTCHA protection
    'django_filters', # For DRF filtering
    # <<< FIX: Add WebAuthn app (if needed separate from store) >>>
    # 'webauthn.apps.WebauthnConfig', # Example if WebAuthn is a separate app

    # Local Apps (using AppConfig paths)
    'store.apps.StoreConfig',
    'adminpanel.apps.AdminpanelConfig',
    'ledger.apps.LedgerConfig',
    'notifications.apps.NotificationsConfig',
    'forum.apps.ForumConfig',
    'withdraw.apps.WithdrawConfig', # <<< FIX v1.1.0: Added withdraw app >>>
]

MIDDLEWARE = [
    # Security middleware high up
    'django.middleware.security.SecurityMiddleware',
    'mymarketplace.middleware.SecurityHeadersMiddleware.SecurityHeadersMiddleware', # Custom CSP/Headers

    # Session handling AFTER security headers potentially
    'django.contrib.sessions.middleware.SessionMiddleware',

    # Common middleware
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', # CSRF protection

    # Auth/User handling
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware', # Must be AFTER AuthenticationMiddleware

    # Axes must be after AuthenticationMiddleware and SessionMiddleware
    'axes.middleware.AxesMiddleware',

    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware', # Covered by CSP, but defense-in-depth

    # Custom Middleware
    'mymarketplace.middleware.OwnerSessionMiddleware.OwnerSessionMiddleware', # Extends owner session timeout
    'mymarketplace.middleware.RequestValidationMiddleware.RequestValidationMiddleware', # Input size validation
    'mymarketplace.middleware.RateLimitMiddleware.DistributedRateLimitMiddleware', # Custom rate limiting
    'mymarketplace.middleware.AnomalyDetectionMiddleware.AnomalyDetectionMiddleware', # Basic anomaly detection
    'mymarketplace.middleware.ErrorHandlingMiddleware.ErrorHandlingMiddleware', # Global exception handling
]

ROOT_URLCONF = 'mymarketplace.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Project-level templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'builtins': [
                # Add custom template tags/filters if needed
            ],
            # <<< BEST PRACTICE: Enable template debugging only if DEBUG is True >>>
            'debug': DEBUG,
        },
    },
]

WSGI_APPLICATION = 'mymarketplace.wsgi.application'

# --- Database ---
# <<< MODIFIED: Use env.db directly with the variable name and default >>>
print(f"DEBUG: Attempting to configure DATABASES using env.db('DATABASE_URL')...", file=sys.stderr)
DATABASES = {
    # env.db looks for 'DATABASE_URL' in Env/.env, uses default URL if not found.
    'default': env.db('DATABASE_URL', default='sqlite:///db_test_direct.sqlite3')
}
# Optional: Add engine/options if default URL doesn't specify them
# DATABASES['default'].setdefault('ENGINE', 'django.db.backends.sqlite3') # Engine is usually inferred from URL scheme
print(f"DEBUG: DATABASES configured as: {DATABASES['default'].get('ENGINE', 'N/A')} | {DATABASES['default'].get('NAME', 'N/A')}", file=sys.stderr) # Safer print
# <<< END MODIFIED BLOCK >>>

# Added safer check for password presence
if 'PASSWORD' not in DATABASES['default'] or not DATABASES['default'].get('PASSWORD'):
      print("WARNING: Database password appears empty or not set.", file=sys.stderr)

# <<< BEST PRACTICE: Use connection pooling in production >>>
# DATABASES['default']['CONN_MAX_AGE'] = 600 # Example: 10 minutes

# --- Password validation ---
# <<< BEST PRACTICE: Use strong validators >>>
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 14}}, # Increased min length
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'axes.validators.AxesPasswordValidator'}, # Integrate Axes
    # Consider adding zxcvbn validation if library is added
    # {'NAME': 'zxcvbn_password.ZXCVBNValidator'},
]
# <<< BEST PRACTICE: Argon2 is the strongest default hasher >>>
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# --- Authentication Settings ---
AUTH_USER_MODEL = 'store.User'
# <<< BEST PRACTICE: Define explicit login/logout URLs, even if primarily API based >>>
LOGIN_URL = '/api/store/auth/login/init/' # Example API login endpoint
LOGOUT_URL = '/api/store/auth/logout/' # Example API logout endpoint
# LOGIN_REDIRECT_URL = '/' # Less relevant for API-centric apps
# LOGOUT_REDIRECT_URL = '/'

# --- Internationalization ---
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False # Explicitly disable if not needed for simplicity/security
USE_TZ = True

# --- Static files & Media files ---
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# <<< BEST PRACTICE: Don't serve static files via Django in production >>>
# STATICFILES_DIRS = [ BASE_DIR / "static", ] # Only needed if collecting from project static dir

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# <<< BEST PRACTICE: Use dedicated file storage in production (e.g., S3, MinIO) >>>
# DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MAX_UPLOAD_SIZE = env.int('MAX_FILE_UPLOAD_SIZE_MB') * 1024 * 1024

# --- Default primary key ---
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Security Settings (Defaults loaded via django-environ) ---
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT')
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE')
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE')
SESSION_COOKIE_HTTPONLY = env.bool('SESSION_COOKIE_HTTPONLY')
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE')
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE')
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = env.bool('SECURE_CONTENT_TYPE_NOSNIFF')
SECURE_BROWSER_XSS_FILTER = env.bool('SECURE_BROWSER_XSS_FILTER') # Deprecated, handled by CSP Middleware
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS')
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD')
SECURE_REFERRER_POLICY = env('SECURE_REFERRER_POLICY')
# <<< BEST PRACTICE: Ensure proxy headers are configured if behind a TRUSTED proxy >>>
# USE_X_FORWARDED_HOST = True # If proxy sets X-Forwarded-Host
# SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- Session Settings ---
SESSION_COOKIE_AGE = env.int('DEFAULT_SESSION_COOKIE_AGE_SECONDS')
SESSION_SAVE_EVERY_REQUEST = True # Needed for activity timeout tracking
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db' # Secure, DB-backed sessions
# SESSION_CACHE_ALIAS = 'default' # Use the default cache

# --- Cache Settings ---
# <<< BEST PRACTICE: Use secure Redis URL with password >>>
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            # Add connection pool settings, timeouts, potential TLS config if needed
            # 'PASSWORD': env('REDIS_PASSWORD', default=None), # Handled via REDIS_URL format preferred
        }
    }
}

# --- Logging Configuration ---
# <<< BEST PRACTICE: Structured JSON logging for production >>>
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True) # Ensure log directory exists
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(levelname)s %(name)s %(module)s %(pathname)s:%(lineno)d %(message)s %(process)d %(thread)d',
        },
        'verbose': { 'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s' },
        'simple': { 'format': '%(levelname)s %(name)s %(message)s' },
    },
    'filters': {
        'require_debug_false': { '()': 'django.utils.log.RequireDebugFalse', },
        'require_debug_true': { '()': 'django.utils.log.RequireDebugTrue', },
        # <<< BEST PRACTICE: Basic sensitive data filtering (expand keywords) >>>
        'exclude_sensitive': {
            '()': 'django.utils.log.CallbackFilter',
            'callback': lambda record: not any(word in str(getattr(record, 'message', '') or getattr(record, 'msg', '')).lower() for word in [ # Safer access to message
                'password', 'secret', 'token', 'key', 'credit', 'card', 'cvv', 'private',
                'mnemonic', 'apikey', 'credential', 'bearer', 'authorization', 'sessionid', 'csrftoken' # Added common tokens
            ]),
        }
    },
    'handlers': {
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'filters': ['require_debug_true'] if DEBUG else ['require_debug_false', 'exclude_sensitive'], # Apply sensitive filter in prod
            'class': 'logging.StreamHandler',
            'formatter': 'simple' if DEBUG else 'json', # JSON logs in prod
        },
        'file_app': {
            'level': 'INFO',
            'filters': ['require_debug_false', 'exclude_sensitive'],
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'app.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'json',
        },
        'file_security': {
            'level': 'INFO',
            'filters': ['require_debug_false'], # Security log might need less filtering
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'security.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'json',
        },
        'null': { 'class': 'logging.NullHandler', },
    },
    'loggers': {
        'django': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'django.request': { 'handlers': ['file_app', 'file_security'], 'level': 'ERROR', 'propagate': False, }, # Log 500s
        'django.security': { 'handlers': ['file_security'], 'level': 'WARNING', 'propagate': False, },
        'axes': { 'handlers': ['console', 'file_security'], 'level': 'INFO', 'propagate': False, },
        # Application loggers
        'store': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'adminpanel': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'ledger': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'notifications': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'forum': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'withdraw': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, }, # <<< ADDED withdraw logger >>>
        'mymarketplace.middleware': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        # Service loggers (consider adjusting levels)
        'store.services': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'store.services.pgp_service': { 'handlers': ['console', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'store.services.escrow_service': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'store.services.encryption_service': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
        'store.services.monero_service': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'store.services.bitcoin_service': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'store.services.ethereum_service': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, },
        'withdraw.services': { 'handlers': ['console', 'file_app', 'file_security'], 'level': 'INFO', 'propagate': False, }, # <<< ADDED withdraw.services logger >>>
        # Third-party loggers
        'hvac': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, }, # Vault client
        'gnupg': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, }, # python-gnupg
        'web3': { 'handlers': ['console', 'file_app'], 'level': 'WARNING', 'propagate': False, },
        'celery': { 'handlers': ['console', 'file_app'], 'level': 'INFO', 'propagate': False, },
    },
    # <<< BEST PRACTICE: Define root logger to catch unhandled logs >>>
    'root': {
        'handlers': ['console', 'file_app'] if DEBUG else ['file_app'],
        'level': 'INFO',
    },
}

# --- Sentry SDK ---
# Note: Removed redundant Sentry block from end of original file. This block is more complete.
SENTRY_DSN = env('SENTRY_DSN')
if SENTRY_DSN and not DEBUG:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        # <<< BEST PRACTICE: Configure logging integration carefully >>>
        sentry_logging = LoggingIntegration(
            level=logging.INFO,      # Send INFO level logs as breadcrumbs
            event_level=logging.ERROR  # Send ERROR level logs as events
        )
        # <<< BEST PRACTICE: Add before_send hook for data scrubbing >>>
        def before_send(event, hint):
            # Example: Scrub sensitive data from event['request']['data'] or headers
            # if 'exc_info' in hint and isinstance(hint['exc_info'][1], SensitiveException): return None
            return event

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[ DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging ],
            traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE'),
            send_default_pii=False, # Explicitly disable sending PII
            environment=DJANGO_ENV, # Use 'production' or specific env name
            # release="shadowmarket@<git-commit-sha>" # Set dynamically in CI/CD
            before_send=before_send,
        )
        print("INFO: Sentry SDK initialized for production.", file=sys.stderr)
    except ImportError:
        print("WARNING: Sentry DSN configured, but 'sentry-sdk' not installed. `pip install sentry-sdk`", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed to initialize Sentry SDK: {e}", file=sys.stderr)


# --- Celery Configuration ---
# <<< BEST PRACTICE: Use secure broker URL with password >>>
CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = 'django-db' # Store results in Django DB
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# <<< BEST PRACTICE: Set visibility timeout appropriate for tasks >>>
# CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 3600} # 1 hour example
# <<< BEST PRACTICE: Configure flower for monitoring if used >>>
# FLOWER_ENABLED = env.bool('FLOWER_ENABLED', default=False)

# --- REST Framework ---
# <<< BEST PRACTICE: Use SessionAuth primarily, add JWT/Token if specific API clients need it >>>
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        # 'rest_framework_simplejwt.authentication.JWTAuthentication', # Uncomment if JWT needed
        # 'rest_framework.authentication.TokenAuthentication', # Less secure than Session/JWT
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        # Default to authenticated for most endpoints
        'rest_framework.permissions.IsAuthenticatedOrReadOnly', # ReadOnly for safe methods, Auth for others
    ),
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ] + (['rest_framework.renderers.BrowsableAPIRenderer'] if DEBUG else []), # Browsable API only in DEBUG
    'DEFAULT_PARSER_CLASSES': ( # Ensure JSON parser is default
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser', # For admin panel or specific form posts
        'rest_framework.parsers.MultiPartParser', # For file uploads if needed
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('DRF_ANON_THROTTLE_RATE'),
        'user': env('DRF_USER_THROTTLE_RATE')
    },
    # <<< BEST PRACTICE: Use custom exception handler >>>
    'EXCEPTION_HANDLER': 'mymarketplace.middleware.ErrorHandlingMiddleware.api_exception_handler',
    # Pagination Settings
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': env.int('DRF_PAGE_SIZE'),
    'PAGE_SIZE_QUERY_PARAM': 'page_size', # Allow client override (optional)
    'MAX_PAGE_SIZE': env.int('DRF_MAX_PAGE_SIZE'),
    # <<< BEST PRACTICE: Use OpenAPI schema >>>
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.openapi.AutoSchema',
    # <<< BEST PRACTICE: Configure JSON renderer options for consistency >>>
    # 'UNICODE_JSON': True, # Already default
    # 'COMPACT_JSON': True, # Already default
    # 'STRICT_JSON': True, # Already default
}

# --- Django-Axes Configuration ---
# <<< BEST PRACTICE: Use cache handler for distributed environments >>>
AXES_ENABLED = env.bool('AXES_ENABLED')
AXES_FAILURE_LIMIT = env.int('AXES_FAILURE_LIMIT')
AXES_COOLOFF_TIME = timedelta(minutes=env.int('AXES_COOLOFF_MINUTES'))
AXES_LOCKOUT_TEMPLATE = 'registration/lockout.html' # Ensure this template exists if needed
AXES_USERNAME_FORM_FIELD = 'username'
AXES_PASSWORD_FORM_FIELD = 'password' # nosec B105 - This is a form field name, not a password value.
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True
AXES_ONLY_USER_FAILURES = False
AXES_RESET_ON_SUCCESS = True
AXES_HANDLER = 'axes.handlers.cache.AxesCacheHandler'
AXES_CACHE = 'default'
# <<< BEST PRACTICE: Log Axes events >>>
AXES_PROXY_COUNT = env.int('AXES_PROXY_COUNT', default=0) # If behind proxies
# AXES_LOCKOUT_URL = '/account-locked/' # Custom lockout URL if needed

# --- Django-OTP Configuration ---
OTP_LOGIN_URL = LOGIN_URL # Redirect here if OTP needed but not provided
OTP_ADMIN_ENFORCE_OTP = True # Enforce OTP for Django admin site (/control/)
# <<< CHANGE: Remove static device if not strictly needed for recovery >>>
# OTP_STATIC_ENABLED = False # Disable static codes in production? (Requires alternative recovery)

# --- Captcha Settings ---
CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.math_challenge'
CAPTCHA_TIMEOUT = 5 # minutes
# <<< BEST PRACTICE: Customize noise/fonts if needed for security >>>
# CAPTCHA_NOISE_FUNCTIONS = (...)
# CAPTCHA_FONT_PATH = ...

# --- GPG/PGP Settings ---
# <<< CHANGE: GPG_HOME is now mandatory >>>
GPG_HOME = env('GPG_HOME')
if not GPG_HOME:
    print("CRITICAL ERROR: GPG_HOME environment variable is not set.", file=sys.stderr)
    sys.exit(1)
# <<< BEST PRACTICE: Ensure GPG_HOME directory exists and has correct permissions >>>
GPG_HOME_PATH = Path(GPG_HOME)
try:
    GPG_HOME_PATH.mkdir(parents=True, exist_ok=True, mode=0o700) # Create with restrictive permissions
    print(f"INFO: Ensured GPG directory exists: {GPG_HOME_PATH}", file=sys.stderr)
except OSError as e:
    print(f"WARNING: Could not create or verify GPG directory permissions for {GPG_HOME_PATH}: {e}", file=sys.stderr)


# --- Cryptocurrency Settings (Loaded via django-environ) ---
# <<< BEST PRACTICE: Use list for consistency >>>
SUPPORTED_CURRENCIES = ['XMR', 'BTC', 'ETH']
# Specific node URLs, credentials, confirmation counts, etc., are loaded from `env` at the top.

# --- Marketplace Specific Settings (Loaded via django-environ) ---
# Values loaded directly from env object at top
SITE_OWNER_USERNAME = env('SITE_OWNER_USERNAME') # Defined in env defaults now
MARKET_USER_USERNAME = env('MARKET_USER_USERNAME')
# Fees, bond amounts, timeouts etc loaded from `env` at the top.

# --- PGP Session Timeout Settings (Loaded via django-environ) ---
# Values (DEFAULT_PGP_AUTH_SESSION_TIMEOUT_MINUTES, OWNER_PGP_AUTH_SESSION_TIMEOUT_MINUTES) loaded from `env` at top.

# --- WebAuthn (FIDO2) Settings ---
# REASON: Added configuration parameters required by the WebAuthn service.
# MUST be set via environment variables or Vault for production.
WEBAUTHN_RP_NAME = 'Shadow Market' # Human-readable name for the Relying Party (your site)
WEBAUTHN_RP_ID = env('WEBAUTHN_RP_ID', default=None) # Relying Party ID (e.g., your .onion domain OR localhost in dev). CRITICAL.
WEBAUTHN_EXPECTED_ORIGIN = env('WEBAUTHN_EXPECTED_ORIGIN', default=None) # Full origin (e.g., http://<onion_address>.onion OR http://localhost:3000 in dev). CRITICAL.
WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS = env.int('WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS', default=300) # Timeout for challenges (default: 5 minutes)

# Add mandatory checks for production environment
if DJANGO_ENV == 'production':
    if not WEBAUTHN_RP_ID:
        print("CRITICAL ERROR: WEBAUTHN_RP_ID setting is NOT configured for production!", file=sys.stderr)
        sys.exit(1)
    if not WEBAUTHN_EXPECTED_ORIGIN:
        print("CRITICAL ERROR: WEBAUTHN_EXPECTED_ORIGIN setting is NOT configured for production!", file=sys.stderr)
        sys.exit(1)
    # Optionally, perform stricter validation on the format of RP_ID and ORIGIN here
    # e.g., check if RP_ID looks like a domain, or origin looks like a valid URL.

# --- Final Checks (Production Only) ---
if DJANGO_ENV == 'production':
    # <<< BEST PRACTICE: Check critical service URLs are configured >>>
    if not all([env('MONERO_RPC_URL'), env('MONERO_WALLET_RPC_URL'), env('BITCOIN_RPC_URL'), env('ETHEREUM_NODE_URL')]):
        print("CRITICAL WARNING: One or more cryptocurrency node URLs are NOT configured for production!", file=sys.stderr)
    if env('VAULT_ADDR') and not (env('VAULT_TOKEN') or (env('VAULT_APPROLE_ROLE_ID') and env('VAULT_APPROLE_SECRET_ID'))):
        print("CRITICAL WARNING: VAULT_ADDR is set, but no Vault authentication method provided.", file=sys.stderr)
    if not env('GPG_HOME'): # Redundant check as it exits earlier, but good for defense-in-depth
        print("CRITICAL WARNING: GPG_HOME is not set for production!", file=sys.stderr)
    # Add check for market user existence?
    # Add check for secure Redis password? (Difficult from URL)
    if DEBUG:
        print("CRITICAL ERROR: DEBUG is True in production environment!", file=sys.stderr)
        sys.exit(1)


print(f"--- Base settings loaded (DJANGO_ENV={DJANGO_ENV}) ---", file=sys.stderr)

# --- END OF FILE ---