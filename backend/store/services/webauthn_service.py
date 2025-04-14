# shadow_market/backend/store/services/webauthn_service.py
# Revision History:
# 2025-04-13 - v1.6 (Current - Gemini):
#   - FIXED: Removed import and usage of non-existent 'ChallengeMismatchError' from webauthn.helpers.exceptions (compatible with webauthn-python >= 2.0).
# 2025-04-06 - v1.5:
#   - FIXED: Removed import of non-existent 'InvalidAuthenticationResponseError' from webauthn.helpers.exceptions (compatible with webauthn-python >= 2.0).
# 2025-04-06 - v1.4:
#   - FIXED: Removed extraneous Markdown formatting characters accidentally included in v1.3.
# 2025-04-06 - v1.3:
#   - FIXED: Removed import of non-existent 'InvalidRegistrationResponseError' from webauthn.helpers.exceptions (compatible with webauthn-python >= 2.0).
# 2025-04-06 - v1.2: Corrected import location for response/option structs (WebAuthnRegistrationResponse, etc.) - moved to webauthn.helpers.structs in webauthn>=2.0.
# 2025-04-06 - v1.1: Corrected import location for bytes_to_base64url (moved to webauthn.helpers in webauthn>=2.0). Fixes ImportError during Django startup.
# 202x-xx-xx - v1.0: Initial consolidated version.
# --- CONSOLIDATED AND ENHANCED FILE ---
# REASON: Merged class-based structure, improved error handling, config management,
# and unique challenge IDs from the first provided version with the implemented
# database ORM logic from the second version. Added recommendations for further
# improvement (Repository Pattern).

import json
import logging
import secrets
from typing import List, Optional, Dict, Any, Final, cast
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db import transaction, IntegrityError
from django.utils import timezone

# --- WebAuthn Library Imports (Corrected v1.1, v1.2, v1.3, v1.5, v1.6) ---
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
    base64url_to_bytes,
    # bytes_to_base64url, # REMOVED from here (v1.1)
    # WebAuthnRegistrationResponse, # REMOVED from here (v1.2)
    # WebAuthnAuthenticationResponse, # REMOVED from here (v1.2)
    # PublicKeyCredentialCreationOptions, # REMOVED from here (v1.2)
    # PublicKeyCredentialRequestOptions, # REMOVED from here (v1.2)
)
# Import helpers separately
from webauthn.helpers import bytes_to_base64url # ADDED HERE (v1.1)
from webauthn.helpers.exceptions import (
    # InvalidRegistrationResponseError, # <<< REMOVED HERE (v1.3) - Does not exist in webauthn>=2.0
    # InvalidAuthenticationResponseError, # <<< REMOVED HERE (v1.5) - Does not exist in webauthn>=2.0
    # ChallengeMismatchError, # <<< REMOVED HERE (v1.6) - Does not exist in webauthn>=2.0
    OriginMismatchError,
    RpIdMismatchError,
    UserVerificationRequiredError,
    InvalidDataError, # Added for more specific error catching
    WebAuthnException, # Base WebAuthn library exception
    # --- Consider adding other specific exceptions if needed by error handling logic ---
    RegistrationRejectedError, # Exists in v2.0+
    AuthenticationRejectedError, # Exists in v2.0+
    InvalidAttestationStatementError, # Exists in v2.0+
    InvalidAuthenticatorDataError, # Exists in v2.0+
    InvalidClientDataError, # Exists in v2.0+
)
# Import structs including response/option types
from webauthn.helpers.structs import (
    RegistrationCredential,
    AuthenticationCredential,
    PublicKeyCredentialDescriptor,
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    AttestationConveyancePreference,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    PublicKeyCredentialParameters,
    PublicKeyCredentialType,
    COSEAlgorithmIdentifier,
    # --- Added Struct Imports (v1.2) ---
    WebAuthnRegistrationResponse,
    WebAuthnAuthenticationResponse,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialRequestOptions,
    # --- End Added Struct Imports ---
)
# --- End WebAuthn Library Imports ---


# --- Model Imports ---
# CRITICAL: Ensure these models exist and match your project structure.
try:
    # Adjust the path '.models' based on the actual location relative to this file
    from ..models import User, WebAuthnCredential
except ImportError:
    # Provide a meaningful error or placeholder if models aren't found during initial setup
    # This prevents runtime errors if models aren't created yet but allows linting/type checking.
    # In a real deployment, these models MUST exist.
    logging.error("Could not import User or WebAuthnCredential models from ..models. "
                  "Ensure these models are defined and accessible.")
    # Define dummy types for type hinting if needed, or raise configuration error
    from django.contrib.auth.models import AbstractBaseUser as User # Placeholder type
    class WebAuthnCredential: pass # Placeholder type
    # raise ImportError("WebAuthn models not found. Please define User and WebAuthnCredential.")


logger = logging.getLogger(__name__)
security_logger = logging.getLogger('django.security') # For security-sensitive events

# --- Custom Exceptions for clearer error signaling ---
class WebAuthnServiceError(Exception):
    """Base exception for WebAuthn service errors."""
    pass

class WebAuthnConfigurationError(WebAuthnServiceError):
    """Indicates a configuration problem."""
    pass

class ChallengeNotFoundError(WebAuthnServiceError):
    """Indicates the expected challenge was not found or expired."""
    pass

class CredentialNotFoundError(WebAuthnServiceError):
    """Indicates a WebAuthn credential was not found for the user."""
    pass

class VerificationError(WebAuthnServiceError):
    """Indicates a failure during cryptographic verification."""
    pass

class UserNotFoundError(WebAuthnServiceError):
    """Indicates the user associated with a credential or handle was not found."""
    pass

class DatabaseError(WebAuthnServiceError):
    """Indicates an underlying database operation failed."""
    pass

class DuplicateCredentialError(WebAuthnServiceError):
    """Indicates an attempt to register an already existing credential ID."""
    pass


# --- Constants and Configuration ---
DEFAULT_CHALLENGE_TIMEOUT_SECONDS: Final[int] = 5 * 60  # 5 minutes
DEFAULT_WEBAUTHN_TIMEOUT_MS: Final[int] = 60 * 1000 # 60 seconds for user interaction

# Recommended public key credential parameters (include common algorithms)
PUB_KEY_CRED_PARAMS: Final[List[PublicKeyCredentialParameters]] = [
    PublicKeyCredentialParameters(
        type=PublicKeyCredentialType.PUBLIC_KEY,
        alg=COSEAlgorithmIdentifier.ES256, # ECDSA w/ SHA-256 (most common)
    ),
    PublicKeyCredentialParameters(
        type=PublicKeyCredentialType.PUBLIC_KEY,
        alg=COSEAlgorithmIdentifier.RS256, # RSA w/ SHA-256
    ),
    PublicKeyCredentialParameters(
        type=PublicKeyCredentialType.PUBLIC_KEY,
        alg=COSEAlgorithmIdentifier.EDDSA, # EdDSA on Curve Ed25519 (increasingly common)
    ),
    # Consider adding PS256 if needed, though less common
    # PublicKeyCredentialParameters(
    #     type=PublicKeyCredentialType.PUBLIC_KEY,
    #     alg=COSEAlgorithmIdentifier.PS256, # RSA PSS w/ SHA-256
    # ),
]

# --- Database Interaction Layer ---
# RECOMMENDED: For larger applications, extract these database functions into a
# dedicated 'WebAuthnCredentialRepository' class and inject it into WebAuthnService.
# This improves separation of concerns and testability. For simplicity in this example,
# they are included as private methods within the service class.

class WebAuthnService:
    """
    Provides methods for handling WebAuthn registration and authentication ceremonies.

    Requires configuration via Django settings:
    - WEBAUTHN_RP_ID: The Relying Party ID (e.g., 'yourdomain.com')
    - WEBAUTHN_RP_NAME: The Relying Party name (e.g., 'My Awesome App')
    - WEBAUTHN_EXPECTED_ORIGIN: The expected origin of the request (e.g., 'https://yourdomain.com')
    Optional settings:
    - WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS: Cache timeout for challenges (default: 300)
    - WEBAUTHN_AUTHENTICATOR_SELECTION: Dict to override authenticator selection criteria.
    - WEBAUTHN_ATTESTATION_PREFERENCE: Override attestation preference (default: 'none')
    - WEBAUTHN_USER_VERIFICATION_REQUIREMENT: Override user verification requirement (default: 'preferred')
    - WEBAUTHN_RESIDENT_KEY_REQUIREMENT: Override resident key requirement (default: 'preferred')
    - WEBAUTHN_TIMEOUT_MS: Timeout for user interaction during ceremony (default: 60000)

    Requires the following models to be defined:
    - `User` (Your Django user model, needs a UUID primary key ideally)
    - `WebAuthnCredential` (Stores credential data, see model definition recommendations)
    """

    def __init__(self):
        # Load configuration from Django settings
        self.rp_id: Optional[str] = getattr(settings, 'WEBAUTHN_RP_ID', None)
        self.rp_name: Optional[str] = getattr(settings, 'WEBAUTHN_RP_NAME', None)
        self.expected_origin: Optional[str] = getattr(settings, 'WEBAUTHN_EXPECTED_ORIGIN', None)
        self.challenge_timeout_seconds: int = getattr(settings, 'WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS', DEFAULT_CHALLENGE_TIMEOUT_SECONDS)
        self.webauthn_timeout_ms: int = getattr(settings, 'WEBAUTHN_TIMEOUT_MS', DEFAULT_WEBAUTHN_TIMEOUT_MS)

        # Validate essential configuration
        if not all([self.rp_id, self.rp_name, self.expected_origin]):
            logger.critical("WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, or WEBAUTHN_EXPECTED_ORIGIN missing in settings.")
            raise WebAuthnConfigurationError("WebAuthn Relying Party information is not fully configured in settings.")

        # Configure authenticator selection criteria with overrides from settings
        # Default to preferring user verification and resident keys, allowing any attachment type.
        default_selection = {
            'authenticator_attachment': None, # Allow platform or cross-platform
            'resident_key': getattr(settings, 'WEBAUTHN_RESIDENT_KEY_REQUIREMENT', ResidentKeyRequirement.PREFERRED), # Use Enum here
            'require_resident_key': getattr(settings, 'WEBAUTHN_REQUIRE_RESIDENT_KEY', None), # Allow explicit override, None uses library default
            'user_verification': getattr(settings, 'WEBAUTHN_USER_VERIFICATION_REQUIREMENT', UserVerificationRequirement.PREFERRED), # Use Enum here
        }
        selection_overrides = getattr(settings, 'WEBAUTHN_AUTHENTICATOR_SELECTION', {})
        # Ensure overrides use Enum types if provided as strings
        for key, value in selection_overrides.items():
            if key == 'resident_key' and isinstance(value, str):
                try:
                    selection_overrides[key] = ResidentKeyRequirement(value)
                except ValueError:
                    logger.warning(f"Invalid value '{value}' for WEBAUTHN_AUTHENTICATOR_SELECTION['resident_key']. Using default.")
                    selection_overrides[key] = default_selection['resident_key'] # Fallback
            elif key == 'user_verification' and isinstance(value, str):
                try:
                    selection_overrides[key] = UserVerificationRequirement(value)
                except ValueError:
                    logger.warning(f"Invalid value '{value}' for WEBAUTHN_AUTHENTICATOR_SELECTION['user_verification']. Using default.")
                    selection_overrides[key] = default_selection['user_verification'] # Fallback
            # Add other potential enum conversions if needed

        # Prepare config dict ensuring correct types (use Enum values where applicable)
        selection_config_dict = {
            'authenticator_attachment': selection_overrides.get('authenticator_attachment', default_selection['authenticator_attachment']),
            'resident_key': selection_overrides.get('resident_key', default_selection['resident_key']).value, # Use enum value
            'require_resident_key': selection_overrides.get('require_resident_key', default_selection['require_resident_key']),
            'user_verification': selection_overrides.get('user_verification', default_selection['user_verification']).value, # Use enum value
        }

        # Filter out None values for require_resident_key if not explicitly set
        if selection_config_dict['require_resident_key'] is None:
            del selection_config_dict['require_resident_key']

        # Filter dictionary to only valid AuthenticatorSelectionCriteria keys before instantiation
        valid_keys = AuthenticatorSelectionCriteria.__annotations__.keys()
        filtered_config_dict = {k: v for k, v in selection_config_dict.items() if k in valid_keys}

        try:
            self.authenticator_selection = AuthenticatorSelectionCriteria(**filtered_config_dict)
        except TypeError as e:
            logger.error(f"Invalid configuration for WEBAUTHN_AUTHENTICATOR_SELECTION: {filtered_config_dict}. Error: {e}")
            raise WebAuthnConfigurationError(f"Invalid WEBAUTHN_AUTHENTICATOR_SELECTION settings: {e}")

        # Configure attestation preference (Default to 'none' for privacy)
        attestation_pref_setting = getattr(settings, 'WEBAUTHN_ATTESTATION_PREFERENCE', AttestationConveyancePreference.NONE)
        if isinstance(attestation_pref_setting, str):
            try:
                self.attestation_preference = AttestationConveyancePreference(attestation_pref_setting)
            except ValueError:
                logger.warning(f"Invalid WEBAUTHN_ATTESTATION_PREFERENCE value '{attestation_pref_setting}', falling back to 'none'.")
                self.attestation_preference = AttestationConveyancePreference.NONE
        elif isinstance(attestation_pref_setting, AttestationConveyancePreference):
            self.attestation_preference = attestation_pref_setting
        else:
            logger.warning(f"Unexpected type for WEBAUTHN_ATTESTATION_PREFERENCE: {type(attestation_pref_setting)}, falling back to 'none'.")
            self.attestation_preference = AttestationConveyancePreference.NONE


        # TODO: If implementing Repository Pattern, instantiate it here:
        # self.credential_repo = WebAuthnCredentialRepository()


    # --- Private Helper Methods ---

    def _generate_cache_key(self, prefix: str, user_id: Optional[UUID] = None, challenge_id: Optional[str] = None) -> str:
        """Generates a unique cache key for challenges."""
        # Use a consistent format and include necessary identifiers
        key_parts = ["webauthn", prefix]
        # Use specific identifiers if provided, otherwise use placeholders for clarity
        key_parts.append(str(user_id) if user_id else "discoverable")
        key_parts.append(challenge_id if challenge_id else "no_challenge_id")

        # Defensive check: ensure challenge_id is present when expected
        if not challenge_id:
            logger.error("_generate_cache_key called without challenge_id where expected (prefix: %s)", prefix)

        return ":".join(key_parts)


    def _generate_user_handle(self, user_id: UUID) -> bytes:
        """
        Generates the user handle (user.id in RP terms) for WebAuthn operations.
        MUST be stable and unique per user. Using the user's UUID is recommended.
        Encode consistently (e.g., UTF-8).
        """
        # Use the string representation of the UUID, encoded to bytes.
        return str(user_id).encode('utf-8')

    def _decode_user_handle(self, user_handle_bytes: bytes) -> UUID:
        """Decodes the user handle bytes back to a UUID."""
        try:
            user_id_str = user_handle_bytes.decode('utf-8')
            return UUID(user_id_str)
        except (UnicodeDecodeError, ValueError, TypeError) as e: # Added TypeError
            logger.error(f"Failed to decode user handle bytes: {user_handle_bytes!r}. Error: {e}", exc_info=True)
            raise VerificationError("Invalid user handle format received.") from e

    # --- Database Interaction Methods (Integrated from File 2) ---
    # RECOMMENDED: Move these to a separate Repository class

    def _db_get_user_credentials(self, user_id: UUID) -> List[RegistrationCredential]:
        """
        Retrieve stored WebAuthn credentials for a user from the database.
        """
        logger.debug(f"Database: Fetching credentials for user {user_id}")
        try:
            # Ensure you have an index on user_id in WebAuthnCredential model
            credentials_qs = WebAuthnCredential.objects.filter(user_id=user_id)
            output: List[RegistrationCredential] = []
            for cred in credentials_qs:
                try:
                    # Convert stored base64url strings back to bytes for the library
                    credential_id_bytes = base64url_to_bytes(cred.credential_id_b64)
                    public_key_bytes = base64url_to_bytes(cred.public_key_b64)
                    # Parse transports string back into list, handle None or empty string
                    transports_list: Optional[List[str]] = cred.transports.split(',') if cred.transports else None

                    output.append(
                        RegistrationCredential(
                            credential_id=credential_id_bytes,
                            public_key=public_key_bytes,
                            sign_count=cred.sign_count,
                            transports=transports_list,
                            # Add other fields if the library uses them and you store them
                            # e.g., attestation info, is_uv_initialized, etc.
                        )
                    )
                except (ValueError, TypeError) as conv_err:
                    # Log conversion errors for specific credentials but continue processing others
                    logger.error(f"Database: Error converting stored credential {getattr(cred, 'id', 'N/A')} (DB PK) "
                                 f"for user {user_id}: {conv_err}", exc_info=True) # Safer access to cred.id
            logger.debug(f"Database: Found {len(output)} valid credentials for user {user_id}")
            return output
        except Exception as e:
            logger.exception(f"Database: Unhandled error retrieving WebAuthn credentials for user {user_id}: {e}")
            # Raise a specific DB error instead of returning empty list
            raise DatabaseError(f"Failed to retrieve credentials for user {user_id}") from e


    def _db_save_user_credential(self, user_id: UUID, reg_cred: RegistrationCredential) -> None:
        """
        Save a new WebAuthn credential for a user to the database.
        Raises UserNotFoundError, DuplicateCredentialError, DatabaseError on failure.
        """
        # Use the b64 version of the ID for logging and storage
        credential_id_b64 = bytes_to_base64url(reg_cred.credential_id)
        public_key_b64 = bytes_to_base64url(reg_cred.public_key)

        logger.debug(f"Database: Attempting to save credential {credential_id_b64} for user {user_id}")
        try:
            # Use select_for_update if concerned about race conditions finding the user,
            # although creating the credential itself should be atomic if credential_id_b64 is unique.
            user = User.objects.get(id=user_id)

            # Convert transports list to comma-separated string for storage (adjust if using JSONField)
            transports_str = ",".join(reg_cred.transports) if reg_cred.transports else ""

            # Create the credential within a transaction for atomicity
            with transaction.atomic():
                # The WebAuthnCredential model should enforce uniqueness on credential_id_b64
                new_credential = WebAuthnCredential.objects.create(
                    user=user,
                    credential_id_b64=credential_id_b64, # Store b64 representation
                    public_key_b64=public_key_b64, # Store b64 representation
                    sign_count=reg_cred.sign_count,
                    transports=transports_str,
                    # Consider adding a default 'nickname' or prompting user later
                    # nickname=f"Authenticator added {timezone.now().strftime('%Y-%m-%d')}"
                )
                logger.info(f"Database: Successfully saved credential {credential_id_b64} "
                            f"(DB PK: {new_credential.pk}) for user {user_id}")

        except User.DoesNotExist:
            logger.error(f"Database: Cannot save credential, user with ID {user_id} does not exist.")
            raise UserNotFoundError(f"User {user_id} not found.")
        except IntegrityError as e:
            # This likely means the unique constraint on credential_id_b64 was violated
            if 'unique constraint' in str(e).lower() and ('credential_id_b64' in str(e).lower() or 'webauthncredential_credential_id_b64' in str(e).lower()): # More robust check
                logger.warning(f"Database: Attempted to save duplicate WebAuthn credential ID "
                               f"{credential_id_b64} for user {user_id}.")
                raise DuplicateCredentialError(f"Credential ID {credential_id_b64} already exists.")
            else:
                logger.exception(f"Database: Integrity error saving credential for user {user_id}: {e}")
                raise DatabaseError(f"Could not save credential due to database integrity constraint.") from e
        except Exception as e:
            logger.exception(f"Database: Unhandled error saving WebAuthn credential for user {user_id}: {e}")
            raise DatabaseError(f"Could not save credential for user {user_id}.") from e


    def _db_update_credential_sign_count(self, user_id: UUID, credential_id_b64: str, new_sign_count: int) -> bool:
        """
        Atomically update the sign count and last used timestamp for a specific credential.
        Uses select_for_update to prevent race conditions if multiple auth attempts happen concurrently.
        Returns True on successful update, False if credential not found for the user.
        Raises DatabaseError for other DB issues.
        """
        logger.debug(f"Database: Updating sign count for credential {credential_id_b64} user {user_id} to {new_sign_count}")
        try:
            with transaction.atomic():
                # Lock the row to prevent race conditions on sign count update
                credential = WebAuthnCredential.objects.select_for_update().filter(
                    user_id=user_id,
                    credential_id_b64=credential_id_b64
                ).first() # Use .first() instead of .get() to handle not found gracefully

                if credential:
                    # Optional: Add a check here if needed: if new_sign_count <= credential.sign_count: log warning/error?
                    # The webauthn library's verify function already handles the core sign count check.
                    # This DB update confirms it.
                    credential.sign_count = new_sign_count
                    credential.last_used_at = timezone.now()
                    credential.save(update_fields=['sign_count', 'last_used_at'])
                    logger.debug(f"Database: Successfully updated sign count for credential {credential_id_b64} user {user_id}")
                    return True
                else:
                    # Credential not found for this user
                    logger.warning(f"Database: Could not find credential {credential_id_b64} for user {user_id} to update sign count.")
                    return False # Indicate not found

        except Exception as e:
            logger.exception(f"Database: Error updating sign count for credential {credential_id_b64}, user {user_id}: {e}")
            raise DatabaseError(f"Failed to update sign count for credential {credential_id_b64}.") from e


    def _db_find_user_id_by_credential_id(self, credential_id_b64: str) -> Optional[UUID]:
        """
        Finds the user ID associated with a given credential ID (b64url encoded).
        Required for non-discoverable credential authentication flows.
        """
        logger.debug(f"Database: Looking up user by credential ID {credential_id_b64}")
        try:
            # Optimize to fetch only the user_id field. Add index on credential_id_b64.
            # Using filter().first() is safer than get() against MultipleObjectsReturned
            credential = WebAuthnCredential.objects.filter(
                credential_id_b64=credential_id_b64
            ).only('user_id').first()

            if credential:
                user_id = cast(UUID, credential.user_id) # Cast because only() might return proxy
                logger.debug(f"Database: Found user {user_id} for credential {credential_id_b64}")
                return user_id
            else:
                logger.warning(f"Database: No user found associated with credential ID: {credential_id_b64}")
                return None

        except MultipleObjectsReturned:
            # This indicates a serious data integrity issue, as credential_id_b64 should be unique.
            logger.critical(f"CRITICAL: Database integrity error! Multiple users found for WebAuthn credential ID: {credential_id_b64}.")
            # Depending on policy, you might raise an error or return None. Returning None is safer initially.
            return None
        except Exception as e:
            logger.exception(f"Database: Error looking up user by credential ID {credential_id_b64}: {e}")
            raise DatabaseError(f"Failed to look up user by credential ID {credential_id_b64}.") from e


    def _db_remove_credential(self, user_id: UUID, credential_id_b64: str) -> bool:
        """
        Removes a specific WebAuthn credential for a user.
        Returns True if deleted, False otherwise (not found or error).
        Raises DatabaseError for DB issues.
        """
        logger.debug(f"Database: Attempting to remove credential {credential_id_b64} for user {user_id}")
        try:
            with transaction.atomic():
                deleted_count, _ = WebAuthnCredential.objects.filter(
                    user_id=user_id,
                    credential_id_b64=credential_id_b64
                ).delete()

            if deleted_count > 0:
                logger.info(f"Database: Successfully removed credential {credential_id_b64} for user {user_id}")
                return True
            else:
                logger.warning(f"Database: Attempted to remove non-existent credential {credential_id_b64} for user {user_id}")
                return False
        except Exception as e:
            logger.exception(f"Database: Error removing WebAuthn credential {credential_id_b64} for user {user_id}: {e}")
            raise DatabaseError(f"Failed to remove credential {credential_id_b64}.") from e


    def _db_get_user_credentials_info(self, user_id: UUID) -> List[Dict[str, Any]]:
        """
        Returns basic, non-sensitive info about a user's registered credentials
        (e.g., for display in profile settings).
        Raises DatabaseError for DB issues.
        """
        logger.debug(f"Database: Fetching credential info list for user {user_id}")
        try:
            # Select only necessary, non-sensitive fields for display
            # Add index on user_id and created_at for performance if needed
            # Ensure your model actually has these fields!
            credentials_qs = WebAuthnCredential.objects.filter(user_id=user_id).only(
                'pk', # Assuming UUID primary key
                'credential_id_b64',
                'nickname',
                'created_at',
                'last_used_at',
                'transports'
            ).order_by('-created_at') # Show newest first

            # Format the output slightly for frontend consumption
            return [
                {
                    "id": str(cred.pk), # Use the model's primary key (UUID) as string
                    "credential_id": cred.credential_id_b64, # The actual WebAuthn ID (b64)
                    "nickname": cred.nickname or 'Unnamed Authenticator', # Provide default
                    "added_on": cred.created_at.isoformat() if cred.created_at else None,
                    "last_used": cred.last_used_at.isoformat() if cred.last_used_at else None,
                    "transports": cred.transports.split(',') if cred.transports else [],
                }
                for cred in credentials_qs
            ]
        except Exception as e:
            logger.exception(f"Database: Error retrieving WebAuthn credential info for user {user_id}: {e}")
            raise DatabaseError(f"Failed to retrieve credential info for user {user_id}.") from e


    # --- Public Service Methods ---

    def generate_registration_options(self, user_id: UUID, username: str, display_name: Optional[str] = None) -> str:
        """
        Generates registration options (including challenge) for a user.

        Args:
            user_id: The UUID of the user registering.
            username: The unique username (potentially used for user name).
            display_name: Optional user display name for authenticator UI.

        Returns:
            A JSON string containing the options for the frontend, including a 'challenge_id'.

        Raises:
            WebAuthnServiceError: If options cannot be generated or DB error occurs.
            UserNotFoundError: If the user cannot be found (future check if needed).
            DatabaseError: If retrieving existing credentials fails.
        """
        # RP config checked in __init__
        logger.info(f"Service: Generating WebAuthn registration options for user {user_id} ({username}).")
        user_display_name = display_name or username
        user_handle = self._generate_user_handle(user_id)

        try:
            # Retrieve existing credentials to exclude them
            existing_credentials = self._db_get_user_credentials(user_id)
            exclude_credentials = [
                PublicKeyCredentialDescriptor(id=cred.credential_id, transports=cred.transports) # Include transports
                for cred in existing_credentials
            ]
            logger.debug(f"Service: Excluding {len(exclude_credentials)} existing credentials for user {user_id}.")

        except DatabaseError as e:
            # Propagate DB errors encountered while fetching credentials
            raise e
        except Exception as e:
            # Catch any other unexpected errors during credential fetch/processing
            logger.exception(f"Service: Unexpected error preparing registration for user {user_id}: {e}")
            raise WebAuthnServiceError("Failed to prepare registration options.") from e

        try:
            options: PublicKeyCredentialCreationOptions = generate_registration_options(
                rp_id=self.rp_id,
                rp_name=self.rp_name,
                user_id=user_handle,
                user_name=username, # Typically maps to username/login field
                user_display_name=user_display_name, # Friendly name for authenticator UI
                exclude_credentials=exclude_credentials,
                authenticator_selection=self.authenticator_selection,
                attestation=self.attestation_preference,
                timeout=self.webauthn_timeout_ms,
                pub_key_cred_params=PUB_KEY_CRED_PARAMS,
                # Add extensions here if needed, e.g., ExtensionsInput(cred_props=True)
            )

            # Generate a unique ID for this specific challenge instance
            challenge_id = secrets.token_urlsafe(16)
            challenge_value = options.challenge # Get the bytes challenge

            # Cache the challenge bytes using the unique challenge_id
            cache_key = self._generate_cache_key("reg_challenge", user_id=user_id, challenge_id=challenge_id)
            cache.set(cache_key, challenge_value, timeout=self.challenge_timeout_seconds)

            logger.info(f"Service: Generated WebAuthn registration options for user {user_id}. Challenge ID: {challenge_id}, Cache Key: {cache_key}")

            # Return JSON options, adding the challenge_id for the client to send back
            options_dict = json.loads(options_to_json(options))
            options_dict["challenge_id"] = challenge_id # Add unique ID to track this challenge
            return json.dumps(options_dict)

        except WebAuthnException as e:
            logger.error(f"Service: WebAuthn library error generating registration options for user {user_id}: {e}", exc_info=True)
            raise WebAuthnServiceError("Could not generate registration options due to library error.") from e
        except Exception as e:
            logger.exception(f"Service: Unexpected error generating registration options for user {user_id}: {e}")
            raise WebAuthnServiceError("An unexpected error occurred generating registration options.") from e


    def verify_registration(self, user_id: UUID, registration_response: Dict[str, Any], challenge_id: str) -> RegistrationCredential:
        """
        Verifies the authenticator's response during registration and saves the credential.

        Args:
            user_id: The UUID of the user registering.
            registration_response: The parsed JSON response from the authenticator/frontend.
            challenge_id: The unique ID associated with the challenge being verified.

        Returns:
            The verified RegistrationCredential object upon success.

        Raises:
            ChallengeNotFoundError: If the challenge is missing or expired.
            VerificationError: If the cryptographic verification fails (mismatch, invalid data).
            DuplicateCredentialError: If the credential ID already exists.
            UserNotFoundError: If the user_id doesn't exist during save.
            DatabaseError: For database errors during save.
            WebAuthnServiceError: For other unexpected errors.
        """
        # RP config checked in __init__
        logger.info(f"Service: Verifying WebAuthn registration for user {user_id} with challenge ID {challenge_id}.")

        cache_key = self._generate_cache_key("reg_challenge", user_id=user_id, challenge_id=challenge_id)
        expected_challenge = cache.get(cache_key)

        if not expected_challenge:
            logger.warning(f"Service: WebAuthn registration challenge not found or expired for user {user_id}. Challenge ID: {challenge_id}, Cache key: {cache_key}")
            security_logger.warning(f"SECURITY: WebAuthn registration FAILED: Challenge expired/missing. User: {user_id}, Challenge ID: {challenge_id}")
            raise ChallengeNotFoundError("Registration challenge not found or expired.")

        try:
            # Determine if User Verification was explicitly required in the options phase
            # This requires storing the generated options or re-deriving the requirement setting
            # For simplicity here, we use the configured setting. A stricter implementation
            # might store the exact `require_user_verification` used for the specific challenge.
            uv_required = (self.authenticator_selection.user_verification == UserVerificationRequirement.REQUIRED.value) # Compare with enum value

            # Verify registration using the raw dictionary response
            verified_credential: RegistrationCredential = verify_registration_response(
                credential=registration_response, # Pass the dict here as per signature
                expected_challenge=expected_challenge,
                expected_origin=self.expected_origin,
                expected_rp_id=self.rp_id,
                require_user_verification=uv_required,
                # Optional: Add require_user_present=True (default in library is True) if needed
            )

            credential_id_b64 = bytes_to_base64url(verified_credential.credential_id) # Get b64 for logging/saving
            logger.info(f"Service: WebAuthn registration verification successful for user {user_id}. Credential ID: {credential_id_b64}")

            # --- CRITICAL: Save the verified credential to the database ---
            self._db_save_user_credential(user_id=user_id, reg_cred=verified_credential)
            # -------------------------------------------------------------

            # Verification and save successful, remove challenge from cache
            cache.delete(cache_key)
            security_logger.info(f"SECURITY: WebAuthn registration SUCCESSFUL: User: {user_id}, Credential ID: {credential_id_b64}")
            return verified_credential # Return the verified credential object

        # Catch the specific exceptions that verify_registration_response can raise
        # --- CORRECTED: Removed ChallengeMismatchError ---
        except (OriginMismatchError, RpIdMismatchError, InvalidDataError, UserVerificationRequiredError, RegistrationRejectedError, InvalidAttestationStatementError, InvalidAuthenticatorDataError, InvalidClientDataError) as e:
            # Catch specific verification failures from the webauthn library (using names from v2.0+)
            logger.warning(f"Service: WebAuthn registration verification FAILED for user {user_id}, challenge ID {challenge_id}. Error: {type(e).__name__} - {e}")
            security_logger.warning(f"SECURITY: WebAuthn registration FAILED: Verification error. User: {user_id}, Challenge ID: {challenge_id}. Error: {type(e).__name__}")
            # Optionally remove challenge from cache even on failure? Depends on policy.
            # cache.delete(cache_key)
            raise VerificationError(f"Registration verification failed: {e}") from e
        except (UserNotFoundError, DuplicateCredentialError, DatabaseError) as e:
            # Propagate specific errors raised from the DB layer
            # Error should already be logged adequately in _db_save_user_credential
            security_logger.error(f"SECURITY: WebAuthn registration FAILED: Post-verification DB error. User: {user_id}, Challenge ID: {challenge_id}. Error: {type(e).__name__}")
            # Don't delete cache key here, maybe allow retry? Or delete depending on error type.
            raise e
        except WebAuthnException as e:
            # Catch other potential errors from the library during verification
            logger.exception(f"Service: WebAuthn library error during registration verification for user {user_id}: {e}")
            security_logger.error(f"SECURITY: WebAuthn registration FAILED: Library error during verification. User: {user_id}, Challenge ID: {challenge_id}. Error: {e}")
            raise VerificationError("Registration verification library error.") from e
        except Exception as e:
            logger.exception(f"Service: Unexpected error during registration verification for user {user_id}: {e}")
            security_logger.error(f"SECURITY: WebAuthn registration FAILED: Unexpected error. User: {user_id}, Challenge ID: {challenge_id}. Error: {e}")
            # Optionally remove challenge from cache
            # cache.delete(cache_key)
            raise WebAuthnServiceError("An unexpected error occurred during registration verification.") from e


    def generate_authentication_options(self, user_id: Optional[UUID] = None) -> str:
        """
        Generates authentication options (challenge) for login.

        Args:
            user_id: The UUID of the user attempting to authenticate (if known).
                     If None, generates options for discoverable credentials (username-less login).

        Returns:
            A JSON string containing the options for the frontend, including a 'challenge_id'.

        Raises:
            CredentialNotFoundError: If user_id is provided but no credentials exist (optional, could also return empty allow list).
            DatabaseError: If fetching credentials fails.
            WebAuthnServiceError: For other generation errors.
        """
        # RP config checked in __init__
        logger.info(f"Service: Generating WebAuthn authentication options. User specified: {user_id is not None}")

        allow_credentials: Optional[List[PublicKeyCredentialDescriptor]] = None
        # User verification: Prefer for standard login, require for discoverable
        # Use the setting from __init__ which includes potential overrides.
        user_verification_req_enum = self.authenticator_selection.user_verification # Get Enum value from config

        # Generate unique ID for this challenge instance *before* potentially hitting DB
        challenge_id = secrets.token_urlsafe(16)
        # Determine cache key part based on whether user ID is known
        cache_key_user_part = str(user_id) if user_id else "discoverable"

        if user_id:
            try:
                # User is known, fetch their specific credentials to populate allowCredentials
                user_credentials = self._db_get_user_credentials(user_id)
                if not user_credentials:
                    # Policy decision: Raise error or allow generation with empty list?
                    # Raising error is clearer if WebAuthn is required for the user.
                    # Returning empty allows fallback (e.g., password) but might hide issues.
                    # Let's raise CredentialNotFoundError for clarity.
                    logger.warning(f"Service: No WebAuthn credentials found for user {user_id} during authentication options generation.")
                    raise CredentialNotFoundError(f"No WebAuthn credentials registered for user {user_id}.")

                allow_credentials = [
                    PublicKeyCredentialDescriptor(
                        id=cred.credential_id,
                        transports=cred.transports # Include transports if available/stored, helps browser select
                    )
                    for cred in user_credentials
                ]
                logger.debug(f"Service: Allowing {len(allow_credentials)} specific credentials for user {user_id}.")

            except DatabaseError as e:
                raise e # Propagate DB errors
            except Exception as e:
                logger.exception(f"Service: Unexpected error fetching credentials for auth options for user {user_id}: {e}")
                raise WebAuthnServiceError("Failed to prepare authentication options.") from e

        else:
            # Username-less login (discoverable credentials / resident keys)
            # Per WebAuthn spec L2+, allowCredentials should typically be omitted or empty.
            allow_credentials = [] # Empty list is preferred over None for clarity
            # User Verification MUST be required for discoverable credentials to securely identify the user.
            user_verification_req_enum = UserVerificationRequirement.REQUIRED
            logger.info("Service: Generating options for discoverable credential (username-less) login, requiring user verification.")


        try:
            options: PublicKeyCredentialRequestOptions = generate_authentication_options(
                rp_id=self.rp_id,
                allow_credentials=allow_credentials, # Can be empty list for discoverable
                user_verification=user_verification_req_enum.value, # Pass the string value
                timeout=self.webauthn_timeout_ms,
                # extensions= # Add extensions if needed (e.g., appid)
            )

            # Cache the challenge bytes using the unique challenge_id
            challenge_value = options.challenge
            cache_key = self._generate_cache_key("auth_challenge", user_id=user_id, challenge_id=challenge_id)
            cache.set(cache_key, challenge_value, timeout=self.challenge_timeout_seconds)

            logger.info(f"Service: Generated WebAuthn authentication options. User: {cache_key_user_part}. Challenge ID: {challenge_id}, Cache Key: {cache_key}")

            # Return JSON options including the challenge_id
            options_dict = json.loads(options_to_json(options))
            options_dict["challenge_id"] = challenge_id # Add unique ID to track this challenge
            return json.dumps(options_dict)

        except WebAuthnException as e:
            logger.error(f"Service: WebAuthn library error generating authentication options for user {cache_key_user_part}: {e}", exc_info=True)
            raise WebAuthnServiceError("Could not generate authentication options due to library error.") from e
        except Exception as e:
            logger.exception(f"Service: Unexpected error generating authentication options for user {cache_key_user_part}: {e}")
            raise WebAuthnServiceError("An unexpected error occurred generating authentication options.") from e


    def verify_authentication(
        self,
        authentication_response: Dict[str, Any],
        challenge_id: str,
    ) -> UUID:
        """
        Verifies the authenticator's response during authentication and updates sign count.

        Args:
            authentication_response: The parsed JSON response from the authenticator/frontend.
                                     Must include `id`, `rawId`, `response`, `type`.
                                     `response` must contain `authenticatorData`, `clientDataJSON`, `signature`.
                                     May contain `userHandle` if discoverable credential was used.
            challenge_id: The unique ID associated with the challenge being verified.

        Returns:
            The UUID of the successfully authenticated user.

        Raises:
            ChallengeNotFoundError: If the challenge is missing or expired.
            CredentialNotFoundError: If the credential used is not found in the database for any user.
            UserNotFoundError: If user couldn't be determined (e.g., bad userHandle and cred ID not found).
            VerificationError: If cryptographic verification fails (sign count, signature, mismatch).
            DatabaseError: For database errors during credential lookup or sign count update.
            WebAuthnServiceError: For other unexpected errors.
        """
        # RP config checked in __init__
        logger.info(f"Service: Verifying WebAuthn authentication with challenge ID {challenge_id}.")

        # --- Input Validation ---
        if not isinstance(authentication_response, dict):
            logger.warning("Service: Authentication response is not a valid dictionary.")
            raise VerificationError("Authentication response format invalid: Not a dictionary.")

        credential_id_b64 = authentication_response.get("id")
        if not credential_id_b64 or not isinstance(credential_id_b64, str):
            logger.warning("Service: Authentication response missing or invalid credential ID ('id').")
            raise VerificationError("Authentication response format invalid: Missing or invalid credential ID.")

        response_data = authentication_response.get("response")
        if not isinstance(response_data, dict):
            logger.warning("Service: Authentication response missing or invalid 'response' object.")
            raise VerificationError("Authentication response format invalid: Missing or invalid 'response' object.")

        # --- Determine User ID ---
        user_id: Optional[UUID] = None
        user_handle_bytes: Optional[bytes] = None
        raw_user_handle = response_data.get("userHandle") # This is Base64URL encoded string

        try:
            if raw_user_handle:
                if not isinstance(raw_user_handle, str):
                    logger.warning(f"Service: Invalid user handle type in assertion: {type(raw_user_handle)}")
                    raise VerificationError("Invalid user handle format: Not a string.")
                # Discoverable credential used - user identified by userHandle in assertion
                logger.debug(f"Service: User handle found in assertion response: {raw_user_handle}")
                user_handle_bytes = base64url_to_bytes(raw_user_handle)
                user_id = self._decode_user_handle(user_handle_bytes)
                logger.info(f"Service: Identified user {user_id} from user handle.")
                # Optional: Verify this user_id actually exists in your User table?
                # try: User.objects.filter(pk=user_id).exists() except Exception: raise DatabaseError(...)
            else:
                # Non-discoverable credential - user must be looked up via credential ID
                logger.debug(f"Service: No user handle. Looking up user by credential ID: {credential_id_b64}")
                user_id = self._db_find_user_id_by_credential_id(credential_id_b64)
                if not user_id:
                    # If lookup fails, the credential is unknown or inactive
                    logger.warning(f"Service: Could not find user associated with credential ID: {credential_id_b64}")
                    security_logger.warning(f"SECURITY: WebAuthn auth FAILED: User lookup failed for credential {credential_id_b64}")
                    # Use CredentialNotFound as the specific credential wasn't found linked to a user
                    raise CredentialNotFoundError(f"Credential {credential_id_b64} not found or not associated with a user.")
                logger.info(f"Service: Found user ID {user_id} associated with credential {credential_id_b64}")

        except (ValueError, TypeError) as e: # Catch potential errors from base64url_to_bytes or UUID conversion
            logger.error(f"Service: Error processing user handle or credential ID: {e}", exc_info=True)
            raise VerificationError(f"Invalid format for user handle or credential ID: {e}") from e
        except DatabaseError as e: # Catch DB errors during user lookup
            raise e # Propagate DB errors
        except VerificationError as e: # Catch decode user handle specific error
            raise e


        # --- Retrieve Challenge ---
        # Now that user_id is determined (or None if lookup failed above, though we raise before here)
        if not user_id:
            # This state should ideally not be reached due to prior checks/raises
            logger.error("Service: User ID could not be determined before challenge retrieval.")
            raise WebAuthnServiceError("Internal error: User identification failed.")

        cache_key = self._generate_cache_key("auth_challenge", user_id=user_id, challenge_id=challenge_id)
        expected_challenge = cache.get(cache_key)

        # Fallback check for discoverable challenge key ONLY if user was found via cred ID lookup (i.e., no user handle in response)
        if not expected_challenge and not raw_user_handle:
            discoverable_cache_key = self._generate_cache_key("auth_challenge", user_id=None, challenge_id=challenge_id)
            logger.debug(f"Service: User-specific challenge key {cache_key} not found, checking discoverable key {discoverable_cache_key}")
            expected_challenge = cache.get(discoverable_cache_key)
            if expected_challenge:
                cache_key = discoverable_cache_key # Use the key where challenge was found

        if not expected_challenge:
            logger.warning(f"Service: WebAuthn authentication challenge expired or not found. User: {user_id}, Challenge ID: {challenge_id}. Attempted cache key(s) like: {cache_key}")
            security_logger.warning(f"SECURITY: WebAuthn auth FAILED: Challenge expired/missing. User: {user_id}, Challenge ID: {challenge_id}")
            raise ChallengeNotFoundError("Authentication challenge not found or expired.")


        # --- Retrieve Specific Credential for Verification ---
        try:
            user_credentials = self._db_get_user_credentials(user_id)
            credential_to_verify: Optional[RegistrationCredential] = None
            try:
                credential_id_bytes = base64url_to_bytes(credential_id_b64)
            except (ValueError, TypeError) as e:
                logger.error(f"Service: Invalid base64url format for credential ID '{credential_id_b64}' in response: {e}", exc_info=True)
                raise VerificationError("Invalid credential ID format in response.") from e

            for cred in user_credentials:
                if cred.credential_id == credential_id_bytes:
                    credential_to_verify = cred
                    break

            if not credential_to_verify:
                logger.warning(f"Service: Attempt to authenticate with unknown or inactive credential ID {credential_id_b64} for user {user_id}")
                security_logger.warning(f"SECURITY: WebAuthn auth FAILED: Unknown/inactive credential ID {credential_id_b64} for user {user_id}")
                # Use CredentialNotFound because this specific cred ID wasn't found *for this user* in our DB list
                raise CredentialNotFoundError(f"Credential {credential_id_b64} not found or inactive for user {user_id}.")

        except DatabaseError as e: # Catch DB errors during credential fetch
            raise e
        except VerificationError as e: # Catch cred ID format error
            raise e
        except Exception as e: # Catch other errors like base64 conversion
            logger.exception(f"Service: Error retrieving/processing credentials for auth verification (User: {user_id}): {e}")
            raise WebAuthnServiceError("Failed to prepare for authentication verification.") from e

        # --- Perform Cryptographic Verification ---
        try:
            # Determine if UV was required based on flow (discoverable always requires, non-discoverable uses setting)
            # If user handle was present, UV was implicitly performed by authenticator
            uv_required = raw_user_handle is not None or \
                          (self.authenticator_selection.user_verification == UserVerificationRequirement.REQUIRED.value) # Compare value

            # Call verify_authentication_response with individual args as per function signature
            auth_verification: AuthenticationCredential = verify_authentication_response(
                credential=authentication_response, # Pass dict here
                expected_challenge=expected_challenge,
                expected_origin=self.expected_origin,
                expected_rp_id=self.rp_id,
                credential_public_key=credential_to_verify.public_key,
                credential_current_sign_count=credential_to_verify.sign_count,
                require_user_verification=uv_required, # Library checks UV flag based on this
            )

            logger.info(f"Service: WebAuthn authentication verification successful for user {user_id}. Credential ID: {credential_id_b64}. New sign count: {auth_verification.new_sign_count}")

            # --- CRITICAL: Update the credential's sign count in the database ---
            update_success = self._db_update_credential_sign_count(
                user_id=user_id,
                credential_id_b64=credential_id_b64,
                new_sign_count=auth_verification.new_sign_count
            )
            # -------------------------------------------------------------------

            if not update_success:
                # This is serious - verification passed but DB update failed.
                # Could be DB issue, race condition (if lock failed), or cred deleted between verify and update.
                # Treat as authentication failure to prevent potential replay using the old sign count.
                logger.critical(f"CRITICAL: Failed to update sign count for user {user_id}, credential {credential_id_b64} after successful verification. Authentication DENIED.")
                security_logger.error(f"SECURITY: WebAuthn auth FAILED: Post-verification sign count update failed. User: {user_id}, Credential: {credential_id_b64}")
                # Don't delete cache key - allows investigation.
                raise DatabaseError("Failed to update credential state after verification. Authentication denied.")

            # Verification and DB update successful, remove challenge from cache
            cache.delete(cache_key)
            security_logger.info(f"SECURITY: WebAuthn auth SUCCESSFUL: User: {user_id}, Credential ID: {credential_id_b64}")

            return user_id # Return the authenticated user's ID

        # Catch specific verification errors from webauthn>=2.0
        # --- CORRECTED: Removed ChallengeMismatchError ---
        except (OriginMismatchError, RpIdMismatchError, InvalidDataError, UserVerificationRequiredError, AuthenticationRejectedError, InvalidClientDataError, InvalidAuthenticatorDataError, ValueError) as e:
            # ValueError can be raised by library for sign count mismatch or other data issues.
            logger.warning(f"Service: WebAuthn authentication verification FAILED for user {user_id}, credential {credential_id_b64}. Error: {type(e).__name__} - {e}")
            security_logger.warning(f"SECURITY: WebAuthn auth FAILED: Verification error. User: {user_id}, Credential: {credential_id_b64}, Challenge ID: {challenge_id}. Error: {type(e).__name__}")
            # Optionally remove challenge from cache even on failure?
            # cache.delete(cache_key)
            raise VerificationError(f"Authentication verification failed: {e}") from e
        except DatabaseError as e: # Catch errors from sign count update
            # Error already logged in _db_update_credential_sign_count if critical
            security_logger.error(f"SECURITY: WebAuthn auth FAILED: DB error during sign count update. User: {user_id}, Challenge ID: {challenge_id}. Error: {e}")
            raise e # Re-raise the specific DB error
        except WebAuthnException as e:
            # Catch other potential errors from the library during verification
            logger.exception(f"Service: WebAuthn library error during auth verification for user {user_id}: {e}")
            security_logger.error(f"SECURITY: WebAuthn auth FAILED: Library error during verification. User: {user_id}, Credential: {credential_id_b64}. Error: {e}")
            raise VerificationError("Authentication verification library error.") from e
        except Exception as e:
            logger.exception(f"Service: Unexpected error during auth verification for user {user_id}, credential {credential_id_b64}: {e}")
            security_logger.error(f"SECURITY: WebAuthn auth FAILED: Unexpected error. User: {user_id}, Credential: {credential_id_b64}, Challenge ID: {challenge_id}. Error: {e}")
            # Optionally remove challenge from cache
            # cache.delete(cache_key)
            raise WebAuthnServiceError("An unexpected error occurred during authentication verification.") from e


    # --- Optional Utility Methods ---

    def remove_credential(self, user_id: UUID, credential_id_b64: str) -> bool:
        """
        Removes a specific WebAuthn credential for a user.

        Args:
            user_id: The UUID of the user owning the credential.
            credential_id_b64: The base64url encoded ID of the credential to remove.

        Returns:
            True if the credential was successfully removed, False if not found.

        Raises:
            DatabaseError: If a database error occurs during deletion.
            WebAuthnServiceError: For other unexpected errors.
        """
        logger.info(f"Service: Request to remove WebAuthn credential {credential_id_b64} for user {user_id}.")
        try:
            success = self._db_remove_credential(user_id, credential_id_b64)
            if success:
                security_logger.info(f"SECURITY: WebAuthn credential REMOVED: User: {user_id}, Credential ID: {credential_id_b64}")
            else:
                logger.warning(f"Service: Credential {credential_id_b64} not found for removal for user {user_id}.")
            return success
        except DatabaseError as e:
            logger.error(f"Service: Failed to remove credential {credential_id_b64} for user {user_id} due to DB error.")
            raise e # Re-raise DB error
        except Exception as e:
            logger.exception(f"Service: Unexpected error removing credential {credential_id_b64} for user {user_id}: {e}")
            raise WebAuthnServiceError("An unexpected error occurred while removing the credential.") from e


    def get_user_credentials_info(self, user_id: UUID) -> List[Dict[str, Any]]:
        """
        Returns basic, non-sensitive info about a user's registered credentials
        (e.g., for display in profile settings). Requires DB implementation.

        Args:
            user_id: The UUID of the user whose credentials info is requested.

        Returns:
            A list of dictionaries, each containing info about one credential.

        Raises:
            DatabaseError: If a database error occurs during retrieval.
            WebAuthnServiceError: For other unexpected errors.
        """
        logger.info(f"Service: Request for WebAuthn credential info list for user {user_id}.")
        try:
            return self._db_get_user_credentials_info(user_id)
        except DatabaseError as e:
            logger.error(f"Service: Failed to get credential info for user {user_id} due to DB error.")
            raise e # Re-raise DB error
        except Exception as e:
            logger.exception(f"Service: Unexpected error getting credential info for user {user_id}: {e}")
            raise WebAuthnServiceError("An unexpected error occurred while retrieving credential information.") from e


# --- END OF WebAuthnService Class ---

# Optional: Instantiate a singleton instance for easy import elsewhere,
# though dependency injection is generally preferred in larger Django apps.
# webauthn_service = WebAuthnService()

# --- Model Definition Reminder ---
# NOTE: You MUST define the `WebAuthnCredential` model, likely in `store/models.py`.
# It should include fields like:
# - user: ForeignKey(User, on_delete=models.CASCADE)
# - credential_id_b64: CharField(max_length=255, unique=True, db_index=True) # Store as base64url string
# - public_key_b64: TextField() # Store as base64url string
# - sign_count: PositiveIntegerField(default=0)
# - transports: CharField(max_length=255, blank=True, default='') # Comma-separated list e.g., "internal,hybrid"
# - nickname: CharField(max_length=100, blank=True, default='') # User-provided name
# - created_at: DateTimeField(auto_now_add=True)
# - last_used_at: DateTimeField(null=True, blank=True)
# Ensure appropriate database indexes are created (on user, credential_id_b64).