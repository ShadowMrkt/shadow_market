// frontend/components/CanaryStatusIndicator.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Initial implementation.
//           - Displays status (Valid, Due, Expired) based on lastUpdated prop.
//           - Links to /canary page.
//           - Uses CSS Modules for styling and dark theme integration.
//           - Includes loading and error states.

import React from 'react';
import Link from 'next/link';
import { formatDate } from '../utils/formatters'; // Use shared formatter
import styles from './CanaryStatusIndicator.module.css'; // Import CSS Module

// --- Configuration (Consider moving to constants.js if shared) ---
const UPDATE_WARNING_DAYS = 14; // Show warning if not updated in this many days
const EXPIRY_DAYS = 30; // Show expired if not updated in this many days
// -----------------------------------------------------------------

/**
 * Calculates the status of the canary based on the last updated date.
 * @param {string | Date | null} lastUpdatedDate - The ISO string or Date object of the last update.
 * @returns {'VALID' | 'UPDATE_DUE' | 'EXPIRED' | 'INVALID_DATE' | 'MISSING'} Status string.
 */
const getCanaryStatus = (lastUpdatedDate) => {
    if (!lastUpdatedDate) {
        return 'MISSING'; // Data not provided
    }
    try {
        const lastUpdate = new Date(lastUpdatedDate);
        if (isNaN(lastUpdate.getTime())) {
             return 'INVALID_DATE'; // Date string was invalid
        }

        const now = new Date();
        const diffTime = now.getTime() - lastUpdate.getTime();
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); // Difference in days

        if (diffDays > EXPIRY_DAYS) {
            return 'EXPIRED';
        } else if (diffDays > UPDATE_WARNING_DAYS) {
            return 'UPDATE_DUE';
        } else {
            return 'VALID';
        }
    } catch (e) {
        console.error("Error calculating canary status:", e);
        return 'INVALID_DATE'; // Error during date parsing/calculation
    }
};


/**
 * Displays a status indicator for the Warrant Canary.
 * Assumes canary data (lastUpdated date) is fetched elsewhere and passed as props.
 *
 * @param {object} props - Component props.
 * @param {string | null | undefined} props.lastUpdated - ISO date string of the canary's last update.
 * @param {boolean} [props.isLoading=false] - Whether the canary data is currently loading.
 * @param {any} [props.error=null] - Any error object/message if fetching failed.
 * @param {string} [props.className=''] - Optional additional class names for the container.
 * @returns {React.ReactElement | null} The canary status indicator component.
 */
const CanaryStatusIndicator = ({ lastUpdated, isLoading = false, error = null, className = '' }) => {

    let status = 'LOADING';
    let statusText = 'Loading...';
    let statusClass = styles.statusLoading;
    let titleText = 'Loading canary status...';

    if (isLoading) {
        // Keep default loading state
    } else if (error) {
        status = 'ERROR';
        statusText = 'Error';
        statusClass = styles.statusError;
        titleText = `Error loading canary: ${error?.message || 'Unknown error'}`;
    } else {
        const calculatedStatus = getCanaryStatus(lastUpdated);
        const formattedDate = formatDate(lastUpdated) || 'N/A'; // Format date if available

        switch (calculatedStatus) {
            case 'VALID':
                status = 'VALID';
                statusText = 'Canary Valid';
                statusClass = styles.statusValid;
                titleText = `Warrant Canary Valid: Last Updated ${formattedDate}`;
                break;
            case 'UPDATE_DUE':
                status = 'UPDATE_DUE';
                statusText = 'Canary Update Due';
                statusClass = styles.statusWarning;
                titleText = `Warrant Canary Update Recommended: Last Updated ${formattedDate} (over ${UPDATE_WARNING_DAYS} days ago)`;
                break;
            case 'EXPIRED':
                status = 'EXPIRED';
                statusText = 'Canary Expired';
                statusClass = styles.statusExpired;
                titleText = `WARRANT CANARY EXPIRED: Last Updated ${formattedDate} (over ${EXPIRY_DAYS} days ago). Exercise caution!`;
                break;
            case 'MISSING':
                status = 'ERROR'; // Treat missing data after load as an error state
                statusText = 'No Data';
                statusClass = styles.statusError;
                titleText = 'Warrant canary data is unavailable.';
                break;
            case 'INVALID_DATE':
            default:
                status = 'ERROR';
                statusText = 'Date Error';
                statusClass = styles.statusError;
                titleText = 'Warrant canary date is invalid or could not be parsed.';
                break;
        }
    }

    return (
        // Link the whole indicator to the canary page
        <Link href="/canary" passHref legacyBehavior>
            <a
                className={`${styles.indicator} ${statusClass} ${className}`}
                title={titleText} // Provide detailed info on hover
                aria-label={titleText} // Make screen readers announce the status
            >
                {/* Optionally add an icon based on status */}
                 <span className={styles.icon}>
                    {status === 'VALID' ? '✅' : status === 'UPDATE_DUE' ? '⚠️' : status === 'EXPIRED' ? '❌' : status === 'ERROR' ? '❓' : '⏳'}
                 </span>
                 <span className={styles.statusText}>{statusText}</span>
                {/* Optionally display date, might make indicator too large for header/footer */}
                 {/* {status !== 'LOADING' && status !== 'ERROR' && lastUpdated && (
                     <span className={styles.lastUpdatedDate}>({formatDate(lastUpdated)})</span>
                 )} */}
            </a>
        </Link>
    );
};

export default CanaryStatusIndicator;

// TODO: Create CanaryStatusIndicator.module.css with styles for .indicator, .icon, .statusText,
//       and status-specific classes (.statusLoading, .statusValid, .statusWarning, .statusExpired, .statusError)
//       using CSS variables for dark theme colors (green, yellow, red, grey).
// TODO: Ensure the parent component (e.g., _app.js or Layout) fetches canary data (lastUpdated)
//       and passes it down as props, along with loading/error state.