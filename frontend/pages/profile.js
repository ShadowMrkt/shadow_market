// frontend/pages/profile.js
// --- REVISION HISTORY ---
// 2025-04-11: Rev 4 - [Gemini] Removed initial setPasswordError('') in handleChangePassword handler to potentially resolve test timing issue.
// 2025-04-11: Rev 3 - [Gemini] Added missing import for 'formatDate' utility function.
// 2025-04-07: Rev 2 - Applied global dark theme classes, used CSS Module for custom styles, used PGP constants.
// ... (previous history) ...

// ... (imports remain the same) ...
import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../context/AuthContext';
import { updateCurrentUser } from '../utils/api';
import { formatDate } from '../utils/formatters';
import Layout from '../components/Layout';
import Modal from '../components/Modal';
import LoadingSpinner from '../components/LoadingSpinner';
import FormError from '../components/FormError';
import { showSuccessToast, showErrorToast, showWarningToast, showInfoToast } from '../utils/notifications';
import { MIN_PASSWORD_LENGTH, PGP_PUBLIC_KEY_BLOCK } from '../utils/constants';
import styles from './Profile.module.css';

export default function ProfilePage() {
    // ... (state variables remain the same) ...
    const { user, isPgpAuthenticated, isLoading: authIsLoading, setUser, logout } = useAuth();
    const router = useRouter();

    // State for editable fields
    const [btcAddress, setBtcAddress] = useState('');
    const [ethAddress, setEthAddress] = useState('');
    const [pgpKey, setPgpKey] = useState('');
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');

    // State for API operations
    const [isSavingAddresses, setIsSavingAddresses] = useState(false);
    const [isSavingPgp, setIsSavingPgp] = useState(false);
    const [isSavingPassword, setIsSavingPassword] = useState(false);
    const [addressError, setAddressError] = useState('');
    const [pgpError, setPgpError] = useState('');
    const [passwordError, setPasswordError] = useState('');

    // State for PGP confirmation modal
    const [isPgpModalOpen, setIsPgpModalOpen] = useState(false);


    // ... (useEffect hooks remain the same) ...
     useEffect(() => {
        if (user) {
            setBtcAddress(user.btc_withdrawal_address || '');
            setEthAddress(user.eth_withdrawal_address || '');
            setPgpKey(user.pgp_public_key || '');
        } else {
            setBtcAddress(''); setEthAddress(''); setPgpKey('');
        }
    }, [user]);

    // Redirect if not logged in
    useEffect(() => {
        if (!authIsLoading && !user) {
            // Use replace for redirects to avoid adding the profile page to history
            router.replace('/login?next=/profile');
        }
    }, [user, authIsLoading, router]);


    // --- Handlers ---
    const handleSaveAddresses = async (e) => {
        e.preventDefault();
        setAddressError(''); // Clear previous errors
        if (!isPgpAuthenticated) {
            showErrorToast("PGP authenticated session required.");
            setAddressError("PGP session required.");
            return;
        }
        setIsSavingAddresses(true);
        const payload = {
            btc_withdrawal_address: btcAddress.trim() || null,
            eth_withdrawal_address: ethAddress.trim() || null,
        };
        try {
            const updatedUser = await updateCurrentUser(payload);
            setUser(updatedUser); // Update global user context
            showSuccessToast("Withdrawal addresses updated!");
        } catch (err) {
            console.error("Update addresses failed:", err);
            const errorMsg = err.response?.data?.btc_withdrawal_address?.[0] ||
                             err.response?.data?.eth_withdrawal_address?.[0] ||
                             err.message || "Failed to update addresses.";
            setAddressError(errorMsg);
            showErrorToast(`Update failed: ${errorMsg}`);
        } finally { setIsSavingAddresses(false); }
    };

    const handleInitiatePgpUpdate = (e) => {
        e.preventDefault();
        setPgpError(''); // Clear previous errors
        if (!isPgpAuthenticated) {
             showErrorToast("PGP authenticated session required.");
             setPgpError("PGP session required.");
             return;
        }
        const keyToValidate = pgpKey.trim();
        if (!keyToValidate.startsWith(PGP_PUBLIC_KEY_BLOCK.BEGIN) || !keyToValidate.includes(PGP_PUBLIC_KEY_BLOCK.END)) {
             setPgpError(`Invalid PGP Key format. Ensure the full block including "${PGP_PUBLIC_KEY_BLOCK.BEGIN}" and "${PGP_PUBLIC_KEY_BLOCK.END}" was pasted correctly.`);
             showErrorToast('Invalid PGP key format.');
             return;
        }
        setIsPgpModalOpen(true);
    };

    const handleConfirmSavePgpKey = async () => {
        // No need to clear pgpError here, cleared on modal close or new attempt
        if (!isPgpAuthenticated) {
             showErrorToast("PGP authenticated session timed out or invalid. Please re-login.");
             setIsPgpModalOpen(false);
             return;
        }
        setIsSavingPgp(true);
        const payload = { pgp_public_key: pgpKey.trim() };
        try {
             const updatedUser = await updateCurrentUser(payload);
             setUser(updatedUser);
             showSuccessToast("PGP key updated successfully!");
             showWarningToast("PGP key changed! Use the new key for future logins/verification.");
             setIsPgpModalOpen(false);
             // logout(); // Consider forcing logout
        } catch (err) {
             console.error("Update PGP key failed:", err);
             const errorMsg = err.response?.data?.pgp_public_key?.[0] ||
                              err.message || "Failed to update PGP key.";
             setPgpError(errorMsg); // Show error within the modal
             showErrorToast(`Update failed: ${errorMsg}`);
        } finally { setIsSavingPgp(false); }
    };

    const handleClosePgpModal = () => {
        setIsPgpModalOpen(false);
        setPgpError(''); // Clear modal-specific errors on close
    }

    const handleChangePassword = async (e) => {
         e.preventDefault();
         // setPasswordError(''); // <<< REMOVED THIS LINE
         if (!isPgpAuthenticated) {
               showErrorToast("PGP authenticated session required.");
               setPasswordError("PGP session required."); // Set error
               return;
         }
         // Perform checks and set error if validation fails
         if (!currentPassword || !newPassword || !confirmPassword) { setPasswordError("All password fields are required."); return; }
         if (newPassword.length < MIN_PASSWORD_LENGTH) { setPasswordError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`); return; }
         if (newPassword !== confirmPassword) { setPasswordError("New passwords do not match."); return; }
         if (newPassword === currentPassword) { setPasswordError("New password cannot be the same as the current password."); return; }

        // If validation passes, clear any previous error before proceeding
        setPasswordError('');
         setIsSavingPassword(true);
         const payload = { current_password: currentPassword, password: newPassword, password_confirm: confirmPassword };
         try {
               await updateCurrentUser(payload);
               showSuccessToast("Password changed successfully!");
               setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
               showInfoToast("Password changed successfully. Use the new password for your next login.");
               // logout(); // Consider forcing logout
         } catch (err) {
               console.error("Change password failed:", err);
               const errorMsg = err.response?.data?.current_password?.[0] ||
                                err.response?.data?.password?.[0] ||
                                err.response?.data?.detail ||
                                err.message || "Failed to change password.";
               setPasswordError(errorMsg); // Set error on API failure
               showErrorToast(`Password change failed: ${errorMsg}`);
         } finally { setIsSavingPassword(false); }
    };

    // --- Render Logic ---
    // ... (render logic remains the same) ...
        if (authIsLoading) {
        return <Layout><div className="text-center p-5"><LoadingSpinner message="Loading profile..." /></div></Layout>;
    }
    if (!user) {
        // Render nothing or a redirect notice while router pushes
        // This avoids rendering the form momentarily before redirecting
        return <Layout><div className="container-narrow text-center p-5">Redirecting to login...</div></Layout>;
    }

    const formsDisabled = !isPgpAuthenticated;

    return (
        <Layout>
            {/* Use global container class */}
            <div className="container-narrow">
                <h1>Your Profile ({user.username})</h1>

                 {!isPgpAuthenticated && (
                      // Use global warning message class
                      <div className="warning-message mb-4">
                          <strong>Security Notice:</strong> Your session is not PGP authenticated. Viewing is allowed, but saving changes requires completing the PGP login challenge. Please <Link href="/login" className="font-weight-bold">re-login</Link> if needed. Forms below are disabled.
                      </div>
                 )}

                {/* Read-only Info Section - Use global card class */}
                <section className="card">
                      <h2 className={styles.sectionTitle}>Account Information</h2>
                      <div className="form-group"> <label className="form-label">Username:</label> <div className={styles.readOnlyValue}>{user.username}</div> </div>
                      <div className="form-group"> <label className="form-label">Joined:</label> <div className={styles.readOnlyValue}>{formatDate(user.date_joined)}</div> </div>
                      <div className="form-group"> <label className="form-label">Last Login:</label> <div className={styles.readOnlyValue}>{formatDate(user.last_login, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })}</div> </div>
                      <div className="form-group"> <label className="form-label">Vendor Status:</label> <div className={styles.readOnlyValue}>{user.is_vendor ? `Yes (Level ${user.vendor_level || 'N/A'})` : 'No'}</div> </div>
                      {user.login_phrase && ( <div className="form-group"> <label className="form-label">Login Phrase (Anti-Phishing):</label> <div className={styles.loginPhrase} title="Verify this phrase during login step 2.">{user.login_phrase}</div> </div> )}
                 </section>

                {/* Withdrawal Addresses Section */}
                 <section className="card">
                    <h2 className={styles.sectionTitle}>Withdrawal Addresses</h2>
                    <form onSubmit={handleSaveAddresses}>
                        <div className="form-group">
                            <label htmlFor="btcAddress" className="form-label">Bitcoin (BTC) Address</label>
                            <input type="text" id="btcAddress" value={btcAddress} onChange={(e) => setBtcAddress(e.target.value)} className="form-input font-monospace" placeholder="Enter your BTC withdrawal address" disabled={isSavingAddresses || formsDisabled} />
                        </div>
                        <div className="form-group">
                            <label htmlFor="ethAddress" className="form-label">Ethereum (ETH) Address</label>
                            <input type="text" id="ethAddress" value={ethAddress} onChange={(e) => setEthAddress(e.target.value)} className="form-input font-monospace" placeholder="Enter your ETH withdrawal address (checksummed)" disabled={isSavingAddresses || formsDisabled}/>
                        </div>
                        {/* TODO: Add XMR address field if supported by backend */}
                        <FormError message={addressError} />
                        <button type="submit" disabled={isSavingAddresses || formsDisabled} className={`button button-primary ${ (isSavingAddresses || formsDisabled) ? 'disabled' : '' }`} title={formsDisabled ? "Requires PGP Authenticated Session" : ""}>
                             {isSavingAddresses ? <LoadingSpinner size="1em"/> : 'Save Addresses'}
                        </button>
                    </form>
                 </section>

                {/* PGP Key Management Section */}
                 <section className="card">
                    <h2 className={styles.sectionTitle}>PGP Public Key</h2>
                    <p className="form-help-text mb-3">Required for login (2FA) and secure communications. Update ONLY if your key is compromised or expiring, AND you possess the private key for the new public key.</p>
                    <form onSubmit={handleInitiatePgpUpdate}>
                        <div className="form-group">
                            <label htmlFor="pgpKey" className="form-label">Your Public Key Block</label>
                            <textarea id="pgpKey" value={pgpKey} onChange={(e) => setPgpKey(e.target.value)} required className="form-textarea font-monospace" rows={10} disabled={formsDisabled} aria-describedby="pgpHelp"/>
                            <small id="pgpHelp" className="form-help-text">Paste the entire block, including BEGIN/END markers.</small>
                            {/* Show PGP error inline only if modal is not open */}
                            <FormError message={pgpError && !isPgpModalOpen ? pgpError : ''} />
                        </div>
                         <button type="submit"
                            disabled={formsDisabled} // Disable only based on PGP auth for initiating
                            className={`button button-primary ${ formsDisabled ? 'disabled' : '' }`}
                            title={formsDisabled ? "Requires PGP Authenticated Session" : "Update PGP Key (requires confirmation)"}
                         >
                             {'Update PGP Key...'}
                         </button>
                    </form>
                 </section>

                {/* Password Change Section */}
                 <section className="card">
                    <h2 className={styles.sectionTitle}>Change Password</h2>
                    <form onSubmit={handleChangePassword}>
                        <div className="form-group">
                              <label htmlFor="currentPassword" className="form-label">Current Password</label>
                              <input type="password" id="currentPassword" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required className="form-input" autoComplete="current-password" disabled={isSavingPassword || formsDisabled}/>
                        </div>
                        <div className="form-group">
                              <label htmlFor="newPassword" className="form-label">New Password</label>
                              <input type="password" id="newPassword" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required className="form-input" minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" disabled={isSavingPassword || formsDisabled} aria-describedby="newPassHelp" />
                              <small id="newPassHelp" className="form-help-text">Minimum {MIN_PASSWORD_LENGTH} characters.</small>
                        </div>
                        <div className="form-group">
                              <label htmlFor="confirmPassword" className="form-label">Confirm New Password</label>
                              <input type="password" id="confirmPassword" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required className="form-input" minLength={MIN_PASSWORD_LENGTH} autoComplete="new-password" disabled={isSavingPassword || formsDisabled}/>
                        </div>
                         <FormError message={passwordError} />
                         <button type="submit" disabled={isSavingPassword || formsDisabled} className={`button button-primary ${ (isSavingPassword || formsDisabled) ? 'disabled' : '' }`} title={formsDisabled ? "Requires PGP Authenticated Session" : ""}>
                              {isSavingPassword ? <LoadingSpinner size="1em"/> : 'Change Password'}
                         </button>
                    </form>
                 </section>

            </div>

             {/* PGP Key Update Confirmation Modal */}
              <Modal
                 isOpen={isPgpModalOpen}
                 onClose={handleClosePgpModal} // Use specific handler
                 title="Confirm PGP Key Update"
             >
                 {/* Using module style for custom list styling if needed */}
                 <p><strong>CRITICAL SECURITY WARNING:</strong></p>
                 <ul className={styles.warningList}>
                     <li>You are changing the PGP key used for Login (2FA) and Encryption.</li>
                     <li>**You MUST possess the PRIVATE key** corresponding to the NEW public key you entered.</li>
                     <li>If you confirm with an incorrect key or lose access to the new private key, **you WILL permanently lose access to your account.** Account recovery is impossible.</li>
                     <li>Your current session MAY be invalidated after this change.</li>
                 </ul>
                 <p>Are you absolutely sure you wish to proceed?</p>
                 {/* Show PGP save errors inside the modal */}
                 <FormError message={pgpError} />
                 <div className={styles.modalActions}> {/* Use module style for modal actions */}
                      {/* Use global button classes */}
                      <button onClick={handleClosePgpModal} className="button button-secondary" disabled={isSavingPgp}>Cancel</button>
                      <button
                         onClick={handleConfirmSavePgpKey}
                         className={`button button-danger ${isSavingPgp ? 'disabled' : ''}`}
                         disabled={isSavingPgp}
                      >
                         {isSavingPgp ? <LoadingSpinner size="1em" /> : 'Confirm & Update PGP Key'}
                     </button>
                 </div>
             </Modal>

        </Layout>
    );
}