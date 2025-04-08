// frontend/pages/tickets/index.js
// <<< REVISED FOR ENTERPRISE GRADE: Pagination, Loading/Error States, Auth Checks, Status Indicator >>>

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
// <<< UPDATED: Import needed API calls, components, constants >>>
import { listTickets } from '../../utils/api';
import Layout from '../../components/Layout';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import PaginationControls from '../../components/PaginationControls';
import { DEFAULT_PAGE_SIZE } from '../../utils/constants';
import { showErrorToast } from '../../utils/notifications';

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '1000px', margin: '2rem auto', padding: '1rem' },
    header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' },
    title: { marginBottom: '0' }, // Remove bottom margin if using header padding
    table: { width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }, // Use global .table styles?
    th: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '2px solid #dee2e6', background: '#f8f9fa', fontSize: '0.9em', textTransform: 'uppercase' },
    td: { textAlign: 'left', padding: '0.8rem 0.5rem', borderBottom: '1px solid #dee2e6', verticalAlign: 'middle' },
    trHover: { '&:hover': { background: '#f1f1f1' } },
    ticketLink: { color: '#007bff', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } },
    statusIndicator: { padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8em', display: 'inline-block', color: '#fff' },
    statusOpen: { background: '#007bff' }, // Blue
    statusClosed: { background: '#6c757d' }, // Gray
    statusStaffReply: { background: '#ffc107', color: '#333' }, // Yellow/Orange
    statusUserReply: { background: '#17a2b8' }, // Teal/Cyan
    loadingText: { textAlign: 'center', padding: '2rem', fontStyle: 'italic', color: '#666' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' },
    // Use global button classes (.button, .button-primary, .button-success, etc.)
};

// Helper component for status badge (adapt based on actual status values from backend)
const TicketStatusBadge = ({ status }) => {
    let style = styles.statusOpen; // Default to open
    let text = status || 'Open'; // Default text

    const lowerStatus = status?.toLowerCase();
    if (lowerStatus === 'closed') { style = styles.statusClosed; text = 'Closed'; }
    else if (lowerStatus === 'staff_reply') { style = styles.statusStaffReply; text = 'Staff Reply'; }
    else if (lowerStatus === 'user_reply') { style = styles.statusUserReply; text = 'User Reply'; }
    // Add more statuses as needed

    return <span style={{...styles.statusIndicator, ...style}}>{text}</span>;
};


export default function TicketsListPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // State for tickets list, pagination, loading/error
    const [ticketsData, setTicketsData] = useState({ results: [], count: 0 });
    const [currentPage, setCurrentPage] = useState(1);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');

    // Fetch tickets function
    const fetchTickets = useCallback(async (page = 1) => {
        // <<< Guard: Check auth and potentially PGP auth >>>
        // <<< Assuming listing tickets might also require PGP auth for consistency/security >>>
        if (!user) { setIsLoading(false); setError("Authentication required."); return; }
         if (!isPgpAuthenticated) {
             setIsLoading(false);
             setError("PGP authenticated session required to view tickets.");
             return;
         }

        setIsLoading(true); setError('');
        const params = {
            limit: DEFAULT_PAGE_SIZE,
            offset: (page - 1) * DEFAULT_PAGE_SIZE,
            // Add other filters if needed (e.g., status)
        };

        try {
            // <<< SECURITY: Backend API MUST filter results to the authenticated user >>>
            const data = await listTickets(params);
            setTicketsData(data);
            setCurrentPage(page);
        } catch (err) {
            console.error("Failed to fetch tickets:", err);
            const errorMsg = err.message || "Could not load your support tickets.";
            setError(errorMsg); showErrorToast(errorMsg);
            setTicketsData({ results: [], count: 0 }); // Reset data on error
        } finally { setIsLoading(false); }
    }, [user, isPgpAuthenticated]); // Depend on user and PGP status

    // Effect for initial fetch and auth checks
    useEffect(() => {
        if (!authIsLoading) {
            if (!user) { router.push('/login?next=/tickets'); }
            else {
                // Fetch data only if user is logged in (PGP check inside fetch function)
                fetchTickets(currentPage);
            }
        }
    }, [user, authIsLoading, router, currentPage, fetchTickets]); // Refetch if page changes

    // Handle page changes from pagination controls
    const handlePageChange = (newPage) => {
        fetchTickets(newPage);
    };


    // --- Render Logic ---
    if (authIsLoading) return <Layout><div style={styles.loadingText}><LoadingSpinner message="Loading tickets..." /></div></Layout>;
    if (!user && !authIsLoading) return <Layout><div style={styles.loadingText}>Redirecting to login...</div></Layout>;

    return (
        <Layout>
            <div style={styles.container}>
                 {/* Header with Title and Create Button */}
                <div style={styles.header}>
                    <h1 style={styles.title}>Your Support Tickets</h1>
                     {/* Link to create new ticket page */}
                    <Link href="/tickets/new" className="button button-success">Create New Ticket</Link>
                </div>

                {/* PGP Auth Warning (if listing requires it and it's missing) */}
                 {!isPgpAuthenticated && !authIsLoading && (
                     <div style={styles.authWarning} className="warning-message">
                         PGP authenticated session required to view tickets. Please <Link href="/login" style={{fontWeight:'bold'}}>re-login</Link>.
                     </div>
                 )}

                {/* General Loading/Error for List */}
                {error && <FormError message={error} />}
                {isLoading && <LoadingSpinner message="Loading your tickets..." />}

                 {/* Tickets Table */}
                 {!isLoading && !error && ticketsData.results.length > 0 && (
                     <>
                        <div className="table-responsive">
                             <table style={styles.table} className="table table-striped table-hover"> {/* Use global classes */}
                                <thead>
                                    <tr>
                                        <th style={styles.th}>Ticket ID</th>
                                        <th style={styles.th}>Subject</th>
                                        <th style={styles.th}>Status</th>
                                        <th style={styles.th}>Last Updated</th>
                                        <th style={styles.th}>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {ticketsData.results.map(ticket => (
                                        <tr key={ticket.id} style={styles.trHover}>
                                            {/* <<< Use first few chars of UUID if ID is long >>> */}
                                            <td style={styles.td}>{ticket.id?.substring(0, 8) || 'N/A'}</td>
                                            <td style={styles.td}>{ticket.subject}</td>
                                            <td style={styles.td}><TicketStatusBadge status={ticket.status_display || ticket.status} /></td>
                                            <td style={styles.td}>{new Date(ticket.updated_at).toLocaleString()}</td>
                                             <td style={styles.td}>
                                                <Link href={`/tickets/${ticket.id}`} style={styles.ticketLink}>View Details</Link>
                                             </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                         {/* Pagination */}
                         <PaginationControls
                            currentPage={currentPage}
                            totalPages={Math.ceil(ticketsData.count / DEFAULT_PAGE_SIZE)}
                            totalCount={ticketsData.count}
                            onPrevious={() => handlePageChange(currentPage - 1)}
                            onNext={() => handlePageChange(currentPage + 1)}
                            isLoading={isLoading}
                         />
                    </>
                 )}

                {/* No Tickets Message */}
                {!isLoading && !error && ticketsData.results.length === 0 && isPgpAuthenticated && (
                    <p style={{marginTop:'2rem', textAlign:'center'}}>You have no support tickets. <Link href="/tickets/new">Create one</Link> if you need assistance.</p>
                )}
                 {!isLoading && !error && !isPgpAuthenticated && ( <p style={{marginTop:'2rem', textAlign:'center'}}>Login with PGP verification required to view tickets.</p> )}

            </div>
        </Layout>
    );
}