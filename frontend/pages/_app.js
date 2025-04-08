// frontend/pages/_app.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 3 - Added explicit configuration props to ToastContainer.
//           - Configured ToastContainer position, theme, autoClose to match notification utils.
//           - Imported TOAST_SUCCESS_DURATION constant.
//           - Added comments for other potential global providers (SWRConfig, ThemeContext, etc.).
//           - Added TODO for ErrorBoundary review/implementation.
// 2025-04-07: Rev 2 - Implemented global Error Boundary.
//           - Imported ErrorBoundary component.
//           - Wrapped <Component {...pageProps} /> within <ErrorBoundary>.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - Added comments regarding notification content sanitization responsibility.
//           - Recommended adding a global Error Boundary for production robustness.
//           - Added comment about dependency vulnerability checks (e.g., react-toastify).
//           - Added comment suggesting optional ToastContainer configuration.
//           - Added revision history block.

import '../styles/globals.css'; // Apply global styles
import { AuthProvider } from '../context/AuthContext'; // Provide auth state globally
import { ToastContainer } from 'react-toastify'; // Import Container for notifications
import 'react-toastify/dist/ReactToastify.css'; // Import default styles for react-toastify
import ErrorBoundary from '../components/ErrorBoundary'; // TODO: Review/Implement ErrorBoundary logic
import { TOAST_SUCCESS_DURATION } from '../utils/constants'; // Import default duration

// Recommendation: Periodically run `npm audit` or `yarn audit` for dependency vulnerabilities.

function MyApp({ Component, pageProps }) {
  return (
    // AuthProvider should generally be one of the outermost providers
    <AuthProvider>
        {/* Other global providers (e.g., ThemeProvider, SWRConfig, CartProvider) would typically wrap ErrorBoundary or be nested inside AuthProvider */}
        {/* Example: <SWRConfig value={{ provider: () => new Map(), fetcher: globalFetcher }}> */}

            {/* ErrorBoundary catches runtime JS errors in children */}
            {/* TODO: Ensure ErrorBoundary component provides adequate logging and a user-friendly fallback UI. */}
            <ErrorBoundary>
                {/* ToastContainer setup - Configuration here sets defaults */}
                {/* Individual toast calls can still override these options */}
                <ToastContainer
                    position="top-right"
                    autoClose={TOAST_SUCCESS_DURATION} // Use constant for default duration
                    hideProgressBar={false}
                    newestOnTop={false} // Or true if preferred
                    closeOnClick
                    rtl={false}
                    pauseOnFocusLoss
                    draggable
                    pauseOnHover
                    theme="dark" // Match dark theme established elsewhere
                    // limit={3} // Optional: Limit concurrent toasts
                />

                {/* Renders the current page component */}
                <Component {...pageProps} />

            </ErrorBoundary>

        {/* </SWRConfig> */}
    </AuthProvider>
  );
}

export default MyApp;