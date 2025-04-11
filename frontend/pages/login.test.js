// frontend/pages/login.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for LoginPage component.
//           - Mocks dependencies (AuthContext, API, Router, child components, fetch).
//           - Tests initial render, redirect, CAPTCHA refresh.
//           - Tests Step 1 submission (success and failure).
//           - Tests Step 2 rendering, Back button, submission (success and failure).

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import LoginPage from './login'; // Adjust path as needed

// --- Mock Dependencies ---

// Mock next/router
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();
const mockRouterQuery = { next: null }; // Default query
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace, // Mock replace for redirect
    query: mockRouterQuery,
    asPath: '/login',
    isReady: true,
  }),
}));

// Mock context/AuthContext
let mockAuthContextValue = {
  user: null,
  isLoading: false,
  login: jest.fn(),
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock utils/api
const mockLoginInit = jest.fn();
const mockLoginPgpVerify = jest.fn();
jest.mock('../utils/api', () => ({ // Adjust path
  loginInit: mockLoginInit,
  loginPgpVerify: mockLoginPgpVerify,
}));

// Mock utils/notifications
const mockShowErrorToast = jest.fn();
const mockShowSuccessToast = jest.fn();
jest.mock('../utils/notifications', () => ({ // Adjust path
  showErrorToast: mockShowErrorToast,
  showSuccessToast: mockShowSuccessToast,
}));

// Mock child components
jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../components/CaptchaInput', () => ({ onChange, onRefresh, isLoading, imageUrl }) => (
  <div>
    Mock CAPTCHA
    <input data-testid="captcha-input" onChange={onChange} disabled={isLoading} />
    <button onClick={onRefresh} disabled={isLoading}>Refresh CAPTCHA</button>
    {imageUrl && <img src={imageUrl} alt="CAPTCHA" />}
  </div>
));
jest.mock('../components/PgpChallengeSigner', () => ({ onSignatureChange, challengeText, username }) => (
  <div>
    Mock PGP Signer for {username}
    <p data-testid="challenge-text">{challengeText}</p>
    <textarea data-testid="signature-input" onChange={onSignatureChange} />
  </div>
));
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert">{message}</div> : null);
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);

// Mock global fetch for CAPTCHA refresh
global.fetch = jest.fn();
// --- End Mocks ---

describe('LoginPage Component', () => {

  beforeEach(() => {
    // Reset all mocks and context state
    jest.clearAllMocks();
    setMockAuthContext({ user: null, isLoading: false, login: jest.fn() });
    mockRouterQuery.next = null; // Reset query param

    // Default successful CAPTCHA fetch
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ key: 'mockCaptchaKey', image_url: '/mock-captcha.png' }),
    });
  });

  test('renders Step 1 form initially', async () => {
    render(<LoginPage />);
    // Wait for initial CAPTCHA load
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    expect(screen.getByText('Step 1 of 2: Enter Credentials')).toBeInTheDocument();
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    expect(screen.getByTestId('captcha-input')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Next: PGP Challenge/i })).toBeInTheDocument();
    expect(screen.queryByText('Step 2 of 2: Verify PGP Signature')).not.toBeInTheDocument();
  });

  test('redirects to profile if user is already logged in', () => {
    setMockAuthContext({ user: { username: 'existingUser' }, isLoading: false });
    render(<LoginPage />);
    expect(mockRouterReplace).toHaveBeenCalledWith('/profile'); // Use replace for redirects
  });

   test('redirects to query param "next" if user is already logged in', () => {
    setMockAuthContext({ user: { username: 'existingUser' }, isLoading: false });
    mockRouterQuery.next = '/some-protected-page';
    render(<LoginPage />);
    expect(mockRouterReplace).toHaveBeenCalledWith('/some-protected-page');
  });

  test('refreshes CAPTCHA on button click', async () => {
    render(<LoginPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1)); // Initial load

    const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
    await userEvent.click(refreshButton);

    // Should fetch again
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  });

  test('shows error if CAPTCHA refresh fails', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network Error')); // Mock initial fetch failure
    render(<LoginPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Failed to load CAPTCHA/i);
  });

  test('handles Step 1 input changes', async () => {
    render(<LoginPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for CAPTCHA

    const usernameInput = screen.getByLabelText(/Username/i);
    const passwordInput = screen.getByLabelText(/Password/i);
    const captchaInput = screen.getByTestId('captcha-input');

    await userEvent.type(usernameInput, 'myuser');
    await userEvent.type(passwordInput, 'mypass');
    await userEvent.type(captchaInput, 'abcde');

    expect(usernameInput).toHaveValue('myuser');
    expect(passwordInput).toHaveValue('mypass');
    expect(captchaInput).toHaveValue('abcde');
  });

  test('shows error on Step 1 submit if fields are missing', async () => {
    render(<LoginPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for CAPTCHA

    const submitButton = screen.getByRole('button', { name: /Next: PGP Challenge/i });
    await userEvent.click(submitButton);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Please fill in all fields/i);
    expect(mockLoginInit).not.toHaveBeenCalled();
  });

  test('calls loginInit and proceeds to Step 2 on successful Step 1 submit', async () => {
    // Mock successful loginInit response
    const pgpData = { pgp_challenge: 'mockChallengeText', login_phrase: 'mockPhrase' };
    mockLoginInit.mockResolvedValueOnce(pgpData);

    render(<LoginPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled()); // Wait for CAPTCHA

    // Fill form
    await userEvent.type(screen.getByLabelText(/Username/i), 'myuser');
    await userEvent.type(screen.getByLabelText(/Password/i), 'mypass');
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');

    // Submit
    const submitButton = screen.getByRole('button', { name: /Next: PGP Challenge/i });
    await userEvent.click(submitButton);

    // Check API call
    expect(mockLoginInit).toHaveBeenCalledTimes(1);
    expect(mockLoginInit).toHaveBeenCalledWith({
      username: 'myuser',
      password: 'mypass',
      captcha_key: 'mockCaptchaKey',
      captcha_value: 'abcde',
    });

    // Check UI transition to Step 2
    await waitFor(() => {
        expect(screen.getByText('Step 2 of 2: Verify PGP Signature')).toBeInTheDocument();
    });
    expect(screen.getByText(pgpData.login_phrase)).toBeInTheDocument(); // Check phrase display
    expect(screen.getByTestId('challenge-text')).toHaveTextContent(pgpData.pgp_challenge);
    expect(screen.getByTestId('signature-input')).toBeInTheDocument();
    expect(screen.queryByText('Step 1 of 2')).not.toBeInTheDocument();
    // Check password field is cleared (optional check)
     expect(screen.queryByLabelText(/Password/i)).not.toBeInTheDocument(); // Assuming it's removed in Step 2
  });

   test('shows error and refreshes CAPTCHA on failed Step 1 submit (API error)', async () => {
    // Mock failed loginInit response
    mockLoginInit.mockRejectedValueOnce(new Error('Invalid credentials'));

    render(<LoginPage />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1)); // Wait for initial CAPTCHA

    // Fill form
    await userEvent.type(screen.getByLabelText(/Username/i), 'myuser');
    await userEvent.type(screen.getByLabelText(/Password/i), 'badpass');
    await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');

    // Submit
    const submitButton = screen.getByRole('button', { name: /Next: PGP Challenge/i });
    await userEvent.click(submitButton);

    // Check API call
    expect(mockLoginInit).toHaveBeenCalledTimes(1);

    // Check error display
    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid username, password, or CAPTCHA./i); // Generic message check
    expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringContaining('Invalid username, password, or CAPTCHA.'));

    // Check CAPTCHA refreshed
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2)); // Initial + refresh on error

    // Check still on Step 1
    expect(screen.getByText('Step 1 of 2: Enter Credentials')).toBeInTheDocument();
  });

  test('handles Step 2 signature input change', async () => {
     // Setup Step 2 UI
     mockLoginInit.mockResolvedValueOnce({ pgp_challenge: 'mockChallengeText', login_phrase: 'mockPhrase' });
     render(<LoginPage />);
     await waitFor(() => expect(global.fetch).toHaveBeenCalled());
     await userEvent.type(screen.getByLabelText(/Username/i), 'myuser');
     await userEvent.type(screen.getByLabelText(/Password/i), 'mypass');
     await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
     await userEvent.click(screen.getByRole('button', { name: /Next: PGP Challenge/i }));
     await waitFor(() => { expect(screen.getByText('Step 2 of 2: Verify PGP Signature')).toBeInTheDocument(); });

     // Interact with signature textarea
     const signatureInput = screen.getByTestId('signature-input');
     const typedSignature = '-----BEGIN PGP SIGNATURE-----...';
     await userEvent.type(signatureInput, typedSignature);

     expect(signatureInput).toHaveValue(typedSignature);
  });

  test('goes back to Step 1 when Back button is clicked', async () => {
     // Setup Step 2 UI
     mockLoginInit.mockResolvedValueOnce({ pgp_challenge: 'mockChallengeText', login_phrase: 'mockPhrase' });
     render(<LoginPage />);
     await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
     await userEvent.type(screen.getByLabelText(/Username/i), 'myuser');
     await userEvent.type(screen.getByLabelText(/Password/i), 'mypass');
     await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
     await userEvent.click(screen.getByRole('button', { name: /Next: PGP Challenge/i }));
     await waitFor(() => { expect(screen.getByText('Step 2 of 2: Verify PGP Signature')).toBeInTheDocument(); });

     // Click Back button
     const backButton = screen.getByRole('button', { name: /Back to Step 1/i });
     await userEvent.click(backButton);

     // Check UI returned to Step 1
     expect(screen.getByText('Step 1 of 2: Enter Credentials')).toBeInTheDocument();
     expect(screen.queryByText('Step 2 of 2')).not.toBeInTheDocument();
     // Check CAPTCHA refreshed on going back
     await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2)); // Initial + refresh on back
  });


  test('calls loginPgpVerify and AuthContext.login on successful Step 2 submit', async () => {
     const username = 'myuser';
     // Setup Step 2 UI
     mockLoginInit.mockResolvedValueOnce({ pgp_challenge: 'mockChallengeText', login_phrase: 'mockPhrase' });
     render(<LoginPage />);
     await waitFor(() => expect(global.fetch).toHaveBeenCalled());
     await userEvent.type(screen.getByLabelText(/Username/i), username); // Use variable
     await userEvent.type(screen.getByLabelText(/Password/i), 'mypass');
     await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
     await userEvent.click(screen.getByRole('button', { name: /Next: PGP Challenge/i }));
     await waitFor(() => { expect(screen.getByText('Step 2 of 2: Verify PGP Signature')).toBeInTheDocument(); });

     // Mock successful PGP verify
     const mockUserData = { id: '123', username: username, /* other user fields */ };
     mockLoginPgpVerify.mockResolvedValueOnce(mockUserData);

     // Input signature and submit
     const signatureInput = screen.getByTestId('signature-input');
     const signature = '-----BEGIN PGP SIGNATURE-----...';
     await userEvent.type(signatureInput, signature);
     const submitStep2Button = screen.getByRole('button', { name: /Login/i });
     await userEvent.click(submitStep2Button);

     // Check API call
     expect(mockLoginPgpVerify).toHaveBeenCalledTimes(1);
     expect(mockLoginPgpVerify).toHaveBeenCalledWith({
       username: username,
       pgp_challenge_signature: signature,
     });

     // Check AuthContext login was called
     expect(mockAuthContextValue.login).toHaveBeenCalledTimes(1);
     expect(mockAuthContextValue.login).toHaveBeenCalledWith(mockUserData, true); // Check user data and PGP status

     // Check success toast
     expect(mockShowSuccessToast).toHaveBeenCalledWith("Login successful!");

     // Note: Redirection is tested separately via the useEffect hook test
  });

  test('shows error, resets to Step 1 on failed Step 2 submit (API error)', async () => {
     const username = 'myuser';
     // Setup Step 2 UI
     mockLoginInit.mockResolvedValueOnce({ pgp_challenge: 'mockChallengeText', login_phrase: 'mockPhrase' });
     render(<LoginPage />);
     await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1)); // Initial CAPTCHA
     await userEvent.type(screen.getByLabelText(/Username/i), username);
     await userEvent.type(screen.getByLabelText(/Password/i), 'mypass');
     await userEvent.type(screen.getByTestId('captcha-input'), 'abcde');
     await userEvent.click(screen.getByRole('button', { name: /Next: PGP Challenge/i }));
     await waitFor(() => { expect(screen.getByText('Step 2 of 2: Verify PGP Signature')).toBeInTheDocument(); });

     // Mock failed PGP verify
     mockLoginPgpVerify.mockRejectedValueOnce(new Error('Invalid signature'));

     // Input signature and submit
     const signatureInput = screen.getByTestId('signature-input');
     const signature = '-----BEGIN PGP SIGNATURE-----BAD';
     await userEvent.type(signatureInput, signature);
     const submitStep2Button = screen.getByRole('button', { name: /Login/i });
     await userEvent.click(submitStep2Button);

     // Check API call
     expect(mockLoginPgpVerify).toHaveBeenCalledTimes(1);

     // Check error display and toast
     expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid PGP signature/i);
     expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringContaining('Invalid PGP signature'));

     // Check UI reset to Step 1
     expect(screen.getByText('Step 1 of 2: Enter Credentials')).toBeInTheDocument();
     // Check CAPTCHA refreshed on error reset
     await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2)); // Initial + refresh on step 2 error
   });

});