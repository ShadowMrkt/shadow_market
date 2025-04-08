# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/ErrorHandlingMiddleware.py
# Revision History:
# 2025-04-07: Initial Refactor - Applied enterprise hardening concepts:
#             - Added trusted proxy support for IP address identification via helper function. CRITICAL FIX.
#             - Ensured consistent IP logging in both DRF handler and middleware.
#             - Improved logging in middleware: uses logger.exception for traceback, logs concise error to security log.
#             - Ensured DEBUG=False prevents leak of exception details in JSON response.
#             - Added stronger TODO comment regarding using a proper 500.html template.
#             - Added type hinting.

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

logger = logging.getLogger(__name__) # Use __name__
security_logger = logging.getLogger('django.security')

# --- IP Address Helper ---
# TODO: Consider moving this to a shared middleware.utils module if used by multiple middleware.
def _get_client_ip_for_request(request: HttpRequest) -> Optional[str]:
    """
    Get the client's real IP address, trusting configured proxies.
    Reads settings: TRUSTED_PROXY_IPS, REAL_IP_HEADER, NUM_PROXIES.
    """
    # Load settings within the function scope or pass them if preferred
    trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
    real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')
    num_proxies = getattr(settings, 'NUM_PROXIES', 1)

    remote_addr = request.META.get('REMOTE_ADDR')
    if not remote_addr:
        logger.error("ErrorHandling: Could not determine REMOTE_ADDR.")
        return None

    ip: Optional[str] = None
    if remote_addr in trusted_proxies:
        header_value = request.META.get(real_ip_header)
        if header_value:
            ips = [ip.strip() for ip in header_value.split(',')]
            if len(ips) >= num_proxies:
                client_ip_index = 0 # Assume first IP when set by trusted proxy
                ip = ips[client_ip_index]
            else:
                logger.warning(
                    f"ErrorHandling: Trusted proxy {remote_addr} provided {real_ip_header} header '{header_value}', "
                    f"but not enough IPs found for NUM_PROXIES={num_proxies}. Falling back to REMOTE_ADDR."
                )
                ip = remote_addr
        else:
            logger.warning(
                f"ErrorHandling: Trusted proxy {remote_addr} did not provide the expected {real_ip_header} header. "
                f"Falling back to REMOTE_ADDR."
                )
            ip = remote_addr
    else:
        ip = remote_addr

    # Log IP source only once per request if needed for debugging elsewhere
    # logger.debug(f"ErrorHandling: Using client IP {ip} for request {request.path}")
    return ip


# --- DRF Custom Exception Handler ---
def api_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[HttpResponse]:
    """
    Custom API exception handler for Django REST Framework.
    Logs the error with context (incl. real IP) and returns a standardized JSON error response.
    To use this, set in settings.py:
    REST_FRAMEWORK = { 'EXCEPTION_HANDLER': 'path.to.api_exception_handler' }
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

    log_message = f"DRF API Exception | {path_info} | {user_info}, {ip_info} | {exc.__class__.__name__}: {exc}"

    # Log full traceback using logger.exception
    logger.exception(log_message, exc_info=True) # exc_info=True is default for logger.exception

    # --- Response Handling ---
    if response is None:
        # Default handler didn't handle it (e.g., non-APIException, server error)
        response_data = {
            "error": "Internal Server Error",
            "detail": "An unexpected server error occurred."
        }
        # Log specifically as unhandled by DRF default
        security_logger.error(f"Unhandled DRF Exception: {log_message}", exc_info=False) # Avoid duplicate traceback in security log
        response = JsonResponse(response_data, status=500)
        return response # Return immediately for unhandled

    # Customize the response data for handled DRF exceptions
    if isinstance(response.data, dict): # Ensure response.data is a dict before modifying
        # Add a custom error code if it's an APIException
        if isinstance(exc, APIException):
            response.data['error_code'] = getattr(exc, 'default_code', exc.__class__.__name__)

        # Ensure 'detail' key exists for consistency, using DRF's standard representation
        if 'detail' not in response.data:
             response.data['detail'] = str(exc.detail if hasattr(exc, 'detail') else exc)

        # **** Security Check: Ensure no sensitive details leak in production ****
        if not settings.DEBUG:
            # If DRF includes non-safe details (e.g. validation errors are usually safe),
            # you might want to sanitize 'detail' further here for certain exception types.
            # Example: Replace generic 500 error details
            if response.status_code == 500:
                 response.data['detail'] = "An internal server error occurred."
                 response.data['error'] = "Internal Server Error" # Ensure consistent key

    return response


# --- Django Middleware for Non-DRF Exceptions ---
class ErrorHandlingMiddleware(MiddlewareMixin):
    """
    Catches unhandled exceptions outside of DRF views, logs them with context,
    and returns a generic error response (JSON or basic HTML based on Accept header).
    Prevents sensitive information leakage when DEBUG=False.
    """

    # No __init__ needed unless we add middleware-specific config

    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        # Ignore APIExceptions if DRF is available, let api_exception_handler handle them
        if DRF_AVAILABLE and isinstance(exception, APIException):
            return None # Let DRF's handler process it via its mechanism

        # --- Logging ---
        user = getattr(request, 'user', None)
        user_info = f"User: {user.username}" if user and user.is_authenticated else "User: Anonymous"
        client_ip = _get_client_ip_for_request(request) or "Unknown"
        ip_info = f"IP: {client_ip}"
        path_info = f"Path: {request.path}"

        log_message = f"Unhandled Middleware/View Exception | {path_info} | {user_info}, {ip_info} | {exception.__class__.__name__}: {exception}"

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
        is_json_preferred = 'application/json' in accept_header or request.path.startswith('/api/') # Assume /api/ paths want JSON

        if is_json_preferred:
            response_data = {
                "error": error_title,
                "detail": error_message # Use 'detail' for consistency with DRF errors
            }
            # **** Security Check: Only add specific details if DEBUG = True ****
            if settings.DEBUG:
                response_data['debug_exception_type'] = exception.__class__.__name__
                response_data['debug_exception_detail'] = str(exception)
                # Avoid sending full traceback in response even in debug mode usually

            return JsonResponse(response_data, status=500)
        else:
            # Return basic HTML response
            # TODO: Implement a user-friendly 500.html template!
            # from django.shortcuts import render
            # return render(request, '500.html', {'error_message': error_message}, status=500)

            # Basic fallback HTML
            html_response = f"""
            <!DOCTYPE html>
            <html>
            <head><title>{error_title}</title></head>
            <body>
                <h1>{error_title}</h1>
                <p>{error_message}</p>
                {f'<p><pre>Debug Info: {exception.__class__.__name__}: {exception}</pre></p>' if settings.DEBUG else ''}
            </body>
            </html>
            """
            return HttpResponseServerError(html_response, content_type='text/html')

# --- MODIFICATION END ---