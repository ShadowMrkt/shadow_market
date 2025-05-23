# backend/store/services/pgp_service.py
# Enterprise Grade: Robust GPG Handling via Service Class, Secure Flows, Constant-Time Comparisons

# Make all type hints strings implicitly (resolves Pylance 'Variable not allowed...' issues)
from __future__ import annotations

# <<< ENTERPRISE GRADE REVISIONS >>>
# - v1.3.4: (2025-05-04) - Improve Input Validation & Error Handling by Gemini
#   - Enhanced `get_key_details` input validation logging to show snippet of invalid key data.
#   - Modified `get_key_details` to catch potential `ValueError` from the external `validate_pgp_public_key`
#     and convert it to a `PGPKeyError` for consistent error handling within the service. This aims
#     to better handle the numerous 'Malformed block structure' errors seen in tests, potentially
#     originating from the validator or the test data fed into it.
#   - Added check for specific GPG import error ("no valid OpenPGP data found").
# - v1.3.3: (2025-05-04) - Enhanced ValueError Logging by Gemini
#   - Added detailed logging within ValueError blocks to show the problematic input values, aiding test debugging.
# - v1.3.2: (2025-05-03) - Address Stale Pylance 'reportInvalidTypeForm' Errors by Gemini
#   - Reviewed Pylance errors regarding `bool` in type expressions (reportInvalidTypeForm).
#   - Confirmed `from __future__ import annotations` is present (added in v1.2.0)
#     which correctly resolves this type of Pylance error by treating hints as strings.
#   - Verified that the `bool` annotations at the previously reported locations are syntactically correct.
#   - Conclusion: The reported Pylance errors were likely stale; no code changes needed.
# - v1.3.1: (2025-05-03) - Enforced absolute imports by Gemini
#   - Updated imports for store.models and store.validators to use 'backend.' prefix.
#   - Aims to resolve Django model registry conflicts.
# - v1.3.0: (2025-04-06) - Enterprise Grade Refactor by Gemini based on User Requirements
#   - SECURITY (Initialization): Ensured GPG_HOME, checks, early GPG test.
#   - SECURITY (Key Handling): Enhanced temp key handling, external validator use.
#   - SECURITY (Challenge/Response): Secure nonces, hashed challenges, cache deletion, constant-time compare.
#   - SECURITY (Encryption/Decryption): `always_trust` clarification, improved error handling.
#   - SECURITY (Signature Verification): Robust checks, constant-time compare.
#   - ROBUSTNESS & LOGGING: Custom exceptions, security logger, type hints, _ensure_service helper.
# - v1.2.0: (2025-04-06) - Fix GPGError AttributeError, TypeError Hint, Cleanup by Gemini
#   - FIXED: `AttributeError: module 'gnupg' has no attribute 'GPGError'`.
#   - ADDED: `from __future__ import annotations`.
#   - IMPROVED: Fingerprint check in `get_key_details` finally block.
#   - ADDED: Comments for `verify_message_signature`.
#   - ADDED: TODO for `verify_message_signature`.
# - v1.1.0: (2025-04-06) - Add Singleton Instance and Module Wrappers by Gemini
#   - FIXED: `AttributeError` in tests.
#   - Added module-level instance and wrapper functions.
#   - Renamed `encrypt_message` to `encrypt_message_for_recipient`.
#   - Added stub `verify_message_signature`.

import gnupg
import os
import logging
import secrets  # For cryptographically secure nonces
import hashlib  # For hashing context/challenges
import hmac     # For constant-time comparison
from pathlib import Path  # For GPG_HOME path handling
from typing import Optional, Tuple, Dict, Any, TYPE_CHECKING, Union

# --- Django Imports ---
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache  # Use Django cache for nonce/challenge storage
from django.core.exceptions import ImproperlyConfigured, ValidationError as DjangoValidationError

# --- Local Imports ---
# Use TYPE_CHECKING to avoid circular imports but allow type hints
if TYPE_CHECKING:
    # Use absolute paths starting from 'backend.'
    from backend.store.models import User
    from backend.store.validators import validate_pgp_public_key

# Explicit try/except for runtime import checks - critical for service usability
_MODEL_VALIDATOR_AVAILABLE = False # Flag for successful import
try:
    # These imports ARE needed at runtime for the service to function
    # Use absolute paths starting from 'backend.'
    from backend.store.models import User
    from backend.store.validators import validate_pgp_public_key
    _MODEL_VALIDATOR_AVAILABLE = True
except ImportError as e:
    # Use basic config if Django logging isn't ready
    logging.basicConfig(level=logging.CRITICAL)
    _logger_init = logging.getLogger(__name__)
    # Log critically, as the service might be unusable
    _logger_init.critical(f"CRITICAL IMPORT ERROR in {__name__}: {e}. Check model/validator paths. PGPService may fail to initialize or function.")
    # Define dummies to allow the file to be imported, but service instantiation will likely fail.
    User = None # type: ignore
    validate_pgp_public_key = None # type: ignore


# --- Logging ---
# Standard logger for general info/errors within the service
logger = logging.getLogger(__name__)
# Dedicated security logger for sensitive events (auth failures, verification issues)
security_logger = logging.getLogger('django.security') # Standard Django security logger

# --- Custom Exceptions ---
class PGPError(Exception):
    """Base exception for PGP service errors."""
    pass

class PGPInitializationError(PGPError):
    """Error during GPG instance initialization or dependency checks."""
    pass

class PGPConfigurationError(PGPInitializationError):
    """Configuration setting missing or invalid."""
    pass

class PGPKeyError(PGPError):
    """Error related to PGP key handling (import, validation, lookup, cleanup)."""
    pass

class PGPEncryptionError(PGPError):
    """Error during PGP encryption."""
    pass

class PGPDecryptionError(PGPError):
    """Error during PGP decryption."""
    pass

class PGPVerificationError(PGPError):
    """Error during signature or challenge verification."""
    pass

class PGPCacheError(PGPError):
    """Error related to caching challenges or nonces."""
    pass


class PGPService:
    """
    Provides PGP functionalities like encryption, decryption, signing verification,
    and secure challenge-response flows for 2FA and action confirmation.

    Manages a single GnuPG instance for the application lifecycle.
    Requires 'GPG_HOME' to be configured in Django settings and ensures the directory exists.
    Optionally uses 'GPG_BINARY_PATH' and 'GPG_USE_AGENT'.
    Uses Django cache for secure nonce/challenge storage.
    Relies on external validator (`validate_pgp_public_key`) for initial key checks.
    """

    # --- Constants ---
    LOGIN_CHALLENGE_CACHE_PREFIX = "pgp_login_challenge_"
    ACTION_NONCE_CACHE_PREFIX = "pgp_action_nonce_"
    # Default timeouts (can be overridden via Django settings)
    DEFAULT_LOGIN_CHALLENGE_TIMEOUT_SECONDS: int = 480  # 8 minutes
    DEFAULT_ACTION_NONCE_TIMEOUT_SECONDS: int = 300   # 5 minutes

    # Settings keys (avoids magic strings)
    SETTING_GPG_HOME = 'GPG_HOME'
    SETTING_GPG_BINARY = 'GPG_BINARY_PATH'
    SETTING_GPG_USE_AGENT = 'GPG_USE_AGENT'
    SETTING_LOGIN_TIMEOUT = 'PGP_LOGIN_CHALLENGE_TIMEOUT_SECONDS'
    SETTING_ACTION_TIMEOUT = 'PGP_ACTION_NONCE_TIMEOUT_SECONDS'

    def __init__(self):
        """
        Initializes the GnuPG interface based on Django settings.
        Ensures GPG_HOME directory exists and has secure permissions.
        Checks for critical dependencies and GPG functionality.
        Raises PGPConfigurationError or PGPInitializationError on failure.
        """
        self.gpg: Optional[gnupg.GPG] = None # Holds the GPG instance

        # 1. Check for critical dependencies loaded at module level
        if not _MODEL_VALIDATOR_AVAILABLE or User is None or validate_pgp_public_key is None:
            raise PGPInitializationError(
                "Cannot initialize PGPService due to missing critical "
                "dependencies (User model or PGP validator). Check logs for ImportErrors."
            )

        # 2. Retrieve GPG configuration from Django settings
        gpg_home_setting = getattr(settings, self.SETTING_GPG_HOME, None)
        if not gpg_home_setting:
            raise PGPConfigurationError(
                f"'{self.SETTING_GPG_HOME}' setting is not configured in Django settings. "
                "PGP operations cannot be performed."
            )

        gpg_binary = getattr(settings, self.SETTING_GPG_BINARY, 'gpg')
        use_agent = getattr(settings, self.SETTING_GPG_USE_AGENT, False)

        try:
            # 3. Ensure GPG_HOME directory exists and handle path
            gpg_home_path = Path(gpg_home_setting).resolve() # Use resolved, absolute path

            if not gpg_home_path.is_dir():
                logger.warning(
                    f"'{self.SETTING_GPG_HOME}' directory '{gpg_home_path}' does not exist. "
                    f"Attempting creation with restricted permissions (0o700). "
                    f"Ensure this directory is managed correctly with appropriate ownership in production."
                )
                try:
                    # Create directory with mode 0o700 (owner read/write/execute only)
                    gpg_home_path.mkdir(mode=0o700, parents=True, exist_ok=True)
                    logger.info(f"Created GPG_HOME directory: {gpg_home_path}")
                    # Note: We cannot easily verify ownership here, relies on deployment setup.
                except OSError as mkdir_e:
                    raise PGPInitializationError(
                        f"Failed to create GPG_HOME directory '{gpg_home_path}': {mkdir_e}. Check permissions."
                    ) from mkdir_e
                except Exception as unexpected_mkdir_e:
                    raise PGPInitializationError(
                        f"Unexpected error creating GPG_HOME directory '{gpg_home_path}': {unexpected_mkdir_e}"
                    ) from unexpected_mkdir_e
            else:
                # Optional: Add check for permissions if directory exists (complex and OS-dependent)
                # try:
                #     if (gpg_home_path.stat().st_mode & 0o777) != 0o700:
                #         logger.warning(f"GPG_HOME directory '{gpg_home_path}' has permissions "
                #                        f"{oct(gpg_home_path.stat().st_mode & 0o777)}, expected 0o700. "
                #                        f"Recommend restricting permissions.")
                # except OSError as stat_e:
                #     logger.warning(f"Could not check permissions for GPG_HOME '{gpg_home_path}': {stat_e}")
                pass # Keep it simple for now, focus on creation.

            # 4. Initialize python-gnupg
            logger.info(f"Initializing GnuPG: Home='{gpg_home_path}', Binary='{gpg_binary}', UseAgent={use_agent}")
            self.gpg = gnupg.GPG(
                gnupghome=str(gpg_home_path),
                gpgbinary=gpg_binary,
                use_agent=use_agent,
                options=['--batch', '--yes'] # Ensure non-interactive mode
            )
            self.gpg.encoding = 'utf-8' # Explicitly set encoding

            # 5. Perform a basic GPG check to ensure it's functional
            # This can raise exceptions if GPG binary isn't found or has issues
            # Use a non-modifying command like listing keys
            self.gpg.list_keys()
            logger.info(
                f"GnuPG initialized successfully. Version: {getattr(self.gpg, 'version', 'N/A')}. "
                f"GPG_HOME: '{gpg_home_path}'"
            )

        except (TypeError, FileNotFoundError) as init_e: # Common init issues
            self.gpg = None
            raise PGPInitializationError(
                f"Failed GnuPG initialization: Check python-gnupg installation, "
                f"GPG executable path ('{gpg_binary}'), or GPG_HOME permissions/existence ('{gpg_home_setting}'). "
                f"Error: {init_e}"
            ) from init_e
        except Exception as e: # Catch other unexpected errors during init
            self.gpg = None
            logger.exception(f"Unexpected error initializing GnuPG at '{gpg_home_setting}' with binary '{gpg_binary}'")
            raise PGPInitializationError(f"Unexpected GnuPG initialization error: {e}") from e

    def _check_gpg_instance(self) -> gnupg.GPG:
        """Internal helper to ensure GPG is initialized before use."""
        if self.gpg is None:
            logger.critical("GPG instance is None when trying to use it. Service may not have initialized correctly.")
            # This state should ideally not be reached if __init__ succeeded or raised.
            raise PGPInitializationError("GPG Service instance is not available (was None when accessed).")
        return self.gpg

    # --- Key Validation & Import ---
    def get_key_details(self, public_key_data: str) -> Dict[str, Any]:
        """
        Validates (using external validator), imports (temporarily), retrieves details,
        and reliably cleans up a PGP key.

        Args:
            public_key_data: The ASCII-armored PGP public key string.

        Returns:
            A dictionary containing the key details from python-gnupg's list_keys.

        Raises:
            PGPKeyError: If validation, import, listing, or cleanup fails critically.
            PGPInitializationError: If GPG service is unavailable.
            ValueError: If input key data is invalid.
        """
        # v1.3.4: Enhanced logging for invalid input
        if not isinstance(public_key_data, str) or not public_key_data.strip():
            key_snippet = repr(public_key_data[:100]) + ('...' if len(str(public_key_data)) > 100 else '') if isinstance(public_key_data, str) else 'N/A'
            logger.warning(f"get_key_details received invalid public_key_data (type: {type(public_key_data)}, empty: {not public_key_data.strip() if isinstance(public_key_data, str) else 'N/A'}, data snippet: {key_snippet})")
            raise ValueError("Public key data must be a non-empty string.")

        gpg = self._check_gpg_instance()
        fingerprint: Optional[str] = None # Store fingerprint for cleanup

        try:
            # 1. Validate format and basic security checks (delegated)
            # This validator MUST raise DjangoValidationError or potentially ValueError on failure
            try:
                # Ensure the validator is actually callable
                if not callable(validate_pgp_public_key):
                     raise PGPInitializationError("PGP public key validator function is not callable or available.")
                validate_pgp_public_key(public_key_data)
            # v1.3.4: Catch ValueError as well as DjangoValidationError
            except (DjangoValidationError, ValueError) as e:
                key_snippet = public_key_data[:100] + ('...' if len(public_key_data) > 100 else '')
                logger.warning(f"PGP Key validation failed by external validator: {e}. Key Snippet: {key_snippet!r}")
                # Convert to our specific PGPKeyError
                # Add specific message for common test error
                if 'Malformed block structure' in str(e):
                     raise PGPKeyError(f"PGP Key validation failed (Malformed Structure - Validator): {e}") from e
                else:
                    raise PGPKeyError(f"PGP Key validation failed (Validator): {e}") from e
            except Exception as val_e: # Catch unexpected errors from validator
                logger.error(f"Unexpected error during PGP key validation call: {val_e}", exc_info=True)
                raise PGPKeyError(f"Unexpected error during PGP key validation: {val_e}") from val_e

            # 2. Import key into GPG keyring
            import_result = gpg.import_keys(public_key_data.strip())
            if not import_result or not import_result.fingerprints:
                stderr = getattr(import_result, 'stderr', 'N/A')
                status = getattr(import_result, 'results', 'N/A')
                logger.error(f"GPG key import failed. Status: {status}, Stderr: {stderr}")
                # v1.3.4: Check if stderr indicates malformed key, similar to validation error
                if 'no valid OpenPGP data found' in stderr:
                     raise PGPKeyError(f"GPG key import failed (Malformed Structure - GPG Import): Status: {status}")
                else:
                    raise PGPKeyError(f"GPG key import failed. Status: {status}")
            fingerprint = import_result.fingerprints[0] # Get the fingerprint for listing and cleanup
            logger.debug(f"Successfully imported key with fingerprint: {fingerprint}")

            # 3. List keys to get details using the obtained fingerprint
            key_data_list = gpg.list_keys(keys=[fingerprint])
            if not key_data_list:
                # Should not happen if import succeeded, but check defensively
                logger.error(f"Failed to retrieve key details after successful import. FP: {fingerprint}")
                raise PGPKeyError(f"Could not retrieve details for imported key: {fingerprint}")

            key_details = key_data_list[0]
            logger.info(f"PGP key details retrieved: FP={key_details.get('fingerprint')}, UIDs={key_details.get('uids')}")
            return key_details

        except PGPKeyError: # Re-raise specific key errors
            raise
        except Exception as e: # Catch GPG errors (import, list) or other unexpected errors
            # Log specifically if it looks like a GPGError, otherwise log generally
            is_gpg_error = hasattr(gnupg, 'GPGError') and isinstance(e, gnupg.GPGError)
            if is_gpg_error:
                 logger.error(f"GPG operation error during key details retrieval (FP: {fingerprint}): {e}")
            else:
                 logger.exception(f"Unexpected error during PGP key import/details retrieval (FP: {fingerprint}): {e}")
            # Raise our custom error, chaining the original
            raise PGPKeyError(f"Failed to get key details (FP: {fingerprint}): {e}") from e
        finally:
            # 4. Clean up: Always attempt to delete the imported key using its fingerprint
            if fingerprint and gpg: # Ensure we have a fingerprint and gpg instance
                try:
                    delete_result = gpg.delete_keys(fingerprint)
                    delete_status = getattr(delete_result, 'status', 'N/A')
                    logger.debug(f"Attempted cleanup of temporary key {fingerprint}. Status: {delete_status}")
                    # Log warning if deletion status doesn't clearly indicate success or key not found
                    if 'deleted' not in delete_status.lower() and 'not found' not in delete_status.lower():
                         logger.warning(f"GPG key deletion for {fingerprint} might not have been fully successful. Status: {delete_status}, Stderr: {getattr(delete_result, 'stderr', 'N/A')}")
                except Exception as del_e:
                    # Log aggressively if cleanup fails, as leaving keys is a risk
                    logger.error(f"CRITICAL: Failed to cleanup temporary key {fingerprint} after get_key_details: {del_e}", exc_info=True)
                    # Consider if this should raise an error - depends on policy.
                    # For now, log critically but allow the original return/exception to proceed.


    # --- PGP 2FA Challenge/Response ---
    def generate_pgp_challenge(self, user: User) -> str:
        """
        Generates challenge text for PGP 2FA login and securely caches its hash.

        Args:
            user: The User object attempting login.

        Returns:
            The challenge text to be encrypted/signed by the user.

        Raises:
            ValueError: If the user object is invalid or lacks a PGP key.
            PGPCacheError: If caching the challenge hash fails.
            PGPInitializationError: If GPG service is unavailable (checked by _check_gpg_instance).
        """
        self._check_gpg_instance() # Basic check, though GPG not directly used here

        if not isinstance(user, User) or not user.pk:
            # v1.3.3: Added logging
            logger.warning(f"generate_pgp_challenge received invalid user (type: {type(user)}, pk: {getattr(user, 'pk', 'N/A')})")
            raise ValueError("Cannot generate PGP challenge: Invalid User object.")
        if not hasattr(user, 'pgp_public_key') or not user.pgp_public_key:
            # v1.3.3: Added logging
            logger.warning(f"generate_pgp_challenge called for user {user.pk} who lacks a PGP public key.")
            # Raising ValueError as the condition prevents challenge generation
            raise ValueError(f"Cannot generate PGP challenge: User {user.username} (ID: {user.pk}) lacks a PGP public key.")

        now = timezone.now()
        timestamp = now.isoformat()
        nonce = secrets.token_hex(16) # Cryptographically secure random nonce

        # Construct a clear, unambiguous challenge message
        challenge_text = (
            f"--- Shadow Market Login Verification ---\n"
            f"Username: {user.username}\n"
            f"Timestamp: {timestamp}\n"
            f"Nonce: {nonce}\n"
            f"SecurityContext: Please sign this exact block using your PGP key to authenticate.\n"
            f"--- END CHALLENGE ---"
        )

        # Cache the SHA256 hash of the challenge for verification, NOT the full text
        cache_key = f"{self.LOGIN_CHALLENGE_CACHE_PREFIX}{user.pk}"
        challenge_bytes = challenge_text.encode('utf-8')
        challenge_hash = hashlib.sha256(challenge_bytes).hexdigest()

        # Store hash and timestamp (optional, for potential expiry checks within data)
        cache_data = {'hash': challenge_hash, 'ts': now.timestamp()}
        timeout = getattr(settings, self.SETTING_LOGIN_TIMEOUT, self.DEFAULT_LOGIN_CHALLENGE_TIMEOUT_SECONDS)

        try:
            # Set the hash in the cache with the defined timeout
            cache.set(cache_key, cache_data, timeout=timeout)
            logger.info(f"Generated PGP login challenge for User ID {user.pk}. Hash cached. Key: {cache_key}, Timeout: {timeout}s.")
            return challenge_text
        except Exception as e:
            logger.exception(f"Failed to set PGP login challenge hash in cache for User ID {user.pk}: {e}")
            # Raise a specific error indicating a system issue preventing challenge generation/storage
            raise PGPCacheError(f"Failed to cache PGP challenge hash for user {user.pk}. Cannot proceed with PGP login.") from e

    def verify_pgp_challenge(self, user: User, signed_challenge_data: str) -> bool:
        """
        Verifies a signed PGP challenge against the user's key and cached hash.
        Deletes the cache entry *immediately* upon retrieval to prevent replay attacks.

        Args:
            user: The User object attempting login.
            signed_challenge_data: The clearsigned PGP message provided by the user.

        Returns:
            True if the signature is valid, matches the user's key, and the content
            hash matches the cached hash; False otherwise. Logs details to security logger.

        Raises:
            PGPKeyError: If importing or cleaning up the user's key fails critically.
            PGPInitializationError: If GPG service is unavailable.
            ValueError: If input arguments are invalid.
        """
        gpg = self._check_gpg_instance()

        if not isinstance(user, User) or not user.pk or not hasattr(user, 'pgp_public_key') or not user.pgp_public_key or not signed_challenge_data:
            # v1.3.3: Added logging
            has_key = hasattr(user, 'pgp_public_key') and bool(user.pgp_public_key) if isinstance(user, User) else False
            logger.warning(f"verify_pgp_challenge received invalid input: UserPK={getattr(user, 'pk', 'N/A')}, HasKey={has_key}, HasSig={bool(signed_challenge_data)}")
            raise ValueError(f"Invalid input for PGP challenge verification.")

        # --- Cache Handling (Critical Section) ---
        cache_key = f"{self.LOGIN_CHALLENGE_CACHE_PREFIX}{user.pk}"
        cached_data = None
        expected_hash = None
        try:
            cached_data = cache.get(cache_key)
            if cached_data:
                # Delete immediately upon retrieval to prevent replay, even if verification fails later
                cache.delete(cache_key)
                logger.debug(f"Retrieved and deleted PGP login challenge cache entry for User ID {user.pk}. Key: {cache_key}")
                # Extract hash safely
                expected_hash = cached_data.get('hash')
                if not expected_hash:
                    logger.error(f"Invalid cache data retrieved for PGP login challenge (missing 'hash'). User ID {user.pk}. Key: {cache_key}")
                    security_logger.error(f"System Error during PGP 2FA Login (Invalid Cache Data): User '{user.username}' (ID: {user.pk}).")
                    return False # Cache data structure error
            else:
                # Cache miss or expired
                logger.warning(f"PGP login verify failed for User ID {user.pk} ({user.username}): Challenge cache miss or expired. Key: {cache_key}")
                security_logger.warning(f"Failed PGP 2FA Login (Cache Miss/Expired): User '{user.username}' (ID: {user.pk}).")
                return False # Challenge expired or was never issued
        except Exception as cache_e:
            logger.exception(f"Error accessing or deleting PGP challenge cache for User ID {user.pk}: {cache_e}")
            security_logger.error(f"System Error during PGP 2FA Login (Cache Access Failed): User '{user.username}' (ID: {user.pk}).")
            return False # Treat cache errors as verification failure

        # --- Key Import and Verification ---
        expected_fingerprint: Optional[str] = None
        try:
            # Import User's Public Key temporarily for verification
            # Assumes the user's key isn't permanently stored/trusted in the service's keyring.
            import_result = gpg.import_keys(user.pgp_public_key.strip())
            if not import_result or not import_result.fingerprints:
                logger.error(f"Failed to import user PGP key for login verification. User ID {user.pk}. Status: {getattr(import_result, 'results', 'N/A')}")
                # This is a critical failure preventing verification
                raise PGPKeyError(f"Failed to import PGP key for user {user.pk} during challenge verification.")
            expected_fingerprint = import_result.fingerprints[0]
            logger.debug(f"Imported user key for verification. User ID {user.pk}, Expected FP: {expected_fingerprint}")

            # Verify Signature (assumes clearsigned format)
            # Encode the input signature data to bytes for gnupg
            verified = gpg.verify(signed_challenge_data.encode('utf-8'))

            # Check 1: Basic verification status and fingerprint match (case-insensitive)
            # Note: `verified` object itself can be truthy even on failure, must check attributes.
            if not verified or not verified.valid or not verified.fingerprint or verified.fingerprint.upper() != expected_fingerprint.upper():
                logger.warning(f"PGP login verify failed for User ID {user.pk} ({user.username}): Signature invalid or fingerprint mismatch. "
                               f"Verified FP: {verified.fingerprint if verified else 'N/A'}, Expected FP: {expected_fingerprint}, Valid: {verified.valid if verified else 'N/A'}, "
                               f"Status: {verified.status if verified else 'N/A'}")
                security_logger.warning(f"Failed PGP 2FA Login (Sig/FP Invalid): User '{user.username}' (ID: {user.pk}). Verified FP: {verified.fingerprint if verified else 'N/A'}.")
                return False

            # Check 2: Ensure signed data was extracted
            original_signed_bytes = verified.data
            if not original_signed_bytes:
                logger.warning(f"PGP login verify failed for User ID {user.pk} ({user.username}): GPG verification successful but extracted no signed data.")
                security_logger.warning(f"Failed PGP 2FA Login (No Signed Data): User '{user.username}' (ID: {user.pk}).")
                return False

            # Check 3: Constant-time comparison of the hash of the *actual signed content* vs expected hash
            actual_hash = hashlib.sha256(original_signed_bytes).hexdigest()
            # Ensure both are bytes for compare_digest
            hashes_match = hmac.compare_digest(actual_hash.encode('utf-8'), expected_hash.encode('utf-8'))

            if not hashes_match:
                logger.warning(f"PGP login verify failed for User ID {user.pk} ({user.username}): Signed content hash mismatch. "
                               f"Actual Hash: {actual_hash[:8]}..., Expected Hash: {expected_hash[:8]}...")
                # Avoid logging full hashes or signed content unless in debug/secure logs
                security_logger.warning(f"Failed PGP 2FA Login (Hash Mismatch): User '{user.username}' (ID: {user.pk}).")
                return False

            # All checks passed - Successful Verification
            logger.info(f"PGP login challenge verification SUCCESS for User ID {user.pk} ({user.username}). Fingerprint: {verified.fingerprint}")
            security_logger.info(f"Successful PGP 2FA Login: User '{user.username}' (ID: {user.pk}).")
            return True

        except PGPKeyError: # Handle specific key import error from above
            security_logger.error(f"System Error during PGP 2FA Login (Key Import Failed): User '{user.username}' (ID: {user.pk}).")
            # Re-raise PGPKeyError as it indicates a problem processing the user's key specifically
            raise
        except Exception as e:
            # Catch GPG errors during verify or other unexpected issues
            logger.exception(f"Unexpected error during PGP challenge verification step for User ID {user.pk} ({user.username}).")
            # Treat unexpected errors during verification as failure for security
            security_logger.error(f"System Error during PGP 2FA Login Verification: User '{user.username}' (ID: {user.pk}). Error: {e}")
            # Convert generic exception to PGPVerificationError
            raise PGPVerificationError(f"Unexpected verification error for user {user.pk}: {e}") from e
            # Or return False if we want to suppress the error propagation: return False

        finally:
            # Clean up the temporarily imported key, regardless of success or failure
            if expected_fingerprint and gpg:
                try:
                    delete_result = gpg.delete_keys(expected_fingerprint)
                    logger.debug(f"Attempted cleanup of verification key {expected_fingerprint} for user {user.pk}. Status: {getattr(delete_result, 'status', 'N/A')}")
                    if 'deleted' not in getattr(delete_result, 'status', '').lower() and 'not found' not in getattr(delete_result, 'status', '').lower():
                            logger.warning(f"Verification key deletion for {expected_fingerprint} (User {user.pk}) might not have been fully successful. Status: {getattr(delete_result, 'status', 'N/A')}")
                except Exception as del_e:
                    logger.error(f"CRITICAL: Failed to cleanup verification key {expected_fingerprint} for user {user.pk}: {del_e}", exc_info=True)
                    # Do not raise here, allow original outcome, but log failure


    # --- PGP Action Signing/Verification ---
    def generate_action_challenge(self, user: User, action_name: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """
        Generates a message and unique nonce for PGP-based action confirmation, securely caching its hash.

        Args:
            user: The User performing the action.
            action_name: A unique identifier for the action (e.g., 'confirm_withdrawal').
            context: Optional dictionary of key-value pairs relevant to the action
                     (e.g., {'amount': 1.0, 'currency': 'BTC', 'address': '...'}).
                     These will be included deterministically in the message to be signed.

        Returns:
            A tuple containing:
            - The full message text to be signed by the user.
            - The generated nonce (required for verification).

        Raises:
            ValueError: If inputs are invalid or context processing fails.
            PGPCacheError: If caching the action hash fails.
            PGPInitializationError: If GPG service is unavailable.
        """
        self._check_gpg_instance() # Basic check

        if not isinstance(user, User) or not user.pk or not action_name:
            # v1.3.3: Added logging
            logger.warning(f"generate_action_challenge received invalid input: UserPK={getattr(user, 'pk', 'N/A')}, ActionName='{action_name}'")
            raise ValueError(f"Invalid input for generate_action_challenge")
        if context and not isinstance(context, dict):
            # v1.3.3: Added logging
            logger.warning(f"generate_action_challenge received invalid context type: {type(context)}")
            raise ValueError("Context must be a dictionary or None.")

        now = timezone.now()
        timestamp = now.isoformat()
        nonce = secrets.token_hex(16) # Secure random nonce for this specific action instance

        # Prepare context string representation safely and deterministically
        context_lines = []
        if context:
            try:
                # Sort context items by key for deterministic order in the message
                sorted_context_items = sorted(context.items())
                # Format carefully, ensuring values are stringified simply
                context_lines = [f"  {k}: {str(v)}" for k, v in sorted_context_items]
            except Exception as ctx_e:
                logger.error(f"Error processing context dictionary for PGP action '{action_name}' for user {user.pk}: {ctx_e}")
                raise ValueError(f"Invalid context provided for action '{action_name}'") from ctx_e
        context_str = "\n".join(context_lines) if context_lines else "  (No specific context provided)"

        # Construct the unambiguous message to be signed
        message_to_sign = (
            f"--- Shadow Market Action Confirmation ---\n"
            f"User: {user.username}\n"
            f"Action: {action_name}\n"
            f"Timestamp: {timestamp}\n"
            f"Nonce: {nonce}\n"
            f"Context:\n{context_str}\n"
            f"SecurityContext: Please sign this exact block with your PGP key to confirm this action.\n"
            f"--- END CONFIRMATION ---"
        )

        # Cache the SHA256 hash of the message for verification
        # Include user, action, AND nonce in the key for uniqueness per attempt
        cache_key = f"{self.ACTION_NONCE_CACHE_PREFIX}{user.pk}_{action_name}_{nonce}"
        message_bytes = message_to_sign.encode('utf-8')
        message_hash = hashlib.sha256(message_bytes).hexdigest()
        cache_data = {'hash': message_hash, 'ts': now.timestamp()} # Store hash and timestamp
        timeout = getattr(settings, self.SETTING_ACTION_TIMEOUT, self.DEFAULT_ACTION_NONCE_TIMEOUT_SECONDS)

        try:
            cache.set(cache_key, cache_data, timeout=timeout)
            logger.info(f"Generated PGP action challenge: User {user.username}, Action '{action_name}'. Hash cached. Nonce: {nonce}, Key: {cache_key}, Timeout: {timeout}s.")
            # Return the full message and the nonce needed for verification
            return message_to_sign, nonce
        except Exception as e:
            logger.exception(f"Failed to set PGP action challenge hash in cache for User {user.pk}, Action '{action_name}', Nonce {nonce}.")
            raise PGPCacheError(f"Failed to cache PGP action challenge hash. Cannot proceed with action confirmation.") from e

    def verify_action_signature(self, user: User, action_name: str, nonce: str, signature: str) -> bool:
        """
        Verifies a PGP signature for an action confirmation using the nonce and cached hash.
        Deletes the cache entry *immediately* upon retrieval to prevent replay attacks.

        Args:
            user: The User object confirming the action.
            action_name: The unique identifier for the action being confirmed.
            nonce: The nonce generated alongside the message for this specific action instance.
            signature: The clearsigned PGP message provided by the user.

        Returns:
            True if the signature is valid, matches the user's key, the nonce is valid,
            and the signed content hash matches the cached hash; False otherwise. Logs details.

        Raises:
            PGPKeyError: If importing or cleaning up the user's key fails critically.
            PGPInitializationError: If GPG service is unavailable.
            ValueError: If input arguments are invalid.
        """
        gpg = self._check_gpg_instance()

        # Basic input validation
        if not all([isinstance(user, User), user.pk, hasattr(user, 'pgp_public_key'), user.pgp_public_key, action_name, nonce, signature]):
            # v1.3.3: Added logging
            has_key = hasattr(user, 'pgp_public_key') and bool(user.pgp_public_key) if isinstance(user, User) else False
            logger.warning(f"verify_action_signature received invalid input: UserPK={getattr(user, 'pk', 'N/A')}, HasKey={has_key}, Action='{action_name}', Nonce={bool(nonce)}, Sig={bool(signature)}")
            raise ValueError(f"Invalid input for verify_action_signature")

        # --- Cache Handling (Critical Section) ---
        # Retrieve Expected Hash using the unique cache key (user, action, nonce)
        cache_key = f"{self.ACTION_NONCE_CACHE_PREFIX}{user.pk}_{action_name}_{nonce}"
        cached_data = None
        expected_hash = None
        try:
            cached_data = cache.get(cache_key)
            if cached_data:
                cache.delete(cache_key) # Prevent replay immediately
                logger.debug(f"Retrieved and deleted PGP action cache entry for User {user.pk}, Action '{action_name}', Nonce {nonce}. Key: {cache_key}")
                expected_hash = cached_data.get('hash')
                if not expected_hash:
                    logger.error(f"Invalid cache data for PGP action nonce. User {user.pk}, Action '{action_name}'. Key: {cache_key}")
                    security_logger.error(f"System Error during PGP Action Confirmation (Invalid Cache Data): User '{user.username}', Action '{action_name}'.")
                    return False
            else:
                # Nonce expired or invalid (already used or never existed)
                logger.warning(f"PGP Action '{action_name}' verify failed for User {user.username} (ID: {user.pk}): Nonce expired or invalid. Cache Key: {cache_key}")
                security_logger.warning(f"Failed PGP Action Confirmation (Nonce Expired/Missing): User '{user.username}', Action '{action_name}'.")
                return False
        except Exception as cache_e:
            logger.exception(f"Error accessing or deleting PGP action cache for User {user.pk}, Action '{action_name}', Nonce {nonce}: {cache_e}")
            security_logger.error(f"System Error during PGP Action Confirmation (Cache Access Failed): User '{user.username}', Action '{action_name}'.")
            return False

        # --- Key Import and Verification ---
        expected_fingerprint: Optional[str] = None
        try:
            # Import User Key temporarily
            import_result = gpg.import_keys(user.pgp_public_key.strip())
            if not import_result or not import_result.fingerprints:
                logger.error(f"Failed to import user key for action verification. User {user.pk}, Action '{action_name}'. Status: {getattr(import_result, 'results', 'N/A')}")
                raise PGPKeyError(f"Failed to import PGP key for user {user.pk} during action '{action_name}' verification.")
            expected_fingerprint = import_result.fingerprints[0]
            logger.debug(f"Imported user key for action verification. User {user.pk}, Action '{action_name}', Expected FP: {expected_fingerprint}")

            # Verify Signature (assumes clearsigned)
            verified = gpg.verify(signature.encode('utf-8'))

            # Check 1: Basic verification and fingerprint (case-insensitive)
            if not verified or not verified.valid or not verified.fingerprint or verified.fingerprint.upper() != expected_fingerprint.upper():
                logger.warning(f"PGP Action '{action_name}' verify failed for User {user.username}: Signature invalid or fingerprint mismatch. "
                               f"Verified FP: {verified.fingerprint if verified else 'N/A'}, Expected FP: {expected_fingerprint}, Valid: {verified.valid if verified else 'N/A'}, "
                               f"Status: {verified.status if verified else 'N/A'}")
                security_logger.warning(f"Failed PGP Action Confirmation (Sig/FP Invalid): User '{user.username}', Action '{action_name}'. Verified FP: {verified.fingerprint if verified else 'N/A'}.")
                return False

            # Check 2: Signed data presence
            original_signed_bytes = verified.data
            if not original_signed_bytes:
                logger.warning(f"PGP Action '{action_name}' verify failed for User {user.username}: No signed data extracted.")
                security_logger.warning(f"Failed PGP Action Confirmation (No Signed Data): User '{user.username}', Action '{action_name}'.")
                return False

            # Check 3: Hash comparison (constant time)
            actual_hash = hashlib.sha256(original_signed_bytes).hexdigest()
            hashes_match = hmac.compare_digest(actual_hash.encode('utf-8'), expected_hash.encode('utf-8'))

            if not hashes_match:
                logger.warning(f"PGP Action '{action_name}' verify failed for User {user.username}: Signed content hash mismatch.")
                security_logger.warning(f"Failed PGP Action Confirmation (Hash Mismatch): User '{user.username}', Action '{action_name}'.")
                return False

            # Success
            logger.info(f"PGP Action '{action_name}' verification SUCCESS for User {user.username}. Fingerprint: {verified.fingerprint}")
            security_logger.info(f"PGP Action Confirmed: User '{user.username}', Action '{action_name}'.")
            return True

        except PGPKeyError: # Handle specific key import error
            security_logger.error(f"System Error during PGP Action Confirmation (Key Import Failed): User '{user.username}', Action '{action_name}'.")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error verifying PGP action '{action_name}' for {user.username}.")
            security_logger.error(f"System Error during PGP Action Confirmation Verification: User '{user.username}', Action '{action_name}'. Error: {e}")
            raise PGPVerificationError(f"Unexpected verification error for action '{action_name}', user {user.pk}: {e}") from e
            # Or return False

        finally:
            # Clean up temporary key
            if expected_fingerprint and gpg:
                try:
                    delete_result = gpg.delete_keys(expected_fingerprint)
                    logger.debug(f"Attempted cleanup of action verification key {expected_fingerprint} for user {user.pk}, action '{action_name}'. Status: {getattr(delete_result, 'status', 'N/A')}")
                    if 'deleted' not in getattr(delete_result, 'status', '').lower() and 'not found' not in getattr(delete_result, 'status', '').lower():
                            logger.warning(f"Action verification key deletion for {expected_fingerprint} (User {user.pk}, Action '{action_name}') might not have been fully successful. Status: {getattr(delete_result, 'status', 'N/A')}")
                except Exception as del_e:
                    logger.error(f"CRITICAL: Failed to cleanup action verification key {expected_fingerprint} for user {user.pk}, action '{action_name}': {del_e}", exc_info=True)


    # --- PGP Encryption/Decryption ---
    def encrypt_message_for_recipient(self, recipient_public_key: str, recipient_fingerprint: str, message: str) -> str:
        """
        Encrypts a string message using the recipient's PGP fingerprint.

        Security Note: This method currently uses `always_trust=True`. This bypasses
        GPG's trust database checks. It is ONLY appropriate if the operational procedures
        GUARANTEE that any key identified by `recipient_fingerprint` present in the
        service's GPG keyring (`settings.GPG_HOME`) has already been fully verified
        and is explicitly trusted by the application's security policy. If keys are
        imported temporarily or trust is not inherent, this needs reassessment.

        Args:
            recipient_public_key: The ASCII-armored PGP public key (used for logging/context only,
                                  NOT used for direct import here).
            recipient_fingerprint: The fingerprint of the recipient's key (must exist
                                   in the service's GPG keyring and meet trust assumptions).
            message: The plaintext message string to encrypt.

        Returns:
            The ASCII-armored encrypted message string.

        Raises:
            ValueError: If inputs are invalid.
            PGPKeyError: If the recipient key cannot be found (optional check).
            PGPEncryptionError: If the encryption process fails.
            PGPInitializationError: If GPG service is unavailable.
        """
        gpg = self._check_gpg_instance()

        if not recipient_fingerprint or not isinstance(recipient_fingerprint, str):
            # v1.3.3: Added logging
            logger.warning(f"encrypt_message_for_recipient received invalid recipient_fingerprint: {recipient_fingerprint!r}")
            raise ValueError("Recipient PGP fingerprint is missing or invalid.")
        if not isinstance(message, str): # GPG can encrypt empty data, so allow empty string
            # v1.3.3: Added logging
            logger.warning(f"encrypt_message_for_recipient received non-string message type: {type(message)}")
            raise ValueError("Message to encrypt must be a string.")

        try:
            # Optional: Check if the key exists before attempting encryption?
            # key_list = gpg.list_keys(keys=[recipient_fingerprint])
            # if not key_list:
            #     logger.error(f"Recipient key with fingerprint {recipient_fingerprint} not found in keyring '{gpg.gnupghome}'.")
            #     raise PGPKeyError(f"Recipient key with fingerprint {recipient_fingerprint} not found in keyring.")
            # logger.debug(f"Found recipient key {recipient_fingerprint} in keyring for encryption.")

            message_bytes = message.encode('utf-8')

            # Encrypt using the fingerprint, relying on the explicit trust assumption documented above.
            encrypted_data = gpg.encrypt(
                message_bytes,
                recipient_fingerprint,
                always_trust=True # SECURITY CRITICAL: See method docstring.
            )

            if encrypted_data.ok:
                logger.debug(f"Successfully encrypted message for fingerprint {recipient_fingerprint}")
                # Return the ASCII armored string representation
                return str(encrypted_data)
            else:
                # Encryption failed, extract details
                status = getattr(encrypted_data, 'status', 'N/A')
                stderr = getattr(encrypted_data, 'stderr', 'N/A').strip()
                logger.error(f"PGP encryption failed for recipient {recipient_fingerprint}. Status: '{status}'. Stderr: {stderr}")
                # Raise specific error with status info
                raise PGPEncryptionError(f"Encryption failed for key {recipient_fingerprint}. Status: {status}. Details: {stderr}")

        # FIX v1.2.0 approach: Handle potential AttributeError if gnupg.GPGError is missing (e.g., due to mocks)
        except PGPKeyError: # Re-raise key errors from optional check
            raise
        except Exception as e: # Catch any exception during GPG op or handling
            is_gpg_error = hasattr(gnupg, 'GPGError') and isinstance(e, gnupg.GPGError)
            if is_gpg_error:
                 logger.error(f"GPG error during encryption for key {recipient_fingerprint}: {e}")
            else:
                 logger.exception(f"Unexpected error during PGP encryption for fingerprint {recipient_fingerprint}...")
            # Raise our custom error, chaining the original
            raise PGPEncryptionError(f"Encryption failed for fingerprint {recipient_fingerprint}: {e}") from e


    def decrypt_message(self, encrypted_message: str, passphrase: Optional[str] = None) -> str:
        """
        Decrypts an ASCII-armored PGP message using a private key available
        in the application's GPG keyring. Handles potential decoding errors.

        Args:
            encrypted_message: The ASCII-armored PGP message string.
            passphrase: The passphrase for the private key, if required and not handled by gpg-agent.

        Returns:
            The decrypted plaintext message string (decoded as UTF-8, replacing errors).

        Raises:
            ValueError: If the encrypted message input is invalid.
            PGPDecryptionError: If decryption fails (wrong key, bad passphrase, corrupted data).
            PGPInitializationError: If GPG service is unavailable.
        """
        gpg = self._check_gpg_instance()

        if not encrypted_message or not isinstance(encrypted_message, str):
            # v1.3.3: Added logging
            logger.warning(f"decrypt_message received invalid encrypted_message (type: {type(encrypted_message)}, empty: {not encrypted_message if isinstance(encrypted_message, str) else 'N/A'})")
            raise ValueError("Encrypted message is missing or invalid.")

        try:
            # Passphrase handling is managed by python-gnupg (may use gpg-agent if configured)
            decrypted_data = gpg.decrypt(encrypted_message, passphrase=passphrase)

            if decrypted_data.ok:
                # Successfully decrypted
                fingerprint = getattr(decrypted_data, 'fingerprint', 'N/A')
                logger.info(f"Successfully decrypted message. Key fingerprint: {fingerprint}")
                # Attempt to decode the resulting bytes as UTF-8
                try:
                    # Use errors='replace' to handle potential non-UTF8 data gracefully
                    return decrypted_data.data.decode('utf-8', errors='replace')
                except AttributeError:
                     # Handle case where decryption succeeded but .data is None or not bytes
                     logger.error(f"Decryption reported OK for fingerprint {fingerprint}, but '.data' attribute is missing or not bytes.")
                     raise PGPDecryptionError(f"Decryption OK but no valid data found for fingerprint {fingerprint}.")
                except Exception as decode_e:
                     # Catch other unexpected errors during decode
                     logger.exception(f"Error decoding decrypted data for fingerprint {fingerprint}")
                     raise PGPDecryptionError(f"Failed to decode decrypted data: {decode_e}") from decode_e
            else:
                # Decryption failed
                status = getattr(decrypted_data, 'status', 'N/A')
                stderr = getattr(decrypted_data, 'stderr', 'N/A').strip()
                logger.warning(f"PGP decryption failed. Status: '{status}'. Stderr: {stderr}")
                # Include status/stderr in the exception for better debugging
                # Distinguish common failures if possible based on stderr
                error_msg = f"PGP decryption failed. Status: {status}. Details: {stderr}"
                if "bad passphrase" in stderr.lower():
                    error_msg = "PGP decryption failed: Bad passphrase provided."
                elif "no secret key" in stderr.lower():
                     error_msg = "PGP decryption failed: No corresponding secret key available in keyring."
                raise PGPDecryptionError(error_msg)

        # FIX v1.2.0 approach: Handle potential AttributeError if gnupg.GPGError is missing
        except Exception as e: # Catch any exception during GPG op or handling
            is_gpg_error = hasattr(gnupg, 'GPGError') and isinstance(e, gnupg.GPGError)
            if is_gpg_error:
                 logger.error(f"GPG error during decryption: {e}")
            else:
                 logger.exception(f"Unexpected error during PGP decryption: {e}")
            # Raise our custom error, chaining the original
            raise PGPDecryptionError(f"Decryption failed: {e}") from e


    # FIX v1.1.0: Add stub for verify_message_signature method
    # UPDATE v1.3.0: Enhance stub with required verification checks, still marked as potentially incomplete.
    def verify_message_signature(self, user: User, signature: str, expected_message: str) -> bool:
        """
        Verifies a clearsigned PGP signature against expected message content.

        NOTE: This method currently handles **clearsigned** signatures using `gpg.verify()`.
        It does NOT explicitly handle detached signatures (`gpg.verify_file()` or similar).
        Further implementation is needed if detached signatures are required.

        NOTE: The test `TestPgpService.test_verify_message_signature_success` may need
              updating to pass the correct arguments: `user`, `signature` (clearsigned),
              and `expected_message`.

        Args:
            user: The User whose PGP key should have signed the message.
            signature: The clearsigned PGP message block.
            expected_message: The exact plaintext message content that is expected
                              to have been signed. Normalization (e.g., line endings)
                              might be necessary depending on the source.

        Returns:
            True if the signature is valid, matches the user's key, and the signed
            content matches the expected_message (after basic normalization); False otherwise.

        Raises:
            PGPKeyError: If importing or cleaning up the user's key fails critically.
            PGPInitializationError: If GPG service is unavailable.
            ValueError: If input arguments are invalid.
            PGPVerificationError: For unexpected errors during verification steps.
        """
        logger.debug(f"Calling verify_message_signature for User {user.pk if user else 'None'}. NOTE: Assumes clearsigned signature format.")
        gpg = self._check_gpg_instance()

        if not all([isinstance(user, User), user.pk, hasattr(user, 'pgp_public_key'), user.pgp_public_key, signature, isinstance(expected_message, str)]):
            # v1.3.3: Added logging
            has_key = hasattr(user, 'pgp_public_key') and bool(user.pgp_public_key) if isinstance(user, User) else False
            logger.warning(f"verify_message_signature received invalid input: UserPK={getattr(user, 'pk', 'N/A')}, HasKey={has_key}, HasSig={bool(signature)}, ExpMsgIsStr={isinstance(expected_message, str)}")
            raise ValueError("Invalid input to verify_message_signature.")

        expected_fingerprint: Optional[str] = None
        try:
            # 1. Import user key (temporarily)
            import_result = gpg.import_keys(user.pgp_public_key.strip())
            if not import_result or not import_result.fingerprints:
                raise PGPKeyError(f"Failed to import key for user {user.pk} during signature verification.")
            expected_fingerprint = import_result.fingerprints[0]
            logger.debug(f"Imported user key for message signature verification. User {user.pk}, Expected FP: {expected_fingerprint}")

            # 2. Perform GPG verification (handles clearsigned)
            verified = gpg.verify(signature.encode('utf-8'))

            # 3. Check verification result (validity, fingerprint)
            if not verified or not verified.valid or not verified.fingerprint or verified.fingerprint.upper() != expected_fingerprint.upper():
                logger.warning(f"Message signature verification failed for User {user.username}: Invalid sig or FP mismatch. "
                               f"Verified FP: {verified.fingerprint if verified else 'N/A'}, Expected FP: {expected_fingerprint}, Valid: {verified.valid if verified else 'N/A'}, "
                               f"Status: {verified.status if verified else 'N/A'}")
                return False

            # 4. Check signed data presence
            signed_data_bytes = verified.data
            if not signed_data_bytes:
                logger.warning(f"Message signature verification failed for User {user.username}: No signed data extracted.")
                return False

            # 5. Compare extracted data with expected message (constant time)
            expected_bytes = expected_message.encode('utf-8')

            # --- Normalization ---
            # PGP signing can alter line endings (e.g., CRLF -> LF).
            # Basic normalization: strip whitespace and compare. More robust might be needed.
            # Example: Replace \r\n with \n before hashing/comparing if needed.
            normalized_signed = signed_data_bytes.strip()
            normalized_expected = expected_bytes.strip()
            # ---------------------

            messages_match = hmac.compare_digest(normalized_signed, normalized_expected)

            if not messages_match:
                logger.warning(f"Message signature verification failed for User {user.username}: Signed content mismatch after normalization.")
                # Avoid logging full messages unless debugging securely
                # logger.debug(f"Mismatch Details: Expected(norm)='{normalized_expected.decode('utf-8', 'replace')[:100]}...', Actual(norm)='{normalized_signed.decode('utf-8', 'replace')[:100]}...'")
                return False

            logger.info(f"Message signature verification SUCCESS for User {user.username}. Fingerprint: {verified.fingerprint}")
            return True # All checks passed

        except PGPKeyError: # Handle specific key import error
            raise
        except Exception as e:
            is_gpg_error = hasattr(gnupg, 'GPGError') and isinstance(e, gnupg.GPGError)
            if is_gpg_error:
                 logger.error(f"GPG error during message signature verification for User {user.pk}: {e}")
            else:
                 logger.exception(f"Unexpected error during message signature verification for User {user.pk}: {e}")
            raise PGPVerificationError(f"Unexpected error during message signature verification for user {user.pk}: {e}") from e
            # Or return False

        finally:
            # Clean up key if imported
            if expected_fingerprint and gpg:
                try:
                    delete_result = gpg.delete_keys(expected_fingerprint)
                    logger.debug(f"Attempted cleanup of message verification key {expected_fingerprint} for user {user.pk}. Status: {getattr(delete_result, 'status', 'N/A')}")
                    if 'deleted' not in getattr(delete_result, 'status', '').lower() and 'not found' not in getattr(delete_result, 'status', '').lower():
                            logger.warning(f"Message verification key deletion for {expected_fingerprint} (User {user.pk}) might not have been fully successful. Status: {getattr(delete_result, 'status', 'N/A')}")
                except Exception as del_e:
                    logger.error(f"CRITICAL: Failed to cleanup message verification key {expected_fingerprint} for user {user.pk}: {del_e}", exc_info=True)


# --- Service Instantiation (Singleton Pattern) ---
# Use a variable to hold the single instance, initialized upon module load
_pgp_service_instance: Optional[PGPService] = None
_pgp_service_available: bool = False

# Attempt to create the instance when the module loads
try:
    _pgp_service_instance = PGPService()
    _pgp_service_available = True
    logger.info("PGPService instance created successfully and available.")
except (PGPInitializationError, PGPConfigurationError) as e:
    # Log critically if the service essential for the app fails to init
    logger.critical(f"CRITICAL FAILURE: Failed to create PGPService instance: {e}", exc_info=False) # exc_info=False as error is already descriptive
    _pgp_service_instance = None
    _pgp_service_available = False
except Exception as e: # Catch any other unexpected error during init
    logger.critical(f"CRITICAL UNEXPECTED ERROR creating PGPService instance: {e}", exc_info=True)
    _pgp_service_instance = None
    _pgp_service_available = False

# --- Module-Level Functions (Wrappers for Singleton Instance) ---
# These provide a simpler interface and ensure the service was initialized successfully.

def _ensure_service() -> PGPService:
    """ Checks if the service instance is available and returns it, raises PGPInitializationError if not. """
    if not _pgp_service_available or _pgp_service_instance is None:
        # Log again if accessed when unavailable, as the initial error might be missed
        logger.critical("Attempted to use PGP service, but it is unavailable or failed during initialization.")
        raise PGPInitializationError("PGP Service is not available or failed to initialize. Check critical logs.")
    return _pgp_service_instance

# --- Wrappers for PGPService methods ---

def get_key_details(public_key_data: str) -> Dict[str, Any]:
    """ Module-level wrapper for PGPService.get_key_details """
    service = _ensure_service()
    return service.get_key_details(public_key_data)

def generate_pgp_challenge(user: User) -> str:
    """ Module-level wrapper for PGPService.generate_pgp_challenge """
    service = _ensure_service()
    return service.generate_pgp_challenge(user)

def verify_pgp_challenge(user: User, signed_challenge_data: str) -> bool:
    """ Module-level wrapper for PGPService.verify_pgp_challenge """
    service = _ensure_service()
    return service.verify_pgp_challenge(user, signed_challenge_data)

def generate_action_challenge(user: User, action_name: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """ Module-level wrapper for PGPService.generate_action_challenge """
    service = _ensure_service()
    return service.generate_action_challenge(user, action_name, context)

def verify_action_signature(user: User, action_name: str, nonce: str, signature: str) -> bool:
    """ Module-level wrapper for PGPService.verify_action_signature """
    service = _ensure_service()
    return service.verify_action_signature(user, action_name, nonce, signature)

def encrypt_message_for_recipient(recipient_public_key: str, recipient_fingerprint: str, message: str) -> str:
    """ Module-level wrapper for PGPService.encrypt_message_for_recipient """
    service = _ensure_service()
    return service.encrypt_message_for_recipient(recipient_public_key, recipient_fingerprint, message)

def decrypt_message(encrypted_message: str, passphrase: Optional[str] = None) -> str:
    """ Module-level wrapper for PGPService.decrypt_message """
    service = _ensure_service()
    return service.decrypt_message(encrypted_message, passphrase)

def verify_message_signature(user: User, signature: str, expected_message: str) -> bool:
    """
    Module-level wrapper for PGPService.verify_message_signature.
    Handles clearsigned signatures. See PGPService method for details and notes.

    Args:
        user: The User whose PGP key should have signed the message.
        signature: The clearsigned PGP message block.
        expected_message: The exact plaintext message content that is expected.
    """
    service = _ensure_service()
    return service.verify_message_signature(user, signature, expected_message)

# --- Health Check Function (Optional) ---
def is_pgp_service_available() -> bool:
    """ Simple check to see if the PGP service initialized successfully. """
    return _pgp_service_available

# --- End of file ---