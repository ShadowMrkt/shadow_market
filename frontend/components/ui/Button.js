// frontend/components/ui/Button.js
// --- REVISION HISTORY ---
// 2025-04-08: Rev 2 - Added optional isLoading prop to show spinner and disable button.
//           - Clarified styling expectations in comments (relies on external classes).
//           - Imported LoadingSpinner. Updated PropTypes.
// 2025-04-08: Rev 1 - Initial creation. Basic functional button component.
//           - Handles children, onClick, disabled, type, className and forwards other props.
//           - Added default props and optional PropTypes.

import React from 'react';
import PropTypes from 'prop-types';
import LoadingSpinner from '../LoadingSpinner'; // Assuming spinner is in components/

/**
 * A reusable Button component that renders an HTML <button>.
 * Relies entirely on the `className` prop for styling. It is expected that
 * consumers will pass necessary classes (e.g., global .button and its variants
 * like .button-primary, .disabled, or utility classes like Tailwind) via `className`.
 *
 * @component
 * @param {object} props - Component props.
 * @param {React.ReactNode} props.children - Content displayed inside the button (usually text). Required unless isLoading is true.
 * @param {Function} [props.onClick] - Function called when clicked.
 * @param {boolean} [props.disabled=false] - If true, the button is disabled (takes precedence over isLoading visual state if manually set).
 * @param {boolean} [props.isLoading=false] - If true, displays a spinner instead of children and disables the button.
 * @param {'button' | 'submit' | 'reset'} [props.type='button'] - Button's type attribute.
 * @param {string} [props.className=''] - CSS classes for styling (e.g., "button button-primary").
 * Additional standard HTML button attributes (aria-label, id, title, etc.) are captured via ...rest.
 * @returns {React.ReactElement} The rendered button element.
 */
const Button = ({
  children,
  onClick,
  disabled = false,
  isLoading = false, // Added isLoading prop
  type = 'button',
  className = '', // Expect consumer to pass styling classes
  ...rest // Capture other standard button attributes
}) => {

  // Button is functionally disabled if explicitly set OR if loading
  const isDisabled = disabled || isLoading;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      // Apply passed className. Consumer is responsible for base styles, variants, and disabled styles.
      // Example: className="button button-primary" or className={`button button-danger ${isDisabled ? 'disabled' : ''}`}
      className={className}
      // Add aria-disabled for better accessibility indication when functionally disabled by isLoading
      aria-disabled={isDisabled ? true : undefined}
      {...rest} // Spread remaining props
    >
      {/* Show spinner if isLoading, otherwise show children */}
      {isLoading ? (
        // Render spinner centered within the button
        // Use '1em' size to match button font size, adjust color if needed via className
        <LoadingSpinner size="1em" aria-label="Loading" />
      ) : (
        children
      )}
    </button>
  );
};

// Optional: Define prop types for type checking during development
Button.propTypes = {
  /**
   * Content rendered inside (usually text or icon). Not rendered if isLoading is true.
   */
  children: PropTypes.node, // Not strictly required if isLoading can be true
  /**
   * Function called when the button is clicked.
   */
  onClick: PropTypes.func,
  /**
   * If true, the button is non-interactive. Overrides isLoading visually if set to true.
   */
  disabled: PropTypes.bool,
  /**
   * If true, shows a loading spinner instead of children and disables the button.
   */
  isLoading: PropTypes.bool, // Added prop type
  /**
   * Sets the button's behavior type.
   */
  type: PropTypes.oneOf(['button', 'submit', 'reset']),
  /**
   * CSS classes to apply for styling (e.g., "button button-primary"). Consumer provides styles.
   */
  className: PropTypes.string,
};

export default Button;