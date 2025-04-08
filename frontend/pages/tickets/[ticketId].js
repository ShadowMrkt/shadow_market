// frontend/pages/tickets/[ticketId].js
// <<< REVISED FOR ENTERPRISE GRADE: Clearer PGP Handling Notes, Auth Checks, Message Display, Error Handling >>>

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
// <<< UPDATED: Import API, components, notifications >>>
import { getTicketDetail, replyToTicket } from '../../utils/api';
import Layout from '../../components/Layout';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { showSuccessToast, showErrorToast } from '../../utils/notifications';

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '900px', margin: '2rem auto', padding: '1rem' },
    header: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', marginBottom: '2rem', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }, // Use global .card?
    title: { marginTop: '0', marginBottom: '0.5rem' },
    metaGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.5rem 1.5rem', fontSize: '0.9em', color: '#495057', marginBottom: '1rem' },
    metaLabel: { fontWeight: '600' },
    messagesContainer: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', marginBottom: '2rem', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' },
    messageList: { maxHeight: '500px', overflowY: 'auto', marginBottom: '1.5rem', paddingRight: '10px' }, // Scrollable message list
    messageBubble: { marginBottom: '1rem', padding: '0.8rem 1.2rem', borderRadius: '15px', maxWidth: '80%', wordWrap: 'break-word', border: '1px solid #eee' },
    messageUser: { background: '#d1e7ff', borderTopLeftRadius: '0', marginLeft: 'auto', // Blueish for user's own message
        // <<< TODO: Improve styling for message alignment >>>
     },
    messageOther: { background: '#f8f9fa', borderTopRightRadius: '0', marginRight: 'auto' }, // Grayish for other party's message
    messageMeta: { fontSize: '0.75em', color: '#6c757d', marginTop: '0.3rem', textAlign: 'right' },
    messageContent: { whiteSpace: 'pre-wrap' }, // Preserve line breaks
    replyFormSection: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' },
    loadingText: { textAlign: 'center', padding: '2rem', fontStyle: 'italic', color: '#666' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' },
    closedWarning: { color: '#721c24', background: '#f8d7da', border: '1px solid #f5c6cb', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem', textAlign:'center' },
    // Use global form/button classes (.form-group, .form-label, .form-textarea, .button, .button-primary, .disabled etc.)
};


export default function TicketDetailPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();
    const { ticketId } = router.query;

    // State
    const [ticket, setTicket] = useState(null);
    const [messages, setMessages] = useState([]);
    const [replyMessage, setReplyMessage] = useState('');
    // <<< ADDED: Separate Loading/Error States >>>
    const [isLoadingTicket, setIsLoadingTicket] = useState(true);
    const [isSubmittingReply, setIsSubmittingReply] = useState(false);
    const [fetchError, setFetchError] = useState('');
    const [replyError, setReplyError] = useState('');

    // Ref for scrolling message list
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    // Fetch Ticket Details & Messages
    const fetchTicketData = useCallback(async () => {
        if (!user || !ticketId || !router.isReady) return; // Ensure prerequisites are met

        setIsLoadingTicket(true); setFetchError(''); setTicket(null); setMessages([]); // Reset state
        try {
            console.log(`Workspaceing details for ticket: ${ticketId}`); // Debug log
            // <<< SECURITY: Backend MUST verify user is requester or assignee >>>
            const data = await getTicketDetail(ticketId);
            setTicket(data.ticket);
            setMessages(data.messages || []);
        } catch (err) {
            console.error(`Failed to fetch ticket ${ticketId}:`, err);
            let errorMsg = err.message || "Could not load ticket details.";
            if (err.status === 401 || err.status === 403) errorMsg = "Permission denied to view this ticket.";
            else if (err.status === 404) errorMsg = "Ticket not found.";
            setFetchError(errorMsg); showErrorToast(errorMsg);
        } finally { setIsLoadingTicket(false); }
    }, [user, ticketId, router.isReady]); // Dependencies

    // Initial Fetch on mount and when ticketId changes
    useEffect(() => {
        if (!authIsLoading && !user) {
             router.push(`/login?next=${router.asPath}`);
        } else if (user && ticketId) {
            fetchTicketData();
        }
    }, [user, authIsLoading, router, ticketId, fetchTicketData]); // Include fetchTicketData

    // Scroll to bottom when messages load/update
    useEffect(() => {
        scrollToBottom();
    }, [messages]); // Dependency on messages array


    // Handle Reply Submission
    const handleReplySubmit = async (e) => {
        e.preventDefault();
        setReplyError(''); // Clear previous reply errors

        // <<< BEST PRACTICE: Re-check PGP Auth status just before submitting reply >>>
        if (!isPgpAuthenticated) {
            showErrorToast("PGP authenticated session required to reply.");
            setReplyError("PGP session required.");
            return;
        }
        if (!replyMessage.trim()) {
            setReplyError("Reply message cannot be empty.");
            return;
        }
        if (!ticket || ticket.status === 'closed') {
            setReplyError("Cannot reply to a closed ticket."); // Should be prevented by UI state too
            return;
        }

        setIsSubmittingReply(true);
        const replyData = { message: replyMessage.trim() };

        try {
            // <<< SECURITY: Backend validates user can reply, sanitizes message, encrypts for recipient >>>
            const newMessage = await replyToTicket(ticket.id, replyData);
            setMessages(prevMessages => [...prevMessages, newMessage]); // Add new message to list
            setReplyMessage(''); // Clear reply input field
            showSuccessToast("Reply sent successfully!");
            // Optional: Update ticket status locally if backend doesn't return full ticket object?
            // setTicket(prev => ({ ...prev, status: 'user_reply' or 'staff_reply' }));
            // Scroll to bottom after sending
            setTimeout(scrollToBottom, 100); // Small delay to allow render
        } catch (err) {
            console.error("Reply submission failed:", err);
            let errorMsg = err.message || "Failed to send reply.";
            // Parse specific backend validation if available
            if (err.status === 400 && err.data) {
                 errorMsg = err.data.detail || err.data.message?.[0] || errorMsg;
            } else if (err.status === 403) {
                 errorMsg = "Permission denied to reply to this ticket.";
            }
            setReplyError(errorMsg);
            showErrorToast(`Reply failed: ${errorMsg}`);
        } finally { setIsSubmittingReply(false); }
    };


    // --- Render Logic ---
    if (authIsLoading || isLoadingTicket) return <Layout><div style={styles.loadingText}><LoadingSpinner message="Loading ticket details..." /></div></Layout>;
    if (!user && !authIsLoading) return <Layout><div style={styles.loadingText}>Redirecting to login...</div></Layout>; // Should be redirected
    if (fetchError) return <Layout><div style={styles.container}><FormError message={fetchError} /><p className="mt-3"><Link href="/tickets">Back to Tickets</Link></p></div></Layout>;
    if (!ticket) return <Layout><div style={styles.container}><p>Ticket data could not be loaded.</p></div></Layout>; // Fallback

    // Determine if reply form should be shown
    const canReply = ticket.status !== 'closed' && user; // Basic check, backend enforces role permission

    return (
        <Layout>
            <div style={styles.container}>
                {/* Ticket Header & Metadata */}
                <div style={styles.header} className="card">
                    <h1 style={styles.title}>Ticket: {ticket.subject}</h1>
                    <div style={styles.metaGrid}>
                        <div><span style={styles.metaLabel}>Ticket ID:</span> {ticket.id?.substring(0, 8) || 'N/A'}</div>
                        <div><span style={styles.metaLabel}>Status:</span> {ticket.status_display || ticket.status}</div>
                        <div><span style={styles.metaLabel}>Requester:</span> {ticket.requester?.username || 'N/A'}</div>
                        <div><span style={styles.metaLabel}>Assignee:</span> {ticket.assignee?.username || 'Staff (Unassigned)'}</div>
                        <div><span style={styles.metaLabel}>Created:</span> {new Date(ticket.created_at).toLocaleString()}</div>
                        <div><span style={styles.metaLabel}>Last Update:</span> {new Date(ticket.updated_at).toLocaleString()}</div>
                         {ticket.related_order && <div><span style={styles.metaLabel}>Related Order:</span> <Link href={`/orders/${ticket.related_order}`}><code style={{fontSize:'1em'}}>{ticket.related_order.substring(0, 8)}...</code></Link></div>}
                    </div>
                </div>

                 {/* Messages Area */}
                <div style={styles.messagesContainer} className="card">
                    <h2 style={{marginTop: 0, marginBottom: '1.5rem'}}>Messages</h2>
                    <div style={styles.messageList}>
                         {messages.length === 0 && <p>No messages yet.</p>}
                         {messages.map(msg => {
                            const isOwnMessage = msg.sender?.id === user?.id;
                            // <<< SECURITY NOTE on PGP Decryption >>>
                            // Assuming backend's getTicketDetail API returns a 'decrypted_content' field
                            // if the message was intended for the current user AND the backend successfully
                            // decrypted it using the *MARKET's* PGP key (via pgp_service.py).
                            // We should prioritize displaying decrypted content if available.
                            // DO NOT attempt client-side decryption here.
                            const displayContent = msg.decrypted_content ?? msg.message ?? '[Content Unavailable]';

                            return (
                                <div key={msg.id} style={{ ...styles.messageBubble, ...(isOwnMessage ? styles.messageUser : styles.messageOther) }} >
                                     <div style={styles.messageContent}>{displayContent}</div>
                                     <div style={styles.messageMeta}>
                                         Sent by {msg.sender?.username || 'System'} on {new Date(msg.created_at).toLocaleString()}
                                     </div>
                                </div>
                            );
                        })}
                        {/* Dummy div to ensure scroll targets bottom */}
                        <div ref={messagesEndRef} />
                    </div>
                </div>

                {/* Reply Form Section */}
                 {canReply && (
                    <div style={styles.replyFormSection} className="card">
                        <h3>Reply to Ticket</h3>

                         {/* PGP Auth Warning for Reply */}
                         {!isPgpAuthenticated && (
                            <div style={styles.authWarning} className="warning-message">
                                <strong>PGP authenticated session required to reply.</strong> Please <Link href="/login" style={{fontWeight:'bold'}}>re-login</Link> if needed. The submit button is disabled.
                             </div>
                         )}

                         {/* Reply Error Display */}
                        <FormError message={replyError} />

                        <form onSubmit={handleReplySubmit}>
                            <div className="form-group">
                                <label htmlFor="replyMessage" className="form-label">Your Message:</label>
                                <textarea
                                    id="replyMessage"
                                    value={replyMessage}
                                    onChange={(e) => setReplyMessage(e.target.value)}
                                    required
                                    className="form-textarea"
                                    rows={6}
                                    disabled={isSubmittingReply || !isPgpAuthenticated} // Disable if submitting or no PGP auth
                                    placeholder="Enter your reply here..."
                                />
                            </div>
                            <div className="d-flex justify-content-end mt-3">
                                 <button type="submit" className={`button button-primary ${ (isSubmittingReply || !isPgpAuthenticated) ? 'disabled' : '' }`} disabled={isSubmittingReply || !isPgpAuthenticated} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}>
                                    {isSubmittingReply ? <LoadingSpinner size="1em"/> : 'Send Reply'}
                                 </button>
                            </div>
                        </form>
                    </div>
                 )}

                 {/* Indicator if ticket is closed */}
                 {!canReply && ticket?.status === 'closed' && (
                     <div style={styles.closedWarning} className="warning-message">
                         This ticket is closed and cannot be replied to. Please create a new ticket if you need further assistance.
                     </div>
                 )}

            </div>
        </Layout>
    );
}