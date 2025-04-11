// frontend/utils/formatters.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 4 - Implemented truncateHash, formatBytes. Added commented-out formatTimeAgo structure.
// 2025-04-09: Rev 3 - Added truncateText implementation.
// 2025-04-09: Rev 2 - Added comments for TODO formatters.
// 2025-04-07: Rev 1 - Added formatPrice (using Decimal.js), formatCurrency. Refined formatDate.
//           - Implemented precise currency formatting using Decimal.js.
//           - Added helper to combine formatted price with currency symbol.
//           - Added options parameter to formatDate.
//           - Reviewed renderStars function.
//           - Added necessary imports and comments.
//           - Added revision history block.

import React from 'react'; // Import React, needed if functions return JSX like renderStars
import { Decimal } from 'decimal.js';
import { CURRENCY_SYMBOLS, DEFAULT_PAGE_SIZE } from './constants'; // Import currency symbols and page size constant
// TODO: Uncomment the line below if/when date-fns is installed
// import { formatDistanceToNowStrict } from 'date-fns';

/**
 * Formats a date string or Date object into a locale-aware string.
 * @param {string | Date | null | undefined} dateInput - The date string or Date object.
 * @param {Intl.DateTimeFormatOptions} [options={}] - Optional formatting options for toLocaleString/toLocaleDateString.
 * @returns {string} Formatted date string or 'N/A'.
 */
export const formatDate = (dateInput, options = {}) => { // Make options default to empty object
    if (!dateInput) return 'N/A';

    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        // Optionally add time:
        // hour: 'numeric',
        // minute: '2-digit',
    };

    const formatOptions = { ...defaultOptions, ...options };

    try {
        const date = new Date(dateInput);
        // Check if the date is valid after parsing
        if (isNaN(date.getTime())) {
            // Try common alternative if direct parse fails (e.g., simple YYYY-MM-DD)
             const parts = String(dateInput).split('-');
             if (parts.length === 3) {
                 const potentiallyValidDate = new Date(parts[0], parts[1] - 1, parts[2]);
                 if (!isNaN(potentiallyValidDate.getTime())) {
                     date.setTime(potentiallyValidDate.getTime());
                 } else {
                    throw new Error('Invalid date input');
                 }
             } else {
                 throw new Error('Invalid date input');
             }
        }
        // Use toLocaleString if time options are present, otherwise toLocaleDateString
        if (formatOptions.hour || formatOptions.minute || formatOptions.second) {
            return date.toLocaleString(undefined, formatOptions); // Use user's locale settings
        } else {
            return date.toLocaleDateString(undefined, formatOptions); // Use user's locale settings
        }
    } catch (e) {
        console.error("Error formatting date:", dateInput, e);
        return 'Invalid Date';
    }
};


/**
 * Formats a numeric amount to a specific number of decimal places, tailored for cryptocurrencies.
 * Uses Decimal.js for precision.
 * @param {number | string | Decimal | null | undefined} amount - The numeric amount to format.
 * @param {string} currencyCode - The currency code (e.g., 'BTC', 'XMR', 'USD').
 * @returns {string | null} Formatted price string or null if input is invalid/null/undefined.
 */
export const formatPrice = (amount, currencyCode) => {
    if (amount === null || amount === undefined || amount === '') return null;

    try {
        const value = new Decimal(amount);
        let decimalPlaces;

        // Determine decimal places based on currency code
        switch (currencyCode?.toUpperCase()) {
            case 'BTC':
                decimalPlaces = 8;
                break;
            case 'XMR':
                // Monero has 12 decimal places (piconero), but often displayed with fewer
                decimalPlaces = 6; // Common display precision, adjust if needed
                // decimalPlaces = 12; // Full precision
                break;
            case 'ETH':
                // Ether has 18 decimal places (wei), often displayed with 4-8
                decimalPlaces = 6; // Common display precision, adjust if needed
                // decimalPlaces = 8;
                break;
            case 'USD':
            case 'EUR':
            case 'GBP': // Add other FIAT currencies as needed
                decimalPlaces = 2;
                break;
            default:
                // Default for unknown or non-crypto currencies (assume 2dp)
                decimalPlaces = 2;
        }

        // Ensure we don't display negative zero
        if (value.isZero() && value.isNegative()) {
            return new Decimal(0).toFixed(decimalPlaces);
        }

        return value.toFixed(decimalPlaces);

    } catch (e) {
        console.error(`Error formatting price for ${currencyCode}:`, amount, e);
        return null; // Indicate formatting failure
    }
};

/**
 * Formats a numeric amount as currency, prepending the correct symbol.
 * @param {number | string | Decimal | null | undefined} amount - The numeric amount.
 * @param {string} currencyCode - The currency code (e.g., 'BTC', 'XMR', 'USD').
 * @param {object} [options={}] - Optional flags.
 * @param {boolean} [options.showNA=true] - Whether to return 'N/A' for null/invalid amounts (default true). Set to false to return empty string ''.
 * @returns {string} Formatted currency string (e.g., '₿ 0.12345678', '$ 19.99'), 'N/A', or ''.
 */
export const formatCurrency = (amount, currencyCode, options = { showNA: true }) => {
    const formattedAmount = formatPrice(amount, currencyCode);

    if (formattedAmount === null) {
        // Handle zero explicitly if needed, otherwise respect showNA option
        if (amount === 0 || amount === '0') {
             const zeroFormatted = formatPrice(0, currencyCode);
             const symbol = CURRENCY_SYMBOLS[currencyCode?.toUpperCase()] || currencyCode || '';
             return `${symbol} ${zeroFormatted}`;
        }
        return options.showNA ? 'N/A' : ''; // Return N/A or empty string based on option
    }

    const symbol = CURRENCY_SYMBOLS[currencyCode?.toUpperCase()] || currencyCode || ''; // Use code if symbol missing

    return `${symbol} ${formattedAmount}`;
};


/**
 * Renders a star rating component using text characters.
 * NOTE: Consider using SVG icons for better styling and accessibility.
 * @param {number | null | undefined} rating - The rating value (ideally 0-5).
 * @returns {React.ReactElement | string} JSX span with stars or 'N/A'.
 */
export const renderStars = (rating) => {
    if (rating === null || rating === undefined || isNaN(rating)) return 'N/A';

    const RATING_MAX = 5;
    // Clamp rating value between 0 and RATING_MAX
    const ratingValue = Math.max(0, Math.min(Number(rating), RATING_MAX));
    // Round to nearest 0.5 for half-star representation
    const rounded = Math.round(ratingValue * 2) / 2;
    const fullStars = Math.floor(rounded);
    const halfStar = rounded % 1 !== 0;
    const emptyStars = RATING_MAX - fullStars - (halfStar ? 1 : 0);

    // Ensure we don't exceed max stars due to rounding edge cases (should be rare with clamp)
    const totalStars = fullStars + (halfStar ? 1 : 0) + emptyStars;
    if (totalStars !== RATING_MAX && totalStars >= 0) { // Ensure emptyStars doesn't go negative
        console.warn("Star calculation resulted in incorrect total:", totalStars, "for rating:", rating);
        // Adjust calculation if necessary, though clamping should prevent most issues
    }

    return (
        <span title={`${ratingValue.toFixed(2)} / ${RATING_MAX.toFixed(0)}`}>
            {'★'.repeat(fullStars)}
            {halfStar ? '½' : ''} {/* TODO: Consider using a better half-star character or icon library */}
            {'☆'.repeat(Math.max(0, emptyStars))} {/* Ensure emptyStars isn't negative */}
        </span>
    );
};

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
    if (hash.length <= totalLength) return hash; // Don't truncate if it's already short enough
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

    // Ensure index is within bounds and handle potential edge cases like Infinity
    const index = Math.min(i, sizes.length - 1);

    return `${parseFloat((bytes / Math.pow(k, index)).toFixed(dm))} ${sizes[index]}`;
};

/**
 * Formats a date to show relative time distance (e.g., "2 hours ago").
 * NOTE: Requires installing and importing a library like 'date-fns' or 'dayjs'.
 * Example using date-fns (uncomment import and install 'date-fns'):
 * npm install date-fns
 * // or
 * yarn add date-fns
 * @param {string | Date | null | undefined} dateInput - The date string or Date object.
 * @returns {string} Relative time string or 'N/A'.
 */
/*
export const formatTimeAgo = (dateInput) => {
    if (!dateInput) return 'N/A';
    try {
        const date = new Date(dateInput);
        if (isNaN(date.getTime())) throw new Error('Invalid date');
        // Example: using formatDistanceToNowStrict from date-fns
        return formatDistanceToNowStrict(date, { addSuffix: true });
    } catch (e) {
        console.error("Error formatting time ago:", e);
        return 'Invalid Date';
    }
};
*/
// --- END TODO ---