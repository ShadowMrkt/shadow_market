# backend/conftest.py
# Revision: v1.0.1 - Cleaned up duplicate code, added comments.
# Purpose: This root conftest ensures necessary external libraries (like OpenSSL DLLs on Windows)
#          can be found by Python during test execution, which might be required by
#          cryptographic dependencies. It does *not* contain application-level fixtures
#          like database setup or service mocking.

import os
import sys
import platform
import logging # Using logging instead of print for consistency

# Configure basic logging for messages from conftest itself
logging.basicConfig(level=logging.INFO, format='%(levelname)s (conftest): %(message)s')
log = logging.getLogger(__name__)

log.info("!!! Root conftest.py IS RUNNING !!!")

# --- BEGIN USER CONFIGURATION ---
# !!! IMPORTANT: Verify this is the CORRECT path to your OpenSSL bin directory on Windows !!!
# This is needed if Python packages relying on OpenSSL (e.g., cryptography)
# cannot find the required DLLs (libcrypto-*.dll, libssl-*.dll) automatically.
openssl_bin_dir = r'C:\Program Files\OpenSSL-Win64\bin'
# --- END USER CONFIGURATION ---

log.info(f"--- conftest.py Dependency Configuration ---")
log.info(f"Platform: {platform.system()} {platform.architecture()}")
log.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
log.info(f"Checking for OpenSSL directory: {openssl_bin_dir}")

# os.add_dll_directory is available and recommended on Windows in Python 3.8+
# It securely adds a path for DLL resolution for the current process.
if platform.system() == "Windows":
    if sys.version_info >= (3, 8):
        if os.path.isdir(openssl_bin_dir):
            try:
                # This tells Python/OS to look in this directory when loading DLLs
                os.add_dll_directory(openssl_bin_dir)
                log.info(f"SUCCESS: Added '{openssl_bin_dir}' to DLL search path via os.add_dll_directory().")
            except Exception as e:
                # Log error if adding the path fails
                log.error(f"ERROR: Failed to add DLL directory '{openssl_bin_dir}' using os.add_dll_directory(): {e}", exc_info=True)
        else:
            log.warning(f"WARNING: Specified OpenSSL directory does not exist: {openssl_bin_dir}")
            log.warning(f"WARNING: Cryptographic operations might fail if OpenSSL DLLs are needed but not found.")
            log.warning(f"WARNING: Please correct the 'openssl_bin_dir' variable in this conftest.py if needed.")
    else: # Windows but older Python (< 3.8)
        log.warning(f"INFO: Python version {sys.version_info.major}.{sys.version_info.minor} < 3.8.")
        log.warning(f"INFO: Cannot use os.add_dll_directory(). OpenSSL DLLs must be findable via the system PATH environment variable.")
        # You might check if the directory is in PATH as a fallback, but modifying PATH is generally discouraged.
        # path_dirs = [p.lower() for p in os.environ.get('PATH', '').split(os.pathsep)]
        # if openssl_bin_dir.lower() in path_dirs:
        #    log.info(f"INFO: OpenSSL directory '{openssl_bin_dir}' appears to be in the system PATH.")
        # else:
        #    log.warning(f"WARNING: OpenSSL directory '{openssl_bin_dir}' not found in system PATH. Cryptographic libraries may fail to load.")
else: # Not Windows
    log.info("INFO: Not on Windows, OpenSSL discovery typically handled by system package manager/paths. Skipping Windows DLL configuration.")

log.info(f"--- End conftest.py Dependency Configuration ---\n")

# You can add pytest fixtures or other hooks below if needed later
# Example (if you needed shared fixtures):
# import pytest
#
# @pytest.fixture(scope="session")
# def my_session_fixture():
#     # Setup code here
#     log.info("Setting up session fixture")
#     yield "some_session_data"
#     # Teardown code here
#     log.info("Tearing down session fixture")