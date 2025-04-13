// frontend/components/PgpChallengeSigner.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 3 - Added data-testid to <pre> for robust test querying.
//                      - Added comments clarifying test requirements for clipboard mocking and controlled textarea onChange assertions. No functional code changes.
// 2025-04-07: Rev 2 - Introduced minimal CSS Module for button/list styling.
//                   - Removed reliance on potentially non-existent global .button-sm class.
//                   - Applied module classes for copy button and instruction list styles.
//                   - Continued using global classes for main elements.
// 2025-04-07: Rev 1 - Applied global classes, added Copy button, accessibility improvements.
//                   - Removed inline styles object.
//                   - Applied global .info-message, .form-*, .button, .code-block classes.
//                   - Added "Copy Challenge" button with clipboard functionality.
//                   - Added ARIA attributes linking signature input to challenge text.
//                   - Added customizable label props.
//                   - Added revision history block.

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

    // --- Note for Test File (`PgpChallengeSigner.test.js`) ---
    // 1. Querying Challenge Text: Use the added data-testid for reliability:
    //    `screen.getByTestId('pgp-challenge-text-block')` and check its `textContent`.
    //    Using `getByText` directly on preformatted text with internal nodes is fragile.
    // 2. Clipboard Tests: These tests fail because `navigator.clipboard.writeText` is likely
    //    not mocked correctly in the JSDOM test environment. You need to set up a mock before rendering:
    //    ```
    //    Object.defineProperty(navigator, 'clipboard', {
    //      value: { writeText: jest.fn().mockResolvedValue(undefined) /* or .mockRejectedValue for error test */ },
    //      writable: true, configurable: true
    //    });
    //    const mockWriteText = navigator.clipboard.writeText;
    //    ```
    //    Then assert `expect(mockWriteText).toHaveBeenCalledWith(...)`.
    // 3. onChange Test (Textarea): This is a controlled component. The test failure
    //    (Expected: "new..." / Received: "initial...") is likely due to asserting on the
    //    immediate event object. The test should verify `onSignatureChange` was called, and potentially
    //    `waitFor` the component to re-render with the new `signatureValue` prop before checking
    //    `screen.getByLabelText(...).toHaveValue("new signature content")`.
    // ----

    const handleCopyChallenge = () => {
        if (!challengeText) {
            showErrorToast("No challenge text available to copy.");
            return;
        }
        // Check if clipboard API is available (important for some environments/browsers)
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
            console.error("Clipboard API (writeText) not available.");
            showErrorToast('Clipboard API not supported or available in this context.');
            // Optionally, provide manual copy instructions here.
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
                {/* Rev 3: Added data-testid for reliable querying */}
                <pre
                  id={challengeTextId}
                  className="code-block"
                  style={{maxHeight: '150px'}}
                  data-testid="pgp-challenge-text-block"
                >
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
                    value={signatureValue} // Controlled
                    onChange={onSignatureChange} // Propagated
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