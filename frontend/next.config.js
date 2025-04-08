// frontend/next.config.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - Strengthened warnings for CSP 'unsafe-inline' and 'unsafe-eval'.
//           - Recommended exploring CSP nonce/hashing for production builds.
//           - Added note on removing 'data:' from img-src if unused.
//           - Clarified report-uri backend endpoint requirement & mentioned report-to.
//           - Confirmed HSTS comment clarity.
//           - Added note on NEXT_PUBLIC vars being build-time embedded.
//           - Added revision history block.
// --- Original Modification: Refined CSP directives, added report-uri, improved comments. ---

/** @type {import('next').NextConfig} */

// Helper function to build the Content-Security-Policy string.
// Makes managing multiple directives cleaner.
const buildCsp = (apiUrl) => {
  const directives = {
    // Default policy for directives not explicitly listed.
    'default-src': ["'self'"], // Restricts everything to the same origin by default.

    // Defines valid sources for JavaScript.
    // WARNING: 'unsafe-inline' is generally required for Next.js hydration scripts
    // unless using CSP nonces or hashes (recommended for production). It poses an XSS risk.
    // WARNING: 'unsafe-eval' is often needed for dev tooling (like HMR) but significantly increases
    // XSS risk and should be STRONGLY AVOIDED IN PRODUCTION unless absolutely necessary and the risk mitigated.
    'script-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'"],

    // Defines valid sources for CSS stylesheets.
    // WARNING: 'unsafe-inline' may be needed for inline styles or some CSS-in-JS libraries.
    // Prefer external CSS files or CSS Modules if possible to remove this.
    'style-src': ["'self'", "'unsafe-inline'"],

    // Defines valid sources for images.
    // Consider removing 'data:' if you don't use data URIs for images, slightly reducing attack surface.
    'img-src': ["'self'", "data:"],

    // Defines valid sources for fonts.
    'font-src': ["'self'"],

    // Defines valid sources for plugins (e.g., <object>, <embed>). 'none' recommended.
    'object-src': ["'none'"],

    // Specifies valid parents that may embed a page using <frame>, <iframe>, <object>, or <embed>.
    // 'none' prevents embedding, mitigating clickjacking.
    'frame-ancestors': ["'none'"],

    // Specifies valid endpoints for form submissions.
    'form-action': ["'self'"],

    // Specifies valid URLs for the <base> element.
    'base-uri': ["'self'"],

    // Defines valid sources for fetch requests, WebSockets, XHR, etc.
    // Needs to include the application's backend API URL.
    'connect-src': ["'self'", apiUrl || 'http://localhost:8000'], // Default for local dev

    // --- Reporting Directive ---
    // Instructs the browser to POST JSON reports of policy violations to the specified URI.
    // NOTE: Requires a backend endpoint at this path configured to receive and process these reports.
    // Consider the newer 'report-to' directive for more advanced reporting if browser support aligns.
    'report-uri': ["/csp-violation-report-endpoint/"],
  };

  return Object.entries(directives)
    .map(([key, value]) => `${key} ${value.join(' ')}`)
    .join('; ');
};

const nextConfig = {
  // Enables React's Strict Mode for highlighting potential problems during development.
  reactStrictMode: true,

  // Define environment variables accessible in the browser (must be prefixed with NEXT_PUBLIC_).
  // Note: By default, these are embedded at build time. Ensure your deployment process
  // handles environment variable updates correctly if they change post-build.
  env: {
    // Crucial to set this correctly via environment variables during build/runtime for production.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000', // Fallback only for local development
  },

  // Function to define custom HTTP headers.
  async headers() {
    // Determine API URL based on environment variable (consistent with env block).
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    return [
      {
        // Apply these headers to all routes within the application.
        source: '/(.*)',
        headers: [
          // --- Content Security Policy (CSP) ---
          // Helps detect and mitigate certain types of attacks, including XSS and data injection.
          {
            key: 'Content-Security-Policy',
            value: buildCsp(apiUrl) // Use the helper function to generate the policy string.
          },

          // --- Other Security Headers ---

          // Prevents browsers from MIME-sniffing the content-type.
          { key: 'X-Content-Type-Options', value: 'nosniff' },

          // Controls how much referrer information is sent with requests.
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },

          // Enforces HTTPS. Usually set by the edge server/proxy (like Nginx/Cloudflare) for the entire domain.
          // Uncommenting here might be redundant or less effective. Requires careful setup if enabled.
          // { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },

          // Prevents clickjacking (redundant with CSP frame-ancestors but good defense-in-depth for older browsers).
          { key: 'X-Frame-Options', value: 'DENY' },

          // Disables the deprecated XSS auditor in browsers; rely on CSP for XSS protection.
          { key: 'X-XSS-Protection', value: '0' },

          // Controls which browser features and APIs can be used by the website.
          // Using a restrictive policy reduces the potential attack surface.
          {
            key: 'Permissions-Policy',
            // Policy copied from backend middleware for consistency (blocks most features by default).
            value: "accelerometer=(), ambient-light-sensor=(), autoplay=(), battery=(), camera=(), display-capture=(), document-domain=(), encrypted-media=(), fullscreen=(), gamepad=(), geolocation=(), gyroscope=(), layout-animations=(self), legacy-image-formats=(self), magnetometer=(), microphone=(), midi=(), navigation-override=(), oversized-images=(self), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), speaker-selection=(), sync-xhr=(), unoptimized-images=(self), unsized-media=(self), usb=(), web-share=(), xr-spatial-tracking=()"
          }
        ],
      },
    ];
  },

  // Add other Next.js configurations here if needed (e.g., images, i18n, redirects, rewrites).
};

module.exports = nextConfig;