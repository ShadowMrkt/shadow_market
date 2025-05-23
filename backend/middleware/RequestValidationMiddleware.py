# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/RequestValidationMiddleware.py
# Revision History:
# - v1.1.0 (2025-04-25):
#   - SECURITY FIX: Corrected IP address extraction logic in `_get_client_ip`. Now correctly takes the *first* IP from the configured header (`REAL_IP_HEADER`) if the `REMOTE_ADDR` is trusted. Removed flawed `NUM_PROXIES` logic.
#   - BEST PRACTICE: Added stronger recommendation to move the duplicated `_get_client_ip` function to a shared utility module.
# - v1.0.0 (2025-04-07): Initial Refactor - Applied enterprise hardening concepts:
#   - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, etc.). CRITICAL FIX. (Logic fixed in v1.1.0)
#   - Made validation limits configurable via settings (e.g., MAX_GET_PARAMS, MAX_PARAM_VALUE_LEN, MAX_JSON_KEYS).
#   - Changed status code for oversized payload from 403 to 413.
#   - Replaced unreliable request.POST length check with check on parsed JSON body keys.
#   - Renamed request body cache attribute from _json_body_cache to json_body.
#   - Ensured json_body is only set on successful parse.
#   - Added type hinting.
#   - Improved logging clarity.

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.http import HttpResponse as HttpResponseBase # For type hint compatibility in process_request
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging
import json
from typing import Optional, Dict, Any # For type hinting

# Use specific logger for this middleware
logger = logging.getLogger('mymarketplace.middleware.requestvalidation')

# --- Default Configuration Values ---
DEFAULT_MAX_GET_PARAMS = 50
DEFAULT_MAX_PARAM_VALUE_LEN = 1024
DEFAULT_MAX_JSON_KEYS = 100
# MAX_UPLOAD_SIZE should primarily be enforced by the web server (Nginx, Apache),
# but Django's DATA_UPLOAD_MAX_MEMORY_SIZE is related for in-memory file handling.
# Using a separate setting here for the Content-Length check is sensible.
DEFAULT_MAX_CONTENT_LENGTH = 10 * 1024 * 1024 # Default 10MB, adjust as needed

class RequestValidationMiddleware(MiddlewareMixin):
    """
    Performs basic request validation at the edge:
    - Checks Content-Length against a limit.
    - Attempts to parse JSON body for relevant methods and checks for validity/key limits.
    - Limits the number of GET parameters and individual value lengths.
    - Correctly identifies client IP behind trusted proxies.

    Settings:
        - MAX_CONTENT_LENGTH (int): Max allowed Content-Length header value (bytes).
                                    Default: 10485760 (10MB).
        - REQUEST_VALIDATION_MAX_GET_PARAMS (int): Max number of GET parameters. Default: 50.
        - REQUEST_VALIDATION_MAX_PARAM_VALUE_LEN (int): Max length of a GET param value. Default: 1024.
        - REQUEST_VALIDATION_MAX_JSON_KEYS (int): Max number of keys in a parsed JSON object body. Default: 100.
        - TRUSTED_PROXY_IPS (list): List of trusted upstream proxy IPs. Default: [].
        - REAL_IP_HEADER (str): META key for real IP header. Default: 'HTTP_X_FORWARDED_FOR'.
    """
    # Note: NUM_PROXIES setting is no longer used due to corrected IP logic.

    def __init__(self, get_response=None):
        super().__init__(get_response)
        # Load configurations from settings, falling back to defaults
        self.max_content_length = getattr(settings, 'MAX_CONTENT_LENGTH', DEFAULT_MAX_CONTENT_LENGTH)
        self.max_get_params = getattr(settings, 'REQUEST_VALIDATION_MAX_GET_PARAMS', DEFAULT_MAX_GET_PARAMS)
        self.max_param_value_len = getattr(settings, 'REQUEST_VALIDATION_MAX_PARAM_VALUE_LEN', DEFAULT_MAX_PARAM_VALUE_LEN)
        self.max_json_keys = getattr(settings, 'REQUEST_VALIDATION_MAX_JSON_KEYS', DEFAULT_MAX_JSON_KEYS)

        # Trusted proxy settings (copied - should be refactored)
        self.trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
        self.real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')

        if not self.trusted_proxies:
             logger.warning(f"{self.__class__.__name__}: TRUSTED_PROXY_IPS setting is empty. Will use REMOTE_ADDR directly.")

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
                # X-Forwarded-For format is "client, proxy1, proxy2", so split and take the first one.
                try:
                    client_ip = header_value.split(',')[0].strip()
                    if client_ip: # Ensure it's not an empty string
                        ip = client_ip
                        # logger.debug(f"{self.__class__.__name__}: Trusted proxy {remote_addr} identified. Using IP {ip} from {self.real_ip_header}: {header_value}")
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

    def process_request(self, request: HttpRequest) -> Optional[HttpResponseBase]:
        """Validates the incoming request against configured limits."""
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
            # Use HttpResponse directly for simple text response
            return HttpResponse(
                f"Request entity too large. Maximum size allowed is {self.max_content_length // (1024*1024)}MB.",
                status=413,
                content_type='text/plain' # Explicitly set content type
            )

        # 2. Attempt to parse JSON body for relevant methods, check for malformed JSON
        # Only parse if Content-Type is correct and method expects a body
        if request.method in ['POST', 'PUT', 'PATCH'] and \
           request.content_type == 'application/json':
            # Check content_length again before reading body as safeguard
            if content_length > self.max_content_length:
                # This case should have been caught above, but for extra safety:
                logger.warning(f"Request rejected: Body read prevented, content length {content_length} exceeds limit {self.max_content_length}. IP: {client_ip}, Path: {request.path}")
                return HttpResponse("Request entity too large.", status=413, content_type='text/plain')

            try:
                # Clear any previously attached body (if middleware runs multiple times?)
                if hasattr(request, 'json_body'):
                    delattr(request, 'json_body')

                if content_length > 0:
                    # Accessing request.body consumes the stream.
                    # Read limited amount? No, json.loads handles large strings but Content-Length check protects memory.
                    raw_body = request.body # Reads the body
                    if not raw_body:
                        # Edge case: Content-Length > 0 but body is empty?
                        logger.warning(f"Request has Content-Length {content_length} but body is empty. IP: {client_ip}, Path: {request.path}. Treating as empty JSON.")
                        parsed_body = {}
                    else:
                        parsed_body = json.loads(raw_body)

                    request.json_body = parsed_body # Store parsed body using a clear name
                    # logger.debug(f"Successfully parsed JSON body for {request.method} {request.path} from IP: {client_ip}")
                else:
                    # If Content-Length is 0, treat as empty JSON object.
                    request.json_body = {}

            except json.JSONDecodeError:
                logger.warning(f"Request rejected: Malformed JSON body from IP: {client_ip} to path: {request.path}")
                return HttpResponseBadRequest("Malformed JSON body.", content_type='text/plain')
            except Exception as e:
                # Catch other potential errors during body reading/parsing
                logger.error(f"Error processing JSON body from IP: {client_ip} to path: {request.path}: {e}", exc_info=True)
                # Return generic bad request here, not 500, as it's likely client input issue
                return HttpResponseBadRequest("Error processing request body.", content_type='text/plain')

        # 3. Check parameter counts (GET and JSON keys)
        num_get_params = len(request.GET)
        if num_get_params > self.max_get_params:
             logger.warning(f"Request rejected: Excessive number of GET parameters ({num_get_params} > {self.max_get_params}) from IP: {client_ip} to path: {request.path}")
             return HttpResponseBadRequest("Too many GET request parameters.", content_type='text/plain')

        # Check number of keys in parsed JSON body, if it exists and is an object
        if hasattr(request, 'json_body') and isinstance(request.json_body, dict):
            num_json_keys = len(request.json_body)
            if num_json_keys > self.max_json_keys:
                logger.warning(f"Request rejected: Excessive number of JSON keys ({num_json_keys} > {self.max_json_keys}) in body from IP: {client_ip} to path: {request.path}")
                return HttpResponseBadRequest("Too many parameters in JSON body.", content_type='text/plain')
        # Consider adding check for JSON list length? Probably less critical than key count.

        # 4. Check GET parameter value lengths
        for key, value in request.GET.items():
            # Should we check key length too? Less common issue.
            if len(value) > self.max_param_value_len:
                logger.warning(f"Request rejected: Excessive parameter length (key: '{key}', length: {len(value)} > {self.max_param_value_len}) from IP: {client_ip} to path: {request.path}")
                # Encode key safely in response? For now, just include it.
                return HttpResponseBadRequest(f"Parameter value too long for key '{key}'.", content_type='text/plain')

        return None # Request is valid according to these basic checks

# --- MODIFICATION END ---