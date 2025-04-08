// frontend/pages/checkout.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global classes, used CSS Module, shared formatters, refined logic.
//           - Removed inline styles object.
//           - Applied global classes (.container-narrow, .card, .warning-message, .form-*, .button-*).
//           - Created Checkout.module.css for custom styles (grid, summaryBox, etc.).
//           - Replaced local formatPrice with shared formatCurrency/formatPrice.
//           - Added clear TODO for multi-currency shipping price handling.
//           - Refined shipping/message encryption logic based on input type.
//           - Improved state management and error handling clarity.
//           - Added TODOs for component verification and address validation.
//           - Added revision history block.

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { Decimal } from 'decimal.js';
import { useAuth } from '../context/AuthContext';
import { getProductDetail, encryptShippingInfo, placeOrder } from '../utils/api';
import Layout from '../components/Layout';
import { CURRENCY_SYMBOLS, PGP_MESSAGE_BLOCK } from '../utils/constants'; // Added PGP constant
import { formatPrice, formatCurrency } from '../utils/formatters'; // Use shared formatters
import LoadingSpinner from '../components/LoadingSpinner';
import FormError from '../components/FormError';
import ShippingAddressForm from '../components/ShippingAddressForm'; // TODO: Verify component exists/props
import { showErrorToast, showSuccessToast, showInfoToast } from '../utils/notifications';
import styles from './Checkout.module.css'; // Import CSS Module for custom styles

// Decimal.js configuration (optional, if needed beyond default)
// Decimal.set({ precision: 18 });

export default function CheckoutPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // State
    const [product, setProduct] = useState(null);
    const [orderParams, setOrderParams] = useState({ productId: null, qty: 1, currency: '', shipping: '' });
    const [isLoadingProduct, setIsLoadingProduct] = useState(true);
    const [isProcessing, setIsProcessing] = useState(false); // Loading state for encryption/placement
    const [error, setError] = useState(''); // General page/form error

    // State for Shipping/Message Input
    const [inputType, setInputType] = useState('structured'); // 'structured' or 'pre_encrypted'
    const [shippingInfo, setShippingInfo] = useState({ /* initial empty state */ });
    const [buyerMessage, setBuyerMessage] = useState('');
    const [preEncryptedBlob, setPreEncryptedBlob] = useState('');

    // Fetch Product details
    const fetchProductData = useCallback(async (productId) => {
        if (!productId) { setError("Product ID missing."); setIsLoadingProduct(false); return; }
        setIsLoadingProduct(true); setError('');
        try {
            const data = await getProductDetail(productId);
            if (!data || !data.is_active) { // Ensure product exists and is active
                 throw new Error("Product not found or is currently unavailable.");
            }
            setProduct(data);
        } catch (err) {
            console.error("Fetch product failed:", err);
            setError(`Could not load product details: ${err.message}. Please go back and try again.`);
            setProduct(null);
        } finally { setIsLoadingProduct(false); }
    }, []);

    // Extract order params and fetch product
    useEffect(() => {
        if (router.isReady) {
            const { productId, qty, currency, shipping } = router.query;
            const parsedQty = parseInt(qty);
            if (!productId || !parsedQty || parsedQty < 1 || !currency) {
                setError("Invalid or missing order information in URL. Please start checkout again from the product page.");
                setIsLoadingProduct(false);
            } else {
                const params = { productId, qty: parsedQty, currency, shipping: shipping || '' };
                setOrderParams(params);
                // Reset product state before fetching new one if productId changes
                setProduct(null);
                fetchProductData(productId);
            }
        }
    }, [router.isReady, router.query, fetchProductData]);

    // Handle Auth checks
    useEffect(() => {
        if (!authIsLoading && !user) {
            router.push(`/login?next=${encodeURIComponent(router.asPath)}`);
        }
    }, [user, authIsLoading, router]);

    // Handler for structured shipping form changes
    const handleShippingChange = useCallback((e) => {
        setError(''); // Clear general error on input change
        setShippingInfo(prev => ({ ...prev, [e.target.name]: e.target.value }));
    }, []);

    // --- Main Handler to Place Order ---
    const handlePlaceOrder = async (e) => {
        if (e) e.preventDefault();
        setError(''); setIsProcessing(true);

        // Re-check critical conditions
        if (!isPgpAuthenticated) {
            setError("PGP authenticated session required. Please re-login.");
            showErrorToast("PGP session required."); setIsProcessing(false); return;
        }
        if (!product) {
            setError("Product data error. Please go back and try again.");
            showErrorToast("Product data missing."); setIsProcessing(false); return;
        }
        if (!orderParams.currency || !product.accepted_currencies?.includes(orderParams.currency)) {
            setError(`Selected currency (${orderParams.currency}) is invalid or not accepted for this product.`);
            showErrorToast('Invalid currency selected.'); setIsProcessing(false); return;
        }

        let finalEncryptedBlob = null;

        // Step 1: Prepare & Encrypt/Validate Shipping Info (if physical product)
        if (!product.is_digital) {
            showInfoToast("Processing shipping information...", { autoClose: 2000 });
            if (inputType === 'structured') {
                const requiredFields = ['recipient_name', 'street_address', 'city', 'postal_code', 'country'];
                const missingFields = requiredFields.filter(field => !shippingInfo[field]?.trim());
                if (missingFields.length > 0) {
                    setError(`Required shipping fields missing: ${missingFields.join(', ')}.`);
                    setIsProcessing(false); return;
                }
                // API Call: Pass structured data and optional message
                try {
                    // SECURITY: Backend encrypts using vendor's key. Message is included.
                    const encryptionResponse = await encryptShippingInfo(product.vendor.id, shippingInfo, buyerMessage.trim() || null, null); // Pass null for blob
                    finalEncryptedBlob = encryptionResponse.encrypted_blob;
                    if (!finalEncryptedBlob) throw new Error(encryptionResponse.error || "Server encryption response missing data.");
                } catch (err) {
                    console.error("Encryption failed:", err);
                    const errMsg = err.message || "Failed to encrypt shipping information.";
                    setError(errMsg); showErrorToast(errMsg); setIsProcessing(false); return;
                }
            } else if (inputType === 'pre_encrypted') {
                const blob = preEncryptedBlob.trim();
                // Use imported constants for validation
                if (!blob || !blob.startsWith(PGP_MESSAGE_BLOCK.BEGIN) || !blob.includes(PGP_MESSAGE_BLOCK.END)) {
                    setError(`Invalid PGP message format. Include full "${PGP_MESSAGE_BLOCK.BEGIN}" and "${PGP_MESSAGE_BLOCK.END}" markers.`);
                    setIsProcessing(false); return;
                }
                // API Call: Pass only the blob for validation/pass-through
                try {
                     // SECURITY: Backend should ideally validate if the blob is decryptable by the intended vendor key, if possible.
                    const validationResponse = await encryptShippingInfo(product.vendor.id, null, null, blob); // Pass null for structured data/message
                    finalEncryptedBlob = validationResponse.encrypted_blob; // Backend returns validated blob
                    if (!finalEncryptedBlob || !validationResponse.was_pre_encrypted) throw new Error(validationResponse.error || "Backend rejected pre-encrypted message.");
                } catch (err) {
                    console.error("Pre-encrypted validation failed:", err);
                    const errMsg = err.message || "Failed to validate pre-encrypted shipping information.";
                    setError(errMsg); showErrorToast(errMsg); setIsProcessing(false); return;
                }
            } else {
                 setError("Invalid input type selected for shipping."); setIsProcessing(false); return;
            }
            // Final check for physical goods - need encrypted blob
            if (!finalEncryptedBlob) { setError("Shipping information could not be processed."); setIsProcessing(false); return; }
        }
        // <<< End Step 1 >>>

        // Step 2: Prepare Final Order Payload
        const finalOrderData = {
            product_id: product.id,
            quantity: orderParams.qty,
            selected_currency: orderParams.currency,
            // Pass shipping option name if not digital
            shipping_option_name: product.is_digital ? null : (orderParams.shipping || null),
             // Pass encrypted blob if physical, null if digital
            encrypted_shipping_blob: product.is_digital ? null : finalEncryptedBlob,
             // Pass buyer message separately only if digital (assume backend encrypts if needed)
             // Or, if structured input was used, message is already in the blob via encryptShippingInfo.
             // If pre-encrypted, message MUST be inside the blob.
             buyer_message: product.is_digital ? (buyerMessage.trim() || null) : null,
        };

        // Step 3: Call placeOrder API
        showInfoToast("Placing order...", { autoClose: 3000 });
        try {
             // SECURITY: Backend MUST re-validate product availability, price, quantity, shipping options, currency etc. before creating order.
            const newOrder = await placeOrder(finalOrderData);
            showSuccessToast("Order placed successfully! Redirecting...");
            // Redirect using the returned order ID
            router.push(`/orders/${newOrder.id}`);
            // No need to setIsProcessing(false) due to redirect
        } catch (err) {
            console.error("Place order failed:", err);
            // Check for specific DRF validation errors
             const errorDetail = err.response?.data;
             let errMsg = err.message || "Failed to place order. An unknown error occurred.";
             if (typeof errorDetail === 'object' && errorDetail !== null) {
                 // Extract common errors
                 errMsg = errorDetail.detail || // General detail
                          errorDetail.non_field_errors?.[0] || // Non-field errors
                          errorDetail.quantity?.[0] || // Quantity error (e.g., stock)
                          errorDetail.selected_currency?.[0] || // Currency error
                          errorDetail.error || // Generic error field
                          JSON.stringify(errorDetail); // Fallback
             }
            setError(errMsg); showErrorToast(errMsg);
            setIsProcessing(false); // Set loading false only on error
        }
        // <<< End Step 3 >>>
    };

    // --- Render Logic ---
    if (authIsLoading || isLoadingProduct) {
         return <Layout><div className="text-center p-5"><LoadingSpinner message="Loading checkout..." /></div></Layout>;
    }
    if (!user && !authIsLoading) {
         return <Layout><div className="container text-center p-5">Redirecting to login...</div></Layout>;
    }
    // Display specific error if product loading failed or params invalid
    if (error && !product) {
         return <Layout><div className="container-narrow"><FormError message={error} /><p className="mt-3 text-center"><Link href="/products" className="button button-secondary">Back to Products</Link></p></div></Layout>;
    }
    if (!product) {
        return <Layout><div className="container text-center p-5">Product not found or failed to load.</div></Layout>; // Fallback
    }

    // Calculate prices for display using shared formatters
    const priceNative = product[`price_${orderParams.currency?.toLowerCase()}`];
    let shippingPriceNative = '0';
    let selectedShippingOptionObj = null;
    if (!product.is_digital && orderParams.shipping && product.shipping_options) {
         selectedShippingOptionObj = product.shipping_options.find(o => o.name === orderParams.shipping);
         // TODO CRITICAL: Shipping price MUST be available in the selected currency from the backend API.
         // The current fallback logic using only XMR price is likely INCORRECT.
         // Either the backend needs to provide price_btc, price_eth etc. for shipping,
         // or reliable client-side conversion based on up-to-date rates is needed (complex).
         shippingPriceNative = selectedShippingOptionObj?.[`price_${orderParams.currency?.toLowerCase()}`] || selectedShippingOptionObj?.price_xmr || '0';
         if (!selectedShippingOptionObj?.[`price_${orderParams.currency?.toLowerCase()}`] && selectedShippingOptionObj?.price_xmr) {
              console.warn(`Shipping price only found in XMR (${selectedShippingOptionObj.price_xmr}), using as estimate for ${orderParams.currency}. Accuracy NOT guaranteed.`);
         }
    }
    const subTotal = new Decimal(priceNative || '0').times(new Decimal(orderParams.qty || 1));
    const shippingCost = new Decimal(shippingPriceNative);
    const totalDecimal = subTotal.plus(shippingCost);
    const currencyCode = orderParams.currency;

    return (
        <Layout>
            {/* Use global container class */}
            <div className="container-narrow">
                <h1>Checkout</h1>

                 {!isPgpAuthenticated && (
                     <div className="warning-message mb-4"> {/* Use global class */}
                         <strong>Security Notice:</strong> Your session is not PGP authenticated. You must <Link href="/login" className="font-weight-bold">re-login</Link> and complete the PGP challenge before placing this order.
                     </div>
                 )}

                <div className={styles.grid}>
                     {/* Order Summary - Use global card class */}
                     <section className={`card ${styles.summaryBox}`}>
                         <h2 className={styles.sectionTitle}>Order Summary</h2>
                         <p><strong>Product:</strong> {product.name}</p>
                         <p><strong>Vendor:</strong> <Link href={`/vendors/${product.vendor?.username}`} className={styles.link}>{product.vendor?.username}</Link></p>
                         <p><strong>Quantity:</strong> {orderParams.qty}</p>
                         <p><strong>Currency:</strong> {currencyCode}</p>
                          {!product.is_digital && <p><strong>Shipping:</strong> {selectedShippingOptionObj?.name || orderParams.shipping || 'N/A'}</p>}
                         <hr className={styles.hr}/>
                         <p>Subtotal: {formatCurrency(subTotal, currencyCode)}</p>
                          {!product.is_digital && <p>Shipping: {formatCurrency(shippingCost, currencyCode)}</p> }
                          <p className={styles.totalPrice}>Total: {formatCurrency(totalDecimal, currencyCode)}</p>
                     </section>

                     {/* Shipping/Message Input Area - Use global card class */}
                     <section className={`card ${styles.shippingBox}`}>
                          <h2 className={styles.sectionTitle}>{product.is_digital ? 'Order Note (Optional)' : 'Shipping & Message'}</h2>
                          {!product.is_digital && (
                              <>
                                  {/* Input Type Selector */}
                                   <div className={`form-group ${styles.inputTypeSelector}`}>
                                       <label className={styles.radioLabel}>
                                           <input type="radio" name="inputType" value="structured" checked={inputType === 'structured'} onChange={(e) => setInputType(e.target.value)} disabled={isProcessing || !isPgpAuthenticated} />
                                           Enter Address Below (Server Encrypts)
                                       </label>
                                       <label className={styles.radioLabel}>
                                           <input type="radio" name="inputType" value="pre_encrypted" checked={inputType === 'pre_encrypted'} onChange={(e) => setInputType(e.target.value)} disabled={isProcessing || !isPgpAuthenticated}/>
                                           Paste PGP Message (You Encrypt)
                                       </label>
                                   </div>

                                   {/* Conditional Rendering based on inputType */}
                                   {inputType === 'structured' && (
                                       <>
                                           <p className="form-help-text mb-3">Enter shipping details. This information will be PGP encrypted for the vendor by our server.</p>
                                           {/* Assuming ShippingAddressForm uses global form styles */}
                                           <ShippingAddressForm
                                               formData={shippingInfo}
                                               onChange={handleShippingChange}
                                               disabled={isProcessing || !isPgpAuthenticated}
                                           />
                                            <div className="form-group mt-4">
                                                <label htmlFor="buyerMessage" className="form-label">Optional Message to Vendor</label>
                                                <textarea id="buyerMessage" name="buyerMessage" value={buyerMessage} onChange={(e) => setBuyerMessage(e.target.value)} className="form-textarea" rows={3} disabled={isProcessing || !isPgpAuthenticated} placeholder="(Encrypted with address)"></textarea>
                                            </div>
                                       </>
                                   )}

                                   {inputType === 'pre_encrypted' && (
                                        <div className="form-group">
                                            <label htmlFor="preEncryptedBlob" className="form-label">PGP Encrypted Message</label>
                                            <textarea id="preEncryptedBlob" name="preEncryptedBlob" value={preEncryptedBlob} onChange={(e) => setPreEncryptedBlob(e.target.value)} required className="form-textarea font-monospace" rows={12} placeholder={`Paste your full PGP message block (BEGIN/END markers included), encrypted for vendor ${product.vendor?.username}...`} disabled={isProcessing || !isPgpAuthenticated} aria-describedby="pgpBlobHelp"></textarea>
                                             <small id="pgpBlobHelp" className="form-help-text">Ensure this is encrypted ONLY for the vendor's PGP key found on their profile. Include all shipping details and any message inside.</small>
                                        </div>
                                   )}
                              </>
                          )}
                          {product.is_digital && (
                               <div className="form-group mt-4">
                                   <label htmlFor="buyerMessageDigital" className="form-label">Optional Message to Vendor</label>
                                   <textarea id="buyerMessageDigital" name="buyerMessageDigital" value={buyerMessage} onChange={(e) => setBuyerMessage(e.target.value)} className="form-textarea" rows={3} disabled={isProcessing || !isPgpAuthenticated} placeholder="(This message will be PGP encrypted by the server)"></textarea>
                                   {/* TODO: Confirm backend handles encrypting this message for digital goods if no shipping blob is sent */}
                               </div>
                          )}
                     </section>
                </div>

                {/* Display General Errors */}
                <FormError message={error} />

                 {/* Place Order Button */}
                 <div className={styles.submitButtonContainer}>
                     <button
                        onClick={handlePlaceOrder}
                        disabled={isProcessing || !product || !isPgpAuthenticated} // Simplified disabled check
                        className={`button button-success w-100 ${isProcessing || !product || !isPgpAuthenticated ? 'disabled' : ''}`} // Use global classes
                        title={!isPgpAuthenticated ? "PGP authenticated session required" : (!product ? "Product error" : "Place your order")}
                     >
                         {isProcessing ? <LoadingSpinner size="1em" /> : 'Confirm & Place Order'}
                     </button>
                 </div>
            </div>
        </Layout>
    );
}

// TODO: Create Checkout.module.css for .grid, .summaryBox, .shippingBox, .totalPrice, .inputTypeSelector, .radioLabel, .submitButtonContainer, .sectionTitle, .hr, .link styles.
// TODO: Verify/Implement ShippingAddressForm component and its props.
// TODO: Implement reliable client-side address format validation (e.g., using a library).
// TODO: Resolve the multi-currency shipping price issue (requires backend changes or complex client-side rate conversion).
// TODO: Confirm backend handling of buyer_message encryption for digital goods in placeOrder.