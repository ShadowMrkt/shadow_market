# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/AnomalyDetectionMiddleware.py
# Revision History:
# 2025-04-07: Initial Refactor - Applied enterprise hardening concepts:
#             - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, etc.). CRITICAL FIX.
#             - Made middleware enable/disable configurable via settings (ENABLE_ANOMALY_DETECTION, default False).
#             - Made User-Agent check configurable via settings (ENABLE_ANOMALY_UA_CHECK, default False).
#             - Updated JSON body attribute check from _json_body_cache to json_body.
#             - Improved recursive checking for nested lists/dicts in JSON body.
#             - Added strong warnings in code/comments about the limitations of this approach and recommending disabling if a WAF/RASP is used.
#             - Added type hinting.
#             - Refined logging context.

from django.utils.deprecation import MiddlewareMixin
from django.http import HttpRequest, HttpResponse
from django.conf import settings
import logging
import re
from typing import Optional, Dict, List, Any, Union # For type hinting

# Standard logger for general flow, potentially less verbose
logger = logging.getLogger(__name__)
# Dedicated security logger for actual detected anomalies
security_logger = logging.getLogger('django.security')

# --- Basic Anomaly Detection Patterns ---
# WARNING: These patterns are extremely rudimentary and easily bypassed.
# They offer minimal protection and should NOT be relied upon for security.
# A proper Web Application Firewall (WAF) or Runtime Application Self-Protection (RASP)
# solution is strongly recommended. Consider disabling this middleware if using a WAF.

# Pre-compile for performance
SQLI_PATTERNS = re.compile(r"(\%27)|(\')|(\-\-)|(\%23)|(#)", re.IGNORECASE)
XSS_PATTERNS = re.compile(r"(<script>)|(%3Cscript%3E)|(alert\()|(\bon\w+\s*=)", re.IGNORECASE) # Added basic event handler check
PATH_TRAVERSAL_PATTERNS = re.compile(r"(\.\./)|(%2E%2E%2F)|(\.\.\\)|(%2E%2E\\)") # Added backslash check

# --- Default Configuration ---
DEFAULT_ENABLE_ANOMALY_DETECTION = False # Default to OFF to avoid false sense of security
DEFAULT_ENABLE_ANOMALY_UA_CHECK = False

class AnomalyDetectionMiddleware(MiddlewareMixin):
    """
    Basic anomaly detection middleware for logging purposes only.

    Checks request parameters and body for rudimentary suspicious patterns (SQLi, XSS, etc.)
    and logs warnings to the 'django.security' logger. Also includes an optional basic
    User-Agent check.

    ** CRITICAL WARNING **
    This middleware provides VERY LIMITED detection capabilities and is easily bypassed.
    It is NOT a substitute for proper input validation within your application logic,
    parameterized database queries, context-aware output encoding, or a dedicated
    Web Application Firewall (WAF) / RASP solution.
    It is recommended to set ENABLE_ANOMALY_DETECTION = False if a WAF is in use.

    Settings:
        - ENABLE_ANOMALY_DETECTION (bool): Enable/disable the middleware. Default: False.
        - ENABLE_ANOMALY_UA_CHECK (bool): Enable/disable the basic User-Agent check. Default: False.
        - TRUSTED_PROXY_IPS (list): List of trusted upstream proxy IPs. Default: [].
        - REAL_IP_HEADER (str): META key for real IP header. Default: 'HTTP_X_FORWARDED_FOR'.
        - NUM_PROXIES (int): Expected number of proxies setting REAL_IP_HEADER. Default: 1.
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.enabled = getattr(settings, 'ENABLE_ANOMALY_DETECTION', DEFAULT_ENABLE_ANOMALY_DETECTION)
        self.enable_ua_check = getattr(settings, 'ENABLE_ANOMALY_UA_CHECK', DEFAULT_ENABLE_ANOMALY_UA_CHECK)

        # Trusted proxy settings (copied for independence)
        self.trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
        self.real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')
        self.num_proxies = getattr(settings, 'NUM_PROXIES', 1)

        if self.enabled:
            logger.info(f"{self.__class__.__name__} enabled. WARNING: Provides minimal security, primarily for logging basic patterns.")
            if not self.trusted_proxies:
                logger.warning(f"{self.__class__.__name__}: TRUSTED_PROXY_IPS setting is empty. IP logging will use REMOTE_ADDR directly.")
        else:
             logger.debug(f"{self.__class__.__name__} is disabled via settings.")


    def _get_client_ip(self, request: HttpRequest) -> Optional[str]:
        """
        Get the client's real IP address, trusting configured proxies.
        (Copied from ConfigurableRateLimitMiddleware - consider moving to a shared util)
        """
        remote_addr = request.META.get('REMOTE_ADDR')
        if not remote_addr:
            logger.error(f"{self.__class__.__name__}: Could not determine REMOTE_ADDR.")
            return None

        ip: Optional[str] = None
        if remote_addr in self.trusted_proxies:
            header_value = request.META.get(self.real_ip_header)
            if header_value:
                ips = [ip.strip() for ip in header_value.split(',')]
                if len(ips) >= self.num_proxies:
                    client_ip_index = 0
                    ip = ips[client_ip_index]
                else:
                    logger.warning(
                        f"{self.__class__.__name__}: Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                        f"but not enough IPs found for NUM_PROXIES={self.num_proxies}. Falling back to REMOTE_ADDR."
                    )
                    ip = remote_addr
            else:
                logger.warning(
                    f"{self.__class__.__name__}: Trusted proxy {remote_addr} did not provide the expected {self.real_ip_header} header. "
                    f"Falling back to REMOTE_ADDR."
                 )
                ip = remote_addr
        else:
            ip = remote_addr

        # Log IP source only once per request if needed for debugging elsewhere
        # logger.debug(f"{self.__class__.__name__}: Using client IP {ip} for request {request.path}")
        return ip

    def check_for_patterns(self, data: str, source: str, client_ip: str, request: HttpRequest):
        """Checks data (string) against basic suspicious patterns and logs."""
        user = request.user
        user_info = f"User: {user.username}" if user.is_authenticated else "User: Anonymous"
        log_prefix = f"{source} from {user_info}, IP: {client_ip}, Path: {request.path}"
        data_snippet = data[:100].replace('\n', ' ').replace('\r', '') # Avoid multi-line snippets in logs

        try:
            if SQLI_PATTERNS.search(data):
                security_logger.warning(f"Potential SQLi pattern detected in {log_prefix}. Data: {data_snippet}...")
            if XSS_PATTERNS.search(data):
                security_logger.warning(f"Potential XSS pattern detected in {log_prefix}. Data: {data_snippet}...")
            if PATH_TRAVERSAL_PATTERNS.search(data):
                security_logger.warning(f"Potential Path Traversal pattern detected in {log_prefix}. Data: {data_snippet}...")
        except Exception as e:
             # Catch potential regex errors on unusual input, though unlikely with simple patterns
             logger.error(f"Error running regex check in {log_prefix}: {e}", exc_info=True)


    def _recursive_check(self, data: Any, source_prefix: str, client_ip: str, request: HttpRequest):
        """Recursively check data structures (dicts, lists) for suspicious strings."""
        if isinstance(data, str):
            self.check_for_patterns(data, source_prefix, client_ip, request)
        elif isinstance(data, dict):
            for key, value in data.items():
                # Also check the key itself? Usually less critical but possible.
                # if isinstance(key, str):
                #     self.check_for_patterns(key, f"{source_prefix} dictionary key", client_ip, request)
                self._recursive_check(value, f"{source_prefix} key '{key}'", client_ip, request)
        elif isinstance(data, list):
            for index, item in enumerate(data):
                self._recursive_check(item, f"{source_prefix} list index {index}", client_ip, request)
        # Ignore other types (int, bool, None, etc.)


    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        if not self.enabled:
            return None

        client_ip = self._get_client_ip(request) or "Unknown"

        # --- Check Query Parameters ---
        for key, value in request.GET.items():
            # Query params are always strings
             self.check_for_patterns(value, f"query parameter '{key}'", client_ip, request)

        # --- Check Parsed JSON Body (if available) ---
        # Use 'json_body' attribute set by RequestValidationMiddleware
        if hasattr(request, 'json_body'):
            logger.debug(f"Checking JSON body from IP: {client_ip} for path: {request.path}")
            self._recursive_check(request.json_body, "JSON body", client_ip, request)

        # --- Check POST Form Data (if not JSON and method is POST) ---
        # This assumes RequestValidationMiddleware didn't parse it as JSON
        elif request.method == 'POST':
            # Accessing request.POST might parse the body if not already done.
            # Check Content-Type to be more specific? application/x-www-form-urlencoded etc.
            if request.content_type != 'application/json': # Redundant check, but clearer intent
                 logger.debug(f"Checking POST form data from IP: {client_ip} for path: {request.path}")
                 for key, value in request.POST.items():
                     if isinstance(value, str): # POST values can sometimes be other types? Unlikely here.
                         self.check_for_patterns(value, f"form field '{key}'", client_ip, request)
                     # Could potentially check uploaded file names in request.FILES here too, if desired.

        # --- Simple User Agent Check (Optional) ---
        if self.enable_ua_check:
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            if not user_agent or len(user_agent) < 10: # Very basic check
                 user = request.user
                 user_info = f"User: {user.username}" if user.is_authenticated else "User: Anonymous"
                 security_logger.info( # Use INFO level for UA as it's less critical than pattern matches
                     f"Suspicious User-Agent detected (empty or short) from {user_info}, IP: {client_ip}, Path: {request.path}. UA: '{user_agent}'"
                 )

        # Add more checks here if desired, e.g., checking specific headers. Remember limitations.

        return None # Never block requests, only log potential anomalies.

# --- MODIFICATION END ---