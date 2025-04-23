// frontend/pages/register.test.js
// --- REVISION HISTORY ---
// ... (Previous revisions) ...
// 2025-04-13 (Gemini): Rev 16 - Fix typo in PGP Key label query (/PGP Public K ey/i -> /PGP Public Key/i). Change 'missing fields' assertion to use queryByTestId('form-error') within waitFor.
// 2025-04-13 (Gemini): Rev 17 - Revert 'missing fields' assertion to use findByTestId directly, removing explicit waitFor block, as findBy* includes waiting. Add debug log *before* assertion.
// 2025-04-22 (Gemini): Rev 18 - Update fetch mocks to use absolute URLs based on expected NEXT_PUBLIC_API_URL env var. Standardize mock response structure. Add explicit waitFor for API calls in validation tests before checking for alerts.
// 2025-04-22 (Gemini): Rev 19 - Change 'missing fields' assertion from findByTestId('form-error') to findByRole('alert') to better align with FormError mock.
// 2025-04-22 (Gemini): Rev 20 - Wrap click and assertion in explicit waitFor for 'missing fields' test to handle potential timing issues. Use getByRole inside waitFor.
// 2025-04-23 (Gemini): Rev 21 - Removed debugging console.log statements for mock fetch interceptions.

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

// --- Mock Dependencies ---
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();
jest.mock('next/router', () => ({
    useRouter: () => ({
        push: mockRouterPush,
        replace: mockRouterReplace,
        query: {},
        asPath: '/register',
        isReady: true,
    }),
}));

let mockAuthContextValue = { user: null, isLoading: false };
jest.mock('../context/AuthContext', () => ({
    useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
    mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

const mockRegisterUser = jest.fn();
jest.mock('../utils/api', () => ({
    __esModule: true,
    ApiError: class ApiError extends Error {
        constructor(message, status, data) {
           super(message);
            this.status = status;
            this.data = data;
            this.name = 'ApiError';
        }
    },
    registerUser: mockRegisterUser,
}));

const mockShowErrorToast = jest.fn();
const mockShowSuccessToast = jest.fn();
jest.mock('../utils/notifications', () => ({
    __esModule: true,
    showErrorToast: mockShowErrorToast,
    showSuccessToast: mockShowSuccessToast,
}));

const mockMinPasswordLength = 12;
jest.mock('../utils/constants', () => ({
    MIN_PASSWORD_LENGTH: mockMinPasswordLength,
    PGP_PUBLIC_KEY_BLOCK: {
        BEGIN: '-----BEGIN PGP PUBLIC KEY BLOCK-----',
        END: '-----END PGP PUBLIC KEY BLOCK-----',
    }
}));

jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../components/CaptchaInput', () => ({ onChange, onRefresh, isLoading, imageUrl, value, inputKey }) => (
    <div>
        Mock CAPTCHA
        {/* Ensure onChange is correctly passed */}
        <input data-testid="captcha-input" onChange={(e) => onChange(e)} disabled={isLoading} value={value || ''}/>
        <button onClick={onRefresh} disabled={isLoading}>Refresh CAPTCHA</button>
        {/* Use the absolute URL passed in */}
        {imageUrl && <img src={imageUrl} alt="CAPTCHA" />}
        {inputKey && <input type="hidden" name="captcha_key" value={inputKey} />}
    </div>
));
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert" data-testid="form-error">{message}</div> : null);
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);

// --- Setup Mocks ---
// Define the expected backend URL (MUST MATCH your .env.test or test environment)
const MOCK_BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'; // Fallback for safety
const MOCK_CAPTCHA_REFRESH_PATH = '/captcha/refresh/';
const MOCK_INITIAL_CAPTCHA_KEY = 'initialCaptchaKey';
const MOCK_INITIAL_CAPTCHA_IMAGE_URL_RELATIVE = `/captcha/image/${MOCK_INITIAL_CAPTCHA_KEY}/`;
const MOCK_INITIAL_CAPTCHA_IMAGE_URL_ABSOLUTE = `${MOCK_BACKEND_URL}${MOCK_INITIAL_CAPTCHA_IMAGE_URL_RELATIVE}`;

global.fetch = jest.fn();
// --- End Mocks ---

// --- Test Data ---
const validPgpKey = `-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG vX.X.X (...)
mQINBF... [VALID MOCK BLOCK] ... ABC=
-----END PGP PUBLIC KEY BLOCK-----`;

// --- Dynamically Import Component Under Test ---
let RegisterPage;


describe('RegisterPage Component', () => {

    beforeAll(() => {
        // Ensure NEXT_PUBLIC_API_URL is logged if undefined during test setup
        if (!process.env.NEXT_PUBLIC_API_URL) {
             console.warn(`WARN: NEXT_PUBLIC_API_URL is not set in the test environment. Tests depending on it will likely fail. Using fallback: ${MOCK_BACKEND_URL}`);
        } else {
             console.log(`INFO: Using NEXT_PUBLIC_API_URL=${process.env.NEXT_PUBLIC_API_URL} for tests.`);
        }

        RegisterPage = require('./register').default;
        if (!RegisterPage) {
            console.error("Failed to require default export from ./register. Check export style.");
            RegisterPage = require('./register');
        }
        if (!RegisterPage) {
            throw new Error("RegisterPage component could not be loaded.");
        }
    });

    beforeEach(() => {
        jest.clearAllMocks();
        setMockAuthContext({ user: null, isLoading: false });

        // Default fetch mock for initial CAPTCHA load
        global.fetch.mockImplementation((url) => {
            // Check if the URL matches the expected CAPTCHA refresh pattern
             if (url.startsWith(`${MOCK_BACKEND_URL}${MOCK_CAPTCHA_REFRESH_PATH}`)) {
                // <<< REVISION 21: Removed console.log >>>
                // console.log(`Mock Fetch Intercepted (Initial): ${url}`);
                 return Promise.resolve({
                     ok: true,
                     status: 200,
                     json: () => Promise.resolve({
                         key: MOCK_INITIAL_CAPTCHA_KEY,
                         image_url: MOCK_INITIAL_CAPTCHA_IMAGE_URL_RELATIVE // Component expects relative path here
                     }),
                 });
             }
             // Fallback for any other unexpected fetch calls
             console.warn(`Unexpected fetch call in test: ${url}`);
             return Promise.resolve({
                 ok: false,
                 status: 404,
                 json: () => Promise.resolve({ detail: 'Mocked 404 Not Found' }),
             });
        });
    });

    // --- Test Cases ---
    test('renders registration form initially and fetches CAPTCHA', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);

        // Wait for the fetch call triggered by useEffect
        await waitFor(() => {
            expect(global.fetch).toHaveBeenCalledWith(
                expect.stringMatching(new RegExp(`^${MOCK_BACKEND_URL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}${MOCK_CAPTCHA_REFRESH_PATH.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\?_=\\d+$`)) // Match absolute URL with timestamp
            );
        });
        expect(global.fetch).toHaveBeenCalledTimes(1); // Ensure it was called exactly once

        expect(screen.getByRole('heading', { name: /Register New Account/i })).toBeInTheDocument();
        expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();

        // Wait for the image URL to update based on the fetch response
        expect(await screen.findByRole('img', { name: /CAPTCHA/i }))
            .toHaveAttribute('src', MOCK_INITIAL_CAPTCHA_IMAGE_URL_ABSOLUTE); // Check absolute URL is used

        expect(screen.getByRole('button', { name: /Register/i })).toBeInTheDocument();
    });

    test('redirects to profile if user is already logged in', async () => {
       if (!RegisterPage) throw new Error("RegisterPage not loaded");
        setMockAuthContext({ user: { username: 'existingUser' }, isLoading: false });
        render(<RegisterPage />);
        await waitFor(() => {
            expect(mockRouterPush).toHaveBeenCalledWith('/profile');
        });
        expect(global.fetch).not.toHaveBeenCalled(); // Should not fetch CAPTCHA if redirecting
    });

    test('fetches initial CAPTCHA and handles refresh', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);

        // Wait for initial fetch
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
        expect(await screen.findByRole('img', { name: /CAPTCHA/i }))
            .toHaveAttribute('src', MOCK_INITIAL_CAPTCHA_IMAGE_URL_ABSOLUTE);

        // Mock response for the *refresh* click
        const refreshedKey = 'newCaptchaKey';
        const refreshedImageUrlRelative = `/captcha/image/${refreshedKey}/`;
        const refreshedImageUrlAbsolute = `${MOCK_BACKEND_URL}${refreshedImageUrlRelative}`;

        global.fetch.mockImplementationOnce((url) => { // Use mockImplementationOnce for the next call
             if (url.startsWith(`${MOCK_BACKEND_URL}${MOCK_CAPTCHA_REFRESH_PATH}`)) {
                // <<< REVISION 21: Removed console.log >>>
                // console.log(`Mock Fetch Intercepted (Refresh): ${url}`);
                 return Promise.resolve({
                     ok: true,
                     status: 200,
                     json: () => Promise.resolve({ key: refreshedKey, image_url: refreshedImageUrlRelative }),
                 });
             }
             return Promise.reject(new Error(`Unexpected refresh fetch URL: ${url}`));
        });


        const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
        const user = userEvent.setup();
        await user.click(refreshButton);

        // Wait for the second fetch call (refresh)
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
        expect(global.fetch).toHaveBeenNthCalledWith(2,
             expect.stringMatching(new RegExp(`^${MOCK_BACKEND_URL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}${MOCK_CAPTCHA_REFRESH_PATH.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\?_=\\d+$`))
        );

        // Wait for the image to update
        expect(await screen.findByRole('img', { name: /CAPTCHA/i }))
            .toHaveAttribute('src', refreshedImageUrlAbsolute);
    });

    test('handles input changes correctly', async () => {
       if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA fetch

        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'newuser');
        await user.type(screen.getByLabelText(/^Password$/i), 'newpassword123');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'newpassword123');
        // Use fireEvent for textarea as userEvent.type might be slow/complex for large text blocks
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: 'test pgp content' } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');

        expect(screen.getByLabelText(/Username/i)).toHaveValue('newuser');
        expect(screen.getByLabelText(/^Password$/i)).toHaveValue('newpassword123');
        expect(screen.getByLabelText(/Confirm Password/i)).toHaveValue('newpassword123');
        expect(screen.getByLabelText(/PGP Public Key/i)).toHaveValue('test pgp content');
        expect(screen.getByTestId('captcha-input')).toHaveValue('abcde');
    });


    // --- Client-side Validation Tests ---
    test('shows error if required fields are missing on submit', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        // Wait for initial CAPTCHA fetch to complete before interacting
        await waitFor(() => expect(global.fetch).toHaveBeenCalled());
        // Ensure captcha image is loaded before interacting further
        await screen.findByRole('img', { name: /CAPTCHA/i });

        const user = userEvent.setup();
        const registerButton = screen.getByRole('button', { name: /Register/i });

        // Wrap the click and the assertion check within waitFor
        await waitFor(async () => {
            await user.click(registerButton);
            // Check for the alert *after* the click within the waitFor callback
            const alert = screen.getByRole('alert'); // Use getByRole here since waitFor retries
            expect(alert).toBeInTheDocument();
            expect(alert).toHaveTextContent(/All fields, including CAPTCHA, are required./i);
            expect(alert).toHaveAttribute('role', 'alert');
            expect(alert).toHaveAttribute('data-testid', 'form-error');
        });

        // This assertion remains outside waitFor, as it checks a side effect *after* the interaction
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if passwords do not match', async () => {
       if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA

        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'user');
        await user.type(screen.getByLabelText(/^Password$/i), 'ValidPassword123');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'DifferentPassword456');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: validPgpKey } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');
        await user.click(screen.getByRole('button', { name: /Register/i }));

        // Wait for the error message
        const alert = await screen.findByRole('alert'); // findByRole is okay since FormError mock uses it
        expect(alert).toHaveTextContent(/Passwords do not match/i);
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if password is too short', async () => {
       if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA

        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'user');
        await user.type(screen.getByLabelText(/^Password$/i), 'short');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'short');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: validPgpKey } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');
        await user.click(screen.getByRole('button', { name: /Register/i }));

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent(`Password must be at least ${mockMinPasswordLength} characters long.`);
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if PGP key format is invalid (missing BEGIN marker)', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA

        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'user');
        await user.type(screen.getByLabelText(/^Password$/i), 'ValidPassword1234');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'ValidPassword1234');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: 'invalid pgp key END-----' } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');
        await user.click(screen.getByRole('button', { name: /Register/i }));

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent(/Invalid PGP Key format/i);
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if PGP key format is invalid (missing END marker)', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA

        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'user');
        await user.type(screen.getByLabelText(/^Password$/i), 'ValidPassword1234');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'ValidPassword1234');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: '-----BEGIN PGP PUBLIC KEY BLOCK----- missing end' } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');
        await user.click(screen.getByRole('button', { name: /Register/i }));

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent(/Invalid PGP Key format/i);
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });


    // --- API Submission Tests ---
    test('calls registerUser API and shows success message on valid submit', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        mockRegisterUser.mockResolvedValueOnce({ success: true }); // Assume API returns simple success object
        const user = userEvent.setup();
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA fetch
        await screen.findByRole('img', { name: /CAPTCHA/i }); // Ensure CAPTCHA image is loaded

        const username = 'gooduser';
        const password = 'validPassword123';
        const pgpKey = validPgpKey;
        const captchaValue = 'abcde';

        // Fill the form
        await user.type(screen.getByLabelText(/Username/i), username);
        await user.type(screen.getByLabelText(/^Password$/i), password);
        await user.type(screen.getByLabelText(/Confirm Password/i), password);
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: pgpKey } });
        await user.type(screen.getByTestId('captcha-input'), captchaValue);

        // Submit
        await user.click(screen.getByRole('button', { name: /Register/i }));

        // Wait for API call and check arguments
        await waitFor(() => expect(mockRegisterUser).toHaveBeenCalledTimes(1));
        expect(mockRegisterUser).toHaveBeenCalledWith({
            username: username,
            password: password,
            password_confirm: password, // Component sends this
            pgp_public_key: pgpKey,
            captcha_0: MOCK_INITIAL_CAPTCHA_KEY, // Check key from initial fetch mock
            captcha_1: captchaValue,
        });

        // Check for success message and toast
        expect(await screen.findByText(/Registration Successful!/i)).toBeInTheDocument();
        expect(mockShowSuccessToast).toHaveBeenCalledWith("Registration successful!"); // Check specific message

        // Ensure no error message is displayed
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    test('shows API error and refreshes CAPTCHA on failed registration submit', async () => {
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        // Simulate an API error (e.g., username taken)
        const apiError = new Error("Simulated API Error"); // Use generic Error or specific ApiError
        apiError.status = 400;
        apiError.data = { username: ['User with this username already exists.'] };
        mockRegisterUser.mockRejectedValueOnce(apiError);

        const user = userEvent.setup();
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {}); // Suppress console.error
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1)); // Wait for initial fetch

        // Fill form with data that will cause API error
        await user.type(screen.getByLabelText(/Username/i), 'existinguser');
        await user.type(screen.getByLabelText(/^Password$/i), 'password123456');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'password123456');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: validPgpKey } });
        await user.type(screen.getByTestId('captcha-input'), 'anyvalue');

        // Mock the CAPTCHA *refresh* fetch call that happens *after* failure
        const refreshedKey = 'refreshedKey';
        const refreshedImageUrlRelative = `/captcha/image/${refreshedKey}/`;
        global.fetch.mockImplementationOnce((url) => { // Next fetch call will be the refresh
             if (url.startsWith(`${MOCK_BACKEND_URL}${MOCK_CAPTCHA_REFRESH_PATH}`)) {
                // <<< REVISION 21: Removed console.log >>>
                // console.log(`Mock Fetch Intercepted (Post-Error Refresh): ${url}`);
                 return Promise.resolve({
                     ok: true,
                     status: 200,
                     json: () => Promise.resolve({ key: refreshedKey, image_url: refreshedImageUrlRelative }),
                 });
             }
             return Promise.reject(new Error(`Unexpected post-error fetch URL: ${url}`));
        });

        // Submit
        await user.click(screen.getByRole('button', { name: /Register/i }));

        // Wait for API call (should happen once)
        await waitFor(() => expect(mockRegisterUser).toHaveBeenCalledTimes(1));

        // Check for the specific API error message
        const expectedApiErrorText = /Registration Error: Username: User with this username already exists./i;
        const alert = await screen.findByRole('alert'); // Use findBy* to wait for error
        expect(alert).toHaveTextContent(expectedApiErrorText);

        // Check toast message
        expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringMatching(expectedApiErrorText));

        // Wait for the CAPTCHA refresh fetch call (total 2 fetches)
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

        // Ensure success message isn't shown
        expect(screen.queryByText(/Registration Successful!/i)).not.toBeInTheDocument();

        consoleErrorSpy.mockRestore();
    });
});