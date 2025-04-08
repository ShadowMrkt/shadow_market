// frontend/pages/products/[slug].js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global classes, used CSS Module, shared formatters, SafeHtmlRenderer.
//           - Removed inline styles object.
//           - Applied global classes (.container, .card, .form-*, .button-*).
//           - Created ProductDetail.module.css for custom styles (grid, stockInfo, priceDisplay etc.).
//           - Replaced local formatPrice with shared formatPrice/formatCurrency.
//           - Added SafeHtmlRenderer for description rendering (with security notes).
//           - Refined state initialization, validation logic, and PGP auth checks.
//           - Maintained critical TODO for multi-currency shipping price dependency.
//           - Added revision history block.

import React, { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { Decimal } from 'decimal.js';
import { useAuth } from '../../context/AuthContext';
import { getProductDetail } from '../../utils/api';
import Layout from '../../components/Layout';
import { CURRENCY_SYMBOLS, SUPPORTED_CURRENCIES } from '../../utils/constants';
import { formatPrice, formatCurrency } from '../../utils/formatters'; // Use shared formatters
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { showErrorToast, showInfoToast } from '../../utils/notifications';
import styles from './ProductDetail.module.css'; // Import CSS Module

// Component to safely render description
// SECURITY: Assumes strong backend sanitization (e.g., allowing only safe tags like p, b, i, em, strong, br, ul, ol, li).
// Using dangerouslySetInnerHTML is inherently risky if sanitization is insufficient.
// Consider frontend sanitization library (like DOMPurify) for extra safety layer if needed.
const SafeHtmlRenderer = React.memo(({ htmlContent }) => {
    const createMarkup = useMemo(() => ({ __html: htmlContent || '' }), [htmlContent]);
    return <div dangerouslySetInnerHTML={createMarkup} />;
});
SafeHtmlRenderer.displayName = 'SafeHtmlRenderer'; // Add display name for React DevTools


export default function ProductDetailPage({ product: initialProduct, error: serverError }) {
    const router = useRouter();
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();

    // State for selections
    const [selectedCurrency, setSelectedCurrency] = useState('');
    const [quantity, setQuantity] = useState(1);
    const [selectedShipping, setSelectedShipping] = useState('');
    const [actionError, setActionError] = useState(''); // Client-side validation/action error

    // Initialize selections based on fetched product data
    useEffect(() => {
        if (initialProduct) {
            const defaultCurrency = initialProduct.accepted_currencies?.[0] || '';
            setSelectedCurrency(defaultCurrency);
            if (!initialProduct.is_digital && initialProduct.shipping_options?.length > 0) {
                setSelectedShipping(initialProduct.shipping_options[0].name || '');
            } else {
                 setSelectedShipping(''); // Reset shipping if digital or no options
            }
            setQuantity(1);
            setActionError('');
        }
    }, [initialProduct]);

    // Memoized calculation of current price based on selection
    const currentPriceInfo = useMemo(() => {
        if (!initialProduct || !selectedCurrency) return { price: 'N/A', formatted: 'N/A', symbol: '' };
        const priceKey = `price_${selectedCurrency.toLowerCase()}`;
        const priceNative = initialProduct[priceKey];
        const symbol = CURRENCY_SYMBOLS[selectedCurrency] || selectedCurrency;
        // Use formatPrice for display-ready value
        const formatted = formatPrice(priceNative, selectedCurrency);
        return { price: priceNative, formatted, symbol };
    }, [initialProduct, selectedCurrency]);

     // --- Client-side Validation ---
    const validateSelection = useCallback(() => {
        setActionError('');
        const qtyNum = Number(quantity); // Use Number() for potentially non-integer inputs initially
        if (isNaN(qtyNum) || !Number.isInteger(qtyNum) || qtyNum < 1) {
            setActionError("Invalid quantity: must be a whole number greater than 0."); return false;
        }
        // Check against available stock only if it's a number (not null)
        if (typeof initialProduct.quantity_available === 'number' && qtyNum > initialProduct.quantity_available) {
            setActionError(`Quantity exceeds available stock (${initialProduct.quantity_available}).`); return false;
        }
        if (!selectedCurrency || !initialProduct.accepted_currencies?.includes(selectedCurrency)) {
            setActionError("Please select a valid currency."); return false;
        }
        if (!initialProduct.is_digital && !selectedShipping) {
            setActionError("Please select a shipping option."); return false;
        }
        return true;
    }, [quantity, selectedCurrency, selectedShipping, initialProduct]);

    // Handle Proceed to Checkout action
    const handleProceedToCheckout = useCallback(() => {
        setActionError('');
        if (!user) {
            showErrorToast("Please login first.");
            router.push(`/login?next=${encodeURIComponent(router.asPath)}`);
            return;
        }
        if (!isPgpAuthenticated) {
            setActionError("PGP authenticated session required to proceed to checkout. Please re-login.");
            showErrorToast("PGP session required.");
            return;
        }
        if (!validateSelection()) {
            return; // Stop if client validation fails
        }

        // Build query parameters for checkout page
        const checkoutParams = {
            productId: initialProduct.id,
            qty: quantity,
            currency: selectedCurrency,
            ...(selectedShipping && { shipping: selectedShipping }),
        };
        const queryString = new URLSearchParams(checkoutParams).toString();
        router.push(`/checkout?${queryString}`);
    }, [user, isPgpAuthenticated, initialProduct, quantity, selectedCurrency, selectedShipping, router, validateSelection]);

    // --- Render Logic ---
    if (serverError) {
        // Note: `getServerSideProps` handles the 404 case by returning { notFound: true }
        return <Layout><div className="container-narrow"><FormError message={serverError.message || "Error loading product details."} /><p className="mt-3 text-center"><Link href="/products" className="button button-secondary">Back to Products</Link></p></div></Layout>;
    }
    // Should not happen if getServerSideProps is correct, but good fallback
    if (!initialProduct) {
        return <Layout><div className="container text-center p-5"><LoadingSpinner message="Loading product data..." /></div></Layout>;
    }

    // Determine stock status class
    const getStockClass = () => {
        if (initialProduct.quantity_available === null) return styles.stockInfoUnlimited;
        if (initialProduct.quantity_available <= 0) return styles.stockInfoOut;
        if (initialProduct.quantity_available <= 10) return styles.stockInfoLow; // Threshold for "low stock"
        return styles.stockInfoIn; // Default "in stock"
    };
    const stockClass = getStockClass();
    const stockText = initialProduct.quantity_available === null ? 'Unlimited Stock' : (initialProduct.quantity_available > 0 ? `${initialProduct.quantity_available} Available` : 'Out of Stock');

    const isCheckoutDisabled = authIsLoading || !user || !isPgpAuthenticated || initialProduct.quantity_available === 0; // Disable if out of stock
    const checkoutButtonTitle = !user ? "Login required" : (!isPgpAuthenticated ? "PGP Session Required" : (initialProduct.quantity_available === 0 ? "Out of Stock" : "Proceed to checkout"));


    // Helper to get shipping price string for dropdown display (using fallback)
    const getShippingOptionDisplayPrice = (opt) => {
         // TODO CRITICAL: Shipping price MUST be available in the selected currency from the backend API.
         // This display uses the same potentially inaccurate fallback logic as the checkout page.
        const priceKey = `price_${selectedCurrency?.toLowerCase()}`;
        let price = opt?.[priceKey];
        if (price === undefined || price === null) {
             price = opt?.price_xmr; // Example fallback
        }
        return formatCurrency(price, selectedCurrency || initialProduct.accepted_currencies?.[0] || 'XMR'); // Format with selected currency
    };

    return (
        <Layout>
            <div className="container"> {/* Use standard container */}
                <nav aria-label="breadcrumb" className={styles.breadcrumb}>
                     <Link href="/products">Products</Link>
                     {initialProduct.category && (
                         <> / <Link href={`/products?category=${initialProduct.category.slug}`}>{initialProduct.category.name}</Link></>
                     )}
                     / {initialProduct.name}
                </nav>

                <div className={styles.mainGrid}>
                    {/* Left Column: Image & Description */}
                    <div>
                         {/* TODO: Replace with actual Image component (e.g., next/image) */}
                         <div className={styles.imagePlaceholder} role="img" aria-label={`Placeholder image for ${initialProduct.name}`}>
                             <span>Product Image Placeholder</span>
                         </div>

                        <section className={`card ${styles.detailsSection}`}> {/* Use global card class */}
                             <h1 className={styles.title}>{initialProduct.name}</h1>
                             <div className={styles.metaInfo}>
                                 <span>Sold by: <Link href={`/vendors/${initialProduct.vendor?.username}`} className={styles.vendorLink}>{initialProduct.vendor?.username || 'N/A'}</Link></span>
                                 {initialProduct.category && <span> in <Link href={`/products?category=${initialProduct.category.slug}`} className={styles.categoryLink}>{initialProduct.category.name}</Link></span>}
                             </div>

                            <p className={`${styles.stockInfo} ${stockClass}`}>
                                Stock: {stockText}
                            </p>

                            <div className={styles.description}>
                                 <h2 className={styles.sectionHeader}>Description</h2>
                                 <SafeHtmlRenderer htmlContent={initialProduct.description} />
                             </div>
                         </section>
                    </div>

                    {/* Right Column: Actions & Details */}
                    <section className={`card ${styles.actionsSection}`}> {/* Use global card class */}
                         <h2 className={styles.sectionHeader}>Purchase Options</h2>

                         <div className={styles.priceDisplay}>
                              {currentPriceInfo.formatted !== 'N/A'
                                  ? <>{currentPriceInfo.symbol} {currentPriceInfo.formatted}</>
                                  : 'Price not available'
                              }
                              {initialProduct.accepted_currencies?.length > 1 && <span className={styles.priceUnit}> per item</span>}
                         </div>

                         <div className={`form-group ${styles.selectionGroup}`}>
                             <label htmlFor="currency" className="form-label">Currency:</label>
                             <select id="currency" value={selectedCurrency} onChange={(e) => setSelectedCurrency(e.target.value)} className="form-select">
                                  {initialProduct.accepted_currencies?.map(curr => (
                                      <option key={curr} value={curr}>{curr} ({CURRENCY_SYMBOLS[curr] || ''})</option>
                                  ))}
                             </select>
                              {!selectedCurrency && initialProduct.accepted_currencies?.length > 0 && <FormError message="Select a currency"/>}
                         </div>

                         <div className={`form-group ${styles.selectionGroup}`}>
                             <label htmlFor="quantity" className="form-label">Quantity:</label>
                             <input
                                 type="number" id="quantity" value={quantity}
                                 onChange={(e) => setQuantity(e.target.value ? Math.max(1, parseInt(e.target.value, 10)) : 1)} // Ensure positive integer
                                 min="1"
                                 max={initialProduct.quantity_available ?? undefined} // Use undefined if null
                                 required
                                 className={`form-input ${styles.quantityInput}`}
                                 disabled={initialProduct.quantity_available === 0} // Disable if out of stock
                             />
                              {initialProduct.quantity_available !== null && <span className="form-help-text ms-2">({initialProduct.quantity_available} available)</span>}
                         </div>

                         {!initialProduct.is_digital && (
                              <div className={`form-group ${styles.selectionGroup}`}>
                                   <label htmlFor="shipping" className="form-label">Shipping Option:</label>
                                   <select id="shipping" value={selectedShipping} onChange={(e) => setSelectedShipping(e.target.value)} required className="form-select">
                                       <option value="">-- Select Shipping --</option>
                                        {initialProduct.shipping_options?.map(opt => (
                                           <option key={opt.name} value={opt.name}>
                                               {opt.name} (+ {getShippingOptionDisplayPrice(opt)}) {/* Display tentative price */}
                                           </option>
                                        ))}
                                   </select>
                                    {!selectedShipping && <FormError message="Select a shipping method"/>}
                               </div>
                          )}

                         <FormError message={actionError} />

                          {!isPgpAuthenticated && !authIsLoading && (
                              <div className={styles.pgpWarning}>
                                  PGP authenticated session required to checkout. Please <Link href="/login" className={styles.pgpWarningLink}>re-login</Link>.
                              </div>
                          )}

                         <button
                              onClick={handleProceedToCheckout}
                              disabled={isCheckoutDisabled}
                              className={`button button-primary w-100 mt-3 ${isCheckoutDisabled ? 'disabled' : ''}`}
                              title={checkoutButtonTitle}
                         >
                              Proceed to Checkout
                          </button>
                     </section>
                </div>
            </div>
        </Layout>
    );
}


// --- getServerSideProps ---
// Keep existing getServerSideProps logic from the provided code.
// Ensure it handles 'not found' and errors correctly by returning
// { notFound: true } or { props: { error: { message: ... } } }
export async function getServerSideProps(context) {
    const { slug } = context.params;
    try {
        const product = await getProductDetail(slug);
        if (!product) {
            return { notFound: true }; // Use Next.js built-in 404 handling
        }
        return { props: { product } };
    } catch (error) {
        console.error(`[getServerSideProps Error] Fetching product ${slug}:`, error);
        // Pass error message to the page component
        return { props: { product: null, error: { message: error.message || 'Failed to load product details from server.' } } };
    }
}