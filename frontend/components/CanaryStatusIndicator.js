// frontend/components/CanaryStatusIndicator.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 4 - Fixed nested <a> tag issue by removing the explicit <a> child of <Link> and applying props directly to <Link>. Removed unnecessary `passHref`.
//                         - Added note re-emphasizing that CSS Module class assertion failures must be fixed in the test file.
// 2025-04-13 (Gemini): Rev 3 - Attempted fix for nested <a> tag issue by removing `legacyBehavior` prop from next/link, keeping `passHref`. (Incorrect approach).
//                         - Added comment clarifying that test failures for CSS classes are due to incorrect assertions in the test file needing update for CSS Modules.
// 2025-04-13: Rev 2 - Moved formatDate call inside switch cases to avoid calling it with invalid dates.
//                  - Confirmed status logic correctly maps to CSS module classes; test failures likely due to incorrect assertions in test file.
//                  - Added aria-hidden to icon span.
// 2025-04-07: Rev 1 - Initial implementation.
//                  - Displays status (Valid, Due, Expired) based on lastUpdated prop.
//                  - Links to /canary page.
//                  - Uses CSS Modules for styling and dark theme integration.
//                  - Includes loading and error states.

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
        // Important: Compare dates directly, avoid time zone issues if possible,
        // or ensure consistent timezone handling (e.g., UTC) if needed.
        // For simplicity, assuming local time comparison is sufficient here.
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
    let icon = '⏳'; // Default loading icon
    // --- Rev 4: Added variable to hold calculated status for clarity ---
    let calculatedStatus = 'LOADING';

    if (isLoading) {
        // Keep default loading state set above
    } else if (error) {
        calculatedStatus = 'ERROR'; // Explicitly set calculatedStatus
        status = 'ERROR';
        statusText = 'Error';
        statusClass = styles.statusError;
        titleText = `Error loading canary: ${error?.message || 'Unknown error'}`;
        icon = '❓';
    } else {
        calculatedStatus = getCanaryStatus(lastUpdated); // Get status
        // --- Rev 2: Only format date when needed and valid ---
        let formattedDate = 'N/A'; // Default for cases where date is invalid/missing

        switch (calculatedStatus) {
            case 'VALID':
                formattedDate = formatDate(lastUpdated); // Format valid date
                status = 'VALID';
                statusText = 'Canary Valid';
                statusClass = styles.statusValid;
                titleText = `Warrant Canary Valid: Last Updated ${formattedDate}`;
                icon = '✅';
                break;
            case 'UPDATE_DUE':
                formattedDate = formatDate(lastUpdated); // Format valid date
                status = 'UPDATE_DUE';
                statusText = 'Canary Update Due';
                statusClass = styles.statusWarning;
                titleText = `Warrant Canary Update Recommended: Last Updated ${formattedDate} (over ${UPDATE_WARNING_DAYS} days ago)`;
                icon = '⚠️';
                break;
            case 'EXPIRED':
                formattedDate = formatDate(lastUpdated); // Format valid (but old) date
                status = 'EXPIRED';
                statusText = 'Canary Expired';
                statusClass = styles.statusExpired;
                titleText = `WARRANT CANARY EXPIRED: Last Updated ${formattedDate} (over ${EXPIRY_DAYS} days ago). Exercise caution!`;
                icon = '❌';
                break;
            case 'MISSING':
                status = 'ERROR'; // Treat missing data after load as an error state
                statusText = 'No Data';
                statusClass = styles.statusError;
                titleText = 'Warrant canary data is unavailable.';
                icon = '❓';
                break;
            case 'INVALID_DATE':
            default:
                status = 'ERROR';
                statusText = 'Date Error';
                statusClass = styles.statusError;
                titleText = 'Warrant canary date is invalid or could not be parsed.';
                icon = '❓';
                break;
        }
    }

    // --- Rev 3/4 NOTE FOR TEST FILE ---
    // The component correctly applies CSS Module classes (e.g., styles.indicator, styles.statusValid).
    // Test failures for `toHaveClass("statusValid")` etc. in `CanaryStatusIndicator.test.js`
    // occur because the test asserts against plain strings instead of the generated CSS module class names.
    // The test file (`components/CanaryStatusIndicator.test.js`) MUST be updated:
    // 1. Import the styles: `import styles from './CanaryStatusIndicator.module.css';`
    // 2. Assert against the imported styles: `expect(link).toHaveClass(styles.statusValid);`
    //    and `expect(link).toHaveClass(styles.indicator, styles.statusValid, customClass);` etc.
    // ----

    // --- Rev 4: Let Link render the anchor tag. Apply props directly to Link. ---
    return (
        <Link
            href="/canary"
            className={`${styles.indicator} ${statusClass} ${className}`}
            title={titleText} // Provide detailed info on hover
            aria-label={titleText} // Make screen readers announce the status
        >
            <span className={styles.icon} aria-hidden="true">{icon}</span>
            <span className={styles.statusText}>{statusText}</span>
            {/* Optional: Display date - Uncomment and ensure formatDate logic is robust if needed */}
            {/* {status !== 'LOADING' && status !== 'ERROR' && lastUpdated && calculatedStatus !== 'MISSING' && calculatedStatus !== 'INVALID_DATE' && (
                  <span className={styles.lastUpdatedDate}>({formatDate(lastUpdated)})</span>
            )} */}
        </Link>
    );
};

export default CanaryStatusIndicator;

// TODO: Create CanaryStatusIndicator.module.css with styles for .indicator, .icon, .statusText,
//       and status-specific classes (.statusLoading, .statusValid, .statusWarning, .statusExpired, .statusError)
//       using CSS variables for dark theme colors (green, yellow, red, grey).
// TODO: Ensure the parent component (e.g., _app.js or Layout) fetches canary data (lastUpdated)
//       and passes it down as props, along with loading/error state.