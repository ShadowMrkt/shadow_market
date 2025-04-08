// frontend/components/PgpChallengeSigner.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Introduced minimal CSS Module for button/list styling.
//           - Removed reliance on potentially non-existent global .button-sm class.
//           - Applied module classes for copy button and instruction list styles.
//           - Continued using global classes for main elements.
// 2025-04-07: Rev 1 - Applied global classes, added Copy button, accessibility improvements.
//           - Removed inline styles object.
//           - Applied global .info-message, .form-*, .button, .code-block classes.
//           - Added "Copy Challenge" button with clipboard functionality.
//           - Added ARIA attributes linking signature input to challenge text.
//           - Added customizable label props.
//           - Added revision history block.

import React from 'react';
import { showSuccessToast, showErrorToast } from '../utils/notifications';
import styles from './PgpChallengeSigner.module.css'; // Import CSS Module

/**
 * Renders the UI for a PGP signing challenge. Displays instructions,
 * the challenge text (with a copy button), and a textarea for the user's signature.
 * Relies on global CSS classes & a minimal CSS module.
 */
const PgpChallengeSigner = ({
    challengeText,
    signatureValue,
    onSignatureChange,
    username,
    disabled = false,
    challengeLabel = "Challenge Text to Sign:",
    signatureLabel = "Paste Your PGP Signature Block:",
    challengeTextId = "pgpChallengeText",
    signatureInputId = "pgpSignatureInput",
}) => {

    const handleCopyChallenge = () => {
        // ... (copy logic remains the same)
        if (!challengeText) {
            showErrorToast("No challenge text available to copy.");
            return;
        }
        navigator.clipboard.writeText(challengeText)
            .then(() => showSuccessToast('Challenge text copied to clipboard!'))
            .catch(err => {
                console.error("Failed to copy challenge text:", err);
                showErrorToast('Failed to copy text automatically. Please copy manually.');
            });
    };

    return (
        <div>
            {/* Use global info message style */}
            <div className="info-message">
                <p><strong>Instructions for PGP Signature:</strong></p>
                {/* Apply module style to the list */}
                <ol className={styles.instructionList}>
                    <li>Copy the entire "{challengeLabel}" block below.</li>
                    <li>Use your PGP software and the private key associated with user <strong>{username}</strong> to <strong>sign</strong> the copied text (Clearsign).</li>
                    <li>Ensure you create an ASCII armored signature (usually starting with <code>-----BEGIN PGP SIGNATURE-----</code>).</li>
                    <li>Copy the <strong>entire PGP signature block</strong>.</li>
                    <li>Paste the signature block into the "{signatureLabel}" text area below.</li>
                </ol>
            </div>

            {/* Challenge Text Display */}
            <div className="form-group">
                <label className="form-label">{challengeLabel}</label>
                {/* Use global code block style */}
                <pre id={challengeTextId} className="code-block" style={{maxHeight: '150px'}}>
                    <code>{challengeText || 'Loading challenge...'}</code>
                </pre>
                {challengeText && (
                    <button
                        type="button"
                        onClick={handleCopyChallenge}
                        // Use global button styles + module style for size/margin
                        className={`button button-secondary ${styles.copyButton}`}
                        title="Copy challenge text to clipboard"
                        disabled={disabled}
                    >
                        Copy Challenge
                    </button>
                )}
            </div>

            {/* Signature Input */}
            <div className="form-group">
                <label htmlFor={signatureInputId} className="form-label">{signatureLabel}</label>
                <textarea
                    id={signatureInputId}
                    value={signatureValue}
                    onChange={onSignatureChange}
                    required
                    className="form-textarea font-monospace" // Use global textarea/font styles
                    rows={10}
                    placeholder="-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----"
                    disabled={disabled}
                    aria-describedby={challengeTextId}
                    spellCheck="false"
                    autoCapitalize='off'
                    autoCorrect='off'
                />
            </div>
        </div>
    );
};

export default PgpChallengeSigner;

// TODO: Create PgpChallengeSigner.module.css for .instructionList and .copyButton styles.