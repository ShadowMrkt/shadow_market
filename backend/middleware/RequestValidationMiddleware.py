# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/RequestValidationMiddleware.py
# Revision History:
# 2025-04-07: Initial Refactor - Applied enterprise hardening concepts:
#             - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, etc.). CRITICAL FIX.
#             - Made validation limits configurable via settings (e.g., MAX_GET_PARAMS, MAX_PARAM_VALUE_LEN, MAX_JSON_KEYS).
#             - Changed status code for oversized payload from 403 to 413.
#             - Replaced unreliable request.POST length check with check on parsed JSON body keys.
#             - Renamed request body cache attribute from _json_body_cache to json_body.
#             - Ensured json_body is only set on successful parse.
#             - Added type hinting.
#             - Improved logging clarity.

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging
import json
from typing import Optional, Dict, Any # For type hinting

logger = logging.getLogger(__name__) # Use standard __name__

# --- Default Configuration Values ---
DEFAULT_MAX_GET_PARAMS = 50
DEFAULT_MAX_PARAM_VALUE_LEN = 1024
DEFAULT_MAX_JSON_KEYS = 100
# MAX_UPLOAD_SIZE should primarily be enforced by the web server (Nginx, Apache),
# but Django's DATA_UPLOAD_MAX_MEMORY_SIZE is related for in-memory file handling.
# Using a separate setting here for the Content-Length check is fine.
DEFAULT_MAX_CONTENT_LENGTH = 10 * 1024 * 1024 # Default 10MB, adjust as needed

class RequestValidationMiddleware(MiddlewareMixin):
    """
    Performs basic request validation at the edge:
    - Checks Content-Length against a limit.
    - Attempts to parse JSON body for relevant methods and checks for validity.
    - Limits the number of GET parameters and JSON body keys.
    - Limits the length of individual GET parameter values.
    - Correctly identifies client IP behind trusted proxies.

    Settings:
        - MAX_CONTENT_LENGTH (int): Max allowed Content-Length header value (bytes).
                                    Default: 10485760 (10MB).
        - REQUEST_VALIDATION_MAX_GET_PARAMS (int): Max number of GET parameters. Default: 50.
        - REQUEST_VALIDATION_MAX_PARAM_VALUE_LEN (int): Max length of a GET param value. Default: 1024.
        - REQUEST_VALIDATION_MAX_JSON_KEYS (int): Max number of keys in a parsed JSON object body. Default: 100.
        - TRUSTED_PROXY_IPS (list): List of trusted upstream proxy IPs. Default: [].
        - REAL_IP_HEADER (str): META key for real IP header. Default: 'HTTP_X_FORWARDED_FOR'.
        - NUM_PROXIES (int): Expected number of proxies setting REAL_IP_HEADER. Default: 1.
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)
        # Load configurations from settings, falling back to defaults
        self.max_content_length = getattr(settings, 'MAX_CONTENT_LENGTH', DEFAULT_MAX_CONTENT_LENGTH)
        self.max_get_params = getattr(settings, 'REQUEST_VALIDATION_MAX_GET_PARAMS', DEFAULT_MAX_GET_PARAMS)
        self.max_param_value_len = getattr(settings, 'REQUEST_VALIDATION_MAX_PARAM_VALUE_LEN', DEFAULT_MAX_PARAM_VALUE_LEN)
        self.max_json_keys = getattr(settings, 'REQUEST_VALIDATION_MAX_JSON_KEYS', DEFAULT_MAX_JSON_KEYS)

        # Trusted proxy settings (copied from RateLimitMiddleware for independence)
        self.trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
        self.real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')
        self.num_proxies = getattr(settings, 'NUM_PROXIES', 1)

        if not self.trusted_proxies:
             logger.warning(f"{self.__class__.__name__}: TRUSTED_PROXY_IPS setting is empty. Will use REMOTE_ADDR directly.")


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
                    # Use the first IP, assuming immediate trusted proxy sets it correctly.
                    client_ip_index = 0
                    ip = ips[client_ip_index]
                    logger.debug(f"{self.__class__.__name__}: Trusted proxy {remote_addr} identified. Using IP {ip} from {self.real_ip_header}: {header_value}")
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
            logger.debug(f"{self.__class__.__name__}: Untrusted REMOTE_ADDR {remote_addr}. Using it as client IP.")

        return ip

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        client_ip = self._get_client_ip(request) or "Unknown"

        # 1. Check Content-Length Header early
        try:
            content_length = int(request.META.get('CONTENT_LENGTH', 0))
        except (ValueError, TypeError):
            logger.warning(f"Invalid Content-Length header '{request.META.get('CONTENT_LENGTH')}' from IP: {client_ip} to path: {request.path}. Treating as 0.")
            content_length = 0

        if content_length > self.max_content_length:
            logger.warning(f"Request rejected: Payload too large ({content_length} bytes > {self.max_content_length}) from IP: {client_ip} to path: {request.path}")
            # Use 413 Payload Too Large
            return HttpResponse(
                f"Request entity too large. Maximum size allowed is {self.max_content_length // (1024*1024)}MB.",
                status=413
            )

        # 2. Attempt to parse JSON body for relevant methods, check for malformed JSON
        # Only parse if Content-Type is correct and method expects a body
        if request.method in ['POST', 'PUT', 'PATCH'] and \
           request.content_type == 'application/json':
            # Check content_length again before reading body to avoid large allocation
            # even if header was somehow spoofed/missing but data exists.
            if content_length > self.max_content_length:
                 # This case should have been caught above, but as a safeguard:
                 logger.warning(f"Request rejected: Body read prevented, content length {content_length} exceeds limit {self.max_content_length}. IP: {client_ip}, Path: {request.path}")
                 return HttpResponse("Request entity too large.", status=413)

            try:
                if content_length > 0:
                    # Accessing request.body consumes the stream. Cache the parsed result.
                    # Use request.read() to respect DATA_UPLOAD_MAX_MEMORY_SIZE if applicable,
                    # though Content-Length check should dominate here.
                    # Limit read amount for extra safety? json.loads might handle large strings efficiently.
                    raw_body = request.body # Reads the body
                    parsed_body = json.loads(raw_body)
                    request.json_body = parsed_body # Store parsed body using a clear name
                    logger.debug(f"Successfully parsed JSON body for {request.method} {request.path} from IP: {client_ip}")
                else:
                    # If Content-Length is 0, treat as empty JSON object? Or null?
                    # Let's assume empty object for consistency in downstream access.
                    request.json_body = {}
            except json.JSONDecodeError:
                logger.warning(f"Request rejected: Malformed JSON body from IP: {client_ip} to path: {request.path}")
                return HttpResponseBadRequest("Malformed JSON body.")
            except Exception as e:
                # Catch other potential errors during body reading/parsing (e.g., memory errors?)
                logger.error(f"Error processing JSON body from IP: {client_ip} to path: {request.path}: {e}", exc_info=True)
                return HttpResponseBadRequest("Error processing request body.")

        # 3. Check parameter counts (GET and JSON keys)
        num_get_params = len(request.GET)
        if num_get_params > self.max_get_params:
             logger.warning(f"Request rejected: Excessive number of GET parameters ({num_get_params} > {self.max_get_params}) from IP: {client_ip} to path: {request.path}")
             return HttpResponseBadRequest("Too many GET request parameters.")

        # Check number of keys in parsed JSON body, if it exists and is an object
        if hasattr(request, 'json_body') and isinstance(request.json_body, dict):
            num_json_keys = len(request.json_body)
            if num_json_keys > self.max_json_keys:
                logger.warning(f"Request rejected: Excessive number of JSON keys ({num_json_keys} > {self.max_json_keys}) in body from IP: {client_ip} to path: {request.path}")
                return HttpResponseBadRequest("Too many parameters in JSON body.")

        # 4. Check GET parameter value lengths
        for key, value in request.GET.items():
            if len(value) > self.max_param_value_len:
                logger.warning(f"Request rejected: Excessive parameter length (key: '{key}', length: {len(value)} > {self.max_param_value_len}) from IP: {client_ip} to path: {request.path}")
                return HttpResponseBadRequest(f"Parameter value too long for key '{key}'.")

        return None # Request is valid according to these basic checks

# --- MODIFICATION END ---