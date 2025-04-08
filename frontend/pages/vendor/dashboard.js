// frontend/pages/vendor/dashboard.js
// <<< REVISED FOR ENTERPRISE GRADE: Robust Auth Checks, Clearer Loading/Error States, Actionable Links >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
import { getVendorStats, listMySales } from '../../utils/api'; // <<< Ensure path is correct >>>
import Layout from '../../components/Layout'; // <<< Ensure path is correct >>>
// <<< ADDED: Import necessary components and constants >>>
import LoadingSpinner from '../../components/LoadingSpinner'; // <<< Ensure path is correct >>>
import FormError from '../../components/FormError'; // <<< Ensure path is correct >>>
import { CURRENCY_SYMBOLS } from '../../utils/constants'; // <<< Ensure path is correct >>>
import { showErrorToast } from '../../utils/notifications'; // <<< Ensure path is correct >>>

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '1100px', margin: '2rem auto', padding: '1rem' },
    title: { marginBottom: '1.5rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' },
    grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.5rem', marginBottom: '2rem' },
    statCard: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', textAlign: 'center', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }, // Use global .card?
    statValue: { fontSize: '2em', fontWeight: 'bold', display: 'block', marginBottom: '0.25rem' },
    statLabel: { fontSize: '0.9em', color: '#6c757d' },
    section: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', marginBottom: '2rem', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }, // Use global .card?
    sectionTitle: { marginTop: '0', marginBottom: '1.5rem' },
    table: { width: '100%', borderCollapse: 'collapse' }, // Use global .table styles?
    th: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '2px solid #dee2e6', background: '#f8f9fa', fontSize: '0.9em', textTransform: 'uppercase' },
    td: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '1px solid #dee2e6' },
    trHover: { '&:hover': { background: '#f1f1f1' } }, // Simple hover effect
    orderLink: { color: '#007bff', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } },
    code: { background: '#e9ecef', padding: '0.1rem 0.3rem', borderRadius: '3px', fontFamily: 'monospace', fontSize: '0.85em' },
    loadingText: { textAlign: 'center', padding: '2rem', fontStyle: 'italic', color: '#666' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' }, // Use global .warning-message
};

// Helper function to format currency (reuse if needed)
const formatCurrency = (value, currency) => {
    if (value === null || value === undefined) return 'N/A';
    const symbol = CURRENCY_SYMBOLS[currency] || currency;
    // Basic formatting, could use Decimal.js if more precision needed
    const num = parseFloat(value);
    return `${symbol} ${isNaN(num) ? 'N/A' : num.toFixed(2)}`; // Adjust decimals as needed
};


export default function VendorDashboard() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // State for stats and sales
    const [stats, setStats] = useState(null);
    const [recentSales, setRecentSales] = useState([]);
    // <<< ADDED: Separate loading/error states >>>
    const [isLoadingStats, setIsLoadingStats] = useState(true);
    const [isLoadingSales, setIsLoadingSales] = useState(true);
    const [statsError, setStatsError] = useState('');
    const [salesError, setSalesError] = useState('');

    // Fetch Vendor Stats
    const fetchStats = useCallback(async () => {
        if (!user || !isPgpAuthenticated) return; // Guard against running if conditions aren't met
        setIsLoadingStats(true); setStatsError('');
        try {
            // <<< SECURITY: Backend API MUST be scoped to the authenticated vendor >>>
            const data = await getVendorStats();
            setStats(data);
        } catch (err) {
            console.error("Failed to fetch vendor stats:", err);
            const errorMsg = err.message || "Could not load vendor statistics.";
            setStatsError(errorMsg); showErrorToast(errorMsg);
            setStats(null);
        } finally { setIsLoadingStats(false); }
    }, [user, isPgpAuthenticated]); // Depend on user and PGP auth status

    // Fetch Recent Sales Requiring Action
    const fetchSales = useCallback(async () => {
        if (!user || !isPgpAuthenticated) return; // Guard
        setIsLoadingSales(true); setSalesError('');
        try {
            // <<< SECURITY: Backend API MUST be scoped and filtered correctly >>>
            // Fetching orders needing action, e.g., status 'payment_confirmed'
            const params = { status: 'payment_confirmed', limit: 10 }; // Example filter
            const data = await listMySales(params);
            setRecentSales(data.results || []);
        } catch (err) {
            console.error("Failed to fetch recent sales:", err);
            const errorMsg = err.message || "Could not load recent sales data.";
            setSalesError(errorMsg); showErrorToast(errorMsg);
            setRecentSales([]);
        } finally { setIsLoadingSales(false); }
    }, [user, isPgpAuthenticated]); // Depend on user and PGP auth status

    // Effect to check authentication, vendor status and trigger fetches
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) { router.push('/login?next=/vendor/dashboard'); }
            else if (!user.is_vendor) {
                showErrorToast("Access denied. Vendor status required.");
                router.push('/profile'); // Redirect non-vendors
            } else if (!isPgpAuthenticated) {
                // Allow viewing page but show warning and disable actions conceptually
                console.warn("Vendor dashboard viewed without PGP authenticated session.");
                 // Reset data if PGP session lost? Optional.
                 // setStats(null); setRecentSales([]);
                 setIsLoadingStats(false); setIsLoadingSales(false); // Ensure loading stops if PGP lost
            } else {
                // Fetch data only if user is vendor AND PGP authenticated
                fetchStats();
                fetchSales();
            }
        }
    }, [user, isPgpAuthenticated, authIsLoading, router, fetchStats, fetchSales]); // Add fetch functions

    // --- Render Logic ---

    // Show loading spinner during initial auth check
    if (authIsLoading) return <Layout><div style={styles.loadingText}><LoadingSpinner message="Loading dashboard..." /></div></Layout>;

    // Handle cases where user is not logged in or not a vendor (should be caught by useEffect redirect, but good fallback)
    if (!user) return <Layout><div style={styles.loadingText}>Redirecting to login...</div></Layout>;
    if (!user.is_vendor) return <Layout><div style={styles.loadingText}>Access Denied. Vendor status required.</div></Layout>;

    return (
        <Layout>
            <div style={styles.container}>
                <h1 style={styles.title}>Vendor Dashboard</h1>

                 {/* Show PGP warning if session lacks PGP auth */}
                {!isPgpAuthenticated && (
                     <div style={styles.authWarning} className="warning-message">
                         <strong>Security Notice:</strong> Your session is not PGP authenticated. Viewing dashboard data is allowed, but actions (like managing products) will require re-logging in with PGP verification.
                     </div>
                 )}

                 {/* Quick Links/Actions - Ensure links are correct */}
                <div style={styles.section} className="mb-4">
                    <h2 style={styles.sectionTitle}>Quick Actions</h2>
                     <div className="d-flex flex-wrap gap-2"> {/* Use flexbox for button layout */}
                        <Link href="/vendor/products" className="button button-secondary">Manage Products</Link>
                        <Link href="/vendor/products/new" className="button button-success">Add New Product</Link>
                        <Link href="/orders?role=vendor" className="button button-secondary">View All Sales</Link> {/* Link to filtered orders page */}
                        <Link href="/wallet" className="button button-secondary">Manage Wallet</Link>
                        <Link href="/tickets" className="button button-secondary">Support Tickets</Link>
                        {/* Add other relevant links, e.g., View Public Profile */}
                     </div>
                </div>

                 {/* Statistics Section */}
                <div style={styles.section} className="mb-4">
                    <h2 style={styles.sectionTitle}>Your Statistics</h2>
                    {statsError && <FormError message={statsError} />}
                    {isLoadingStats && <LoadingSpinner message="Loading stats..." />}
                    {!isLoadingStats && !statsError && stats && (
                        <div style={styles.grid}>
                             <div style={styles.statCard}>
                                <span style={styles.statValue}>{stats.active_listings ?? 'N/A'}</span>
                                <span style={styles.statLabel}>Active Listings</span>
                             </div>
                             <div style={styles.statCard}>
                                <span style={styles.statValue}>{stats.pending_sales ?? 'N/A'}</span>
                                <span style={styles.statLabel}>Pending Sales</span>
                             </div>
                            <div style={styles.statCard}>
                                <span style={styles.statValue}>{stats.total_sales_completed ?? 'N/A'}</span>
                                <span style={styles.statLabel}>Completed Sales</span>
                            </div>
                             <div style={styles.statCard}>
                                <span style={styles.statValue}>{stats.open_disputes ?? 'N/A'}</span>
                                <span style={styles.statLabel}>Open Disputes</span>
                             </div>
                            {/* Estimated Revenue might need currency formatting */}
                            {/* <div style={styles.statCard}>
                                <span style={styles.statValue}>{formatCurrency(stats.estimated_revenue?.total_value_usd, 'USD') ?? 'N/A'}</span>
                                <span style={styles.statLabel}>Est. Lifetime Revenue (USD)</span>
                            </div> */}
                             {/* Add Vendor Level/Rating if available in stats */}
                        </div>
                    )}
                     {!isLoadingStats && !statsError && !stats && isPgpAuthenticated && ( <p>Could not load statistics.</p> )}
                </div>

                 {/* Recent Sales Requiring Action Section */}
                <div style={styles.section}>
                    <h2 style={styles.sectionTitle}>Recent Sales Requiring Action (e.g., Shipment)</h2>
                    {salesError && <FormError message={salesError} />}
                    {isLoadingSales && <LoadingSpinner message="Loading sales..." />}
                    {!isLoadingSales && !salesError && recentSales.length === 0 && isPgpAuthenticated && (
                        <p>No recent orders require your action at this time.</p>
                    )}
                    {!isLoadingSales && !salesError && recentSales.length > 0 && (
                        <div className="table-responsive"> {/* Make table scrollable on small screens */}
                             <table style={styles.table} className="table table-striped table-hover"> {/* Use global classes */}
                                <thead>
                                    <tr>
                                        <th style={styles.th}>Order ID</th>
                                        <th style={styles.th}>Date</th>
                                        <th style={styles.th}>Product</th>
                                        <th style={styles.th}>Quantity</th>
                                        <th style={styles.th}>Status</th>
                                        <th style={styles.th}>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {recentSales.map(order => (
                                        // <<< ADDED: Hover style if using CSS-in-JS >>>
                                        <tr key={order.id} style={styles.trHover}>
                                             <td style={styles.td}><code style={styles.code}>{order.id.substring(0, 8)}...</code></td>
                                            <td style={styles.td}>{new Date(order.created_at).toLocaleDateString()}</td>
                                            <td style={styles.td}>{order.product?.name || 'N/A'}</td>
                                            <td style={styles.td}>{order.quantity}</td>
                                            <td style={styles.td}>{order.status_display || order.status}</td>
                                             <td style={styles.td}>
                                                 {/* <<< UPDATED: Direct link to order detail >>> */}
                                                 <Link href={`/orders/${order.id}`} style={styles.orderLink}>View Details</Link>
                                             </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                     {!isLoadingSales && !salesError && !isPgpAuthenticated && ( <p>Login with PGP verification required to load sales data.</p> )}
                </div>

            </div>
        </Layout>
    );
}