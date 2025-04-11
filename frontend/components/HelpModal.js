// frontend/components/HelpModal.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 2 - Refactored to use the standard Modal component.
//           - Removed custom overlay/modal structure and styling classes.
//           - Imported and rendered components/Modal.
//           - Passed props (isOpen, onClose, title) to standard Modal.
//           - Kept original help content as children.
// 2025-04-07: Rev 1 - Initial simple implementation (not using standard Modal).

import React from 'react';
import Modal from './Modal'; // Import the standard Modal component

// Note: This component no longer needs its own CSS module. Styling comes from Modal.js
// and potentially global styles for the <p> tags inside.

/**
 * Displays help content within the standard application modal.
 *
 * @param {object} props - Component props.
 * @param {boolean} props.isOpen - Whether the modal should be displayed.
 * @param {function} props.onClose - Function called when the modal requests to be closed.
 * @returns {React.ReactElement} The help modal component using the standard Modal.
 */
export default function HelpModal({ isOpen, onClose }) {
  // The standard Modal component already handles the isOpen check,
  // so technically the `if (!isOpen) return null;` check isn't strictly
  // necessary here, but keeping it doesn't hurt.
  if (!isOpen) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Quick Help & Hints" // Pass title to the standard Modal
    >
      {/* The content paragraphs are now passed as children */}
      <p><strong>Sign Up:</strong> Enter a unique username, a strong password, and optionally your PGP public key for added security.</p>
      <p><strong>Login:</strong> Enter your username and password. Complete two‑factor authentication (TOTP or PGP) as prompted.</p>
      <p><strong>Payments:</strong> At checkout, select your cryptocurrency wallet and follow the guided instructions to securely complete your payment.</p>
      <p><strong>Orders:</strong> Track your orders in your account dashboard. Confirm delivery when received or report non‑delivery if needed.</p>
      <p><strong>Vendor Features:</strong> After paying the vendor fee, unlock the vendor dashboard to manage listings and view analytics.</p>
      <p>For more detailed instructions, please visit the Help page.</p>
      {/* Add more help content as needed */}
    </Modal>
  );
}