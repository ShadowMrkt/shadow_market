# backend/store/services/encryption_service.py
import os
import logging
import base64
from typing import Optional, Union
from nacl import secret, utils
from nacl.exceptions import CryptoError
from nacl.encoding import Base64Encoder

# Use Vault or KMS to fetch the primary encryption key
from ..vault_integration import get_secret_from_vault # Use vault helper

logger = logging.getLogger(__name__)

# --- Key Management ---
# The actual key bytes should NOT be in code. Fetch from secure source.
_encryption_key_bytes: Optional[bytes] = None
_key_version: Optional[str] = None # Track key version if rotation is implemented

def _get_encryption_key() -> Optional[bytes]:
    """
    Retrieves the application's symmetric encryption key from a secure source (Vault/KMS/Env).
    Caches the key in memory for performance. Implements basic Vault fetching.
    """
    global _encryption_key_bytes
    if _encryption_key_bytes:
        return _encryption_key_bytes

    key = None
    key_source = "Environment Variable"

    # Priority 1: Vault
    if os.getenv('VAULT_ADDR'):
        key_source = "Vault"
        try:
            # Assumes key is stored in Vault at path 'encryption', key name 'symmetric_key_base64'
            secret_data = get_secret_from_vault("encryption")
            key_base64 = secret_data.get("symmetric_key_base64") if secret_data else None
            if key_base64:
                key = base64.b64decode(key_base64)
                logger.info("Successfully loaded encryption key from Vault.")
            else:
                 logger.error("Encryption key 'symmetric_key_base64' not found in Vault at configured path.")
        except Exception as e:
            logger.exception("Failed to load encryption key from Vault.")
            # Fallback or raise error? Depends on policy. Forcing Vault if configured:
            raise RuntimeError("Failed to load mandatory encryption key from Vault.") from e

    # Priority 2: Environment Variable (Fallback, less secure, okay for dev)
    if not key:
         key_source = "Environment Variable 'ENCRYPTION_KEY_BASE64'"
         key_base64_env = os.environ.get('ENCRYPTION_KEY_BASE64')
         if key_base64_env:
             try:
                 key = base64.b64decode(key_base64_env)
                 logger.warning("Loaded encryption key from environment variable (less secure).")
             except Exception as e:
                 logger.error(f"Failed to decode base64 encryption key from environment variable: {e}")
                 key = None # Ensure key is None if decode fails


    # Validate key length (NaCl SecretBox requires 32 bytes)
    if key and len(key) == secret.SecretBox.KEY_SIZE:
        _encryption_key_bytes = key
        # Store key version if fetched from Vault metadata?
        return _encryption_key_bytes
    elif key:
        logger.error(f"Invalid encryption key length loaded from {key_source}. Expected {secret.SecretBox.KEY_SIZE} bytes, got {len(key)}.")
        raise ValueError("Invalid encryption key length.")
    else:
        logger.error(f"Encryption key could not be loaded from any source (Vault/Env).")
        # Fail hard if key is absolutely required at startup
        raise RuntimeError("Encryption key could not be loaded.")


# --- Encryption/Decryption Functions ---

def encrypt_data(data: Union[str, bytes]) -> Optional[str]:
    """
    Encrypts string or bytes data using the application's symmetric key.
    Returns Base64 encoded ciphertext (including nonce).
    """
    key = _get_encryption_key()
    if not key: return None # Error logged in _get_encryption_key

    try:
        box = secret.SecretBox(key)
        nonce = utils.random(secret.SecretBox.NONCE_SIZE)

        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        elif isinstance(data, bytes):
            data_bytes = data
        else:
             logger.error("Invalid data type for encryption. Must be str or bytes.")
             return None

        encrypted_message = box.encrypt(data_bytes, nonce) # This includes the nonce

        # Return as base64 encoded string for easier storage/transmission
        encoded = base64.b64encode(encrypted_message).decode('utf-8')
        # logger.debug("Encryption successful.") # Reduce log noise
        return encoded

    except CryptoError as ce:
        logger.error(f"Symmetric encryption failed: {ce}")
        return None
    except Exception as e:
        logger.exception("Unexpected error during symmetric encryption.")
        return None

def decrypt_data(encoded_encrypted_data: str) -> Optional[bytes]:
    """
    Decrypts Base64 encoded data using the application's symmetric key.
    Expects the input format from encrypt_data (nonce prepended by NaCl).
    Returns the original bytes.
    """
    key = _get_encryption_key()
    if not key: return None
    if not encoded_encrypted_data or not isinstance(encoded_encrypted_data, str):
         logger.warning("Invalid input for decryption. Must be non-empty string.")
         return None

    try:
        box = secret.SecretBox(key)
        encrypted_message_with_nonce = base64.b64decode(encoded_encrypted_data)

        decrypted_bytes = box.decrypt(encrypted_message_with_nonce)
        # logger.debug("Decryption successful.") # Reduce log noise
        return decrypted_bytes

    except CryptoError as ce:
        # This often means wrong key, tampered data, or incorrect format
        logger.warning(f"Symmetric decryption failed (CryptoError): {ce}. Data might be corrupted, tampered, or wrong key used.")
        return None
    except (ValueError, TypeError) as e:
        logger.warning(f"Symmetric decryption failed (Decode/Type Error): {e}. Input data likely not valid base64.")
        return None
    except Exception as e:
        logger.exception("Unexpected error during symmetric decryption.")
        return None

def decrypt_data_as_str(encoded_encrypted_data: str, encoding='utf-8') -> Optional[str]:
    """Helper function to decrypt data and decode it as a string."""
    decrypted_bytes = decrypt_data(encoded_encrypted_data)
    if decrypted_bytes:
        try:
            return decrypted_bytes.decode(encoding)
        except UnicodeDecodeError:
            logger.warning(f"Decrypted data could not be decoded using {encoding}.")
            return None
    return None


# --- Key Rotation ---
# Key rotation requires storing the key version with the encrypted data
# and having access to old keys for decryption. This adds complexity.
# Example: encrypt_data could return "v1:<base64_data>", decrypt_data parses version.
# Requires secure storage and retrieval of multiple key versions.

# def rotate_encryption_key():
#    """ Placeholder for key rotation logic (e.g., generate new key, store in Vault, update _encryption_key_bytes) """
#    logger.warning("rotate_encryption_key: Not implemented. Requires secure key version management.")
#    pass