// frontend/pages/orders/index.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Migrated to CSS Modules, improved accessibility, refined loading/error states, general cleanup.
//             - Replaced inline styles with imports from OrdersIndex.module.css.
//             - Added scope attributes to table headers/cells.
//             - Added aria-label to reset button.
//             - Used LoadingSpinner component more consistently.
//             - Added TODO for moving formatPrice utility.
//             - Added TODO for refining error handling based on API responses.
//             - Added revision history block.

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext';
import { listOrders } from '../../utils/api'; // Ensure listOrders accepts params object
import Layout from '../../components/Layout';
import { CURRENCY_SYMBOLS, SUPPORTED_CURRENCIES, DEFAULT_PAGE_SIZE } from '../../utils/constants';
import { Decimal } from 'decimal.js';
// Import reusable components
import PaginationControls from '../../components/PaginationControls';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import styles from './OrdersIndex.module.css'; // Import CSS Module

// Order Status Choices (Consider moving to constants.js if reused)
const STATUS_FILTER_CHOICES = [
    { value: '', label: 'All Statuses' },
    { value: 'pending_payment', label: 'Pending Payment' },
    { value: 'payment_unconfirmed', label: 'Payment Unconfirmed' },
    { value: 'payment_confirmed', label: 'Payment Confirmed / In Escrow' },
    { value: 'shipped', label: 'Shipped' },
    { value: 'finalized', label: 'Finalized' },
    { value: 'disputed', label: 'Disputed' },
    { value: 'dispute_resolved', label: 'Dispute Resolved' },
    { value: 'cancelled_timeout', label: 'Cancelled (Timeout)' },
    { value: 'cancelled_buyer', label: 'Cancelled (Buyer)' },
    { value: 'cancelled_vendor', label: 'Cancelled (Vendor)' },
    { value: 'refunded', label: 'Refunded' },
];

// Allowed Ordering Fields (Consider moving to constants.js if reused)
const ORDERING_CHOICES = [
    { value: '-created_at', label: 'Date Placed (Newest)' },
    { value: 'created_at', label: 'Date Placed (Oldest)' },
    { value: '-updated_at', label: 'Last Updated (Newest)' },
    { value: 'updated_at', label: 'Last Updated (Oldest)' },
    { value: 'status', label: 'Status (A-Z)' },
    { value: '-status', label: 'Status (Z-A)' },
    // TODO: Add price ordering if needed/supported by backend
    // { value: 'total_price_native_selected', label: 'Total Price (Low-High)' },
    // { value: '-total_price_native_selected', label: 'Total Price (High-Low)' },
];

// TODO: Consider moving formatPrice to a shared utils/formatters.js file
// Helper to format price
const formatPrice = (price, currency) => {
    if (price === null || price === undefined) return 'N/A';
    try {
        const p = new Decimal(price);
        let options;
        // Define precision based on currency - consider adding more currencies or a default
        if (currency === 'BTC') options = { minimumFractionDigits: 8, maximumFractionDigits: 8 };
        else if (currency === 'ETH') options = { minimumFractionDigits: 6, maximumFractionDigits: 8 };
        else if (currency === 'XMR') options = { minimumFractionDigits: 6, maximumFractionDigits: 12 };
        else options = { minimumFractionDigits: 2, maximumFractionDigits: 2 }; // Default for FIAT?
        // Use toFixed which is simpler if Decimal precision is already set or not strictly needed beyond display
        return p.toFixed(options.maximumFractionDigits);
    } catch (e) {
        console.error("Price formatting error:", e);
        return 'Error';
    }
};

// Helper to format date consistently
const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    try {
        // Adjust options as needed
        return new Date(dateString).toLocaleDateString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric'
        });
    } catch (e) {
        console.error("Date formatting error:", e);
        return 'Invalid Date';
    }
};

export default function OrderListPage() {
    const { user, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    const [orders, setOrders] = useState([]);
    const [isLoading, setIsLoading] = useState(true); // Loading state specific to order fetching
    const [error, setError] = useState('');

    // State for filters & sorting - derived from router query in useEffect
    const [statusFilter, setStatusFilter] = useState('');
    const [currencyFilter, setCurrencyFilter] = useState('');
    const [ordering, setOrdering] = useState('-created_at');

    // State for pagination - derived from router query and API response
    const [currentPage, setCurrentPage] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [nextPageUrl, setNextPageUrl] = useState(null);
    const [previousPageUrl, setPreviousPageUrl] = useState(null);

    const totalPages = totalCount > 0 ? Math.ceil(totalCount / DEFAULT_PAGE_SIZE) : 0;

    // Function to update URL query parameters (triggers refetch via useEffect)
    const updateQueryParams = useCallback((newParams) => {
        const query = { ...router.query };
        for (const key in newParams) {
            if (newParams[key] === undefined || newParams[key] === null || newParams[key] === '') {
                delete query[key];
            } else {
                query[key] = String(newParams[key]); // Ensure values are strings
            }
        }
        // Reset page to 1 if filters/sorting changed, unless page itself is the new param
        if (!('page' in newParams)) {
            delete query.page;
        }

        router.push({
            pathname: router.pathname, // Use router.pathname to be safe
            query: query,
        }, undefined, { shallow: true }); // Shallow routing avoids full page reload
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [router.pathname, router.query]); // Depend on query


    // Fetch orders based on current query params
    const fetchOrders = useCallback(async (queryParams) => {
        if (!user) return; // Should be handled by redirect logic, but safe check

        setIsLoading(true);
        setError('');
        try {
            const page = parseInt(queryParams.page) || 1;
            // Clean params before sending? Ensure only expected keys? Backend should handle unknowns robustly.
            const paramsToSend = { ...queryParams };

            console.log("Fetching orders with params:", paramsToSend);
            const data = await listOrders(paramsToSend); // Pass the whole query object

            setOrders(data.results || []);
            setTotalCount(data.count || 0);
            setNextPageUrl(data.next || null);
            setPreviousPageUrl(data.previous || null);
            setCurrentPage(page); // Sync current page state

        } catch (err) {
            console.error("Failed to fetch orders:", err);
            // TODO: Implement more specific error handling based on API status codes/messages
            // e.g., distinguish 401/403 (auth) from 500 (server) or 400 (bad request)
            setError(err.response?.data?.detail || err.message || "Could not fetch your orders. Please try again later.");
            setOrders([]); // Clear orders on error
            setTotalCount(0); // Reset pagination info on error
            setNextPageUrl(null);
            setPreviousPageUrl(null);
        } finally {
            setIsLoading(false);
        }
    }, [user]); // Depend only on user; query params passed directly


    // Effect to sync local state from router and fetch data
    useEffect(() => {
        if (router.isReady && user) {
            // Sync local filter/sort state from URL query for controlled components
            setStatusFilter(router.query.status || '');
            setCurrencyFilter(router.query.selected_currency || '');
            setOrdering(router.query.ordering || '-created_at');
            setCurrentPage(parseInt(router.query.page) || 1);

            // Fetch data using the current router query
            fetchOrders(router.query);
        }
        // No cleanup needed here as fetchOrders handles its own state
    }, [router.isReady, user, router.query, fetchOrders]); // Re-run when query changes


    // Redirect if not logged in (after initial auth check)
    useEffect(() => {
        if (!authIsLoading && !user && router.isReady) {
            // Redirect to login, preserving the intended destination
            router.push(`/login?next=${encodeURIComponent(router.asPath)}`);
        }
    }, [user, authIsLoading, router]);


    // --- Event Handlers ---
    const handleFilterChange = (setter) => (e) => {
        const { name, value } = e.target;
        setter(value); // Update local state immediately for responsiveness (optional)
        updateQueryParams({ [name]: value || undefined }); // Update URL, remove if empty
    };

    const handleOrderingChange = (e) => {
        const { value } = e.target;
        setOrdering(value); // Update local state immediately (optional)
        updateQueryParams({ ordering: value }); // Update URL
    };

    const handleResetFilters = () => {
        // Reset local state for immediate UI update
        setStatusFilter('');
        setCurrencyFilter('');
        setOrdering('-created_at');
        // Push empty query (except potentially other non-filter params)
        // Simplest is often just resetting known filters:
        updateQueryParams({ status: undefined, selected_currency: undefined, ordering: undefined, page: undefined });
    };

    const handlePageChange = (newPage) => {
        if (newPage >= 1 && (totalPages === 0 || newPage <= totalPages)) {
             updateQueryParams({ page: newPage });
        }
    };


    // --- Render Logic ---
    // Show loading spinner while auth is checking or if user is null (before redirect effect runs)
    if (authIsLoading || !user) {
        // Use Layout to maintain structure, show spinner centrally
        return <Layout><LoadingSpinner message="Loading user session..." /></Layout>;
    }

    // Main content rendering
    return (
        <Layout>
            <div className={styles.container}>
                <h1 className={styles.title}>Your Orders</h1>

                {/* Filtering/Sorting Controls */}
                <div className={styles.filterBar}>
                    <div className={styles.filterGroup}>
                        <label htmlFor="statusFilter" className={styles.filterLabel}>Status</label>
                        <select
                            id="statusFilter"
                            name="status" // Name matches query param key
                            value={statusFilter}
                            onChange={handleFilterChange(setStatusFilter)}
                            className={styles.filterSelect}
                            disabled={isLoading}
                            aria-describedby="statusFilterDesc"
                        >
                            {STATUS_FILTER_CHOICES.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                        </select>
                        <small id="statusFilterDesc" className={styles.filterDescription}>Filter by order status.</small>
                    </div>
                    <div className={styles.filterGroup}>
                        <label htmlFor="currencyFilter" className={styles.filterLabel}>Currency</label>
                        <select
                            id="currencyFilter"
                            name="selected_currency" // Name matches query param key
                            value={currencyFilter}
                            onChange={handleFilterChange(setCurrencyFilter)}
                            className={styles.filterSelect}
                            disabled={isLoading}
                            aria-describedby="currencyFilterDesc"
                        >
                            <option value="">All Currencies</option>
                            {(SUPPORTED_CURRENCIES || []).map(curr => (
                                <option key={curr} value={curr}>{curr} ({CURRENCY_SYMBOLS[curr] || curr})</option>
                            ))}
                        </select>
                         <small id="currencyFilterDesc" className={styles.filterDescription}>Filter by payment currency.</small>
                    </div>
                    <div className={styles.filterGroup}>
                        <label htmlFor="orderingFilter" className={styles.filterLabel}>Sort By</label>
                        <select
                            id="orderingFilter"
                            name="ordering" // Name matches query param key
                            value={ordering}
                            onChange={handleOrderingChange}
                            className={styles.filterSelect}
                            disabled={isLoading}
                             aria-describedby="orderingFilterDesc"
                        >
                            {ORDERING_CHOICES.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                        </select>
                        <small id="orderingFilterDesc" className={styles.filterDescription}>Sort order list.</small>
                    </div>
                    <button
                        onClick={handleResetFilters}
                        className={styles.filterResetButton}
                        title="Reset Filters"
                        aria-label="Reset all filters and sorting"
                        disabled={isLoading}
                    >
                        &#x21BA; {/* Reset icon */}
                    </button>
                </div>

                {/* Error Display */}
                <FormError message={error} />

                {/* Orders Table or Loading/No Orders Message */}
                {isLoading ? (
                    <LoadingSpinner message="Loading orders..." />
                ) : orders.length > 0 ? (
                    <>
                        <div className={styles.tableContainer}> {/* Optional: container for overflow */}
                            <table className={styles.orderTable}>
                                <thead>
                                    <tr>
                                        <th scope="col" className={styles.th}>Order ID</th>
                                        <th scope="col" className={styles.th}>Product</th>
                                        <th scope="col" className={styles.th}>Your Role</th>
                                        <th scope="col" className={styles.th}>Status</th>
                                        <th scope="col" className={styles.th}>Total</th>
                                        <th scope="col" className={styles.th}>Date Placed</th>
                                        <th scope="col" className={styles.th}>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {orders.map(order => {
                                        // Determine role (ensure user object is valid)
                                        const userRole = user && order.buyer?.id === user.id ? 'Buyer'
                                                         : user && order.vendor?.id === user.id ? 'Vendor'
                                                         : 'N/A'; // Should not happen if API is correct

                                        const roleClass = userRole === 'Buyer' ? styles.roleBuyer
                                                        : userRole === 'Vendor' ? styles.roleVendor
                                                        : '';

                                        const currencySymbol = CURRENCY_SYMBOLS[order.selected_currency] || order.selected_currency;

                                        // Determine if action needed - refine this logic based on exact requirements
                                        const needsAction = (
                                            (userRole === 'Vendor' && ['payment_confirmed', 'disputed'].includes(order.status)) ||
                                            (userRole === 'Buyer' && ['shipped', 'disputed'].includes(order.status)) ||
                                            (userRole === 'Buyer' && order.status === 'pending_release_signature') // Example for multi-sig
                                            // Add more conditions as needed
                                        );
                                        const statusClass = needsAction ? styles.actionNeeded : '';

                                        return (
                                            <tr key={order.id}>
                                                {/* First cell acts as row header for accessibility */}
                                                <td scope="row" className={styles.td}>
                                                    <Link href={`/orders/${order.id}`} className={styles.link}>
                                                        <code title={order.id}>{order.id.substring(0, 8)}...</code>
                                                    </Link>
                                                </td>
                                                <td className={styles.td}>
                                                    {order.product ? (
                                                        <Link href={`/products/${order.product.slug}`} className={styles.link} title={order.product.name}>
                                                            {order.product.name.substring(0, 30)}{order.product.name.length > 30 ? '...' : ''}
                                                        </Link>
                                                    ) : ( 'Product Data Missing' )}
                                                    {' '}x {order.quantity}
                                                </td>
                                                <td className={styles.td}>
                                                    <span className={roleClass}>{userRole}</span>
                                                </td>
                                                <td className={styles.td}>
                                                    <span className={statusClass} title={`Status: ${order.status}`}>
                                                        {order.status_display || order.status} {/* Prefer display name */}
                                                    </span>
                                                </td>
                                                <td className={styles.td}>
                                                    {currencySymbol} {formatPrice(order.total_price_native_selected, order.selected_currency)}
                                                </td>
                                                <td className={styles.td}>{formatDate(order.created_at)}</td>
                                                <td className={styles.td}>
                                                    {/* Use global button styles if defined, or module styles */}
                                                    <Link href={`/orders/${order.id}`} className={`${styles.buttonLink} ${styles.buttonSmall}`}>
                                                        View
                                                    </Link>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {/* Use PaginationControls component */}
                        <PaginationControls
                            currentPage={currentPage}
                            totalPages={totalPages}
                            totalCount={totalCount}
                            onPageChange={handlePageChange} // Simplified handler
                            isLoading={isLoading}
                            pageSize={DEFAULT_PAGE_SIZE} // Pass page size for display
                        />
                    </>
                ) : (
                    // Only show "No orders" if not loading and no error occurred
                    !error && !isLoading && <p className={styles.noOrders}>No orders found matching your criteria.</p>
                )}
            </div>
        </Layout>
    );
}