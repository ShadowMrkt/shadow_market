// frontend/utils/api.js
// --- REVISION HISTORY ---
// 2025-04-16: Rev 5 - [Gemini] Refined non-401/403 error message to prioritize detail field over stringified JSON, falling back to status text.
// 2025-04-16: Rev 4 - [Gemini] Ensured ApiError constructor correctly uses the generated errorMessage.
// 2025-04-16: Rev 3 - [Gemini] Fixed JSON error message construction in apiRequest to consistently include stringified body, matching test expectation.
// 2025-04-16: Rev 2 - [Gemini] Added applyForVendor and getVendorApplicationStatus functions.
// 2025-04-11: Rev 1 - Recreated file based on utils/api.test.js.
//                  - Implemented core apiRequest helper.
//                  - Added specific functions: getCurrentUser, getProducts, loginInit, logoutUser, updateCurrentUser.
//                  - Implemented CSRF handling via js-cookie.
//                  - Added robust error handling for network errors and non-ok HTTP responses (including 401, 403, 400 with JSON body).
//                  - Used URLSearchParams for query parameters.
//                  - Added ApiError custom error class.

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
        super(message); // Ensure the message passed here is used by the parent Error class
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
 * @returns {Promise<any>} - Resolves with the parsed JSON response, or null for 204 No Content.
 * @throws {ApiError} - Rejects with an ApiError for network issues or non-ok HTTP responses.
 */
export const apiRequest = async (endpoint, method = 'GET', body = null, params = null) => {
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

    const upperMethod = method.toUpperCase(); // Standardize method check
    const headers = new Headers({
        'Accept': 'application/json',
    });

    const config = {
        method: upperMethod,
        headers: headers,
        // credentials: 'include', // Uncomment if backend requires cookies (ensure CORS allows credentials)
        // mode: 'cors', // Usually default, but can be explicit
        // cache: 'no-cache', // Consider cache policy for production
    };

    const stateChangingMethods = ['POST', 'PUT', 'PATCH', 'DELETE']; // Define state-changing methods

    // Only add Content-Type and body if body is actually present and method allows it
    if (body !== null && body !== undefined && stateChangingMethods.includes(config.method)) {
        try {
            config.body = JSON.stringify(body);
            headers.set('Content-Type', 'application/json');
        } catch (e) {
            console.error("Failed to stringify request body:", e);
            throw new Error("Invalid request body provided.");
        }
    }

    // Automatically add CSRF token for state-changing methods
    if (stateChangingMethods.includes(config.method)) {
        const csrfToken = Cookies.get('csrftoken');
        if (csrfToken) {
            headers.set('X-CSRFToken', csrfToken);
        } else {
            console.warn(`CSRF token not found for state-changing request ${config.method} ${endpoint}. Request may fail.`);
            // Depending on backend setup, you might want to throw an error here
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
        let derivedErrorMessage = `API Error (${response.status}): ${response.statusText}`; // Start with default

        // Attempt to parse error body
        try {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                errorData = await response.json();
                // --- FIXED: Prioritize 'detail' field, then stringified JSON, fallback to statusText ---
                if (errorData && typeof errorData === 'object') {
                    if (errorData.detail && typeof errorData.detail === 'string') {
                        // Use the detail string if available and not empty
                        derivedErrorMessage = `API Error (${response.status}): ${errorData.detail}`;
                    } else if (Object.keys(errorData).length > 0) {
                         // If no detail, but other fields exist (e.g., validation errors), stringify the object for the message
                         derivedErrorMessage = `API Error (${response.status}): ${JSON.stringify(errorData)}`;
                    }
                    // If errorData is null, empty object, or not an object/string detail, the default derivedErrorMessage remains.
                }
                // --- End Fix ---
            } else {
                // Handle non-JSON errors (e.g., HTML error pages, plain text)
                const textBody = await response.text();
                errorData = { detail: textBody || response.statusText }; // Store text body in 'detail' for consistency
                derivedErrorMessage = `API Error (${response.status}): ${response.statusText}`; // Keep original status text message
                console.warn(`Received error status ${response.status} with non-JSON content-type: ${contentType} from ${endpoint}`);
            }
        } catch (e) {
            // Handle JSON parsing errors for the error response itself
            console.warn(`Failed to parse error body for status ${response.status} from ${endpoint}:`, e);
            try {
                 // Attempt to get raw text body as fallback detail
                 const textBody = await response.text();
                 errorData = { detail: textBody || response.statusText };
            } catch (textErr) {
                 // If even getting text fails, use statusText
                 errorData = { detail: response.statusText };
            }
             derivedErrorMessage = `API Error (${response.status}): ${response.statusText}`; // Fallback message
        }

        // Throw specific errors for 401/403 (takes precedence over derivedErrorMessage)
        if (response.status === 401) {
            console.error('Unauthorized access detected:', endpoint, errorData);
            throw new ApiError('Unauthorized', response.status, errorData); // Uses specific 'Unauthorized' message
        }
        if (response.status === 403) {
            console.error('Forbidden access detected:', endpoint, errorData);
            throw new ApiError('Forbidden', response.status, errorData); // Uses specific 'Forbidden' message
        }

        // Throw generic ApiError for other non-ok statuses, using the derivedErrorMessage
        throw new ApiError(derivedErrorMessage, response.status, errorData);

    } catch (error) {
        // Handle network errors or errors thrown during response processing/custom logic
        if (error instanceof ApiError) {
            // Re-throw ApiErrors directly (already logged if needed)
            throw error;
        } else if (error instanceof TypeError && error.message === 'Failed to fetch') { // More specific check for network errors
             console.error(`Network Error during fetch for ${endpoint}:`, error);
             throw new ApiError(`Network error: ${error.message}`); // No HTTP status for these
        } else {
             // Catch other unexpected errors (e.g., from URL parsing, JSON.stringify, or other TypeErrors)
             console.error(`An unexpected error occurred during API request to ${endpoint}:`, error);
             throw new ApiError(`Unexpected error: ${error.message || String(error)}`);
        }
    }
};

// --- Specific API Function Implementations ---

/**
 * Fetches the current logged-in user's data.
 * GET /api/store/users/me/
 */
export const getCurrentUser = () => {
    return apiRequest('/api/store/users/me/', 'GET');
};

/**
 * Fetches a list of products, optionally filtered by query parameters.
 * GET /api/store/products/
 * @param {object} [queryParams] - Object containing query parameters (e.g., { limit, category, search }).
 */
export const getProducts = (queryParams = null) => {
    return apiRequest('/api/store/products/', 'GET', null, queryParams);
};

/**
 * Initiates the login process.
 * POST /api/store/auth/login/init/
 * @param {object} credentials - { username, password, captcha_key, captcha_value }.
 */
export const loginInit = (credentials) => {
    if (!credentials) {
        return Promise.reject(new Error("Login credentials are required."));
    }
    return apiRequest('/api/store/auth/login/init/', 'POST', credentials);
};

/**
 * Logs the current user out.
 * POST /api/store/auth/logout/
 */
export const logoutUser = () => {
    return apiRequest('/api/store/auth/logout/', 'POST', {});
};

/**
 * Updates the current logged-in user's data.
 * PATCH /api/store/users/me/
 * @param {object} updateData - Object containing fields to update.
 */
export const updateCurrentUser = (updateData) => {
    if (!updateData || Object.keys(updateData).length === 0) {
        return Promise.reject(new Error("No update data provided for user profile."));
    }
    return apiRequest('/api/store/users/me/', 'PATCH', updateData);
};


// --- <<< NEW: Vendor Application Functions >>> ---

/**
 * Submits a request to apply for vendor status.
 * Assumes the backend endpoint handles creating the VendorApplication record.
 * POST /api/store/vendor/apply/  (VERIFY THIS ENDPOINT)
 * @returns {Promise<object>} The newly created vendor application object.
 */
export const applyForVendor = async () => {
    // !!! IMPORTANT: Verify this endpoint URL matches your backend DRF router/URL configuration !!!
    const endpoint = '/api/store/vendor/apply/';
    // apiRequest handles POST and CSRF automatically
    return await apiRequest(endpoint, 'POST');
    // Include body if the backend requires specific application data
    // return await apiRequest(endpoint, 'POST', { justification: "..." });
};

/**
 * Fetches the current user's active vendor application status.
 * Assumes backend returns the application object or 404 if none exists.
 * GET /api/store/vendor/application-status/ (VERIFY THIS ENDPOINT)
 * @returns {Promise<object|null>} The vendor application object or null if not found/no active app.
 */
export const getVendorApplicationStatus = async () => {
    // !!! IMPORTANT: Verify this endpoint URL matches your backend DRF router/URL configuration !!!
    const endpoint = '/api/store/vendor/application-status/';
    try {
        // apiRequest handles GET automatically
        const applicationData = await apiRequest(endpoint, 'GET');
        // Check if the response is meaningful (not empty object/array if backend sends that for 'not found')
        // Adjust this check based on exactly what your backend returns for "no active application" vs an actual application
        if (applicationData && typeof applicationData === 'object' && Object.keys(applicationData).length > 0) {
             return applicationData;
        }
        console.log("No active vendor application found (API returned non-error, but empty/null data).");
        return null; // No active/meaningful application found

    } catch (error) {
         // Specifically handle 404 as "not found" and return null
         if (error.status === 404) {
             console.log("No active vendor application found (404).");
             return null;
         }
         // Re-throw other errors (like 500, network errors) to be caught by the calling component (profile.js)
         console.error("Error fetching vendor application status:", error);
         throw error; // Re-throw ApiError
    }
};

// --- Add other API functions below as needed, following the pattern ---

// Export the error class if needed elsewhere
export { ApiError };