# backend/conftest.py
# Revision: v1.1.3 - Moved Windows OpenSSL DLL pre-loading to the absolute top.
# Revision: v1.1.4 - Added monkeypatching for ctypes.util.find_library on Windows to directly
#                   return paths to known OpenSSL DLLs for problematic generic search terms.
# Revision: v1.1.5 - Modified monkeypatch for ctypes.util.find_library on Windows:
#                   Force SSL-related search terms to resolve to the libcrypto DLL.
#                   This is a workaround for python-bitcoinlib potentially looking for
#                   crypto functions (like BN_add) in its _ssl handle with OpenSSL 3.x.
# Purpose: This root conftest ensures necessary external libraries (like OpenSSL DLLs on Windows)
#          can be found by Python during test execution. It also includes service mocking
#          (e.g., for Vault) and temporary shims for missing dependencies to facilitate
#          test collection and execution in various environments.

import os
import sys
import platform
import logging
import shutil
import ctypes
from pathlib import Path
import asyncio
from unittest.mock import patch, MagicMock
import pytest

logging.basicConfig(level=logging.INFO, format='%(levelname)s (conftest): %(message)s')
log = logging.getLogger(__name__)

# --- BEGIN WINDOWS OPENSSL DLL HANDLING & MONKEYPATCHING ---
if platform.system() == "Windows":
    log.info("!!! Attempting Windows OpenSSL DLL configuration & monkeypatching at the top of conftest.py !!!")
    
    openssl_bin_dir_str = os.getenv("OPENSSL_BIN_DIR", r'C:\Program Files\OpenSSL-Win64\bin')
    openssl_bin_path = Path(openssl_bin_dir_str)
    log.info(f"Effective OpenSSL directory: {openssl_bin_path}")

    actual_ssl_dll_path = None # Path to the true libssl
    actual_crypto_dll_path = None # Path to the true libcrypto

    if openssl_bin_path.is_dir():
        if sys.version_info >= (3, 8):
            try:
                os.add_dll_directory(str(openssl_bin_path))
                log.info(f"SUCCESS: Added '{openssl_bin_path}' to DLL search path via os.add_dll_directory().")
            except Exception as e:
                log.error(f"ERROR: Failed to add DLL directory '{openssl_bin_path}': {e}")
        
        ssl_dll_candidates = ["libssl-3-x64.dll", "libssl-3.dll", "libssl-1_1-x64.dll", "libssl-1_1.dll", "ssleay32.dll"]
        crypto_dll_candidates = ["libcrypto-3-x64.dll", "libcrypto-3.dll", "libcrypto-1_1-x64.dll", "libcrypto-1_1.dll", "libeay32.dll"]

        for name in ssl_dll_candidates:
            if (openssl_bin_path / name).exists():
                actual_ssl_dll_path = openssl_bin_path / name
                log.info(f"Found actual SSL DLL: {actual_ssl_dll_path}")
                break
        
        for name in crypto_dll_candidates:
            if (openssl_bin_path / name).exists():
                actual_crypto_dll_path = openssl_bin_path / name
                log.info(f"Found actual Crypto DLL: {actual_crypto_dll_path}")
                break

        if not actual_crypto_dll_path: # Crypto is essential for BN_add etc.
            log.critical(f"CRITICAL: Could not find a known Crypto DLL (e.g., libcrypto-3-x64.dll) in {openssl_bin_path}. The patch will likely fail.")
        else:
            # Pre-load crypto (essential) and ssl (good practice)
            try:
                ctypes.CDLL(str(actual_crypto_dll_path))
                log.info(f"SUCCESS: Explicitly pre-loaded crypto DLL: {actual_crypto_dll_path}")
                if actual_ssl_dll_path: # Only load ssl if found and different from crypto
                     if actual_ssl_dll_path != actual_crypto_dll_path:
                        try:
                            ctypes.CDLL(str(actual_ssl_dll_path))
                            log.info(f"SUCCESS: Explicitly pre-loaded SSL DLL: {actual_ssl_dll_path}")
                        except OSError as e:
                            log.error(f"ERROR: Failed to explicitly pre-load SSL DLL {actual_ssl_dll_path}: {e}")
                     else: # Should not happen with modern OpenSSL but safeguard for ancient libeay32 cases
                        log.info(f"SSL and Crypto DLL paths are the same ({actual_ssl_dll_path}), SSL pre-loading skipped as crypto already loaded.")
                elif not actual_ssl_dll_path: # If no separate SSL DLL was found
                    log.warning(f"No separate SSL DLL found. Assuming crypto DLL ({actual_crypto_dll_path.name}) handles all needs if legacy.")

            except OSError as e:
                log.critical(f"CRITICAL ERROR: Failed to explicitly pre-load crypto DLL {actual_crypto_dll_path}: {e}. This is a fatal issue for the patch.")
                # No point in continuing with the patch if libcrypto can't be loaded.
                sys.exit("Failed to load essential OpenSSL crypto library.")


            # Monkeypatch ctypes.util.find_library
            original_find_library = ctypes.util.find_library
            
            # For python-bitcoinlib, 'ssl' search terms might be used for a library expected to have crypto funcs
            ssl_search_terms = ['ssl', 'ssl.35', 'libeay32', 'ssleay32', 'libssl', # Added libssl generic
                                'libssl-1_1-x64', 'libssl-1_1', 'libssl-3-x64', 'libssl-3'] 
            crypto_search_terms = ['crypto', 'crypto.35', 'eay32', # libeay32 is covered by ssl_search_terms if it's a combined lib
                                   'libcrypto', 'libcrypto-1_1-x64', 'libcrypto-1_1', 
                                   'libcrypto-3-x64', 'libcrypto-3']

            def patched_find_library(name):
                log.debug(f"Patched find_library called for: '{name}'")
                name_lower = name.lower()

                # ** THE DIRTY HACK **
                # If python-bitcoinlib asks for 'ssl' (or related terms), give it libcrypto
                # because it seems to expect crypto functions (like BN_add) from its _ssl handle.
                if actual_crypto_dll_path and any(term == name_lower for term in ssl_search_terms):
                    log.info(f"Patched find_library (SSL HACK): Matched SSL term '{name}'. Returning Crypto DLL: {actual_crypto_dll_path}")
                    return str(actual_crypto_dll_path)
                
                # If it asks for crypto, also give it libcrypto
                if actual_crypto_dll_path and any(term == name_lower for term in crypto_search_terms):
                    log.info(f"Patched find_library: Matched Crypto term '{name}'. Returning Crypto DLL: {actual_crypto_dll_path}")
                    return str(actual_crypto_dll_path)

                log.debug(f"Patched find_library: No specific rule for '{name}', calling original find_library.")
                original_result = original_find_library(name)
                log.debug(f"Original find_library for '{name}' returned: {original_result}")
                return original_result

            ctypes.util.find_library = patched_find_library
            log.info("SUCCESS: Monkeypatched ctypes.util.find_library (Force SSL-terms to Crypto DLL).")
    else:
        log.warning(f"WARNING: Specified OpenSSL directory for pre-loading/patching does not exist: {openssl_bin_path}")

    log.info("!!! Windows OpenSSL DLL configuration & monkeypatching attempt complete !!!")
# --- END WINDOWS OPENSSL DLL HANDLING & MONKEYPATCHING ---

log.info("!!! Root conftest.py IS RUNNING (post-OpenSSL handling) !!!")
# ... (rest of the file remains the same as v1.1.4 / v1.1.3) ...
# --- conftest.py General Info ---
log.info(f"--- conftest.py General Info ---")
log.info(f"Platform: {platform.system()} {platform.architecture()} ({platform.machine()})")
log.info(f"Python Version: {platform.python_version()}")
log.info(f"--- End conftest.py General Info ---\n")


# --- GPG Configuration ---
GPG_HOME_NAME = "gnupg_home_sm_pytest"
try:
    user_home = Path.home()
except Exception as e:
    log.warning(f"Could not determine user home directory: {e}. Defaulting to CWD for GPG_HOME.")
    user_home = Path.cwd()

DEFAULT_GPG_HOME = user_home / GPG_HOME_NAME
GPG_HOME_DIR_FOR_TESTS = Path(os.getenv("GPG_HOME_FOR_TESTS", DEFAULT_GPG_HOME))

def _ensure_gpg_home_exists():
    try:
        if GPG_HOME_DIR_FOR_TESTS.exists():
            if platform.system() != "Windows":
                os.chmod(GPG_HOME_DIR_FOR_TESTS, 0o700)
            log.info(f"GPG_HOME for tests already exists: {GPG_HOME_DIR_FOR_TESTS}")
            return
        
        GPG_HOME_DIR_FOR_TESTS.mkdir(parents=True, exist_ok=True)
        if platform.system() != "Windows":
            os.chmod(GPG_HOME_DIR_FOR_TESTS, 0o700)
        log.info(f"Created GPG_HOME for tests with 700 permissions: {GPG_HOME_DIR_FOR_TESTS}")
    except OSError as e:
        log.error(f"ERROR: Could not create or set permissions for GPG_HOME_DIR_FOR_TESTS '{GPG_HOME_DIR_FOR_TESTS}': {e}")
    except Exception as e:
        log.error(f"ERROR: An unexpected error occurred while ensuring GPG_HOME_DIR_FOR_TESTS: {e}")

_ensure_gpg_home_exists()
os.environ['GNUPGHOME'] = str(GPG_HOME_DIR_FOR_TESTS)
log.info(f"GNUPGHOME environment variable set to: {os.environ['GNUPGHOME']}")

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_gpg_home():
    yield
    try:
        if GPG_HOME_DIR_FOR_TESTS.exists() and GPG_HOME_NAME in str(GPG_HOME_DIR_FOR_TESTS):
            log.info(f"Attempting to remove test GPG home directory: {GPG_HOME_DIR_FOR_TESTS}")
            shutil.rmtree(GPG_HOME_DIR_FOR_TESTS, ignore_errors=True)
            log.info(f"Successfully removed test GPG home directory: {GPG_HOME_DIR_FOR_TESTS}")
        else:
            log.info(f"Test GPG home directory not found, name mismatch, or not managed by this fixture. Skipping removal: {GPG_HOME_DIR_FOR_TESTS}")
    except Exception as e:
        log.error(f"Error removing test GPG home directory '{GPG_HOME_DIR_FOR_TESTS}': {e}")

# --- Asyncio Event Loop Policy (Placeholder) ---
@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        pass 
    else:
        pass

# --- Vault Client Mocking ---
@pytest.fixture(scope='session', autouse=True)
def mock_vault_client_session(request):
    if request.node.get_closest_marker("skip_vault_mock"):
        log.info("Skipping Vault client mock for this test based on 'skip_vault_mock' marker.")
        yield None 
        return

    log.info("Attempting to apply mock for Vault client.")
    mock_client_instance = MagicMock()
    mock_client_instance.is_authenticated.return_value = True
    mock_kv_v2 = MagicMock()
    mock_kv_v2.read_secret_version.return_value = {
        'data': {
            'data': {
                'dummy_secret_key': 'dummy_secret_value',
                'DATABASE_URL': os.getenv('TEST_DATABASE_URL', 'sqlite:///./db_test_mocked_from_vault.sqlite3'),
                'DJANGO_SECRET_KEY': 'fake-test-secret-key-from-mock-vault',
            }
        }
    }
    mock_client_instance.secrets.kv.v2 = mock_kv_v2
    mock_sys_backend = MagicMock()
    mock_sys_backend.is_initialized.return_value = True
    mock_sys_backend.is_sealed.return_value = False
    mock_client_instance.sys = mock_sys_backend
    patch_targets = [
        'hvac.Client',
        'backend.vault_integration.initialize_vault_client',
        'backend.common.utils.vault_utils.initialize_vault_client',
    ]
    active_patches = []
    for target_path in patch_targets:
        try:
            p = patch(target_path, return_value=mock_client_instance)
            p.start()
            active_patches.append(p)
            log.info(f"Successfully patched Vault client at '{target_path}'.")
        except (ModuleNotFoundError, AttributeError):
            log.info(f"Skipping patch for '{target_path}' (not found or import error during patching attempt).")
            pass
    yield mock_client_instance
    for p_item in active_patches:
        try:
            p_item.stop()
        except RuntimeError:
            pass
    if active_patches:
        log.info("Stopped Vault client mocks.")
    else:
        log.info("No Vault client patches were activated.")

# --- Temporary Stubs for Missing Dependencies ---
try:
    import web3
except ImportError:
    log.warning("WORKAROUND: 'web3' library not found. Mocking for test collection. Run 'pip install web3 eth-account'")
    sys.modules['web3'] = MagicMock()
    sys.modules['web3.auto'] = MagicMock()
    sys.modules['web3.providers'] = MagicMock()
    sys.modules['web3.middleware'] = MagicMock()
    sys.modules['web3.exceptions'] = MagicMock()
try:
    import eth_account
except ImportError:
    log.warning("WORKAROUND: 'eth_account' library not found. Mocking for test collection. Run 'pip install web3 eth-account'")
    sys.modules['eth_account'] = MagicMock()
    sys.modules['eth_account.messages'] = MagicMock()

try:
    from backend.store.utils import conversion as backend_conversion_utils
    if not hasattr(backend_conversion_utils, 'btc_to_satoshi') or not hasattr(backend_conversion_utils, 'xmr_to_piconero'):
        log.warning("Module backend.store.utils.conversion found, but missing expected functions. Will attempt to mock if needed by individual tests.")
    else:
        log.info("Module backend.store.utils.conversion and its key functions seem importable.")
except ImportError:
    log.warning("WORKAROUND: Could not import from 'backend.store.utils.conversion'. Mocking for test collection.")
    mock_conversion_module = MagicMock()
    mock_conversion_module.btc_to_satoshi = MagicMock(return_value=0)
    mock_conversion_module.xmr_to_piconero = MagicMock(return_value=0)
    sys.modules['backend.store.utils.conversion'] = mock_conversion_module

try:
    import bitcoinrpc
except ImportError:
    log.warning("WORKAROUND: 'bitcoinrpc' library not found. Bitcoin RPC features will be unavailable. Consider 'pip install python-bitcoinrpc'")

log.info("Conftest setup, including GPG, Vault mocks, and missing dependency stubs (if any), is complete.")