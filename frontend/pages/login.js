// frontend/pages/login.js
// --- REVISION HISTORY ---
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
import { useAuth } from '../../context/AuthContext'; // <<< Verify path is correct
import { loginInit, loginPgpVerify } from '../../utils/api'; // <<< Verify path is correct
import Layout from '../../components/Layout'; // <<< Verify path is correct & implements necessary security (e.g., headers if needed)
// <<< Import necessary components - Assume these are implemented securely >>>
import CaptchaInput from '../../components/CaptchaInput'; // Assumes handles CAPTCHA display/input correctly
import PgpChallengeSigner from '../../components/PgpChallengeSigner'; // Assumes handles challenge display/signature input correctly & securely
import FormError from '../../components/FormError'; // Assumes safely renders error messages
import LoadingSpinner from '../../components/LoadingSpinner';
import { showSuccessToast, showErrorToast } from '../../utils/notifications'; // <<< Verify path & assume functions sanitize inputs >>>

// Styles object (can be replaced/merged with global CSS classes like .card, .form-group etc.)
const styles = {
    container: { maxWidth: '500px', margin: '3rem auto', padding: '2rem', background: '#fff', borderRadius: '8px', border: '1px solid #dee2e6', boxShadow: '0 2px 10px rgba(0,0,0,0.1)' },
    title: { textAlign: 'center', marginBottom: '1.5rem' },
    stepIndicator: { textAlign: 'center', fontWeight: 'bold', marginBottom: '1rem', color: '#007bff' },
    pgpInstructions: { fontSize: '0.9em', color: '#6c757d', marginBottom: '1rem', background: '#f8f9fa', padding: '1rem', borderRadius: '4px', border: '1px solid #dee2e6' },
    captchaContainer: { margin: '1rem 0' }, // Ensure spacing around CAPTCHA
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
        if (!authLoading && user) {
            const nextUrl = router.query.next || '/profile'; // Redirect to profile or intended page
            router.push(nextUrl);
        }
    }, [user, authLoading, router]);

    // --- !!! CRITICAL: CAPTCHA IMPLEMENTATION !!! ---
    // The following 'refreshCaptcha' function is a PLACEHOLDER.
    // You MUST replace the fetch call and logic with the actual method required
    // by your backend CAPTCHA implementation (e.g., django-simple-captcha).
    // This typically involves fetching a new CAPTCHA key and image URL from a specific backend endpoint.
    const refreshCaptcha = useCallback(async () => {
        setCaptchaLoading(true);
        setError(''); // Clear errors on refresh
        setCaptchaValue(''); // Clear input field
        try {
            // ================== START: REPLACE THIS BLOCK ==================
            // Example: If using django-simple-captcha, you might need an endpoint that returns JSON:
            // const response = await fetch('/api/captcha/refresh/'); // Replace with your actual endpoint
            // if (!response.ok) throw new Error('Failed to fetch new CAPTCHA data');
            // const data = await response.json(); // Expects { key: "...", image_url: "..." }
            // setCaptchaKey(data.key);
            // setCaptchaImageUrl(data.image_url);

            // --- TEMPORARY PLACEHOLDER SIMULATION ---
            // This will NOT work with a real CAPTCHA backend. Remove this simulation.
            console.warn("CAPTCHA refresh logic is a placeholder and needs actual implementation!");
            const timestamp = new Date().getTime();
            const tempKey = `dummyKey${timestamp}`; // Fake key generation
            // Construct a URL assuming django-simple-captcha's default URL structure. THIS MAY BE WRONG.
            const tempImageUrl = `/captcha/image/${tempKey}/`; // Replace with actual URL from backend
            await new Promise(resolve => setTimeout(resolve, 300)); // Simulate network delay
            setCaptchaKey(tempKey);
            setCaptchaImageUrl(tempImageUrl); // Make sure your CaptchaInput component can handle this URL
             // ================== END: REPLACE THIS BLOCK ==================

        } catch (err) {
            console.error("CAPTCHA refresh failed:", err);
            setError("Failed to load CAPTCHA image. Please try refreshing the page or contact support if the issue persists.");
            setCaptchaKey(''); setCaptchaImageUrl(''); // Clear on error
        } finally {
            setCaptchaLoading(false);
        }
    }, []); // No dependencies needed for useCallback if it doesn't use external state/props

    // Fetch initial CAPTCHA on mount (only if not logged in)
    useEffect(() => {
        if (!authLoading && !user) {
             // --- !!! CRITICAL: Needs real implementation matching refreshCaptcha above !!! ---
            refreshCaptcha();
        }
    }, [authLoading, user, refreshCaptcha]); // Run when auth state is known and user is not logged in

    // Handle Step 1: Credentials + CAPTCHA submission
    const handleLoginStep1 = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors
        if (!username || !password || !captchaValue || !captchaKey) {
            setError("Please fill in all fields, including the CAPTCHA.");
            return;
        }
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
        } catch (err) {
            console.error("Login Step 1 failed:", err);
            // <<< SECURITY: Use generic error for failed login attempts to prevent username enumeration >>>
            // Status codes likely indicate auth failure (handled by api.js returning specific errors or messages)
            let errMsg;
            if (err.message === 'Unauthorized' || (typeof err.message === 'string' && err.message.toLowerCase().includes('captcha'))) {
                 errMsg = "Invalid username, password, or CAPTCHA."; // Generic message for auth/captcha failures
            } else {
                // Handle other potential errors (network, server issues)
                errMsg = "Login initialization failed. Please try again."; // More generic than leaking err.message
            }
            setError(errMsg);
            showErrorToast(errMsg);
            // Refresh CAPTCHA on failure for retry
            refreshCaptcha();
        } finally {
            setIsSubmitting(false);
        }
    };

    // Handle Step 2: PGP Signature submission
    const handleLoginStep2 = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors
        if (!pgpSignature.trim()) {
            setError("Please paste your PGP signature (including BEGIN/END markers).");
            return;
        }
        setIsSubmitting(true);

        const signatureData = {
            username, // Send username again for backend to associate challenge/signature
            pgp_challenge_signature: pgpSignature.trim(),
        };

        try {
            const responseUserData = await loginPgpVerify(signatureData);
            // <<< SECURITY: Backend returns user data and sets secure HttpOnly session cookie >>>
            // Call AuthContext's login function to update global state
            login(responseUserData, true); // Pass the user object, explicitly state PGP verified
            showSuccessToast("Login successful!");
            // Redirect is handled by useEffect watching the 'user' state in AuthContext consumer (this page)
        } catch (err) {
            console.error("Login Step 2 failed:", err);
            // Provide more specific feedback for PGP errors if possible
            // NOTE: Relies on backend consistency or specific error codes. String matching is fragile.
            let errMsg = "PGP verification failed. Please check your signature or start over."; // Default PGP error
            if (err.message === 'Unauthorized' || err.message === 'Forbidden') {
                // Let generic message handle auth issues from api.js
            } else if (typeof err.message === 'string') {
                // Recommend backend sends distinct error codes/messages rather than relying on string parsing.
                if (err.message.toLowerCase().includes("invalid signature")) {
                     errMsg = "Invalid PGP signature provided. Ensure you signed the exact text.";
                 } else if (err.message.toLowerCase().includes("expired") || err.message.toLowerCase().includes("not found")) {
                     errMsg = "Login challenge expired or invalid. Please go back and start over.";
                 } else {
                    // Use message from error if it's not a generic auth one, otherwise keep default
                    if (!['Unauthorized', 'Forbidden', 'PGP Auth Required', 'Not Found'].includes(err.message)) {
                        errMsg = err.message; // Use specific message if available and not generic auth type
                    }
                 }
            }
            setError(errMsg);
            showErrorToast(errMsg);
            // <<< UX/Security: Force user back to step 1 on PGP verification failure >>>
            setStep(1);
            setPgpChallenge(''); setPgpSignature(''); setLoginPhrase('');
            // Refresh CAPTCHA for Step 1 retry
            refreshCaptcha();
        } finally {
            setIsSubmitting(false);
        }
    };

    // Render Loading state or Login form
    // Avoid rendering form if auth state is still loading or user is already logged in (handled by useEffect redirect)
     if (authLoading || (!authLoading && user)) {
         return <Layout><div className="text-center p-5"><LoadingSpinner message="Loading..." /></div></Layout>;
     }

    return (
        <Layout>
            <div style={styles.container} className="card"> {/* Use global class if available */}
                <h1 style={styles.title}>Login</h1>
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
                                    className="form-input" // Use global class
                                    disabled={isSubmitting}
                                    autoComplete="username" // Helps password managers
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
                                    className="form-input" // Use global class
                                    disabled={isSubmitting}
                                    autoComplete="current-password" // Helps password managers
                                 />
                            </div>

                            {/* CAPTCHA Section */}
                             <div style={styles.captchaContainer}>
                                 {/* Assume CaptchaInput handles display logic based on props */}
                                 <CaptchaInput
                                     imageUrl={captchaImageUrl}
                                     inputKey={captchaKey} // Pass the hidden key (needed by django-simple-captcha)
                                     value={captchaValue}
                                     onChange={(e) => setCaptchaValue(e.target.value)}
                                     onRefresh={refreshCaptcha} // Button inside CaptchaInput triggers this
                                     isLoading={captchaLoading} // Show loading indicator on CAPTCHA component
                                     disabled={isSubmitting} // Disable input during main form submission
                                     // Required can be handled internally by CaptchaInput or here
                                 />
                                 {/* Show error here only if loading is finished but URL is still missing */}
                                 {!captchaLoading && !captchaImageUrl && <FormError message="Could not load CAPTCHA." />}
                             </div>

                            <button
                                type="submit"
                                disabled={isSubmitting || captchaLoading || !captchaImageUrl} // Disable if submitting or CAPTCHA not ready
                                className={`button button-primary w-100 ${(isSubmitting || captchaLoading || !captchaImageUrl) ? 'disabled' : ''}`} // Use global classes
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
                        {/* <<< ADDED: Display Anti-Phishing Login Phrase >>> */}
                        {loginPhrase && (
                            <div className="alert alert-info" role="alert" style={{textAlign:'center', marginBottom:'1rem', wordBreak:'break-all'}}>
                                Verify Login Phrase: <strong>{loginPhrase}</strong> {/* Ensure loginPhrase is properly escaped if it could contain HTML/JS - Assume plain text */}
                            </div>
                        )}
                        {/* <<< ADDED: Clearer Instructions >>> */}
                        <div style={styles.pgpInstructions}>
                            <p>To complete login, please sign the following challenge text EXACTLY using the PGP private key associated with your account ({username}).</p>
                            <ol style={{fontSize:'0.9em', paddingLeft:'1.2rem'}}>
                                <li>Copy the entire text block below (including the `-----BEGIN PGP SIGNED MESSAGE-----` header if present, or just the challenge text if not).</li>
                                <li>Use your PGP software (e.g., Kleopatra, GPG Suite, command line) to "Sign" this text using your private key. Choose "Clearsign" if available, otherwise a standard detached signature might work depending on backend verification logic.</li>
                                <li>Paste the ENTIRE resulting signed message block (including BEGIN/END markers and the original text for clearsign) OR the detached signature block into the textarea below.</li>
                            </ol>
                            <p style={{fontSize:'0.9em'}}><Link href="/pgp-guide#signing-challenge" target="_blank" rel="noopener noreferrer">Need help signing?</Link></p> {/* Added rel attribute */}
                        </div>
                        <form onSubmit={handleLoginStep2}>
                            {/* Component to display challenge and handle signature input */}
                            {/* Assume PgpChallengeSigner handles display/input securely */}
                            <PgpChallengeSigner
                                challengeText={pgpChallenge} // Pass challenge text from backend
                                signatureValue={pgpSignature} // Controlled component value
                                onSignatureChange={(e) => setPgpSignature(e.target.value)} // Update state
                                disabled={isSubmitting}
                                required // Mark as required for form validation if PgpChallengeSigner doesn't handle it
                            />
                            <button
                                type="submit"
                                disabled={isSubmitting}
                                className={`button button-primary w-100 mt-3 ${isSubmitting ? 'disabled' : ''}`} // Use global classes
                            >
                                {isSubmitting ? <LoadingSpinner size="1em"/> : 'Login'}
                            </button>
                        </form>
                        <button
                            onClick={() => {
                                setStep(1);
                                setError('');
                                // Clear PGP state when going back
                                setPgpChallenge('');
                                setPgpSignature('');
                                setLoginPhrase('');
                                // Refresh CAPTCHA for Step 1
                                refreshCaptcha();
                             }}
                            className="button button-secondary w-100 mt-2" // Use global classes
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