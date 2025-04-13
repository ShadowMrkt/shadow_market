// frontend/utils/api.test.js
// --- REVISION HISTORY ---
// 2025-04-11: Rev 5 - Corrected assertion in 500 error test to expect actual text body in error.data.detail.
// 2025-04-11: Rev 4 - Added `headers` to all mock fetch responses.
//                   - Refactored error handling tests to use `.rejects.toMatchObject()` instead of redundant try/catch blocks.
//                   - Adjusted logout test assertion for headers.
// 2025-04-11: Rev 3 - Updated import statement to explicitly include logoutUser and updateCurrentUser.
// 2025-04-09: Rev 2 - Added tests for POST request and error handling (4xx/5xx/Network).
// 2025-04-09: Rev 1 - Initial creation. Mocks fetch/cookie, tests GET requests.

import Cookies from 'js-cookie';
// Import specific functions to test, and the core helper if needed
import {
  // apiRequest, // Only include if apiRequest is tested directly
  getCurrentUser,
  getProducts,
  loginInit,
  logoutUser,
  updateCurrentUser,
  // Import ApiError if you want to use toBeInstanceOf(ApiError)
  // ApiError // Assuming ApiError class is exported from api.js or defined locally for tests
} from './api'; // Adjust path if needed, assumes api.js is in the same dir
import { API_BASE_URL } from './constants'; // Import base URL

// --- Mock global fetch ---
global.fetch = jest.fn();

// --- Mock js-cookie ---
jest.mock('js-cookie', () => ({
  get: jest.fn(),
}));

// Define ApiError locally if not exported/imported, just for instanceof checks
// Or import it from './api' if exported there
class ApiError extends Error {
    constructor(message, status, data) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
}


describe('API Utility Functions', () => {

  beforeEach(() => {
    // Reset mocks before each test
    jest.clearAllMocks();
    // Default successful fetch response - NOW INCLUDES HEADERS
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue({ success: true }),
      statusText: 'OK',
      headers: new Headers({'Content-Type': 'application/json'}), // <-- Added default headers
    });
    // Default CSRF token mock
    Cookies.get.mockReturnValue('mockcsrftoken');
  });

  // --- Test GET request (example: getCurrentUser) ---
  test('getCurrentUser successfully fetches user data', async () => {
    const mockUserData = { id: 1, username: 'test', is_vendor: false };
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue(mockUserData),
      headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
    });
    const user = await getCurrentUser();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/store/users/me/`,
      expect.objectContaining({ method: 'GET' })
    );
    expect(user).toEqual(mockUserData);
  });

   // --- Test GET request with query params (example: getProducts) ---
   test('getProducts constructs URL with query params', async () => {
     const mockProductsResponse = { results: [], count: 0 };
     global.fetch.mockResolvedValueOnce({
       ok: true,
       status: 200,
       json: jest.fn().mockResolvedValue(mockProductsResponse),
       headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
     });
     const params = { limit: 10, category: 'electronics', search: 'widget' };
     await getProducts(params);
     expect(global.fetch).toHaveBeenCalledTimes(1);
     const expectedUrl = `${API_BASE_URL}/api/store/products/?limit=10&category=electronics&search=widget`;
     // Check headers passed TO fetch are minimal for GET
     expect(global.fetch).toHaveBeenCalledWith(expectedUrl, expect.objectContaining({
        method: 'GET',
        headers: expect.any(Headers) // GET shouldn't add Content-Type or CSRF by default
     }));
      // Verify Accept header was set by apiRequest
      const actualHeaders = global.fetch.mock.calls[0][1].headers;
      expect(actualHeaders.get('Accept')).toBe('application/json');
      expect(actualHeaders.has('Content-Type')).toBe(false);
      expect(actualHeaders.has('X-CSRFToken')).toBe(false);
   });


  // --- Test POST request (example: loginInit) ---
  describe('POST Requests (e.g., loginInit)', () => {
    test('loginInit sends correct POST request with body and CSRF token', async () => {
      const credentials = { username: 'user', password: 'pw', captcha_key: 'k', captcha_value: 'v' };
      const mockResponseData = { pgp_challenge: 'challenge', login_phrase: 'phrase' };
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: jest.fn().mockResolvedValue(mockResponseData),
        headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
      });

      const result = await loginInit(credentials);

      expect(global.fetch).toHaveBeenCalledTimes(1);
      expect(Cookies.get).toHaveBeenCalledWith('csrftoken'); // CSRF lookup

      // Verify fetch call details
      const expectedUrl = `${API_BASE_URL}/api/store/auth/login/init/`;
      const expectedConfig = {
        method: 'POST',
        body: JSON.stringify(credentials),
        headers: expect.any(Headers) // Check specific headers below
      };
      expect(global.fetch).toHaveBeenCalledWith(expectedUrl, expect.objectContaining(expectedConfig));

      // Verify headers specifically
      const actualHeaders = global.fetch.mock.calls[0][1].headers;
      expect(actualHeaders.get('Accept')).toBe('application/json');
      expect(actualHeaders.get('Content-Type')).toBe('application/json');
      expect(actualHeaders.get('X-CSRFToken')).toBe('mockcsrftoken');

      expect(result).toEqual(mockResponseData);
    });

    test('handles POST request resulting in 204 No Content', async () => {
        global.fetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            // No json function needed for 204
            statusText: 'No Content',
            headers: new Headers(), // <-- Added headers (can be empty for 204)
        });

        const result = await logoutUser();

        expect(global.fetch).toHaveBeenCalledTimes(1);
        expect(Cookies.get).toHaveBeenCalledWith('csrftoken'); // CSRF lookup

        // Verify fetch call details for logout
        const expectedUrl = `${API_BASE_URL}/api/store/auth/logout/`;
         const expectedConfig = {
            method: 'POST',
            body: JSON.stringify({}), // Empty body sent by api.js
            headers: expect.any(Headers) // Check specific headers below
        };
        expect(global.fetch).toHaveBeenCalledWith(expectedUrl, expect.objectContaining(expectedConfig));

        // Verify headers specifically for logout call
        const actualHeaders = global.fetch.mock.calls[0][1].headers;
        expect(actualHeaders.get('Accept')).toBe('application/json');
        // Content-Type might be added by apiRequest even for empty body depending on implementation
        // expect(actualHeaders.has('Content-Type')).toBe(true); // Adjust if needed
        expect(actualHeaders.get('Content-Type')).toBe('application/json'); // If api.js adds it
        expect(actualHeaders.get('X-CSRFToken')).toBe('mockcsrftoken');

        expect(result).toBeNull(); // apiRequest returns null for 204
    });
  });

  // --- Test PUT/PATCH/DELETE requests ---
  describe('PUT/PATCH/DELETE Requests', () => {
      test('updateCurrentUser sends PATCH request with CSRF', async () => {
          const updateData = { btc_withdrawal_address: 'newAddress' };
          const mockUserResponse = { id: 1, username: 'test', btc_withdrawal_address: 'newAddress' };
          global.fetch.mockResolvedValueOnce({
              ok: true,
              status: 200,
              json: jest.fn().mockResolvedValue(mockUserResponse),
              headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
          });

          const result = await updateCurrentUser(updateData);

          expect(global.fetch).toHaveBeenCalledTimes(1);
          expect(Cookies.get).toHaveBeenCalledWith('csrftoken');

          // Verify fetch call details
          const expectedUrl = `${API_BASE_URL}/api/store/users/me/`;
          const expectedConfig = {
                method: 'PATCH',
                body: JSON.stringify(updateData),
                headers: expect.any(Headers) // Check specific headers below
            };
          expect(global.fetch).toHaveBeenCalledWith(expectedUrl, expect.objectContaining(expectedConfig));

          // Verify headers specifically
          const actualHeaders = global.fetch.mock.calls[0][1].headers;
          expect(actualHeaders.get('Accept')).toBe('application/json');
          expect(actualHeaders.get('Content-Type')).toBe('application/json');
          expect(actualHeaders.get('X-CSRFToken')).toBe('mockcsrftoken');

          expect(result).toEqual(mockUserResponse);
      });
  });


  // --- Test apiRequest error handling ---
  describe('apiRequest Error Handling', () => {
    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('throws error with status for non-ok responses (e.g., 404)', async () => {
        const errorBody = { detail: 'Resource not found' };
        global.fetch.mockResolvedValueOnce({
            ok: false,
            status: 404,
            statusText: 'Not Found',
            headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
            json: jest.fn().mockResolvedValue(errorBody),
        });

        await expect(getCurrentUser()).rejects.toMatchObject({
            name: 'ApiError', // Check the error type (if using class)
            status: 404,
            data: errorBody,
            message: `API Error (404): ${errorBody.detail}` // Check specific message
        });
    });

    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('throws error with status for server errors (e.g., 500)', async () => {
        const statusText = 'Internal Server Error';
        const errorTextBody = '<h1>Server Error</h1>'; // The actual text body returned
        global.fetch.mockResolvedValueOnce({
            ok: false,
            status: 500,
            statusText: statusText,
            headers: new Headers({'Content-Type': 'text/html'}), // <-- Added headers (non-json)
            text: jest.fn().mockResolvedValue(errorTextBody) // Mock text() for non-json
        });

        await expect(getCurrentUser()).rejects.toMatchObject({
            name: 'ApiError',
            status: 500,
            // Check data contains the actual text body in 'detail'
            data: { detail: errorTextBody }, // <-- UPDATED EXPECTATION
            // Check message contains the statusText
            message: `API Error (500): ${statusText}` // <-- KEPT EXPECTATION
        });
    });

    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('throws specific "Unauthorized" error for 401 status', async () => {
        const errorBody = { detail: 'Authentication credentials were not provided.' };
        global.fetch.mockResolvedValueOnce({
            ok: false,
            status: 401,
            statusText: 'Unauthorized',
            headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
            json: jest.fn().mockResolvedValue(errorBody),
        });

        await expect(getCurrentUser()).rejects.toMatchObject({
            name: 'ApiError',
            status: 401,
            data: errorBody,
            message: 'Unauthorized' // Specific message from api.js
        });
    });

    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('throws specific "Forbidden" error for 403 status', async () => {
        const errorBody = { detail: 'Permission denied.' };
        global.fetch.mockResolvedValueOnce({
            ok: false,
            status: 403,
            statusText: 'Forbidden',
            headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
            json: jest.fn().mockResolvedValue(errorBody),
        });

         await expect(getCurrentUser()).rejects.toMatchObject({
            name: 'ApiError',
            status: 403,
            data: errorBody,
            message: 'Forbidden' // Specific message from api.js
        });
    });

    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('parses and includes JSON error details in thrown error message (e.g., 400)', async () => {
        const errorBody = { username: ["Username already taken."], non_field_errors: ["Invalid request."] };
        global.fetch.mockResolvedValueOnce({
             ok: false,
             status: 400,
             statusText: 'Bad Request',
             headers: new Headers({'Content-Type': 'application/json'}), // <-- Added headers
             json: jest.fn().mockResolvedValue(errorBody),
           });

        await expect(loginInit({})).rejects.toMatchObject({
            name: 'ApiError',
            status: 400,
            data: errorBody,
            // Check specific message format from api.js (using stringified JSON)
            message: `API Error (400): ${JSON.stringify(errorBody)}`
        });
    });

    // REFACTORED: Removed try/catch, uses .rejects.toMatchObject()
    test('handles network errors during fetch', async () => {
        const networkError = new TypeError('Failed to fetch');
        global.fetch.mockRejectedValueOnce(networkError);

        await expect(getCurrentUser()).rejects.toMatchObject({
            name: 'ApiError',
            status: undefined, // No status for network errors
            data: undefined,   // No data for network errors
            message: `Network error: ${networkError.message}` // Specific message
        });
    });
  });

});