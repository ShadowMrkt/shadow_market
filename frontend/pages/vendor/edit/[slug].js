// frontend/pages/vendor/products/[...slug].js
// Handles /vendor/products/new AND /vendor/products/edit/[actual-slug]
import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '../../context/AuthContext';
import { getProductDetail, createProduct, updateProduct, getCategories } from '../../utils/api';
import Layout from '../../components/Layout';
import Link from 'next/link';

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
    priceInputContainer: { display: 'flex', alignItems: 'center', gap: '0.5rem' },
    currencySymbol: { fontWeight: 'bold'},
};

// Component using the ProductForm fields logic
export default function ProductEditPage() {
    const { user, isVendor, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();
    const { slug } = router.query; // Array: ['new'] or ['edit', 'actual-slug']

    const isNew = slug && slug[0] === 'new';
    const productSlug = !isNew && slug ? slug[1] : null; // Get actual slug if editing

    // State
    const [productData, setProductData] = useState({ // Matches backend ProductForm/Model fields
        name: '', description: '', category_id: '',
        price_xmr: '', price_btc: '', price_eth: '',
        accepted_currencies: ['XMR'], // Default XMR
        quantity: 1, ships_from: '', ships_to: '', shipping_options: '[]', // Store JSON as string in form state
        is_active: true, is_featured: false,
    });
    const [categories, setCategories] = useState([]);
    const [isLoadingData, setIsLoadingData] = useState(!isNew); // Load data if editing
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState('');

    // Redirects & Permissions Checks
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) {
                router.push('/login');
            } else if (!user.is_vendor) {
                setError("Access Denied: You are not registered as a vendor.");
                setIsLoadingData(false);
            }
        }
    }, [user, authIsLoading, router]);

    // Fetch Categories
    useEffect(() => {
        if (user && user.is_vendor) {
             getCategories()
                 .then(setCategories)
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
                    // Ensure vendor owns this product
                    if (data.vendor?.id !== user.id) {
                         setError("Access Denied: You do not own this product.");
                         return;
                    }
                    // Populate form state - ensure nulls become empty strings for inputs
                    // Format shipping options back to string
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
                        shipping_options: JSON.stringify(data.shipping_options || []),
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
        }
    }, [productSlug, user]); // Dependencies


    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        if (type === 'checkbox') {
            if (name === 'accepted_currencies') {
                // Handle multi-checkbox for currencies
                const currentValues = productData.accepted_currencies;
                if (checked) {
                    setProductData(prev => ({ ...prev, accepted_currencies: [...currentValues, value] }));
                } else {
                    setProductData(prev => ({ ...prev, accepted_currencies: currentValues.filter(curr => curr !== value) }));
                }
            } else {
                 // Handle single checkboxes (is_active, is_featured)
                 setProductData(prev => ({ ...prev, [name]: checked }));
            }
        } else if (type === 'number') {
             setProductData(prev => ({ ...prev, [name]: parseInt(value) || 0 }));
        }
        else {
             setProductData(prev => ({ ...prev, [name]: value }));
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (!isPgpAuthenticated) {
             setError("PGP authenticated session required to save products.");
             return;
        }

        // Basic client-side validation
        if (!productData.category_id) { setError("Please select a category."); return; }
        if (!productData.accepted_currencies || productData.accepted_currencies.length === 0) { setError("Please select at least one accepted currency."); return; }
        // Check if at least one price is set for an accepted currency
        let priceSet = false;
        if (productData.accepted_currencies.includes('XMR') && productData.price_xmr) priceSet = true;
        if (productData.accepted_currencies.includes('BTC') && productData.price_btc) priceSet = true;
        if (productData.accepted_currencies.includes('ETH') && productData.price_eth) priceSet = true;
        if (!priceSet) { setError("Please set a price for at least one accepted currency."); return; }

        // Validate JSON for shipping options
        let shippingOptionsParsed;
        try {
            shippingOptionsParsed = JSON.parse(productData.shipping_options || '[]');
             if (!Array.isArray(shippingOptionsParsed)) throw new Error("Not a list.");
            // Add deeper validation if needed
        } catch(err) {
             setError("Invalid JSON format for shipping options."); return;
        }


        setIsSubmitting(true);
        const payload = {
             ...productData,
             // Convert prices back to Decimal strings if needed, or ensure API handles strings
             price_xmr: productData.price_xmr || null,
             price_btc: productData.price_btc || null,
             price_eth: productData.price_eth || null,
             shipping_options: shippingOptionsParsed, // Send parsed list
        };

        try {
            let savedProduct;
            if (isNew) {
                savedProduct = await createProduct(payload);
                alert("Product created successfully!");
                router.push(`/vendor/products`); // Redirect to list after create
            } else {
                savedProduct = await updateProduct(productSlug, payload);
                alert("Product updated successfully!");
                 router.push(`/vendor/products`); // Redirect to list after update
            }
            console.log("Saved product:", savedProduct);

        } catch (err) {
             console.error("Save product failed:", err);
             if (typeof err.message === 'object' && err.message !== null) {
                const fieldErrors = Object.entries(err.message).map(([field, messages]) =>
                     `${field}: ${messages.join(', ')}`
                ).join('\n');
                 setError(`Save failed:\n${fieldErrors}`);
             } else {
                setError(err.message || "Failed to save product. Please try again.");
             }
              setIsSubmitting(false); // Only set false on error if not redirecting
        }
        // setIsSubmitting(false); // Dont set here if redirecting on success
    };


    // Render loading/error states or the form
    if (authIsLoading || isLoadingData) return <Layout><div>Loading...</div></Layout>;
    if (!user?.is_vendor) return <Layout><p style={styles.error}>{error || "Access Denied."}</p></Layout>;

    return (
        <Layout>
            <div style={styles.container}>
                <h1 style={styles.title}>{isNew ? 'Create New Product' : `Edit Product: ${productData.name}`}</h1>

                 {!isPgpAuthenticated && (
                     <p style={styles.error}>
                         PGP authenticated session required to save products. Please <Link href="/login">re-login</Link> and complete the PGP challenge.
                     </p>
                 )}

                <form onSubmit={handleSubmit}>
                    {/* Basic Info */}
                    <div style={styles.formGroup}>
                        <label htmlFor="name" style={styles.label}>Product Name</label>
                        <input type="text" name="name" id="name" value={productData.name} onChange={handleChange} required style={styles.input} maxLength={255} disabled={isSubmitting || !isPgpAuthenticated}/>
                    </div>
                    <div style={styles.formGroup}>
                         <label htmlFor="category_id" style={styles.label}>Category</label>
                         <select name="category_id" id="category_id" value={productData.category_id} onChange={handleChange} required style={styles.input} disabled={isSubmitting || !isPgpAuthenticated}>
                             <option value="">Select Category...</option>
                             {categories.map(cat => <option key={cat.id} value={cat.id}>{cat.name}</option>)}
                         </select>
                     </div>
                    <div style={styles.formGroup}>
                        <label htmlFor="description" style={styles.label}>Description</label>
                        <textarea name="description" id="description" value={productData.description} onChange={handleChange} required style={styles.textarea} rows={10} disabled={isSubmitting || !isPgpAuthenticated}/>
                         <p style={styles.helpText}>Use Markdown for formatting. Basic HTML allowed: p, br, ul, ol, li, strong, em, b, i, u, h3-h5.</p>
                    </div>

                    {/* Pricing & Currency */}
                     <div style={styles.formGroup}>
                         <label style={styles.label}>Accepted Currencies (Select all that apply)</label>
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
                          <div style={styles.priceInputContainer}>
                               <span style={styles.currencySymbol}>XMR ({CURRENCY_SYMBOLS.XMR})</span>
                               <input type="number" name="price_xmr" value={productData.price_xmr} onChange={handleChange} style={styles.input} step="0.000001" min="0" placeholder="e.g., 1.25" disabled={isSubmitting || !isPgpAuthenticated || !productData.accepted_currencies.includes('XMR')}/>
                          </div>
                           <div style={styles.priceInputContainer}>
                               <span style={styles.currencySymbol}>BTC ({CURRENCY_SYMBOLS.BTC})</span>
                               <input type="number" name="price_btc" value={productData.price_btc} onChange={handleChange} style={styles.input} step="0.00000001" min="0" placeholder="e.g., 0.005" disabled={isSubmitting || !isPgpAuthenticated || !productData.accepted_currencies.includes('BTC')}/>
                          </div>
                           <div style={styles.priceInputContainer}>
                               <span style={styles.currencySymbol}>ETH ({CURRENCY_SYMBOLS.ETH})</span>
                               <input type="number" name="price_eth" value={productData.price_eth} onChange={handleChange} style={styles.input} step="0.000001" min="0" placeholder="e.g., 0.1" disabled={isSubmitting || !isPgpAuthenticated || !productData.accepted_currencies.includes('ETH')}/>
                          </div>
                     </div>

                    {/* Inventory & Shipping */}
                     <div style={styles.formGroup}>
                         <label htmlFor="quantity" style={styles.label}>Quantity Available</label>
                         <input type="number" name="quantity" id="quantity" value={productData.quantity} onChange={handleChange} required style={styles.input} min="0" step="1" disabled={isSubmitting || !isPgpAuthenticated}/>
                         <p style={styles.helpText}>Set to 0 for unlimited stock (e.g., digital goods).</p>
                    </div>
                     <div style={styles.formGroup}>
                        <label htmlFor="ships_from" style={styles.label}>Ships From (Country/Region)</label>
                        <input type="text" name="ships_from" id="ships_from" value={productData.ships_from} onChange={handleChange} style={styles.input} maxLength={100} disabled={isSubmitting || !isPgpAuthenticated}/>
                    </div>
                     <div style={styles.formGroup}>
                        <label htmlFor="ships_to" style={styles.label}>Ships To (Optional, comma-separated)</label>
                        <textarea name="ships_to" id="ships_to" value={productData.ships_to} onChange={handleChange} style={styles.textarea} rows={3} placeholder="e.g., USA, Canada, UK. Leave blank for worldwide." disabled={isSubmitting || !isPgpAuthenticated}/>
                    </div>
                     <div style={styles.formGroup}>
                        <label htmlFor="shipping_options" style={styles.label}>Shipping Options (JSON Format)</label>
                        <textarea name="shipping_options" id="shipping_options" value={productData.shipping_options} onChange={handleChange} style={styles.textarea} rows={5} placeholder='[{"name": "Standard", "price_xmr": "0.1"}, {"name": "Express", "price_xmr": "0.5"}]' disabled={isSubmitting || !isPgpAuthenticated}/>
                         <p style={styles.helpText}>Enter as a JSON list. Price should be in XMR for now (TODO: adapt). Required for non-digital items.</p>
                     </div>

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

                    {error && <p style={styles.error}>{error}</p>}

                    <button
                        type="submit"
                        disabled={isSubmitting || isLoadingData || !isPgpAuthenticated}
                        style={{...styles.button, ...((isSubmitting || isLoadingData || !isPgpAuthenticated) ? styles.buttonDisabled : {})}}
                    >
                        {isSubmitting ? 'Saving...' : (isNew ? 'Create Product' : 'Update Product')}
                    </button>
                </form>
            </div>
        </Layout>
    );
}

// No getServerSideProps needed, data fetching happens client-side via useEffect