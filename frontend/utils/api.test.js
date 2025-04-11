// frontend/utils/api.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 2 - Added tests for POST request and error handling (4xx/5xx/Network).
// 2025-04-09: Rev 1 - Initial creation. Mocks fetch/cookie, tests GET requests.

import Cookies from 'js-cookie';
// Import specific functions to test, and the core helper if needed
import {
    apiRequest,
    getCurrentUser,
    loginInit,
    getProducts,
    // ... other functions if needed for specific tests
} from './api'; // Adjust path
import { API_BASE_URL } from './constants'; // Import base URL

// --- Mock global fetch ---
global.fetch = jest.fn();

// --- Mock js-cookie ---
// Use jest.requireActual if you need parts of the original module, but here we just mock 'get'
jest.mock('js-cookie', () => ({
  get: jest.fn(),
}));

describe('API Utility Functions', () => {

  beforeEach(() => {
    // Reset mocks before each test
    jest.clearAllMocks();
    // Default successful fetch response
    global.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue({ success: true }), // Default success JSON
      statusText: 'OK', // Add statusText for error cases
    });
    // Default CSRF token mock
    Cookies.get.mockReturnValue('mockcsrftoken');
  });

  // --- Test GET request (example: getCurrentUser) ---
  test('getCurrentUser successfully fetches user data', async () => {
    const mockUserData = { id: 1, username: 'test', is_vendor: false };
    global.fetch.mockResolvedValueOnce({
      ok: true, status: 200, json: jest.fn().mockResolvedValue(mockUserData),
    });
    const user = await getCurrentUser();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/store/users/me/`, // Corrected endpoint prefix
      expect.objectContaining({ method: 'GET' })
    );
    expect(Cookies.get).not.toHaveBeenCalled();
    expect(user).toEqual(mockUserData);
  });

   // --- Test GET request with query params (example: getProducts) ---
   test('getProducts constructs URL with query params', async () => {
     const mockProductsResponse = { results: [], count: 0 };
     global.fetch.mockResolvedValueOnce({
      ok: true, status: 200, json: jest.fn().mockResolvedValue(mockProductsResponse),
     });
     const params = { limit: 10, category: 'electronics', search: 'widget' };
     await getProducts(params);
     expect(global.fetch).toHaveBeenCalledTimes(1);
     // Check URL encoding and path prefix
     const expectedUrl = `${API_BASE_URL}/api/store/products/?limit=10&category=electronics&search=widget`;
     expect(global.fetch).toHaveBeenCalledWith(expectedUrl, expect.objectContaining({ method: 'GET' }));
     expect(Cookies.get).not.toHaveBeenCalled();
  });


  // --- NEW: Test POST request (example: loginInit) ---
  describe('POST Requests (e.g., loginInit)', () => {
    test('loginInit sends correct POST request with body and CSRF token', async () => {
      const credentials = { username: 'user', password: 'pw', captcha_key: 'k', captcha_value: 'v' };
      const mockResponseData = { pgp_challenge: 'challenge', login_phrase: 'phrase' };
      global.fetch.mockResolvedValueOnce({
        ok: true, status: 200, json: jest.fn().mockResolvedValue(mockResponseData),
      });

      const result = await loginInit(credentials);

      expect(global.fetch).toHaveBeenCalledTimes(1);
      expect(Cookies.get).toHaveBeenCalledWith('csrftoken'); // CSRF should be checked
      expect(global.fetch).toHaveBeenCalledWith(
        `${API_BASE_URL}/api/store/auth/login/init/`, // Corrected endpoint prefix
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'X-CSRFToken': 'mockcsrftoken', // Check CSRF header
          }),
          body: JSON.stringify(credentials), // Check body is stringified
        })
      );
      expect(result).toEqual(mockResponseData);
    });

     test('handles POST request resulting in 204 No Content', async () => {
       // Example: logoutUser might return 204
        global.fetch.mockResolvedValueOnce({
            ok: true,
            status: 204,
            json: jest.fn(), // Should not be called
            statusText: 'No Content',
        });

        const result = await logoutUser(); // Assuming logoutUser uses POST and expects 204

        expect(global.fetch).toHaveBeenCalledTimes(1);
         expect(global.fetch).toHaveBeenCalledWith(
            `${API_BASE_URL}/api/store/auth/logout/`,
            expect.objectContaining({ method: 'POST' })
        );
        expect(result).toBeNull(); // apiRequest should return null for 204
    });
  });

  // --- Test PUT/PATCH/DELETE requests ---
  // (Structure similar to POST tests, just change method and endpoint)
  describe('PUT/PATCH/DELETE Requests', () => {
      test('updateCurrentUser sends PATCH request with CSRF', async () => {
          const updateData = { btc_withdrawal_address: 'newAddress' };
          const mockUserResponse = { id: 1, username: 'test', btc_withdrawal_address: 'newAddress' };
          global.fetch.mockResolvedValueOnce({
              ok: true, status: 200, json: jest.fn().mockResolvedValue(mockUserResponse),
          });

          const result = await updateCurrentUser(updateData);

          expect(global.fetch).toHaveBeenCalledTimes(1);
          expect(Cookies.get).toHaveBeenCalledWith('csrftoken');
          expect(global.fetch).toHaveBeenCalledWith(
              `${API_BASE_URL}/api/store/users/me/`,
              expect.objectContaining({
                  method: 'PATCH',
                  headers: expect.objectContaining({ 'X-CSRFToken': 'mockcsrftoken' }),
                  body: JSON.stringify(updateData),
              })
          );
          expect(result).toEqual(mockUserResponse);
      });

      // Add similar tests for PUT and DELETE if applicable API functions exist
  });


  // --- NEW: Test apiRequest error handling ---
  describe('apiRequest Error Handling', () => {
    test('throws error with status for non-ok responses (e.g., 404)', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: false, // Simulate failure
        status: 404,
        statusText: 'Not Found',
        json: jest.fn().mockResolvedValue({ detail: 'Resource not found' }), // Mock error body
      });

      // Use rejects.toThrow to catch the error thrown by apiRequest
      await expect(getCurrentUser()).rejects.toThrow(/API Error \(404\): Resource not found/);

      // Check that the thrown error has status and data properties
       try {
           await getCurrentUser();
       } catch (e) {
           expect(e.status).toBe(404);
           expect(e.data).toEqual({ detail: 'Resource not found' });
       }
    });

     test('throws error with status for server errors (e.g., 500)', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: false, status: 500, statusText: 'Internal Server Error',
        json: jest.fn().mockRejectedValue(new Error("Cannot parse JSON")), // Mock non-JSON error response
      });

      await expect(getCurrentUser()).rejects.toThrow(/API Error \(500\): Internal Server Error/);
       try {
           await getCurrentUser();
       } catch (e) {
           expect(e.status).toBe(500);
           // e.data might be undefined or contain statusText if JSON parsing failed
           expect(e.data).toEqual({ detail: 'Internal Server Error' });
       }
    });

    test('throws specific "Unauthorized" error for 401 status', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: false, status: 401, statusText: 'Unauthorized',
         json: jest.fn().mockResolvedValue({ detail: 'Authentication credentials were not provided.' }),
      });

      await expect(getCurrentUser()).rejects.toThrow('Unauthorized');
       try {
           await getCurrentUser();
       } catch (e) {
           expect(e.status).toBe(401);
           expect(e.data).toEqual({ detail: 'Authentication credentials were not provided.' });
       }
    });

    test('throws specific "Forbidden" error for 403 status', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: false, status: 403, statusText: 'Forbidden',
         json: jest.fn().mockResolvedValue({ detail: 'Permission denied.' }),
      });

      await expect(getCurrentUser()).rejects.toThrow('Forbidden');
        try {
           await getCurrentUser();
       } catch (e) {
           expect(e.status).toBe(403);
           expect(e.data).toEqual({ detail: 'Permission denied.' });
       }
    });

     test('parses and includes JSON error details in thrown error message (e.g., 400)', async () => {
        const errorBody = { username: ["Username already taken."], non_field_errors: ["Invalid request."] };
         global.fetch.mockResolvedValueOnce({
            ok: false, status: 400, statusText: 'Bad Request',
            json: jest.fn().mockResolvedValue(errorBody),
         });

         // Expect the stringified JSON detail in the error message
         await expect(loginInit({})).rejects.toThrow(`API Error (400): ${JSON.stringify(errorBody)}`);
         try {
            await loginInit({});
        } catch (e) {
            expect(e.status).toBe(400);
            expect(e.data).toEqual(errorBody); // Check the data property
        }
     });

     test('handles network errors during fetch', async () => {
        const networkError = new TypeError('Failed to fetch'); // Simulate network error
        global.fetch.mockRejectedValueOnce(networkError);

        await expect(getCurrentUser()).rejects.toThrow(/Network error: Failed to fetch/);
         try {
            await getCurrentUser();
        } catch (e) {
            expect(e.status).toBeUndefined(); // Network errors don't have HTTP status
            expect(e.data).toBeUndefined();
        }
     });
  });

});