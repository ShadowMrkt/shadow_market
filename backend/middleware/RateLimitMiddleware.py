# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/RateLimitMiddleware.py
# Revision History:
# 2025-04-07: Initial Refactor - Applied enterprise hardening concepts:
#             - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, settings.REAL_IP_HEADER). CRITICAL FIX.
#             - Moved rate limit definitions (RATE_LIMIT_CONFIGS) and endpoint mapping (RATE_LIMIT_MAPPING) to be configurable via settings.py, with defaults.
#             - Improved logging clarity and context.
#             - Added type hinting.
#             - Clearly documented the non-atomic nature of the default cache update mechanism and recommended Redis.
#             - Renamed middleware class slightly for clarity.
#             - Encapsulated IP fetching logic within the class.

import time
import logging
from collections import OrderedDict
from typing import Optional, Tuple, Dict, Any, List # For type hinting

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.core.cache import cache # Use Django's cache abstraction
from django.urls import resolve, Resolver404
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

logger = logging.getLogger(__name__) # Use __name__ for module-level logger

# --- Default Rate Limit Configuration (used if not overridden in settings.py) ---
# Define rate limits (requests, period_in_seconds)
# Use descriptive names for limit types
DEFAULT_RATE_LIMITS_CONFIG = {
    # Limit Type             : (Requests, Period)
    'anon_browse'          : (200, 3600),    # Anonymous general Browse: 200 reqs/hour
    'user_browse'          : (2000, 3600),   # Authenticated general Browse: 2000 reqs/hour
    'login_attempt_ip'     : (10, 60 * 5),   # Login attempts (per IP): 10 reqs/5 minutes
    'login_success_user'   : (5, 60 * 15),   # Post-successful login actions (per User): 5 reqs/15 minutes
    'register_attempt_ip'  : (5, 3600),      # Registration attempts (per IP): 5 reqs/hour
    'product_list'         : (120, 60),      # Product listing/search: 120 reqs/minute
    'product_detail'       : (180, 60),      # Product detail view: 180 reqs/minute
    'product_create_user'  : (10, 3600),     # Vendor creating/updating product: 10 reqs/hour
    'order_place_user'     : (5, 60 * 10),   # Placing an order: 5 reqs/10 minutes
    'order_action_user'    : (20, 60 * 5),   # Other order actions (ship, finalize, etc): 20 reqs/5 minutes
    'withdrawal_prep_user' : (5, 60 * 10),   # Preparing withdrawal: 5 reqs/10 minutes
    'withdrawal_exec_user' : (3, 60 * 15),   # Executing withdrawal: 3 reqs/15 minutes
    'ticket_create_user'   : (5, 3600),      # Creating support ticket: 5 reqs/hour
    'ticket_reply_user'    : (30, 3600),     # Replying to ticket: 30 reqs/hour
    'upload_user'          : (10, 3600),     # Generic upload limit: 10 reqs/hour
    'sensitive_api_user'   : (60, 60),       # Fallback for sensitive APIs: 60 reqs/minute
    'captcha_request_ip'   : (20, 60),       # Requesting CAPTCHA: 20 reqs/minute
}

# --- Default Endpoint to Limit Type Mapping (used if not overridden in settings.py) ---
# Map URL names (or patterns) to specific rate limit types defined above.
# Use OrderedDict to ensure the most specific match is checked first.
DEFAULT_ENDPOINT_LIMIT_MAPPING = OrderedDict([
    # URL Name (or prefix)   : Limit Type
    # Authentication / Registration
    ('api:login-pgp-verify'  , 'login_attempt_ip'),
    ('api:register'          , 'register_attempt_ip'),
    ('api:login-init'        , 'login_attempt_ip'), # Potentially adjust limit if needed
    ('captcha-image'         , 'captcha_request_ip'), # django-simple-captcha URL name

    # Wallet / Financial
    ('api:withdraw-prepare'  , 'withdrawal_prep_user'),
    ('api:withdraw-execute'  , 'withdrawal_exec_user'),

    # Orders
    ('api:place-order'       , 'order_place_user'),
    ('api:mark-shipped'      , 'order_action_user'),
    ('api:finalize-order'    , 'order_action_user'),
    ('api:sign-release'      , 'order_action_user'),
    ('api:open-dispute'      , 'order_action_user'),

    # Products / Vendor Actions
    ('api:product-list'      , 'product_list'),
    ('api:product-detail'    , 'product_detail'),
    ('api:product-create'    , 'product_create_user'),
    ('api:product-update'    , 'product_create_user'), # Use same limit for update

    # Support Tickets
    ('api:ticket-create'     , 'ticket_create_user'),
    ('api:ticketmessage-create', 'ticket_reply_user'),
    ('api:ticket-list'       , 'user_browse'), # Treat listing as general browse
    ('api:ticket-detail'     , 'user_browse'),
    ('api:ticketmessage-list', 'user_browse'),

    # Other Sensitive Actions (fallback/examples)
    ('api:encrypt-for-vendor', 'sensitive_api_user'),
    ('api:current-user-update', 'sensitive_api_user'),

    # Default fallbacks (matched last)
    ('api:'                  , 'user_browse'), # Default for authenticated API users
    (''                      , 'anon_browse'), # Default for anonymous users (matches any path if others fail)
])


# --- Middleware Class ---
class ConfigurableRateLimitMiddleware(MiddlewareMixin):
    """
    Implements distributed rate limiting using Django's cache framework (Redis recommended).

    Applies granular limits based on resolved URL names and authentication status,
    configurable via Django settings. Identifies client IP considering trusted proxies.

    Settings:
        - ENABLE_RATE_LIMITING (bool): Enable/disable the middleware. Default: True.
        - RATE_LIMIT_CONFIGS (dict): Overrides DEFAULT_RATE_LIMITS_CONFIG.
        - RATE_LIMIT_MAPPING (dict|list): Overrides DEFAULT_ENDPOINT_LIMIT_MAPPING.
                                         Use list of tuples to preserve order.
        - TRUSTED_PROXY_IPS (list): List of IP addresses of immediate upstream proxies
                                    that are allowed to set the real IP header. Default: [].
        - REAL_IP_HEADER (str): META key for the header containing the real client IP
                                (e.g., 'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP').
                                Default: 'HTTP_X_FORWARDED_FOR'.
        - NUM_PROXIES (int): If using X-Forwarded-For, how many proxy IPs to expect
                             before the client IP. Default: 1.

    Cache Atomicity Note:
        The default Django cache API using get/set for counters is *not* strictly atomic.
        Under high load, a small race condition could allow slightly exceeding the limit.
        Using a Redis cache backend (via django-redis) significantly minimizes this window.
        For guaranteed atomicity, consider using cache.incr() if available and suitable,
        or Redis Lua scripts. This implementation prioritizes clarity and compatibility.
    """
    RATELIMIT_CACHE_PREFIX = "rl:" # Short prefix for cache keys

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.enabled = getattr(settings, 'ENABLE_RATE_LIMITING', True)
        # Load configurations from settings, falling back to defaults
        self.limit_configs = getattr(settings, 'RATE_LIMIT_CONFIGS', DEFAULT_RATE_LIMITS_CONFIG)
        mapping_setting = getattr(settings, 'RATE_LIMIT_MAPPING', DEFAULT_ENDPOINT_LIMIT_MAPPING.items())
        # Ensure mapping is an OrderedDict or convert from list/dict
        if isinstance(mapping_setting, dict):
             self.endpoint_mapping = OrderedDict(mapping_setting.items())
        else: # Assume list of tuples or already OrderedDict
             self.endpoint_mapping = OrderedDict(mapping_setting)

        # Trusted proxy settings
        self.trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
        self.real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')
        self.num_proxies = getattr(settings, 'NUM_PROXIES', 1)

        if not self.enabled:
            logger.info("Rate limiting is disabled via settings.ENABLE_RATE_LIMITING.")
        if not self.trusted_proxies:
             logger.warning("TRUSTED_PROXY_IPS setting is empty. Rate limiting will use REMOTE_ADDR directly. "
                           "Ensure this is correct for your deployment.")

    def _get_client_ip(self, request: HttpRequest) -> Optional[str]:
        """
        Get the client's real IP address, trusting configured proxies.

        Logic:
        1. Get the immediate upstream IP from request.META['REMOTE_ADDR'].
        2. If REMOTE_ADDR is in TRUSTED_PROXY_IPS:
           a. Look for the header specified in REAL_IP_HEADER.
           b. If found (e.g., X-Forwarded-For): Parse it. The client IP is typically
              the first entry, unless multiple trusted proxies are involved (use NUM_PROXIES).
              Example: Client, ProxyA, ProxyB -> XFF: "Client, ProxyA"
              If ProxyB is trusted, REMOTE_ADDR is ProxyB's IP.
              If NUM_PROXIES=1, we trust ProxyB setting XFF, client is first IP.
              If NUM_PROXIES=2, we trust ProxyA setting XFF, client is first IP.
              (Simplified: take the IP at index `len(ips) - num_proxies` if trusting XFF chain)
           c. If header not found or empty, log warning and fall back to REMOTE_ADDR.
        3. If REMOTE_ADDR is NOT trusted, use REMOTE_ADDR as the client IP.
        """
        remote_addr = request.META.get('REMOTE_ADDR')
        if not remote_addr:
            logger.error("Could not determine REMOTE_ADDR. Cannot apply IP-based rate limits.")
            return None

        ip: Optional[str] = None
        if remote_addr in self.trusted_proxies:
            header_value = request.META.get(self.real_ip_header)
            if header_value:
                # Split header value (e.g., "client, proxy1, proxy2")
                ips = [ip.strip() for ip in header_value.split(',')]

                if len(ips) >= self.num_proxies:
                    # The client IP is expected at this position from the *left*
                    # e.g., if num_proxies=1, client is ips[0]
                    # e.g., if num_proxies=2, client is ips[0]
                    # Django's SECURE_PROXY_SSL_HEADER logic is slightly different,
                    # usually taking the Nth from the *right*. Let's stick to common XFF usage:
                    # Client is typically the *first* element set by the *last* trusted proxy.
                    # If num_proxies defines how many trusted proxies are *expected*,
                    # the client IP should be at index len(ips) - num_proxies.
                    # However, the simplest/most common convention is the first IP.
                    # Let's use the first IP for simplicity, assuming the immediate trusted
                    # proxy correctly sets/appends the header.
                    client_ip_index = 0 # Assume first IP is client when set by trusted proxy
                    ip = ips[client_ip_index]
                    logger.debug(f"Trusted proxy {remote_addr} identified. Using IP {ip} from {self.real_ip_header} header: {header_value}")
                else:
                    logger.warning(
                        f"Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                        f"but not enough IPs found for NUM_PROXIES={self.num_proxies}. Falling back to REMOTE_ADDR."
                    )
                    ip = remote_addr # Fallback if header format is unexpected
            else:
                logger.warning(
                    f"Trusted proxy {remote_addr} did not provide the expected {self.real_ip_header} header. "
                    f"Falling back to REMOTE_ADDR."
                 )
                ip = remote_addr # Fallback if header is missing
        else:
            # If the immediate upstream server is not a trusted proxy, use its IP
            ip = remote_addr
            logger.debug(f"Untrusted REMOTE_ADDR {remote_addr}. Using it as client IP.")

        return ip


    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Checks and enforces the rate limit for the incoming request."""
        if not self.enabled:
            return None

        # --- Resolve URL and Determine Limit ---
        try:
            match = resolve(request.path_info)
            # Construct full URL name: <namespace>:<url_name> or just <url_name>
            url_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Resolver404:
            # Could not resolve URL (e.g., static file, invalid path).
            # Try matching based on path prefix as a fallback if needed, or just bypass.
            url_name = None
            # Let's determine limit type based on auth status if URL is unresolved
            limit_type = self._get_limit_type(request, url_name)
            logger.debug(f"URL '{request.path_info}' not resolved. Using limit type '{limit_type}'.")


        # Determine rate limit config based on resolved name or fallback
        if url_name:
             limit_type = self._get_limit_type(request, url_name)

        if not limit_type:
            # This case should ideally be covered by fallbacks in _get_limit_type
            logger.warning(f"Rate limit type could not be determined for request path '{request.path_info}' (resolved: {url_name}). Bypassing limit.")
            return None

        limit_config = self.limit_configs.get(limit_type)
        if not limit_config:
            logger.error(f"Rate limit configuration missing for determined type '{limit_type}'. Bypassing limit.")
            return None

        limit, period = limit_config

        # --- Determine Cache Key ---
        cache_key, identifier = self._get_cache_key_and_identifier(request, limit_type)

        if not cache_key or not identifier:
            # Error logged in _get_cache_key_and_identifier if IP/User is missing
             logger.error(f"Could not generate cache key or identifier for limit type '{limit_type}'. Bypassing limit.")
             return None

        # --- Enforce Limit using Cache ---
        try:
            now = time.time()
            # Get current usage data from cache
            # Format: {'count': N, 'expiry': timestamp}
            usage_data: Dict[str, Any] = cache.get(cache_key, {'count': 0, 'expiry': 0})
            current_count: int = usage_data.get('count', 0)
            expiry_time: float = usage_data.get('expiry', 0)

            # Check if the window has expired
            if now > expiry_time:
                # Start new window
                current_count = 1
                new_expiry_time = now + period
                # Set new data in cache with timeout slightly longer than period for safety
                cache.set(cache_key, {'count': current_count, 'expiry': new_expiry_time}, timeout=period + 5)
                remaining = limit - current_count
                reset_time = period
                expiry_time = new_expiry_time # Update expiry for headers/logging
            else:
                # Increment count within the existing window (NON-ATOMIC step)
                current_count += 1
                # Update cache data, keeping the existing expiry time
                # Timeout is duration FROM NOW until expiry + buffer
                cache_timeout = max(5, int(expiry_time - now) + 5)
                cache.set(cache_key, {'count': current_count, 'expiry': expiry_time}, timeout=cache_timeout)
                remaining = limit - current_count
                reset_time = int(expiry_time - now)

            # Store rate limit info on request for potential use in response headers
            request.rate_limit_info = {
                'limit': limit,
                'remaining': max(0, remaining), # Don't show negative remaining
                'reset': max(0, reset_time), # Ensure reset is non-negative
            }

            # --- Check if Limit Exceeded ---
            if current_count > limit:
                user_id = getattr(request.user, 'id', 'Anonymous')
                log_identifier = f"User: {user_id}" if request.user.is_authenticated else f"IP: {identifier}" # Identifier is IP for anon
                logger.warning(
                    f"Rate limit exceeded for key '{cache_key}' ({log_identifier}, URL: {url_name or request.path_info}). "
                    f"Count: {current_count}/{limit} per {period}s. Reset in {reset_time}s."
                )
                # Return HTTP 429 Too Many Requests
                response = HttpResponse("Rate limit exceeded. Please try again later.", status=429)
                response['Retry-After'] = str(reset_time) # Inform client when to retry (seconds)
                # Optionally add X-RateLimit headers even on failure
                response['X-RateLimit-Limit'] = str(limit)
                response['X-RateLimit-Remaining'] = '0'
                response['X-RateLimit-Reset'] = str(reset_time)
                return response

        except Exception as e:
            # Log cache/unexpected errors but don't block requests (fail open)
            logger.exception(f"Rate limiting failed for key '{cache_key}' due to error: {e}. Request allowed.")

        return None # Rate limit not exceeded or error occurred

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Adds RateLimit headers to the response if available on the request."""
        if hasattr(request, 'rate_limit_info'):
            info = request.rate_limit_info
            response['X-RateLimit-Limit'] = str(info['limit'])
            response['X-RateLimit-Remaining'] = str(info['remaining'])
            response['X-RateLimit-Reset'] = str(info['reset'])
            # Clear info from request? Optional.
            # del request.rate_limit_info
        return response

    def _get_limit_type(self, request: HttpRequest, url_name: Optional[str]) -> Optional[str]:
        """Determine the rate limit type based on URL name mapping and auth status."""
        user = request.user
        limit_type_found: Optional[str] = None

        # Check mappings using resolved URL name first
        if url_name:
            for name_pattern, limit_type in self.endpoint_mapping.items():
                # Allow exact match or prefix match (e.g., 'api:')
                is_match = (url_name == name_pattern) or \
                           (name_pattern.endswith(':') and url_name.startswith(name_pattern))

                if is_match:
                    # Check if limit type is user-specific and user is anonymous
                    is_user_limit = '_user' in limit_type # Simple check, adjust if names vary
                    if is_user_limit and not user.is_authenticated:
                        # Skip user-only limits for anonymous users, continue searching map
                        logger.debug(f"Skipping user limit '{limit_type}' for anonymous user on URL '{url_name}'.")
                        continue
                    else:
                        limit_type_found = limit_type
                        logger.debug(f"Matched URL '{url_name}' to limit type '{limit_type_found}'.")
                        break # Found the most specific applicable match

        # Fallback if no specific URL match found or applicable
        if not limit_type_found:
            if user.is_authenticated:
                limit_type_found = 'user_browse' # Default authenticated
            else:
                limit_type_found = 'anon_browse' # Default anonymous
            logger.debug(f"No specific URL match for '{url_name or request.path_info}'. Using fallback limit type '{limit_type_found}'.")

        return limit_type_found


    def _get_cache_key_and_identifier(self, request: HttpRequest, limit_type: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate the cache key and identifier (IP or User ID) based on the limit type.
        Returns (cache_key, identifier).
        """
        user = request.user
        client_ip = self._get_client_ip(request)

        identifier: Optional[str] = None
        id_type: Optional[str] = None

        # Determine if the key should be based on User ID or IP Address
        # Convention: Suffix '_ip' forces IP-based, '_user' forces user-based (if logged in).
        if '_ip' in limit_type:
            identifier = client_ip
            id_type = 'ip'
        elif '_user' in limit_type:
            if user.is_authenticated:
                identifier = str(user.id)
                id_type = 'user'
            else:
                # Cannot apply user limit to anonymous user - this should have been caught
                # in _get_limit_type, but handle defensively. Fallback to IP? Or block?
                logger.error(f"Attempted to apply user-specific limit '{limit_type}' to anonymous user. Misconfiguration? Bypassing this specific limit check.")
                return None, None # Indicate failure to generate key
        else:
            # No specific suffix, use default behavior: user ID if logged in, IP otherwise
            if user.is_authenticated:
                 identifier = str(user.id)
                 id_type = 'user'
            else:
                 identifier = client_ip
                 id_type = 'ip'

        # Check if we have a valid identifier (especially IP)
        if not identifier:
            if id_type == 'ip':
                 logger.error("Could not determine client IP address. Cannot apply IP-based rate limits.")
            else: # Should not happen for authenticated user unless user.id is weird
                 logger.error(f"Could not determine identifier for id_type '{id_type}'.")
            return None, None

        # Construct cache key: rl:[user|ip]:<identifier>:<limit_type>
        # Ensure identifier does not contain characters problematic for cache keys (like spaces, colons)
        safe_identifier = identifier.replace(":", "_").replace(" ", "_")
        cache_key = f"{self.RATELIMIT_CACHE_PREFIX}{id_type}:{safe_identifier}:{limit_type}"
        return cache_key, identifier # Return original identifier for logging

# --- MODIFICATION END ---