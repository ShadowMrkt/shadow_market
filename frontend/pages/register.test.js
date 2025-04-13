// frontend/pages/register.test.js
// --- REVISION HISTORY ---
// ... (Previous revisions) ...
// 2025-04-13 (Gemini): Rev 16 - Fix typo in PGP Key label query (/PGP Public K ey/i -> /PGP Public Key/i). Change 'missing fields' assertion to use queryByTestId('form-error') within waitFor.
// 2025-04-13 (Gemini): Rev 17 - Revert 'missing fields' assertion to use findByTestId directly, removing explicit waitFor block, as findBy* includes waiting. Add debug log *before* assertion.

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
        <input data-testid="captcha-input" onChange={onChange} disabled={isLoading} value={value || ''}/>
        <button onClick={onRefresh} disabled={isLoading}>Refresh CAPTCHA</button>
        {imageUrl && <img src={imageUrl} alt="CAPTCHA" />}
        {inputKey && <input type="hidden" name="captcha_key" value={inputKey} />}
    </div>
));
// Mock FormError remains the same - responsible for role="alert"
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert" data-testid="form-error">{message}</div> : null);
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);

// Mock global fetch
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
        RegisterPage = require('./register').default;
        if (!RegisterPage) {
            console.error("Failed to require default export from ./register. Check export style.");
            RegisterPage = require('./register');
        }
         if (!RegisterPage) {
             throw new Error("RegisterPage component could not be loaded.");
         }
    });

    beforeEach(async () => {
        jest.clearAllMocks();
        setMockAuthContext({ user: null, isLoading: false });
        global.fetch.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ key: 'initialCaptchaKey', image_url: '/initial-captcha.png' }),
        });
    });

    // --- Test Cases ---
    test('renders registration form initially and fetches CAPTCHA', async () => {
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
        expect(screen.getByRole('heading', { name: /Register New Account/i })).toBeInTheDocument();
        expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
        expect(await screen.findByRole('img', { name: /CAPTCHA/i })).toHaveAttribute('src', '/initial-captcha.png');
        expect(screen.getByRole('button', { name: /Register/i })).toBeInTheDocument();
    });

    test('redirects to profile if user is already logged in', async () => {
        // ... (test unchanged)
         if (!RegisterPage) throw new Error("RegisterPage not loaded");
         setMockAuthContext({ user: { username: 'existingUser' }, isLoading: false });
         render(<RegisterPage />);
         await waitFor(() => {
             expect(mockRouterPush).toHaveBeenCalledWith('/profile');
         });
         expect(global.fetch).not.toHaveBeenCalled();
      });

    test('fetches initial CAPTCHA and handles refresh', async () => {
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
        expect(await screen.findByRole('img', { name: /CAPTCHA/i })).toHaveAttribute('src', '/initial-captcha.png');
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ key: 'newCaptchaKey', image_url: '/new-captcha.png' }),
        });
        const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
        const user = userEvent.setup();
        await user.click(refreshButton);
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
        expect(await screen.findByRole('img', { name: /CAPTCHA/i })).toHaveAttribute('src', '/new-captcha.png');
    });

     test('handles input changes correctly', async () => {
        // ... (test unchanged)
         if (!RegisterPage) throw new Error("RegisterPage not loaded");
         render(<RegisterPage />);
         await waitFor(() => expect(global.fetch).toHaveBeenCalled());
         const user = userEvent.setup();
         await user.type(screen.getByLabelText(/Username/i), 'newuser');
         await user.type(screen.getByLabelText(/^Password$/i), 'newpassword123');
         await user.type(screen.getByLabelText(/Confirm Password/i), 'newpassword123');
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
        await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for initial CAPTCHA
        const user = userEvent.setup();
        const registerButton = screen.getByRole('button', { name: /Register/i });

        await user.click(registerButton);

        // <<< REVISION 17: Use findByTestId directly. Add debug *before* assertion >>>
        console.log("--- DEBUG START (shows error if required fields are missing) ---");
        // Debug the state *just before* the findBy... starts waiting
        screen.debug(undefined, 30000);
        console.log("--- DEBUG END ---");

        // findByTestId includes waiting
        const alert = await screen.findByTestId('form-error');
        expect(alert).toBeInTheDocument();
        expect(alert).toHaveTextContent(/All fields, including CAPTCHA, are required./i);
        expect(alert).toHaveAttribute('role', 'alert');

        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if passwords do not match', async () => {
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled());
        const user = userEvent.setup();
        await user.type(screen.getByLabelText(/Username/i), 'user');
        await user.type(screen.getByLabelText(/^Password$/i), 'ValidPassword123');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'DifferentPassword456');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: validPgpKey } });
        await user.type(screen.getByTestId('captcha-input'), 'abcde');
        await user.click(screen.getByRole('button', { name: /Register/i }));
        const alert = await screen.findByRole('alert'); // findByRole is fine here
        expect(alert).toHaveTextContent(/Passwords do not match/i);
        expect(mockRegisterUser).not.toHaveBeenCalled();
    });

    test('shows error if password is too short', async () => {
        // ... (test unchanged)
         if (!RegisterPage) throw new Error("RegisterPage not loaded");
         render(<RegisterPage />);
         await waitFor(() => expect(global.fetch).toHaveBeenCalled());
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
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled());
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
        // ... (test unchanged after Rev 16 typo fix)
         if (!RegisterPage) throw new Error("RegisterPage not loaded");
         render(<RegisterPage />);
         await waitFor(() => expect(global.fetch).toHaveBeenCalled());
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
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        mockRegisterUser.mockResolvedValueOnce({ success: true });
        const user = userEvent.setup();
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalled());
        await screen.findByRole('img', { name: /CAPTCHA/i });
        const username = 'gooduser';
        const password = 'validPassword123';
        const pgpKey = validPgpKey;
        const captchaValue = 'abcde';
        const initialCaptchaKey = 'initialCaptchaKey';
        await user.type(screen.getByLabelText(/Username/i), username);
        await user.type(screen.getByLabelText(/^Password$/i), password);
        await user.type(screen.getByLabelText(/Confirm Password/i), password);
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: pgpKey } });
        await user.type(screen.getByTestId('captcha-input'), captchaValue);
        await user.click(screen.getByRole('button', { name: /Register/i }));
        await waitFor(() => expect(mockRegisterUser).toHaveBeenCalledTimes(1));
        expect(mockRegisterUser).toHaveBeenCalledWith(expect.objectContaining({
            username: username, password: password, pgp_public_key: pgpKey, captcha_key: initialCaptchaKey, captcha_value: captchaValue,
        }));
        expect(await screen.findByText(/Registration Successful!/i)).toBeInTheDocument();
        expect(mockShowSuccessToast).toHaveBeenCalledWith("Registration successful!");
        await waitFor(() => {
            expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        });
    });

    test('shows API error and refreshes CAPTCHA on failed registration submit', async () => {
        // ... (test unchanged)
        if (!RegisterPage) throw new Error("RegisterPage not loaded");
        const apiError = {
            message: 'Simulated API Error', status: 400, data: { username: ['User with this username already exists.'] }
        };
        mockRegisterUser.mockRejectedValueOnce(apiError);
        const user = userEvent.setup();
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
        render(<RegisterPage />);
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
        await user.type(screen.getByLabelText(/Username/i), 'existinguser');
        await user.type(screen.getByLabelText(/^Password$/i), 'password123456');
        await user.type(screen.getByLabelText(/Confirm Password/i), 'password123456');
        fireEvent.change(screen.getByLabelText(/PGP Public Key/i), { target: { value: validPgpKey } });
        await user.type(screen.getByTestId('captcha-input'), 'anyvalue');
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ key: 'refreshedKey', image_url: '/refreshed-captcha.png' }),
        });
        await user.click(screen.getByRole('button', { name: /Register/i }));
        const expectedApiErrorText = /Registration Error: Username: User with this username already exists./i;
        await waitFor(() => { // Assertion already uses waitFor here
            const alert = screen.queryByTestId('form-error'); // Use testId here too for consistency
            expect(alert).toBeInTheDocument();
            expect(alert).toHaveTextContent(expectedApiErrorText);
        });
        expect(mockRegisterUser).toHaveBeenCalledTimes(1);
        expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringMatching(expectedApiErrorText));
        await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
        expect(screen.queryByText(/Registration Successful!/i)).not.toBeInTheDocument();
        consoleErrorSpy.mockRestore();
    });
});