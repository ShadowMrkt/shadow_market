# --- MODIFICATION START ---
# File: shadow_market/backend/middleware/SecurityHeadersMiddleware.py
# Revision History:
# 2025-04-07: Initial Refactor - Applied enterprise hardening concepts:
#             - Replaced print() with logging.
#             - Made 'unsafe-inline' for style-src conditional via settings (CSP_ALLOW_UNSAFE_INLINE_STYLES) with warnings. Strongly recommend disabling this.
#             - Made CSP report-uri configurable via settings (CSP_REPORT_URI).
#             - Added configurable default for Referrer-Policy.
#             - Added optional, configurable COOP and COEP headers via settings (SECURE_COOP_POLICY, SECURE_COEP_POLICY).
#             - Improved nonce generation/CSP construction error handling.
#             - Added type hints.
#             - Addressed Sentry URL parsing robustness slightly.
#             - Ensured X-XSS-Protection is disabled.

from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.http import HttpRequest, HttpResponse # For type hinting
from typing import Optional # For type hinting
import os
import base64
import logging # Use standard logging
from urllib.parse import urlparse # For potentially better URL parsing

logger = logging.getLogger(__name__) # Initialize logger for this module

class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Sets crucial security headers for HTTP responses, aiming for production-grade security.

    Includes a strong Content-Security-Policy (CSP) with nonces for inline scripts
    and configurable reporting for violations. Also sets other headers like
    X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy,
    and optionally COOP/COEP.
    """

    def _generate_nonce(self) -> Optional[str]:
        """Generates a secure nonce."""
        try:
            # Use os.urandom for cryptographically secure randomness
            return base64.b64encode(os.urandom(16)).decode('utf-8')
        except Exception:
            # Log the full error if nonce generation fails. This is critical.
            logger.exception("CRITICAL: Failed to generate CSP nonce. CSP effectiveness significantly reduced.")
            return None

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        # --- Nonce Generation ---
        # Generate a unique nonce for each request. Attach to request for template access.
        nonce = self._generate_nonce()
        request.csp_nonce = nonce # Make nonce available, will be None if generation failed

        # --- Content Security Policy (CSP) Definition ---
        # Start with a restrictive base policy.
        csp_directives = {
            "default-src": ["'self'"],
            "script-src": [
                "'self'",
                # Only include nonce if successfully generated
                f"'nonce-{nonce}'" if nonce else "",
                # 'strict-dynamic' allows nonce/hash-trusted scripts to load others.
                # Requires careful use of nonces/hashes on initial scripts.
                "'strict-dynamic'",
                # Add external script sources from settings if needed (prefer hosting locally)
                # Example: getattr(settings, 'CSP_SCRIPT_SRC_EXTRAS', [])
            ],
            "style-src": [
                "'self'",
                # Add external style sources from settings if needed
                # Example: getattr(settings, 'CSP_STYLE_SRC_EXTRAS', [])
            ],
            "img-src": ["'self'", "data:"], # Allow self and data URIs. Review if 'data:' is necessary.
            "font-src": ["'self'"], # Allow fonts from same origin
            "object-src": ["'none'"], # Strongly recommended: Disallow plugins
            "frame-ancestors": ["'none'"], # Prevent framing (clickjacking protection)
            "form-action": ["'self'"], # Restrict where forms can submit
            "base-uri": ["'self'"], # Restrict <base> tag
            "connect-src": ["'self'"], # Restrict AJAX/Fetch/WebSocket connections
        }

        # --- Conditional CSP Directives ---

        # Handle 'unsafe-inline' for styles based on settings
        # !! SECURITY WARNING !!: 'unsafe-inline' is dangerous. Avoid if AT ALL possible
        # by removing inline styles/scripts or using nonce/hashes for styles (requires frontend changes).
        if getattr(settings, 'CSP_ALLOW_UNSAFE_INLINE_STYLES', False):
            csp_directives["style-src"].append("'unsafe-inline'")
            logger.warning("CSP: Allowing 'unsafe-inline' for style-src due to settings.CSP_ALLOW_UNSAFE_INLINE_STYLES. This significantly reduces protection against XSS.")
        # else:
            # If not allowing unsafe-inline, consider adding style nonces/hashes here
            # if nonce:
            #     csp_directives["style-src"].append(f"'nonce-{nonce}'")
            # Requires adding nonce="{{ request.csp_nonce }}" to <style> tags in templates.

        # Remove empty strings resulting from failed nonce generation in script-src
        csp_directives["script-src"] = [src for src in csp_directives["script-src"] if src]
        if nonce is None and "'strict-dynamic'" in csp_directives["script-src"]:
            # This state might break script loading depending on how scripts are loaded.
            logger.error("CSP: Nonce generation failed, but 'strict-dynamic' is present. Script execution may be blocked unexpectedly.")
            # Consider removing 'strict-dynamic' or defining a stricter fallback script-src here if nonce failure is common.


        # Add Sentry endpoint to connect-src if configured
        sentry_dsn = getattr(settings, 'SENTRY_DSN', None)
        if sentry_dsn:
            try:
                # Use urlparse for slightly more robust parsing
                parsed_dsn = urlparse(sentry_dsn)
                # Construct the base URL Sentry posts to (scheme + netloc)
                sentry_host = f"{parsed_dsn.scheme}://{parsed_dsn.netloc}"
                if sentry_host:
                     # Avoid duplicates if 'self' resolves to the same host
                    if sentry_host not in csp_directives["connect-src"]:
                         csp_directives["connect-src"].append(sentry_host)
            except Exception: # Catch broader errors during parsing
                logger.warning(
                    f"Could not parse Sentry host from DSN '{sentry_dsn}' for CSP connect-src.",
                    exc_info=True # Log traceback for debugging
                )

        # Add other allowed connect-src domains from settings
        # Example: csp_directives["connect-src"].extend(getattr(settings, 'CSP_CONNECT_SRC_EXTRAS', []))


        # --- Reporting Directive ---
        csp_report_uri = getattr(settings, 'CSP_REPORT_URI', None)
        if csp_report_uri:
            # Ensure you have an endpoint at this URI to receive POST reports
            csp_directives["report-uri"] = [csp_report_uri]
            logger.info(f"CSP: Reporting violations to {csp_report_uri}")
        else:
            logger.warning("CSP: No CSP_REPORT_URI configured in settings. Violation reporting is disabled.")
        # Consider adding 'report-to' directive for the newer Reporting API if needed.


        # --- Construct and Set CSP Header ---
        csp_policy_parts = []
        for key, values in csp_directives.items():
            # Filter out any remaining empty/None values just in case
            filtered_values = [v for v in values if v]
            if filtered_values:
                csp_policy_parts.append(f"{key} {' '.join(filtered_values)}")

        if csp_policy_parts:
            csp_policy = "; ".join(csp_policy_parts)
            response['Content-Security-Policy'] = csp_policy
        else:
            # This should ideally not happen with the current structure
             logger.error("CRITICAL: Failed to construct any CSP directives. CSP header NOT set.")


        # --- Other Essential Security Headers ---

        # Prevent MIME-sniffing attacks
        response['X-Content-Type-Options'] = 'nosniff'

        # Prevent framing (Defense-in-depth alongside CSP frame-ancestors)
        response['X-Frame-Options'] = 'DENY'

        # Referrer Policy: Control how much referrer info is sent.
        # Default to a reasonably secure policy if not explicitly set in settings.
        referrer_policy = getattr(settings, 'SECURE_REFERRER_POLICY', 'strict-origin-when-cross-origin')
        if referrer_policy:
            response['Referrer-Policy'] = referrer_policy

        # X-XSS-Protection: Deprecated. Explicitly disable it as CSP is the successor.
        response['X-XSS-Protection'] = '0'

        # Strict-Transport-Security (HSTS): Handled by Django's core SecurityMiddleware.
        # Ensure Django's middleware is enabled and SECURE_HSTS_SECONDS, etc., are set in production settings.

        # Permissions Policy: Restrict browser features. Start with a deny-all baseline,
        # then allow specific features as needed ('self' or specific origins).
        # Keep this policy as restrictive as possible.
        default_permissions_policy = [
             "accelerometer=()", "ambient-light-sensor=()", "autoplay=()", "battery=()",
             "camera=()", "display-capture=()", "document-domain=()", "encrypted-media=()",
             "fullscreen=()", "gamepad=()", "geolocation=()", "gyroscope=()", "layout-animations=(self)",
             "legacy-image-formats=(self)", "magnetometer=()", "microphone=()", "midi=()",
             "navigation-override=()", "oversized-images=(self)", "payment=()", "picture-in-picture=()",
             "publickey-credentials-get=()", "screen-wake-lock=()", "speaker-selection=()",
             "sync-xhr=()", "unoptimized-images=(self)", "unsized-media=(self)", "usb=()",
             "web-share=()", "xr-spatial-tracking=()"
        ]
        # Allow overriding or extending via settings if necessary
        permissions_policy_str = ", ".join(getattr(settings, 'PERMISSIONS_POLICY_DIRECTIVES', default_permissions_policy))
        if permissions_policy_str:
             response['Permissions-Policy'] = permissions_policy_str


        # --- Optional Process Isolation Headers ---
        # COOP (Cross-Origin-Opener-Policy): Helps mitigate cross-origin attacks.
        # 'same-origin-allow-popups' is common, 'same-origin' is stricter.
        coop_policy = getattr(settings, 'SECURE_COOP_POLICY', None)
        if coop_policy:
             response['Cross-Origin-Opener-Policy'] = coop_policy
             logger.info(f"Setting Cross-Origin-Opener-Policy: {coop_policy}")

        # COEP (Cross-Origin-Embedder-Policy): Prevents loading cross-origin resources
        # that don't explicitly grant permission (via CORP or CORS).
        # 'require-corp' is the most secure but can break resources without CORP/CORS.
        # 'credentialless' is a newer, potentially less breaking alternative for some use cases.
        coep_policy = getattr(settings, 'SECURE_COEP_POLICY', None)
        if coep_policy:
             response['Cross-Origin-Embedder-Policy'] = coep_policy
             logger.warning(f"Setting Cross-Origin-Embedder-Policy: {coep_policy}. This can break loading of cross-origin resources without proper CORP/CORS headers. Test thoroughly.")


        return response

# --- MODIFICATION END ---