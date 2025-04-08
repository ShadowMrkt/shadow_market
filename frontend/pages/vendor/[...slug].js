// frontend/pages/vendor/[...slug].js
// <<< REVISED FOR ENTERPRISE GRADE: Clearer Edit/Create Modes, Multi-Currency UI, Validation Feedback, Shipping JSON UX Note >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
// <<< UPDATED: Import necessary API calls, components, constants >>>
import { getCategories, getProductDetail, createProduct, updateProduct } from '../../utils/api';
import Layout from '../../components/Layout';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { SUPPORTED_CURRENCIES, CURRENCY_SYMBOLS } from '../../utils/constants';
import { showSuccessToast, showErrorToast, showInfoToast } from '../../utils/notifications';

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '900px', margin: '2rem auto', padding: '1rem' },
    title: { marginBottom: '1.5rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' },
    formSection: { background: '#ffffff', padding: '1.5rem 2rem', borderRadius: '8px', border: '1px solid #dee2e6', marginBottom: '2rem', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }, // Use global .card?
    sectionTitle: { marginTop: '0', marginBottom: '1.5rem', fontSize: '1.2em', fontWeight: 'bold' },
    loadingText: { textAlign: 'center', padding: '2rem', fontStyle: 'italic', color: '#666' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' }, // Use global .warning-message
    priceGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '1rem' },
    shippingJsonWarning: { fontSize: '0.9em', fontStyle: 'italic', color: '#dc3545', marginTop: '0.5rem' },
    // Use global form/button classes (.form-group, .form-label, .form-input, .form-select, .form-textarea, .form-check, .button, .button-primary, .disabled etc.)
};

// Initial empty form state structure
const initialFormData = {
    name: '',
    category: '', // Store category slug
    description: '',
    quantity_available: null, // Use null for unlimited
    is_digital: false,
    shipping_options_json: '[]', // Default to empty JSON array string
    status: 'active', // Default status
    // Prices - dynamically generated keys
    // price_xmr: '', price_btc: '', price_eth: '', ...
    accepted_currencies: [], // Array of currency codes
};
// Dynamically add price keys for supported currencies
SUPPORTED_CURRENCIES.forEach(curr => {
    initialFormData[`price_${curr.toLowerCase()}`] = '';
});


export default function ProductEditCreatePage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();
    const { slug } = router.query; // Slug array from [...slug].js

    const editMode = slug && slug[0] === 'edit' && slug[1];
    const productSlug = editMode ? slug[1] : null;

    // State
    const [formData, setFormData] = useState(initialFormData);
    const [categories, setCategories] = useState([]);
    const [isLoadingData, setIsLoadingData] = useState(true); // Loading categories or product details
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState(''); // General form/API error

    // Fetch Categories and Product Data (if editing)
    useEffect(() => {
        const fetchData = async () => {
            // <<< Guard: Require login, vendor status, and PGP auth early >>>
             if (authIsLoading) return; // Wait for auth check
             if (!user) { router.push('/login?next=' + router.asPath); return; }
             if (!user.is_vendor) { showErrorToast("Access denied."); router.push('/profile'); return; }
             // PGP auth check happens before save, allow viewing form without it for now.

            setIsLoadingData(true); setError('');
            let productData = null;
            let fetchedCategories = [];

            try {
                // Fetch Categories (always needed)
                const catResponse = await getCategories({ limit: 200 }); // Fetch all
                fetchedCategories = catResponse.results || [];
                setCategories(fetchedCategories);

                // Fetch Product details only if in edit mode
                if (editMode && productSlug) {
                    // <<< SECURITY: Backend API must verify vendor ownership of this product >>>
                    productData = await getProductDetail(productSlug);
                     if (!productData) throw new Error("Product not found or you don't have permission to edit it."); // Check if product exists/accessible
                     // <<< Initialize form state with fetched product data >>>
                     setFormData({
                        name: productData.name || '',
                        category: productData.category?.slug || '', // Use slug
                        description: productData.description || '',
                        quantity_available: productData.quantity_available, // Keep null if unlimited
                        is_digital: productData.is_digital || false,
                        shipping_options_json: JSON.stringify(productData.shipping_options || [], null, 2), // Pretty print JSON
                        status: productData.status || 'active',
                        accepted_currencies: productData.accepted_currencies || [],
                        // Dynamically set prices
                         ...SUPPORTED_CURRENCIES.reduce((acc, curr) => {
                             const priceKey = `price_${curr.toLowerCase()}`;
                             acc[priceKey] = productData[priceKey] !== null && productData[priceKey] !== undefined ? String(productData[priceKey]) : '';
                             return acc;
                         }, {}),
                     });
                } else {
                    // Reset form for create mode (ensure initial state is clean)
                    setFormData(initialFormData);
                }
            } catch (err) {
                console.error("Failed to load data for product form:", err);
                setError(err.message || "Could not load necessary data. Please try again.");
                showErrorToast(err.message || "Failed to load data.");
                // If loading product failed in edit mode, maybe redirect or show persistent error
                 if (editMode) setFormData(initialFormData); // Reset form on error?
            } finally {
                setIsLoadingData(false);
            }
        };

        if (router.isReady) { // Ensure router query params are available
             fetchData();
        }

    }, [router.isReady, productSlug, editMode, authIsLoading, user, router]); // Dependencies for fetching


    // --- Handlers ---
    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setError(''); // Clear error on change

        if (type === 'checkbox') {
             // Handle 'accepted_currencies' checkboxes
             if (name === 'accepted_currencies') {
                const currentCurrencies = formData.accepted_currencies || [];
                if (checked) {
                    setFormData(prev => ({ ...prev, accepted_currencies: [...currentCurrencies, value] }));
                } else {
                    setFormData(prev => ({ ...prev, accepted_currencies: currentCurrencies.filter(curr => curr !== value) }));
                }
             } else { // Handle other checkboxes like 'is_digital'
                 setFormData(prev => ({ ...prev, [name]: checked }));
             }
         } else if (name === 'quantity_available') {
             // Allow empty string for null (unlimited), otherwise parse as int
             const numValue = value === '' ? null : parseInt(value, 10);
             if (value === '' || (!isNaN(numValue) && numValue >= 0)) {
                 setFormData(prev => ({ ...prev, [name]: numValue }));
             } else if (isNaN(numValue)) {
                  // Handle potential non-numeric input gracefully, maybe show a hint or ignore
                  console.warn("Ignoring non-numeric input for quantity.");
             }
         } else {
             // Handle regular inputs (text, number, select, textarea)
            setFormData(prev => ({ ...prev, [name]: value }));
        }
    };

    // Basic JSON validation for shipping options
    const validateShippingJson = () => {
         if (formData.is_digital) return true; // No validation needed if digital
         try {
             const parsed = JSON.parse(formData.shipping_options_json);
             if (!Array.isArray(parsed)) {
                 setError("Shipping Options must be a valid JSON array (e.g., [{\"name\": \"Standard\", \"price_xmr\": \"0.05\"}] )");
                 return false;
             }
             // <<< TODO: Add deeper validation? Check if objects have 'name' and price keys? >>>
             return true;
         } catch (e) {
             setError("Invalid JSON format in Shipping Options. Please check syntax.");
             return false;
         }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors

        // <<< BEST PRACTICE: Re-check PGP Auth status just before saving >>>
        if (!isPgpAuthenticated) {
             showErrorToast("PGP authenticated session required to save product.");
             setError("PGP session required.");
             return;
        }

        if (!validateShippingJson()) return; // Validate shipping JSON format

        // <<< SECURITY: Backend MUST sanitize description and validate ALL fields >>>
        const payload = { ...formData };
        // Ensure quantity is number or null
        payload.quantity_available = (payload.quantity_available === '' || payload.quantity_available === null) ? null : Number(payload.quantity_available);
        // Ensure prices are numbers or null/empty string (backend should handle conversion/validation)
        SUPPORTED_CURRENCIES.forEach(curr => {
             const priceKey = `price_${curr.toLowerCase()}`;
             if (payload[priceKey] === '') payload[priceKey] = null; // Send null if empty
             // Consider adding client-side numeric validation for prices too
         });

        setIsSaving(true);
        try {
            let savedProduct;
            if (editMode) {
                // <<< SECURITY: Backend must verify ownership before update >>>
                savedProduct = await updateProduct(productSlug, payload);
                showSuccessToast(`Product "${savedProduct.name}" updated successfully!`);
            } else {
                savedProduct = await createProduct(payload);
                showSuccessToast(`Product "${savedProduct.name}" created successfully!`);
            }
             // Redirect to the updated/new product's detail page or vendor products list
            // Using slug is better for SEO/readability if available on response
            router.push(`/products/${savedProduct.slug || savedProduct.id}`); // Fallback to ID if slug not returned immediately

        } catch (err) {
            console.error("Save product failed:", err);
             let errorMsg = err.message || `Failed to ${editMode ? 'update' : 'create'} product.`;
             // <<< Attempt to parse specific DRF validation errors >>>
             if (err.status === 400 && err.data) {
                 const fieldErrors = Object.entries(err.data)
                     .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(' ') : messages}`)
                     .join('; ');
                 if (fieldErrors) {
                     errorMsg = `Validation Error: ${fieldErrors}`;
                 } else if (err.data.detail) {
                     errorMsg = err.data.detail;
                 }
             }
            setError(errorMsg);
            showErrorToast(`Save failed: ${errorMsg.substring(0, 100)}${errorMsg.length > 100 ? '...' : ''}`);
        } finally {
            setIsSaving(false);
        }
    };


    // --- Render Logic ---
    if (authIsLoading || isLoadingData) return <Layout><div style={styles.loadingText}><LoadingSpinner message={`Loading ${editMode ? 'product details' : 'form'}...`} /></div></Layout>;
    // Handle case where user check finished but no user or not vendor
    if (!user || !user.is_vendor) return <Layout><div style={styles.loadingText}>Access Denied. Redirecting...</div></Layout>;
    // Handle case where loading finished but data fetch failed (error state is set)
     if (!isLoadingData && error && !formData.name) { // Check if form is still empty after error
         return <Layout><div style={styles.container}><FormError message={error} /><p><Link href="/vendor/dashboard">Back to Dashboard</Link></p></div></Layout>;
     }

     // Determine if save button should be disabled
     const isSaveDisabled = isSaving || !isPgpAuthenticated;

    return (
        <Layout>
            <div style={styles.container}>
                 <h1 style={styles.title}>{editMode ? `Edit Product: ${formData.name}` : 'Create New Product'}</h1>

                 {/* PGP Auth Warning */}
                 {!isPgpAuthenticated && (
                     <div style={styles.authWarning} className="warning-message">
                         <strong>Security Notice:</strong> Your session is not PGP authenticated. You cannot save changes without completing the PGP login challenge. Please <Link href="/login" style={{fontWeight:'bold'}}>re-login</Link> if needed. The Save button is disabled.
                     </div>
                 )}

                 <FormError message={error} />

                 <form onSubmit={handleSubmit}>
                    {/* Basic Info Section */}
                    <div style={styles.formSection} className="card mb-4">
                         <h2 style={styles.sectionTitle}>Basic Information</h2>
                         <div className="form-group mb-3">
                             <label htmlFor="name" className="form-label">Product Name*</label>
                             <input type="text" id="name" name="name" value={formData.name} onChange={handleChange} required className="form-input" disabled={isSaving}/>
                         </div>
                         <div className="form-group mb-3">
                             <label htmlFor="category" className="form-label">Category*</label>
                             <select id="category" name="category" value={formData.category} onChange={handleChange} required className="form-select" disabled={isSaving || isLoadingData}>
                                <option value="">-- Select Category --</option>
                                {categories.map(cat => <option key={cat.slug} value={cat.slug}>{cat.name}</option>)}
                             </select>
                         </div>
                         <div className="form-group mb-3">
                             <label htmlFor="description" className="form-label">Description*</label>
                             <textarea id="description" name="description" value={formData.description} onChange={handleChange} required className="form-textarea" rows={8} disabled={isSaving}></textarea>
                              <p className="form-help-text">Enter product description. Basic HTML allowed (e.g., &lt;b&gt;, &lt;p&gt;, &lt;br&gt;). Will be sanitized on save.</p>
                         </div>
                     </div>

                     {/* Pricing & Currency Section */}
                    <div style={styles.formSection} className="card mb-4">
                         <h2 style={styles.sectionTitle}>Pricing & Accepted Currencies</h2>
                         {/* <<< ADDED: Multi-currency price inputs >>> */}
                         <div style={styles.priceGrid} className="mb-3">
                            {SUPPORTED_CURRENCIES.map(curr => (
                                <div key={curr} className="form-group">
                                     <label htmlFor={`price_${curr.toLowerCase()}`} className="form-label">Price ({curr})</label>
                                     <input
                                         type="number"
                                         step="any" // Allow decimals
                                         id={`price_${curr.toLowerCase()}`}
                                         name={`price_${curr.toLowerCase()}`}
                                         value={formData[`price_${curr.toLowerCase()}`]}
                                         onChange={handleChange}
                                         className="form-input"
                                         placeholder={`e.g., 1.25`}
                                         disabled={isSaving}
                                     />
                                </div>
                            ))}
                         </div>
                         <div className="form-group mb-3">
                             <label className="form-label d-block mb-2">Accepted Currencies*</label> {/* Ensure label clearly indicates mandatory selection */}
                            {SUPPORTED_CURRENCIES.map(curr => (
                                <div key={curr} className="form-check form-check-inline">
                                     <input
                                         className="form-check-input"
                                         type="checkbox"
                                         id={`accept_${curr.toLowerCase()}`}
                                         name="accepted_currencies"
                                         value={curr}
                                         checked={formData.accepted_currencies.includes(curr)}
                                         onChange={handleChange}
                                         disabled={isSaving}
                                     />
                                     <label className="form-check-label" htmlFor={`accept_${curr.toLowerCase()}`}>{curr}</label>
                                </div>
                            ))}
                             {formData.accepted_currencies.length === 0 && <FormError message="At least one currency must be accepted."/>} {/* Hint if none selected */}
                         </div>
                     </div>

                    {/* Inventory & Shipping Section */}
                    <div style={styles.formSection} className="card mb-4">
                         <h2 style={styles.sectionTitle}>Inventory & Shipping</h2>
                         <div className="form-group mb-3">
                             <label htmlFor="quantity_available" className="form-label">Quantity Available</label>
                             <input type="number" id="quantity_available" name="quantity_available" value={formData.quantity_available ?? ''} onChange={handleChange} className="form-input" min="0" disabled={isSaving}/>
                             <p className="form-help-text">Leave blank or 0 for unlimited stock.</p>
                         </div>
                         <div className="form-check mb-3">
                            <input className="form-check-input" type="checkbox" id="is_digital" name="is_digital" checked={formData.is_digital} onChange={handleChange} disabled={isSaving} />
                            <label className="form-check-label" htmlFor="is_digital">Digital Product (No Shipping Required)</label>
                         </div>
                          {/* Shipping options only if not digital */}
                          {!formData.is_digital && (
                             <div className="form-group mb-3">
                                 <label htmlFor="shipping_options_json" className="form-label">Shipping Options (JSON Format)*</label>
                                 <textarea id="shipping_options_json" name="shipping_options_json" value={formData.shipping_options_json} onChange={handleChange} required={!formData.is_digital} className="form-textarea" rows={6} disabled={isSaving}></textarea>
                                 <p className="form-help-text">Enter as JSON array, e.g., <code style={{fontSize:'0.85em'}}>[{'{'}"name": "Standard Int'l", "price_xmr": "0.05", "price_btc": "0.0001"{'}'}, {'{'}"name": "Express Domestic", "price_xmr": "0.1"{'}'}]</code>. Include price keys for *all* accepted currencies for each option.</p>
                                  {/* <<< ADDED: Warning about JSON UX >>> */}
                                  <p style={styles.shippingJsonWarning}>Note: JSON input is required for now. Ensure format is correct. A structured editor may be added later.</p>
                             </div>
                          )}
                     </div>

                    {/* Status Section */}
                    <div style={styles.formSection} className="card mb-4">
                         <h2 style={styles.sectionTitle}>Status</h2>
                         <div className="form-group">
                             <label htmlFor="status" className="form-label">Product Status*</label>
                             <select id="status" name="status" value={formData.status} onChange={handleChange} required className="form-select" disabled={isSaving}>
                                 <option value="active">Active (Visible to Buyers)</option>
                                 <option value="inactive">Inactive (Hidden)</option>
                                 {/* Add 'featured' if implemented */}
                                 {/* <option value="featured">Featured</option> */}
                             </select>
                         </div>
                     </div>

                    {/* Submit Button */}
                     <div className="d-flex justify-content-end gap-2">
                        <Link href="/vendor/products" className="button button-secondary" disabled={isSaving}>Cancel</Link>
                        <button type="submit" className={`button button-primary ${isSaveDisabled ? 'disabled' : ''}`} disabled={isSaveDisabled} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}>
                             {isSaving ? <LoadingSpinner size="1em"/> : (editMode ? 'Save Changes' : 'Create Product')}
                         </button>
                     </div>
                </form>
            </div>
        </Layout>
    );
}