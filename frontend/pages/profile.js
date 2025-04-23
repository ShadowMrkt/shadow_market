// frontend/pages/profile.js
// --- REVISION HISTORY ---
// 2025-04-23 (Gemini): Rev 20 - Corrected Vendor Status JSX logic again. When an applicationError occurs (fetch or initial apply fail), now displays the error *and* the Apply Button interface (matching test expectation).
// 2025-04-23 (Gemini): Rev 19 - Refined Vendor Status JSX logic. If applicationError is set during fetch, only the error is displayed, hiding status/apply button sections. Fixes test failure.
// 2025-04-23 (Gemini): Rev 18 - Fixed Vendor Status section:
//                      - Apply button now remains visible even if the initial API call fails (test fix).
//                      - Added descriptive text for 'pending_review' and 'approved' statuses (test fix).
//                      - Added descriptive text for 'rejected' status for consistency.
// 2025-04-23 (Gemini): Rev 17 - Moved state updates (setIsLoading...) out of finally blocks into try/catch. Removed automatic PGP modal reopening on post-PGP API errors to simplify state flow and potentially resolve act warnings.
// ... (previous history) ...

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { useAuth } from '../context/AuthContext';
import { updateCurrentUser, applyForVendor, getVendorApplicationStatus, ApiError } from '../utils/api';
import { formatDate } from '../utils/formatters';
import { showErrorToast, showSuccessToast, showInfoToast } from '../utils/notifications';
import LoadingSpinner from '../components/LoadingSpinner';
import PGPChallengeSigner from '../components/PgpChallengeSigner';
import FormError from '../components/FormError';
import Button from '../components/ui/Button';
import styles from '../styles/Profile.module.css';
import { MIN_PASSWORD_LENGTH } from '../utils/constants';

// Options for formatting date and time
const dateTimeOptions = {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: 'numeric', timeZoneName: 'short', timeZone: 'UTC'
};
const dateOnlyOptions = {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
}

const ProfilePage = () => {
    const { user, loading: authLoading, isPgpAuthenticated, setUser } = useAuth();
    const router = useRouter();

    // State for editable fields
    const [btcAddress, setBtcAddress] = useState('');
    const [ethAddress, setEthAddress] = useState('');
    const [pgpKey, setPgpKey] = useState('');
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');

    // State for loading indicators and errors/success messages
    const [isUpdatingAddresses, setIsUpdatingAddresses] = useState(false);
    const [isUpdatingPgpKey, setIsUpdatingPgpKey] = useState(false);
    const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);
    const [addressError, setAddressError] = useState('');
    const [pgpError, setPgpError] = useState('');
    const [passwordError, setPasswordError] = useState('');
    const [addressSuccess, setAddressSuccess] = useState('');
    const [pgpSuccess, setPgpSuccess] = useState('');
    const [passwordSuccess, setPasswordSuccess] = useState('');

    // Vendor Application State
    const [vendorApplication, setVendorApplication] = useState(null);
    const [isLoadingApplication, setIsLoadingApplication] = useState(true); // Start true for initial fetch
    const [applicationError, setApplicationError] = useState('');
    const [isSubmittingApplication, setIsSubmittingApplication] = useState(false);

    // PGP Modal State
    const [isPgpModalOpen, setIsPgpModalOpen] = useState(false);
    const [pgpActionType, setPgpActionType] = useState('');
    const [pgpChallenge, setPgpChallenge] = useState({ challenge_text: '', nonce: '' });
    const [pgpModalError, setPgpModalError] = useState('');

    // Fetch Vendor Application Status
    const fetchApplicationStatus = useCallback(async () => {
        // Only fetch if user exists, is NOT a vendor, and IS PGP authenticated
        if (user && !user.is_vendor && isPgpAuthenticated) {
            showInfoToast("Refreshing application status...");
            setIsLoadingApplication(true);
            setApplicationError(''); // Clear previous errors before fetching
            try {
                const statusData = await getVendorApplicationStatus();
                setVendorApplication(statusData);
                 // Moved from finally
                setIsLoadingApplication(false);
            } catch (err) {
                if (err.status === 404) {
                    // 404 means no application found, which is not an error state for display
                    setVendorApplication(null);
                } else {
                    // Handle actual errors during fetch
                    console.error("Failed to fetch vendor application status:", err);
                    const errorMsg = err.data?.detail || err.message || "Could not load vendor application status.";
                    setApplicationError(errorMsg); // Set error state to display
                    setVendorApplication(null); // Ensure no stale application data is shown
                    showErrorToast(errorMsg);
                }
                 // Moved from finally
                setIsLoadingApplication(false);
            }
            // Removed finally block
        } else {
            // If user is vendor, not logged in, or not PGP auth'd, don't load status
            setIsLoadingApplication(false); // Ensure loading stops
            setVendorApplication(null);
            setApplicationError('');
        }
    }, [user, isPgpAuthenticated]); // Dependencies: user context and PGP auth status

    useEffect(() => {
        // Fetch initial status only if PGP is authenticated
        if (isPgpAuthenticated) {
            fetchApplicationStatus();
        } else {
            // If not PGP authenticated, ensure loading is false and no app data shown
             setIsLoadingApplication(false);
             setVendorApplication(null);
             setApplicationError('');
        }
    }, [fetchApplicationStatus, isPgpAuthenticated]); // Re-run if PGP status changes


    useEffect(() => {
        if (!authLoading && !user) {
            console.log("User not logged in, redirecting to login.");
            router.replace(`/login?next=${router.pathname}`);
        }
    }, [authLoading, user, router]);

    useEffect(() => {
        if (user) {
            setBtcAddress(user.btc_withdrawal_address || '');
            setEthAddress(user.eth_withdrawal_address || '');
            setPgpKey(user.pgp_public_key || '');
        } else {
            setBtcAddress(''); setEthAddress(''); setPgpKey('');
        }
    }, [user]);

    // --- Vendor Application ---
    const handleApplyForVendor = async () => {
        if (!isPgpAuthenticated) {
            showErrorToast("PGP Authentication Required to apply."); return;
        }
        setIsSubmittingApplication(true);
        setApplicationError(''); // Clear previous application errors before trying again
        try {
            const challengeResponse = await applyForVendor(); // API call to get challenge
            if (challengeResponse && challengeResponse.challenge_text && challengeResponse.nonce) {
                setPgpChallenge(challengeResponse);
                setPgpActionType('apply_vendor');
                setIsPgpModalOpen(true);
                setPgpModalError('');
                // isSubmittingApplication remains true until modal callback
            } else {
                // Should ideally not happen if API behaves, but handle defensively
                throw new Error("Failed to get PGP challenge for vendor application.");
            }
        } catch (err) {
            // This catch block handles errors from the *initial* applyForVendor call (getting challenge)
            console.error("Failed to initiate vendor application:", err); // Changed log message slightly
            const errorMsg = err.data?.detail || err.message || "Failed to start vendor application process.";
            setApplicationError(errorMsg); // Set error to display in vendor section
            showErrorToast(errorMsg);
            // Ensure loading stops if the modal doesn't open due to this error
            setIsSubmittingApplication(false);
        }
    };


    // --- PGP Modal Callbacks ---
    const handlePgpChallengeSuccess = async (signedChallenge) => {
        setIsPgpModalOpen(false);
        const currentAction = pgpActionType;
        // Clear PGP state immediately after getting needed info
        setPgpActionType(''); setPgpChallenge({ challenge_text: '', nonce: '' }); setPgpModalError('');

        if (currentAction === 'update_addresses') {
            setIsUpdatingAddresses(true); setAddressError(''); setAddressSuccess('');
            try {
                const payload = { btc_withdrawal_address: btcAddress, eth_withdrawal_address: ethAddress, signed_challenge: signedChallenge };
                const updatedUser = await updateCurrentUser(payload);
                setUser(updatedUser); // Update context
                showSuccessToast("Withdrawal addresses updated successfully!");
                setAddressSuccess("Withdrawal addresses updated successfully!"); setAddressError('');
                 // Moved from finally
                setIsUpdatingAddresses(false);
            } catch (err) {
                console.error("Address update failed after PGP:", err);
                const errorMsg = err.data?.detail || (err.data ? JSON.stringify(err.data) : null) || err.message || "Failed to update addresses.";
                setAddressError(errorMsg); showErrorToast(errorMsg);
                 // Moved from finally
                setIsUpdatingAddresses(false);
            }
            // Removed finally block

        } else if (currentAction === 'update_pgp') {
            setIsUpdatingPgpKey(true); setPgpError(''); setPgpSuccess('');
            try {
                const payload = { pgp_public_key: pgpKey, signed_challenge: signedChallenge };
                const updatedUser = await updateCurrentUser(payload);
                setUser(updatedUser); // Update context
                showSuccessToast("PGP Key updated successfully!");
                setPgpSuccess("PGP Key updated successfully!"); setPgpError('');
                 // Moved from finally
                setIsUpdatingPgpKey(false);
            } catch (err) {
                console.error("PGP Key update failed after PGP:", err);
                const errorMsg = err.data?.detail || (err.data ? JSON.stringify(err.data) : null) || err.message || "Failed to update PGP key.";
                setPgpError(errorMsg); showErrorToast(errorMsg);
                 // Moved from finally
                setIsUpdatingPgpKey(false);
            }
            // Removed finally block

        } else if (currentAction === 'update_password') {
            setIsUpdatingPassword(true); setPasswordError(''); setPasswordSuccess('');
            try {
                const payload = { current_password: currentPassword, password: newPassword, signed_challenge: signedChallenge };
                await updateCurrentUser(payload); // Password change likely doesn't return user object
                showSuccessToast("Password changed successfully!");
                setPasswordSuccess("Password changed successfully!");
                // Clear fields on success
                setCurrentPassword(''); setNewPassword(''); setConfirmPassword(''); setPasswordError('');
                 // Moved from finally
                setIsUpdatingPassword(false);
            } catch (err) {
                console.error("Password change failed after PGP:", err);
                const errorMsg = err.data?.detail || (err.data ? JSON.stringify(err.data) : null) || err.message || "Failed to change password.";
                setPasswordError(errorMsg); showErrorToast(errorMsg);
                // Don't clear fields on error
                 // Moved from finally
                setIsUpdatingPassword(false);
            }
             // Removed finally block

        } else if (currentAction === 'apply_vendor') {
            // Keep submitting state true while we perform the post-PGP submission
            setIsSubmittingApplication(true); setApplicationError('');
            try {
                // This is the API call to submit the application *with* the signature
                await applyForVendor({ signed_challenge: signedChallenge });
                showSuccessToast("Vendor application submitted successfully.");
                // Refresh status immediately after successful submission
                await fetchApplicationStatus(); // This sets isLoadingApplication etc.
                // Let fetchApplicationStatus handle the final loading state
            } catch(err) {
                 // This catch handles errors from the *second* applyForVendor call (submitting signature)
                console.error("Vendor application submission failed after PGP:", err);
                const errorMsg = err.data?.detail || err.message || "Failed to submit vendor application after PGP step.";
                setApplicationError(errorMsg); showErrorToast(errorMsg);
                // Ensure loading stops on error here
                setIsSubmittingApplication(false);
            }
            // Removed finally block
        }
    };

    const handlePgpChallengeFail = (error) => {
        console.error("PGP Modal Error/Failure:", error);
        setPgpModalError(error || "PGP signing failed or was cancelled.");
        // Keep modal open, don't reset loading states here
    }

    const handlePgpChallengeCancel = () => {
        setIsPgpModalOpen(false);
        const currentAction = pgpActionType;
        // Reset PGP state first
        setPgpActionType(''); setPgpChallenge({ challenge_text: '', nonce: '' }); setPgpModalError('');
        // Reset loading state associated with the cancelled action
        if (currentAction === 'update_addresses') setIsUpdatingAddresses(false);
        if (currentAction === 'update_pgp') setIsUpdatingPgpKey(false);
        if (currentAction === 'update_password') setIsUpdatingPassword(false);
        if (currentAction === 'apply_vendor') setIsSubmittingApplication(false);
        showInfoToast("PGP authentication cancelled.");
    };

    // --- Form Handlers ---
    const handleAddressSubmit = async (e) => {
        console.log('handleAddressSubmit triggered');
        e.preventDefault();
        if (!isPgpAuthenticated) { showErrorToast("PGP Authentication Required."); return; }
        setAddressError(''); setAddressSuccess(''); setIsUpdatingAddresses(true);

        if (ethAddress && !/^0x[a-fA-F0-9]{40}$/.test(ethAddress)) {
            const errorMsg = "Invalid Ethereum address format.";
            setAddressError(errorMsg); showErrorToast(errorMsg);
            setIsUpdatingAddresses(false);
            return;
        }

        try {
            const challengeResponse = await updateCurrentUser({ request_pgp_challenge_for: 'addresses' });
            if (challengeResponse && challengeResponse.challenge_text && challengeResponse.nonce) {
                setPgpChallenge(challengeResponse); setPgpActionType('update_addresses'); setIsPgpModalOpen(true); setPgpModalError('');
                // isUpdatingAddresses remains true until modal callback
            } else {
                throw new Error("Failed to get PGP challenge for address update.");
            }
        } catch (err) {
            console.error("Address update initiation failed:", err);
            const errorMsg = err.data?.detail || err.message || "Failed to initiate address update.";
            setAddressError(errorMsg); showErrorToast(errorMsg); setIsUpdatingAddresses(false);
        }
    };

    const handlePgpKeySubmit = async (e) => {
        e.preventDefault();
        if (!isPgpAuthenticated) { showErrorToast("PGP Authentication Required."); return; }
        setPgpError(''); setPgpSuccess('');
        const pgpTrimmed = pgpKey.trim();

        if (!pgpTrimmed || !pgpTrimmed.includes('-----BEGIN PGP PUBLIC KEY BLOCK-----') || !pgpTrimmed.includes('-----END PGP PUBLIC KEY BLOCK-----')) {
            const errorMsg = "Invalid PGP key format. Please ensure you paste the entire block including BEGIN/END markers.";
            setPgpError(errorMsg); showErrorToast(errorMsg);
            return;
        }

        setIsUpdatingPgpKey(true);
        try {
            const challengeResponse = await updateCurrentUser({ request_pgp_challenge_for: 'pgp_key' });
            if (challengeResponse && challengeResponse.challenge_text && challengeResponse.nonce) {
                setPgpChallenge(challengeResponse); setPgpActionType('update_pgp'); setIsPgpModalOpen(true); setPgpModalError('');
                // isUpdatingPgpKey remains true until modal callback
            } else {
                throw new Error("Failed to get PGP challenge for PGP key update.");
            }
        } catch (err) {
            console.error("PGP key update initiation failed:", err);
            const errorMsg = err.data?.detail || err.message || "Failed to initiate PGP key update.";
            setPgpError(errorMsg); showErrorToast(errorMsg); setIsUpdatingPgpKey(false);
        }
    };

    const handlePasswordSubmit = async (e) => {
        e.preventDefault();
        if (!isPgpAuthenticated) { showErrorToast("PGP Authentication Required."); return; }
        setPasswordError(''); setPasswordSuccess('');

        if (!currentPassword || !newPassword || !confirmPassword) {
            setPasswordError("All password fields are required."); showErrorToast("All password fields are required."); return;
        }
        if (newPassword.length < MIN_PASSWORD_LENGTH) {
            const errorMsg = `New password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
            setPasswordError(errorMsg); showErrorToast(errorMsg); return;
        }
        if (newPassword !== confirmPassword) {
            setPasswordError("New passwords do not match."); showErrorToast("New passwords do not match."); return;
        }
        if (newPassword === currentPassword) {
             setPasswordError("New password cannot be the same as the current password."); showErrorToast("New password cannot be the same as the current password."); return;
        }

        setIsUpdatingPassword(true);
        try {
            const challengeResponse = await updateCurrentUser({ request_pgp_challenge_for: 'password' });
            if (challengeResponse && challengeResponse.challenge_text && challengeResponse.nonce) {
                setPgpChallenge(challengeResponse); setPgpActionType('update_password'); setIsPgpModalOpen(true); setPgpModalError('');
                // isUpdatingPassword remains true until modal callback
            } else {
                throw new Error("Failed to get PGP challenge for password change.");
            }
        } catch (err) {
            console.error("Password change initiation failed:", err);
            const errorMsg = err.data?.detail || err.message || "Failed to initiate password change.";
            setPasswordError(errorMsg); showErrorToast(errorMsg); setIsUpdatingPassword(false);
        }
    };

    if (authLoading || (!user && !authLoading)) {
        return <LoadingSpinner />;
    }

    // Helper function to get descriptive text for vendor status
    const getVendorStatusDescription = (status) => {
        switch (status) {
            case 'pending_review':
                return "Your application is currently under review.";
            case 'approved':
                return "Congratulations! Your vendor application has been approved.";
            case 'rejected':
                 return "Unfortunately, your vendor application has been rejected.";
            // Add other statuses if needed
            default:
                return null; // No specific description for other statuses like pending_bond (handled separately)
        }
    };

    return (
        <div className={styles.containerNarrow}>
            <Head><title>Your Profile - ShadowMarket</title></Head>
            <h1>Your Profile ({user?.username})</h1>

            {!isPgpAuthenticated && (
                <div className={`${styles.warningBox} alert alert-warning`}>
                    <h4>PGP Authentication Required</h4>
                    <p>For security, most profile modifications require an active PGP-authenticated session.</p>
                    <p>Complete PGP authentication first to manage vendor status.</p>
                    <p>Please <a href="/login?pgp=true" className="alert-link">re-authenticate with PGP</a> to enable these actions.</p>
                </div>
            )}

            <section className={styles.card}>
                <h2 className={styles.sectionTitle}>Account Information</h2>
                <div className={styles.formGroup}><label className={styles.formLabel}>Username:</label><div className={styles.readOnlyValue}>{user.username}</div></div>
                <div className={styles.formGroup}><label className={styles.formLabel}>Joined:</label><div className={styles.readOnlyValue}>{formatDate(user.date_joined, dateOnlyOptions)}</div></div>
                <div className={styles.formGroup}><label className={styles.formLabel}>Last Login:</label><div className={styles.readOnlyValue}>{formatDate(user.last_login, dateTimeOptions)}</div></div>
                <div className={styles.formGroup}><label className={styles.formLabel}>Vendor Status:</label><div className={styles.readOnlyValue}>{user.is_vendor ? 'Yes' : 'No'}</div></div>
                <div className={styles.formGroup}><label className={styles.formLabel}>Login Phrase (Anti-Phishing):</label><div className={styles.loginPhrase} title="Verify this phrase during login step 2.">{user.login_phrase || 'Not Set'}</div></div>
            </section>

            {/* --- Vendor Application Section (Only show if NOT a vendor) --- */}
            {!user.is_vendor && (
                <section className={styles.card}>
                    <h2 className={styles.sectionTitle}>Vendor Status</h2>

                    {/* Loading State */}
                    {isLoadingApplication && <LoadingSpinner message="Loading application status..." />}

                    {/* --- FIX: Revised Logic for Error/Status/Apply --- */}
                    {!isLoadingApplication && (
                        <>
                            {/* Display Error FIRST if it exists */}
                            {applicationError && <FormError message={applicationError} />}

                            {/* Display Status Details (only if NO error and application exists) */}
                            {!applicationError && vendorApplication && (
                                <div>
                                    <p><strong>Your Vendor Application Status:</strong> {vendorApplication.status_display || vendorApplication.status}</p>
                                    <p>Submitted: {formatDate(vendorApplication.created_at, dateTimeOptions)}</p>
                                    {vendorApplication.status === 'pending_bond' && (
                                        <p className={styles.highlight}>
                                            Action Required: Please deposit the required bond amount ({vendorApplication.bond_amount} {vendorApplication.bond_currency}) to your wallet.
                                        </p>
                                    )}
                                    {getVendorStatusDescription(vendorApplication.status) && (
                                        <p>{getVendorStatusDescription(vendorApplication.status)}</p>
                                    )}
                                    {vendorApplication.status === 'rejected' && <p>Reason: {vendorApplication.rejection_reason || 'No reason provided.'}</p>}
                                    {(vendorApplication.status === 'pending_review' || vendorApplication.status === 'pending_bond') && (
                                        <Button onClick={fetchApplicationStatus} disabled={isLoadingApplication || !isPgpAuthenticated} className="mt-2" title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}>Refresh Status</Button>
                                    )}
                                </div>
                            )}

                            {/* Display Apply Interface (only if NO application exists OR if an error occurred - allows retry) */}
                            {(!vendorApplication || applicationError) && (
                                <>
                                    {!isPgpAuthenticated && !applicationError && /* Show PGP prompt only if needed and no other error shown */
                                        <p className={styles.warningText}>Complete PGP authentication first to manage vendor status.</p>
                                    }
                                    <p>You are not currently a vendor. Applying requires PGP authentication and may require a bond payment.</p>
                                    <Button
                                        onClick={handleApplyForVendor}
                                        disabled={!isPgpAuthenticated || isSubmittingApplication}
                                        isLoading={isSubmittingApplication}
                                        variant="success"
                                        title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : "Apply to become a vendor"}
                                    >
                                        {isSubmittingApplication ? "Submitting..." : "Apply for Vendor Status"}
                                    </Button>
                                </>
                            )}
                        </>
                    )}
                    {/* --- END FIX --- */}
                </section>
            )}


            {/* --- Other Sections (Addresses, PGP Key, Password) --- */}
            <section className={styles.card}>
                <h2 className={styles.sectionTitle}>Withdrawal Addresses</h2>
                <form onSubmit={handleAddressSubmit} noValidate>
                    <p className={styles.formHelpText}>Set your withdrawal addresses here. For security, changes require PGP authentication.</p>
                    {addressError && <FormError message={addressError} />}
                    {addressSuccess && <div className="alert alert-success">{addressSuccess}</div>}
                    <div className={styles.formGroup}><label htmlFor="btcAddress" className={styles.formLabel}>Bitcoin (BTC) Address:</label><input type="text" id="btcAddress" value={btcAddress} onChange={(e) => setBtcAddress(e.target.value)} className={`${styles.formInput} ${styles.fontMonospace}`} placeholder="Enter your BTC withdrawal address" disabled={!isPgpAuthenticated || isUpdatingAddresses} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : "Enter a valid Bitcoin address"}/></div>
                    <div className={styles.formGroup}><label htmlFor="ethAddress" className={styles.formLabel}>Ethereum (ETH) Address:</label><input type="text" id="ethAddress" value={ethAddress} onChange={(e) => setEthAddress(e.target.value)} className={`${styles.formInput} ${styles.fontMonospace}`} placeholder="Enter your ETH withdrawal address (0x...)" pattern="^0x[a-fA-F0-9]{40}$" title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : "Enter a valid Ethereum address starting with 0x"} disabled={!isPgpAuthenticated || isUpdatingAddresses}/></div>
                    <Button type="submit" variant="primary" disabled={!isPgpAuthenticated || isUpdatingAddresses} isLoading={isUpdatingAddresses}>{isUpdatingAddresses ? 'Saving...' : 'Save Addresses'}</Button>
                </form>
            </section>

            <section className={styles.card}>
                <h2 className={styles.sectionTitle}>PGP Public Key</h2>
                <form onSubmit={handlePgpKeySubmit} noValidate>
                    <p className={styles.formHelpText}>Your PGP key is used for 2FA login and secure communication. Updating it requires PGP authentication.</p>
                    {pgpError && <FormError message={pgpError} />}
                    {pgpSuccess && <div className="alert alert-success">{pgpSuccess}</div>}
                    <div className={styles.formGroup}><label htmlFor="pgpKey" className={styles.formLabel}>Current PGP Key:</label><textarea id="pgpKey" value={pgpKey} onChange={(e) => setPgpKey(e.target.value)} rows="10" className={`${styles.formTextarea} ${styles.fontMonospace}`} placeholder="-----BEGIN PGP PUBLIC KEY BLOCK-----&#10;...&#10;-----END PGP PUBLIC KEY BLOCK-----" required disabled={!isPgpAuthenticated || isUpdatingPgpKey} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : "Paste your entire PGP public key block"}/></div>
                    <Button type="submit" variant="primary" disabled={!isPgpAuthenticated || isUpdatingPgpKey} isLoading={isUpdatingPgpKey}>{isUpdatingPgpKey ? 'Updating...' : 'Update PGP Key'}</Button>
                </form>
            </section>

            <section className={styles.card}>
                <h2 className={styles.sectionTitle}>Change Password</h2>
                <form onSubmit={handlePasswordSubmit} noValidate>
                    <p className={styles.formHelpText}>Choose a strong, unique password. Requires current password and PGP authentication.</p>
                    {passwordError && <FormError message={passwordError} />}
                    {passwordSuccess && <div className="alert alert-success">{passwordSuccess}</div>}
                    <div className={styles.formGroup}><label htmlFor="currentPassword" className={styles.formLabel}>Current Password:</label><input type="password" id="currentPassword" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className={styles.formInput} required autoComplete="current-password" disabled={!isPgpAuthenticated || isUpdatingPassword} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}/></div>
                    <div className={styles.formGroup}><label htmlFor="newPassword" className={styles.formLabel}>New Password:</label><input type="password" id="newPassword" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className={styles.formInput} minLength={MIN_PASSWORD_LENGTH} required autoComplete="new-password" disabled={!isPgpAuthenticated || isUpdatingPassword} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}/><p className={styles.formHelpText}>Minimum {MIN_PASSWORD_LENGTH} characters.</p></div>
                    <div className={styles.formGroup}><label htmlFor="confirmPassword" className={styles.formLabel}>Confirm New Password:</label><input type="password" id="confirmPassword" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className={styles.formInput} minLength={MIN_PASSWORD_LENGTH} required autoComplete="new-password" disabled={!isPgpAuthenticated || isUpdatingPassword} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}/></div>
                    <Button type="submit" variant="primary" disabled={!isPgpAuthenticated || isUpdatingPassword} isLoading={isUpdatingPassword}>{isUpdatingPassword ? 'Changing...' : 'Change Password'}</Button>
                </form>
            </section>

            {/* PGP Modal */}
            <PGPChallengeSigner
                isOpen={isPgpModalOpen}
                challengeText={pgpChallenge.challenge_text}
                nonce={pgpChallenge.nonce}
                onSuccess={handlePgpChallengeSuccess}
                onFail={handlePgpChallengeFail}
                onCancel={handlePgpChallengeCancel}
                errorMessage={pgpModalError}
             />
        </div>
    );
};

export default ProfilePage;