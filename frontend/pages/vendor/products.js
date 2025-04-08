// frontend/pages/vendor/products.js
// <<< REVISED FOR ENTERPRISE GRADE: Pagination, Delete Confirmation, Status Indicators, Auth Checks >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
// <<< UPDATED: Import needed API calls, components, constants >>>
import { getProducts, deleteProduct } from '../../utils/api'; // Assumes getProducts can filter by vendor implicitly based on auth
import Layout from '../../components/Layout';
import Modal from '../../components/Modal';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import PaginationControls from '../../components/PaginationControls';
import { DEFAULT_PAGE_SIZE } from '../../utils/constants';
import { showSuccessToast, showErrorToast, showWarningToast } from '../../utils/notifications';

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '1100px', margin: '2rem auto', padding: '1rem' },
    title: { marginBottom: '1rem' },
    header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' },
    table: { width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }, // Use global .table styles?
    th: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '2px solid #dee2e6', background: '#f8f9fa', fontSize: '0.9em', textTransform: 'uppercase' },
    td: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '1px solid #dee2e6', verticalAlign: 'middle' },
    trHover: { '&:hover': { background: '#f1f1f1' } },
    actionLinks: { display: 'flex', gap: '0.75rem' },
    statusIndicator: { padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8em', display: 'inline-block', color: '#fff' },
    statusActive: { background: '#28a745' }, // Green
    statusInactive: { background: '#6c757d' }, // Gray
    statusFeatured: { background: '#007bff' }, // Blue
    loadingText: { textAlign: 'center', padding: '2rem', fontStyle: 'italic', color: '#666' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' },
    modalActions: { marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end', gap: '1rem' },
    // Use global button classes (.button, .button-primary, .button-danger, .button-secondary, .disabled etc.)
};

// Helper component for status indicator
const StatusBadge = ({ status }) => {
    let style = styles.statusInactive; // Default
    let text = 'Inactive';
    if (status === 'active') { style = styles.statusActive; text = 'Active'; }
    else if (status === 'featured') { style = styles.statusFeatured; text = 'Featured'; } // Assuming 'featured' status exists

    return <span style={{...styles.statusIndicator, ...style}}>{text}</span>;
};

export default function VendorProductsPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // State for products list, pagination, and loading/error
    const [productsData, setProductsData] = useState({ results: [], count: 0 });
    const [currentPage, setCurrentPage] = useState(1);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');

    // State for delete confirmation modal
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [productToDelete, setProductToDelete] = useState(null); // Store { id, name, slug }
    const [isDeleting, setIsDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState('');

    // Fetch vendor's products function
    const fetchVendorProducts = useCallback(async (page = 1) => {
        // <<< Guard: Ensure user, vendor status, and PGP auth before fetching >>>
        if (!user || !user.is_vendor || !isPgpAuthenticated) {
            setIsLoading(false); // Stop loading if conditions not met
            if (user && !user.is_vendor) setError("Access denied. Vendor status required.");
            else if (user && !isPgpAuthenticated) setError("PGP authenticated session required to manage products.");
            else setError("Authentication required."); // General auth error
            return;
        }

        setIsLoading(true); setError(''); // Clear previous errors on fetch
        const params = {
            // <<< SECURITY: Backend MUST filter by authenticated vendor >>>
            // Optionally, pass vendor ID if API requires it, but backend should verify
            // vendor_id: user.id, // Example if needed, but backend scoping is better
            limit: DEFAULT_PAGE_SIZE,
            offset: (page - 1) * DEFAULT_PAGE_SIZE,
        };

        try {
            const data = await getProducts(params);
            setProductsData(data);
            setCurrentPage(page); // Update current page state
        } catch (err) {
            console.error("Failed to fetch vendor products:", err);
            const errorMsg = err.message || "Could not load your products.";
            setError(errorMsg); showErrorToast(errorMsg);
            setProductsData({ results: [], count: 0 }); // Reset data on error
        } finally { setIsLoading(false); }
    }, [user, isPgpAuthenticated]); // Depend on user and PGP status

    // Effect to check authentication and fetch initial data
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) { router.push('/login?next=/vendor/products'); }
            else if (!user.is_vendor) {
                showErrorToast("Access denied. Vendor status required.");
                router.push('/profile');
            } else {
                 // Fetch data only if user is vendor (PGP check happens inside fetch function)
                fetchVendorProducts(currentPage); // Fetch current page
            }
        }
    }, [user, authIsLoading, router, currentPage, fetchVendorProducts]); // Re-fetch if page changes

    // --- Delete Handlers ---
    const openDeleteModal = (product) => {
        if (!isPgpAuthenticated) {
             showErrorToast("PGP authenticated session required to delete products.");
             return;
        }
        setProductToDelete({ id: product.id, name: product.name, slug: product.slug }); // Store slug for API call
        setDeleteError(''); // Clear previous delete errors
        setIsModalOpen(true);
    };

    const closeDeleteModal = () => {
        setIsModalOpen(false);
        setProductToDelete(null);
        setIsDeleting(false); // Ensure deleting state is reset
    };

    const handleDeleteConfirm = async () => {
         // <<< BEST PRACTICE: Re-check PGP Auth status inside confirm handler >>>
        if (!isPgpAuthenticated) {
             showErrorToast("PGP authenticated session timed out. Please re-login.");
             closeDeleteModal(); return;
        }
        if (!productToDelete) return;

        setIsDeleting(true); setDeleteError('');
        try {
            // <<< SECURITY: API requires PGP auth, backend verifies ownership >>>
            await deleteProduct(productToDelete.slug); // Use slug for deletion endpoint
            showSuccessToast(`Product "${productToDelete.name}" deleted successfully.`);
            closeDeleteModal();
            // Refresh the product list after deletion (fetch current page again)
            fetchVendorProducts(currentPage);
        } catch (err) {
            console.error("Delete product failed:", err);
            const errorMsg = err.message || "Failed to delete product.";
            setDeleteError(errorMsg); // Show error inside modal
            showErrorToast(`Delete failed: ${errorMsg}`);
            // Keep modal open on error to show message
        } finally { setIsDeleting(false); }
    };


    // --- Render Logic ---
    if (authIsLoading) return <Layout><div style={styles.loadingText}><LoadingSpinner message="Loading product management..." /></div></Layout>;
    if (!user || !user.is_vendor) return <Layout><div style={styles.loadingText}>Access Denied. Redirecting...</div></Layout>; // Should be redirected by useEffect

    return (
        <Layout>
            <div style={styles.container}>
                 {/* Header with Title and Add Button */}
                <div style={styles.header}>
                    <h1 style={styles.title}>Manage Your Products</h1>
                    <Link href="/vendor/products/new" className="button button-success">Add New Product</Link>
                </div>

                 {/* PGP Auth Warning */}
                 {!isPgpAuthenticated && (
                     <div style={styles.authWarning} className="warning-message">
                         <strong>Security Notice:</strong> Your session is not PGP authenticated. Viewing is allowed, but actions like deleting products require completing the PGP login challenge. Please <Link href="/login" style={{fontWeight:'bold'}}>re-login</Link> if needed. Action buttons are disabled.
                     </div>
                 )}

                {/* General Loading/Error for List */}
                {error && <FormError message={error} />}
                {isLoading && <LoadingSpinner message="Loading your products..." />}

                {/* Products Table */}
                 {!isLoading && !error && productsData.results.length > 0 && (
                     <>
                        <div className="table-responsive">
                            <table style={styles.table} className="table table-striped table-hover"> {/* Use global classes */}
                                <thead>
                                    <tr>
                                        <th style={styles.th}>Name</th>
                                        <th style={styles.th}>Status</th>
                                        <th style={styles.th}>Stock</th>
                                         {/* Add Price columns if useful (consider multi-currency complexity) */}
                                         {/* <th style={styles.th}>Price (XMR)</th> */}
                                        <th style={styles.th}>Sales</th>
                                        <th style={styles.th}>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {productsData.results.map(product => (
                                        <tr key={product.id} style={styles.trHover}>
                                             <td style={styles.td}>{product.name}</td>
                                             <td style={styles.td}><StatusBadge status={product.status} /></td>
                                             <td style={styles.td}>{product.quantity_available ?? 'Unlimited'}</td>
                                             {/* Price example (adjust based on available data) */}
                                             {/* <td style={styles.td}>{formatPrice(product.price_xmr, 'XMR')}</td> */}
                                            <td style={styles.td}>{product.sales_count ?? 0}</td> {/* Assuming sales_count exists */}
                                             <td style={styles.td}>
                                                <div style={styles.actionLinks}>
                                                     {/* <<< Pass slug to edit page >>> */}
                                                     <Link href={`/vendor/products/edit/${product.slug}`} className={`button button-secondary button-sm ${!isPgpAuthenticated ? 'disabled' : ''}`} title={!isPgpAuthenticated ? "Requires PGP Auth" : "Edit Product"}>Edit</Link>
                                                     <button
                                                        onClick={() => openDeleteModal(product)}
                                                        className={`button button-danger button-sm ${!isPgpAuthenticated ? 'disabled' : ''}`}
                                                        disabled={!isPgpAuthenticated} // Disable button if no PGP auth
                                                        title={!isPgpAuthenticated ? "Requires PGP Auth" : "Delete Product"}
                                                     >Delete</button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                         {/* Pagination */}
                         <PaginationControls
                            currentPage={currentPage}
                            totalPages={Math.ceil(productsData.count / DEFAULT_PAGE_SIZE)}
                            totalCount={productsData.count}
                            onPrevious={() => fetchVendorProducts(currentPage - 1)}
                            onNext={() => fetchVendorProducts(currentPage + 1)}
                            isLoading={isLoading}
                         />
                    </>
                 )}

                {/* No Products Message */}
                {!isLoading && !error && productsData.results.length === 0 && isPgpAuthenticated && (
                    <p style={{marginTop:'2rem', textAlign:'center'}}>You haven't added any products yet. <Link href="/vendor/products/new">Add your first product!</Link></p>
                )}
                 {!isLoading && !error && !isPgpAuthenticated && ( <p style={{marginTop:'2rem', textAlign:'center'}}>Login with PGP verification required to view and manage products.</p> )}

            </div>

             {/* Delete Confirmation Modal */}
             <Modal isOpen={isModalOpen} onClose={closeDeleteModal} title="Confirm Product Deletion">
                 {productToDelete && (
                     <>
                        <p>Are you sure you want to permanently delete the product: <strong>{productToDelete.name}</strong>?</p>
                        <p>This action cannot be undone. Associated sales data may be affected or anonymized based on system rules.</p>
                        <FormError message={deleteError} /> {/* Show delete error inside modal */}
                        <div style={styles.modalActions}>
                             <button onClick={closeDeleteModal} className="button button-secondary" disabled={isDeleting}>Cancel</button>
                             <button onClick={handleDeleteConfirm} className="button button-danger" disabled={isDeleting}>
                                {isDeleting ? <LoadingSpinner size="1em"/> : 'Confirm Delete'}
                             </button>
                        </div>
                    </>
                 )}
            </Modal>
        </Layout>
    );
}