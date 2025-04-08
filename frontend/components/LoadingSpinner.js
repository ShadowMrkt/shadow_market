// frontend/components/LoadingSpinner.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Migrated styles to CSS Module, integrated dark theme colors via variables.
//           - Removed inline styles object and <style jsx global>.
//           - Created and imported LoadingSpinner.module.css.
//           - Defined @keyframes spin within the CSS Module.
//           - Updated spinner colors to use CSS variables from globals.css.
//           - Kept dynamic size calculation via inline style prop alongside base class.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - Added role="status" to container for improved accessibility.
//           - Added security comment regarding assumption for 'message' prop.
//           - Added comments about alternative styling approaches (CSS Modules, etc.).
//           - Added revision history block.

import React from 'react';
import styles from './LoadingSpinner.module.css'; // Import CSS Module

/**
 * Displays a CSS-based loading spinner with an optional message.
 * Uses CSS Modules for styling and integrates with the application's dark theme via CSS variables.
 * Includes ARIA role="status" for accessibility.
 *
 * @param {object} props - Component props.
 * @param {string} [props.size='1.5em'] - The width and height of the spinner (e.g., '1em', '24px').
 * @param {string | null} [props.message=null] - Optional message to display next to the spinner.
 * @param {string} [props.className=''] - Optional additional class names for the container.
 * @returns {React.ReactElement} The loading spinner component.
 */
const LoadingSpinner = ({ size = '1.5em', message = null, className = '' }) => {
    // Dynamically calculate border width based on size, ensuring a minimum
    // This part still needs inline styles as it's dynamic based on props.
    const dynamicSpinnerStyle = {
        width: size,
        height: size,
        // Adjust border width proportionally, ensuring a minimum (e.g., 2px)
        // Using CSS max() function requires browser support, fallback might be needed for older browsers
        // Alternatively, calculate in JS: const borderWidth = `max(2px, ${parseFloat(size) / 8}${size.replace(/[\d.-]/g, '')})`
        borderWidth: `max(2px, calc(${size} / 8))`,
    };

    // SECURITY NOTE: Assumes 'message' prop is a safe string (e.g., developer-defined).
    // Relies on React's default JSX escaping for strings.

    return (
        // ACCESSIBILITY: role="status" makes screen readers announce this as status information (loading).
        // Combine passed className with module className
        <div className={`${styles.spinnerContainer} ${className}`} role="status">
            {/* Apply base styles via CSS Module class, dynamic size/border via inline style */}
            <div
                className={styles.spinnerBase}
                style={dynamicSpinnerStyle}
                aria-hidden="true" // Hide decorative spinner element from screen readers
            ></div>
            {/* Display optional message */}
            {message && <span className={styles.messageText}>{message}</span>}
        </div>
    );
};

export default LoadingSpinner;

// TODO: Create LoadingSpinner.module.css defining .spinnerContainer, .spinnerBase, .messageText, and @keyframes spin.