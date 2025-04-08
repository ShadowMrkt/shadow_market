// frontend/components/Modal.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Migrated styles to CSS Module, added focus trap structure/recommendation.
//           - Removed inline styles object.
//           - Created and imported Modal.module.css.
//           - Styled for dark theme using CSS variables.
//           - Kept Escape key listener.
//           - Added refs and structure/comments strongly recommending 'focus-trap-react' for accessibility.
//           - Added comment recommending React Portals.
//           - Added revision history block.

import React, { useEffect, useRef } from 'react';
import styles from './Modal.module.css'; // Import CSS Module

// Recommendation: For robust stacking context and avoiding potential CSS issues,
// consider rendering the modal using ReactDOM.createPortal into a dedicated DOM node outside your main app root.
// import ReactDOM from 'react-dom'; -> return ReactDOM.createPortal(<div...>, document.getElementById('modal-root'));

/**
 * Renders a modal dialog component.
 * Includes overlay, close button, Escape key handling, and structure for focus trapping.
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
    const previousFocusRef = useRef(null); // Ref to store previously focused element

    // Handle Escape key press
    useEffect(() => {
        const handleEscape = (event) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };

        if (isOpen) {
            document.addEventListener('keydown', handleEscape);
        }

        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, onClose]);

    // --- Accessibility: Focus Trapping ---
    // TODO CRITICAL: Implement robust focus trapping. The code below sets up refs,
    // but manual implementation is complex. Strongly recommend using a library like 'focus-trap-react'.
    // Example using focus-trap-react: Wrap the inner modal div:
    // import FocusTrap from 'focus-trap-react';
    // ...
    // <FocusTrap active={isOpen} focusTrapOptions={{ initialFocus: false, // Or target specific element
    //                                                 onDeactivate: onClose,
    //                                                 clickOutsideDeactivates: true}}>
    //    <div ref={modalRef} className={styles.modal} onClick={handleModalClick}>...</div>
    // </FocusTrap>
    useEffect(() => {
        if (isOpen) {
             // Store the element that had focus before the modal opened
             previousFocusRef.current = document.activeElement;

             // --- Focus Trap Logic Placeholder ---
             // Library 'focus-trap-react' handles this automatically and robustly.
             // Manual implementation would involve:
             // 1. Finding all focusable elements inside modalRef.current.
             // 2. Setting initial focus (e.g., modalRef.current.focus() or first focusable element).
             // 3. Adding a keydown listener to trap Tab/Shift+Tab within the modal.
             // --- End Placeholder ---

             // Make the modal container itself focusable if it doesn't have focusable children initially
             if (modalRef.current && !modalRef.current.contains(document.activeElement)) {
                modalRef.current.setAttribute('tabindex', '-1'); // Make it focusable
                modalRef.current.focus();
             }

        } else {
            // Return focus to the element that opened the modal when it closes
            if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
                previousFocusRef.current.focus();
            }
            previousFocusRef.current = null; // Clear the ref
        }

        // Cleanup for manual focus trap listener would go here
        return () => {
            // Remove keydown listener if implemented manually
        };
    }, [isOpen]); // Rerun when isOpen changes


    if (!isOpen) {
        return null;
    }

    // Prevent clicks inside the modal content from triggering the overlay's onClose
    const handleModalClick = (e) => {
        e.stopPropagation();
    };

    const titleId = `${modalId}-title`;

    return (
        <div
            className={styles.overlay}
            onClick={onClose} // Close when clicking the overlay
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? titleId : undefined} // Only label if title exists
        >
            {/* Use ref here for focus management */}
            <div
                ref={modalRef}
                className={styles.modal}
                onClick={handleModalClick} // Prevent closing when clicking inside
                // Optional: Add aria-describedby if there's a primary descriptive element
                // aria-describedby={`${modalId}-description`}
            >
                {/* Close Button */}
                <button
                    className={styles.closeButton}
                    onClick={onClose}
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
        </div>
    );
};

export default Modal;

// TODO: Create Modal.module.css for overlay, modal, closeButton, title styles using CSS variables.
// TODO: Implement focus trapping using 'focus-trap-react' or manually (manual implementation is complex).
// TODO: Consider using ReactDOM.createPortal for rendering the modal outside the main app root.