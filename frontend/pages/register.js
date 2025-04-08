// frontend/pages/register.js
// <<< REVISED FOR ENTERPRISE GRADE: Enhanced Validation, Instructions, Error Handling, Success Feedback >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
import { registerUser } from '../../utils/api'; // <<< Ensure path is correct >>>
import Layout from '../../components/Layout'; // <<< Ensure path is correct >>>
// <<< ADDED: Import necessary components and constants >>>
import CaptchaInput from '../../components/CaptchaInput';
import FormError from '../../components/FormError';
import LoadingSpinner from '../../components/LoadingSpinner';
import { MIN_PASSWORD_LENGTH } from '../../utils/constants'; // <<< Ensure path is correct >>>
import { showSuccessToast, showErrorToast } from '../../utils/notifications'; // <<< Ensure path is correct >>>

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '600px', margin: '3rem auto', padding: '2rem', background: '#fff', borderRadius: '8px', border: '1px solid #dee2e6', boxShadow: '0 2px 10px rgba(0,0,0,0.1)' }, // Use global .card?
    title: { textAlign: 'center', marginBottom: '1.5rem' },
    successMessage: { textAlign: 'center', color: '#155724', background: '#d4edda', border: '1px solid #c3e6cb', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' },
    // Use global form/button classes (.form-group, .form-label, .form-input, .form-textarea, .button, .button-primary, .disabled etc.)
    captchaContainer: { margin: '1rem 0' },
    pgpLabelContainer: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' },
    pgpGuideLink: { fontSize: '0.8em' },
};

export default function RegisterPage() {
    const { user } = useAuth();
    const router = useRouter();

    // Form State
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [passwordConfirm, setPasswordConfirm] = useState('');
    const [pgpKey, setPgpKey] = useState('');
    // CAPTCHA State
    const [captchaKey, setCaptchaKey] = useState('');
    const [captchaImageUrl, setCaptchaImageUrl] = useState('');
    const [captchaValue, setCaptchaValue] = useState('');
    const [captchaLoading, setCaptchaLoading] = useState(true);
    // General State
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(''); // Combined error state for form/API errors
    const [isSuccess, setIsSuccess] = useState(false); // <<< ADDED: Success state >>>

    // Redirect if already logged in
    useEffect(() => {
        if (user) {
            router.push('/profile'); // Redirect logged-in users away from register page
        }
    }, [user, router]);

    // Function to fetch/refresh CAPTCHA (same as login page)
    const refreshCaptcha = useCallback(async () => {
        setCaptchaLoading(true); setError('');
        try {
            // <<< BEST PRACTICE: Adjust URL based on actual backend CAPTCHA setup >>>
            const timestamp = new Date().getTime();
            const response = await fetch('/captcha/refresh/?'+timestamp);
            if (!response.ok) throw new Error('Failed to fetch new CAPTCHA');
            const data = await response.json();
            setCaptchaKey(data.key);
            setCaptchaImageUrl(data.image_url);
            setCaptchaValue('');
        } catch (err) {
            console.error("CAPTCHA refresh failed:", err);
            setError("Failed to load CAPTCHA image. Please try refreshing the page.");
            setCaptchaKey(''); setCaptchaImageUrl('');
        } finally { setCaptchaLoading(false); }
    }, []);

    // Fetch initial CAPTCHA on mount
    useEffect(() => {
        refreshCaptcha();
    }, [refreshCaptcha]);

    // <<< ADDED: Client-side validation function >>>
    const validateForm = () => {
        setError(''); // Clear previous client-side errors
        if (!username.trim() || !password || !passwordConfirm || !pgpKey.trim() || !captchaValue.trim()) {
             setError("All fields, including CAPTCHA, are required."); return false;
        }
        if (password !== passwordConfirm) { setError("Passwords do not match."); return false; }
        if (password.length < MIN_PASSWORD_LENGTH) { setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters long.`); return false; }
        const pgpTrimmed = pgpKey.trim();
        if (!pgpTrimmed.startsWith('-----BEGIN PGP PUBLIC KEY BLOCK-----') || !pgpTrimmed.includes('-----END PGP PUBLIC KEY BLOCK-----')) {
            setError('Invalid PGP Key format. Ensure the full block including BEGIN/END markers was pasted correctly.'); return false;
        }
        return true; // Validation passed
    };

    // Handle Registration Submission
    const handleRegister = async (e) => {
        e.preventDefault();
        setIsSuccess(false); // Reset success state on new attempt

        // Perform client-side validation first
        if (!validateForm()) {
             return; // Stop if client validation fails
        }

        setIsLoading(true);

        const userData = {
            username: username.trim(),
            password: password,
            password_confirm: passwordConfirm, // Send confirmation to backend
            pgp_public_key: pgpKey.trim(),
            captcha_key: captchaKey,
            captcha_value: captchaValue,
        };

        try {
            // <<< SECURITY: Backend MUST perform its own robust validation >>>
            // (Username unique, password complexity, PGP key import/validity, CAPTCHA)
            await registerUser(userData);
            setIsSuccess(true); // Set success state
            showSuccessToast("Registration successful!");
            // Clear form fields on success? Optional, keeps username for easy login maybe.
            // setUsername('');
            setPassword(''); setPasswordConfirm(''); setPgpKey(''); setCaptchaValue('');
            // Maybe redirect to login or show success message on page.
            // router.push('/login');
        } catch (err) {
            console.error("Registration failed:", err);
            let errorMsg = err.message || "An unexpected error occurred during registration.";
            // <<< CHANGE: Try to parse DRF validation errors for specific feedback >>>
             if (err.status === 400 && err.data) {
                 const fieldErrors = Object.entries(err.data)
                    .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(' ') : messages}`)
                    .join('; ');
                 if (fieldErrors) {
                      errorMsg = `Registration Error: ${fieldErrors}`;
                 } else if (err.data.detail) { // Fallback to detail message
                     errorMsg = err.data.detail;
                 }
             } else if (err.status === 401 || err.status === 403) {
                 errorMsg = "Registration failed due to an authorization issue (maybe CAPTCHA?).";
             }
            setError(errorMsg);
            showErrorToast(`Registration failed: ${errorMsg.substring(0, 100)}${errorMsg.length > 100 ? '...' : ''}`); // Show potentially truncated toast
            // Refresh CAPTCHA on failure
            refreshCaptcha();
        } finally { setIsLoading(false); }
    };

    return (
        <Layout>
            <div style={styles.container} className="card"> {/* Use global class */}
                <h1 style={styles.title}>Register New Account</h1>

                {/* <<< ADDED: Success Message Block >>> */}
                 {isSuccess ? (
                    <div style={styles.successMessage}>
                         <p><strong>Registration Successful!</strong></p>
                         <p>You can now log in using your username, password, and PGP key.</p>
                         <Link href="/login" className="button button-primary mt-2">Proceed to Login</Link>
                    </div>
                 ) : (
                    <>
                        <FormError message={error} />
                        <form onSubmit={handleRegister}>
                             {/* Username */}
                            <div className="form-group">
                                <label htmlFor="username" className="form-label">Username</label>
                                <input type="text" id="username" value={username} onChange={(e) => setUsername(e.target.value)} required className="form-input" disabled={isLoading}/>
                                <p className="form-help-text">Unique, cannot be changed later.</p>
                            </div>
                            {/* Password */}
                            <div className="form-group">
                                <label htmlFor="password"className="form-label">Password</label>
                                <input type="password" id="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="form-input" minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" disabled={isLoading}/>
                                <p className="form-help-text">Minimum {MIN_PASSWORD_LENGTH} characters. Choose a strong, unique password.</p>
                            </div>
                            {/* Confirm Password */}
                             <div className="form-group">
                                <label htmlFor="passwordConfirm" className="form-label">Confirm Password</label>
                                <input type="password" id="passwordConfirm" value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} required className="form-input" minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" disabled={isLoading}/>
                            </div>
                            {/* PGP Key */}
                            <div className="form-group">
                                 {/* <<< ADDED: Link to PGP Guide in label >>> */}
                                 <div style={styles.pgpLabelContainer}>
                                     <label htmlFor="pgpKey" className="form-label">PGP Public Key</label>
                                     <Link href="/pgp-guide" target="_blank" style={styles.pgpGuideLink}>What is this? PGP Guide</Link>
                                 </div>
                                {/* <<< CHANGE: Use global class for textarea >>> */}
                                <textarea id="pgpKey" value={pgpKey} onChange={(e) => setPgpKey(e.target.value)} required className="form-textarea" rows={10} placeholder="-----BEGIN PGP PUBLIC KEY BLOCK-----&#10;...&#10;-----END PGP PUBLIC KEY BLOCK-----" disabled={isLoading}/>
                                <p className="form-help-text">Required for login (2FA). Paste your entire public key block here.</p>
                            </div>

                            {/* CAPTCHA */}
                             <div style={styles.captchaContainer}>
                                <CaptchaInput
                                    imageUrl={captchaImageUrl}
                                    inputKey={captchaKey}
                                    value={captchaValue}
                                    onChange={(e) => setCaptchaValue(e.target.value)}
                                    onRefresh={refreshCaptcha}
                                    isLoading={captchaLoading}
                                    disabled={isLoading}
                                />
                                {!captchaLoading && !captchaImageUrl && <FormError message="Could not load CAPTCHA." />}
                            </div>

                            <button type="submit" disabled={isLoading || captchaLoading} className={`button button-primary w-100 ${ (isLoading || captchaLoading) ? 'disabled' : ''}`}>
                                {isLoading ? <LoadingSpinner size="1em"/> : 'Register'}
                            </button>
                        </form>

                        <p className="text-center mt-4">
                            Already have an account? <Link href="/login">Login here</Link>
                        </p>
                    </>
                )}
            </div>
        </Layout>
    );
}