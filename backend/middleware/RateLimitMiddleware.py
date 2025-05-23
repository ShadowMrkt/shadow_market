# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/RateLimitMiddleware.py
# Revision History:
# - v1.1.0 (2025-04-25):
#   - SECURITY FIX: Corrected IP address extraction logic in `_get_client_ip`. Now correctly takes the *first* IP from the configured header (`REAL_IP_HEADER`) if the `REMOTE_ADDR` is trusted. Removed flawed `NUM_PROXIES` logic.
#   - BEST PRACTICE (Atomicity): Changed core rate limit logic to use `cache.incr()` for atomic counter updates (recommended with Redis/Memcached). Includes handling for initial hit to set expiry. Falls back gracefully if `incr` fails.
#   - REFACTOR: Simplified cache data structure - only stores the count directly, expiry handled by cache timeout.
#   - IMPROVEMENT: Calculate remaining time more directly when using `incr`.
# - v1.0.0 (2025-04-07): Initial Refactor - Applied enterprise hardening concepts:
#   - Added trusted proxy support for IP address identification (settings.TRUSTED_PROXY_IPS, settings.REAL_IP_HEADER). CRITICAL FIX. (Logic fixed in v1.1.0)
#   - Moved rate limit definitions (RATE_LIMIT_CONFIGS) and endpoint mapping (RATE_LIMIT_MAPPING) to be configurable via settings.py, with defaults.
#   - Improved logging clarity and context.
#   - Added type hinting.
#   - Clearly documented the non-atomic nature of the default cache update mechanism and recommended Redis.
#   - Renamed middleware class slightly for clarity.
#   - Encapsulated IP fetching logic within the class.

import time
import logging
from collections import OrderedDict
from typing import Optional, Tuple, Dict, Any, List # For type hinting

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.core.cache import cache # Use Django's cache abstraction
from django.urls import resolve, Resolver404
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

# Use specific logger for this middleware
logger = logging.getLogger('mymarketplace.middleware.ratelimit')

# --- Default Rate Limit Configuration (used if not overridden in settings.py) ---
# Define rate limits (requests, period_in_seconds)
# Use descriptive names for limit types
DEFAULT_RATE_LIMITS_CONFIG = {
    # Limit Type             : (Requests, Period)
    'anon_browse'            : (200, 3600),     # Anonymous general Browse: 200 reqs/hour
    'user_browse'            : (2000, 3600),    # Authenticated general Browse: 2000 reqs/hour
    'login_attempt_ip'       : (10, 60 * 5),    # Login attempts (per IP): 10 reqs/5 minutes
    'login_success_user'     : (5, 60 * 15),    # Post-successful login actions (per User): 5 reqs/15 minutes
    'register_attempt_ip'    : (5, 3600),       # Registration attempts (per IP): 5 reqs/hour
    'product_list'           : (120, 60),       # Product listing/search: 120 reqs/minute
    'product_detail'         : (180, 60),       # Product detail view: 180 reqs/minute
    'product_create_user'    : (10, 3600),      # Vendor creating/updating product: 10 reqs/hour
    'order_place_user'       : (5, 60 * 10),    # Placing an order: 5 reqs/10 minutes
    'order_action_user'      : (20, 60 * 5),    # Other order actions (ship, finalize, etc): 20 reqs/5 minutes
    'withdrawal_prep_user'   : (5, 60 * 10),    # Preparing withdrawal: 5 reqs/10 minutes
    'withdrawal_exec_user'   : (3, 60 * 15),    # Executing withdrawal: 3 reqs/15 minutes
    'ticket_create_user'     : (5, 3600),       # Creating support ticket: 5 reqs/hour
    'ticket_reply_user'      : (30, 3600),      # Replying to ticket: 30 reqs/hour
    'upload_user'            : (10, 3600),      # Generic upload limit: 10 reqs/hour
    'sensitive_api_user'     : (60, 60),        # Fallback for sensitive APIs: 60 reqs/minute
    'captcha_request_ip'     : (20, 60),        # Requesting CAPTCHA: 20 reqs/minute
}

# --- Default Endpoint to Limit Type Mapping (used if not overridden in settings.py) ---
# Map URL names (or prefixes) to specific rate limit types defined above.
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
    Uses atomic cache.incr() if available for better accuracy under load.

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

    Cache Backend Recommendation:
        Using cache.incr() provides atomic increments, preventing race conditions.
        This works best with Redis or Memcached cache backends via django-redis or
        Django's built-in Memcached backend. Database or filesystem caches might not
        support atomic increments efficiently or at all.
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
        # NUM_PROXIES is no longer used in the corrected IP logic below

        if not self.enabled:
            logger.info("Rate limiting is disabled via settings.ENABLE_RATE_LIMITING.")
        if not self.trusted_proxies:
             logger.warning("TRUSTED_PROXY_IPS setting is empty. Rate limiting will use REMOTE_ADDR directly. "
                            "Ensure this is correct for your deployment.")

    def _get_client_ip(self, request: HttpRequest) -> Optional[str]:
        """
        Get the client's real IP address, trusting configured proxies.
        If REMOTE_ADDR is trusted, takes the *first* IP from REAL_IP_HEADER.
        """
        remote_addr = request.META.get('REMOTE_ADDR')
        if not remote_addr:
            logger.error("Could not determine REMOTE_ADDR. Cannot apply IP-based rate limits.")
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
                        # logger.debug(f"Trusted proxy {remote_addr} identified. Using IP {ip} from {self.real_ip_header} header: {header_value}")
                    else:
                         logger.warning(
                            f"Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                            f"but the first value was empty. Falling back to REMOTE_ADDR."
                        )
                except IndexError:
                     logger.warning(
                        f"Trusted proxy {remote_addr} provided {self.real_ip_header} header '{header_value}', "
                        f"but it was empty or malformed after split. Falling back to REMOTE_ADDR."
                    )
                except Exception as e:
                    logger.warning(
                        f"Error processing {self.real_ip_header} header '{header_value}' from trusted proxy {remote_addr}: {e}. "
                        f"Falling back to REMOTE_ADDR."
                    )
            else:
                logger.warning(
                    f"Trusted proxy {remote_addr} did not provide the expected {self.real_ip_header} header. "
                    f"Falling back to REMOTE_ADDR."
                )
        # else:
            # logger.debug(f"Untrusted REMOTE_ADDR {remote_addr}. Using it as client IP.")

        return ip

    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Checks and enforces the rate limit for the incoming request using cache.incr()."""
        if not self.enabled:
            return None

        # --- Resolve URL and Determine Limit ---
        try:
            match = resolve(request.path_info)
            url_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Resolver404:
            url_name = None
            # Determine limit type based on auth status if URL is unresolved
            limit_type = self._get_limit_type(request, url_name) # Uses fallback logic
            logger.debug(f"URL '{request.path_info}' not resolved. Using limit type '{limit_type}'.")

        # Determine rate limit config based on resolved name or fallback
        if url_name and 'limit_type' not in locals(): # Only run if not already set by Resolver404 fallback
            limit_type = self._get_limit_type(request, url_name)

        if not limit_type:
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
            logger.error(f"Could not generate cache key or identifier for limit type '{limit_type}'. Bypassing limit.")
            return None

        # --- Enforce Limit using Cache (Atomic Increment Method) ---
        try:
            # Atomically increment the count for the cache key.
            # cache.incr() initializes the key to 1 if it doesn't exist.
            current_count = cache.incr(cache_key)

            # If this is the first hit (count is 1), set the expiry for the key.
            if current_count == 1:
                # Set the timeout for the cache key itself
                cache.expire(cache_key, timeout=period)
                # Alternative if expire isn't available: set with timeout
                # cache.set(cache_key, 1, timeout=period)

            # Get the remaining time until the key expires (TTL: Time To Live)
            # Note: cache.ttl() might return None if the key doesn't exist or has no timeout,
            # or -1/-2 depending on backend/state. We need a robust way to estimate reset.
            # We know the period, and if count > 1, it must have been set recently.
            # A simple estimate is usually sufficient for headers.
            # We use the 'period' as the reset time from the *start* of the window.
            reset_time_estimate = period # For header, represents full window duration

            # More accurate TTL if available (e.g., Redis)
            try:
                ttl = cache.ttl(cache_key)
                if ttl is not None and ttl > 0:
                    reset_time_estimate = ttl
            except AttributeError:
                pass # Backend doesn't support ttl, use period

            remaining = max(0, limit - current_count)

            # Store rate limit info on request for potential use in response headers
            request.rate_limit_info = {
                'limit': limit,
                'remaining': remaining,
                'reset': reset_time_estimate,
            }

            # --- Check if Limit Exceeded ---
            if current_count > limit:
                user_id = getattr(request.user, 'id', 'Anonymous')
                log_identifier = f"User: {user_id}" if request.user.is_authenticated and '_user' in limit_type else f"IP: {identifier}"
                logger.warning(
                    f"Rate limit exceeded for key '{cache_key}' ({log_identifier}, URL: {url_name or request.path_info}). "
                    f"Count: {current_count}/{limit} per {period}s. Approx reset in {reset_time_estimate}s."
                )
                # Return HTTP 429 Too Many Requests
                response = HttpResponse("Rate limit exceeded. Please try again later.", status=429)
                response['Retry-After'] = str(reset_time_estimate) # Inform client when to retry (seconds)
                response['X-RateLimit-Limit'] = str(limit)
                response['X-RateLimit-Remaining'] = '0' # Exceeded, so 0 remaining
                response['X-RateLimit-Reset'] = str(reset_time_estimate)
                return response

        except AttributeError:
             # Cache backend likely doesn't support incr or expire/ttl. Log error and fail open.
             logger.exception(f"Rate limiting cache backend does not support atomic incr/expire/ttl for key '{cache_key}'. Falling back: request allowed.")
        except Exception as e:
            # Log other cache/unexpected errors but don't block requests (fail open)
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
                           (name_pattern.endswith(':') and name_pattern != '' and url_name.startswith(name_pattern)) or \
                           (name_pattern == '' and not url_name) # Match empty pattern only if url_name is empty/None?

                if is_match:
                    # Check if limit type is user-specific and user is anonymous
                    is_user_limit = '_user' in limit_type # Simple check, adjust if names vary
                    if is_user_limit and not user.is_authenticated:
                        # Skip user-only limits for anonymous users, continue searching map
                        # logger.debug(f"Skipping user limit '{limit_type}' for anonymous user on URL '{url_name}'.")
                        continue
                    else:
                        limit_type_found = limit_type
                        # logger.debug(f"Matched URL '{url_name}' to limit type '{limit_type_found}'.")
                        break # Found the most specific applicable match

        # Fallback if no specific URL match found or applicable
        if not limit_type_found:
            # Check the catch-all patterns defined in the mapping explicitly
            if user.is_authenticated:
                limit_type_found = self.endpoint_mapping.get('api:', 'user_browse') # Default auth API, then overall auth browse
            else:
                 limit_type_found = self.endpoint_mapping.get('', 'anon_browse') # Default anonymous
            # logger.debug(f"No specific URL match for '{url_name or request.path_info}'. Using fallback limit type '{limit_type_found}'.")

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
                # in _get_limit_type, but handle defensively.
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
        # Ensure identifier does not contain characters problematic for cache keys
        safe_identifier = str(identifier).replace(":", "_").replace(" ", "_").replace("@", "_") # Be safe
        cache_key = f"{self.RATELIMIT_CACHE_PREFIX}{id_type}:{safe_identifier}:{limit_type}"
        return cache_key, str(identifier) # Return original identifier for logging

# --- MODIFICATION END ---