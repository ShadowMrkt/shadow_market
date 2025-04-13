// frontend/utils/api.js
// --- REVISION HISTORY ---
// 2025-04-11: Rev 1 - Recreated file based on utils/api.test.js.
//                   - Implemented core apiRequest helper.
//                   - Added specific functions: getCurrentUser, getProducts, loginInit, logoutUser, updateCurrentUser.
//                   - Implemented CSRF handling via js-cookie.
//                   - Added robust error handling for network errors and non-ok HTTP responses (including 401, 403, 400 with JSON body).
//                   - Used URLSearchParams for query parameters.
//                   - Added ApiError custom error class.

import Cookies from 'js-cookie';
import { API_BASE_URL } from './constants'; // Assuming constants.js is in the same directory

/**
 * Custom Error class for API-related errors.
 * Includes HTTP status and parsed error data if available.
 */
class ApiError extends Error {
    /**
     * @param {string} message - The error message.
     * @param {number | undefined} status - The HTTP status code, if available.
     * @param {any} [data] - Parsed error data from the response body, if available.
     */
    constructor(message, status, data) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
        // Maintain proper stack trace (optional, depends on environment support)
        if (Error.captureStackTrace) {
            Error.captureStackTrace(this, ApiError);
        }
    }
}

/**
 * Core function for making API requests. Handles URL construction, headers,
 * CSRF tokens, request body, response parsing, and error handling.
 *
 * @param {string} endpoint - The API endpoint path (e.g., '/api/store/users/me/').
 * @param {string} [method='GET'] - The HTTP method.
 * @param {object | null} [body=null] - The request body for POST/PUT/PATCH etc. Will be JSON.stringify'd.
 * @param {object | null} [params=null] - Query parameters as an object.
 * @param {boolean} [requiresCsrf=false] - Whether to include the X-CSRFToken header.
 * @returns {Promise<any>} - Resolves with the parsed JSON response, or null for 204 No Content.
 * @throws {ApiError} - Rejects with an ApiError for network issues or non-ok HTTP responses.
 */
export const apiRequest = async (endpoint, method = 'GET', body = null, params = null, requiresCsrf = false) => {
    // Ensure API_BASE_URL is defined
    if (!API_BASE_URL) {
        throw new Error("API_BASE_URL is not defined. Check your environment variables and constants file.");
    }

    let url;
    try {
        // Construct URL carefully, handling potential base URL trailing slash and endpoint leading slash
        const baseUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL : `${API_BASE_URL}/`;
        const endpointPath = endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;
        url = new URL(endpointPath, baseUrl);
    } catch (e) {
        console.error("Error constructing URL:", e, { API_BASE_URL, endpoint });
        throw new Error(`Invalid URL components: ${e.message}`);
    }


    // Append query parameters if provided
    if (params) {
        // Filter out null/undefined params before creating search string
        const definedParams = Object.entries(params).reduce((acc, [key, value]) => {
            if (value !== null && value !== undefined) {
                acc[key] = value;
            }
            return acc;
        }, {});
        if (Object.keys(definedParams).length > 0) {
            url.search = new URLSearchParams(definedParams).toString();
        }
    }

    const headers = new Headers({
        'Accept': 'application/json',
    });

    const config = {
        method: method.toUpperCase(),
        headers: headers,
        // credentials: 'include', // Uncomment if backend requires cookies (ensure CORS allows credentials)
        // mode: 'cors', // Usually default, but can be explicit
        // cache: 'no-cache', // Consider cache policy for production
    };

    // Only add Content-Type and body if body is actually present and method allows it
    if (body !== null && body !== undefined && ['POST', 'PUT', 'PATCH'].includes(config.method)) {
        try {
            config.body = JSON.stringify(body);
            headers.set('Content-Type', 'application/json');
        } catch (e) {
            console.error("Failed to stringify request body:", e);
            throw new Error("Invalid request body provided.");
        }
    }

    if (requiresCsrf) {
        const csrfToken = Cookies.get('csrftoken');
        if (csrfToken) {
            headers.set('X-CSRFToken', csrfToken);
        } else {
            console.warn(`CSRF token requested for ${method} ${endpoint} but not found in cookies.`);
            // Decide how to handle missing CSRF. Throwing an error might be safer.
            // throw new ApiError('CSRF token is missing', 403); // Example: Treat as Forbidden
        }
    }

    try {
        const response = await fetch(url.toString(), config);

        // --- Handle successful responses (2xx) ---
        if (response.ok) {
            if (response.status === 204) { // No Content
                return null;
            }
            // Attempt to parse JSON for other 2xx responses
            try {
                // Check content type before assuming JSON
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    return await response.json();
                } else {
                    // Handle cases like 200 OK with non-JSON content if expected by any endpoint
                    console.warn(`Received successful status ${response.status} but non-JSON content-type: ${contentType} for ${endpoint}`);
                    return await response.text(); // Or return null, or throw, depending on desired behavior
                }
            } catch (e) {
                console.error(`Failed to parse JSON for successful response ${response.status} from ${endpoint}:`, e);
                // Throw an error indicating parsing failure despite success status
                throw new ApiError(`API Error (${response.status}): Failed to parse successful response body`, response.status);
            }
        }

        // --- Handle error responses (non-2xx) ---
        let errorData = null;
        let errorMessage = `API Error (${response.status}): ${response.statusText}`; // Default message

        // Attempt to parse error body only if content seems parseable (JSON or maybe text)
        try {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                 errorData = await response.json();
                 // Refine error message using parsed data
                 if (errorData && typeof errorData === 'object') {
                    if (errorData.detail && typeof errorData.detail === 'string') {
                        errorMessage = `API Error (${response.status}): ${errorData.detail}`;
                    } else if (Object.keys(errorData).length > 0) {
                        // Use stringified JSON only if it's not empty and doesn't have 'detail'
                         errorMessage = `API Error (${response.status}): ${JSON.stringify(errorData)}`;
                    }
                 }
            } else {
                // Try to get text if not JSON, could be HTML error page or plain text
                const textBody = await response.text();
                errorData = { detail: textBody || response.statusText }; // Store text body in 'detail'
                errorMessage = `API Error (${response.status}): ${response.statusText}`; // Keep original status text message
                console.warn(`Received error status ${response.status} with non-JSON content-type: ${contentType} from ${endpoint}`);
            }
        } catch (e) {
            console.warn(`Failed to parse error body for status ${response.status} from ${endpoint}:`, e);
            // Keep the basic statusText message and set detail fallback if parsing fails
             errorData = { detail: response.statusText };
        }

        // Throw specific errors for common authorization/authentication issues
        if (response.status === 401) {
            // Could potentially trigger auto-logout or redirect here in a real app
            console.error('Unauthorized access detected:', endpoint, errorData);
            throw new ApiError('Unauthorized', response.status, errorData);
        }
        if (response.status === 403) {
            console.error('Forbidden access detected:', endpoint, errorData);
            throw new ApiError('Forbidden', response.status, errorData);
        }

        // Throw generic ApiError for other non-ok statuses, including the refined message
        throw new ApiError(errorMessage, response.status, errorData);

    } catch (error) {
        // Handle network errors or errors thrown during response processing/custom logic
        if (error instanceof ApiError) {
            // Re-throw ApiErrors directly (already logged if needed)
            throw error;
        } else if (error instanceof TypeError) { // Catches "Failed to fetch" and potentially others
             console.error(`Network or Type Error during fetch for ${endpoint}:`, error);
             throw new ApiError(`Network error: ${error.message}`); // No HTTP status for these
        } else {
             // Catch other unexpected errors (e.g., from URL parsing, JSON.stringify)
             console.error(`An unexpected error occurred during API request to ${endpoint}:`, error);
             throw new ApiError(`Unexpected error: ${error.message}`);
        }
    }
};

// --- Specific API Function Implementations ---

/**
 * Fetches the current logged-in user's data.
 * GET /api/store/users/me/
 */
export const getCurrentUser = () => {
    return apiRequest('api/store/users/me/', 'GET', null, null, false);
};

/**
 * Fetches a list of products, optionally filtered by query parameters.
 * GET /api/store/products/
 * @param {object} [queryParams] - Object containing query parameters (e.g., { limit, category, search }).
 */
export const getProducts = (queryParams = null) => {
    return apiRequest('api/store/products/', 'GET', null, queryParams, false);
};

/**
 * Initiates the login process.
 * POST /api/store/auth/login/init/
 * @param {object} credentials - { username, password, captcha_key, captcha_value }.
 */
export const loginInit = (credentials) => {
    // Ensure credentials object is provided
    if (!credentials) {
        return Promise.reject(new Error("Login credentials are required."));
    }
    return apiRequest('api/store/auth/login/init/', 'POST', credentials, null, true); // Requires CSRF
};

/**
 * Logs the current user out.
 * POST /api/store/auth/logout/
 */
export const logoutUser = () => {
    // Expects 204 No Content on success. Send empty body {} as per test expectation.
    return apiRequest('api/store/auth/logout/', 'POST', {}, null, true); // Requires CSRF
};

/**
 * Updates the current logged-in user's data.
 * PATCH /api/store/users/me/
 * @param {object} updateData - Object containing fields to update.
 */
export const updateCurrentUser = (updateData) => {
     // Ensure updateData object is provided
    if (!updateData || Object.keys(updateData).length === 0) {
        return Promise.reject(new Error("No update data provided for user profile."));
    }
    return apiRequest('api/store/users/me/', 'PATCH', updateData, null, true); // Requires CSRF
};

// --- Add other API functions below as needed, following the pattern ---
/*
export const someOtherGetFunction = (id, queryParams) => {
    return apiRequest(`/api/resource/${id}/`, 'GET', null, queryParams, false);
};

export const createResource = (data) => {
    return apiRequest('/api/resource/', 'POST', data, null, true); // Requires CSRF
};

export const deleteResource = (id) => {
    return apiRequest(`/api/resource/${id}/`, 'DELETE', null, null, true); // Requires CSRF, often expects 204
};
*/