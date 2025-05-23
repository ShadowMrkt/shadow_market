# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/utils.py
# Revision History:
# - v1.0.0 (2025-04-25): Initial creation. Extracted get_client_ip function from various middleware files.

import logging
from typing import Optional
from django.http import HttpRequest
from django.conf import settings

# Use a logger specific to middleware utilities, or a shared one
logger = logging.getLogger('mymarketplace.middleware.utils')

def get_client_ip(request: HttpRequest) -> Optional[str]:
    """
    Get the client's real IP address, trusting configured proxies.

    Reads settings: TRUSTED_PROXY_IPS, REAL_IP_HEADER.

    If the immediate upstream proxy (request.META['REMOTE_ADDR']) is in
    settings.TRUSTED_PROXY_IPS, this function trusts the *first* IP address
    listed in the header specified by settings.REAL_IP_HEADER (e.g.,
    'HTTP_X_FORWARDED_FOR'). Otherwise, it returns REMOTE_ADDR directly.

    Args:
        request: The HttpRequest object.

    Returns:
        The determined client IP address as a string, or None if REMOTE_ADDR
        is not available.
    """
    # Load settings within the function scope for independence
    trusted_proxies = set(getattr(settings, 'TRUSTED_PROXY_IPS', []))
    # Default to 'HTTP_X_FORWARDED_FOR', the most common header
    real_ip_header = getattr(settings, 'REAL_IP_HEADER', 'HTTP_X_FORWARDED_FOR')

    remote_addr = request.META.get('REMOTE_ADDR')
    if not remote_addr:
        logger.error("get_client_ip: Could not determine REMOTE_ADDR from request.META.")
        return None

    ip: Optional[str] = remote_addr # Default to REMOTE_ADDR

    if remote_addr in trusted_proxies:
        header_value = request.META.get(real_ip_header)
        if header_value:
            # X-Forwarded-For format is "client, proxy1, proxy2", so split and take the first one.
            try:
                # Take the first IP address in the list
                client_ip = header_value.split(',')[0].strip()
                if client_ip: # Ensure it's not an empty string
                    ip = client_ip
                    # logger.debug(f"get_client_ip: Trusted proxy {remote_addr} identified. Using IP {ip} from {real_ip_header}: {header_value}")
                else:
                     logger.warning(
                        f"get_client_ip: Trusted proxy {remote_addr} provided {real_ip_header} header '{header_value}', "
                        f"but the first value was empty. Falling back to REMOTE_ADDR."
                    )
            except IndexError:
                 logger.warning(
                    f"get_client_ip: Trusted proxy {remote_addr} provided {real_ip_header} header '{header_value}', "
                    f"but it was empty or malformed after split. Falling back to REMOTE_ADDR."
                )
            except Exception as e:
                # Catch potential unexpected errors during split/strip
                 logger.warning(
                    f"get_client_ip: Error processing {real_ip_header} header '{header_value}' from trusted proxy {remote_addr}: {e}. "
                    f"Falling back to REMOTE_ADDR."
                )
        else:
            logger.warning(
                f"get_client_ip: Trusted proxy {remote_addr} did not provide the expected {real_ip_header} header. "
                f"Falling back to REMOTE_ADDR."
            )
    # else:
        # logger.debug(f"get_client_ip: Untrusted REMOTE_ADDR {remote_addr}. Using it as client IP.")

    return ip

# --- MODIFICATION END ---
