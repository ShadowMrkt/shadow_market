// frontend/utils/api.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 2 - Imported API_BASE_URL, uncommented getUnsignedReleaseTxData, added TODOs.
//           - Replaced local API_BASE_URL definition with import from constants.
//           - Uncommented and placed getUnsignedReleaseTxData function for multi-sig flow.
//           - Added comments/TODOs suggesting structured error codes and AbortController usage.
//           - Added TODO placeholders for missing API functions.
// 2025-04-07: Rev 1 - Initial enterprise-grade review and update.
//           - Conditionally add X-CSRFToken header only if token exists.
//           - Added comments on CSRF cookie config, HTTPS, credentials include.
//           - Improved 403 error handling for PGP requirement detection (case-insensitive).
//           - Refined network error message in catch block.
//           - Removed unused 'requiresPgpAuth' parameter from apiRequest.
//           - Added revision history block.

import Cookies from 'js-cookie';
import { API_BASE_URL } from './constants'; // Import base URL from constants

// Helper to get CSRF token from cookies
function getCsrfToken() {
    return Cookies.get('csrftoken'); // Default Django CSRF cookie name
}
// --- Canary ---
/**
 * Fetches the latest warrant canary data.
 * Assumes backend endpoint returns { canary_last_updated: "YYYY-MM-DD", ... }
 * @returns {Promise<object>} Canary data object or null.
 */
export const getCanaryData = () => apiRequest('/api/store/canary/', 'GET');
/**
 * Centralized helper function for making API requests.
 * Handles base URL, JSON parsing, CSRF token, and basic error handling.
 * TODO: Consider enhancing error handling to rely on structured error codes from the backend
 * (e.g., { "code": "pgp_required", "detail": "..." }) instead of string matching for messages like "PGP Auth Required".
 * TODO: For specific use cases like type-ahead search, consider implementing AbortController logic
 * to cancel stale requests.
 * @param {string} endpoint - The API endpoint (e.g., '/api/store/users/me/').
 * @param {string} [method='GET'] - HTTP method.
 * @param {object|null} [data=null] - Data payload for POST/PUT/PATCH requests.
 * @returns {Promise<any>} - Resolves with the JSON response data or null for 204 No Content.
 * @throws {Error} - Throws an error with specific messages for known issues (Unauthorized, PGP Auth Required, Forbidden, Not Found, Network error) or the backend error detail.
 */
async function apiRequest(endpoint, method = 'GET', data = null) {
    const url = `${API_BASE_URL}${endpoint}`; // Use imported constant
    const headers = {
        ...(data && ['POST', 'PUT', 'PATCH'].includes(method.toUpperCase()) && { 'Content-Type': 'application/json' }),
        'Accept': 'application/json',
    };

    const csrfToken = getCsrfToken();
    if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken;
    } else if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())) {
        console.warn(`CSRF token cookie 'csrftoken' not found for state-changing request: ${method} ${endpoint}`);
    }

    const config = {
        method: method.toUpperCase(),
        headers: headers,
        // credentials: 'include', // Uncomment ONLY if needed for cross-origin cookie-based auth (CORS)
    };

    if (data && ['POST', 'PUT', 'PATCH'].includes(config.method)) {
        config.body = JSON.stringify(data);
    }

    let response;

    try {
        response = await fetch(url, config);

        if (response.status === 204) {
            return null;
        }

        let responseData = null;
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            try {
                responseData = await response.json();
            } catch (jsonError) {
                console.error(`API Error: Failed to parse JSON response for ${method} ${endpoint}`, jsonError);
                throw new Error(`API Error: Unexpected response format received from server (${response.status}).`);
            }
        }

        if (!response.ok) {
            let errorMessage = response.statusText;
            if (responseData) {
                errorMessage = responseData.detail || responseData.error ||
                               (typeof responseData === 'object' ? JSON.stringify(responseData) : String(responseData));
            }

            console.error(`API Error (${response.status}) on ${method} ${endpoint}: ${errorMessage}`);

            if (response.status === 401) {
                throw new Error('Unauthorized');
            }
            if (response.status === 403) {
                // Relying on string message is brittle; structured error codes preferred.
                if (typeof errorMessage === 'string' && errorMessage.toLowerCase().includes("pgp authenticated session required")) {
                    throw new Error("PGP Auth Required");
                }
                throw new Error(errorMessage || 'Forbidden');
            }
            if (response.status === 404) {
                throw new Error(errorMessage || 'Not Found');
            }
            // Throw the specific detail message from the backend for other errors
            throw new Error(errorMessage);
        }

        return responseData;

    } catch (error) {
        console.error(`API Request Failed (${method} ${endpoint}):`, error);

        if (error instanceof Error) {
            // Re-throw specific errors we've already identified
            if (['Unauthorized', 'PGP Auth Required', 'Forbidden', 'Not Found'].includes(error.message) || error.message.startsWith('API Error:')) {
                throw error;
            }
            // Wrap other errors (like network failures)
            throw new Error(`Network error or invalid response when trying to reach the API. Please check your connection. (${error.message})`);
        } else {
            // Fallback for non-standard throws
            throw new Error('An unknown network or API error occurred.');
        }
    }
}


// --- Auth ---
export const registerUser = (userData) => apiRequest('/api/store/auth/register/', 'POST', userData);
export const loginInit = (credentials) => apiRequest('/api/store/auth/login/init/', 'POST', credentials);
export const loginPgpVerify = (signatureData) => apiRequest('/api/store/auth/login/pgp_verify/', 'POST', signatureData);
export const logoutUser = () => apiRequest('/api/store/auth/logout/', 'POST');

// --- User ---
export const getCurrentUser = () => apiRequest('/api/store/users/me/', 'GET');
// Update requires PGP auth check *before* calling
export const updateCurrentUser = (userData) => apiRequest('/api/store/users/me/', 'PATCH', userData);

// --- Vendors ---
export const getVendorPublicProfile = (username) => apiRequest(`/api/store/vendors/${username}/`, 'GET');
// Stats/Sales require PGP auth check *before* calling
export const getVendorStats = () => apiRequest('/api/store/vendor/stats/', 'GET');
export const listMySales = (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return apiRequest(`/api/store/vendor/sales/?${query}`, 'GET');
};
// TODO: Define getVendorFeedback(username, params={})

// --- Categories ---
export const getCategories = async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return apiRequest(`/api/store/categories/?${query}`, 'GET');
};
export const getCategoryDetail = (slug) => apiRequest(`/api/store/categories/${slug}/`, 'GET');

// --- Products ---
// Helper to standardize paginated response
const handlePaginatedResponse = (responseData) => ({
    count: responseData?.count ?? 0,
    next: responseData?.next ?? null,
    previous: responseData?.previous ?? null,
    // Handle cases where API might return just an array for non-paginated lists
    results: responseData?.results ?? (Array.isArray(responseData) ? responseData : []),
});

export const getProducts = async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    const endpoint = `/api/store/products/?${query}`;
    const responseData = await apiRequest(endpoint, 'GET');
    return handlePaginatedResponse(responseData);
};
export const getProductDetail = (productIdOrSlug) => apiRequest(`/api/store/products/${productIdOrSlug}/`, 'GET');
// Product CUD requires PGP auth check *before* calling
export const createProduct = (productData) => apiRequest('/api/store/products/', 'POST', productData);
export const updateProduct = (slug, productData) => apiRequest(`/api/store/products/${slug}/`, 'PATCH', productData);
export const deleteProduct = (slug) => apiRequest(`/api/store/products/${slug}/`, 'DELETE');

// --- Orders ---
// Order actions generally require PGP auth check *before* calling
export const placeOrder = (orderData) => apiRequest('/api/store/orders/place/', 'POST', orderData);
export const listOrders = async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    const endpoint = `/api/store/orders/?${query}`;
    const responseData = await apiRequest(endpoint, 'GET');
    return handlePaginatedResponse(responseData);
};
export const getOrderDetails = (orderId) => apiRequest(`/api/store/orders/${orderId}/`, 'GET');
export const markOrderShipped = (orderId, trackingData = {}) => apiRequest(`/api/store/orders/${orderId}/ship/`, 'POST', trackingData);
// export const finalizeOrder = (orderId) => apiRequest(`/api/store/orders/${orderId}/finalize/`, 'POST'); // May be deprecated by multi-sig flow initiation
export const getUnsignedReleaseTxData = (orderId) => apiRequest(`/api/store/orders/${orderId}/prepare-release-tx/`, 'POST'); // <-- Uncommented and verified placement
export const signRelease = (orderId, signatureData) => apiRequest(`/api/store/orders/${orderId}/sign_release/`, 'POST', { signature_data: signatureData }); // Pass signature in correct format
export const openDispute = (orderId, reasonData) => apiRequest(`/api/store/orders/${orderId}/dispute/`, 'POST', reasonData);

// --- Wallet/Withdrawal ---
// Wallet actions require PGP auth check *before* calling
export const getWalletBalances = () => apiRequest('/api/store/wallet/balances/', 'GET');
export const prepareWithdrawal = (prepData) => apiRequest('/api/store/wallet/withdraw/prepare/', 'POST', prepData);
export const executeWithdrawal = (execData) => apiRequest('/api/store/wallet/withdraw/execute/', 'POST', execData);

// --- Feedback ---
// Feedback requires PGP auth check *before* calling
export const submitFeedback = (feedbackData) => apiRequest('/api/store/feedback/submit/', 'POST', feedbackData);
// TODO: Define getFeedback({ recipient_id: vendorId / recipient_username: username, ...params }) function

// --- Support Tickets ---
// Ticket actions may require PGP auth check *before* calling
export const listTickets = async (params = {}) => {
     const query = new URLSearchParams(params).toString();
     const endpoint = `/api/store/tickets/?${query}`;
     const responseData = await apiRequest(endpoint, 'GET');
     return handlePaginatedResponse(responseData);
};
export const getTicketDetail = (ticketId) => apiRequest(`/api/store/tickets/${ticketId}/`, 'GET');
export const createTicket = (ticketData) => apiRequest('/api/store/tickets/', 'POST', ticketData);
export const replyToTicket = (ticketId, messageData) => apiRequest(`/api/store/tickets/${ticketId}/messages/`, 'POST', messageData);

// --- Utils ---
// Encrypt requires PGP auth check *before* calling
export const encryptShippingInfo = (vendorId, shippingData) => {
    const payload = { vendor_id: vendorId, shipping_data: shippingData };
    return apiRequest('/api/store/utils/encrypt-for-vendor/', 'POST', payload);
};

// --- Health Check ---
export const healthCheck = () => apiRequest('/health/', 'GET');