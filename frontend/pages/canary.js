// frontend/pages/canary.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global classes, used CSS Module, added Copy buttons.
//           - Removed inline styles object.
//           - Applied global .container-narrow, .card, .p-4, .code-block, .warning-message, .text-muted classes.
//           - Created Canary.module.css for custom styles (fingerprintBlock, codeInline, etc.).
//           - Added Copy buttons for Fingerprint, Signed Data, and Signature.
//           - Used shared formatters/notifications utils.
//           - Added revision history block.

import React from 'react';
import Layout from '../components/Layout';
import { getCanaryData } from '../utils/api'; // TODO: Verify API function exists and fetches needed fields
import Link from 'next/link';
import FormError from '../components/FormError';
import { formatDate } from '../utils/formatters'; // Use shared formatter
import { showSuccessToast, showErrorToast } from '../utils/notifications'; // For copy feedback
import styles from './Canary.module.css'; // Import CSS Module for custom styles

// Function to fetch data server-side
export async function getServerSideProps(context) {
    try {
        // Ensure getCanaryData fetches: content, last_updated, signature, fingerprint, key_url
        const canaryData = await getCanaryData();
        return { props: { canaryData: canaryData || null, error: null } };
    } catch (err) {
        console.error("Failed to fetch canary data:", err);
        const errorMessage = err.response?.data?.detail || err.message || "Could not load canary data.";
        return { props: { canaryData: null, error: errorMessage } };
    }
}

// Helper to format fingerprint for better readability
const formatFingerprint = (fp) => {
    if (!fp || typeof fp !== 'string' || fp.length < 8) return fp; // Basic check
    // Add spaces every 4 characters for common display format
    return fp.replace(/(.{4})/g, '$1 ').trim();
};

// Helper for copy to clipboard
const copyToClipboard = (text, successMessage) => {
    if (!text) {
        showErrorToast("Nothing to copy.");
        return;
    }
    navigator.clipboard.writeText(text)
        .then(() => showSuccessToast(successMessage || 'Copied to clipboard!'))
        .catch(err => {
            console.error("Clipboard copy failed:", err);
            showErrorToast('Failed to copy automatically. Please copy manually.');
        });
};

export default function CanaryPage({ canaryData, error }) {

    const {
        canary_content,
        canary_last_updated,
        canary_pgp_signature,
        canary_signing_key_fingerprint,
        canary_signing_key_url
    } = canaryData || {}; // Default to empty object

    // Construct the exact data that should have been signed for verification display.
    // CRITICAL: Ensure this matches the backend signing process EXACTLY.
    const signedDataFormat = (canary_content && canary_last_updated)
        ? `${canary_content.trimRight()}\n${canary_last_updated}`
        : null; // Set to null if data is missing


    return (
        <Layout>
            {/* Use global narrow container */}
            <div className="container-narrow">
                {/* Use global card style */}
                <div className="card p-4">
                    <h1 className="mb-4">Warrant Canary</h1>

                    {error && <FormError message={error} />}

                    {!error && !canaryData && (
                        <p className="text-muted">Warrant canary information is currently unavailable.</p>
                    )}

                    {canaryData && (
                        <>
                            <p>
                                This page serves as a warrant canary. It is a statement published regularly, intended to implicitly notify users if the market operators have been served with a secret government subpoena or warrant demanding user data, server access, or modifications to the site that cannot be openly disclosed.
                            </p>
                            <p>
                                The canary statement below is regularly updated and cryptographically signed using the market administration's PGP key. If the statement is not updated by the expected date, or if the PGP signature fails verification, users should exercise extreme caution as it may indicate compromise.
                            </p>

                            <section className="mt-4">
                                <h2 className={styles.sectionTitle}>Canary Statement</h2>
                                <p>
                                    <strong>Last Updated (YYYY-MM-DD):</strong>{' '}
                                    <span className={styles.dateHighlight}>{formatDate(canary_last_updated) || 'Not Set'}</span>
                                </p>
                                {/* Use global code block style */}
                                <pre className="code-block"><code>
                                    {canary_content || '(No canary statement has been set yet.)'}
                                </code></pre>
                            </section>

                            <section className="mt-4">
                                <h2 className={styles.sectionTitle}>Signing Key Details</h2>
                                {canary_signing_key_fingerprint ? (
                                    <>
                                        <p>This canary was signed with the PGP key identified by the following fingerprint:</p>
                                        <div className={styles.fingerprintContainer}>
                                            {/* Use module style for fingerprint block */}
                                            <code className={styles.fingerprintBlock} title="PGP Key Fingerprint">
                                                {formatFingerprint(canary_signing_key_fingerprint)}
                                            </code>
                                             <button
                                                type="button"
                                                onClick={() => copyToClipboard(canary_signing_key_fingerprint, 'Fingerprint copied!')}
                                                className={`button button-secondary button-sm ${styles.copyButton}`}
                                                title="Copy Fingerprint">
                                                Copy
                                            </button>
                                            {/* Optional link to key source */}
                                            {canary_signing_key_url && (
                                                <a href={canary_signing_key_url} target="_blank" rel="noopener noreferrer" className={styles.keyUrlLink}>
                                                    [Verify/Download Key]
                                                </a>
                                            )}
                                        </div>
                                        <p className="mt-2 text-muted small">
                                            You must independently verify this fingerprint matches the official, trusted market key obtained from a reliable source (e.g., known forum posts, trusted directories). Do NOT trust the key just because it's displayed or linked here.
                                        </p>
                                    </>
                                ) : (
                                    <p className="text-warning">Signing key fingerprint is not currently specified.</p> // Use global text class
                                )}
                            </section>

                            <section className="mt-4">
                                <h2 className={styles.sectionTitle}>PGP Signature</h2>
                                <p>The following signature covers the exact text of the statement above plus a newline and the "Last Updated" date ({formatDate(canary_last_updated) || 'YYYY-MM-DD'}).</p>
                                {/* Use global code block style */}
                                <pre className="code-block"><code>
                                    {canary_pgp_signature || '(No signature available.)'}
                                </code></pre>
                                {canary_pgp_signature && (
                                     <button
                                        type="button"
                                        onClick={() => copyToClipboard(canary_pgp_signature, 'Signature copied!')}
                                        className={`button button-secondary button-sm ${styles.copyButton}`}
                                        title="Copy PGP Signature Block">
                                        Copy Signature
                                    </button>
                                )}
                            </section>

                            <section className={`mt-4 ${styles.verificationSection}`}>
                                <h2 className={styles.sectionTitle}>Manual Verification Instructions (Using GPG)</h2>
                                {canary_signing_key_fingerprint && canary_pgp_signature && signedDataFormat ? (
                                    <>
                                        <p>To manually verify the integrity and date of this statement using GnuPG (GPG):</p>
                                        <ol>
                                            <li className={styles.listItem}>
                                                <strong>Obtain & Verify the Public Key:</strong> Ensure you have the official Shadow Market PGP public key whose fingerprint is{' '}
                                                <code className={styles.codeInline}>{formatFingerprint(canary_signing_key_fingerprint)}</code>.
                                                Import it into your GPG keyring. Verify the fingerprint meticulously against a trusted source.
                                                {canary_signing_key_url && <a href={canary_signing_key_url} target="_blank" rel="noopener noreferrer" className={styles.keyUrlLink}>[Key URL]</a>}
                                            </li>
                                            <li className={styles.listItem}>
                                                 <strong>Prepare Signed Data:</strong> Save the **exact** text below (including the newline between content and date) to a plain text file (e.g., <code className={styles.codeInline}>canary_data.txt</code>).
                                                 {/* Use global code block style */}
                                                 <pre className="code-block mt-2"><code>{signedDataFormat}</code></pre>
                                                 <button
                                                    type="button"
                                                    onClick={() => copyToClipboard(signedDataFormat, 'Data to verify copied!')}
                                                    className={`button button-secondary button-sm ${styles.copyButton}`}
                                                    title="Copy Data to Verify">
                                                    Copy Data
                                                </button>
                                             </li>
                                            <li className={styles.listItem}>
                                                <strong>Save the Signature:</strong> Save the PGP signature block (from the "PGP Signature" section above) to another plain text file (e.g., <code className={styles.codeInline}>canary.sig</code>). Include BEGIN/END lines.
                                            </li>
                                            <li className={styles.listItem}>
                                                <strong>Run Verification Command:</strong> Open your terminal and run:
                                                {/* Use global code block style */}
                                                <pre className="code-block mt-2"><code>gpg --verify canary.sig canary_data.txt</code></pre>
                                            </li>
                                            <li className={styles.listItem}>
                                                <strong>Check GPG Output:</strong> Carefully examine the output. Look for:
                                                <ul className="mt-2">
                                                    <li><code className={styles.codeInline}>gpg: Good signature from "[Key Owner Name/UID]" [...]</code></li>
                                                    <li>Primary key fingerprint matching: <code className={styles.codeInline}>{formatFingerprint(canary_signing_key_fingerprint)}</code>.</li>
                                                    <li>Signature timestamp close to the "Last Updated" date: <code className={styles.codeInline}>{formatDate(canary_last_updated)}</code>.</li>
                                                    <li>Any warnings about key validity (expired, not trusted, etc.). Your trust depends on independent key verification.</li>
                                                </ul>
                                            </li>
                                        </ol>
                                        <p className="mt-3"><strong>If verification fails, the fingerprint mismatches, or the canary is outdated, assume potential compromise and act cautiously.</strong></p>
                                    </>
                                ) : (
                                    <p className="text-muted">Cannot provide full verification instructions as canary content, signature, or signing key fingerprint is missing.</p>
                                )}
                            </section>
                        </>
                    )}
                </div>
            </div>
        </Layout>
    );
}

// TODO: Create Canary.module.css for .sectionTitle, .dateHighlight, .fingerprintContainer, .fingerprintBlock, .copyButton, .keyUrlLink, .listItem, .codeInline, .verificationSection styles.
// TODO: Ensure getCanaryData in utils/api.js fetches all required fields.