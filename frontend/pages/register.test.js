// frontend/pages/register.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for RegisterPage component.
//           - Mocks dependencies (AuthContext, API, Router, child components, fetch, constants).
//           - Tests initial render, redirect, CAPTCHA handling.
//           - Tests client-side validation (required, password, PGP format).
//           - Tests successful and failed registration submissions.

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import RegisterPage from './register'; // Adjust path as needed

// --- Mock Dependencies ---

// Mock next/router
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn(); // Use replace for redirects
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace,
    query: {},
    asPath: '/register',
    isReady: true,
  }),
}));

// Mock context/AuthContext
let mockAuthContextValue = {
  user: null,
  isLoading: false, // Assume auth check is done
  // Other context values not directly used by RegisterPage
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock utils/api
const mockRegisterUser = jest.fn();
jest.mock('../utils/api', () => ({ // Adjust path
  registerUser: mockRegisterUser,
}));

// Mock utils/notifications
const mockShowErrorToast = jest.fn();
const mockShowSuccessToast = jest.fn();
jest.mock('../utils/notifications', () => ({ // Adjust path
  showErrorToast: mockShowErrorToast,
  showSuccessToast: mockShowSuccessToast,
}));

// Mock constants (Provide values used in the component)
jest.mock('../utils/constants', () => ({
    MIN_PASSWORD_LENGTH: 12,
    PGP_PUBLIC_KEY_BLOCK: {
        BEGIN: '-----BEGIN PGP PUBLIC KEY BLOCK-----',
        END: '-----END PGP PUBLIC KEY BLOCK-----',
    }
}));

// Mock child components
jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../components/CaptchaInput', () => ({ onChange, onRefresh, isLoading, imageUrl, value }) => (
  <div>
    Mock CAPTCHA
    <input data-testid="captcha-input" onChange={onChange} disabled={isLoading} value={value}/>
    <button onClick={onRefresh} disabled={isLoading}>Refresh CAPTCHA</button>
    {imageUrl && <img src={imageUrl} alt="CAPTCHA" />}
  </div>
));
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert">{message}</div> : null);
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);

// Mock global fetch for CAPTCHA refresh
global.fetch = jest.fn();
// --- End Mocks ---

// --- Test Data ---
const validPgpKey = `-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG vX.X.X (...)

mQINBF... [VALID MOCK BLOCK] ... ABC=
-----END PGP PUBLIC KEY BLOCK-----`;

describe('RegisterPage Component', () => {

  beforeEach(() => {
    // Reset all mocks and context state
    jest.clearAllMocks();
    setMockAuthContext({ user: null, isLoading: false });

    // Default successful CAPTCHA fetch
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ key: 'mockCaptchaKey', image_url: '/mock-captcha.png' }),
    });
  });

  test('renders registration form initially', async () => {
    render(<RegisterPage />);
    // Wait for initial CAPTCHA load
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    expect(screen.getByRole('heading', { name: /Register New Account/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument(); // Use exact match or better regex for password
    expect(screen.getByLabelText(/Confirm Password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/PGP Public Key/i)).toBeInTheDocument();
    expect(screen.getByTestId('captcha-input')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Register/i })).toBeInTheDocument();
  });

  test('redirects to profile if user is already logged in', () => {
    setMockAuthContext({ user: { username: 'existingUser' }, isLoading: false });
    render(<RegisterPage />);
    expect(mockRouterReplace).toHaveBeenCalledWith('/profile'); // Use replace for redirects
  });

  test('fetches initial CAPTCHA and handles refresh', async () => {
    render(<RegisterPage />);
    // Initial fetch
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('img', { name: /CAPTCHA/i })).toHaveAttribute('src', '/mock-captcha.png');

    // Mock second fetch
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ key: 'newCaptchaKey', image_url: '/new-captcha.png' }),
    });

    // Click refresh
    const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
    await userEvent.click(refreshButton);

    // Check fetch called again and image updates
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => {
        expect(screen.getByRole('img', { name: /CAPTCHA/i })).toHaveAttribute('src', '/new-captcha.png');
    });
  });

  test('handles input changes correctly', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText(/Username/i), 'newuser');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'newpassword123');
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'newpassword123');
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), 'testpgp');
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');

    expect(screen.getByLabelText(/Username/i)).toHaveValue('newuser');
    expect(screen.getByLabelText(/^Password$/i)).toHaveValue('newpassword123');
    expect(screen.getByLabelText(/Confirm Password/i)).toHaveValue('newpassword123');
    expect(screen.getByLabelText(/PGP Public Key/i)).toHaveValue('testpgp');
    expect(screen.getByTestId('captcha-input')).toHaveValue('abcde');
  });

  // --- Client-side Validation Tests ---
  test('shows error if required fields are missing on submit', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/All fields.*required/i);
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  test('shows error if passwords do not match', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await userEvent.type(screen.getByLabelText(/Username/i), 'user');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'password123');
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'password456'); // Mismatch
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), validPgpKey);
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Passwords do not match/i);
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  test('shows error if password is too short', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await userEvent.type(screen.getByLabelText(/Username/i), 'user');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'short'); // Too short
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'short');
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), validPgpKey);
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Password must be at least 12 characters/i);
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  test('shows error if PGP key format is invalid (missing BEGIN marker)', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await userEvent.type(screen.getByLabelText(/Username/i), 'user');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'password123');
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'password123');
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), 'invalid pgp key'); // Invalid format
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid PGP Key format/i);
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  test('shows error if PGP key format is invalid (missing END marker)', async () => {
    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await userEvent.type(screen.getByLabelText(/Username/i), 'user');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'password123');
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'password123');
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), '-----BEGIN PGP PUBLIC KEY BLOCK-----...'); // Missing end
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid PGP Key format/i);
    expect(mockRegisterUser).not.toHaveBeenCalled();
  });

  // --- API Submission Tests ---
  test('calls registerUser API and shows success message on valid submit', async () => {
    mockRegisterUser.mockResolvedValueOnce({ success: true }); // Mock successful API call

    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    // Fill form with valid data
    const username = 'gooduser';
    const password = 'validPassword123';
    const captcha = 'abcde';
    await userEvent.type(screen.getByLabelText(/Username/i), username);
    await userEvent.type(screen.getByLabelText(/^Password$/i), password);
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), password);
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), validPgpKey);
    await userEvent.type(screen.getByTestId('captcha-input'), captcha);

    // Submit
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    // Check API call
    await waitFor(() => expect(mockRegisterUser).toHaveBeenCalledTimes(1));
    expect(mockRegisterUser).toHaveBeenCalledWith({
      username: username,
      password: password,
      password_confirm: password,
      pgp_public_key: validPgpKey,
      captcha_key: 'mockCaptchaKey',
      captcha_value: captcha,
    });

    // Check for success UI
    expect(await screen.findByText(/Registration Successful!/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Proceed to Login/i })).toBeInTheDocument();
    expect(mockShowSuccessToast).toHaveBeenCalledWith("Registration successful!");

    // Check form is hidden/cleared (form fields shouldn't be visible anymore)
    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Register/i })).not.toBeInTheDocument();
  });

  test('shows API error and refreshes CAPTCHA on failed registration submit', async () => {
    const apiError = new Error('Username already exists.'); // Simulate API error
    mockRegisterUser.mockRejectedValueOnce(apiError);

    render(<RegisterPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1)); // Initial CAPTCHA

    // Fill form with valid data
    await userEvent.type(screen.getByLabelText(/Username/i), 'existinguser');
    await userEvent.type(screen.getByLabelText(/^Password$/i), 'password123');
    await userEvent.type(screen.getByLabelText(/Confirm Password/i), 'password123');
    await userEvent.type(screen.getByLabelText(/PGP Public Key/i), validPgpKey);
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');

    // Submit
    await userEvent.click(screen.getByRole('button', { name: /Register/i }));

    // Check API call
    await waitFor(() => expect(mockRegisterUser).toHaveBeenCalledTimes(1));

    // Check error display
    expect(await screen.findByRole('alert')).toHaveTextContent(/Username already exists/i);
    expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringContaining('Registration failed: Username already exists.'));

    // Check CAPTCHA refreshed
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2)); // Initial + refresh on error

    // Check form is still visible
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Register/i })).toBeInTheDocument();
  });

});