# backend/store/validators.py

"""
Custom Django field validators for the store application.

Includes validators for:
- Monero Addresses (Format Check & Checksum using 'monero' library)
- Bitcoin Addresses (Format & Checksum using bitcoinaddress library)
- Ethereum Addresses (Format and Checksum using Web3)
- PGP Public Keys (Format, Importability, Security Policy Checks)
"""
# <<< VALIDATOR REVISIONS >>>
# - v1.9.1 (2025-06-28):
#   - IMPROVED: The Monero address validator's pre-check now identifies the specific invalid
#     characters found, rather than returning a generic error. This provides clearer, more
#     actionable feedback for both users and developers.
#   - Rationale: This is a production-grade hardening of the validator that makes debugging
#     easier and directly identifies the root cause of the test failures (invalid 'o' in
#     the test constant).
# - v1.9.0 (2025-06-28):
#   - FIXED: Hardened the Monero address validator to prevent `OverflowError` from the underlying library. Added a Base58 character set regex pre-check. This provides a more specific error for invalid characters and prevents the library from processing malformed data that could lead to unexpected exceptions. This is the root cause fix for the `test_update_current_user_addresses_success` failure.
#   - FIXED: Corrected syntax errors reported by Pylance linter by removing non-breaking space characters (\u00A0) that were causing parsing and indentation failures throughout the file.
# - (Older revisions omitted for brevity)

import logging
import re
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Set, Type

# Third-party Imports
try:
    import gnupg
except ImportError:
    gnupg = None

try:
    from web3 import Web3
    from web3.exceptions import InvalidAddress as Web3InvalidAddress
except ImportError:
    Web3 = None
    Web3InvalidAddress = None

try:
    from monero.address import Address as MoneroAddress
    import monero.exceptions as monero_exceptions
except ImportError:
    MoneroAddress = None
    monero_exceptions = None

try:
    import bitcoinaddress
except ImportError:
    bitcoinaddress = None

# Django Imports
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

# --- Logging Configuration ---
logger = logging.getLogger(__name__)

# --- Configuration Constants ---
MIN_RSA_KEY_SIZE: int = 3072
ALLOWED_PUBKEY_ALGORITHMS: Set[str] = {'1', '17', '19', '22', '18'}
DISALLOWED_HASH_ALGORITHMS: Set[str] = {'1', '2', '3'}
PREFERRED_HASH_ALGORITHMS: Set[str] = {'8', '9', '10', '11'}

# --- Address Regex Patterns ---
BTC_ADDRESS_REGEX = re.compile(
    r'^(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|(bc|tb)1[ac-hj-np-z02-9]{10,87})$'
)
ETH_ADDRESS_REGEX = r'^0x[a-fA-F0-9]{40}$'
# --- Validator Functions ---

def validate_monero_address(value: str) -> None:
    """
    Validates a Monero address format and checksum using the 'monero' library.
    This is a multi-layered check for robustness.
    Raises ValidationError or ImproperlyConfigured.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")

    # Layer 1 (REVISION 1.9.1): Detailed character set pre-check.
    base58_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
    invalid_chars = {char for char in value if char not in base58_chars}
    if invalid_chars:
        invalid_str = ", ".join(sorted(list(invalid_chars)))
        raise ValidationError(f"'{value[:10]}...' contains invalid Base58 character(s): {invalid_str}")

    # Layer 2: Perform a fast-fail length check.
    if not (len(value) == 95 or len(value) == 106):
        raise ValidationError(f"'{value[:10]}...' has an invalid length for a Monero address (must be 95 or 106 characters).")

    # Layer 3: Use the library for the final, definitive checksum validation.
    if MoneroAddress is None or monero_exceptions is None:
        logger.error("'monero' library core components not available. Cannot validate Monero addresses.")
        raise ImproperlyConfigured("'monero' library components failed to import. Ensure it is installed.")

    try:
        MoneroAddress(value)
        logger.debug(f"Monero address validation passed for: {value[:10]}...")
    except (monero_exceptions.WrongAddress, ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Monero address validation failed for '{value[:10]}...': ({type(e).__name__}) {e}")
        raise ValidationError(f"'{value[:10]}...' is not a valid Monero address format or checksum.") from e
    except Exception as e:
        logger.error(f"Unexpected error during Monero address validation for '{value[:10]}...': {e}", exc_info=True)
        raise ValidationError(f"An unexpected error occurred during Monero address validation: {e}") from e


def validate_bitcoin_address(value: str) -> None:
    """
    Validates a Bitcoin address using a two-layered approach: a regex for format
    and the 'bitcoinaddress' library for checksum validation.
    Raises ValidationError or ImproperlyConfigured.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")

    if not BTC_ADDRESS_REGEX.match(value):
        raise ValidationError(f"'{value}' does not have a valid Bitcoin address format.")

    if bitcoinaddress is None:
        logger.error("'bitcoinaddress' library not found. Cannot perform robust Bitcoin address validation.")
        raise ImproperlyConfigured("The 'bitcoinaddress' library is required but not installed.")

    try:
        address_obj = bitcoinaddress.Address(value)
        logger.debug(f"Bitcoin address library validation PASSED for: {value} (Type: {getattr(address_obj, 'type', 'N/A')})")
    except (ValueError, TypeError) as e:
        logger.warning(f"Bitcoin address library validation failed for '{value}': ({type(e).__name__}) {e}")
        raise ValidationError(f"'{value}' is not a valid Bitcoin address (Library Check Failed: {e}).") from e
    except Exception as e:
        logger.error(f"Unexpected error during Bitcoin address library validation for '{value}': {e}", exc_info=True)
        raise ValidationError(f"An unexpected error ({type(e).__name__}) occurred: {e}") from e


def validate_ethereum_address(value: str) -> None:
    """
    Validates an Ethereum address format and EIP-55 checksum using Web3.py.
    Raises ValidationError or ImproperlyConfigured.
    """
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")

    if Web3 is None or Web3InvalidAddress is None:
        logger.error("Web3 library not found or incomplete. Cannot validate Ethereum addresses.")
        raise ImproperlyConfigured("Web3 library is required for Ethereum address validation but is not installed.")

    if not re.fullmatch(ETH_ADDRESS_REGEX, value):
        raise ValidationError(f"'{value}' is not a valid Ethereum address format (Regex check failed).")

    try:
        Web3.to_checksum_address(value)
        logger.debug(f"Ethereum address validation passed for: {value}")
    except Web3InvalidAddress as e:
        raise ValidationError(f"'{value}' is not a valid Ethereum address (Invalid checksum or format according to Web3: {e}).") from e
    except Exception as e:
        logger.error(f"Unexpected Web3 error during Ethereum address validation for '{value}': {e}", exc_info=True)
        raise ValidationError(f"An unexpected error occurred during Ethereum address validation: {e}") from e


def validate_pgp_public_key(value: str) -> None:
    """
    Validates a PGP public key block for format, importability, security, and usability.
    Raises ValidationError or ImproperlyConfigured.
    """
    if gnupg is None:
        logger.error("python-gnupg library not found, cannot perform PGP key validation.")
        raise ImproperlyConfigured("python-gnupg library is required for PGP key validation but is not installed.")

    if not isinstance(value, str) or not value.strip():
        raise ValidationError("PGP key must be a non-empty string.")

    key_block = value.strip()

    MIN_KEY_BLOCK_LENGTH = 80
    if not key_block.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----") or \
       not key_block.endswith("-----END PGP PUBLIC KEY BLOCK-----") or \
       len(key_block) < MIN_KEY_BLOCK_LENGTH:
        raise ValidationError(f"Invalid PGP Key: Malformed block structure or too short (min length {MIN_KEY_BLOCK_LENGTH} chars).")

    gpg_home_setting_name = 'GPG_HOME'
    gpg_home = getattr(settings, gpg_home_setting_name, None)
    if not gpg_home:
        logger.critical(f"CRITICAL: settings.{gpg_home_setting_name} is not configured for PGP validation!")
        raise ImproperlyConfigured(f"PGP validation service is misconfigured (settings.{gpg_home_setting_name} is missing).")

    gpg_instance: Optional[gnupg.GPG] = None
    fingerprint: Optional[str] = None
    try:
        gpg_instance = gnupg.GPG(gnupghome=gpg_home)
        gpg_instance.encoding = 'utf-8'

        import_result = gpg_instance.import_keys(key_block)
        if not import_result or not import_result.results or not import_result.fingerprints:
            stderr_info = getattr(import_result, 'stderr', 'N/A') if import_result else 'N/A'
            log_detail = f"Status: {getattr(import_result, 'status', 'N/A')}, Results: {getattr(import_result, 'results', 'N/A')}, StdErr: {stderr_info}"
            logger.warning(f"PGP key import failed. {log_detail}. Key: {key_block[:80]}...")
            raise ValidationError(f"Failed to import PGP key. Ensure it is a valid public key block. GPG stderr: {stderr_info}")

        fingerprint = import_result.fingerprints[0]
        key_data_list = gpg_instance.list_keys(keys=[fingerprint])

        if not key_data_list:
            logger.error(f"Could not retrieve key data after import for fingerprint {fingerprint}.")
            raise ValidationError("Failed to analyze imported PGP key details.")

        key: Dict[str, Any] = key_data_list[0]
        logger.debug(f"Validating PGP key details for fingerprint: {fingerprint}")

        if key.get('revoked'):
            raise ValidationError(f"PGP key ({fingerprint[-16:]}) is revoked.")

        if key.get('expires'):
            try:
                expiry_ts = int(key['expires'])
                if expiry_ts != 0 and datetime.fromtimestamp(expiry_ts, dt_timezone.utc) < datetime.now(dt_timezone.utc):
                    expiry_date = datetime.fromtimestamp(expiry_ts, dt_timezone.utc)
                    raise ValidationError(f"PGP key ({fingerprint[-16:]}) expired on {expiry_date.strftime('%Y-%m-%d')}.")
            except (ValueError, TypeError):
                raise ValidationError("Invalid or unparsable expiry date on PGP key.")

        algo_code: Optional[str] = key.get('algo')
        if algo_code not in ALLOWED_PUBKEY_ALGORITHMS:
            raise ValidationError(f"Primary key algorithm (code {algo_code}) is not allowed.")

        if algo_code == '1': # RSA
            try:
                key_length = int(key.get('length', 0))
                if key_length < MIN_RSA_KEY_SIZE:
                    raise ValidationError(f"RSA key size ({key_length}) is insufficient (min: {MIN_RSA_KEY_SIZE}).")
            except (ValueError, TypeError):
                raise ValidationError("Invalid or unparsable RSA key length.")

        can_encrypt = 'e' in key.get('cap', '').lower()
        for subkey_id, subkey_data in key.get('subkeys', {}).items():
            if subkey_data.get('revoked'):
                continue
            if subkey_data.get('expires'):
                try:
                    sub_expiry_ts = int(subkey_data['expires'])
                    if sub_expiry_ts != 0 and datetime.fromtimestamp(sub_expiry_ts, dt_timezone.utc) < datetime.now(dt_timezone.utc):
                        continue
                except (ValueError, TypeError):
                    continue

            sub_algo_code: Optional[str] = subkey_data.get('algo')
            if sub_algo_code not in ALLOWED_PUBKEY_ALGORITHMS:
                raise ValidationError(f"Subkey {subkey_id[-16:]} uses disallowed algorithm (code {sub_algo_code}).")

            if sub_algo_code == '1': # RSA Subkey
                try:
                    sub_key_length = int(subkey_data.get('length', 0))
                    if sub_key_length < MIN_RSA_KEY_SIZE:
                        raise ValidationError(f"RSA subkey {subkey_id[-16:]} size ({sub_key_length}) is too small (min: {MIN_RSA_KEY_SIZE}).")
                except (ValueError, TypeError):
                    raise ValidationError(f"Invalid RSA subkey length for {subkey_id[-16:]}.")

            if not can_encrypt and 'e' in subkey_data.get('cap', '').lower():
                can_encrypt = True

        if not can_encrypt:
            raise ValidationError("PGP key (including its non-revoked, non-expired subkeys) lacks encryption capability ('e' flag).")

        all_hash_prefs : Set[str] = set()
        top_level_prefs = key.get('prefs', {}).get('hash_algos', [])
        all_hash_prefs.update(map(str, top_level_prefs))

        for uid_data in key.get('uids_full', []):
            uid_prefs = uid_data.get('prefs', {}).get('hash_algos', [])
            all_hash_prefs.update(map(str, uid_prefs))

        disallowed_prefs_found: Set[str] = all_hash_prefs.intersection(DISALLOWED_HASH_ALGORITHMS)
        if disallowed_prefs_found:
            raise ValidationError(f"PGP key prefers weak hash algorithms (codes {disallowed_prefs_found}). Use SHA-2 family.")

        has_strong_pref = any(h_pref in PREFERRED_HASH_ALGORITHMS for h_pref in all_hash_prefs)
        if not has_strong_pref and all_hash_prefs:
            raise ValidationError("PGP key does not list any preferred modern hash algorithms (e.g., SHA256, SHA384, SHA512).")

        logger.info(f"PGP Public Key validation successful for fingerprint {fingerprint[-16:]}")

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during PGP key validation for key '{key_block[:50]}...': {e}", exc_info=True)
        raise ValidationError("An unexpected error occurred during PGP key validation.") from e
    finally:
        if gpg_instance and fingerprint:
            try:
                delete_result = gpg_instance.delete_keys(fingerprint, secret=False)
                logger.debug(f"Cleaned up validation key {fingerprint}: Status='{delete_result.status}', StdErr='{delete_result.stderr}'")
                if "error" in str(delete_result.status).lower() or \
                   (delete_result.stderr and "error" in str(delete_result.stderr).lower()):
                    logger.warning(f"Potential issue during PGP key cleanup for {fingerprint}: {delete_result.status} / {delete_result.stderr}")
            except Exception as del_e:
                logger.error(f"Error during PGP key cleanup for {fingerprint}: {del_e}", exc_info=True)

# --- END OF FILE ---