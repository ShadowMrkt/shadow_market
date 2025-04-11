// frontend/utils/notifications.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 3 - Added more detail to theme matching TODO comment.
// 2025-04-07: Rev 2 - Used duration constants, set theme to dark, added ToastContainer reminder.
//           - Imported and used TOAST_SUCCESS_DURATION, TOAST_ERROR_DURATION from constants.
//           - Changed default theme to "dark" for better integration.
//           - Added comment reminding to include <ToastContainer /> in the app layout.
//           - Added comment about optional toastId usage.
//           - Slightly improved non-string message handling fallback.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - Added security comments clarifying reliance on react-toastify's string escaping and caller responsibility for safe message content.
//           - Made string input expectation explicit in comments/JSDoc.
//           - Added minor robustness to showErrorToast message handling.
//           - Added revision history block.

import { toast } from 'react-toastify';
import { TOAST_SUCCESS_DURATION, TOAST_ERROR_DURATION } from './constants'; // Import duration constants

// IMPORTANT: For toasts to appear, you must render the <ToastContainer /> component
// somewhere in your application's component tree (typically in _app.js or Layout.js).
// Ensure its props (theme, autoClose, etc.) match the defaults set here or desired global behavior.
// Example: <ToastContainer theme="dark" autoClose={TOAST_SUCCESS_DURATION} /> in _app.js

// Default configuration for all toasts
const toastConfig = {
    position: "top-right",
    autoClose: TOAST_SUCCESS_DURATION, // Use success duration as the default autoClose time
    hideProgressBar: false,
    closeOnClick: true,
    pauseOnHover: true,
    draggable: true,
    progress: undefined,
    theme: "dark", // Use the built-in dark theme as a base

    // TODO ADVANCED THEME: For perfect theme matching with globals.css variables, you might need to:
    // 1. Override specific `react-toastify` CSS classes in `globals.css`.
    //    Example:
    //    .Toastify__toast--success { background-color: var(--accent-green) !important; color: var(--text-on-accent) !important; }
    //    .Toastify__progress-bar--success { background: var(--text-on-accent) !important; }
    //    (Use !important carefully if needed to override default styles)
    // 2. OR potentially pass style objects/classNames directly in options if the API supports it well enough.
};

/**
 * Displays a success toast notification.
 * SECURITY NOTE: Assumes 'message' is a string. Relies on react-toastify's
 * default behavior to escape string content, preventing XSS. Calling code
 * must ensure the provided message string is safe and does not contain unsanitized user input.
 * @param {string} message The message string to display.
 * @param {import('react-toastify').ToastOptions} [options={}] Optional configuration overrides for react-toastify (can include toastId).
 */
export const showSuccessToast = (message, options = {}) => {
    // Ensure message is treated as a string, though caller should provide one.
    const displayMessage = typeof message === 'string' ? message : String(message ?? 'Success!'); // Use ?? for nullish coalescing
    toast.success(displayMessage, { ...toastConfig, ...options });
};

/**
 * Displays an error toast notification. Logs the full error to the console.
 * Truncates long messages for display in the toast UI.
 * SECURITY NOTE: Assumes 'message' is a string or Error object. Extracts message property if Error.
 * Relies on react-toastify's default behavior to escape string content, preventing XSS.
 * Calling code must ensure provided messages/errors don't expose sensitive info unintentionally.
 * @param {string | Error | any} error The error message string, Error object, or other value to display/log.
 * @param {import('react-toastify').ToastOptions} [options={}] Optional configuration overrides for react-toastify (can include toastId).
 */
export const showErrorToast = (error, options = {}) => {
    let originalMessage = 'An unknown error occurred.';
    let errorToLog = error; // Keep original error for logging

    // Attempt to extract message if an Error object is passed
    if (typeof error === 'string') {
        originalMessage = error || originalMessage; // Use provided string or default
    } else if (error instanceof Error && error.message) {
        originalMessage = error.message;
    } else {
        // Try to stringify other types, but log the original object
         try {
             originalMessage = String(error ?? originalMessage); // Coerce other types, use ??
         } catch { /* Ignore coercion errors, use default */ }
         errorToLog = error; // Ensure the original object/value is logged
    }

    // Prevent overly long error messages in toasts for better UI, log full error instead.
    const MAX_TOAST_MSG_LENGTH = 150;
    const displayMessage = originalMessage.length > MAX_TOAST_MSG_LENGTH
        ? originalMessage.substring(0, MAX_TOAST_MSG_LENGTH - 3) + '...' // Truncate and add ellipsis
        : originalMessage;

    // Log the *full* original error message or object for debugging purposes.
    console.error("Error Toast Triggered:", errorToLog); // Log the original input

    toast.error(displayMessage, {
        ...toastConfig,
        autoClose: TOAST_ERROR_DURATION, // Use specific error duration constant
        ...options
       });
};

/**
 * Displays an info toast notification.
 * SECURITY NOTE: Assumes 'message' is a string. Relies on react-toastify's
 * default behavior to escape string content, preventing XSS. Calling code
 * must ensure the provided message string is safe.
 * @param {string} message The message string to display.
 * @param {import('react-toastify').ToastOptions} [options={}] Optional configuration overrides for react-toastify (can include toastId).
 */
export const showInfoToast = (message, options = {}) => {
    // Ensure message is treated as a string.
    const displayMessage = typeof message === 'string' ? message : String(message ?? 'Info'); // Use ??
    toast.info(displayMessage, { ...toastConfig, ...options });
};

/**
 * Displays a warning toast notification.
 * SECURITY NOTE: Assumes 'message' is a string. Relies on react-toastify's
 * default behavior to escape string content, preventing XSS. Calling code
 * must ensure the provided message string is safe.
 * @param {string} message The message string to display.
 * @param {import('react-toastify').ToastOptions} [options={}] Optional configuration overrides for react-toastify (can include toastId).
 */
export const showWarningToast = (message, options = {}) => {
    // Ensure message is treated as a string.
    const displayMessage = typeof message === 'string' ? message : String(message ?? 'Warning'); // Use ??
    // Optionally use a specific duration constant if defined in constants.js
    // const warningDuration = constants.TOAST_WARNING_DURATION || TOAST_SUCCESS_DURATION;
    toast.warn(displayMessage, { ...toastConfig, /* autoClose: warningDuration, */ ...options });
};

// --- Example Usage ---
// import { showSuccessToast, showErrorToast } from './utils/notifications';
// showSuccessToast("Profile updated successfully!");
// try { /* ... api call ... */ } catch (error) { showErrorToast(error); }

// --- React Toastify Container Reminder ---
// Remember to include <ToastContainer /> in your main layout (_app.js or Layout.js)
// e.g.,
// import { ToastContainer } from 'react-toastify';
// import 'react-toastify/dist/ReactToastify.css'; // Import CSS
// function MyApp({ Component, pageProps }) {
//   return (
//     <>
//       <Component {...pageProps} />
//       <ToastContainer
//          position="top-right"
//          autoClose={5000} // Base autoClose matches toastConfig
//          hideProgressBar={false}
//          newestOnTop={false}
//          closeOnClick
//          rtl={false}
//          pauseOnFocusLoss
//          draggable
//          pauseOnHover
//          theme="dark" // Theme matches toastConfig
//        />
//     </>
//   );
// }