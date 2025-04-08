// frontend/pages/vendors/[username].js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Added revision history, refined error handling, added feedback SWR structure.
//           - Improved clarity of loading/error messages.
//           - Added SWR hook structure to VendorFeedbackSection (API call commented out).
//           - Added/refined comments regarding SWR usage and TODOs.
//           - Verified component props and imports.

import React, { useState, useMemo } from 'react';
import { useRouter } from 'next/router';
import useSWR, { SWRConfig } from 'swr'; // Import SWRConfig for potential SSR fallback usage

// API Utils - Assuming these fetch data
// TODO: Ensure getFeedback exists in api.js or implement it.
import { getVendorPublicProfile, getProducts /*, getFeedback */ } from '../../utils/api';

// Constants
import { DEFAULT_PAGE_SIZE } from '../../utils/constants';

// Components
import Layout from '../../components/Layout';
import ProductCard from '../../components/ProductCard';
import PaginationControls from '../../components/PaginationControls';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError'; // Import if using for errors

// Utils & Styles
import { formatDate, renderStars } from '../../utils/formatters';
import styles from '../../styles/VendorProfile.module.css'; // Assuming CSS module exists

// --- Helper Fetchers for SWR ---
// Defined outside components or imported if centralized
const profileFetcher = (username) => getVendorPublicProfile(username);

const productsFetcher = (username, page) => {
    const params = { vendor__username: username, is_active: true, page: page, page_size: DEFAULT_PAGE_SIZE };
    return getProducts(params); // Assumes getProducts handles pagination structure
};

// TODO: Implement getFeedback in utils/api.js
// const feedbackFetcher = (username, page) => {
//     const params = { recipient_username: username, page: page, page_size: DEFAULT_PAGE_SIZE };
//     // return getFeedback(params); // Call the actual API function
//     // Placeholder data for testing:
//     return Promise.resolve({
//         count: 0, next: null, previous: null, results: [
//             // { id: 1, rating: 5, comment: 'Great vendor!', reviewer: { username: 'Buyer1'}, created_at: new Date().toISOString() },
//             // { id: 2, rating: 4, comment: null, reviewer: { username: 'Buyer2'}, created_at: new Date().toISOString() },
//         ]
//     });
// };


// --- Sub-Components ---

const VendorProfileHeader = ({ profile }) => {
    if (!profile) return null;

    return (
        <header className={styles.profileHeader}> {/* Use header element */}
            <h1 className={styles.username}>{profile.username}</h1>
            <p className={styles.metaInfo}>
                {profile.vendor_level_name || 'Vendor'} |
                Joined: {formatDate(profile.date_joined)} |
                Approved Since: {formatDate(profile.approved_vendor_since)} |
                Last Seen: {formatDate(profile.last_seen) || 'Never'}
            </p>
            {/* Stats Grid */}
            <div className={styles.statsGrid}>
                <div className={styles.statItem}>
                    <span className={styles.statValue}>{renderStars(profile.vendor_avg_rating)}</span>
                    <span className={styles.statLabel}>Avg Rating ({profile.vendor_rating_count ?? 0})</span>
                </div>
                <div className={styles.statItem}>
                    <span className={styles.statValue}>{profile.vendor_total_orders ?? 'N/A'}</span>
                    <span className={styles.statLabel}>Total Orders</span>
                </div>
                <div className={styles.statItem}>
                    <span className={styles.statValue}>{profile.vendor_completion_rate_percent?.toFixed(1) ?? 'N/A'}%</span>
                    <span className={styles.statLabel}>Completion Rate</span>
                </div>
                <div className={styles.statItem}>
                    <span className={styles.statValue}>{profile.vendor_dispute_rate_percent?.toFixed(1) ?? 'N/A'}%</span>
                    <span className={styles.statLabel}>Dispute Rate</span>
                </div>
                 <div className={styles.statItem}>
                     <span className={styles.statValue}>{profile.vendor_bond_paid ? 'Yes' : 'No'}</span>
                     <span className={styles.statLabel}>Bond Paid</span>
                 </div>
                  <div className={styles.statItem}>
                      <span className={styles.statValue}>{profile.vendor_completed_orders_30d ?? 'N/A'}</span>
                      <span className={styles.statLabel}>Sales (30d)</span>
                  </div>
            </div>
            {profile.vendor_reputation_last_updated && (
                <p className={styles.reputationUpdated}>
                    <small>Stats updated: {formatDate(profile.vendor_reputation_last_updated)}</small>
                </p>
            )}
            {/* PGP Key Section */}
            {profile.pgp_public_key && (
                <div className={styles.pgpKeySection}>
                    <details>
                        <summary className={styles.pgpKeySummary}>Show PGP Public Key</summary>
                        {/* Use global code-block style */}
                        <pre className={`code-block ${styles.pgpKeyBlock}`}><code>{profile.pgp_public_key}</code></pre>
                        {/* TODO: Add a "Copy Key" button? */}
                    </details>
                </div>
            )}
             {/* Vendor Policies/Description */}
             {profile.vendor_profile_description && (
                 <div className={styles.vendorDescription}>
                    <h2>About this Vendor</h2>
                    {/* SECURITY: Ensure backend sanitizes this HTML or render as plain text */}
                    <div dangerouslySetInnerHTML={{ __html: profile.vendor_profile_description }} />
                    {/* Or Safter: <p>{profile.vendor_profile_description}</p> */}
                 </div>
             )}
        </header>
    );
};

const VendorProductList = ({ username, profileLoaded }) => {
    const [page, setPage] = useState(1);

    const swrKey = username ? ['vendorProducts', username, page] : null;
    const { data: productsData, error: productsError, isValidating: isLoadingProducts } = useSWR(
        swrKey,
        () => productsFetcher(username, page),
        { revalidateOnFocus: false, keepPreviousData: true } // keepPreviousData prevents UI flashing on page change
    );

    const products = productsData?.results || [];
    const totalCount = productsData?.count || 0;
    const totalPages = totalCount > 0 ? Math.ceil(totalCount / DEFAULT_PAGE_SIZE) : 0;
    const hasNext = !!productsData?.next;
    const hasPrevious = !!productsData?.previous;

    // Memoize handlers
    const paginationHandlers = useMemo(() => ({
        onPrevious: () => { if (hasPrevious) setPage(prev => Math.max(1, prev - 1)); },
        onNext: () => { if (hasNext) setPage(prev => prev + 1); },
    }), [hasNext, hasPrevious]);

    // Only render section if profile is loaded, prevents potential duplicate rendering/layout shifts
    if (!profileLoaded) return null;

    return (
        <section aria-labelledby={`vendor-products-heading-${username}`} aria-live="polite" aria-busy={isLoadingProducts}>
            <h2 id={`vendor-products-heading-${username}`} className={styles.sectionTitle}>Listings from {username}</h2>
            {/* Show spinner overlay only if loading initial data OR if revalidating without previous data */}
            {(isLoadingProducts && !productsData) && <div className={styles.loadingOverlay}><LoadingSpinner message="Loading products..." /></div>}
            {productsError && <FormError message={`Could not load products: ${productsError.message}`} className={styles.errorMessage} />}
            {!isLoadingProducts && !productsError && products.length === 0 && (
                <p className={styles.noItemsMessage}>This vendor has no active listings.</p>
            )}
            {products.length > 0 && (
                <>
                    <div className={styles.productList}>
                        {products.map(product => (
                            <ProductCard key={product.id || product.slug} product={product} />
                        ))}
                    </div>
                    <PaginationControls
                        currentPage={page}
                        totalPages={totalPages}
                        totalCount={totalCount}
                        onPrevious={paginationHandlers.onPrevious}
                        onNext={paginationHandlers.onNext}
                        isLoading={isLoadingProducts && !!productsData} // Indicate loading only during revalidation if data exists
                        hasNext={hasNext}
                        hasPrevious={hasPrevious}
                    />
                </>
            )}
        </section>
    );
};

const VendorFeedbackSection = ({ username, profileLoaded, feedbackCount }) => {
    const [page, setPage] = useState(1);

    // SWR setup for feedback (API call commented out until implemented)
    const swrKey = username ? ['vendorFeedback', username, page] : null;
    // TODO: Uncomment fetcher call when getFeedback API function is ready
    const fetcherFn = () => Promise.resolve({ count: 0, next: null, previous: null, results: [] }); // Placeholder
    // const fetcherFn = () => feedbackFetcher(username, page);
    const { data: feedbackData, error: feedbackError, isValidating: isLoadingFeedback } = useSWR(
        swrKey,
        fetcherFn,
        { revalidateOnFocus: false, keepPreviousData: true }
    );

    const feedback = feedbackData?.results || [];
    const totalCount = feedbackData?.count || feedbackCount || 0; // Use profile count as fallback total
    const totalPages = totalCount > 0 ? Math.ceil(totalCount / DEFAULT_PAGE_SIZE) : 0;
    const hasNext = !!feedbackData?.next;
    const hasPrevious = !!feedbackData?.previous;

    // Memoize handlers
    const paginationHandlers = useMemo(() => ({
        onPrevious: () => { if (hasPrevious) setPage(prev => Math.max(1, prev - 1)); },
        onNext: () => { if (hasNext) setPage(prev => prev + 1); },
    }), [hasNext, hasPrevious]);


    // Only render section if profile is loaded
    if (!profileLoaded) return null;

    return (
        <section aria-labelledby={`vendor-feedback-heading-${username}`} aria-live="polite" aria-busy={isLoadingFeedback}>
             <h2 id={`vendor-feedback-heading-${username}`} className={styles.sectionTitle}>Feedback ({totalCount})</h2>
             {(isLoadingFeedback && !feedbackData) && <div className={styles.loadingOverlay}><LoadingSpinner message="Loading feedback..." /></div>}
             {feedbackError && <FormError message={`Could not load feedback: ${feedbackError.message}`} className={styles.errorMessage}/>}
             {!isLoadingFeedback && !feedbackError && feedback.length === 0 && (
                 <p className={styles.noItemsMessage}>No feedback available for this vendor yet.</p>
             )}
             {feedback.length > 0 && (
                 <>
                     <ul className={styles.feedbackList}>
                         {feedback.map(fb => (
                            <li key={fb.id} className={styles.feedbackItem}>
                                 <div className={styles.feedbackRating}>Rating: {renderStars(fb.rating)}</div>
                                 {fb.comment && <p className={styles.feedbackComment}>{fb.comment}</p>}
                                 <p className={styles.feedbackMeta}>
                                     By: {fb.reviewer?.username || 'Anonymous'} on {formatDate(fb.created_at)}
                                     {/* Optionally link to product if feedback includes it */}
                                     {/* {fb.product && ` | For: ${fb.product.name}`} */}
                                 </p>
                             </li>
                         ))}
                     </ul>
                      <PaginationControls
                        currentPage={page}
                        totalPages={totalPages}
                        totalCount={totalCount}
                        onPrevious={paginationHandlers.onPrevious}
                        onNext={paginationHandlers.onNext}
                        isLoading={isLoadingFeedback && !!feedbackData} // Indicate loading only during revalidation
                        hasNext={hasNext}
                        hasPrevious={hasPrevious}
                    />
                 </>
             )}
        </section>
    );
};

// --- Main Page Component ---

export default function VendorProfilePage() {
    const router = useRouter();
    // Ensure username is treated as a string, handle potential array from query
    const username = Array.isArray(router.query.username) ? router.query.username[0] : router.query.username;

    // Fetch Vendor Profile using SWR
    const {
        data: vendorProfile,
        error: profileError,
        isValidating: isLoadingProfile // Use isValidating which is true on initial load & revalidations
    } = useSWR(
        // Key is null if username isn't ready, preventing fetch
        username ? ['vendorProfile', username] : null,
        () => profileFetcher(username),
        {
            revalidateOnFocus: false, // Sensible default for profile data
            shouldRetryOnError: false // Don't retry if vendor not found (404)
        }
    );

    // Determine overall page state for initial load message
    // isLoading is true only during the very first fetch when no data/error exists yet.
    const isLoading = isLoadingProfile && !vendorProfile && !profileError;
    const profileLoadFailed = !!profileError && !vendorProfile; // Error occurred before any data was loaded
    const profileLoadedSuccessfully = !!vendorProfile; // Profile data is available (might still have an error from revalidation)

    // --- Render Logic ---
    const renderContent = () => {
        if (isLoading) {
             // Use centered spinner for initial page load
            return <div className={styles.fullPageLoader}><LoadingSpinner message={`Loading profile for ${username}...`} /></div>;
        }

        if (profileLoadFailed) {
            // Extract status for specific error message
            const status = profileError.response?.status || (profileError.message === 'Not Found' ? 404 : null); // Check common ways API client might surface status
            const errorMessage = status === 404
                ? `Vendor "${username}" not found.`
                : (profileError.message || `Could not load profile for vendor "${username}". Please try again later.`);
            return <FormError message={errorMessage} className={styles.errorMessage} />;
        }

        if (!vendorProfile) {
             // Fallback if loading finished but profile is still null/undefined (shouldn't happen ideally)
             return <FormError message={`Vendor profile data is unavailable for "${username}".`} className={styles.errorMessage} />;
        }

        // Profile loaded successfully, render sections
        return (
            <>
                <VendorProfileHeader profile={vendorProfile} />
                {/* Pass username and profileLoaded flag to child components */}
                <VendorProductList username={username} profileLoaded={profileLoadedSuccessfully} />
                <VendorFeedbackSection
                    username={username}
                    profileLoaded={profileLoadedSuccessfully}
                    feedbackCount={vendorProfile.vendor_rating_count} // Pass initial count from profile
                />
            </>
        );
    };

    return (
        <Layout>
            {/* Use global container class */}
            <div className="container">
                {renderContent()}
            </div>
        </Layout>
    );
}

// --- SSR/ISR Option ---
// Uncomment and adapt if needed for SEO or faster initial profile load.
// Remember to install SWRConfig in _app.js or wrap the component here if using fallback.
/*
export async function getServerSideProps(context) {
    const { username } = context.params;
    let profile = null;
    let ssrError = null;

    try {
        profile = await getVendorPublicProfile(username);
    } catch (error) {
        console.error(`SSR Error fetching profile for ${username}:`, error);
        const status = error.response?.status || (error.message === 'Not Found' ? 404 : 500);
        if (status === 404) {
             return { notFound: true }; // Return 404 page
        }
        ssrError = `Failed to load profile data server-side (Status: ${status})`;
    }

    return {
        props: {
            // Pass initial data to SWR fallback or directly to component
            // Using fallback is generally preferred with SWR
            fallback: profile ? { [`vendorProfile/${username}`]: profile } : {}, // SWR key needs to match client-side EXACTLY
            username, // Pass username from params
            ssrError // Pass error if occurred during SSR fetch
        },
    };
}

// If using SSR/ISR with SWR fallback:
// export default function VendorProfilePage({ fallback, username, ssrError }) { // Receive props
//     // Check for SSR error first
//     if (ssrError) {
//         return <Layout><div className="container"><FormError message={ssrError} /></div></Layout>;
//     }
//
//     return (
//         // Wrap component content with SWRConfig to provide fallback data
//         <SWRConfig value={{ fallback }}>
//             <Layout>
//                 <div className="container">
//                     { // Conditionally render the main content based on username prop
//                       // The useSWR hook inside will pick up fallback data
//                       username ? <VendorProfileContent username={username} /> : <FormError message="Username not provided."/>
//                     }
//                 </div>
//             </Layout>
//         </SWRConfig>
//     );
// }
// // Define VendorProfileContent component containing the original component logic using useSWR
// const VendorProfileContent = ({ username }) => { ... component logic using useSWR ... };
*/