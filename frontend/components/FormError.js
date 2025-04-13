// frontend/components/FormError.js
// --- REVISION HISTORY ---
// 2025-04-13: Rev 5 - Reinstated role="alert". Test failures indicated that delegating this role to consumers was problematic/inconsistent with component usage (e.g., in register.js) and test mocks. FormError should manage its own alert role. (Gemini)
// 2025-04-12: Rev 4 - Removed redundant role="alert" from internal div. (Gemini) // REVERTING THIS CHANGE
// 2025-04-11: Rev 3 - No functional changes. Analysis suggests component is likely correct.
// 2025-04-07: Rev 2 - Refactored to use global .error-message class, added className prop, refined formatting.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.

import React from 'react';

/**
 * Displays an error message, handling strings, Error objects, and basic
 * DRF-like field error object structures ({ field: [errors], ... }).
 * Uses the globally defined `.error-message` class for styling.
 * Returns null if no message or an empty object/array is provided.
 * Includes role="alert" for accessibility when an error is displayed.
 *
 * @param {object} props - Component props.
 * @param {string | Error | object | null | undefined} props.message - The error content to display.
 * @param {string} [props.className=''] - Optional additional class names for the container.
 * @returns {React.ReactElement | null} The error message component or null.
 */
const FormError = ({ message, className = '' }) => {
    // Don't render anything if the message is null, undefined, or an empty string
    if (!message) {
        return null;
    }

    let displayMessage = '';
    const defaultErrorText = "An unknown error occurred.";

    // --- Error Content Formatting ---
    if (typeof message === 'string') {
        displayMessage = message;
    } else if (message instanceof Error) {
        displayMessage = message.message || defaultErrorText;
    } else if (typeof message === 'object' && message !== null && Object.keys(message).length > 0) {
        // Format assuming DRF-like field errors: { field_name: ["Msg1.", "Msg2."], ... }
        // Adjust this logic if your API returns errors differently.
        displayMessage = Object.entries(message)
            .map(([field, messages]) => {
                // Ignore fields specifically named 'code' if backend sends structured errors like { code: '...', detail: '...' }
                if (field === 'code') return null;

                // Format field name (replace underscore, capitalize) - skip for 'non_field_errors' or 'detail'
                const formattedField = (field === 'non_field_errors' || field === 'detail')
                    ? ''
                    : field.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) + ': ';
                // Join array messages, otherwise use message directly
                const messageText = Array.isArray(messages) ? messages.join(' ') : String(messages);
                return `${formattedField}${messageText}`;
            })
            .filter(line => line !== null) // Remove skipped lines (like 'code')
            .join('\n'); // Join different field errors with newlines

        // Handle cases where the object might format to an empty string (e.g., only contained 'code')
        if (!displayMessage.trim()) {
            displayMessage = defaultErrorText;
        }
    } else {
        // Fallback for unexpected types or empty objects/arrays
        return null; // Don't render if we couldn't format meaningfully
    }

    // Final check for an empty resulting message after formatting
    if (!displayMessage.trim()) {
        return null;
    }

    // --- Security Note (XSS) ---
    // React automatically escapes string content rendered within JSX `{...}`.
    // This prevents raw HTML/script tags within the `displayMessage` string
    // from being executed. Ensure the source message/error is trustworthy.

    // Render the error message using the global style and include accessibility role.
    return (
        <div
            // Apply global error class and any additional passed classes
            // The global .error-message class should handle styles (bg, color, border, padding, etc.)
            // and `white-space: pre-wrap;` for multi-line display.
            className={`error-message ${className}`.trim()} // Use trim() for cleaner class string
            // <<< REVISION 5: Reinstated role="alert" for accessibility >>>
            role="alert"
        >
            {displayMessage}
        </div>
    );
};

export default FormError;