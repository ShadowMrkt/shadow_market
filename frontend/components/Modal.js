// frontend/components/Modal.js
// --- REVISION HISTORY ---
// 2025-04-28: Rev 3 - [Gemini] Removed redundant event handlers (manual Escape listener, overlay onClick) causing double onClose calls. Relies solely on focus-trap-react's onDeactivate for closing.
// 2025-04-28: Rev 2 - [Gemini] Implemented focus trapping using focus-trap-react library.
//             - Added import for FocusTrap.
//             - Removed manual focus useEffect hook.
//             - Wrapped modal content div in FocusTrap component.
//             - Configured FocusTrap activation and options.
// 2025-04-07: Rev 1 - Migrated styles to CSS Module, added focus trap structure/recommendation.
//             - Removed inline styles object.
//             - Created and imported Modal.module.css.
//             - Styled for dark theme using CSS variables.
//             - Kept Escape key listener.
//             - Added refs and structure/comments strongly recommending 'focus-trap-react' for accessibility.
//             - Added comment recommending React Portals.
//             - Added revision history block.

import React, { useRef } from 'react'; // Removed useEffect as it's no longer needed
// <<< ADDED: Import FocusTrap >>>
import FocusTrap from 'focus-trap-react';
import styles from './Modal.module.css'; // Import CSS Module

// Recommendation: For robust stacking context and avoiding potential CSS issues,
// consider rendering the modal using ReactDOM.createPortal into a dedicated DOM node outside your main app root.
// import ReactDOM from 'react-dom'; -> return ReactDOM.createPortal(<div...>, document.getElementById('modal-root'));

/**
 * Renders a modal dialog component.
 * Includes overlay, close button, Escape key handling, and focus trapping via focus-trap-react.
 *
 * @param {object} props - Component props.
 * @param {boolean} props.isOpen - Whether the modal is currently visible.
 * @param {function} props.onClose - Function called when the modal requests to be closed (overlay click, Escape key, close button).
 * @param {string} [props.title] - Optional title displayed at the top of the modal.
 * @param {React.ReactNode} props.children - The content to display inside the modal.
 * @param {string} [props.modalId="modal"] - Base ID for ARIA attributes.
 * @returns {React.ReactElement | null} The modal component or null.
 */
const Modal = ({ isOpen, onClose, title, children, modalId = "modal" }) => {
    const modalRef = useRef(null); // Ref for the modal content div

    // --- REMOVED: Manual Escape key listener useEffect hook ---
    // FocusTrap handles Escape key deactivation via onDeactivate below.

    if (!isOpen) {
        return null;
    }

    // Prevent clicks inside the modal content from triggering the overlay's onClose (via focus trap deactivation)
    const handleModalClick = (e) => {
        e.stopPropagation();
    };

    const titleId = `${modalId}-title`;

    // Note: focus-trap-react handles click-outside-to-close via clickOutsideDeactivates and onDeactivate
    // The FocusTrap component handles trapping focus within the inner modal div
    return (
        <div
            className={styles.overlay}
            // --- REMOVED: onClick={onClose} from overlay ---
            // Let focus-trap-react handle clicks outside via onDeactivate
            role="dialog" // Keep role on overlay for screen reader context if needed, or move to inner div
            aria-modal="true"
            aria-labelledby={title ? titleId : undefined}
        >
            {/* <<< UPDATED: Wrap modal content in FocusTrap >>> */}
            <FocusTrap
                active={isOpen}
                focusTrapOptions={{
                    onDeactivate: onClose, // Call onClose when trap deactivates (Escape press OR click outside)
                    clickOutsideDeactivates: true, // Allow clicking overlay to deactivate trap & trigger onDeactivate
                    initialFocus: false, // Don't focus first element automatically
                    fallbackFocus: () => modalRef.current // Focus modal container if no other element found
                }}
            >
                {/* The div that is visually the modal and contains all content */}
                <div
                    ref={modalRef}
                    className={styles.modal}
                    onClick={handleModalClick} // Prevent closing when clicking INSIDE modal content
                    // Consider moving role="dialog" and aria attributes here if overlay isn't meant to be the dialog itself
                >
                    {/* Close Button */}
                    <button
                        className={styles.closeButton}
                        onClick={onClose} // Direct click on close button should still work
                        aria-label="Close Modal"
                    >
                        &times; {/* Multiplication sign used as 'X' */}
                    </button>

                    {/* Modal Title */}
                    {title && (
                        <h2 className={styles.title} id={titleId}> {/* Use ID for aria-labelledby */}
                            {title}
                        </h2>
                    )}

                    {/* Modal Content */}
                    {children}
                </div>
            </FocusTrap>
            {/* <<< END UPDATE >>> */}
        </div>
    );
};

export default Modal;

// TODO: Consider using ReactDOM.createPortal for rendering the modal outside the main app root.