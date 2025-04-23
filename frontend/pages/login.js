/*
 * Revision History:
 * 2025-04-23 (Gemini): Rev 9 - Remove debug console.log statements for CAPTCHA refresh.
 * 2025-04-23 (Gemini): Rev 8 - Adjust Step 1 validation logic and Step 2 error handling order.
 * - PROBLEM 1: Test 'shows validation error...' failed to find alert content.
 * - FIX 1: Modified `handleLoginStep1` JS validation. Instead of setting error and returning immediately, set a flag, perform the check, and set the error *after* the check if the flag is set. Reverted FormError mock to conditional rendering.
 * - PROBLEM 2: Test 'shows error, resets to Step 1...' failed to find the specific error text.
 * - CAUSE 2: State updates for step change and captcha refresh happened after setting the error, likely clearing it before assertion.
 * - FIX 2: Reordered state updates in `handleLoginStep2` catch block. Now sets Step, clears PGP state, *then* sets the error message, and finally calls refreshCaptcha. Modified test to wait for Step 1 UI *then* find error text.
 * 2025-04-23 (Gemini): Rev 7 - Remove duplicate CAPTCHA error message rendering.
 * - PROBLEM: Failing test 'shows error if CAPTCHA refresh fails' reported multiple elements with text "/Could not load CAPTCHA image/i".
 * - CAUSE: An explicit <FormError> for CAPTCHA loading failure was rendered near the CaptchaInput component (line ~333), in addition to the main <FormError> at the top (line ~291) displaying the same error message set via the `error` state in the `refreshCaptcha` catch block.
 * - FIX: Removed the specific <FormError> check `{!captchaLoading && !captchaImageUrl && <FormError ... />}` within the CaptchaInput container. The main error display mechanism is sufficient.
 * ... (previous history omitted for brevity) ...
 */
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

// Helper: Construct absolute URL for API calls (adapt base URL as needed)
// Reads from environment variable or defaults to a common local dev setup
const getApiUrl = (path) => {
    const apiUrlBase = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    // Ensure no double slashes
    return `${apiUrlBase.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
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

    // --- Updated CAPTCHA Refresh Logic ---
    const refreshCaptcha = useCallback(async () => {
        setCaptchaLoading(true);
        // setError(''); // Keep existing non-captcha errors visible if any
        setCaptchaValue(''); // Clear input field
        setCaptchaKey(''); // Clear old key/image prevent stale display on error
        setCaptchaImageUrl('');

        // Add timestamp to prevent potential browser caching issues with the GET request
        const url = getApiUrl(`/captcha/refresh/?_=${new Date().getTime()}`);
        // console.log(`Workspaceing CAPTCHA from: ${url}`); // DEBUG - REMOVED in Rev 9

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    // Add other headers like CSRF token if needed by your backend
                },
            });

            if (!response.ok) {
                // Attempt to read error details if possible, otherwise use status text
                let errorDetail = response.statusText;
                try {
                    const errorJson = await response.json();
                    errorDetail = errorJson.detail || JSON.stringify(errorJson);
                } catch (parseError) {
                    // Ignore if response body is not JSON
                }
                throw new Error(`CAPTCHA API Error (${response.status}): ${errorDetail}`);
            }

            const data = await response.json();

            if (!data.key || !data.image_url) {
                throw new Error("Invalid CAPTCHA data received from API.");
            }

            // console.log("CAPTCHA Refreshed. Key:", data.key, "Image URL:", data.image_url); // DEBUG - REMOVED in Rev 9
            setCaptchaKey(data.key);
            // Construct full image URL if needed (assuming API returns relative path)
            // Example: If API returns '/captcha/image/xyz/', make it absolute
            const fullImageUrl = data.image_url.startsWith('/') ? getApiUrl(data.image_url) : data.image_url;
            setCaptchaImageUrl(fullImageUrl);

        } catch (err) {
            console.error("CAPTCHA refresh failed:", err); // Keep actual error logging
            const errMsg = err instanceof Error ? err.message : "Failed to load CAPTCHA image. Please try refreshing the page or contact support if the issue persists.";
            setError(errMsg); // Display the specific error
            showErrorToast("Failed to refresh CAPTCHA. Please try again."); // User-friendly toast
        } finally {
            setCaptchaLoading(false);
        }
    }, []); // No dependencies needed as getApiUrl reads from process.env

    // Fetch initial CAPTCHA on mount (only if not logged in and auth state is known)
    useEffect(() => {
        if (!authLoading && !user) {
            refreshCaptcha(); // Call the updated function
        }
    }, [authLoading, user, refreshCaptcha]); // Run when auth state is known and user is not logged in

    // Handle Step 1: Credentials + CAPTCHA submission
    const handleLoginStep1 = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors at the start

        // --- Modified Frontend Validation (Rev 8) ---
        let validationError = '';
        if (!username || !password || !captchaValue || !captchaKey) {
            validationError = "Please fill in all fields, including the CAPTCHA.";
        }

        if (validationError) {
            setError(validationError);
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
            console.error("Login Step 1 failed:", err); // Keep actual error logging
            // <<< SECURITY: Use generic error for failed login attempts >>>
            let errMsg;
             // Check if it's an ApiError with data or just a generic error message
             const detailError = err?.data?.detail || err?.data; // Prioritize detail if present
             const message = detailError ? JSON.stringify(detailError) : (err instanceof Error ? err.message : String(err));

            if (message.toLowerCase().includes('captcha') ||
                message.includes('Invalid username') || // Cover backend variations
                message.includes('Invalid password') ||
                message.includes('Invalid credentials'))
            {
                errMsg = "Invalid username, password, or CAPTCHA.";
            } else {
                errMsg = "Login initialization failed. Please try again.";
            }

            // --- Order from Rev 4 ---
            showErrorToast(errMsg);   // Show notification
            setError(errMsg);         // Set the primary error message state
            setIsSubmitting(false);   // Set loading to false *before* calling refresh
            refreshCaptcha();         // Call refresh CAPTCHA *after* main state updates for this action
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
            console.error("Login Step 2 failed:", err); // Keep actual error logging
            // Determine specific error message
            let errMsg = "PGP verification failed. Please check your signature or start over."; // Default PGP error

             // Check if it's an ApiError with data or just a generic error message
             const detailError = err?.data?.detail || err?.data; // Prioritize detail if present
             const message = detailError ? JSON.stringify(detailError) : (err instanceof Error ? err.message : String(err));

            if (message.toLowerCase().includes("invalid signature")) {
                 errMsg = "Invalid PGP signature provided. Ensure you signed the exact text.";
             } else if (message.toLowerCase().includes("expired") || message.toLowerCase().includes("not found") || message.includes('Unauthorized') || message.includes('Forbidden')) {
                 errMsg = "Login challenge expired or invalid. Please go back and start over.";
             } else {
                 // Use the error message directly if it's not one of the common handled cases
                 if (!['PGP Auth Required'].includes(message)) { // Avoid overly generic messages if we have specifics
                     errMsg = message;
                 }
             }

            // --- Reordered State Updates (Rev 8) ---
            showErrorToast(errMsg);   // Show notification first
            setPgpChallenge('');      // Clear PGP specific state
            setPgpSignature('');
            setLoginPhrase('');
            setStep(1);               // Reset step
            setIsSubmitting(false);   // Set loading false
            setError(errMsg);         // Set the error message *after* step change
            refreshCaptcha();         // Refresh CAPTCHA last
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
                                    inputKey={captchaKey} // Use captchaKey as the key prop if needed by CaptchaInput for re-renders
                                    value={captchaValue}
                                    onChange={(e) => setCaptchaValue(e.target.value)}
                                    onRefresh={refreshCaptcha}
                                    isLoading={captchaLoading}
                                    disabled={isSubmitting || authLoading}
                                />
                                {/* Specific CAPTCHA error removed in Rev 7 */}
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