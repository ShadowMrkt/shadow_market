import React from 'react';

export default function HelpModal({ isOpen, onClose }) {
  if (!isOpen) return null;
  return (
    <div className="help-modal-overlay" onClick={onClose}>
      <div className="help-modal" onClick={(e) => e.stopPropagation()}>
        <button className="help-close" onClick={onClose}>X</button>
        <h2>Quick Help &amp; Hints</h2>
        <p><strong>Sign Up:</strong> Enter a unique username, a strong password, and optionally your PGP public key for added security.</p>
        <p><strong>Login:</strong> Enter your username and password. Complete two‑factor authentication (TOTP or PGP) as prompted.</p>
        <p><strong>Payments:</strong> At checkout, select your cryptocurrency wallet and follow the guided instructions to securely complete your payment.</p>
        <p><strong>Orders:</strong> Track your orders in your account dashboard. Confirm delivery when received or report non‑delivery if needed.</p>
        <p><strong>Vendor Features:</strong> After paying the vendor fee, unlock the vendor dashboard to manage listings and view analytics.</p>
        <p>For more detailed instructions, please visit the Help page.</p>
      </div>
    </div>
  );
}
