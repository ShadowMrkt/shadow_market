// frontend/pages/orders/[orderId].js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Merged duplicate components, refactored to CSS Modules, Decimal.js, constants, cleaned up action/state logic.
//           - Removed duplicate OrderDetail component. Renamed OrderDetailPage -> OrderDetail.
//           - Replaced inline styles with CSS Module import (OrderDetail.module.css).
//           - Replaced local formatPrice with import from formatters (assuming Decimal.js). Added formatDate.
//           - Replaced hardcoded status strings with constants (assuming ORDER_STATUS in constants.js).
//           - Clarified and streamlined action logic (finalize vs prepare release).
//           - Improved state management (isLoading, actionLoading, isSigning, errors).
//           - Integrated global dark theme styles (buttons, messages, inputs) where appropriate.
//           - Improved PGP auth checking and feedback.
//           - Enhanced multi-sig UI flow clarity (copy button, labels).
//           - Added basic a11y attributes (aria-busy).
//           - Added revision history block.

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext';
import {
    getOrderDetails,
    markOrderShipped,
    // finalizeOrder, // Likely replaced by prepare/sign flow initiation if multi-sig
    openDispute,
    getUnsignedReleaseTxData, // API to get data for signing
    signRelease             // API to submit the signature
} from '../../utils/api'; // TODO: Verify these API functions exist and match expected params/response
import Layout from '../../components/Layout';
import { CURRENCY_SYMBOLS, ORDER_STATUS } from '../../utils/constants'; // TODO: Ensure ORDER_STATUS map exists in constants.js
import { formatPrice, formatDate } from '../../utils/formatters'; // TODO: Ensure these exist and use Decimal.js for price
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { showErrorToast, showSuccessToast, showInfoToast } from '../../utils/notifications';
import styles from './OrderDetail.module.css'; // Import CSS Module

// --- Order Detail Page Component ---
export default function OrderDetail() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();
    const { orderId } = router.query;

    // --- State Variables ---
    const [order, setOrder] = useState(null);
    const [isLoading, setIsLoading] = useState(true); // Loading state for initial order fetch
    const [error, setError] = useState(''); // General page load error
    const [userRole, setUserRole] = useState(null); // 'buyer', 'vendor', or 'staff'

    // Action-specific states
    const [actionLoading, setActionLoading] = useState(false); // Loading for simple actions (Mark Shipped, Dispute)
    const [disputeReason, setDisputeReason] = useState('');
    const [showDisputeForm, setShowDisputeForm] = useState(false);

    // Multi-sig Signing state
    const [isSigning, setIsSigning] = useState(false); // Loading for prepare/submit signature actions
    const [unsignedTxData, setUnsignedTxData] = useState('');
    const [userSignatureInput, setUserSignatureInput] = useState('');
    const [prepareTxError, setPrepareTxError] = useState('');
    const [signError, setSignError] = useState('');

    // --- Data Fetching ---
    const fetchOrderDetails = useCallback(async (showLoading = true) => {
        if (!orderId) {
             setIsLoading(false); // Ensure loading stops if no ID
             return;
        }
        // Require PGP Auth to view sensitive order details
        if (!isPgpAuthenticated && !authIsLoading) {
             setError("PGP authentication required to view order details. Please log out and log back in fully.");
             showErrorToast("PGP authentication required.");
             setIsLoading(false);
             setOrder(null); // Clear any stale order data
             return;
         }
        // Don't proceed if still checking auth or PGP status isn't confirmed yet
        if (authIsLoading || isPgpAuthenticated === null) {
             setIsLoading(true); // Show loading while waiting for auth context
             return;
        }

        if (showLoading) setIsLoading(true);
        setError('');
        // Don't clear previous order data immediately if doing a background refresh (showLoading=false)

        try {
            console.log(`Workspaceing order details for ${orderId}...`);
            const data = await getOrderDetails(orderId);
            setOrder(data);

            if (data && user) {
                if (data.buyer?.id === user.id) setUserRole('buyer');
                else if (data.vendor?.id === user.id) setUserRole('vendor');
                else if (user.is_staff) setUserRole('staff');
                else {
                     setUserRole(null); // User not involved
                     throw new Error("You do not have permission to view this order."); // Throw error if user role can't be determined
                }
            } else if (!data) {
                 throw new Error("Order not found.");
            }
        } catch (err) {
            console.error(`Failed to fetch order ${orderId}:`, err);
            const errorMessage = err.response?.data?.detail || err.message || `Could not load order ${orderId}.`;
            setError(errorMessage);
            showErrorToast(`Error loading order: ${errorMessage}`);
            setOrder(null); // Clear order data on error
            setUserRole(null);
        } finally {
             // Only set loading false if it was set true initially
             // Avoids flicker on background refresh
             if (showLoading || !order) setIsLoading(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [orderId, user, isPgpAuthenticated, authIsLoading]); // Dependencies for fetching


    // --- Effects ---
    // Redirect if not logged in (after initial auth check)
    useEffect(() => {
        if (!authIsLoading && !user && router.isReady) {
            router.push(`/login?next=${encodeURIComponent(router.asPath)}`);
        }
    }, [user, authIsLoading, router]);

    // Fetch order details when dependencies change
    useEffect(() => {
        if (router.isReady && user) {
             fetchOrderDetails();
        } else if (router.isReady && !user && !authIsLoading) {
             // Handle case where user is definitely logged out but redirection hasn't happened yet
             setIsLoading(false);
        }
    }, [router.isReady, user, orderId, fetchOrderDetails]); // Rerun if orderId changes

    // --- Helper for Simple Actions ---
    const handleSimpleAction = async (actionName, apiCall, successMessage, options = {}) => {
        if (!isPgpAuthenticated) {
            showErrorToast("Action requires a PGP authenticated session. Please log out and log back in.");
            return;
        }
        setActionLoading(true);
        try {
            const result = await apiCall();
            setOrder(result); // Optimistically update UI, or rely on re-fetch
            showSuccessToast(successMessage);
            if (options.clearDisputeForm) {
                setDisputeReason('');
                setShowDisputeForm(false);
            }
            // Re-fetch in background to ensure consistency
            await fetchOrderDetails(false); // Refresh without main loading spinner
        } catch (err) {
            console.error(`${actionName} failed:`, err);
            const message = err.response?.data?.detail || err.message || `Failed to ${actionName}.`;
            showErrorToast(message);
            // Optionally set a local error state if needed beyond toast
        } finally {
            setActionLoading(false);
        }
    };

    // --- Specific Action Handlers ---
    const handleMarkShipped = () => {
        handleSimpleAction(
            'mark shipped',
            () => markOrderShipped(order.id), // Assuming API takes just orderId
            'Order marked as shipped!'
        );
    };

    const handleOpenDispute = (e) => {
        e.preventDefault();
        if (!disputeReason.trim()) {
            showErrorToast("Please provide a reason for the dispute.");
            return;
        }
        handleSimpleAction(
            'open dispute',
            () => openDispute(order.id, { reason: disputeReason }),
            'Dispute opened successfully!',
            { clearDisputeForm: true }
        );
    };

    // --- Multi-Sig Handlers ---
    const handlePrepareRelease = async () => {
        if (!order || !orderId || !isPgpAuthenticated) {
            showErrorToast("Cannot prepare release. Order data missing or PGP session invalid.");
            return;
        }
        setIsSigning(true);
        setPrepareTxError('');
        setUnsignedTxData('');
        setUserSignatureInput('');

        try {
            // Assumes API returns { unsigned_tx: "BASE64_PSBT_OR_HEX" }
            const data = await getUnsignedReleaseTxData(orderId);
            if (data && data.unsigned_tx) {
                setUnsignedTxData(data.unsigned_tx);
                showSuccessToast("Unsigned transaction data prepared. Please sign externally.");
            } else {
                const errorMsg = "Failed to retrieve unsigned transaction data from the server.";
                setPrepareTxError(errorMsg);
                showErrorToast(errorMsg);
            }
        } catch (err) {
            console.error("Prepare release error:", err);
            const message = err.response?.data?.detail || err.message || "An error occurred while preparing the release transaction.";
            setPrepareTxError(message);
            showErrorToast(message);
        } finally {
            setIsSigning(false);
        }
    };

    const handleSignRelease = async (e) => {
        e.preventDefault();
        if (!order || !orderId || !userSignatureInput.trim() || !isPgpAuthenticated) {
            setSignError("Cannot submit signature. Order data, signature, or PGP session invalid.");
            showErrorToast("Cannot submit signature. Data or PGP session invalid.");
            return;
        }
        setIsSigning(true);
        setSignError('');

        try {
            // Assumes signRelease expects { signature_data: ... }
            // TODO: Verify API contract for signRelease response structure
            const result = await signRelease(orderId, { signature_data: userSignatureInput.trim() });
            showSuccessToast("Signature submitted successfully!");

            // Clear form and maybe hide it
            setUnsignedTxData(''); // Clear unsigned data to hide the form
            setUserSignatureInput('');
            setPrepareTxError('');
            setSignError('');

            // Show info if broadcast-ready (adjust based on actual API response)
            if (result?.is_ready_for_broadcast) {
                 showInfoToast("Order is now ready for final broadcast by the system.");
            } else if (result?.message) {
                 showInfoToast(result.message); // Show backend message if provided
            }

            // Refresh order state
            await fetchOrderDetails(false); // Refresh without main loading spinner
        } catch (err) {
            console.error("Sign release error:", err);
            const message = err.response?.data?.detail || err.message || "An error occurred while submitting the signature.";
            setSignError(message);
            showErrorToast(message);
        } finally {
            setIsSigning(false);
        }
    };

    const handleCopyData = () => {
         navigator.clipboard.writeText(unsignedTxData)
            .then(() => showSuccessToast('Data copied to clipboard!'))
            .catch(err => showErrorToast('Failed to copy data. Please copy manually.'));
    };

    // --- Render Logic ---
    if (isLoading) {
        return <Layout><div className={styles.loadingContainer}><LoadingSpinner message="Loading Order..." /></div></Layout>;
    }
    // Show redirecting message if user isn't loaded yet but auth check is done
    if (!user && !authIsLoading) {
        return <Layout><div className={styles.loadingContainer}><LoadingSpinner message="Redirecting to login..." /></div></Layout>;
    }
    // Show main error if occurred during load or if PGP required but missing
    if (error) {
        return <Layout><div className={styles.container}><div className="error-message">{error}</div></div></Layout>;
    }
    // Final check if order is still null after loading attempt (e.g., 404)
    if (!order) {
        return <Layout><div className={styles.container}><p>Order not found or could not be loaded.</p></div></Layout>;
    }

    // Derived constants for rendering logic
    const currencySymbol = CURRENCY_SYMBOLS[order.selected_currency] || order.selected_currency;
    const orderStatus = order.status; // Assuming status is already in the desired format (e.g., use constants map if needed)

    // Determine available actions based on status, role, and signing state
    const isVendor = userRole === 'vendor';
    const isBuyer = userRole === 'buyer';

    const canMarkShipped = isVendor && orderStatus === ORDER_STATUS.PAYMENT_CONFIRMED;

    // Determine if the user (buyer or vendor) needs to provide *their* signature
    const needsMySignature = order.escrow_type === 'multi-sig' && order.release_initiated &&
                             ((isBuyer && !order.release_signature_buyer_present) ||
                              (isVendor && !order.release_signature_vendor_present));

    // User can prepare the release TX if they need to sign and it hasn't been prepared yet
    const canPrepareRelease = needsMySignature;

    // Conditions to allow opening a dispute (adjust based on exact market rules)
    const canOpenDispute = (isBuyer || isVendor) &&
                            [ORDER_STATUS.PAYMENT_CONFIRMED, ORDER_STATUS.SHIPPED].includes(orderStatus) &&
                           (!order.dispute_deadline || new Date() < new Date(order.dispute_deadline));


    return (
        <Layout>
            <div className={styles.container}>
                <h1 className={styles.title}>Order Details <code className={styles.code}>{order.id.substring(0, 8)}...</code></h1>
                {/* Order Meta Info */}
                <div className={styles.metaGrid}>
                     <p><strong className={styles.label}>Status:</strong> <span className={styles[`status_${orderStatus}`] || ''}>{order.status_display || orderStatus}</span></p>
                     <p><strong className={styles.label}>Date Placed:</strong> {formatDate(order.created_at)}</p>
                     <p><strong className={styles.label}>Last Updated:</strong> {formatDate(order.updated_at)}</p>
                     {userRole && <p>
                         <strong className={styles.label}>Your Role:</strong>
                         <span className={styles[`role_${userRole}`]}>{userRole.toUpperCase()}</span>
                     </p>}
                 </div>

                {/* PGP Auth Warning */}
                {!isPgpAuthenticated && <div className="warning-message mt-3">Actions on this page require a PGP authenticated session. Some actions may be disabled. Please log out and log back in fully if needed.</div>}

                {/* Main Content Grid */}
                <div className={styles.grid}>
                    {/* Left Column: Product, Payment, Shipping */}
                    <div className={styles.leftCol}>
                        <section>
                            <h2 className={styles.sectionTitle}>Product</h2>
                            {order.product ? (
                                <div>
                                    <Link href={`/products/${order.product.slug}`} className={styles.productLink}>
                                         <h3>{order.product.name}</h3>
                                    </Link>
                                    <p><strong className={styles.label}>Quantity:</strong> {order.quantity}</p>
                                    <p><strong className={styles.label}>Vendor:</strong> <Link href={`/vendors/${order.vendor?.username}`} className={styles.link}>{order.vendor?.username}</Link></p>
                                    {/* Consider adding mini ProductCard here? */}
                                </div>
                            ) : <p>Product details not available.</p>}
                        </section>

                        <section>
                            <h2 className={styles.sectionTitle}>Payment</h2>
                            {order.payment ? (
                                <>
                                    <p><strong className={styles.label}>Currency:</strong> {order.selected_currency}</p>
                                    <p><strong className={styles.label}>Total Price:</strong> {currencySymbol} {formatPrice(order.total_price_native_selected, order.selected_currency)}</p>
                                    <p><strong className={styles.label}>Deposit Address:</strong> <code className={`${styles.codeBlock} ${styles.wrapText}`}>{order.payment.payment_address}</code></p>
                                    {order.payment.payment_id_monero && <p><strong className={styles.label}>Monero Payment ID:</strong> <code className={styles.codeBlock}>{order.payment.payment_id_monero}</code></p>}
                                    <p><strong className={styles.label}>Payment Status:</strong> {order.payment.is_confirmed ? `Confirmed (${order.payment.confirmations_received}/${order.payment.confirmations_needed} confs)` : `Pending (${order.payment.confirmations_received}/${order.payment.confirmations_needed} confs)`}</p>
                                    {order.payment.transaction_hash && <p><strong className={styles.label}>Transaction Hash:</strong> <code className={`${styles.codeBlock} ${styles.wrapText}`}>{order.payment.transaction_hash}</code></p> }
                                    {order.payment_deadline && <p><strong className={styles.label}>Payment Deadline:</strong> {formatDate(order.payment_deadline)}</p>}
                                </>
                            ) : <p>Payment details not available.</p>}
                        </section>

                        <section>
                            <h2 className={styles.sectionTitle}>Shipping</h2>
                            {order.product?.is_digital ? (
                                <p>Digital product - no shipping required.</p>
                            ) : (
                                <>
                                    <p><strong className={styles.label}>Option:</strong> {order.selected_shipping_option?.name || 'N/A'}</p>
                                    {isVendor && (
                                        <div>
                                            <strong className={styles.label}>Shipping Address (Encrypted):</strong>
                                            {order.encrypted_shipping_info ? (
                                                <div className={styles.encryptedInfo}>
                                                    <p className="small text-muted mb-1">Decrypt using your PGP private key.</p>
                                                    {/* TODO: Add client-side decrypt button if implementing PGP tools */}
                                                     {/* <button className="button button-secondary button-sm mb-2">Decrypt Here (Requires Key)</button> */}
                                                    <textarea readOnly rows="6" value={order.encrypted_shipping_info} className={`form-textarea ${styles.codeBlock}`}></textarea>
                                                </div>
                                            ) : (
                                                <div className="error-message mt-2">Shipping information missing!</div>
                                            )}
                                        </div>
                                    )}
                                    {isBuyer && <p className="text-muted small">(Shipping address is encrypted and only visible to the vendor)</p>}
                                </>
                            )}
                        </section>
                    </div>

                    {/* Right Column: Participants, Deadlines, Escrow, Actions */}
                    <div className={styles.rightCol}>
                        <section>
                            <h2 className={styles.sectionTitle}>Participants</h2>
                            <p><strong className={styles.label}>Buyer:</strong> {order.buyer?.username || 'N/A'}</p>
                            <p><strong className={styles.label}>Vendor:</strong> <Link href={`/vendors/${order.vendor?.username}`} className={styles.link}>{order.vendor?.username || 'N/A'}</Link></p>
                        </section>

                        <section>
                            <h2 className={styles.sectionTitle}>Deadlines</h2>
                            <p><strong className={styles.label}>Auto-Finalize By:</strong> {formatDate(order.auto_finalize_deadline)}</p>
                            <p><strong className={styles.label}>Dispute By:</strong> {formatDate(order.dispute_deadline)}</p>
                        </section>

                         <section>
                            <h2 className={styles.sectionTitle}>Escrow Details ({order.escrow_type})</h2>
                            {order.escrow_type === 'multi-sig' && (
                                <>
                                     {/* Display relevant multi-sig info */}
                                     {order.btc_escrow_address && <p><strong className={styles.label}>BTC Escrow Addr:</strong> <code className={`${styles.codeBlock} ${styles.wrapText}`}>{order.btc_escrow_address}</code></p>}
                                     {order.xmr_multisig_wallet_name && <p><strong className={styles.label}>XMR Wallet Context:</strong> {order.xmr_multisig_wallet_name}</p>}
                                     {/* Add ETH details if implemented */}
                                    <p><strong className={styles.label}>Release Initiated:</strong> {order.release_initiated ? 'Yes' : 'No'}</p>
                                    <p><strong className={styles.label}>Buyer Signed:</strong> {order.release_signature_buyer_present ? 'Yes' : 'No'}</p>
                                    <p><strong className={styles.label}>Vendor Signed:</strong> {order.release_signature_vendor_present ? 'Yes' : 'No'}</p>
                                    <p><strong className={styles.label}>Ready for Broadcast:</strong> {order.is_ready_for_broadcast ? 'Yes' : 'No'}</p>
                                    {order.release_tx_broadcast_hash && <p><strong className={styles.label}>Release TX Hash:</strong> <code className={`${styles.codeBlock} ${styles.wrapText}`}>{order.release_tx_broadcast_hash}</code></p>}
                                </>
                            )}
                             {order.escrow_type !== 'multi-sig' && (
                                <p>Standard Escrow (Details may vary)</p>
                             )}
                        </section>

                        {/* --- Actions Section --- */}
                        <section aria-live="polite" aria-busy={actionLoading || isSigning}>
                             <h2 className={styles.sectionTitle}>Actions</h2>

                            {/* Vendor Actions */}
                            {isVendor && canMarkShipped && (
                                <button
                                    onClick={handleMarkShipped}
                                    disabled={actionLoading || !isPgpAuthenticated}
                                    className="button button-primary"
                                >
                                    {actionLoading ? <LoadingSpinner size="small" /> : 'Mark as Shipped'}
                                </button>
                            )}

                            {/* Multi-Sig Signing Flow */}
                            {order.escrow_type === 'multi-sig' && (
                                <>
                                    {/* Prepare Release Button */}
                                    {canPrepareRelease && !unsignedTxData && (
                                        <div className={styles.actionSection}>
                                            <h4>Provide Your Signature for Release</h4>
                                            <p className="text-muted small">Click below to get the unsigned transaction data. You'll need to sign this data using your external wallet.</p>
                                            <button
                                                onClick={handlePrepareRelease}
                                                disabled={isSigning || !isPgpAuthenticated}
                                                className="button button-primary"
                                            >
                                                {isSigning ? <LoadingSpinner size="small" /> : 'Prepare Release Transaction'}
                                            </button>
                                            {prepareTxError && <FormError message={prepareTxError} className="mt-2" />}
                                        </div>
                                    )}

                                    {/* Signing Form (shown when unsignedTxData is available) */}
                                    {unsignedTxData && (
                                        <div className={styles.actionSection}>
                                            <h4>Sign Release Transaction ({order.selected_currency.toUpperCase()})</h4>
                                            <p className="text-muted small">Copy the data below and sign it using your external wallet software. Paste the resulting signature data back here.</p>
                                            <div className="form-group">
                                                <label htmlFor="unsignedTxDataDisplay" className="form-label">Unsigned Transaction Data:</label>
                                                <textarea
                                                    id="unsignedTxDataDisplay" readOnly rows={7}
                                                    value={unsignedTxData}
                                                    className={`form-textarea ${styles.codeBlock}`} // Use global + module styles
                                                />
                                                <button onClick={handleCopyData} className="button button-secondary mt-2">Copy Data</button>
                                            </div>

                                            <form onSubmit={handleSignRelease}>
                                                <div className="form-group">
                                                    <label htmlFor="userSignatureInput" className="form-label">Paste Your Signature Data Here:</label>
                                                    <textarea
                                                        id="userSignatureInput" rows={7}
                                                        value={userSignatureInput}
                                                        onChange={(e) => setUserSignatureInput(e.target.value)}
                                                        required aria-required="true"
                                                        className={`form-textarea ${styles.codeBlock}`}
                                                        placeholder={order.selected_currency === 'BTC' ? 'Paste signed PSBT (Base64)' : 'Paste signed transaction data (Hex)'}
                                                        aria-describedby="signatureHelp"
                                                    />
                                                    <small id="signatureHelp" className="form-help-text">Ensure you paste the complete signature data provided by your wallet.</small>
                                                </div>
                                                {signError && <FormError message={signError} />}
                                                <button
                                                    type="submit"
                                                    disabled={isSigning || !userSignatureInput || !isPgpAuthenticated}
                                                    className="button button-success"
                                                >
                                                    {isSigning ? <LoadingSpinner size="small" /> : 'Submit Signature'}
                                                </button>
                                            </form>
                                        </div>
                                    )}
                                </>
                            )}
                             {/* End Multi-Sig Flow */}


                            {/* Dispute Action */}
                            {canOpenDispute && (
                                <div className={styles.actionSection}>
                                    {!showDisputeForm ? (
                                        <button
                                            onClick={() => setShowDisputeForm(true)}
                                            disabled={actionLoading || !isPgpAuthenticated}
                                            className="button button-danger"
                                        >
                                            Open Dispute
                                        </button>
                                    ) : (
                                        <form onSubmit={handleOpenDispute} className={styles.disputeForm}>
                                             <h4>Open Dispute</h4>
                                            <div className="form-group">
                                                <label htmlFor="disputeReason" className="form-label">Reason for Dispute:</label>
                                                <textarea
                                                    id="disputeReason" value={disputeReason}
                                                    onChange={(e) => setDisputeReason(e.target.value)}
                                                    required aria-required="true"
                                                    className="form-textarea" rows={4} minLength={10}
                                                />
                                                 <small className="form-help-text">Please provide a clear reason.</small>
                                            </div>
                                            <button
                                                type="submit"
                                                disabled={actionLoading || !isPgpAuthenticated || !disputeReason.trim()}
                                                className="button button-danger"
                                            >
                                                {actionLoading ? <LoadingSpinner size="small" /> : 'Submit Dispute'}
                                            </button>
                                             <button type="button" onClick={() => setShowDisputeForm(false)} className="button button-secondary ml-2">Cancel</button>
                                        </form>
                                    )}
                                </div>
                            )}

                             {/* No Actions Available Message */}
                             {!canMarkShipped && !canPrepareRelease && !unsignedTxData && !canOpenDispute && orderStatus !== ORDER_STATUS.FINALIZED && orderStatus !== ORDER_STATUS.DISPUTED && orderStatus !== ORDER_STATUS.DISPUTE_RESOLVED && !order.release_tx_broadcast_hash && (
                                 <p className="text-muted mt-3">No actions available for you at this time.</p>
                             )}

                        </section>

                        {/* TODO: Add Feedback Form */}
                        {/* {isBuyer && orderStatus === ORDER_STATUS.FINALIZED && !order.feedback_given && (
                            <section>
                                <h2 className={styles.sectionTitle}>Leave Feedback</h2>
                                <FeedbackForm orderId={order.id} onFeedbackSubmit={fetchOrderDetails} />
                            </section>
                        )} */}

                         {/* TODO: Add Dispute/Messages Section if status is Disputed */}
                         {/* {orderStatus === ORDER_STATUS.DISPUTED && <DisputeChat orderId={order.id} />} */}
                    </div>
                </div>

            </div>
        </Layout>
    );
}

// TODO: Create OrderDetail.module.css for specific layout styles (grid, columns, sections, roles, status etc.).
// TODO: Ensure utils/constants.js defines ORDER_STATUS map (e.g., { PENDING_PAYMENT: 'pending_payment', ... }).
// TODO: Ensure utils/formatters.js provides formatPrice (using Decimal.js) and formatDate.
// TODO: Verify API function names and request/response structures match the backend implementation.
// TODO: Implement PGP decryption for shipping info if required on the frontend.
// TODO: Implement FeedbackForm and DisputeChat components if needed.