// frontend/pages/_document.js
// /***************************************************************************************
// * REVISION HISTORY (Most recent first)
// ***************************************************************************************
// * 2025-04-28    [Gemini]   Modified for CSP Nonce implementation.
// * - Added getInitialProps to read X-CSP-Nonce header from request.
// * - Passed nonce as prop to Document component.
// * - Applied nonce prop to NextScript component.
// * 2025-04-28    [Gemini]   Initial creation. Standard Next.js custom Document boilerplate.
// ***************************************************************************************/

import { Html, Head, Main, NextScript } from 'next/document';

export default function Document({ cspNonce }) { // Receive nonce as prop
  return (
    <Html lang="en">
      <Head>
        {/* Nonce applied automatically by Next.js to <Head> elements if needed */}
        {/* <meta name="csp-nonce" content={cspNonce} />  */} {/* Alternative way to pass nonce if needed */}
      </Head>
      <body>
        <Main />
        <NextScript nonce={cspNonce} /> {/* Apply nonce to NextScript */}
      </body>
    </Html>
  );
}

// Fetch nonce from request headers during SSR/getInitialProps
Document.getInitialProps = async (ctx) => {
  const initialProps = await ctx.defaultGetInitialProps(ctx);
  // Read nonce from the custom header set in middleware.js
  const cspNonce = ctx.req?.headers['x-csp-nonce'] || null;
  return {
    ...initialProps,
    cspNonce, // Pass nonce as a prop
  };
};