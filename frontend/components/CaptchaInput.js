// frontend/components/CaptchaInput.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Applied global classes, used CSS Module, improved error display.
//           - Removed inline styles object.
//           - Applied global .form-*, .button classes.
//           - Created CaptchaInput.module.css for custom layout/image styles.
//           - Styled for dark theme via CSS variables (in module).
//           - Used FormError component for loading failure message. Added retry button.
//           - Added TODO to consider next/image.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - CRITICAL FIX: Removed incorrect API_BASE_URL prefix from image src. [...]
//           - Added comments emphasizing reliance on parent component providing correct props [...].
//           - Added explicit <label> for accessibility.
//           - Added comment recommending CSS Modules/global styles.
//           - Added revision history block.

import React from 'react';
import styles from './CaptchaInput.module.css'; // Import CSS Module for custom styles
import FormError from './FormError'; // Import FormError for consistent error display
import LoadingSpinner from './LoadingSpinner'; // Import Spinner for loading state

/**
 * Component to display a CAPTCHA image, input field, and refresh button.
 * Relies on parent component for state management and interaction with backend CAPTCHA logic.
 * Uses global CSS classes for form elements and buttons, and a CSS Module for layout.
 *
 * @param {object} props - Component props.
 * @param {string | null} props.imageUrl - The RELATIVE URL path to the CAPTCHA image. Null if loading or error.
 * @param {string | null} props.inputKey - The hidden key associated with the CAPTCHA. Null if loading or error.
 * @param {string} props.value - Current value of the CAPTCHA input field (controlled).
 * @param {function} props.onChange - Function to call when the input value changes (passes event).
 * @param {function} props.onRefresh - Function to call when the refresh button is clicked.
 * @param {boolean} props.isLoading - Boolean indicating if the CAPTCHA is currently loading/refreshing.
 * @param {boolean} [props.required=true] - Standard HTML required attribute for the input.
 * @param {string} [props.inputId="captchaInput"] - Customizable ID for label association.
 * @returns {React.ReactElement} The CAPTCHA input component.
 */
const CaptchaInput = ({
    imageUrl,
    inputKey,
    value,
    onChange,
    onRefresh,
    isLoading,
    required = true,
    inputId = "captchaInput",
}) => {

    // --- CRITICAL DEPENDENCY ---
    // Parent component MUST implement logic in `onRefresh` to fetch a valid
    // `imageUrl` (relative path) and `inputKey` from the backend CAPTCHA endpoint.

    return (
        // Use global form-group class for spacing
        <div className="form-group">
            <label htmlFor={inputId} className="form-label">Enter CAPTCHA Text:</label>
            {isLoading ? (
                // Use LoadingSpinner component
                <div className={styles.loadingState}>
                    <LoadingSpinner size="1.2em" message="Loading CAPTCHA..." />
                </div>
            ) : imageUrl && inputKey ? (
                // Display CAPTCHA image, input, and refresh button
                // Use CSS Module for layout container
                <div className={styles.captchaBox}>
                    {/* TODO: Consider replacing <img> with next/image if dimensions are consistent */}
                    <img
                        // Use relative imageUrl directly
                        src={imageUrl}
                        alt="CAPTCHA security challenge image" // Slightly more specific alt
                        className={styles.captchaImage} // Style via module
                        width={150} // Adjust based on actual CAPTCHA image dimensions
                        height={50}
                    />
                    <input
                        type="text"
                        id={inputId}
                        name="captcha_value" // Form submission name
                        value={value}
                        onChange={onChange}
                        required={required}
                        className="form-input" // Use global input style
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck="false"
                        placeholder="Enter text from image"
                        disabled={isLoading} // Already handled loading state above, but keep for robustness
                        aria-label="CAPTCHA text input" // Explicit label for assistive tech
                    />
                    <button
                        type="button"
                        onClick={onRefresh}
                        disabled={isLoading} // Disable button only during loading
                        className={`button button-secondary ${isLoading ? 'disabled' : ''}`} // Use global button styles
                        title="Get a new CAPTCHA image"
                    >
                        {/* Replace text with an icon potentially */}
                        &#x21BB; {/* Refresh icon */}
                        {/* Refresh */}
                    </button>
                    {/* Hidden input holds the key associated with the image */}
                    <input type="hidden" name="captcha_key" value={inputKey} />
                </div>
            ) : (
                // Fallback if loading finished but imageUrl/inputKey is still missing (error state)
                <div className={styles.errorState}>
                    <FormError message="Could not load CAPTCHA image." />
                    <button
                        type="button"
                        onClick={onRefresh}
                        className="button button-secondary mt-2"
                        disabled={isLoading} // Allow retry even if loading=false but image failed
                    >
                        Retry Load
                    </button>
                </div>
            )}
        </div>
    );
};

export default CaptchaInput;

// TODO: Create CaptchaInput.module.css for .captchaBox, .captchaImage, .loadingState, .errorState styles.