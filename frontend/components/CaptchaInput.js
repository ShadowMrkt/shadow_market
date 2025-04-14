// frontend/components/CaptchaInput.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 5 - Corrected input field names for django-simple-captcha compatibility.
//                           - Hidden key field name changed to 'captcha_0'.
//                           - Visible input field name changed to 'captcha_1'.
// 2025-04-13 (Gemini): Rev 4 - Added aria-live attributes for loading/error states.
//                             - Re-verified component logic against test failures; component correctly handles onChange, onRefresh, and disabled props.
//                             - Emphasized that test failures for onChange, onRefresh count, and disabled state require fixes in the test file (`CaptchaInput.test.js`).
// 2025-04-13 (Gemini): Rev 3 - Added dedicated `disabled` prop distinct from `isLoading`.
//                             - Applied `disabled` prop to input and button `disabled` attribute.
//                             - Added visually hidden text to refresh button for better accessibility and testability.
//                             - Added comments clarifying testing requirements for controlled components and button querying.
//                             - Added CSS suggestion for visually-hidden class.
// 2025-04-07: Rev 2 - Applied global classes, used CSS Module, improved error display. [...]
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update. [...]

import React from 'react';
import styles from './CaptchaInput.module.css'; // Import CSS Module for custom styles
import FormError from './FormError'; // Import FormError for consistent error display
import LoadingSpinner from './LoadingSpinner'; // Import Spinner for loading state

/**
 * Component to display a CAPTCHA image, input field, and refresh button.
 * Relies on parent component for state management and interaction with backend CAPTCHA logic.
 * Uses global CSS classes for form elements and buttons, and a CSS Module for layout.
 * **Compatible with django-simple-captcha.**
 *
 * @param {object} props - Component props.
 * @param {string | null} props.imageUrl - The RELATIVE URL path to the CAPTCHA image. Null if loading or error.
 * @param {string | null} props.inputKey - The hidden key associated with the CAPTCHA. Null if loading or error.
 * @param {string} props.value - Current value of the CAPTCHA input field (controlled).
 * @param {function} props.onChange - Function to call when the input value changes (passes event). Parent controls state.
 * @param {function} props.onRefresh - Function to call when the refresh button is clicked. Parent implements logic.
 * @param {boolean} props.isLoading - Boolean indicating if the CAPTCHA is currently loading/refreshing. Hides input/button when true.
 * @param {boolean} [props.disabled=false] - Boolean indicating if the input/button should be disabled (independent of loading state).
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
    disabled = false, // Rev 3: Added disabled prop
    required = true,
    inputId = "captcha_1", // Default ID changed to match expected name
}) => {

    // --- CRITICAL DEPENDENCY ---
    // Parent component MUST implement logic in `onRefresh` to fetch a valid
    // `imageUrl` (relative path) and `inputKey` from the backend CAPTCHA endpoint (e.g., /captcha/refresh/),
    // and manage the `value`, `isLoading`, and `disabled` state via props.

    // --- Note for Test File (`CaptchaInput.test.js`) --- Rev 4 Update ---
    // 1. Refresh Button Query: Use the accessible name provided by the visually hidden text:
    //      `screen.getByRole('button', { name: /Refresh CAPTCHA/i })`. Prefer `userEvent.click`.
    // 2. onRefresh Double Call Test: This component correctly calls the `onRefresh` prop once per click event.
    //      The double call observed (Expected 1, Received 2) likely stems from the test setup. Investigate test logic.
    // 3. onChange Test Failure: This is a controlled component. The `value` prop dictates display value.
    //      The test failure suggests an issue with the event simulation (`userEvent.type`) or mock handler in the test.
    // 4. Disabled Test Failure: Component correctly renders disabled elements. Test should assert `.toBeDisabled()`.
    // ----

    return (
        // Use global form-group class for spacing
        <div className="form-group">
            <label htmlFor={inputId} className="form-label">Enter CAPTCHA Text:</label>
            {isLoading ? (
                // Use LoadingSpinner component
                <div className={styles.loadingState} aria-live="polite"> {/* Rev 4: Added aria-live */}
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
                        name="captcha_1" // <<<--- CORRECTED NAME for user input ---<<<
                        value={value} // Controlled by parent
                        onChange={onChange} // Handled by parent - Component correctly passes the handler
                        required={required}
                        className="form-input" // Use global input style
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck="false"
                        placeholder="Enter text from image"
                        disabled={isLoading || disabled} // Rev 3: Disable if loading OR disabled prop is true
                        aria-label="CAPTCHA text input" // Explicit label for assistive tech
                    />
                    <button
                        type="button"
                        onClick={onRefresh} // Component correctly passes the handler
                        disabled={isLoading || disabled} // Rev 3: Disable if loading OR disabled prop is true
                        // Rev 3: Apply global disabled class if needed by CSS framework when disabled attribute is present
                        className={`button button-secondary ${ (isLoading || disabled) ? 'disabled' : ''}`} // Use global button styles
                        title="Get a new CAPTCHA image"
                    >
                        <span aria-hidden="true">&#x21BB;</span> {/* Refresh icon */}
                        {/* Rev 3: Added visually hidden text for accessibility and reliable test querying */}
                        <span className={styles.visuallyHidden}>Refresh CAPTCHA</span>
                    </button>
                    {/* Hidden input holds the key associated with the image */}
                    <input type="hidden" name="captcha_0" value={inputKey} />  {/* <<<--- CORRECTED NAME for hidden key ---<<< */}
                </div>
            ) : (
                // Fallback if loading finished but imageUrl/inputKey is still missing (error state)
                <div className={styles.errorState} aria-live="assertive"> {/* Rev 4: Added aria-live */}
                    <FormError message="Could not load CAPTCHA image." />
                    <button
                        type="button"
                        onClick={onRefresh} // Component correctly passes the handler
                        className="button button-secondary mt-2"
                        // Allow retry click only if not currently loading a retry attempt, and not generally disabled
                        disabled={isLoading || disabled}
                    >
                        Retry Load
                    </button>
                </div>
            )}
        </div>
    );
};

export default CaptchaInput;

/*
TODO: Create CaptchaInput.module.css for .captchaBox, .captchaImage, .loadingState, .errorState styles.
      Ensure it includes a .visuallyHidden class:
      .visuallyHidden {
        border: 0;
        clip: rect(0 0 0 0);
        height: 1px;
        margin: -1px;
        overflow: hidden;
        padding: 0;
        position: absolute;
        width: 1px;
        white-space: nowrap;
      }
*/