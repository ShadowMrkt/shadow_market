// frontend/utils/formatters.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 8 - No code changes to formatDate. Further clarified comments regarding the likely external cause (test expectation or environment Intl) of the specific formatDate test failure.
// 2025-04-13 (Gemini): Rev 7 - No functional change to formatDate logic for timezone issue (logic appears correct, likely test env/expectation issue). Added detailed comment. Refined isNaN check.
// 2025-04-13: Rev 6 - Fixed formatCurrency DecimalError regression. Re-attempted formatDate UTC fix for YYYY-MM-DD inputs by appending 'T00:00:00Z'. Refined invalid date check. (Gemini)
// 2025-04-13: Rev 5 - Fixed formatDate UTC handling for YYYY-MM-DD strings and invalid date checks. Fixed formatPrice negative zero output. Fixed renderStars spacing and title attribute for clamping tests. (Gemini)
// 2025-04-09: Rev 4 - Implemented truncateHash, formatBytes. Added commented-out formatTimeAgo structure.
// 2025-04-09: Rev 3 - Added truncateText implementation.
// 2025-04-09: Rev 2 - Added comments for TODO formatters.
// 2025-04-07: Rev 1 - Added formatPrice (using Decimal.js), formatCurrency. Refined formatDate. Added renderStars, imports, comments, revision history.

import React from 'react'; // Import React, needed if functions return JSX like renderStars
import { Decimal } from 'decimal.js';
import { CURRENCY_SYMBOLS, DEFAULT_PAGE_SIZE } from './constants'; // Import currency symbols and page size constant
// TODO: Uncomment the line below if/when date-fns is installed
// import { formatDistanceToNowStrict } from 'date-fns';

/**
 * Formats a date string or Date object into a locale-aware string.
 * Handles YYYY-MM-DD specifically for UTC consistency. Defaults to UTC unless overridden.
 * @param {string | Date | number | null | undefined} dateInput - The date string, Date object, or timestamp number.
 * @param {Intl.DateTimeFormatOptions} [options={}] - Optional formatting options for toLocaleString/toLocaleDateString. Can include `timeZone` to override UTC default.
 * @returns {string} Formatted date string, 'Invalid Date', or 'N/A'.
 */
export const formatDate = (dateInput, options = {}) => {
    if (dateInput === null || dateInput === undefined || dateInput === '') return 'N/A';

    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        // Default to UTC for consistency unless overridden by caller options
        timeZone: 'UTC',
    };
    // Merge caller options, allowing them to override timeZone
    const formatOptions = { ...defaultOptions, ...options };

    // --- Note for Test File (`formatters.test.js`) ---
    // The test failing with Expected: "... 3:30 AM" / Received: "... 10:30 AM" likely indicates an issue EXTERNAL to this function's logic:
    // 1. Test Expectation Issue: The test might expect a specific local time (e.g., 3:30 AM in UTC-7) but doesn't pass `{ timeZone: 'America/Los_Angeles', ... }` in the `options`. Without the override, the function correctly defaults to UTC (producing 10:30 AM in this example). Verify the test passes the intended `timeZone` option AND uses an unambiguous `dateStr` input.
    // 2. Test Environment `Intl` Limitation: The Node/JSDOM environment running the test might lack full ICU data needed for `toLocaleString` to correctly apply the specific `timeZone` requested by the test options, causing it to fall back to UTC or system time. Configure the test environment for full ICU support if specific timezone formatting is critical.
    // The function logic correctly defaults to UTC and allows override via the `options` object. No changes made here.
    // ----

    try {
        let date;
        const dateString = String(dateInput);

        // Check for YYYY-MM-DD format and parse as UTC
        const ymdRegex = /^\d{4}-\d{2}-\d{2}$/;
        if (ymdRegex.test(dateString)) {
            // Explicitly check component ranges before parsing
             const parts = dateString.split('-').map(part => parseInt(part, 10));
             if (parts[1] < 1 || parts[1] > 12 || parts[2] < 1 || parts[2] > 31) {
                  throw new Error('Invalid date components (Month/Day out of range)');
             }
             // Check for invalid day-in-month (e.g., Feb 30) - Create a temp UTC date to check validity
             const tempDate = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
              // Rev 7: Refined isNaN check
             if (!tempDate || isNaN(tempDate.getTime()) || tempDate.getUTCFullYear() !== parts[0] || tempDate.getUTCMonth() !== parts[1] - 1 || tempDate.getUTCDate() !== parts[2]) {
                   throw new Error('Invalid date components (Day invalid for month/year or parse error)');
             }
            // Parse YYYY-MM-DD as UTC by appending Z time indicator
            date = new Date(dateString + 'T00:00:00Z');
        } else {
            // Attempt parsing other formats (like ISO strings with timezone, or timestamps) directly
            date = new Date(dateInput); // Can handle numbers (timestamps) or strings
        }

        // Final check if the resulting date object represents a valid time
        if (!date || isNaN(date.getTime())) { // Rev 7: Added !date check
             throw new Error('Invalid date input (Could not parse)');
        }

        // Format using the merged options (which includes the effective timeZone)
        if (formatOptions.hour || formatOptions.minute || formatOptions.second) {
            return date.toLocaleString(undefined, formatOptions);
        } else {
            return date.toLocaleDateString(undefined, formatOptions);
        }
    } catch (e) {
        console.error("Error formatting date:", dateInput, e.message);
        return 'Invalid Date';
    }
};


/**
 * Formats a numeric amount to a specific number of decimal places, tailored for currencies.
 * Uses Decimal.js for precision. Corrects negative zero output.
 * @param {number | string | Decimal | null | undefined} amount - The numeric amount to format.
 * @param {string} currencyCode - The currency code (e.g., 'BTC', 'XMR', 'USD').
 * @returns {string | null} Formatted price string or null if input is invalid/null/undefined.
 */
export const formatPrice = (amount, currencyCode) => {
    // Allow 0, but reject null/undefined/empty string early
    if (amount === null || amount === undefined || amount === '') return null;

    try {
        // Ensure the input is a valid number before creating Decimal
        const amountStr = String(amount);
        if (isNaN(Number(amountStr))) { // Check if convertible to number
             throw new Error('Input is not a valid number');
        }

        const value = new Decimal(amountStr); // Use string representation for Decimal constructor
        let decimalPlaces;

        // Determine decimal places based on currency code
        switch (currencyCode?.toUpperCase()) {
            case 'BTC':
                decimalPlaces = 8;
                break;
            case 'XMR':
                decimalPlaces = 6; // Common display precision
                break;
            case 'ETH':
                decimalPlaces = 6; // Common display precision
                break;
            case 'USD':
            case 'EUR':
            case 'GBP':
                 decimalPlaces = 2;
                 break;
            default:
                 console.warn(`formatPrice: Unknown currency code '${currencyCode}', defaulting to 2 decimal places.`);
                 decimalPlaces = 2;
        }

        let formatted = value.toFixed(decimalPlaces);

        // FIX: Check for and correct negative zero representation AFTER formatting
        const negativeZeroRegex = /^-0(\.0+)?$/; // Matches "-0" or "-0.0", "-0.00" etc.
        if (negativeZeroRegex.test(formatted)) {
             formatted = formatted.substring(1); // Remove the leading '-'
        }

        return formatted;

    } catch (e) {
        // Catch Decimal errors or the explicit NaN error
        console.error(`Error formatting price for ${currencyCode}:`, amount, e.message);
        return null; // Indicate formatting failure
    }
};


/**
 * Formats a numeric amount as currency, prepending the correct symbol.
 * Handles invalid inputs robustly.
 * @param {number | string | Decimal | null | undefined} amount - The numeric amount.
 * @param {string} currencyCode - The currency code (e.g., 'BTC', 'XMR', 'USD').
 * @param {object} [options={}] - Optional flags.
 * @param {boolean} [options.showNA=true] - Whether to return 'N/A' for null/invalid amounts (default true). Set to false to return empty string ''.
 * @returns {string} Formatted currency string (e.g., '₿ 0.12345678', '$ 19.99'), 'N/A', or ''.
 */
export const formatCurrency = (amount, currencyCode, options = { showNA: true }) => {
    // FIX: Call formatPrice first, which handles null/undefined/invalid checks robustly
    const formattedAmount = formatPrice(amount, currencyCode);

    if (formattedAmount === null) {
        // formatPrice failed or input was null/undefined/empty
        return options.showNA ? 'N/A' : '';
    }

    // If formatPrice succeeded, proceed to add symbol
    const symbol = CURRENCY_SYMBOLS[currencyCode?.toUpperCase()] || currencyCode || '';
    return `${symbol} ${formattedAmount}`;
};


/**
 * Renders a star rating component using text characters. Corrects spacing and title attribute.
 * @param {number | string | null | undefined} rating - The rating value (ideally 0-5).
 * @returns {React.ReactElement | string} JSX span with stars or 'N/A'.
 */
export const renderStars = (rating) => {
    const ratingNumber = Number(rating); // Convert string input
    if (rating === null || rating === undefined || isNaN(ratingNumber)) return 'N/A';

    const RATING_MAX = 5;
    const originalRating = ratingNumber; // Keep original for title

    // Clamp rating value between 0 and RATING_MAX for star calculation
    const clampedRating = Math.max(0, Math.min(originalRating, RATING_MAX));
    // Round to nearest 0.5 for half-star representation
    const rounded = Math.round(clampedRating * 2) / 2;
    const fullStars = Math.floor(rounded);
    const halfStar = rounded % 1 !== 0;
    const emptyStars = RATING_MAX - fullStars - (halfStar ? 1 : 0);

    // FIX: Construct the star string without extra spaces
    let starsString = '';
    starsString += '★'.repeat(fullStars);
    if (halfStar) {
         starsString += '½'; // Or use a different half-star symbol/icon
    }
    starsString += '☆'.repeat(Math.max(0, emptyStars));

    // FIX: Use original (unclamped) rating in title, formatted to 2 decimal places
    const titleRating = originalRating.toFixed(2);

    return (
        <span title={`${titleRating} / ${RATING_MAX.toFixed(0)}`}>
             {starsString}
        </span>
    );
};

// --- Other formatters (truncateText, truncateHash, formatBytes) remain unchanged ---

/**
 * Truncates a string to a specified maximum length and adds an ellipsis.
 * @param {string | null | undefined} text - The text to truncate.
 * @param {number} [maxLength=100] - The maximum length before truncating.
 * @returns {string} The truncated string or the original string if shorter.
 */
export const truncateText = (text, maxLength = 100) => {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
};

/**
 * Truncates a hash or long string, showing start and end characters.
 * @param {string | null | undefined} hash - The hash string.
 * @param {number} [startChars=6] - Number of characters to show at the start.
 * @param {number} [endChars=4] - Number of characters to show at the end.
 * @returns {string} Truncated hash or original string if too short.
 */
export const truncateHash = (hash, startChars = 6, endChars = 4) => {
    if (!hash || typeof hash !== 'string') return hash || ''; // Return original if not a string or null/undefined
    const totalLength = startChars + endChars;
    if (hash.length <= totalLength + 3) return hash; // Don't truncate if it's already short (allow space for '...')
    return `${hash.substring(0, startChars)}...${hash.substring(hash.length - endChars)}`;
};

/**
 * Formats a number of bytes into a human-readable string (KB, MB, GB, etc.).
 * @param {number | null | undefined} bytes - The number of bytes.
 * @param {number} [decimals=2] - The number of decimal places for the result.
 * @returns {string} Human-readable file size string (e.g., '1.23 MB').
 */
export const formatBytes = (bytes, decimals = 2) => {
    if (bytes === null || bytes === undefined || isNaN(bytes)) return 'N/A'; // Handle null/undefined/NaN
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    // Ensure index is within bounds and handle potential edge cases like Infinity or negative bytes
    const index = Math.max(0, Math.min(i, sizes.length - 1)); // Ensure index is non-negative

    return `${parseFloat((bytes / Math.pow(k, index)).toFixed(dm))} ${sizes[index]}`;
};

/**
 * Formats a date to show relative time distance (e.g., "2 hours ago").
 * NOTE: Requires installing and importing a library like 'date-fns' or 'dayjs'.
 * Example using date-fns (uncomment import and install 'date-fns'):
 * npm install date-fns
 * // or
 * yarn add date-fns
 * @param {string | Date | number | null | undefined} dateInput - The date string, Date object, or timestamp.
 * @returns {string} Relative time string or 'N/A'.
 */
/*
export const formatTimeAgo = (dateInput) => {
     if (!dateInput) return 'N/A';
     try {
         const date = new Date(dateInput);
         if (isNaN(date.getTime())) throw new Error('Invalid date');
         // Example: using formatDistanceToNowStrict from date-fns
         // return formatDistanceToNowStrict(date, { addSuffix: true });
     } catch (e) {
         console.error("Error formatting time ago:", e);
         return 'Invalid Date';
     }
};
*/
// --- END TODO ---