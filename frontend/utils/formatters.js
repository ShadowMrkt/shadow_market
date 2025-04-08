// frontend/utils/formatters.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Added formatPrice (using Decimal.js), formatCurrency. Refined formatDate.
//           - Implemented precise currency formatting using Decimal.js.
//           - Added helper to combine formatted price with currency symbol.
//           - Added options parameter to formatDate.
//           - Reviewed renderStars function.
//           - Added necessary imports and comments.
//           - Added revision history block.

import React from 'react'; // Import React, needed if functions return JSX like renderStars
import { Decimal } from 'decimal.js';
import { CURRENCY_SYMBOLS } from './constants'; // Import currency symbols

/**
 * Formats a date string or Date object into a locale-aware string.
 * @param {string | Date | null | undefined} dateInput - The date string or Date object.
 * @param {Intl.DateTimeFormatOptions} options - Optional formatting options for toLocaleString/toLocaleDateString.
 * @returns {string} Formatted date string or 'N/A'.
 */
export const formatDate = (dateInput, options) => {
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
            throw new Error('Invalid date input');
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
 * @returns {string | null} Formatted price string or null if input is invalid.
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
                // Default for unknown or non-crypto currencies
                decimalPlaces = 2;
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
 * @returns {string} Formatted currency string (e.g., '₿ 0.12345678', '$ 19.99') or 'N/A'.
 */
export const formatCurrency = (amount, currencyCode) => {
    const formattedAmount = formatPrice(amount, currencyCode);

    if (formattedAmount === null) {
        // Optionally check if amount was 0, return formatted zero if needed
        if (amount === 0 || amount === '0') {
             const zeroFormatted = formatPrice(0, currencyCode);
             const symbol = CURRENCY_SYMBOLS[currencyCode?.toUpperCase()] || currencyCode || '';
             return `${symbol} ${zeroFormatted}`;
        }
        return 'N/A'; // Return N/A if amount is null/undefined/invalid
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

    // Ensure we don't exceed max stars due to rounding edge cases
    const totalStars = fullStars + (halfStar ? 1 : 0) + emptyStars;
    if (totalStars !== RATING_MAX) {
        console.warn("Star calculation issue for rating:", rating);
        // Adjust empty stars calculation if needed, though clamp should prevent this
    }

    return (
        <span title={`${ratingValue.toFixed(2)} / ${RATING_MAX.toFixed(0)}`}>
            {'★'.repeat(fullStars)}
            {halfStar ? '½' : ''} {/* Consider using a better half-star character or icon */}
            {'☆'.repeat(emptyStars)}
        </span>
    );
};

// TODO: Add other formatters as needed:
// - truncateText(text, maxLength)
// - truncateHash(hash, charsToShow = 6)
// - formatBytes(bytes, decimals = 2)
// - formatTimeAgo(dateInput) // Requires library like date-fns or dayjs