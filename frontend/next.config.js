// frontend/next.config.js
// --- REVISION HISTORY ---
// 2025-04-28    [Gemini]   Removed static CSP header configuration (async headers() block).
//             CSP with nonce is now handled dynamically by middleware.js.
// 2025-04-07    [Gemini]   Rev 1 - Initial enterprise-grade review and update.
//           - Strengthened warnings for CSP 'unsafe-inline' and 'unsafe-eval'.
//           - Recommended exploring CSP nonce/hashing for production builds.
//           - Added note on removing 'data:' from img-src if unused.
//           - Clarified report-uri backend endpoint requirement & mentioned report-to.
//           - Confirmed HSTS comment clarity.
//           - Added note on NEXT_PUBLIC vars being build-time embedded.
//           - Added revision history block.
// --- Original Modification: Refined CSP directives, added report-uri, improved comments. ---

/** @type {import('next').NextConfig} */

// NOTE: The buildCsp helper function and the async headers() function block
//       have been REMOVED as CSP is now handled by middleware.js

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

  // REMOVED async headers() function - Now handled by middleware.js

  // Add other Next.js configurations here if needed (e.g., images, i18n, redirects, rewrites).
};

module.exports = nextConfig;