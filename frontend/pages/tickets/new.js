// frontend/pages/tickets/new.js
// <<< REVISED FOR ENTERPRISE GRADE: Auth Checks, Clearer Feedback, Error Handling >>>

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link'; // Keep Link for navigation
import { useAuth } from '../../context/AuthContext'; // <<< Ensure path is correct >>>
// <<< UPDATED: Import API, components, notifications >>>
import { createTicket } from '../../utils/api';
import Layout from '../../components/Layout';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { showSuccessToast, showErrorToast } from '../../utils/notifications';

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '700px', margin: '2rem auto', padding: '1rem' },
    formContainer: { background: '#ffffff', padding: '2rem', borderRadius: '8px', border: '1px solid #dee2e6', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }, // Use global .card?
    title: { textAlign: 'center', marginBottom: '1.5rem' },
    authWarning: { color: '#856404', background: '#fff3cd', border: '1px solid #ffeeba', padding: '1rem', borderRadius: '4px', marginBottom: '1.5rem' }, // Use global .warning-message
    // Use global form/button classes (.form-group, .form-label, .form-input, .form-textarea, .button, .button-primary, .disabled etc.)
};

export default function NewTicketPage() {
    const { user, isPgpAuthenticated, isLoading: authIsLoading } = useAuth();
    const router = useRouter();

    // Form State
    const [subject, setSubject] = useState('');
    const [message, setMessage] = useState('');
    const [relatedOrderId, setRelatedOrderId] = useState(''); // Optional

    // General State
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    // Redirect if not logged in
    useEffect(() => {
        if (!authIsLoading && !user) {
            router.push('/login?next=/tickets/new');
        }
    }, [user, authIsLoading, router]);

    // Handle Form Submission
    const handleSubmit = async (e) => {
        e.preventDefault();
        setError(''); // Clear previous errors

        // <<< BEST PRACTICE: Re-check PGP Auth status just before submitting >>>
        if (!isPgpAuthenticated) {
            showErrorToast("PGP authenticated session required to create a ticket.");
            setError("PGP session required.");
            return;
        }

        // <<< Add basic client-side validation >>>
        if (!subject.trim() || !message.trim()) {
            setError("Subject and Message fields are required.");
            return;
        }
        // Optional: Add length limits checks if desired (backend should enforce too)

        setIsLoading(true);
        const ticketData = {
            subject: subject.trim(),
            message: message.trim(),
            // Send related_order_id only if provided and potentially validated format-wise
            // Backend should fully validate the ID existence and user's relation to it
            related_order_id: relatedOrderId.trim() || null,
        };

        try {
            // <<< SECURITY: Backend MUST validate/sanitize inputs and requires PGP auth >>>
            const newTicket = await createTicket(ticketData);
            showSuccessToast("Support ticket created successfully!");
            // Redirect to the newly created ticket's detail page
            router.push(`/tickets/${newTicket.id}`);
            // No need to setIsLoading(false) as we are redirecting
        } catch (err) {
            console.error("Create ticket failed:", err);
            let errorMsg = err.message || "Failed to create ticket.";
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
            showErrorToast(`Ticket creation failed: ${errorMsg.substring(0, 100)}${errorMsg.length > 100 ? '...' : ''}`);
            setIsLoading(false); // Keep loading false on error
        }
    };


    // --- Render Logic ---
    if (authIsLoading) return <Layout><div style={styles.loadingText}><LoadingSpinner message="Loading..." /></div></Layout>;
    if (!user && !authIsLoading) return <Layout><div style={styles.loadingText}>Redirecting to login...</div></Layout>;

    const isSubmitDisabled = isLoading || !isPgpAuthenticated;

    return (
        <Layout>
            <div style={styles.container}>
                <div style={styles.formContainer} className="card"> {/* Use global class */}
                    <h1 style={styles.title}>Create New Support Ticket</h1>

                    {/* PGP Auth Warning */}
                    {!isPgpAuthenticated && (
                        <div style={styles.authWarning} className="warning-message">
                            <strong>Security Notice:</strong> Your session is not PGP authenticated. You cannot create a ticket without completing the PGP login challenge. Please <Link href="/login" style={{fontWeight:'bold'}}>re-login</Link> if needed. The submit button is disabled.
                        </div>
                    )}

                    <FormError message={error} />

                    <form onSubmit={handleSubmit}>
                        {/* Subject */}
                        <div className="form-group mb-3">
                            <label htmlFor="subject" className="form-label">Subject*</label>
                            <input
                                type="text"
                                id="subject"
                                value={subject}
                                onChange={(e) => setSubject(e.target.value)}
                                required
                                className="form-input"
                                disabled={isLoading}
                                maxLength={100} // Example limit
                            />
                        </div>

                        {/* Message */}
                        <div className="form-group mb-3">
                            <label htmlFor="message" className="form-label">Message*</label>
                            <textarea
                                id="message"
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                required
                                className="form-textarea"
                                rows={10}
                                disabled={isLoading}
                                placeholder="Please provide as much detail as possible..."
                            />
                        </div>

                        {/* Related Order ID (Optional) */}
                        <div className="form-group mb-4">
                             <label htmlFor="relatedOrderId" className="form-label">Related Order ID (Optional)</label>
                             <input
                                type="text" // Or search/select if implemented
                                id="relatedOrderId"
                                value={relatedOrderId}
                                onChange={(e) => setRelatedOrderId(e.target.value)}
                                className="form-input"
                                disabled={isLoading}
                                placeholder="Enter Order ID if applicable (e.g., a1b2c3d4...)"
                             />
                             <p className="form-help-text">If this ticket relates to a specific order, please enter its ID.</p>
                        </div>

                         {/* Submit Button */}
                        <div className="d-flex justify-content-end gap-2">
                             <Link href="/tickets" className={`button button-secondary ${isLoading ? 'disabled' : ''}`}>Cancel</Link>
                             <button type="submit" className={`button button-primary ${isSubmitDisabled ? 'disabled' : ''}`} disabled={isSubmitDisabled} title={!isPgpAuthenticated ? "Requires PGP Authenticated Session" : ""}>
                                {isLoading ? <LoadingSpinner size="1em"/> : 'Create Ticket'}
                             </button>
                        </div>
                    </form>
                </div>
            </div>
        </Layout>
    );
}