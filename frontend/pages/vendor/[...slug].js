// frontend/pages/vendor/edit/[slug].js
// Handles /vendor/products/new AND /vendor/products/edit/[actual-slug]
// <<< REVISED FOR ENTERPRISE GRADE: v1.1 - Improved Shipping Options UX >>>
import React, { useState, useEffect, useCallback } from 'react'; // Added useCallback
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext';
import { getProductDetail, createProduct, updateProduct, getCategories } from '../../utils/api';
import Layout from '../../components/Layout';
import LoadingSpinner from '../../components/LoadingSpinner'; // Import LoadingSpinner
import FormError from '../../components/FormError';
import { SUPPORTED_CURRENCIES, CURRENCY_SYMBOLS } from '../../utils/constants';
import { showSuccessToast, showErrorToast, showInfoToast } from '../../utils/notifications';

// Styles (reuse/adapt)
const styles = {
    container: { maxWidth: '800px', margin: '2rem auto', padding: '2rem', border: '1px solid #ccc', borderRadius: '8px', background: '#f9f9f9' },
    title: { textAlign: 'center', marginBottom: '1.5rem' },
    formGroup: { marginBottom: '1rem' },
    label: { display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' },
    input: { width: '100%', padding: '0.8rem', border: '1px solid #ccc', borderRadius: '4px', boxSizing: 'border-box' },
    textarea: { width: '100%', padding: '0.8rem', border: '1px solid #ccc', borderRadius: '4px', minHeight: '150px' },
    checkboxGroup: { display: 'flex', gap: '1rem', flexWrap: 'wrap' },
    checkboxLabel: { marginRight: '0.5rem'},
    button: { padding: '1rem 2rem', background: '#28a745', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '1rem', marginTop: '1rem' },
    buttonDisabled: { background: '#ccc', cursor: 'not-allowed' },
    error: { color: 'red', marginTop: '1rem', textAlign: 'center', whiteSpace: 'pre-wrap' },
    helpText: { fontSize: '0.9em', color: '#666', marginTop: '0.25rem' },
    priceInputContainer: { display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }, // Added margin
    currencySymbol: { fontWeight: 'bold', minWidth: '60px', textAlign: 'right' }, // Align symbols
    shippingOptionRow: { display: 'flex', gap: '1rem', alignItems: 'flex-start', marginBottom: '1rem', paddingBottom: '1rem', borderBottom: '1px dashed #ddd' },
    shippingOptionInputs: { flexGrow: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem 1rem' }, // Grid layout for inputs
    removeButton: { padding: '0.5rem 0.8rem', background: '#dc3545', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '0.9em', alignSelf: 'center' },
    addButton: { padding: '0.5rem 1rem', background: '#007bff', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '0.9em', marginTop: '0.5rem' },
};

// Initial empty form state structure
const initialFormData = {
    name: '', description: '', category_id: '',
    price_xmr: '', price_btc: '', price_eth: '',
    accepted_currencies: ['XMR'],
    quantity: 1, ships_from: '', ships_to: '',
    // <<< UPDATED: Store shipping_options as an array >>>
    shipping_options: [],
    // <<< END UPDATE >>>
    is_active: true, is_featured: false,
};

// --- ADDED: Blank Shipping Option Structure ---
const blankShippingOption = () => ({
    name: '',
    price_xmr: '',
    price_btc: '',
    price_eth: '',
});
// --- END ADDED ---

// Component using the ProductForm fields logic
export default function ProductEditPage() {
    const { user, isVendor, isPgpAuthenticated, isLoading: authIsLoading } = useAuth(); // Corrected property name
    const router = useRouter();
    const { slug } = router.query; // Array: ['new'] or ['edit', 'actual-slug']

    const isNew = slug && slug[0] === 'new';
    const productSlug = !isNew && slug ? slug[1] : null; // Get actual slug if editing

    // State
    const [productData, setProductData] = useState(initialFormData);
    const [categories, setCategories] = useState([]);
    const [isLoadingData, setIsLoadingData] = useState(!isNew); // Load data if editing
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState('');

    // Redirects & Permissions Checks
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) {
                router.push('/login');
            } else if (!user.is_vendor) { // Check user object directly
                setError("Access Denied: You are not registered as a vendor.");
                setIsLoadingData(false);
            }
        }
    }, [user, authIsLoading, router]);

    // Fetch Categories
    useEffect(() => {
        if (user && user.is_vendor) {
             getCategories()
                 .then(res => setCategories(res?.results || [])) // Handle potential missing results
                 .catch(err => {
                     console.error("Failed to fetch categories:", err);
                     setError("Could not load categories for selection.");
                 });
        }
    }, [user]);

    // Fetch existing Product Data if editing
    useEffect(() => {
        if (productSlug && user && user.is_vendor) {
            setIsLoadingData(true);
            getProductDetail(productSlug)
                .then(data => {
                    if (data.vendor?.id !== user.id) {
                         setError("Access Denied: You do not own this product.");
                         setIsLoadingData(false); // Stop loading on permission error
                         return;
                    }
                    // Populate form state
                    setProductData({
                        name: data.name || '',
                        description: data.description || '',
                        category_id: data.category?.id || '',
                        price_xmr: data.price_xmr || '',
                        price_btc: data.price_btc || '',
                        price_eth: data.price_eth || '',
                        accepted_currencies: data.accepted_currencies || [],
                        quantity: data.quantity ?? 1,
                        ships_from: data.ships_from || '',
                        ships_to: data.ships_to || '',
                        // <<< UPDATED: Directly use the fetched array >>>
                        shipping_options: Array.isArray(data.shipping_options) ? data.shipping_options : [],
                        // <<< END UPDATE >>>
                        is_active: data.is_active !== undefined ? data.is_active : true,
                        is_featured: data.is_featured || false,
                    });
                })
                .catch(err => {
                    console.error(`Failed to fetch product ${productSlug}:`, err);
                    setError(err.message || "Could not load product data.");
                })
                .finally(() => {
                    setIsLoadingData(false);
                });
        } else if (isNew) {
            // Reset form if switching to create mode
            setProductData(initialFormData);
            setIsLoadingData(false); // Not loading if creating new
        }
    }, [productSlug, isNew, user]); // Dependencies


    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setError(''); // Clear general error on change

        if (type === 'checkbox') {
            if (name === 'accepted_currencies') {
                const currentValues = productData.accepted_currencies;
                if (checked) {
                    setProductData(prev => ({ ...prev, accepted_currencies: [...currentValues, value] }));
                } else {
                    setProductData(prev => ({ ...prev, accepted_currencies: currentValues.filter(curr => curr !== value) }));
                }
            } else {
                 setProductData(prev => ({ ...prev, [name]: checked }));
            }
        } else if (type === 'number') {
             // Allow empty string to represent null/unlimited for quantity
            const numValue = value === '' ? null : parseInt(value, 10);
            if (name === 'quantity' && (value === '' || (!isNaN(numValue) && numValue >= 0))) {
                 setProductData(prev => ({ ...prev, quantity: numValue }));
            } else if (name.startsWith('price_')) { // Handle price inputs
                 setProductData(prev => ({ ...prev, [name]: value })); // Store price as string
            } else if (name === 'quantity') {
                 // Ignore invalid quantity input? Or show error? For now, ignore.
                 console.warn("Ignoring non-numeric/negative input for quantity");
            }
        } else {
             setProductData(prev => ({ ...prev, [name]: value }));
        }
    };

    // --- ADDED: Shipping Option Handlers ---
    const handleShippingOptionChange = (index, field, value) => {
        const updatedOptions = [...productData.shipping_options];
        updatedOptions[index] = { ...updatedOptions[index], [field]: value };
        setProductData(prev => ({ ...prev, shipping_options: updatedOptions }));
    };

    const handleAddShippingOption = () => {
        setProductData(prev => ({
            ...prev,
            shipping_options: [...prev.shipping_options, blankShippingOption()]
        }));
    };

    const handleRemoveShippingOption = (index) => {
        setProductData(prev => ({
            ...prev,
            shipping_options: prev.shipping_options.filter((_, i) => i !== index)
        }));
    };
    // --- END ADDED ---


    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (!isPgpAuthenticated) {
             setError("PGP authenticated session required to save products.");
             showErrorToast("PGP authenticated session required.");
             return;
        }

        // Basic client-side validation (can be enhanced)
        if (!productData.category_id) { setError("Please select a category."); return; }
        if (!productData.accepted_currencies || productData.accepted_currencies.length === 0) { setError("Please select at least one accepted currency."); return; }
        let priceSet = productData.accepted_currencies.some(curr => {
             const priceKey = `price_${curr.toLowerCase()}`;
             return productData[priceKey] && parseFloat(productData[priceKey]) >= 0;
        });
        if (!priceSet) { setError("Please set a valid, non-negative price for at least one accepted currency."); return; }

        // --- REMOVED: JSON.parse validation for shipping_options ---
        // let shippingOptionsParsed = productData.shipping_options; // Use the array directly

        setIsSubmitting(true);
        const payload = {
             ...productData,
             // Convert quantity only if not null
             quantity: productData.quantity === null ? null : Number(productData.quantity),
             // Ensure prices are sent as null if empty string, otherwise keep as string for API
             price_xmr: productData.price_xmr || null,
             price_btc: productData.price_btc || null,
             price_eth: productData.price_eth || null,
             // --- UPDATED: Send the shipping_options array directly ---
             shipping_options: productData.shipping_options,
        };

        try {
            let savedProduct;
            if (isNew) {
                savedProduct = await createProduct(payload);
                showSuccessToast(`Product "${savedProduct.name}" created successfully!`);
            } else {
                // <<< SECURITY: Backend must verify ownership before update >>>
                savedProduct = await updateProduct(productSlug, payload);
                showSuccessToast(`Product "${savedProduct.name}" updated successfully!`);
            }
            console.log("Saved product:", savedProduct);
            // Redirect after save
            router.push(`/products/${savedProduct.slug || savedProduct.id}`);

        } catch (err) {
             console.error("Save product failed:", err);
             let errorMsg = err.message || `Failed to ${isNew ? 'create' : 'update'} product.`;
             if (err.status === 400 && err.data) {
                 const fieldErrors = Object.entries(err.data)
                     .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(' ') : messages}`)
                     .join('\n');
                 if (fieldErrors) { errorMsg = `Validation Error(s):\n${fieldErrors}`; }
                 else if (err.data.detail) { errorMsg = err.data.detail; }
             }
            setError(errorMsg);
            showErrorToast(`Save failed: ${errorMsg.substring(0, 100)}${errorMsg.length > 100 ? '...' : ''}`);
            setIsSubmitting(false); // Only stop submitting on error
        }
        // Don't set isSubmitting false here if redirecting on success
    };


    // --- Render Logic ---
    if (authIsLoading || isLoadingData) return <Layout><div style={{textAlign:'center', padding:'2rem'}}><LoadingSpinner message={`Loading ${isNew ? 'form' : 'product details'}...`} /></div></Layout>;
    if (!user?.is_vendor) return <Layout><div className="container"><p style={styles.error}>{error || "Access Denied."}</p></div></Layout>;


    return (
        <Layout>
            <div style={styles.container}>
                <h1 style={styles.title}>{isNew ? 'Create New Product' : `Edit Product: ${productData.name || '...'}`}</h1>

                 {!isPgpAuthenticated && (
                     <p style={styles.error} className="alert alert-warning">
                         PGP authenticated session required to save changes. Please <Link href="/login">re-login</Link>.
                     </p>
                 )}

                <FormError message={error} /> {/* Display general form error */}

                <form onSubmit={handleSubmit}>
                    {/* Basic Info */}
                    <div style={styles.formGroup}>
                        <label htmlFor="name" style={styles.label}>Product Name*</label>
                        <input type="text" name="name" id="name" value={productData.name} onChange={handleChange} required style={styles.input} maxLength={255} disabled={isSubmitting || !isPgpAuthenticated}/>
                    </div>
                    <div style={styles.formGroup}>
                         <label htmlFor="category_id" style={styles.label}>Category*</label>
                         <select name="category_id" id="category_id" value={productData.category_id} onChange={handleChange} required style={{...styles.input, appearance:'auto'}} disabled={isSubmitting || !isPgpAuthenticated}>
                             <option value="">Select Category...</option>
                             {categories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                         </select>
                     </div>
                    <div style={styles.formGroup}>
                        <label htmlFor="description" style={styles.label}>Description*</label>
                        <textarea name="description" id="description" value={productData.description} onChange={handleChange} required style={styles.textarea} rows={10} disabled={isSubmitting || !isPgpAuthenticated}/>
                         <p style={styles.helpText}>Use Markdown for formatting. Basic HTML allowed: p, br, ul, ol, li, strong, em, b, i, u, h3-h5.</p>
                    </div>

                    {/* Pricing & Currency */}
                     <div style={styles.formGroup}>
                         <label style={styles.label}>Accepted Currencies*</label>
                         <div style={styles.checkboxGroup}>
                            {SUPPORTED_CURRENCIES.map(curr => (
                                <label key={curr} style={styles.checkboxLabel}>
                                     <input
                                         type="checkbox"
                                         name="accepted_currencies"
                                         value={curr}
                                         checked={productData.accepted_currencies.includes(curr)}
                                         onChange={handleChange}
                                         disabled={isSubmitting || !isPgpAuthenticated}
                                         style={{marginRight:'0.3rem'}}
                                     />
                                     {curr}
                                </label>
                            ))}
                         </div>
                     </div>
                      <div style={styles.formGroup}>
                         <label style={styles.label}>Prices (Enter for accepted currencies)</label>
                         {SUPPORTED_CURRENCIES.map(curr => (
                             <div style={styles.priceInputContainer} key={curr}>
                                   <span style={styles.currencySymbol}>{curr} ({CURRENCY_SYMBOLS[curr]})</span>
                                   <input
                                      type="number" // Use number for better mobile UX, but handle validation carefully
                                      name={`price_${curr.toLowerCase()}`}
                                      value={productData[`price_${curr.toLowerCase()}`]}
                                      onChange={handleChange}
                                      style={styles.input}
                                      step="any" // Allows decimals appropriate for crypto
                                      min="0"
                                      placeholder={`e.g., ${curr === 'BTC' ? '0.005' : (curr === 'ETH' ? '0.1' : '1.25')}`}
                                      disabled={isSubmitting || !isPgpAuthenticated || !productData.accepted_currencies.includes(curr)}
                                   />
                              </div>
                         ))}
                     </div>

                    {/* Inventory & Shipping */}
                     <div style={styles.formGroup}>
                         <label htmlFor="quantity" style={styles.label}>Quantity Available</label>
                         <input type="number" name="quantity" id="quantity" value={productData.quantity ?? ''} onChange={handleChange} style={styles.input} min="0" step="1" placeholder="Leave blank for unlimited" disabled={isSubmitting || !isPgpAuthenticated}/>
                     </div>
                     <div style={styles.formGroup}>
                        <label style={styles.checkboxLabel}>
                             <input type="checkbox" name="is_digital" checked={productData.is_digital} onChange={handleChange} disabled={isSubmitting || !isPgpAuthenticated} style={{marginRight:'0.3rem'}}/>
                             Digital Product (No Shipping Required)
                         </label>
                     </div>

                     {/* Shipping Options (Only if not digital) */}
                     {!productData.is_digital && (
                         <div style={styles.formGroup}>
                            <label style={styles.label}>Shipping Options</label>
                            {productData.shipping_options.map((option, index) => (
                                <div key={index} style={styles.shippingOptionRow}>
                                    <div style={styles.shippingOptionInputs}>
                                        {/* Name Input */}
                                        <div className="form-group">
                                            <label htmlFor={`shipping_name_${index}`} className="form-label" style={{ fontSize: '0.9em' }}>Option Name*</label>
                                            <input
                                                type="text"
                                                id={`shipping_name_${index}`}
                                                value={option.name}
                                                onChange={(e) => handleShippingOptionChange(index, 'name', e.target.value)}
                                                required
                                                placeholder="e.g., Standard Int'l"
                                                style={styles.input}
                                                disabled={isSubmitting || !isPgpAuthenticated}
                                            />
                                        </div>
                                        {/* Placeholder to align grid */}
                                        <div></div>
                                        {/* Price Inputs */}
                                        {SUPPORTED_CURRENCIES.map(curr => (
                                            <div className="form-group" key={curr}>
                                                <label htmlFor={`shipping_price_${curr.toLowerCase()}_${index}`} className="form-label" style={{ fontSize: '0.9em' }}>Price ({curr})*</label>
                                                <input
                                                    type="number"
                                                    id={`shipping_price_${curr.toLowerCase()}_${index}`}
                                                    value={option[`price_${curr.toLowerCase()}`]}
                                                    onChange={(e) => handleShippingOptionChange(index, `price_${curr.toLowerCase()}`, e.target.value)}
                                                    required // Require price for each currency for simplicity, adjust if needed
                                                    step="any"
                                                    min="0"
                                                    placeholder="0.00"
                                                    style={styles.input}
                                                    disabled={isSubmitting || !isPgpAuthenticated}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveShippingOption(index)}
                                        style={styles.removeButton}
                                        disabled={isSubmitting || !isPgpAuthenticated}
                                        title="Remove Shipping Option"
                                    >
                                        &times; {/* Remove Symbol */}
                                    </button>
                                </div>
                            ))}
                            <button
                                type="button"
                                onClick={handleAddShippingOption}
                                style={styles.addButton}
                                disabled={isSubmitting || !isPgpAuthenticated}
                            >
                                + Add Shipping Option
                            </button>
                            <p style={styles.helpText}>Define shipping options available for this product. Ensure prices are set for all accepted currencies.</p>
                         </div>
                      )}

                     {/* Status */}
                     <div style={styles.formGroup}>
                        <label style={styles.label}>Status</label>
                         <label style={styles.checkboxLabel}>
                             <input type="checkbox" name="is_active" checked={productData.is_active} onChange={handleChange} disabled={isSubmitting || !isPgpAuthenticated} style={{marginRight:'0.3rem'}}/>
                             Active (Listed for sale)
                         </label>
                         <label style={styles.checkboxLabel}>
                             <input type="checkbox" name="is_featured" checked={productData.is_featured} onChange={handleChange} disabled={isSubmitting || !isPgpAuthenticated} style={{marginRight:'0.3rem'}}/>
                             Featured
                         </label>
                    </div>

                    <div className="d-flex justify-content-end gap-2">
                       <Link href="/vendor/products" className={`button button-secondary ${isSubmitting ? 'disabled' : ''}`}>Cancel</Link>
                       <button
                            type="submit"
                            disabled={isSubmitting || !isPgpAuthenticated}
                            style={{...styles.button, ...((isSubmitting || !isPgpAuthenticated) ? styles.buttonDisabled : {})}}
                        >
                            {isSubmitting ? <LoadingSpinner size="1em"/> : (isNew ? 'Create Product' : 'Update Product')}
                        </button>
                    </div>
                </form>
            </div>
        </Layout>
    );
}