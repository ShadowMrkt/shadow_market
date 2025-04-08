// frontend/pages/wallet.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global dark theme classes, used CSS Module, used shared formatters.
//           - Removed inline styles object.
//           - Applied global classes (.container, .card, .warning-message, .form-*, .button-*).
//           - Created Wallet.module.css for custom styles (.balanceGrid, .balanceCard, .stepIndicator, etc.).
//           - Replaced local formatBalance with shared formatCurrency from formatters.js.
//           - Added TODOs for address validation and component verification.
//           - Refined comments and error handling messages.
//           - Added revision history block.

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { Decimal } from 'decimal.js'; // Still needed for client-side validation comparison
import { useAuth } from '../context/AuthContext';
import { getWalletBalances, prepareWithdrawal, executeWithdrawal } from '../utils/api';
import Layout from '../components/Layout';
import { SUPPORTED_CURRENCIES, CURRENCY_SYMBOLS } from '../utils/constants';
import { formatCurrency } from '../utils/formatters'; // Import shared formatter
import WithdrawalInputForm from '../components/WithdrawalInputForm'; // TODO: Verify component exists/props match
import PgpChallengeSigner from '../components/PgpChallengeSigner'; // TODO: Verify component exists/props match
import LoadingSpinner from '../components/LoadingSpinner';
import FormError from '../components/FormError';
import { showSuccessToast, showErrorToast, showInfoToast } from '../utils/notifications';
import styles from './Wallet.module.css'; // Import CSS Module for custom styles

// Configure Decimal.js precision if needed locally for comparisons (global setting might suffice)
// Decimal.set({ precision: 18 });

export default function WalletPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // State for Balances
    const [balances, setBalances] = useState(null);
    const [isLoadingBalances, setIsLoadingBalances] = useState(true);
    const [balanceLoadError, setBalanceLoadError] = useState(''); // Renamed for clarity

    // State for Withdrawal Process
    const [withdrawalStep, setWithdrawalStep] = useState(1); // 1: Input, 2: Sign
    const [currency, setCurrency] = useState(SUPPORTED_CURRENCIES[0] || 'XMR');
    const [amount, setAmount] = useState('');
    const [address, setAddress] = useState('');
    const [pgpMessageToSign, setPgpMessageToSign] = useState('');
    const [withdrawalSignature, setWithdrawalSignature] = useState('');
    const [isPreparing, setIsPreparing] = useState(false);
    const [isExecuting, setIsExecuting] = useState(false);
    const [withdrawalError, setWithdrawalError] = useState('');

    // Fetch balances function
    const fetchBalances = useCallback(async () => {
        // Balance view requires PGP Auth
        if (!user || !isPgpAuthenticated) {
            setIsLoadingBalances(false);
            // Don't set error if auth is still loading, AuthContext handles the redirect/initial state
            if (!authIsLoading) {
                 setBalanceLoadError("PGP authenticated session required to view balances.");
            }
            setBalances(null); // Ensure balances are cleared if auth fails
            return;
        }
        setIsLoadingBalances(true); setBalanceLoadError('');
        try {
            const data = await getWalletBalances();
            setBalances(data);
        } catch (err) {
            console.error("Failed to fetch balances:", err);
            // Use error message from API request helper
            const errorMsg = err.message || "Could not load wallet balances.";
            setBalanceLoadError(errorMsg); showErrorToast(errorMsg);
            setBalances(null);
        } finally { setIsLoadingBalances(false); }
    }, [user, isPgpAuthenticated, authIsLoading]); // Include authIsLoading dependency

    // Initial Fetch and Auth Check
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) { router.push('/login?next=/wallet'); }
            // Fetch balances only if user is loaded AND PGP auth status is known (true/false)
            else if (isPgpAuthenticated !== null) {
                fetchBalances();
            }
        }
         // If auth is loading, wait for it to finish.
         // If PGP status is null, wait for AuthContext initial check to complete.
    }, [user, authIsLoading, isPgpAuthenticated, router, fetchBalances]);

    // --- Withdrawal Handlers ---
    const handlePrepareWithdrawal = async (e) => {
        e.preventDefault();
        setWithdrawalError('');
        if (!isPgpAuthenticated) {
            showErrorToast("PGP authenticated session required."); setWithdrawalError("PGP session required."); return;
        }

        const availableBalance = balances?.[currency]?.available || '0';
        try {
            const requestedAmount = new Decimal(amount);
            const available = new Decimal(availableBalance);
            if (requestedAmount.isNaN() || requestedAmount.isNegative() || requestedAmount.isZero()) {
                 setWithdrawalError("Invalid amount specified (must be positive)."); return;
            }
            if (requestedAmount.greaterThan(available)) {
                 // Use shared formatter for display in error
                 setWithdrawalError(`Insufficient available funds. Available: ${formatCurrency(available, currency)}`); return;
            }
            if (!address.trim()) { setWithdrawalError("Destination address is required."); return; }
             // TODO: Implement client-side address format validation here (regex or library like 'cryptocurrency-address-validator')
             // e.g., if (!isValidAddress(address.trim(), currency)) { setWithdrawalError('Invalid address format for ' + currency); return; }

        } catch (decError) {
             setWithdrawalError("Invalid amount specified (must be a number)."); return;
        }

        setIsPreparing(true);
        const prepData = { currency, amount: amount.toString(), address: address.trim() };

        try {
            // SECURITY: Backend generates unique message including details + nonce
            const response = await prepareWithdrawal(prepData);
            setPgpMessageToSign(response.pgp_message_to_sign); // Expecting { pgp_message_to_sign: "..." }
            setWithdrawalStep(2);
            showInfoToast("Withdrawal prepared. Please sign the confirmation message.");
        } catch (err) {
            console.error("Prepare withdrawal failed:", err);
            const errorMsg = err.message || "Failed to prepare withdrawal. Check details or try again later.";
            setWithdrawalError(errorMsg); showErrorToast(errorMsg);
        } finally { setIsPreparing(false); }
    };

    const handleExecuteWithdrawal = async (e) => {
        e.preventDefault();
        setWithdrawalError('');
        if (!isPgpAuthenticated) { // Re-check PGP auth status
            showErrorToast("PGP authenticated session timed out. Please start withdrawal again.");
            setWithdrawalStep(1); setPgpMessageToSign(''); setWithdrawalSignature('');
            return;
        }
        if (!withdrawalSignature.trim()) {
            setWithdrawalError("Please paste your PGP signature for the withdrawal confirmation."); return;
        }
        setIsExecuting(true);

        const execData = {
            currency, amount: amount.toString(), address: address.trim(), // Resend details for backend verification
            pgp_confirmation_signature: withdrawalSignature.trim(),
        };

        try {
            // SECURITY: Backend validates signature against original message AND atomically checks/locks funds
            const response = await executeWithdrawal(execData);
            // Assuming response contains { transaction_id: "..." } on success
            showSuccessToast(`Withdrawal successful! ${response.transaction_id ? `Transaction ID: ${response.transaction_id}` : ''}`);
            // Reset form and fetch updated balances
            setAmount(''); setAddress(''); setWithdrawalSignature(''); setPgpMessageToSign('');
            setWithdrawalStep(1);
            fetchBalances();
        } catch (err) {
            console.error("Execute withdrawal failed:", err);
            let errorMsg = err.message || "Withdrawal execution failed. Please check signature or try again.";
            // Refine specific error messages
            if (typeof err.message === 'string') {
                if (err.message.toLowerCase().includes("invalid signature")) errorMsg = "Invalid PGP signature provided.";
                else if (err.message.toLowerCase().includes("insufficient funds")) errorMsg = "Insufficient available funds (balance may have changed).";
                else if (err.message.toLowerCase().includes("expired") || err.message.toLowerCase().includes("invalid") || err.message.toLowerCase().includes("not found")) {
                    errorMsg = "Withdrawal confirmation expired or invalid. Please start over.";
                    // Force back to step 1 on expiration errors
                    setWithdrawalStep(1); setPgpMessageToSign(''); setWithdrawalSignature('');
                }
            }
            setWithdrawalError(errorMsg); showErrorToast(errorMsg);
            // Stay on step 2 but show error, allowing user to correct signature
        } finally { setIsExecuting(false); }
    };

    const handleBackToStep1 = () => {
        setWithdrawalStep(1);
        setPgpMessageToSign('');
        setWithdrawalSignature('');
        setWithdrawalError('');
    }

    // --- Render Logic ---
    if (authIsLoading) {
        return <Layout><div className="text-center p-5"><LoadingSpinner message="Loading wallet..." /></div></Layout>;
    }
    if (!user && !authIsLoading) {
        // Redirect should have happened, but render fallback message
        return <Layout><div className="container text-center p-5">Please login to view your wallet.</div></Layout>;
    }

    return (
        <Layout>
            {/* Use global container class */}
            <div className="container">
                <h1>Your Wallet</h1>

                {/* Balance Display Section - Use global card class */}
                <section className="card mb-4">
                     <h2 className={styles.sectionTitle}>Balances</h2>
                     {balanceLoadError && <FormError message={balanceLoadError} />}
                     {!isPgpAuthenticated && !authIsLoading && !balanceLoadError && (
                         <div className="warning-message"> {/* Use global class */}
                              PGP authenticated session required to view balances. Please <Link href="/login" className="font-weight-bold">re-login</Link>.
                         </div>
                     )}
                     {isLoadingBalances && <LoadingSpinner message="Loading balances..." />}
                     {!isLoadingBalances && !balanceLoadError && balances && isPgpAuthenticated && (
                         <div className={styles.balanceGrid}>
                              {SUPPORTED_CURRENCIES.map(curr => (
                                 <div key={curr} className={styles.balanceCard}>
                                      <div className={styles.balanceCurrency}>{CURRENCY_SYMBOLS[curr] || curr}</div>
                                      <div className={styles.balanceValue} title={`Total: ${balances[curr]?.total || '0'}`}>
                                          {formatCurrency(balances[curr]?.total, curr)}
                                      </div>
                                      <div className={styles.balanceLabel}>Total</div>
                                      <hr className={styles.hr}/>
                                      <div className={styles.balanceValue} title={`Available: ${balances[curr]?.available || '0'}`}>
                                          {formatCurrency(balances[curr]?.available, curr)}
                                      </div>
                                      <div className={styles.balanceLabel}>Available</div>
                                      <div className={styles.balanceLocked} title={`Locked: ${balances[curr]?.locked || '0'}`}>
                                          ({formatCurrency(balances[curr]?.locked, curr)} Locked)
                                      </div>
                                  </div>
                              ))}
                         </div>
                     )}
                     {!isLoadingBalances && !balanceLoadError && !balances && isPgpAuthenticated && (
                         <p>Could not load balance data.</p>
                     )}
                </section>

                 {/* Withdrawal Section - Use global card class */}
                 <section className="card mb-4">
                     <h2 className={styles.sectionTitle}>Withdraw Funds</h2>

                     {!isPgpAuthenticated && !authIsLoading && (
                          <div className="warning-message"> {/* Use global class */}
                              PGP authenticated session required to withdraw funds. Please <Link href="/login" className="font-weight-bold">re-login</Link>.
                          </div>
                     )}

                     {/* Display withdrawal error if any */}
                     <FormError message={withdrawalError} />

                     {/* Step 1: Withdrawal Input Form */}
                     {withdrawalStep === 1 && isPgpAuthenticated && (
                         <form onSubmit={handlePrepareWithdrawal}>
                              <div className={styles.stepIndicator} aria-current="step">Step 1: Enter Withdrawal Details</div>
                              {/* Assuming WithdrawalInputForm uses global form styles */}
                              <WithdrawalInputForm
                                 currency={currency}
                                 onCurrencyChange={(e) => { setCurrency(e.target.value); setWithdrawalError(''); }}
                                 amount={amount}
                                 onAmountChange={(e) => setAmount(e.target.value)}
                                 address={address}
                                 onAddressChange={(e) => setAddress(e.target.value)}
                                 balances={balances} // Pass balances for display/validation
                                 disabled={isPreparing}
                             />
                              <button type="submit" disabled={isPreparing} className={`button button-primary mt-3 ${ isPreparing ? 'disabled' : '' }`}>
                                  {isPreparing ? <LoadingSpinner size="1em"/> : 'Prepare Withdrawal'}
                              </button>
                         </form>
                     )}

                     {/* Step 2: PGP Confirmation */}
                     {withdrawalStep === 2 && isPgpAuthenticated && (
                          <form onSubmit={handleExecuteWithdrawal}>
                              <div className={styles.stepIndicator} aria-current="step">Step 2: Confirm with PGP Signature</div>
                              <div className={styles.pgpInstructions}>
                                   <p>To confirm your withdrawal of <strong>{amount} {currency}</strong> to address <strong className='font-monospace'>{address}</strong>, please sign the following message block EXACTLY using the PGP private key associated with your account (Clearsign).</p>
                                   <ol>
                                       <li>Copy the entire message block below.</li>
                                       <li>Use your PGP software to "Sign" this text (Clearsign).</li>
                                       <li>Paste the ENTIRE resulting signed message (including BEGIN/END markers) into the signature field.</li>
                                   </ol>
                                   <p><Link href="/pgp-guide#signing-challenge" target="_blank" className="small">Need help signing?</Link></p>
                              </div>

                             {/* Assuming PgpChallengeSigner uses global form styles */}
                              <PgpChallengeSigner
                                 challengeText={pgpMessageToSign}
                                 signatureValue={withdrawalSignature}
                                 onSignatureChange={(e) => setWithdrawalSignature(e.target.value)}
                                 disabled={isExecuting}
                                 challengeLabel="Message to Sign:"
                                 signatureLabel="Paste Signed Confirmation Message:"
                             />
                              {/* Use global spacing/layout utilities if available, or module styles */}
                              <div className={`d-flex gap-2 mt-3 ${styles.actionButtons}`}>
                                   <button type="button" onClick={handleBackToStep1} className="button button-secondary" disabled={isExecuting}>Back</button>
                                   <button type="submit" disabled={isExecuting || !withdrawalSignature.trim()} className={`button button-success ${ (isExecuting || !withdrawalSignature.trim()) ? 'disabled' : '' }`}>
                                       {isExecuting ? <LoadingSpinner size="1em"/> : 'Execute Withdrawal'}
                                   </button>
                              </div>
                          </form>
                     )}
                </section>

            </div>
        </Layout>
    );
}

// TODO: Create Wallet.module.css for .sectionTitle, .balanceGrid, .balanceCard, .balance*, .hr, .balanceLocked, .stepIndicator, .pgpInstructions, .actionButtons.
// TODO: Verify/Implement WithdrawalInputForm and PgpChallengeSigner components and their props.
// TODO: Implement client-side address format validation.