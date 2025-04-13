// frontend/pages/wallet.js
// --- REVISION HISTORY ---
// 2025-04-13: Rev 15 - Added reset for `amount` and `address` state in handleBackToStep1 function to clear inputs when returning from Step 2. (Gemini)
// 2025-04-13: Rev 14 - Added reset for `amount` and `address` state in handleExecuteWithdrawal catch block when `shouldReset` is true (e.g., on expired error), fixing test failure. (Gemini)
// 2025-04-12: Rev 13 - Changed main useEffect dependency from `router` object to specific `router.pathname` and `router.push` to improve stability in tests. Added pathname check before redirect. (Gemini)
// 2025-04-12: Rev 12 - Simplified async state handling in fetchBalances: setIsLoadingBalances(false) now ONLY in finally block. (Gemini)
// 2025-04-12: Rev 11 - Updated isValidAddress placeholder logic for better test compatibility; Added data-testid="balance-grid". (Gemini)
// ... previous history ...

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { Decimal } from 'decimal.js';
import { useAuth } from '../context/AuthContext';
import { getWalletBalances, prepareWithdrawal, executeWithdrawal } from '../utils/api'; // Adjust path
import Layout from '../components/Layout'; // Adjust path
import { SUPPORTED_CURRENCIES, CURRENCY_SYMBOLS, ERROR_MESSAGES } from '../utils/constants'; // Adjust path
import { formatCurrency } from '../utils/formatters'; // Adjust path
import WithdrawalInputForm from '../components/WithdrawalInputForm'; // Adjust path
import PgpChallengeSigner from '../components/PgpChallengeSigner'; // Adjust path
import LoadingSpinner from '../components/LoadingSpinner'; // Adjust path
import { showSuccessToast, showErrorToast, showInfoToast } from '../utils/notifications'; // Adjust path
import styles from './Wallet.module.css'; // Adjust path

// Placeholder Address Validation Function - REMINDER: Needs real implementation
const isValidAddress = (address, currencyCode) => {
    const trimmedAddress = address?.trim() || '';
    if (!trimmedAddress) return false;
    console.warn(`isValidAddress: Using placeholder validation for ${currencyCode}. IMPLEMENT REAL CHECKS.`);
    switch (currencyCode) {
        case 'XMR':
            return trimmedAddress.length > 10;
        case 'BTC':
            return trimmedAddress.length >= 26 && trimmedAddress.length <= 62;
        default:
            return trimmedAddress.length > 10;
    }
};


export default function WalletPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();
    // *** Destructure router properties used in effects ***
    const { push: routerPush, pathname: routerPathname } = router;


    // State
    const [balances, setBalances] = useState(null);
    const [isLoadingBalances, setIsLoadingBalances] = useState(true);
    const [balanceLoadError, setBalanceLoadError] = useState('');
    const [withdrawalStep, setWithdrawalStep] = useState(1);
    const [currency, setCurrency] = useState(SUPPORTED_CURRENCIES[0] || 'XMR');
    const [amount, setAmount] = useState('');
    const [address, setAddress] = useState('');
    const [pgpMessageToSign, setPgpMessageToSign] = useState('');
    const [withdrawalId, setWithdrawalId] = useState('');
    const [withdrawalSignature, setWithdrawalSignature] = useState('');
    const [isPreparing, setIsPreparing] = useState(false);
    const [isExecuting, setIsExecuting] = useState(false);
    const [withdrawalError, setWithdrawalError] = useState('');

    // fetchBalances function - Dependencies should be stable now
    const fetchBalances = useCallback(async (isRetry = false) => {
        if (!isPgpAuthenticated && user) {
            if (!isRetry) setIsLoadingBalances(false);
            if (!authIsLoading && isPgpAuthenticated === false) {
                setBalanceLoadError("PGP authenticated session required to view balances.");
            } else if (!user && !authIsLoading) {
                setBalanceLoadError("Please login to view balances.");
                setBalances(null);
            }
            return;
        }
        // ** Use stable routerPathname here **
        if (authIsLoading || (!user && routerPathname === '/wallet')) {
            return;
        }

        setIsLoadingBalances(true);
        setBalanceLoadError('');
        try {
            const data = await getWalletBalances();
            setBalances(data);
        } catch (err) {
            console.error("WalletPage: Failed to fetch balances:", err);
            const errorMsg = err.message || "Could not load wallet balances.";
            setBalanceLoadError(errorMsg);
            showErrorToast(errorMsg);
            // Keep existing balances on failed refresh
        } finally {
            setIsLoadingBalances(false);
        }
    // ** Use stable routerPathname in dependency **
    }, [user, isPgpAuthenticated, authIsLoading, routerPathname]); // Removed fetchBalances from here as it's defined outside effect using it

    // useEffect for Initial Fetch and Auth Check
    useEffect(() => {
        // console.log("Effect running: AuthLoading:", authIsLoading, "User:", !!user, "PGP:", isPgpAuthenticated, "Path:", routerPathname); // Keep for debugging if needed
        if (!authIsLoading) {
            if (!user) {
                // ** Use stable routerPathname and routerPush **
                if (routerPathname === '/wallet') {
                    routerPush('/login?next=/wallet');
                }
            } else if (isPgpAuthenticated === false) {
                setIsLoadingBalances(false);
                setBalanceLoadError("PGP authenticated session required. Please re-login to authenticate.");
                setBalances(null);
            } else if (isPgpAuthenticated === true) {
                fetchBalances();
            }
        }
    // ** Use stable dependencies **
    }, [user, authIsLoading, isPgpAuthenticated, routerPathname, routerPush, fetchBalances]); // Use specific, stable dependencies

    // handlePrepareWithdrawal function
    const handlePrepareWithdrawal = async (e) => {
        e.preventDefault();
        setWithdrawalError('');
        if (!isPgpAuthenticated) {
            setWithdrawalError("PGP authenticated session required to initiate withdrawal.");
            showErrorToast("PGP authenticated session required.");
            return;
        }
        const availableBalance = balances?.[currency]?.available || '0';
        const trimmedAddress = address.trim();

        // --- Validation ---
        try {
            const requestedAmount = new Decimal(amount);
            const available = new Decimal(availableBalance);

            if (requestedAmount.isNaN()) {
                setWithdrawalError("Invalid amount specified (must be a number)."); return;
            }
            if (requestedAmount.isNegative() || requestedAmount.isZero()) {
                setWithdrawalError("Invalid amount specified (must be positive)."); return;
            }
            if (requestedAmount.greaterThan(available)) {
                setWithdrawalError(`Insufficient available funds. Available: ${formatCurrency(available, currency)}`); return;
            }
            if (!trimmedAddress) {
                 setWithdrawalError("Destination address is required."); return;
            }
            if (!isValidAddress(trimmedAddress, currency)) {
                setWithdrawalError(`Invalid address format for ${currency}. Please double-check.`);
                return;
            }
        } catch (decError) {
             setWithdrawalError("Invalid amount specified (must be a number)."); return;
        }
        // --- End Validation ---

        setIsPreparing(true);
        const prepData = { currency, amount: amount.toString(), address: trimmedAddress };
        try {
            const response = await prepareWithdrawal(prepData);
            setPgpMessageToSign(response.pgp_message_to_sign);
            setWithdrawalId(response.withdrawal_id);
            setWithdrawalStep(2);
            showInfoToast("Withdrawal prepared. Please sign the confirmation message.");
        } catch (err) {
            console.error("Prepare withdrawal failed:", err);
            const errorMsg = err.message || "Failed to prepare withdrawal. Check details or try again later.";
            setWithdrawalError(errorMsg); showErrorToast(errorMsg);
        } finally { setIsPreparing(false); }
    };

    // handleExecuteWithdrawal function
    const handleExecuteWithdrawal = async (e) => {
        e.preventDefault();
        setWithdrawalError('');
        if (!isPgpAuthenticated) {
            showErrorToast("PGP authenticated session timed out. Please start withdrawal again.");
            setWithdrawalStep(1); setPgpMessageToSign(''); setWithdrawalSignature(''); setWithdrawalId('');
            // Also clear amount/address if PGP timed out during Step 2 execution attempt
            setAmount('');
            setAddress('');
            return;
        }
        const trimmedSignature = withdrawalSignature.trim();
        if (!trimmedSignature) {
            setWithdrawalError("Please paste your PGP signature for the withdrawal confirmation."); return;
        }
        setIsExecuting(true);

        const execData = {
            withdrawal_id: withdrawalId,
            pgp_confirmation_signature: trimmedSignature,
        };

        try {
            const response = await executeWithdrawal(execData);
            showSuccessToast(`Withdrawal successful! ${response.transaction_id ? `Transaction ID: ${response.transaction_id}` : ''}`);
            setAmount(''); setAddress(''); setWithdrawalSignature(''); setPgpMessageToSign(''); setWithdrawalId('');
            setWithdrawalStep(1);
            fetchBalances(true); // Refresh balances on success
        } catch (err) {
            console.error("Execute withdrawal failed:", err);
            let errorMsg = err.message || "Withdrawal execution failed. Please check signature or try again.";
            let shouldReset = false;
            let shouldRefreshBalances = false;

            if (typeof err.message === 'string') {
                const lowerCaseMsg = err.message.toLowerCase();
                const expiryMsg = ERROR_MESSAGES?.WITHDRAWAL_EXPIRED?.toLowerCase() || 'expired or invalid';

                if (lowerCaseMsg.includes(expiryMsg)) {
                    errorMsg = "Withdrawal expired or invalid. Please prepare a new withdrawal."; // Use user-friendly message directly
                    shouldReset = true;
                    shouldRefreshBalances = true;
                } else if (lowerCaseMsg.includes("invalid signature")) {
                    errorMsg = "Invalid PGP signature provided.";
                } else if (lowerCaseMsg.includes("insufficient funds")) {
                    errorMsg = "Insufficient available funds (balance may have changed since preparation).";
                    shouldReset = true;
                    shouldRefreshBalances = true;
                }
                // Consider other specific API errors here that might require reset
            }

            setWithdrawalError(errorMsg);
            showErrorToast(errorMsg);

            if (shouldReset) {
                setWithdrawalStep(1);
                setPgpMessageToSign('');
                setWithdrawalSignature('');
                setWithdrawalId('');
                setAmount('');
                setAddress('');
                if (shouldRefreshBalances) {
                    fetchBalances(true); // Refresh balances if state might be stale (e.g. insufficient funds)
                }
            }
            // If not reset, we stay on Step 2 (e.g., invalid signature), user can correct and retry.
        } finally {
             setIsExecuting(false);
        }
    };

    // handleBackToStep1 function (Updated)
    const handleBackToStep1 = () => {
        setWithdrawalStep(1);
        setPgpMessageToSign('');
        setWithdrawalSignature('');
        setWithdrawalId('');
        setWithdrawalError('');
        // *** FIX: Reset amount and address when going back ***
        setAmount('');
        setAddress('');
        // *** END FIX ***
    }

    // --- Render Logic ---
    if (authIsLoading) {
        return <Layout><div className="text-center p-5"><LoadingSpinner message="Loading authentication..." /></div></Layout>;
    }
    if (!user && !authIsLoading) {
         return <Layout><div className="container text-center p-5">Redirecting to login...</div></Layout>;
    }

    return (
        <Layout>
            <div className="container">
                <h1>Your Wallet</h1>

                {/* Balance Display Section */}
                <section className="card mb-4">
                    <h2 className={styles.sectionTitle}>Balances</h2>
                    {balanceLoadError && (
                        <div role="alert" data-testid="balance-load-error-alert" aria-live="assertive" className={styles.errorMessage}>
                            {balanceLoadError}
                            {balanceLoadError.includes("PGP authenticated session required") && (
                                <div className="mt-2 small">
                                    Please <Link href="/login?pgp=required" className="font-weight-bold">re-login to authenticate PGP</Link>.
                                </div>
                            )}
                        </div>
                    )}
                    {isLoadingBalances && <LoadingSpinner data-testid="balance-spinner" message="Loading balances..." />}

                    {!isLoadingBalances && !balanceLoadError && balances && isPgpAuthenticated === true && (
                        <div className={styles.balanceGrid} data-testid="balance-grid">
                            {SUPPORTED_CURRENCIES.map(curr => {
                                const balanceData = balances[curr];
                                const total = balanceData?.total ?? '0';
                                const available = balanceData?.available ?? '0';
                                const locked = balanceData?.locked ?? '0';
                                return (
                                    <div key={curr} className={styles.balanceCard}>
                                        <div className={styles.balanceCurrency}>{CURRENCY_SYMBOLS[curr] || curr}</div>
                                        <div className={styles.balanceValue} title={`Total: ${total}`}>
                                            {formatCurrency(total, curr)}
                                        </div>
                                        <div className={styles.balanceLabel}>Total</div>
                                        <hr className={styles.hr}/>
                                        <div className={styles.balanceValue} title={`Available: ${available}`}>
                                            {formatCurrency(available, curr)}
                                        </div>
                                        <div className={styles.balanceLabel}>Available</div>
                                        <div className={styles.balanceLocked} title={`Locked: ${locked}`}>
                                            ({formatCurrency(locked, curr)} Locked)
                                        </div>
                                    </div>
                                );
                            })}
                           </div>
                    )}
                    {!isLoadingBalances && !balanceLoadError && !balances && isPgpAuthenticated === true && (
                         <p>No balance data found or balances are zero.</p>
                    )}
                 </section>

                 {/* Withdrawal Section */}
                 <section className="card mb-4">
                      <h2 className={styles.sectionTitle}>Withdraw Funds</h2>
                      {withdrawalError && (
                          <div role="alert" aria-live="assertive" className={styles.errorMessage}>
                              {withdrawalError}
                          </div>
                      )}
                      {isPgpAuthenticated === true ? (
                          <>
                              {withdrawalStep === 1 && (
                                  <form onSubmit={handlePrepareWithdrawal}>
                                      <div className={styles.stepIndicator} aria-current="step">Step 1: Enter Withdrawal Details</div>
                                      <WithdrawalInputForm
                                          currency={currency}
                                          onCurrencyChange={(e) => { setCurrency(e.target.value); setWithdrawalError(''); }}
                                          amount={amount}
                                          onAmountChange={(e) => setAmount(e.target.value)}
                                          address={address}
                                          onAddressChange={(e) => setAddress(e.target.value)}
                                          onSubmit={handlePrepareWithdrawal}
                                          isLoading={isPreparing}
                                          disabled={isPreparing}
                                          balances={balances}
                                      />
                                  </form>
                              )}
                              {withdrawalStep === 2 && (
                                  <form onSubmit={handleExecuteWithdrawal}>
                                      <div className={styles.stepIndicator} aria-current="step">Step 2: Confirm with PGP Signature</div>
                                      <div className={styles.pgpInstructions}>
                                           {/* Instructions */}
                                          <p>To confirm your withdrawal of <strong>{amount} {currency}</strong> to address <strong className='font-monospace'>{address}</strong>, please sign the following message block EXACTLY using the PGP private key associated with your account (Clearsign).</p>
                                          <ol>
                                               <li>Copy the entire message block below.</li>
                                               <li>Use your PGP software to "Sign" this text (Clearsign).</li>
                                               <li>Paste the ENTIRE resulting signed message (including BEGIN/END markers) into the signature field.</li>
                                           </ol>
                                           <p><Link href="/pgp-guide#signing-challenge" target="_blank" className="small">Need help signing?</Link></p>
                                      </div>
                                      <PgpChallengeSigner
                                          challengeText={pgpMessageToSign}
                                          signatureValue={withdrawalSignature}
                                          onSignatureChange={(e) => setWithdrawalSignature(e.target.value)}
                                          username={user?.username}
                                          disabled={isExecuting}
                                          challengeLabel="Message to Sign:"
                                          signatureLabel="Paste Signed Confirmation Message:"
                                      />
                                      <div className={`d-flex gap-2 mt-3 ${styles.actionButtons}`}>
                                          <button type="button" onClick={handleBackToStep1} className="button button-secondary" disabled={isExecuting}>Back</button>
                                          <button type="submit" disabled={isExecuting || !withdrawalSignature.trim()} className={`button button-success ${ (isExecuting || !withdrawalSignature.trim()) ? 'disabled' : '' }`}>
                                              {isExecuting ? <LoadingSpinner size="1em"/> : 'Execute Withdrawal'}
                                          </button>
                                      </div>
                                  </form>
                              )}
                          </>
                      ) : (
                          !authIsLoading && isPgpAuthenticated === false && (
                              <div className="warning-message">
                                  PGP authenticated session required to withdraw funds. Please <Link href="/login?pgp=required" className="font-weight-bold">re-login to authenticate PGP</Link>.
                              </div>
                          )
                      )}
                  </section>
            </div>
        </Layout>
    );
}