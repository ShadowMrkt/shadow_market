# backend/vault_integration.py
# <<< ENTERPRISE GRADE REVISION: v1.4.1 - Fix Helper Exception Propagation >>>
# Features: AppRole/Token Auth, KV v2 CRUD, Error Handling, Logging, Specific Helpers
# Revision Notes:
# - v1.4.1: (Current - 2025-04-07)
#   - FIXED: Pytest failures introduced in v1.4.0. Modified exception handling in
#     `get_crypto_secret_from_vault` and `get_monero_wallet_password` to explicitly
#     catch expected exceptions (VaultSecretNotFoundError, VaultAuthenticationError,
#     RuntimeError, ValueError, TypeError, etc.) raised by `read_vault_secret` or
#     the helpers themselves. These specific exceptions are now re-raised directly
#     if `raise_error=True`, allowing tests expecting them to pass. The final
#     `except Exception` now correctly catches only genuinely unexpected errors.
# - v1.4.0: Added thread safety lock. Simplified helper exception handling (which caused test failures).
# - v1.3.0: Removed debug prints from v1.2.6. Acknowledged persistent test failure.
# - Prior revisions... (details omitted for brevity, see original file for full history)

import logging
import os
import sys
from typing import Optional, Dict, Any
import datetime # Added for revision date
from threading import Lock # REQUIRED for thread-safe singleton client access

# --- BEST PRACTICE: Use try/except for critical library imports ---
try:
    import hvac
    # Import specific exceptions needed for handling
    from hvac.exceptions import InvalidPath, Forbidden, VaultError as HvacVaultError
    # Consider importing requests exceptions if needed for network error handling
    # from requests.exceptions import ConnectionError, Timeout, RequestException
    HVAC_AVAILABLE = True
except ImportError:
    # Basic logging setup for early critical failures if main config not yet loaded
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logger_init = logging.getLogger(__name__)
    logger_init.critical("CRITICAL: python-hvac library not installed. Vault integration disabled. Run `pip install hvac`")
    HVAC_AVAILABLE = False
    # Define dummies/stubs for type hinting and basic checks elsewhere
    class HvacClientStub:
        def is_authenticated(self): return False
        def sys(self): raise NotImplementedError("HVAC not installed")
        def secrets(self): raise NotImplementedError("HVAC not installed")
        def auth(self): raise NotImplementedError("HVAC not installed")
    # Define hvac as the stub type for type hinting when import fails
    hvac = HvacClientStub # type: ignore
    InvalidPath = type('InvalidPath', (Exception,), {})
    Forbidden = type('Forbidden', (Exception,), {})
    HvacVaultError = type('HvacVaultError', (Exception,), {}) # Dummy for base hvac error
    # RequestException = type('RequestException', (Exception,), {}) # Dummy if needed

# --- Custom Application Exceptions ---
# Define these here or import from your project's exceptions module (e.g., core.exceptions)
class VaultError(Exception):
    """Base exception for vault integration errors."""
    pass

class VaultAuthenticationError(VaultError):
    """Custom exception for Vault authentication failures (e.g., bad token/role, permissions)."""
    pass

class VaultSecretNotFoundError(VaultError):
    """Custom exception for when a secret path or key within a secret is not found."""
    pass

# --- Django Imports (for settings) ---
try:
    from django.conf import settings as django_settings
    DJANGO_SETTINGS_AVAILABLE = True
except ImportError:
    django_settings = None # type: ignore
    DJANGO_SETTINGS_AVAILABLE = False
    # Use print for startup warnings if logger isn't fully configured yet
    print("WARNING: Django settings not available during vault_integration import. Using environment variables as fallback.", file=sys.stderr)

# --- Logging ---
# Use standard logging; configuration should be handled by Django or the application entry point.
logger = logging.getLogger(__name__)
# Use 'django.security' if Django is present and configured for it, otherwise use a distinct name.
security_logger_name = 'django.security' if DJANGO_SETTINGS_AVAILABLE else 'vault.security'
security_logger = logging.getLogger(security_logger_name)


# --- Vault Configuration Helper ---
def _get_vault_config(key: str, default: Optional[Any] = None) -> Optional[Any]:
    """
    Safely retrieves Vault configuration.
    Priority: Django settings -> Environment variables -> Default value.
    """
    if DJANGO_SETTINGS_AVAILABLE and hasattr(django_settings, key):
        # Use getattr for safe access even if key exists but is None in settings
        config_value = getattr(django_settings, key, default)
        # Allow environment variable to override Django setting if needed (optional behavior)
        # config_value = os.environ.get(key, config_value)
        return config_value
    # Fallback to environment variable if Django not used or key not in settings
    return os.environ.get(key, default)

# --- Vault Configuration Values ---
# (Configuration loading logic remains the same as v1.4.0)
VAULT_ADDR = _get_vault_config('VAULT_ADDR')
VAULT_APPROLE_ROLE_ID = _get_vault_config('VAULT_APPROLE_ROLE_ID')
VAULT_APPROLE_SECRET_ID = _get_vault_config('VAULT_APPROLE_SECRET_ID')
VAULT_TOKEN = _get_vault_config('VAULT_TOKEN')
try:
    VAULT_KV_VERSION = int(_get_vault_config('VAULT_KV_VERSION', 2))
    if VAULT_KV_VERSION not in [1, 2]:
        raise ValueError(f"Unsupported KV version: {VAULT_KV_VERSION}")
except (ValueError, TypeError) as e:
    logger.warning(f"Invalid VAULT_KV_VERSION ('{_get_vault_config('VAULT_KV_VERSION')}') provided. Defaulting to 2. Error: {e}")
    VAULT_KV_VERSION = 2
VAULT_KV_MOUNT_POINT = _get_vault_config('VAULT_KV_MOUNT_POINT', 'secret')
VAULT_SECRET_BASE_PATH = _get_vault_config('VAULT_SECRET_BASE_PATH', 'shadowmarket')
try:
    VAULT_CLIENT_TIMEOUT = int(_get_vault_config('VAULT_CLIENT_TIMEOUT', 10))
except (ValueError, TypeError):
    VAULT_CLIENT_TIMEOUT = 10
vault_tls_verify_config = _get_vault_config('VAULT_TLS_VERIFY', 'True')
VAULT_TLS_VERIFY = str(vault_tls_verify_config).lower() not in ['false', '0', 'no', 'off']


# --- Global HVAC Client Instance & Thread Lock ---
_hvac_client_instance: Optional[hvac.Client] = None
_hvac_client_lock = Lock() # Ensure thread safety for singleton access

def get_vault_client(force_reauth: bool = False) -> Optional[hvac.Client]:
    """
    Initializes and returns a thread-safe, singleton authenticated HVAC client instance.
    Handles AppRole and Token authentication methods. Includes basic health check.

    Args:
        force_reauth: If True, bypasses health check and forces a new authentication attempt.

    Returns:
        An authenticated hvac.Client instance or None if unavailable/authentication fails.
    """
    # --- Thread Safety Lock ---
    with _hvac_client_lock:
        global _hvac_client_instance
        if not HVAC_AVAILABLE:
            # Already logged critical error on import, avoid repetitive logs
            return None

        # 1. Check existing instance health unless forcing reauth
        if not force_reauth and _hvac_client_instance:
            if _hvac_client_instance.is_authenticated():
                try:
                    # Use a lightweight health check (GET request)
                    status_response = _hvac_client_instance.sys.read_health_status(method='GET')
                    status_data = {}
                    is_healthy_status_code = False
                    if isinstance(status_response, dict): # Older hvac versions?
                        status_data = status_response
                        is_healthy_status_code = True # Assume success if no exception
                    elif hasattr(status_response, 'status_code'): # requests.Response object
                        is_healthy_status_code = 200 <= status_response.status_code < 300
                        if is_healthy_status_code:
                            try:
                                status_data = status_response.json()
                            except ValueError:
                                logger.warning("Vault health check returned non-JSON response despite 2xx status.")
                                is_healthy_status_code = False # Re-evaluate as unhealthy
                        # Log non-2xx health check status if available
                        elif hasattr(status_response, 'reason'):
                            logger.warning(f"Vault health check returned non-2xx status: {status_response.status_code} {status_response.reason}")

                    is_initialized = status_data.get('initialized', False)
                    is_sealed = status_data.get('sealed', True) # Default to sealed

                    if is_healthy_status_code and is_initialized and not is_sealed:
                        logger.debug("Using existing healthy and authenticated Vault client instance.")
                        return _hvac_client_instance
                    else:
                        logger.warning(
                            f"Existing Vault client unhealthy or status check failed. "
                            f"Status Code: {getattr(status_response, 'status_code', 'N/A')}, "
                            f"Initialized: {is_initialized}, Sealed: {is_sealed}. Re-authenticating."
                        )
                        _hvac_client_instance = None # Force re-auth

                # except (ConnectionError, Timeout, RequestException) as conn_e: # If requests exceptions were imported
                except Exception as conn_e:
                    logger.warning(f"Vault client health check failed ({type(conn_e).__name__}: {conn_e}). Re-authenticating.")
                    _hvac_client_instance = None # Force re-auth
            else: # Not authenticated
                logger.info("Existing Vault client instance is no longer authenticated. Re-authenticating.")
                _hvac_client_instance = None # Force re-auth

        # --- If instance is None or needs re-auth ---

        # 2. Check Prerequisite Configuration
        if not VAULT_ADDR:
            logger.critical("VAULT_ADDR not configured. Cannot create Vault client.")
            _hvac_client_instance = None # Ensure cleared
            return None

        # 3. Initialize New Client
        try:
            # Use configured timeout and TLS verification settings
            client = hvac.Client(
                url=VAULT_ADDR,
                timeout=VAULT_CLIENT_TIMEOUT,
                verify=VAULT_TLS_VERIFY # Production should usually be True
            )
            if not VAULT_TLS_VERIFY:
                security_logger.warning("Vault client initialized with TLS verification DISABLED. This is insecure for production.")

            logger.info(f"Initializing new Vault client for: {VAULT_ADDR}")
            authenticated = False
            auth_method_used = "None"

            # 4. Attempt Authentication (AppRole preferred)
            if VAULT_APPROLE_ROLE_ID and VAULT_APPROLE_SECRET_ID:
                auth_method_used = "AppRole"
                logger.info("Attempting Vault AppRole authentication...")
                try:
                    auth_response = client.auth.approle.login(
                        role_id=VAULT_APPROLE_ROLE_ID,
                        secret_id=VAULT_APPROLE_SECRET_ID,
                        use_token=True # Ensures client.token is set
                    )
                    if client.is_authenticated():
                        lease_duration = auth_response.get('auth', {}).get('lease_duration', 'N/A')
                        policies = auth_response.get('auth', {}).get('policies', [])
                        logger.info(f"Vault AppRole auth successful. Lease Duration: {lease_duration}, Policies: {policies}")
                        authenticated = True
                    else:
                        security_logger.critical("Vault AppRole auth call seemingly succeeded but client is not authenticated.")
                except (HvacVaultError, Forbidden) as auth_err:
                    security_logger.critical(f"Vault AppRole auth failed: {type(auth_err).__name__} - {auth_err}")
                # except RequestException as req_err:
                #     security_logger.critical(f"Network error during Vault AppRole authentication: {req_err}")
                except Exception as e:
                    security_logger.exception(f"Unexpected error during Vault AppRole authentication: {e}")

            # 5. Fallback to Token if AppRole failed or wasn't configured
            if not authenticated and VAULT_TOKEN:
                auth_method_used = "Token"
                logger.info("Attempting Vault auth using provided Token (AppRole failed or not configured).")
                client.token = VAULT_TOKEN
                if client.is_authenticated():
                    # Verify token validity/permissions
                    try:
                        health_response = client.sys.read_health_status(method='GET')
                        # Check status_code exists before comparing
                        status_code = getattr(health_response, 'status_code', None)
                        is_ok = status_code is not None and 200 <= status_code < 300
                        if is_ok:
                            logger.info("Vault auth successful using Token (verified via health check).")
                            authenticated = True
                        else:
                            security_logger.critical("Vault auth with Token failed verification (health check failed). Status: %s", status_code or 'N/A')
                    except (HvacVaultError, Forbidden) as token_verify_err:
                        security_logger.critical(f"Vault Token seems invalid or lacks permissions for verification: {token_verify_err}")
                    except Exception as e:
                        security_logger.exception(f"Unexpected error during Vault Token verification: {e}")
                else:
                    security_logger.critical("Vault Token was set, but client.is_authenticated() returned False.")


            # 6. Handle No Authentication Method Configured
            elif not authenticated and auth_method_used == "None":
                security_logger.critical("No Vault authentication method configured or successful (checked AppRole RoleID/SecretID and Token).")

            # 7. Finalize
            if authenticated:
                _hvac_client_instance = client
                logger.debug("Vault client authenticated successfully.")
                return _hvac_client_instance
            else:
                logger.error(f"Vault authentication failed using method: {auth_method_used}.")
                _hvac_client_instance = None
                return None

        # except RequestException as req_e:
        #     logger.critical(f"Network error connecting to Vault at {VAULT_ADDR}: {req_e}")
        #     _hvac_client_instance = None
        #     return None
        except Exception as e: # Catch errors during hvac.Client instantiation etc.
            logger.exception(f"CRITICAL: Failed to initialize or authenticate Vault client for {VAULT_ADDR}: {e}")
            _hvac_client_instance = None
            return None
    # --- End Thread Safety Lock ---


# --- Generic Secret Reading Function ---
# (Logic remains the same - robust handling of KV1/2, errors, keys)
def read_vault_secret(secret_sub_path: str, key: Optional[str] = None, raise_error: bool = True) -> Optional[Any]:
    """ Reads a secret (or specific key within) from Vault KV, handling KV1/KV2 and errors. """
    client = get_vault_client()
    if not client:
        if raise_error: raise RuntimeError("Vault client is unavailable or not authenticated.")
        return None

    if not VAULT_KV_MOUNT_POINT or not VAULT_SECRET_BASE_PATH:
        msg = "Vault KV mount point or base path not configured."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return None

    base_path_clean = VAULT_SECRET_BASE_PATH.strip('/')
    sub_path_clean = secret_sub_path.strip('/')
    full_secret_path = f"{base_path_clean}/{sub_path_clean}" if base_path_clean else sub_path_clean
    log_prefix = f"VaultRead(Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}', Key='{key or '(all)'}')"
    logger.debug(f"{log_prefix}: Attempting read.")

    try:
        secret_data = None
        if VAULT_KV_VERSION == 2:
            logger.debug(f"{log_prefix}: Using KVv2 read.")
            response = client.secrets.kv.v2.read_secret_version(path=full_secret_path, mount_point=VAULT_KV_MOUNT_POINT)
            secret_data = response.get('data', {}).get('data')
            logger.debug(f"{log_prefix}: KVv2 raw response data presence: {'data' in response}, {'data' in response.get('data', {}) if 'data' in response else 'N/A'}")
        elif VAULT_KV_VERSION == 1:
            logger.debug(f"{log_prefix}: Using KVv1 read.")
            response = client.secrets.kv.v1.read_secret(path=full_secret_path, mount_point=VAULT_KV_MOUNT_POINT)
            secret_data = response.get('data')
            logger.debug(f"{log_prefix}: KVv1 raw response data presence: {'data' in response}")
        else:
            msg = f"Unsupported VAULT_KV_VERSION: {VAULT_KV_VERSION}"
            logger.error(f"{log_prefix}: {msg}")
            if raise_error: raise ValueError(msg)
            return None

        if secret_data is None:
            msg = f"Secret path '{full_secret_path}' found but contains no data (or 'data' key missing/null in response)."
            logger.warning(f"{log_prefix}: {msg}")
            if key:
                if raise_error: raise VaultSecretNotFoundError(f"Key '{key}' not found within empty or non-dictionary secret at '{full_secret_path}'.")
                else: return None
            else:
                return None # Return None if no key requested and secret data is null/empty

        if key:
            if not isinstance(secret_data, dict):
                msg = f"Secret data at '{full_secret_path}' is not a dictionary (Type: {type(secret_data).__name__}). Cannot retrieve key '{key}'."
                logger.error(f"{log_prefix}: {msg}")
                if raise_error: raise TypeError(msg)
                return None
            value = secret_data.get(key)
            if value is None:
                msg = f"Key '{key}' not found within secret data at '{full_secret_path}'."
                logger.warning(f"{log_prefix}: {msg}")
                if raise_error: raise VaultSecretNotFoundError(msg)
                return None
            logger.debug(f"{log_prefix}: Successfully retrieved requested key '{key}'.")
            return value
        else: # Return whole dict
            if not isinstance(secret_data, dict):
                msg = f"Secret data at '{full_secret_path}' is not a dictionary (Type: {type(secret_data).__name__}) when requesting all data."
                logger.error(f"{log_prefix}: {msg}")
                if raise_error: raise TypeError(msg)
                return None
            logger.debug(f"{log_prefix}: Successfully retrieved all secret data (dictionary).")
            return secret_data

    except InvalidPath as e:
        msg = f"Vault path not found: Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}'"
        logger.warning(f"{log_prefix}: {msg}")
        if raise_error: raise VaultSecretNotFoundError(msg) from e
        return None
    except Forbidden as e:
        msg = f"Permission denied accessing Vault path: Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}'."
        security_logger.error(f"{log_prefix}: {msg} Check Vault ACL policies.")
        if raise_error: raise VaultAuthenticationError(msg) from e
        return None
    except HvacVaultError as e:
        logger.exception(f"{log_prefix}: Vault API error reading secret: {e}")
        if raise_error: raise VaultError(f"Vault API error reading secret '{full_secret_path}': {e}") from e
        return None
    # except RequestException as e:
    #     logger.exception(f"{log_prefix}: Network error reading Vault secret: {e}")
    #     if raise_error: raise VaultError(f"Network error reading secret '{full_secret_path}': {e}") from e
    #     return None


# --- Generic Secret Writing Function ---
# (Logic remains the same)
def write_vault_secret(secret_sub_path: str, secret_data: Dict[str, Any], raise_error: bool = True) -> bool:
    """ Writes (creates/updates) a secret in Vault KV. Handles KV V1/V2. """
    client = get_vault_client()
    if not client:
        if raise_error: raise RuntimeError("Vault client unavailable or not authenticated for writing.")
        return False

    if not VAULT_KV_MOUNT_POINT or not VAULT_SECRET_BASE_PATH:
        msg = "Vault KV mount point or base path not configured for writing."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return False

    if not isinstance(secret_data, dict):
        msg = "Secret data to write must be a dictionary."
        logger.error(msg)
        if raise_error: raise TypeError(msg)
        return False

    base_path_clean = VAULT_SECRET_BASE_PATH.strip('/')
    sub_path_clean = secret_sub_path.strip('/')
    full_secret_path = f"{base_path_clean}/{sub_path_clean}" if base_path_clean else sub_path_clean
    log_prefix = f"VaultWrite(Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}')"
    logger.info(f"{log_prefix}: Attempting write.")

    try:
        if VAULT_KV_VERSION == 2:
            logger.debug(f"{log_prefix}: Using KVv2 write (create_or_update).")
            client.secrets.kv.v2.create_or_update_secret(path=full_secret_path, secret=secret_data, mount_point=VAULT_KV_MOUNT_POINT)
        elif VAULT_KV_VERSION == 1:
            logger.debug(f"{log_prefix}: Using KVv1 write (create).")
            client.secrets.kv.v1.create_secret(path=full_secret_path, secret=secret_data, mount_point=VAULT_KV_MOUNT_POINT)
        else:
            msg = f"Unsupported VAULT_KV_VERSION for writing: {VAULT_KV_VERSION}"
            logger.error(f"{log_prefix}: {msg}")
            if raise_error: raise ValueError(msg)
            return False
        logger.info(f"{log_prefix}: Successfully wrote secret to Vault.")
        return True

    except Forbidden as e:
        msg = f"Permission denied writing Vault secret: Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}'."
        security_logger.error(f"{log_prefix}: {msg} Check Vault ACL policies.")
        if raise_error: raise VaultAuthenticationError(msg) from e
        return False
    except (InvalidPath, HvacVaultError) as e:
        logger.exception(f"{log_prefix}: Vault API error writing secret: {e}")
        if raise_error: raise VaultError(f"Failed to write secret '{full_secret_path}': {e}") from e
        return False
    # except RequestException as e:
    #     logger.exception(f"{log_prefix}: Network error writing Vault secret: {e}")
    #     if raise_error: raise VaultError(f"Network error writing secret '{full_secret_path}': {e}") from e
    #     return False
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error writing Vault secret: {e}")
        if raise_error: raise VaultError(f"Unexpected error writing secret '{full_secret_path}': {e}") from e
        return False

# --- Generic Secret Deletion Function ---
# (Logic remains the same)
def delete_vault_secret(secret_sub_path: str, raise_error: bool = False) -> bool:
    """ Deletes a secret from Vault KV. Handles KV V1 and V2 appropriately. Idempotent. """
    client = get_vault_client()
    if not client:
        if raise_error: raise RuntimeError("Vault client unavailable or not authenticated for deletion.")
        return False

    if not VAULT_KV_MOUNT_POINT or not VAULT_SECRET_BASE_PATH:
        msg = "Vault KV mount point or base path not configured for deletion."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return False

    base_path_clean = VAULT_SECRET_BASE_PATH.strip('/')
    sub_path_clean = secret_sub_path.strip('/')
    full_secret_path = f"{base_path_clean}/{sub_path_clean}" if base_path_clean else sub_path_clean
    log_prefix = f"VaultDelete(Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}')"
    logger.warning(f"{log_prefix}: Attempting PERMANENT deletion of Vault secret.")

    try:
        if VAULT_KV_VERSION == 2:
            logger.debug(f"{log_prefix}: Using KVv2 delete (metadata_and_all_versions).")
            client.secrets.kv.v2.delete_metadata_and_all_versions(path=full_secret_path, mount_point=VAULT_KV_MOUNT_POINT)
        elif VAULT_KV_VERSION == 1:
            logger.debug(f"{log_prefix}: Using KVv1 delete (delete_secret).")
            client.secrets.kv.v1.delete_secret(path=full_secret_path, mount_point=VAULT_KV_MOUNT_POINT)
        else:
            msg = f"Unsupported VAULT_KV_VERSION for deletion: {VAULT_KV_VERSION}"
            logger.error(f"{log_prefix}: {msg}")
            if raise_error: raise ValueError(msg)
            return False
        logger.info(f"{log_prefix}: Successfully deleted secret versions/metadata (or it was already gone).")
        return True

    except InvalidPath:
        logger.warning(f"{log_prefix}: Vault path not found during deletion (considered successful as secret doesn't exist).")
        return True # Treat "not found" during delete as success
    except Forbidden as e:
        msg = f"Permission denied deleting Vault secret: Mount='{VAULT_KV_MOUNT_POINT}', Path='{full_secret_path}'."
        security_logger.error(f"{log_prefix}: {msg} Check Vault ACL policies.")
        if raise_error: raise VaultAuthenticationError(msg) from e
        return False
    except HvacVaultError as e:
        logger.exception(f"{log_prefix}: Vault API error deleting secret: {e}")
        if raise_error: raise VaultError(f"Failed to delete secret '{full_secret_path}': {e}") from e
        return False
    # except RequestException as e:
    #     logger.exception(f"{log_prefix}: Network error deleting Vault secret: {e}")
    #     if raise_error: raise VaultError(f"Network error deleting secret '{full_secret_path}': {e}") from e
    #     return False
    except Exception as e:
        logger.exception(f"{log_prefix}: Unexpected error deleting Vault secret: {e}")
        if raise_error: raise VaultError(f"Unexpected error deleting secret '{full_secret_path}': {e}") from e
        return False

# --- Specific Helper Functions ---

def get_crypto_secret_from_vault(key_type: str, key_name: str, key_field: str, raise_error: bool = True) -> Optional[str]:
    """ Helper to retrieve a specific crypto key field from Vault. """
    if not key_type or not key_name or not key_field:
        msg = "key_type, key_name, and key_field must be provided."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return None

    secret_path = f"crypto_keys/{key_type.lower().strip()}/{key_name.strip()}"
    full_log_name = f"crypto key '{secret_path}' field '{key_field}'"

    try:
        value = read_vault_secret(secret_sub_path=secret_path, key=key_field, raise_error=raise_error)

        # If raise_error is True and an error occurred, read_vault_secret would have raised it.
        # If raise_error is False and an error occurred, value will be None.
        if value is None:
             if not raise_error: logger.warning(f"Value for {full_log_name} not found or Vault unavailable/error occurred (raise_error=False). See previous logs.")
             return None # Return None as requested by raise_error=False path or if value genuinely missing

        if isinstance(value, str):
            logger.debug(f"Successfully retrieved {full_log_name}.")
            return value
        else: # Value found, but wrong type
            msg = f"Vault data for {full_log_name} was found but is not a string (Type: {type(value).__name__})."
            logger.error(msg)
            if raise_error: raise TypeError(msg) # Raise expected error directly
            return None

    # --- REVISED EXCEPTION HANDLING (v1.4.1) ---
    # Catch specific, expected application exceptions from read_vault_secret or this helper's logic
    except (VaultSecretNotFoundError, VaultAuthenticationError, VaultError, # From read_vault_secret
            RuntimeError, ValueError, TypeError) as expected_e: # From read_vault_secret client check or helper's own checks/type validation
        # Log the specific error that occurred
        logger.error(f"Failed to retrieve {full_log_name}: {type(expected_e).__name__}: {expected_e}")
        if raise_error:
            raise # Re-raise the original specific exception for the caller (and tests) to handle
        else:
            return None # Return None if not raising errors

    # Catch truly *unexpected* exceptions (programming errors, unexpected system issues)
    except Exception as unexpected_e:
        logger.exception(f"Unexpected error during processing in get_crypto_secret_from_vault for {full_log_name}: {unexpected_e}")
        if raise_error:
            # Wrap unexpected errors in a generic VaultError for consistent top-level handling
            raise VaultError(f"Unexpected error processing {full_log_name}: {unexpected_e}") from unexpected_e
        else:
            return None


def get_monero_wallet_password(order_uuid_or_id: str, raise_error: bool = True) -> Optional[str]:
    """ Fetches a stored Monero wallet password for a specific order from Vault. """
    if not order_uuid_or_id:
        msg = "Order ID must be provided to retrieve Monero wallet password."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return None

    secret_path = f"monero_wallets/{str(order_uuid_or_id).strip()}"
    key_field = "password"
    full_log_name = f"Monero password for order '{order_uuid_or_id}'"
    logger.debug(f"Attempting to retrieve {full_log_name} from Vault path '{secret_path}' key '{key_field}'.")

    try:
        password = read_vault_secret(secret_sub_path=secret_path, key=key_field, raise_error=raise_error)

        if password is None:
            if not raise_error: logger.warning(f"{full_log_name} not found or Vault error occurred (raise_error=False).")
            return None

        if isinstance(password, str):
            logger.info(f"Successfully retrieved Monero password existence status for order '{order_uuid_or_id}'.")
            return password
        else: # Found but wrong type
            msg = f"Stored {full_log_name} is not a string (Type: {type(password).__name__})."
            logger.error(msg)
            if raise_error: raise TypeError(msg) # Raise expected error directly
            return None

    # --- REVISED EXCEPTION HANDLING (v1.4.1) ---
    # Catch specific, expected application exceptions from read_vault_secret or this helper's logic
    except (VaultSecretNotFoundError, VaultAuthenticationError, VaultError, # From read_vault_secret
            RuntimeError, ValueError, TypeError) as expected_e: # From read_vault_secret client check or helper's own checks/type validation
        # Log the specific error that occurred
        logger.error(f"Failed to retrieve {full_log_name}: {type(expected_e).__name__}: {expected_e}")
        if raise_error:
            raise # Re-raise the original specific exception
        else:
            return None # Return None if not raising errors

    # Catch truly *unexpected* exceptions
    except Exception as unexpected_e:
        logger.exception(f"Unexpected error during processing in get_monero_wallet_password for {full_log_name}: {unexpected_e}")
        if raise_error:
            # Wrap unexpected errors
            raise VaultError(f"Unexpected error processing {full_log_name}: {unexpected_e}") from unexpected_e
        else:
            return None


# (store_monero_wallet_password logic remains the same)
def store_monero_wallet_password(order_uuid_or_id: str, password: str, raise_error: bool = True) -> bool:
    """ Stores a Monero wallet password for a specific order in Vault. """
    if not order_uuid_or_id or not password:
        msg = "Order ID and password must be provided to store Monero wallet password."
        logger.error(msg)
        if raise_error: raise ValueError(msg)
        return False
    if not isinstance(password, str):
        msg = "Password must be a string."
        logger.error(msg)
        if raise_error: raise TypeError(msg)
        return False

    secret_path = f"monero_wallets/{str(order_uuid_or_id).strip()}"
    secret_data = {"password": password}
    log_prefix = f"VaultStoreMoneroPwd(Order='{order_uuid_or_id}', Path='{secret_path}')"
    logger.info(f"{log_prefix}: Storing Monero wallet password.")
    return write_vault_secret(secret_sub_path=secret_path, secret_data=secret_data, raise_error=raise_error)

# (delete_monero_wallet_password logic remains the same)
def delete_monero_wallet_password(order_uuid_or_id: str, raise_error: bool = False) -> bool:
    """ Deletes a stored Monero wallet password secret for a specific order from Vault. Idempotent. """
    if not order_uuid_or_id:
        msg = "Order ID must be provided to delete Monero wallet password."
        logger.error(msg)
        if raise_error: raise ValueError(msg) # Raise error if requested, even for invalid input
        return False

    secret_path = f"monero_wallets/{str(order_uuid_or_id).strip()}"
    log_prefix = f"VaultDeleteMoneroPwd(Order='{order_uuid_or_id}', Path='{secret_path}')"
    logger.warning(f"{log_prefix}: Attempting deletion of Monero wallet password secret.")
    return delete_vault_secret(secret_sub_path=secret_path, raise_error=raise_error)


# (Optional initial check code remains the same - commented out)
# def check_vault_connectivity(): ...

# <<< END OF FILE: backend/vault_integration.py >>>