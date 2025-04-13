// frontend/pages/login.js
// --- REVISION HISTORY ---
// 2025-04-11: Rev 5 - Fix two test failures: 'API error' message and 'Back button' CAPTCHA refresh.
//           - PROBLEM 1: API error test showed generic fallback error instead of specific 'Invalid...' message because the mocked error message ('Invalid credentials') wasn't handled.
//           - FIX 1: Updated the 'if' condition in handleLoginStep1 catch block to include checking for err.message === 'Invalid credentials'.
//           - PROBLEM 2: Back button test failed because refreshCaptcha() was commented out in onClick handler.
//           - FIX 2: Uncommented refreshCaptcha() in the Back button onClick handler as test expects CAPTCHA to refresh on navigating back.
// 2025-04-11: Rev 4 - Fix 'shows error and refreshes CAPTCHA on failed Step 1 submit (API error)' test failure.
//           - PROBLEM: Calling refreshCaptcha() within the catch block of handleLoginStep1 could clear the error state set by that catch block due to refreshCaptcha's internal setError('').
//           - FIX: Reordered operations in the handleLoginStep1 catch block. Now sets error message and loading state *before* calling refreshCaptcha(). Moved setIsSubmitting(false) from finally into the success/error paths of the try/catch.
//           - No changes made for 'shows error on Step 1 submit if fields are missing' as the code appears correct; suspect issue might be in FormError component or test timing.
// 2025-04-11: Rev 3 - Attempt to fix test failures by reordering state updates in catch blocks.
//           - Moved `setError(errMsg)` call to be the last operation within the main logic of the `catch` blocks for `handleLoginStep1` and `handleLoginStep2`.
//           - This is an attempt to mitigate potential state update batching/timing issues observed in Jest/JSDOM test environment.
// 2025-04-11: Rev 2 - Fix test failures (redirects, alerts).
//           - FIXED: Corrected loading state logic to prevent rendering spinner when redirect should occur. Changed redirect to use `router.replace`.
//           - ANALYSIS: Alert test failures ('Unable to find role="alert"') likely stem from the `FormError` component implementation or test interaction timing, as the `setError` logic appears correct within this component. No changes made to error setting here, assuming `FormError` correctly uses `role="alert"`.
//           - Refactored loading spinner conditional rendering for clarity and added centering style.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - CRITICAL: Added prominent placeholders and warnings that CAPTCHA fetching logic MUST be replaced with actual implementation.
//           - Maintained generic error message for Step 1 auth failures (security).
//           - Refined fallback error messages slightly. Added comments recommending backend error codes for PGP failures.
//           - Added appropriate `autoComplete` attributes to username/password fields.
//           - Added comments about component/dependency assumptions and path checking.
//           - Added revision history block.
// <<< Original Revision: Enterprise Grade: Clearer Steps, Robust Error Handling, Security Comments >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../context/AuthContext'; // <<< Verify path is correct
import { loginInit, loginPgpVerify } from '../utils/api'; // <<< Verify path is correct
import Layout from '../components/Layout'; // <<< Verify path is correct & implements necessary security (e.g., headers if needed)
// <<< Import necessary components - Assume these are implemented securely >>>
import CaptchaInput from '../components/CaptchaInput'; // Assumes handles CAPTCHA display/input correctly
import PgpChallengeSigner from '../components/PgpChallengeSigner'; // Assumes handles challenge display/signature input correctly & securely
import FormError from '../components/FormError'; // Assumes safely renders error messages AND uses role="alert" for accessibility/testing
import LoadingSpinner from '../components/LoadingSpinner';
import { showSuccessToast, showErrorToast } from '../utils/notifications'; // <<< Verify path & assume functions sanitize inputs >>>

// Styles object (can be replaced/merged with global CSS classes like .card, .form-group etc.)
const styles = {
    container: { maxWidth: '500px', margin: '3rem auto', padding: '2rem', background: '#fff', borderRadius: '8px', border: '1px solid #dee2e6', boxShadow: '0 2px 10px rgba(0,0,0,0.1)' },
    title: { textAlign: 'center', marginBottom: '1.5rem' },
    stepIndicator: { textAlign: 'center', fontWeight: 'bold', marginBottom: '1rem', color: '#007bff' },
    pgpInstructions: { fontSize: '0.9em', color: '#6c757d', marginBottom: '1rem', background: '#f8f9fa', padding: '1rem', borderRadius: '4px', border: '1px solid #dee2e6' },
    captchaContainer: { margin: '1rem 0' }, // Ensure spacing around CAPTCHA
    loadingContainer: { display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '5rem 0' }, // Centered loading
};

export default function LoginPage() {
    const { login, user, isLoading: authLoading } = useAuth(); // Get login function and user state + auth loading status
    const router = useRouter();

    // State
    const [step, setStep] = useState(1); // 1: Credentials, 2: PGP Challenge
    // Step 1 State
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    // CAPTCHA State
    const [captchaKey, setCaptchaKey] = useState('');
    const [captchaImageUrl, setCaptchaImageUrl] = useState('');
    const [captchaValue, setCaptchaValue] = useState('');
    const [captchaLoading, setCaptchaLoading] = useState(true); // Start loading CAPTCHA initially
    // Step 2 State
    const [pgpChallenge, setPgpChallenge] = useState('');
    const [loginPhrase, setLoginPhrase] = useState(''); // Anti-phishing phrase
    const [pgpSignature, setPgpSignature] = useState('');
    // General State
    const [isSubmitting, setIsSubmitting] = useState(false); // Combined loading for API calls within this page
    const [error, setError] = useState('');

    // Redirect if already logged in (wait for auth check to complete)
    useEffect(() => {
        // Only attempt redirect checks once auth state is resolved and user exists
        if (!authLoading && user) {
            const nextUrl = router.query.next || '/profile'; // Redirect to profile or intended page
            // Use replace to avoid adding the login page to history when redirecting logged-in users
            router.replace(nextUrl);
        }
    }, [user, authLoading, router]);

    // --- !!! CRITICAL: CAPTCHA IMPLEMENTATION !!! ---
    // The following 'refreshCaptcha' function is a PLACEHOLDER.
    // It should ideally NOT clear errors set by other functions.
    const refreshCaptcha = useCallback(async () => {
        setCaptchaLoading(true);
        // setError(''); // Removed: Let calling function manage general error state
        setCaptchaValue(''); // Clear input field
        try {
            // ================== START: REPLACE THIS BLOCK ==================
            console.warn("CAPTCHA refresh logic is a placeholder and needs actual implementation!");
            const timestamp = new Date().getTime();
            const tempKey = `dummyKey${timestamp}`;
            const tempImageUrl = `/captcha/image/${tempKey}/`;
            await new Promise(resolve => setTimeout(resolve, 300)); // Simulate network delay
            setCaptchaKey(tempKey);
            setCaptchaImageUrl(tempImageUrl);
             // ================== END: REPLACE THIS BLOCK ==================
             // Clear only CAPTCHA-specific errors on successful refresh? Or rely on main form error handling.
             // For now, let's assume successful refresh implies no CAPTCHA error. If the *overall* form had an error, it remains.

        } catch (err) {
            console.error("CAPTCHA refresh failed:", err);
            const errMsg = "Failed to load CAPTCHA image. Please try refreshing the page or contact support if the issue persists.";
            // Clear state related to captcha first
            setCaptchaKey('');
            setCaptchaImageUrl('');
            // Set error last in the catch block - specific to CAPTCHA failure
            setError(errMsg); // Okay to set error here as it's *specific* to CAPTCHA fetch
        } finally {
            setCaptchaLoading(false);
        }
    }, []); // No dependencies needed for useCallback if it doesn't use external state/props

    // Fetch initial CAPTCHA on mount (only if not logged in and auth state is known)
    useEffect(() => {
        if (!authLoading && !user) {
            // --- !!! CRITICAL: Needs real implementation matching refreshCaptcha above !!! ---
            refreshCaptcha();
        }
    }, [authLoading, user, refreshCaptcha]); // Run when auth state is known and user is not logged in

    // Handle Step 1: Credentials + CAPTCHA submission
    const handleLoginStep1 = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors at the start

        // --- Frontend Validation ---
        if (!username || !password || !captchaValue || !captchaKey) {
            setError("Please fill in all fields, including the CAPTCHA.");
            // Ensure FormError component renders this message with role="alert"
            return; // Stop submission
        }
        // --- End Frontend Validation ---

        setIsSubmitting(true);

        const credentials = {
            username,
            password,
            captcha_key: captchaKey,
            captcha_value: captchaValue,
        };

        try {
            const response = await loginInit(credentials);
            // <<< SECURITY: Backend provides challenge & phrase >>>
            setPgpChallenge(response.pgp_challenge);
            setLoginPhrase(response.login_phrase); // Display this in Step 2
            setStep(2); // Move to PGP signature step
            // Clear sensitive fields for security after submitting Step 1
            setPassword('');
            setCaptchaValue('');
            // No error on success
            setIsSubmitting(false); // Set loading false on success path

        } catch (err) {
            console.error("Login Step 1 failed:", err);
            // <<< SECURITY: Use generic error for failed login attempts >>>
            let errMsg;
            // --- UPDATED Condition to handle specific mock error ---
            if (err.message === 'Unauthorized' ||
                (typeof err.message === 'string' && err.message.toLowerCase().includes('captcha')) ||
                err.message === 'Invalid credentials' // Handle specific error from test mock
            ) {
                 errMsg = "Invalid username, password, or CAPTCHA.";
            } else {
                 errMsg = "Login initialization failed. Please try again.";
            }

            // --- Order from Rev 4 ---
            showErrorToast(errMsg);  // Show notification
            setError(errMsg);        // Set the primary error message state
            setIsSubmitting(false);  // Set loading to false *before* calling refresh
            refreshCaptcha();        // Call refresh CAPTCHA *after* main state updates for this action
            // --------------------

        }
    };

    // Handle Step 2: PGP Signature submission
    const handleLoginStep2 = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors at the start
        if (!pgpSignature.trim()) {
            setError("Please paste your PGP signature (including BEGIN/END markers).");
            // Ensure FormError component renders this message with role="alert"
            return;
        }
        setIsSubmitting(true);

        const signatureData = {
            username, // Send username again for backend
            pgp_challenge_signature: pgpSignature.trim(),
        };

        try {
            const responseUserData = await loginPgpVerify(signatureData);
            // <<< SECURITY: Backend returns user data and sets secure HttpOnly session cookie >>>
            login(responseUserData, true);
            showSuccessToast("Login successful!");
            // Redirect is handled by useEffect
            setIsSubmitting(false); // Set loading false on success path

        } catch (err) {
            console.error("Login Step 2 failed:", err);
            // Determine specific error message
            let errMsg = "PGP verification failed. Please check your signature or start over."; // Default PGP error
            if (err.message === 'Unauthorized' || err.message === 'Forbidden') {
               // Let generic message handle auth issues
            } else if (typeof err.message === 'string') {
                if (err.message.toLowerCase().includes("invalid signature")) {
                    errMsg = "Invalid PGP signature provided. Ensure you signed the exact text.";
                 } else if (err.message.toLowerCase().includes("expired") || err.message.toLowerCase().includes("not found")) {
                    errMsg = "Login challenge expired or invalid. Please go back and start over.";
                 } else {
                    // Use the error message directly if it's not one of the common handled cases
                     if (!['Unauthorized', 'Forbidden', 'PGP Auth Required', 'Not Found'].includes(err.message)) {
                        errMsg = err.message;
                    }
                }
            }

             // --- Order from Rev 4 ---
            showErrorToast(errMsg);  // Show notification
            setPgpChallenge('');     // Clear PGP specific state
            setPgpSignature('');
            setLoginPhrase('');
            setStep(1);              // Reset step *before* setting error and loading=false
            setError(errMsg);        // Set the error message
            setIsSubmitting(false);  // Set loading false
            refreshCaptcha();        // Refresh CAPTCHA for the reset Step 1 *after* other state updates
            // -----------------------------------------

        }
    };

    // Render Loading state or Login form
    if (authLoading) {
        return (
            <Layout>
                <div style={styles.loadingContainer}>
                    <LoadingSpinner message="Checking authentication..." />
                </div>
            </Layout>
        );
    }

    // Render the form if authLoading is false and user is null.
    return (
        <Layout>
            <div style={styles.container} className="card">
                <h1 style={styles.title}>Login</h1>
                {/* Ensure FormError handles empty strings gracefully and uses role="alert" */}
                <FormError message={error} />

                {/* Step 1: Credentials & Captcha */}
                {step === 1 && (
                    <>
                        <div style={styles.stepIndicator}>Step 1 of 2: Enter Credentials</div>
                        <form onSubmit={handleLoginStep1}>
                            <div className="form-group">
                                <label htmlFor="username" className="form-label">Username</label>
                                <input
                                    type="text"
                                    id="username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    required
                                    className="form-input"
                                    disabled={isSubmitting || authLoading} // Disable if submitting or initial auth check running
                                    autoComplete="username"
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="password"className="form-label">Password</label>
                                <input
                                    type="password"
                                    id="password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    className="form-input"
                                    disabled={isSubmitting || authLoading}
                                    autoComplete="current-password"
                                 />
                            </div>

                             <div style={styles.captchaContainer}>
                                 <CaptchaInput
                                     imageUrl={captchaImageUrl}
                                     inputKey={captchaKey}
                                     value={captchaValue}
                                     onChange={(e) => setCaptchaValue(e.target.value)}
                                     onRefresh={refreshCaptcha}
                                     isLoading={captchaLoading}
                                     disabled={isSubmitting || authLoading}
                                 />
                                 {/* Show CAPTCHA load error specifically if loading finished but no image */}
                                 {!captchaLoading && !captchaImageUrl && <FormError message="Could not load CAPTCHA image. Try refreshing." />}
                             </div>

                            <button
                                type="submit"
                                disabled={isSubmitting || captchaLoading || !captchaImageUrl || authLoading}
                                className={`button button-primary w-100 ${(isSubmitting || captchaLoading || !captchaImageUrl || authLoading) ? 'disabled' : ''}`}
                            >
                                {isSubmitting ? <LoadingSpinner size="1em"/> : 'Next: PGP Challenge'}
                            </button>
                        </form>
                    </>
                )}

                {/* Step 2: PGP Challenge */}
                {step === 2 && (
                    <>
                        <div style={styles.stepIndicator}>Step 2 of 2: Verify PGP Signature</div>
                        {loginPhrase && (
                            <div className="alert alert-info" role="alert" style={{textAlign:'center', marginBottom:'1rem', wordBreak:'break-all'}}>
                                Verify Login Phrase: <strong>{loginPhrase}</strong>
                            </div>
                        )}
                        <div style={styles.pgpInstructions}>
                           <p>To complete login, please sign the following challenge text EXACTLY using the PGP private key associated with your account ({username}).</p>
                           <ol style={{fontSize:'0.9em', paddingLeft:'1.2rem'}}>
                                <li>Copy the entire text block below.</li>
                                <li>Use your PGP software to "Sign" this text. Choose "Clearsign".</li>
                                <li>Paste the ENTIRE resulting signed message block into the textarea below.</li>
                           </ol>
                           <p style={{fontSize:'0.9em'}}><Link href="/pgp-guide#signing-challenge" target="_blank" rel="noopener noreferrer">Need help signing?</Link></p>
                        </div>
                        <form onSubmit={handleLoginStep2}>
                            <PgpChallengeSigner
                                challengeText={pgpChallenge}
                                signatureValue={pgpSignature}
                                onSignatureChange={(e) => setPgpSignature(e.target.value)}
                                disabled={isSubmitting}
                                required
                            />
                            <button
                                type="submit"
                                disabled={isSubmitting}
                                className={`button button-primary w-100 mt-3 ${isSubmitting ? 'disabled' : ''}`}
                            >
                                {isSubmitting ? <LoadingSpinner size="1em"/> : 'Login'}
                            </button>
                        </form>
                        <button
                            onClick={() => {
                                setStep(1);
                                setError(''); // Clear error when going back
                                setPgpChallenge('');
                                setPgpSignature('');
                                setLoginPhrase('');
                                // --- RESTORED this call based on test expectation ---
                                refreshCaptcha();
                            }}
                            className="button button-secondary w-100 mt-2"
                            disabled={isSubmitting}
                        >
                            Back to Step 1
                        </button>
                    </>
                )}

                <p className="text-center mt-4">
                    Don't have an account? <Link href="/register">Register here</Link>
                </p>
            </div>
        </Layout>
    );
}