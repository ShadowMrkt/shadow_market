# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/AnomalyDetectionMiddleware.py
# Revision History:
# - v1.1.0 (2025-04-25):
#   - SECURITY FIX: Corrected IP address extraction logic in `_get_client_ip`. Now correctly takes the *first* IP from the configured header (`REAL_IP_HEADER`) if the `REMOTE_ADDR` is trusted. Removed flawed `NUM_PROXIES` logic.
#   - BEST PRACTICE: Added stronger recommendation to move the duplicated `_get_client_ip` function to a shared utility module.
#   - BEST PRACTICE: Added another warning comment reinforcing that this middleware is not a security control.
# - v1.0.1 (2025-04-24): (Gemini) Corrected SQLI_PATTERNS regex (removed unnecessary escape).
# - v1.0.0 (2025-04-07): Initial Refactor - Applied enterprise hardening concepts:
#   - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, etc.). CRITICAL FIX. (Logic fixed in v1.1.0)
#   - Made middleware enable/disable configurable via settings (ENABLE_ANOMALY_DETECTION, default False).
#   - Made User-Agent check configurable via settings (ENABLE_ANOMALY_UA_CHECK, default False).
#   - Updated JSON body attribute check from _json_body_cache to json_body.
#   - Improved recursive checking for nested lists/dicts in JSON body.
#   - Added strong warnings in code/comments about the limitations of this approach and recommending disabling if a WAF/RASP is used.
#   - Added type hinting.
#   - Refined logging context.

from django.utils.deprecation import MiddlewareMixin
from django.http import HttpRequest, HttpResponse
from django.http import HttpResponse as HttpResponseBase # For type hint compatibility
from django.conf import settings
import logging
import re
from typing import Optional, Dict, List, Any, Union # For type hinting

# Standard logger for general flow, potentially less verbose
logger = logging.getLogger('mymarketplace.middleware.anomalydetection')
# Dedicated security logger for actual detected anomalies
security_logger = logging.getLogger('django.security')

# --- Basic Anomaly Detection Patterns ---
# WARNING: These patterns are extremely rudimentary and easily bypassed.
# They offer minimal protection and should NOT be relied upon for security.
# A proper Web Application Firewall (WAF) or Runtime Application Self-Protection (RASP)
# solution is strongly recommended. Consider disabling this middleware if using a WAF.

# Pre-compile for performance
# CORRECTED: Removed unnecessary escape before '--'
SQLI_PATTERNS = re.compile(r"(\%27)|(\')|(--)|(\%23)|(#)", re.IGNORECASE)
XSS_PATTERNS = re.compile(r"(<script>)|(%3Cscript%3E)|(alert\()|(\bon\w+\s*=)", re.IGNORECASE) # Added basic event handler check
PATH_TRAVERSAL_PATTERNS = re.compile(r"(\.\./)|(%2E%2E%2F)|(\.\.\\)|(%2E%2E\\)") # Added backslash check

# --- Default Configuration ---
DEFAULT_ENABLE_ANOMALY_DETECTION = False # Default to OFF to avoid false sense of security
DEFAULT_ENABLE_ANOMALY_UA_CHECK = False

class AnomalyDetectionMiddleware(MiddlewareMixin):
    """
    Basic anomaly detection middleware for **logging purposes only**.

    Checks request parameters and body for rudimentary suspicious patterns (SQLi, XSS, etc.)
    and logs warnings to the 'django.security' logger. Also includes an optional basic
    User-Agent check.

    ** CRITICAL WARNING **
    This middleware provides VERY LIMITED detection capabilities and is easily bypassed.
    It is **NOT A SUBSTITUTE** for proper input validation within your application logic,
    parameterized database queries, context-aware output encoding, or a dedicated
    Web Application Firewall (WAF) / RASP solution.
    It is recommended to set ENABLE_ANOMALY_DETECTION = False if a WAF is in use.
    Its primary value is potentially identifying extremely basic probes in logs.

    Settings:
        - ENABLE_ANOMALY_DETECTION (bool): Enable/disable the middleware. Default: False.
        - ENABLE_ANOMALY_UA_CHECK (bool): Enable/disable the basic User-Agent check. Default: False.
        - TRUSTED_PROXY_IPS (list): List of trusted upstream proxy IPs. Default: [].
        - REAL_IP_HEADER (str): META key for real IP header. Default: 'HTTP_X_FORWARDED_FOR'.
    """
    # Note: NUM_PROXIES setting is no longer used due to corrected IP logic.

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.enabled = getattr(settings, 'ENABLE_ANOMALY_DETECTION', DEFAULT_ENABLE_ANOMALY_DETECTION)
        self.enable_ua_check = getattr(settings, 'ENABLE_ANOMALY_UA_CHECK', DEFAULT_ENABLE_ANOMALY_UA_CHECK)

        # Trusted proxy settings (copied - should be refactored)
        self.trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
        self.real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')

        if self.enabled:
            logger.info(f"{self.__class__.__name__} enabled. WARNING: Provides minimal security detection, primarily for logging basic patterns. DO NOT rely on this for protection.")
            if not self.trusted_proxies:
                logger.warning(f"{self.__class__.__name__}: TRUSTED_PROXY_IPS setting is empty. IP logging will use REMOTE_ADDR directly.")
        else:
            logger.debug(f"{self.__class__.__name__} is disabled via settings.")

    # <<< BEST PRACTICE: Move this duplicated function to a shared utility module >>>
    # Example: from mymarketplace.middleware.utils import get_client_ip
    def _get_client_ip(self, request: HttpRequest) -> Optional[str]:
        """
        Get the client's real IP address, trusting configured proxies.
        If REMOTE_ADDR is trusted, takes the *first* IP from REAL_IP_HEADER.
        """
        remote_addr = request.META.get('REMOTE_ADDR')
        if not remote_addr:
            logger.error(f"{self.__class__.__name__}: Could not determine REMOTE_ADDR.")
            return None

        ip: Optional[str] = remote_addr # Default to REMOTE_ADDR

        # <<< SECURITY FIX: Corrected logic >>>
        if remote_addr in self.trusted_proxies:
            header_value = request.META.get(self.real_ip_header)
            if header_value:
                try:
                    client_ip = header_value.split(',')[0].strip()
                    if client_ip:
                        ip = client_ip
                    else:
                         logger.warning(
                            f"{self.__class__.__name__}: Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                            f"but the first value was empty. Falling back to REMOTE_ADDR."
                        )
                except IndexError:
                     logger.warning(
                        f"{self.__class__.__name__}: Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                        f"but it was empty or malformed after split. Falling back to REMOTE_ADDR."
                    )
                except Exception as e:
                    logger.warning(
                        f"{self.__class__.__name__}: Error processing {self.real_ip_header} header '{header_value}' from trusted proxy {remote_addr}: {e}. "
                        f"Falling back to REMOTE_ADDR."
                    )
            else:
                logger.warning(
                    f"{self.__class__.__name__}: Trusted proxy {remote_addr} did not provide the expected {self.real_ip_header} header. "
                    f"Falling back to REMOTE_ADDR."
                )
        # else:
            # logger.debug(f"{self.__class__.__name__}: Untrusted REMOTE_ADDR {remote_addr}. Using it as client IP.")

        return ip

    def check_for_patterns(self, data: str, source: str, client_ip: str, request: HttpRequest):
        """Checks data (string) against basic suspicious patterns and logs to security logger."""
        user = request.user
        user_info = f"User: {user.username}" if user and user.is_authenticated else "User: Anonymous" # Added check for user existence
        log_prefix = f"Pattern detected in {source} from {user_info}, IP: {client_ip}, Path: {request.path}"
        # Limit snippet length, avoid newlines in log messages
        data_snippet = data[:100].replace('\n', '\\n').replace('\r', '\\r')

        try:
            if SQLI_PATTERNS.search(data):
                security_logger.warning(f"Potential SQLi pattern ({SQLI_PATTERNS.pattern}) detected | {log_prefix} | Data Snippet: {data_snippet}...")
            if XSS_PATTERNS.search(data):
                security_logger.warning(f"Potential XSS pattern ({XSS_PATTERNS.pattern}) detected | {log_prefix} | Data Snippet: {data_snippet}...")
            if PATH_TRAVERSAL_PATTERNS.search(data):
                security_logger.warning(f"Potential Path Traversal pattern ({PATH_TRAVERSAL_PATTERNS.pattern}) detected | {log_prefix} | Data Snippet: {data_snippet}...")
        except Exception as e:
            # Catch potential regex errors on unusual input
            logger.error(f"Error running regex check in AnomalyDetectionMiddleware for {log_prefix}: {e}", exc_info=True)


    def _recursive_check(self, data: Any, source_prefix: str, client_ip: str, request: HttpRequest):
        """Recursively check data structures (dicts, lists) for suspicious strings."""
        # Add recursion depth limit? Usually unnecessary for request data. max_depth = 10
        if isinstance(data, str):
            self.check_for_patterns(data, source_prefix, client_ip, request)
        elif isinstance(data, dict):
            for key, value in data.items():
                # Check keys? Optional, uncomment if desired.
                # if isinstance(key, str):
                #     self.check_for_patterns(key, f"{source_prefix} dictionary key '{key}'", client_ip, request)
                self._recursive_check(value, f"{source_prefix} key '{key}'", client_ip, request)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                self._recursive_check(item, f"{source_prefix} list index {index}", client_ip, request)
        # Ignore other types (int, float, bool, None, etc.) which are generally safe from these patterns.


    def process_request(self, request: HttpRequest) -> Optional[HttpResponseBase]:
        """Processes the request to check for anomalies if enabled."""
        if not self.enabled:
            return None

        client_ip = self._get_client_ip(request) or "Unknown"

        # --- Check Query Parameters ---
        for key, value in request.GET.items():
            # Query params are always strings
            self.check_for_patterns(value, f"query parameter '{key}'", client_ip, request)
            # Also check key name?
            # self.check_for_patterns(key, "query parameter key", client_ip, request)


        # --- Check Parsed JSON Body (if available from RequestValidationMiddleware) ---
        if hasattr(request, 'json_body') and request.json_body is not None:
            # logger.debug(f"Checking JSON body from IP: {client_ip} for path: {request.path}")
            self._recursive_check(request.json_body, "JSON body", client_ip, request)

        # --- Check POST Form Data (if not JSON and method is POST) ---
        # This assumes RequestValidationMiddleware didn't parse it as JSON
        # and avoids accessing request.body again if json_body exists.
        elif request.method == 'POST' and not hasattr(request, 'json_body'):
             if request.content_type != 'application/json': # Optional check for clarity
                # logger.debug(f"Checking POST form data from IP: {client_ip} for path: {request.path}")
                # Accessing request.POST parses the body if needed (form data)
                for key, value in request.POST.items():
                    if isinstance(value, str):
                        self.check_for_patterns(value, f"form field '{key}'", client_ip, request)
                    # Also check key name?
                    # self.check_for_patterns(key, "form field key", client_ip, request)

                # Consider checking request.FILES for uploaded file names/metadata?
                # for key, uploaded_file in request.FILES.items():
                #     self.check_for_patterns(uploaded_file.name, f"uploaded file name '{key}'", client_ip, request)


        # --- Simple User Agent Check (Optional) ---
        if self.enable_ua_check:
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            if not user_agent or len(user_agent) < 10: # Very basic check for presence and minimal length
                user = request.user
                user_info = f"User: {user.username}" if user and user.is_authenticated else "User: Anonymous"
                security_logger.info( # Use INFO level for UA as it's less critical than pattern matches
                    f"Suspicious User-Agent detected (empty or < 10 chars) | From: {user_info}, IP: {client_ip}, Path: {request.path} | UA: '{user_agent}'"
                )

        # Add more checks here if desired, e.g., checking specific headers for anomalies.
        # Remember the limitations of simple pattern matching.

        # This middleware *only logs* and should never block the request.
        return None

# --- MODIFICATION END ---