# backend/store/validators.py

"""
Custom Django field validators for the store application.

Includes validators for:
- Monero Addresses (Format Check Only)
- Bitcoin Addresses (Basic Format Check - Requires Library for Full Validation)
- Ethereum Addresses (Format and Checksum using Web3)
- PGP Public Keys (Format, Importability, Security Policy Checks)
"""
# <<< VALIDATOR REVISIONS >>>
# - v1.1.2: (2025-04-07) - Correct BTC Address Regex Bech32 Chars by Gemini
#   - FIXED: Corrected the character set within BTC_ADDRESS_REGEX for the Bech32/Bech32m
#     part to use `[qpzry9x8gf2tvdw0s3jn54khce6mua7l]` instead of the incorrect `[ac-hj-np-z02-9]`.
#   - NOTE: Regex still does not validate checksums. Library recommended.
# - v1.1.1: (2025-04-07) - Improve BTC Address Regex (Format Only) by Gemini
#   - FIXED: Updated BTC_ADDRESS_REGEX to correctly match the format of Testnet Bech32 (tb1...)
#     addresses, resolving the ValidationError in test_mark_shipped_btc_success.
#   - WARNING: Emphasized that this regex *still does not validate checksums* and a dedicated
#     library (e.g., bitcoinaddress, python-bitcoinlib) is strongly recommended for production.
# - v1.1.0: (2025-04-06) - Fix GPG Home Setting Name Typo by Gemini
#   - FIXED: `ImproperlyConfigured` error in `validate_pgp_public_key`.
#   - Changed check from `settings.GNUPG_HOME` to the correct `settings.GPG_HOME`.
#   - Updated log and exception messages to reflect the correct setting name.
# - v1.0.0: Initial Version

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

# Third-party Imports (Ensure these are in your requirements.txt)
# Attempt imports and handle gracefully if optional dependencies are missing
try:
    import gnupg
except ImportError:
    gnupg = None  # type: ignore # Allow graceful failure if not installed

try:
    from web3 import Web3
    from web3.exceptions import InvalidAddress
except ImportError:
    Web3 = None  # type: ignore # Allow graceful failure if not installed
    InvalidAddress = None # type: ignore

# Django Imports
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

# --- Configuration Constants ---

# Consider moving PGP constants to Django settings (e.g., settings.PGP_VALIDATION_CONFIG)
# if they need to be configured per deployment.
MIN_RSA_KEY_SIZE: int = 3072
# See https://tools.ietf.org/html/rfc4880#section-9.1
ALLOWED_PUBKEY_ALGORITHMS: Set[str] = {
    '1',   # RSA (Encrypt or Sign) - Size check needed
    '17',  # DSA (Sign only) - Discouraged unless >= 2048 bit, SHA2+ (Not checked here)
    '19',  # ECDSA (Sign Only) - Requires specific curve checks (Not implemented here)
    '22',  # EdDSA (Ed25519) - RECOMMENDED
    '18',  # ECDH (Curve25519) - RECOMMENDED (often used with EdDSA subkey)
    # '19', # Elgamal (Encrypt only) - Generally DISCOURAGED (Code 16 or 20? RFC4880 is complex)
}
# See https://tools.ietf.org/html/rfc4880#section-9.4
DISALLOWED_HASH_ALGORITHMS: Set[str] = {
    '1',  # MD5
    '2',  # SHA1
    '3',  # RIPEMD160
    # '8', '9', '10', '11' are SHA2 family - Allowed
}
PREFERRED_HASH_ALGORITHMS: Set[str] = {'8', '9', '10', '11'}  # SHA256, SHA384, SHA512, SHA224


# --- Address Regex Patterns ---
# NOTE: Regex checks are FORMAT ONLY. Checksum validation requires libraries.

# Monero: Starts with 4 (standard) or 8 (integrated), 95 or 106 chars total.
# Source: Simplified based on common patterns. Base58 characters.
MONERO_ADDRESS_REGEX = r'^[48][1-9A-HJ-NP-Za-km-z]{94}([1-9A-HJ-NP-Za-km-z]{11})?$'

# !! WARNING: Regex DOES NOT VALIDATE CHECKSUMS - USE A DEDICATED LIBRARY FOR PRODUCTION !!
# Improved Regex v2: Matches format for Legacy(1), P2SH(3), Bech32(bc1q/bc1p),
# and their Testnet equivalents(m/n/2, tb1q/tb1p) with more accurate character sets.
BTC_ADDRESS_REGEX = r'^(?:[13mn2][a-km-zA-HJ-NP-Z1-9]{25,39}|(?:bc|tb)1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{11,71})$'

# Ethereum: Standard 0x followed by 40 hex characters.
ETH_ADDRESS_REGEX = r'^0x[a-fA-F0-9]{40}$'


# --- Validator Functions ---

def validate_monero_address(value: str) -> None:
    """
    Validates the basic format of a Monero standard or integrated address.

    NOTE: This validator ONLY checks the format (prefix, length, characters).
    It does NOT validate the Base58 checksum due to complexity. For strict
    validation, integrate a dedicated Monero library if available and reliable.

    Raises:
        ValidationError: If the format is invalid.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")
    if not re.match(MONERO_ADDRESS_REGEX, value):
        raise ValidationError(f"'{value[:10]}...' is not a valid Monero address format.")
    logger.debug(f"Monero address format validation passed for: {value[:10]}...")


def validate_bitcoin_address(value: str) -> None:
    """
    Performs a basic format check for Bitcoin addresses (Legacy, P2SH, SegWit).

    WARNING: This validator uses a basic regex and DOES NOT validate checksums,
    which differ based on address type (P2PKH, P2SH, Bech32, Bech32m).
    For production use, integrating a dedicated library like 'bitcoinaddress'
    or 'python-bitcoinlib' for proper checksum validation is STRONGLY recommended.

    Example (using hypothetical library):
    ```python
    # try:
    #     import bitcoinaddress
    #     if not bitcoinaddress.validate(value):
    #         raise ValidationError("Invalid Bitcoin address checksum or format.")
    # except ImportError:
    #         logger.warning("Bitcoin address validation library not found. "
    #                        "Falling back to basic regex check.")
    #         if not re.match(BTC_ADDRESS_REGEX, value):
    #             raise ValidationError("Invalid Bitcoin address format (basic check).")
    # except Exception as e:
    #         raise ValidationError(f"Bitcoin validation error: {e}")
    ```

    Raises:
        ValidationError: If the basic format appears invalid.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")
    # Use the improved regex (which still lacks checksum validation)
    if not re.match(BTC_ADDRESS_REGEX, value):
        raise ValidationError(f"'{value[:10]}...' does not match basic Bitcoin address format.")

    # Add library-based validation here if possible and required.
    # If a library *is* required, raise an error if it cannot be imported,
    # or if validation fails using the library.
    logger.warning(
        f"Bitcoin address validation for '{value[:10]}...' used basic regex ONLY. "
        "Checksum not validated. Consider using a dedicated library."
    )
    logger.debug(f"Bitcoin address basic format validation passed for: {value[:10]}...")


def validate_ethereum_address(value: str) -> None:
    """
    Validates an Ethereum address format and EIP-55 checksum using Web3.py.

    Requires the 'web3' library to be installed.

    Raises:
        ValidationError: If the format or checksum is invalid, or if Web3 is unavailable.
        ImproperlyConfigured: If Web3 library is needed but not installed.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")

    if Web3 is None or InvalidAddress is None:
        logger.error("Web3 library not found, cannot perform Ethereum address validation.")
        # Option 1: Fail hard if Web3 is absolutely required
        raise ImproperlyConfigured("Web3 library is required for Ethereum address validation but is not installed.")
        # Option 2: Allow failure but maybe log critical / raise ValidationError
        # raise ValidationError("Ethereum validation service unavailable.")

    if not re.match(ETH_ADDRESS_REGEX, value):
        raise ValidationError(f"'{value}' is not a valid Ethereum address format (Regex check failed).")

    try:
        # Web3.is_checksum_address checks if it *already* has a valid checksum.
        # Web3.to_checksum_address converts a valid non-checksum address or
        # validates an already checksummed one. It raises InvalidAddress if
        # the address format is fundamentally wrong or checksum is incorrect
        # for mixed-case addresses.
        checksummed_address = Web3.to_checksum_address(value)

        # Policy Decision: Enforce checksum?
        # If you require users to *input* checksummed addresses (EIP-55):
        # if not Web3.is_checksum_address(value):
        #     raise ValidationError(
        #         f"Address is valid but requires EIP-55 checksum. Expected: {checksummed_address}"
        #     )
        # If any valid address (checksummed or not) is acceptable, the
        # to_checksum_address call succeeding is enough.

    except InvalidAddress:
        # This catches cases where the address has mixed case but invalid checksum,
        # or other subtle invalidities not caught by the regex.
        raise ValidationError(f"'{value}' is not a valid Ethereum address (Invalid checksum or format).")
    except Exception as e:
        # Catch other unexpected errors from Web3
        logger.error(f"Unexpected Web3 error during Ethereum address validation: {e}", exc_info=True)
        raise ValidationError(f"An unexpected error occurred during Ethereum address validation: {e}")

    logger.debug(f"Ethereum address validation passed for: {value}")


def validate_pgp_public_key(value: str) -> None:
    """
    Validates a PGP public key block for format, importability, security, and usability.

    Checks:
    - Basic block format (BEGIN/END headers).
    - Successful import using GnuPG.
    - Key is not revoked.
    - Key is not expired.
    - Key algorithm and size meet security requirements (e.g., RSA >= 3072, Ed25519).
    - Key (or a subkey) has encryption capability.
    - Subkey algorithms and sizes meet requirements.
    - Optionally checks for weak hash algorithm preferences.

    Requires the 'python-gnupg' library and a configured GnuPG installation.
    Relies on `settings.GPG_HOME` being correctly set in Django settings.

    Raises:
        ValidationError: If the key is invalid, fails security checks, or GPG interaction fails.
        ImproperlyConfigured: If python-gnupg is not installed or settings.GPG_HOME is missing.
    """
    if gnupg is None:
        logger.error("python-gnupg library not found, cannot perform PGP key validation.")
        raise ImproperlyConfigured("python-gnupg library is required for PGP key validation but is not installed.")

    if not isinstance(value, str) or not value.strip():
        raise ValidationError("PGP key must be a non-empty string.")

    key_block = value.strip()

    # Basic structural checks
    if not key_block.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"):
        raise ValidationError("Invalid PGP Key: Does not start with expected header.")
    if not key_block.endswith("-----END PGP PUBLIC KEY BLOCK-----"):
        raise ValidationError("Invalid PGP Key: Does not end with expected footer.")
    # Basic length check (arbitrary, adjust if needed)
    # Consider making this minimum length configurable via settings
    # Or removing it if the GPG import check is deemed sufficient.
    if len(key_block) < 200:
        raise ValidationError("Invalid PGP Key: Key appears too short.")

    # Ensure GPG home directory is configured
    # FIX v1.1.0: Use correct setting name 'GPG_HOME'
    gpg_home_setting_name = 'GPG_HOME'
    gpg_home = getattr(settings, gpg_home_setting_name, None)
    if not gpg_home:
        logger.critical(f"CRITICAL: settings.{gpg_home_setting_name} is not configured for PGP validation!")
        # Fail hard as GPG cannot operate without a home directory
        raise ImproperlyConfigured(f"PGP validation service is misconfigured (settings.{gpg_home_setting_name} is missing).")

    gpg: Optional[gnupg.GPG] = None
    fingerprint: Optional[str] = None
    try:
        # Initialize GPG instance specifically for this validation context
        # This avoids potential state issues with a shared GPG instance if validation
        # involves temporary imports/deletions.
        gpg = gnupg.GPG(gnupghome=gpg_home)
        gpg.encoding = 'utf-8' # Explicitly set encoding

        # Attempt to import the key
        import_result = gpg.import_keys(key_block)

        if not import_result or not import_result.results or not import_result.fingerprints:
            # Log details from results if available
            log_detail = f"Result Status: {import_result.status}, Results: {import_result.results}" if import_result else "No import result object."
            logger.warning(f"PGP key import failed during validation. {log_detail}. Key starts with: {key_block[:80]}...")
            raise ValidationError("Failed to import PGP key. Ensure it is a valid public key block.")

        # Use the fingerprint from the successful import
        fingerprint = import_result.fingerprints[0]

        # Retrieve detailed key information using the fingerprint
        # Ensure secret=False is not needed (it's default for list_keys)
        key_data_list = gpg.list_keys(keys=[fingerprint])

        if not key_data_list:
            logger.error(f"Could not retrieve key data after import for fingerprint {fingerprint}.")
            # Consider attempting to delete the potentially problematic key if this happens often
            # gpg.delete_keys(fingerprint) # Use with caution
            raise ValidationError("Failed to analyze imported PGP key. It might be corrupted or incompatible.")

        key: Dict[str, Any] = key_data_list[0] # Get the primary key data dictionary
        logger.debug(f"Validating PGP key details for fingerprint: {fingerprint}, Data: {key}")

        # --- Perform Security and Usability Checks ---

        # 1. Check Revocation Status
        # Check ownsig for revocation signatures? 'revoked' field might not always be set depending on GPG version/config.
        # A more robust check might involve looking at the 'sigs' attribute if available.
        # For now, rely on the 'revoked' flag if present.
        if key.get('revoked'):
            raise ValidationError(f"PGP key ({fingerprint[-16:]}) is revoked.")

        # 2. Check Expiration Date
        if key.get('expires'):
            try:
                expiry_timestamp = int(key['expires'])
                # Handle keys that never expire (often denoted by 0, but check GPG behavior)
                if expiry_timestamp == 0:
                    logger.debug(f"Key {fingerprint} has no expiration date.")
                else:
                    expiry_date = datetime.fromtimestamp(expiry_timestamp, timezone.utc)
                    if expiry_date < datetime.now(timezone.utc):
                        raise ValidationError(
                            f"PGP key ({fingerprint[-16:]}) expired on {expiry_date.strftime('%Y-%m-%d')}."
                        )
            except (ValueError, TypeError):
                logger.warning(f"Could not parse expiry timestamp '{key['expires']}' for key {fingerprint}.")
                raise ValidationError("Invalid or unparsable expiry date on PGP key.")

        # 3. Check Primary Key Algorithm and Size
        algo_code: Optional[str] = key.get('algo')
        if algo_code not in ALLOWED_PUBKEY_ALGORITHMS:
            raise ValidationError(f"Primary key algorithm (code {algo_code}) is not allowed or recognized.")
        if algo_code == '1':  # RSA specific check
            try:
                key_length = int(key.get('length', 0))
                if key_length < MIN_RSA_KEY_SIZE:
                    raise ValidationError(
                        f"RSA key size ({key_length} bits) is insufficient. "
                        f"Minimum required: {MIN_RSA_KEY_SIZE} bits."
                    )
            except (ValueError, TypeError):
                logger.warning(f"Could not parse RSA key length '{key.get('length')}' for key {fingerprint}.")
                raise ValidationError("Invalid or unparsable RSA key length found.")
        # Add specific checks for other algorithms (like DSA size) if they are allowed and need limits.

        # 4. Check Key Usage Flags (Encryption Capability)
        # Must have at least one key or subkey capable of encryption ('e' flag)
        can_encrypt = False
        # Combine primary key capabilities ('cap' field is preferred in newer GPG)
        primary_flags: str = key.get('cap', '')
        if 'e' in primary_flags.lower():
            can_encrypt = True

        subkeys_valid = True
        # gnupg library returns subkeys in a dictionary keyed by subkey fingerprint/key ID
        for subkey_id, subkey_data in key.get('subkeys', {}).items():
            # Check subkey revocation/expiration (optional, depends on policy)
            # if subkey_data.get('revoked'): continue # Skip revoked subkeys?
            # if subkey_data.get('expires'): ... check expiry ...

            subkey_flags: str = subkey_data.get('cap', '')
            subkey_algo_code: Optional[str] = subkey_data.get('algo')

            # If primary key cannot encrypt, check if this subkey can
            if not can_encrypt and 'e' in subkey_flags.lower():
                can_encrypt = True
                # If this subkey provides the encryption capability, validate its algorithm/size
                if subkey_algo_code not in ALLOWED_PUBKEY_ALGORITHMS:
                    logger.warning(f"Encrypting subkey {subkey_id} uses disallowed algorithm {subkey_algo_code}.")
                    subkeys_valid = False
                    raise ValidationError(f"Encrypting subkey {subkey_id[-16:]} uses disallowed algorithm (code {subkey_algo_code}).")

                if subkey_algo_code == '1': # RSA Subkey size check
                    try:
                        sub_key_length = int(subkey_data.get('length', 0))
                        if sub_key_length < MIN_RSA_KEY_SIZE:
                            logger.warning(f"Encrypting subkey {subkey_id} RSA size ({sub_key_length} bits) is too small.")
                            subkeys_valid = False
                            raise ValidationError(f"Encrypting RSA subkey {subkey_id[-16:]} size ({sub_key_length} bits) is too small.")
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse RSA subkey length '{subkey_data.get('length')}' for subkey {subkey_id}.")
                        raise ValidationError(f"Invalid or unparsable RSA subkey length found for {subkey_id[-16:]}.")
                # Add checks for other subkey algos/sizes if needed (e.g., Ed25519 doesn't need size check)

            # Optionally: Validate ALL subkeys, even non-encrypting ones, for algorithm/size
            # (Depends on security policy - e.g., disallow keys with ANY weak subkey)
            # else: # Check non-encrypting subkeys too
            #     if subkey_algo_code not in ALLOWED_PUBKEY_ALGORITHMS: ... raise ...
            #     if subkey_algo_code == '1': ... check size ... raise ...


        if not can_encrypt:
            raise ValidationError("PGP key (including subkeys) lacks encryption capability ('e' flag/capability).")

        # Raise error if any subkey validation failed (might be redundant if raised inside loop)
        if not subkeys_valid:
            raise ValidationError("One or more subkeys use disallowed algorithms or insufficient key sizes.")


        # 5. Check Associated Hash Algorithm Preferences (Security Recommendation)
        # This data might be nested within user ID packets ('uids') or in 'prefs'
        all_hash_prefs : Set[str] = set()
        # Check top-level prefs if available
        top_level_prefs = key.get('prefs', {}).get('hash_algos', [])
        all_hash_prefs.update(top_level_prefs)
        # Check prefs associated with user IDs
        for uid_data in key.get('uids_full', []): # 'uids_full' might contain more details
            uid_prefs = uid_data.get('prefs', {}).get('hash_algos', [])
            all_hash_prefs.update(uid_prefs)

        # Fallback if 'uids_full' or detailed prefs aren't available (might vary by GPG version)
        # if not all_hash_prefs and 'prefs' in key: # Check basic prefs again
        #     basic_hash_prefs = key.get('prefs',{}).get('hash_algos',[])
        #     all_hash_prefs.update(basic_hash_prefs)

        disallowed_prefs_found: Set[str] = all_hash_prefs.intersection(DISALLOWED_HASH_ALGORITHMS)

        if disallowed_prefs_found:
            # Policy: Reject keys that list weak algorithms even if stronger ones are also present? (Safer)
            logger.warning(f"Key {fingerprint} lists weak/disallowed hash preferences: {disallowed_prefs_found}")
            raise ValidationError(
                f"PGP key prefers weak hash algorithms (e.g., MD5, SHA1: codes {disallowed_prefs_found}). "
                "Please update key preferences to use only SHA-2 family (codes 8, 9, 10, 11)."
               )

        # Policy: Ensure at least one *preferred* strong hash algorithm is listed?
        has_strong_pref = any(h in PREFERRED_HASH_ALGORITHMS for h in all_hash_prefs)
        if not has_strong_pref and all_hash_prefs: # Only fail if prefs exist but none are good
            raise ValidationError("PGP key does not list any preferred modern hash algorithms (SHA256+).")


        # If all checks pass:
        logger.info(f"PGP Public Key validation successful for fingerprint {fingerprint[-16:]}")

    except ValidationError:
        # Re-raise validation errors directly to Django
        raise
    except Exception as e:
        # Catch unexpected GPG or processing errors
        logger.error(f"Unexpected error during PGP key validation for key starting '{key_block[:50]}...': {e}", exc_info=True)
        # Provide a generic error to the user, log the details
        raise ValidationError("An unexpected error occurred during PGP key validation. Please try again or contact support.") from e
    finally:
        # Clean up the imported key to avoid polluting the keyring used for validation
        if gpg and fingerprint:
            try:
                # Use with extreme caution, especially on shared keyrings.
                # Ensure this keyring is *only* used for validation.
                delete_result = gpg.delete_keys(fingerprint)
                logger.debug(f"Cleaned up validation key {fingerprint}: {delete_result.status}")
            except Exception as del_e:
                logger.error(f"Error during optional PGP key cleanup in validator for {fingerprint}: {del_e}")

# --- END OF FILE ---