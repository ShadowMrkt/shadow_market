# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/ErrorHandlingMiddleware.py
# Revision History:
# - v1.1.0 (2025-04-25):
#   - SECURITY FIX: Corrected IP address extraction logic in `_get_client_ip_for_request`. Now correctly takes the *first* IP from the configured header (`REAL_IP_HEADER`) if the `REMOTE_ADDR` is trusted. Removed flawed `NUM_PROXIES` logic.
#   - BEST PRACTICE: Added recommendation to move IP helper to utils if shared.
#   - BEST PRACTICE: Strengthened comment about using a proper 500.html template.
# - v1.0.0 (2025-04-07): Initial Refactor - Applied enterprise hardening concepts:
#   - Added trusted proxy support for IP address identification via helper function. CRITICAL FIX. (Logic fixed in v1.1.0)
#   - Ensured consistent IP logging in both DRF handler and middleware.
#   - Improved logging in middleware: uses logger.exception for traceback, logs concise error to security log.
#   - Ensured DEBUG=False prevents leak of exception details in JSON response.
#   - Added stronger TODO comment regarding using a proper 500.html template.
#   - Added type hinting.

from django.http import HttpRequest, HttpResponse, JsonResponse, HttpResponseServerError
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
import logging
import traceback
from typing import Optional, Dict, Any, Callable # For type hinting

# Attempt to import DRF components safely
try:
    from rest_framework.views import exception_handler as drf_exception_handler
    from rest_framework.exceptions import APIException
    DRF_AVAILABLE = True
except ImportError:
    drf_exception_handler = None
    APIException = Exception # Fallback base class if DRF not installed
    DRF_AVAILABLE = False

# Use specific logger for this middleware
logger = logging.getLogger('mymarketplace.middleware.errorhandling')
security_logger = logging.getLogger('django.security') # Standard security logger

# --- IP Address Helper ---
# <<< Recommendation: Consider moving this to a shared middleware.utils module if used elsewhere >>>
def _get_client_ip_for_request(request: HttpRequest) -> Optional[str]:
    """
    Get the client's real IP address, trusting configured proxies.
    Reads settings: TRUSTED_PROXY_IPS, REAL_IP_HEADER.

    If REMOTE_ADDR is in TRUSTED_PROXY_IPS, it trusts the *first* IP
    in the REAL_IP_HEADER (e.g., X-Forwarded-For: client, proxy1, proxy2).
    Otherwise, it uses REMOTE_ADDR directly.
    """
    # Load settings within the function scope
    trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
    # Default to 'HTTP_X_FORWARDED_FOR', the most common header
    real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')

    remote_addr = request.META.get('REMOTE_ADDR')
    if not remote_addr:
        logger.error("ErrorHandling: Could not determine REMOTE_ADDR.")
        return None

    ip: Optional[str] = remote_addr # Default to REMOTE_ADDR

    # <<< SECURITY FIX: Simplified and corrected logic >>>
    if remote_addr in trusted_proxies:
        header_value = request.META.get(real_ip_header)
        if header_value:
            # X-Forwarded-For format is "client, proxy1, proxy2", so split and take the first one.
            try:
                # Take the first IP address in the list
                client_ip = header_value.split(',')[0].strip()
                if client_ip: # Ensure it's not an empty string
                    ip = client_ip
                else:
                     logger.warning(
                        f"ErrorHandling: Trusted proxy {remote_addr} provided {real_ip_header} header '{header_value}', "
                        f"but the first value was empty. Falling back to REMOTE_ADDR."
                    )
            except IndexError:
                 logger.warning(
                    f"ErrorHandling: Trusted proxy {remote_addr} provided {real_ip_header} header '{header_value}', "
                    f"but it was empty or malformed after split. Falling back to REMOTE_ADDR."
                )
            except Exception as e:
                # Catch potential unexpected errors during split/strip
                 logger.warning(
                    f"ErrorHandling: Error processing {real_ip_header} header '{header_value}' from trusted proxy {remote_addr}: {e}. "
                    f"Falling back to REMOTE_ADDR."
                )
        else:
            logger.warning(
                f"ErrorHandling: Trusted proxy {remote_addr} did not provide the expected {real_ip_header} header. "
                f"Falling back to REMOTE_ADDR."
            )

    # logger.debug(f"ErrorHandling: Determined client IP as {ip} for request {request.path}")
    return ip


# --- DRF Custom Exception Handler ---
def api_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[HttpResponse]:
    """
    Custom API exception handler for Django REST Framework.
    Logs the error with context (incl. real IP) and returns a standardized JSON error response.
    To use this, set in settings.py:
    REST_FRAMEWORK = { 'EXCEPTION_HANDLER': 'mymarketplace.middleware.ErrorHandlingMiddleware.api_exception_handler' }
    """
    if not DRF_AVAILABLE:
        logger.error("DRF components not found, cannot use api_exception_handler.")
        # Fallback to generic error? Or let Django handle? Let Django handle for now.
        return None # Allow default Django error handling

    # Call REST framework's default exception handler first
    response = drf_exception_handler(exc, context)
    request: Optional[HttpRequest] = context.get('request')

    # --- Logging ---
    user_info = "User: N/A"
    ip_info = "IP: N/A"
    path_info = "Path: N/A"
    if request:
        user = getattr(request, 'user', None)
        user_info = f"User: {user.username}" if user and user.is_authenticated else "User: Anonymous"
        client_ip = _get_client_ip_for_request(request) or "Unknown"
        ip_info = f"IP: {client_ip}"
        path_info = f"Path: {request.path}"

    log_message_prefix = f"DRF API Exception | {path_info} | {user_info}, {ip_info}"
    log_message = f"{log_message_prefix} | {exc.__class__.__name__}: {exc}"

    # Log full traceback using logger.exception
    # Use the specific middleware logger for detailed tracebacks
    logger.exception(log_message, exc_info=True)

    # --- Response Handling ---
    if response is None:
        # Default handler didn't handle it (e.g., non-APIException, server error)
        response_data = {
            "error": "Internal Server Error",
            "detail": "An unexpected server error occurred."
        }
        # Log specifically as unhandled by DRF default to security log
        security_logger.error(f"Unhandled DRF Exception: {log_message}", exc_info=False) # Avoid duplicate traceback in security log
        return JsonResponse(response_data, status=500) # Return immediately for unhandled

    # Customize the response data for handled DRF exceptions
    if isinstance(response.data, dict): # Ensure response.data is a dict before modifying
        # Add a custom error code if it's an APIException
        if isinstance(exc, APIException):
            response.data['error_code'] = getattr(exc, 'default_code', exc.__class__.__name__)

        # Ensure 'detail' key exists for consistency, using DRF's standard representation
        # DRF usually puts detail under 'detail' key or field names for validation errors
        if 'detail' not in response.data and not any(k != 'error_code' for k in response.data):
            # If only 'error_code' is present, add a generic detail
             response.data['detail'] = str(exc.detail if hasattr(exc, 'detail') else exc)

        # **** Security Check: Ensure no sensitive details leak in production ****
        if not settings.DEBUG:
            # If DRF includes non-safe details (e.g. validation errors are usually safe),
            # you might want to sanitize 'detail' further here for certain exception types.
            # Example: Replace generic 500 error details
            if response.status_code >= 500: # Catch 500 and potentially others like 502, 503 if needed
                response.data = {
                    "error": "Internal Server Error",
                    "detail": "An internal server error occurred.",
                    "error_code": "ServerError" # Provide a generic code for 5xx errors
                }

    # Ensure response.data is serializable if we modified it extensively (should be fine here)
    return response


# --- Django Middleware for Non-DRF Exceptions ---
class ErrorHandlingMiddleware(MiddlewareMixin):
    """
    Catches unhandled exceptions outside of DRF views, logs them with context,
    and returns a generic error response (JSON or basic HTML based on Accept header).
    Prevents sensitive information leakage when DEBUG=False.
    Must be placed appropriately in the MIDDLEWARE setting (typically near the top/after security).
    """

    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        # Ignore APIExceptions if DRF is available, let api_exception_handler handle them
        # This check prevents handling the same exception twice.
        if DRF_AVAILABLE and isinstance(exception, APIException):
            return None # Let DRF's handler process it via its mechanism

        # --- Logging ---
        user = getattr(request, 'user', None)
        user_info = f"User: {user.username}" if user and user.is_authenticated else "User: Anonymous"
        client_ip = _get_client_ip_for_request(request) or "Unknown"
        ip_info = f"IP: {client_ip}"
        path_info = f"Path: {request.path}"

        log_message_prefix = f"Unhandled Middleware/View Exception | {path_info} | {user_info}, {ip_info}"
        log_message = f"{log_message_prefix} | {exception.__class__.__name__}: {exception}"

        # Log the full traceback and message using logger.exception
        logger.exception(log_message, exc_info=True)
        # Also log a concise error message to the security log
        security_logger.error(f"Unhandled Exception: {log_message}", exc_info=False)


        # --- Response Generation (Generic Error for Security) ---

        # Default error details (safe for production)
        error_title = "Internal Server Error"
        error_message = "An unexpected server error occurred. Please try again later or contact support if the problem persists."

        # Check if JSON response is preferred
        accept_header = request.META.get('HTTP_ACCEPT', '')
         # Simple check, could be more robust (e.g., using mimeparse library)
        is_json_preferred = 'application/json' in accept_header or request.path.startswith('/api/')

        if is_json_preferred:
            response_data = {
                "error": error_title,
                "detail": error_message # Use 'detail' for consistency with DRF errors
            }
            # **** Security Check: Only add specific details if DEBUG = True ****
            if settings.DEBUG:
                response_data['debug_exception_type'] = exception.__class__.__name__
                response_data['debug_exception_detail'] = str(exception)
                # Avoid sending full traceback in response even in debug mode

            return JsonResponse(response_data, status=500)
        else:
            # Return basic HTML response
            # <<< BEST PRACTICE: Implement a user-friendly 500.html template! >>>
            # This provides a much better user experience than raw HTML.
            # Ensure the template context only contains safe information.
            # from django.shortcuts import render
            # try:
            #     return render(request, '500.html', {'error_message': error_message}, status=500)
            # except Exception as render_exc:
            #      logger.error(f"Error rendering 500.html template: {render_exc}")
            #      # Fallback to raw HTML if template fails

            # Basic fallback HTML (only used if 500.html template is missing or fails)
            html_response = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{error_title}</title>
                <style> body {{ font-family: sans-serif; padding: 20px; }} h1 {{ color: #cc0000; }} </style>
            </head>
            <body>
                <h1>{error_title}</h1>
                <p>{error_message}</p>
                {'' if not settings.DEBUG else ''}
            </body>
            </html>
            """
            return HttpResponseServerError(html_response.strip(), content_type='text/html')

# --- MODIFICATION END ---