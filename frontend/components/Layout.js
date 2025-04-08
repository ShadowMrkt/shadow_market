// frontend/components/Layout.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 3 - Integrated CanaryStatusIndicator using useSWR for data fetching.
//           - Added useSWR hook to fetch canary data within Layout.
//           - Imported getCanaryData and CanaryStatusIndicator.
//           - Replaced placeholder with actual component in the header.
//           - Passed necessary props (lastUpdated, isLoading, error) to indicator.
// 2025-04-07: Rev 2 - Migrated to CSS Modules, added logo placeholder, refined loading states, added guide links, basic a11y attributes, canary status placeholder.
//           [...]
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           [...]

import Head from 'next/head';
import Link from 'next/link';
import Image from 'next/image';
import React from 'react';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from './LoadingSpinner';
import styles from './Layout.module.css';
// --- NEW IMPORTS ---
import useSWR from 'swr';
import { getCanaryData } from '../utils/api'; // Import API function
import CanaryStatusIndicator from './CanaryStatusIndicator'; // Import the indicator component
// -------------------

// Define a simple fetcher for SWR
const fetcher = (url) => getCanaryData(); // getCanaryData already uses apiRequest

export default function Layout({ children }) {
    const { user, logout, isLoading: authIsLoading } = useAuth();
    const currentYear = new Date().getFullYear();

    // --- NEW: Fetch Canary Data using SWR ---
    const {
        data: canaryData,
        error: canaryError,
        isValidating: canaryIsValidating // True on load & revalidations
    } = useSWR(
        'canaryData', // Simple cache key for global canary data
        fetcher,
        {
            // Optional: configure revalidation intervals, etc.
            revalidateOnFocus: true, // Revalidate when window gets focus
            // refreshInterval: 300000 // Revalidate every 5 minutes (example)
        }
    );
    // Determine loading state specifically for the *initial* fetch
    const isCanaryLoading = canaryIsValidating && !canaryData && !canaryError;
    // ----------------------------------------

    return (
        <>
            <Head>
                <title>Shadow Market</title>
                <meta name="description" content="The most secure darknet market." />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <link rel="icon" href="/favicon.ico" />
            </Head>

            <div className={styles.layoutContainer}>
                <header className={styles.header} role="banner">
                    <nav className={styles.navbar} aria-label="Main Navigation">
                        {/* Left Section: Logo and Core Links */}
                        <div className={styles.navSection}>
                             <Link href="/" className={styles.logoLink}>
                                <Image
                                    src="/images/logo-placeholder.png" // TODO: Replace with actual logo path
                                    alt="Shadow Market Logo"
                                    width={150} height={40} priority
                                />
                            </Link>
                            <Link href="/products" className={styles.navLink}>Products</Link>
                            {/* TODO: Add other core navigation links */}
                        </div>

                        {/* Center Section: Search Bar Placeholder */}
                        <div className={styles.navSection}>
                             {/* TODO: Implement Search Component */}
                             {/* <SearchComponent /> */}
                             <span style={{color: '#888'}}>{/* Placeholder */}</span>
                        </div>

                        {/* Right Section: Auth, Actions, Canary */}
                        <div className={`${styles.navSection} ${styles.authSection}`}>
                            {authIsLoading ? (
                                <LoadingSpinner size="small" />
                            ) : user ? (
                                <>
                                    {/* Conditionally render based on PGP status if needed */}
                                    {/* {!isPgpAuthenticated && <span title="PGP Session Needed">⚠️</span>} */}
                                    <Link href="/profile" className={styles.navLink} title={`Logged in as ${user.username}`}>Profile</Link>
                                    <Link href="/orders" className={styles.navLink}>Orders</Link>
                                    <Link href="/wallet" className={styles.navLink}>Wallet</Link>
                                    {/* Link to Support Tickets if implemented */}
                                    {/* <Link href="/tickets" className={styles.navLink}>Support</Link> */}
                                    <button onClick={logout} className={`${styles.button} ${styles.buttonSecondary}`} title="Logout">Logout</button>
                                </>
                            ) : (
                                <>
                                    <Link href="/login" className={styles.navLink}>Login</Link>
                                    <Link href="/register" className={styles.navLink}>Register</Link>
                                </>
                            )}
                            {/* --- Render Canary Status Indicator --- */}
                            {/* Remove the old placeholder: <span className={styles.canaryPlaceholder}>[C]</span> */}
                            <CanaryStatusIndicator
                                lastUpdated={canaryData?.canary_last_updated}
                                isLoading={isCanaryLoading} // Pass initial loading state
                                error={canaryError}
                                className={styles.canaryIndicatorHeader} // Add optional specific class if needed for spacing/positioning
                            />
                            {/* ------------------------------------ */}
                        </div>
                    </nav>
                    {/* TODO: Integrate SessionTimeoutWarning component if needed */}
                </header>

                <main className={styles.mainContent}>
                    {authIsLoading ? ( // Show main loading only for initial auth check
                        <div className={styles.loadingPlaceholder}>
                            <LoadingSpinner message="Loading application..." />
                        </div>
                    ) : (
                        children // Render page content
                    )}
                </main>

                <footer className={styles.footer} role="contentinfo">
                    <div className={styles.footerLinks}>
                         <Link href="/rules" className={styles.footerLink}>Rules</Link>
                         <Link href="/faq" className={styles.footerLink}>FAQ</Link>
                         <Link href="/pgp-guide" className={styles.footerLink}>PGP Guide</Link>
                         <Link href="/canary" className={styles.footerLink}>Canary</Link>
                         {/* Add other links */}
                    </div>
                    <div className={styles.footerCopyright}>
                        © Shadow Market {currentYear} - Security First.
                    </div>
                </footer>
            </div>
        </>
    );
}

// TODO: Add optional .canaryIndicatorHeader style to Layout.module.css if needed for positioning.
// TODO: Ensure getCanaryData API function exists and returns { canary_last_updated: "YYYY-MM-DD" }.
// TODO: Implement SearchComponent and SessionTimeoutWarning.