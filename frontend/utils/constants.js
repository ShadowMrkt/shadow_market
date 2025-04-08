// frontend/utils/constants.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Added ORDER_STATUS map, display map, PGP block constants, API URL placeholder.
//           - Defined constants for backend order status strings.
//           - Added corresponding map for user-friendly display names.
//           - Added constants for PGP block delimiters.
//           - Added placeholder for API_BASE_URL using environment variables.
//           - Added comments clarifying usage and need for verification.
//           - Added revision history block.

/**
 * Mapping of currency codes to their common symbols.
 */
export const CURRENCY_SYMBOLS = {
    XMR: 'ɱ', // Monero symbol (U+2C6F)
    BTC: '₿', // Bitcoin symbol (U+20BF)
    ETH: 'Ξ', // Ethereum symbol (U+039E)
    USD: '$', // Example for potential display purposes
    EUR: '€',
    // Add other currencies if needed
};

/**
 * List of supported cryptocurrency codes for payments.
 * IMPORTANT: Should match backend configuration.
 */
export const SUPPORTED_CURRENCIES = ['XMR', 'BTC', 'ETH'];

// TODO: Consider adding a list of supported DISPLAY currencies if implementing conversion rates
// export const DISPLAY_CURRENCIES = ['USD', 'EUR', 'BTC', 'XMR', 'ETH'];

/**
 * Default pagination size for lists (e.g., orders, products).
 * IMPORTANT: Should match the default page size set in the backend API.
 */
export const DEFAULT_PAGE_SIZE = 12;

/**
 * Minimum password length requirement for registration/password change.
 */
export const MIN_PASSWORD_LENGTH = 12;

/**
 * Timeout durations in milliseconds for notification toasts.
 */
export const TOAST_SUCCESS_DURATION = 5000;
export const TOAST_ERROR_DURATION = 8000; // Longer duration for errors

/**
 * Base URL for the backend API.
 * Best practice is to use environment variables.
 * NEXT_PUBLIC_ prefix makes it available on the client-side.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'; // Provide a sensible default for local dev

/**
 * Standard PGP Block Identifiers for parsing/validation.
 */
export const PGP_PUBLIC_KEY_BLOCK = {
    BEGIN: '-----BEGIN PGP PUBLIC KEY BLOCK-----',
    END: '-----END PGP PUBLIC KEY BLOCK-----',
};
export const PGP_PRIVATE_KEY_BLOCK = {
    BEGIN: '-----BEGIN PGP PRIVATE KEY BLOCK-----',
    END: '-----END PGP PRIVATE KEY BLOCK-----',
};
export const PGP_MESSAGE_BLOCK = {
    BEGIN: '-----BEGIN PGP MESSAGE-----',
    END: '-----END PGP MESSAGE-----',
};
export const PGP_SIGNATURE_BLOCK = {
    BEGIN: '-----BEGIN PGP SIGNATURE-----',
    END: '-----END PGP SIGNATURE-----',
};


/**
 * Order Status Constants Map.
 * Maps internal constant keys (used in frontend logic) to the actual status strings
 * returned by the backend API.
 * TODO: CRITICAL - Verify these values exactly match the strings returned by your specific backend API.
 */
export const ORDER_STATUS = {
    PENDING_PAYMENT: 'pending_payment',
    PAYMENT_UNCONFIRMED: 'payment_unconfirmed',
    PAYMENT_CONFIRMED: 'payment_confirmed', // Escrow funded
    SHIPPED: 'shipped',
    // Multi-sig related statuses (examples, adjust based on your backend)
    RELEASE_INITIATED: 'release_initiated', // Process started, signatures needed
    READY_FOR_BROADCAST: 'ready_for_broadcast', // All signatures present
    // Completion statuses
    FINALIZED: 'finalized', // Successfully completed and paid out
    DISPUTED: 'disputed',
    DISPUTE_RESOLVED: 'dispute_resolved', // After moderator decision
    // Cancellation/Failure statuses
    CANCELLED_TIMEOUT: 'cancelled_timeout', // e.g., payment timed out
    CANCELLED_BUYER: 'cancelled_buyer',
    CANCELLED_VENDOR: 'cancelled_vendor',
    REFUNDED: 'refunded',
};

/**
 * Order Status Display Names Map.
 * Provides user-friendly text for displaying order statuses in the UI.
 * Keys should match the values from the ORDER_STATUS map above.
 */
export const ORDER_STATUS_DISPLAY = {
    [ORDER_STATUS.PENDING_PAYMENT]: 'Pending Payment',
    [ORDER_STATUS.PAYMENT_UNCONFIRMED]: 'Payment Unconfirmed',
    [ORDER_STATUS.PAYMENT_CONFIRMED]: 'Payment Confirmed / In Escrow',
    [ORDER_STATUS.SHIPPED]: 'Shipped',
    [ORDER_STATUS.RELEASE_INITIATED]: 'Release Initiated (Awaiting Signatures)',
    [ORDER_STATUS.READY_FOR_BROADCAST]: 'Release Ready (Awaiting Broadcast)',
    [ORDER_STATUS.FINALIZED]: 'Finalized',
    [ORDER_STATUS.DISPUTED]: 'Disputed',
    [ORDER_STATUS.DISPUTE_RESOLVED]: 'Dispute Resolved',
    [ORDER_STATUS.CANCELLED_TIMEOUT]: 'Cancelled (Timeout)',
    [ORDER_STATUS.CANCELLED_BUYER]: 'Cancelled (Buyer)',
    [ORDER_STATUS.CANCELLED_VENDOR]: 'Cancelled (Vendor)',
    [ORDER_STATUS.REFUNDED]: 'Refunded',
    // Add default or handle unknown statuses gracefully in components
    'unknown': 'Unknown Status',
};


// TODO: Consider moving STATUS_FILTER_CHOICES and ORDERING_CHOICES from orders/index.js here
// if they are used elsewhere or to further centralize constants.
// Example: Deriving filter choices from ORDER_STATUS maps:
/*
export const STATUS_FILTER_CHOICES = [
    { value: '', label: 'All Statuses' },
    ...Object.entries(ORDER_STATUS_DISPLAY)
        .filter(([key,]) => key !== 'unknown') // Exclude the 'unknown' key
        .map(([value, label]) => ({ value, label }))
];
*/

// Add other frontend-specific constants as needed
// Example: Websocket URL, specific UI settings, etc.
// export const WEBSOCKET_URL = process.env.NEXT_PUBLIC_WEBSOCKET_URL || 'ws://localhost:8000/ws';