// frontend/pages/profile.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for ProfilePage component.
//           - Mocks dependencies (AuthContext, API, Router, child components, constants, notifications).
//           - Tests initial render, redirect, disabled state.
//           - Tests address update (success/failure).
//           - Tests PGP key update initiation, validation, modal confirmation (success/failure).
//           - Tests password change (validation, success/failure).

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import ProfilePage from './profile'; // Adjust path as needed
import { MIN_PASSWORD_LENGTH, PGP_PUBLIC_KEY_BLOCK } from '../utils/constants'; // Import actual constants

// --- Mock Dependencies ---

// Mock next/router
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace, // Use replace for redirects
    query: {},
    asPath: '/profile',
    isReady: true,
  }),
}));

// Mock context/AuthContext
const mockSetUser = jest.fn();
const mockLogout = jest.fn();
let mockAuthContextValue = {
  user: { // Mock initial user data
    id: 'user1',
    username: 'testuser',
    date_joined: new Date('2025-01-01T10:00:00Z').toISOString(),
    last_login: new Date('2025-04-09T12:00:00Z').toISOString(),
    is_vendor: true,
    vendor_level: 2,
    login_phrase: 'correct horse battery staple',
    btc_withdrawal_address: 'initialBTCAddress',
    eth_withdrawal_address: 'initialETHAddress',
    pgp_public_key: `-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: MockKey
Initial PGP Key Data
-----END PGP PUBLIC KEY BLOCK-----`
  },
  isPgpAuthenticated: true,
  isLoading: false,
  setUser: mockSetUser,
  logout: mockLogout,
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock utils/api
const mockUpdateCurrentUser = jest.fn();
jest.mock('../utils/api', () => ({ // Adjust path
  updateCurrentUser: mockUpdateCurrentUser,
}));

// Mock utils/notifications
const mockShowErrorToast = jest.fn();
const mockShowSuccessToast = jest.fn();
const mockShowWarningToast = jest.fn();
const mockShowInfoToast = jest.fn();
jest.mock('../utils/notifications', () => ({ // Adjust path
  showErrorToast: mockShowErrorToast,
  showSuccessToast: mockShowSuccessToast,
  showWarningToast: mockShowWarningToast,
  showInfoToast: mockShowInfoToast,
}));

// Mock child components
jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
// Mock Modal to make content accessible and simulate close
let isModalOpen = false; // Track modal state for test purposes
let modalCloseHandler = () => {};
jest.mock('../components/Modal', () => ({ isOpen, onClose, title, children }) => {
    isModalOpen = isOpen; // Update tracked state
    modalCloseHandler = onClose; // Store close handler
    if (!isOpen) return null;
    return (
        <div role="dialog" aria-modal="true" aria-labelledby="mockModalTitle">
            {title && <h2 id="mockModalTitle">{title}</h2>}
            {children}
            <button onClick={onClose}>Close Mock Modal</button> {/* Add way to close */}
        </div>
    );
});
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert">{message}</div> : null);
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);

// --- Helper ---
const validPgpKeyNew = `-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: MockKeyNew
New PGP Key Data
-----END PGP PUBLIC KEY BLOCK-----`;

// --- Test Suite ---
describe('ProfilePage Component', () => {

  beforeEach(() => {
    // Reset mocks and context state before each test
    jest.clearAllMocks();
    // Reset user to default mock data, assuming PGP authenticated
    setMockAuthContext({
        user: {
            id: 'user1', username: 'testuser',
            date_joined: new Date('2025-01-01T10:00:00Z').toISOString(),
            last_login: new Date('2025-04-09T12:00:00Z').toISOString(),
            is_vendor: true, vendor_level: 2, login_phrase: 'correct horse battery staple',
            btc_withdrawal_address: 'initialBTCAddress', eth_withdrawal_address: 'initialETHAddress',
            pgp_public_key: `-----BEGIN PGP PUBLIC KEY BLOCK-----\nVersion: MockKey\nInitial PGP Key Data\n-----END PGP PUBLIC KEY BLOCK-----`
        },
        isPgpAuthenticated: true,
        isLoading: false,
        setUser: mockSetUser,
        logout: mockLogout,
    });
     isModalOpen = false; // Reset modal tracking state
  });

  test('renders user information and populates forms correctly', () => {
    render(<ProfilePage />);

    // Check read-only info
    expect(screen.getByText('Username:')).toBeInTheDocument();
    expect(screen.getByText(mockAuthContextValue.user.username)).toBeInTheDocument();
    expect(screen.getByText('Joined:')).toBeInTheDocument();
    expect(screen.getByText(formatDate(mockAuthContextValue.user.date_joined))).toBeInTheDocument(); // Checks formatter is used
    expect(screen.getByText('Last Login:')).toBeInTheDocument();
    // Check login phrase
    expect(screen.getByText('Login Phrase (Anti-Phishing):')).toBeInTheDocument();
    expect(screen.getByText(mockAuthContextValue.user.login_phrase)).toBeInTheDocument();
    // Check vendor status
    expect(screen.getByText('Vendor Status:')).toBeInTheDocument();
    expect(screen.getByText(/Yes \(Level 2\)/i)).toBeInTheDocument();

    // Check form fields populated
    expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toHaveValue(mockAuthContextValue.user.btc_withdrawal_address);
    expect(screen.getByLabelText(/Ethereum \(ETH\) Address/i)).toHaveValue(mockAuthContextValue.user.eth_withdrawal_address);
    expect(screen.getByLabelText(/Your Public Key Block/i)).toHaveValue(mockAuthContextValue.user.pgp_public_key);
  });

  test('redirects to login if user is not logged in', () => {
    setMockAuthContext({ user: null, isLoading: false }); // Set user to null
    render(<ProfilePage />);
    expect(mockRouterReplace).toHaveBeenCalledWith('/login?next=/profile');
  });

  test('disables forms if PGP is not authenticated', () => {
    setMockAuthContext({ ...mockAuthContextValue, isPgpAuthenticated: false });
    render(<ProfilePage />);

    // Check warning message
    expect(screen.getByText(/Your session is not PGP authenticated/i)).toBeInTheDocument();

    // Check form fields and buttons are disabled
    expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /Save Addresses/i })).toBeDisabled();

    expect(screen.getByLabelText(/Your Public Key Block/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /Update PGP Key.../i })).toBeDisabled();

    expect(screen.getByLabelText(/Current Password/i)).toBeDisabled();
    expect(screen.getByLabelText(/New Password/i)).toBeDisabled();
    expect(screen.getByLabelText(/Confirm New Password/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /Change Password/i })).toBeDisabled();
  });

  // --- Address Update Tests ---
  test('updates address fields and handles successful save', async () => {
    mockUpdateCurrentUser.mockResolvedValueOnce({ ...mockAuthContextValue.user, btc_withdrawal_address: 'newBTCAddress' });
    render(<ProfilePage />);

    const btcInput = screen.getByLabelText(/Bitcoin \(BTC\) Address/i);
    await userEvent.clear(btcInput);
    await userEvent.type(btcInput, 'newBTCAddress');
    expect(btcInput).toHaveValue('newBTCAddress');

    await userEvent.click(screen.getByRole('button', { name: /Save Addresses/i }));

    expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1);
    expect(mockUpdateCurrentUser).toHaveBeenCalledWith({
      btc_withdrawal_address: 'newBTCAddress',
      eth_withdrawal_address: 'initialETHAddress', // Unchanged
    });
    expect(mockSetUser).toHaveBeenCalledTimes(1);
    expect(mockSetUser).toHaveBeenCalledWith(expect.objectContaining({ btc_withdrawal_address: 'newBTCAddress' }));
    expect(mockShowSuccessToast).toHaveBeenCalledWith("Withdrawal addresses updated!");
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('shows error on failed address save', async () => {
    mockUpdateCurrentUser.mockRejectedValueOnce(new Error('Invalid BTC address format'));
    render(<ProfilePage />);

    await userEvent.type(screen.getByLabelText(/Bitcoin \(BTC\) Address/i), 'invalid-btc');
    await userEvent.click(screen.getByRole('button', { name: /Save Addresses/i }));

    expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1);
    expect(mockSetUser).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid BTC address format');
    expect(mockShowErrorToast).toHaveBeenCalledWith('Update failed: Invalid BTC address format');
  });

  // --- PGP Key Update Tests ---
  test('shows PGP format error on client-side validation fail', async () => {
     render(<ProfilePage />);
     const pgpInput = screen.getByLabelText(/Your Public Key Block/i);
     await userEvent.clear(pgpInput);
     await userEvent.type(pgpInput, 'this is not a pgp key');
     await userEvent.click(screen.getByRole('button', { name: /Update PGP Key.../i }));

     expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid PGP Key format/i);
     expect(mockShowErrorToast).toHaveBeenCalledWith('Invalid PGP key format.');
     expect(isModalOpen).toBe(false); // Modal should not open
     expect(mockUpdateCurrentUser).not.toHaveBeenCalled();
  });

  test('opens confirmation modal on valid PGP update initiation', async () => {
    render(<ProfilePage />);
    const pgpInput = screen.getByLabelText(/Your Public Key Block/i);
    await userEvent.clear(pgpInput);
    await userEvent.type(pgpInput, validPgpKeyNew); // Use valid format

    await userEvent.click(screen.getByRole('button', { name: /Update PGP Key.../i }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // No inline error
    expect(isModalOpen).toBe(true); // Check tracked modal state
    expect(screen.getByRole('dialog')).toBeInTheDocument(); // Modal should be rendered
    expect(screen.getByRole('heading', { name: /Confirm PGP Key Update/i })).toBeInTheDocument();
    expect(screen.getByText(/CRITICAL SECURITY WARNING/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Confirm & Update PGP Key/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument(); // Or 'Close Mock Modal' from mock
  });

   test('closes PGP modal on cancel', async () => {
    render(<ProfilePage />);
    await userEvent.clear(screen.getByLabelText(/Your Public Key Block/i));
    await userEvent.type(screen.getByLabelText(/Your Public Key Block/i), validPgpKeyNew);
    await userEvent.click(screen.getByRole('button', { name: /Update PGP Key.../i }));

    expect(isModalOpen).toBe(true);
    // Use the mock modal's close button
    await userEvent.click(screen.getByRole('button', { name: /Close Mock Modal/i }));

    expect(isModalOpen).toBe(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('handles successful PGP key update via modal confirmation', async () => {
     mockUpdateCurrentUser.mockResolvedValueOnce({ ...mockAuthContextValue.user, pgp_public_key: validPgpKeyNew });
     render(<ProfilePage />);
     const pgpInput = screen.getByLabelText(/Your Public Key Block/i);
     await userEvent.clear(pgpInput);
     await userEvent.type(pgpInput, validPgpKeyNew);
     await userEvent.click(screen.getByRole('button', { name: /Update PGP Key.../i }));

     // Modal is open
     expect(isModalOpen).toBe(true);
     const confirmButton = screen.getByRole('button', { name: /Confirm & Update PGP Key/i });
     await userEvent.click(confirmButton);

     // Check API call within modal handler
     expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1);
     expect(mockUpdateCurrentUser).toHaveBeenCalledWith({ pgp_public_key: validPgpKeyNew });

     // Check context update and toasts
     expect(mockSetUser).toHaveBeenCalledTimes(1);
     expect(mockSetUser).toHaveBeenCalledWith(expect.objectContaining({ pgp_public_key: validPgpKeyNew }));
     expect(mockShowSuccessToast).toHaveBeenCalledWith("PGP key updated successfully!");
     expect(mockShowWarningToast).toHaveBeenCalledWith(expect.stringContaining("PGP key changed!"));

     // Check modal closed
     expect(isModalOpen).toBe(false);
     expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('shows error within modal on failed PGP key update', async () => {
     mockUpdateCurrentUser.mockRejectedValueOnce(new Error('Backend validation failed'));
     render(<ProfilePage />);
     await userEvent.clear(screen.getByLabelText(/Your Public Key Block/i));
     await userEvent.type(screen.getByLabelText(/Your Public Key Block/i), validPgpKeyNew);
     await userEvent.click(screen.getByRole('button', { name: /Update PGP Key.../i }));

     // Modal is open
     expect(isModalOpen).toBe(true);
     const confirmButton = screen.getByRole('button', { name: /Confirm & Update PGP Key/i });
     await userEvent.click(confirmButton);

     // Check API call
     expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1);

     // Check error shown *within modal*
     const dialog = screen.getByRole('dialog');
     expect(within(dialog).getByRole('alert')).toHaveTextContent('Backend validation failed');
     expect(mockShowErrorToast).toHaveBeenCalledWith('Update failed: Backend validation failed');

     // Modal should remain open
     expect(isModalOpen).toBe(true);
     expect(dialog).toBeInTheDocument();
     expect(mockSetUser).not.toHaveBeenCalled(); // Context shouldn't update
  });


  // --- Password Change Tests ---
  test('shows validation errors for password change', async () => {
     render(<ProfilePage />);
     // Missing fields
     await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));
     expect(await screen.findByRole('alert')).toHaveTextContent(/All password fields are required/i);
     mockUpdateCurrentUser.mockClear(); // Ensure API not called

     // Mismatch
     await userEvent.type(screen.getByLabelText(/Current Password/i), 'currentpass');
     await userEvent.type(screen.getByLabelText(/New Password/i), 'newpass123');
     await userEvent.type(screen.getByLabelText(/Confirm New Password/i), 'newpass456');
     await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));
     expect(await screen.findByRole('alert')).toHaveTextContent(/New passwords do not match/i);
     mockUpdateCurrentUser.mockClear();

     // Too short
     await userEvent.clear(screen.getByLabelText(/New Password/i));
     await userEvent.clear(screen.getByLabelText(/Confirm New Password/i));
     await userEvent.type(screen.getByLabelText(/New Password/i), 'short');
     await userEvent.type(screen.getByLabelText(/Confirm New Password/i), 'short');
     await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));
     expect(await screen.findByRole('alert')).toHaveTextContent(/must be at least 12 characters/i);
     mockUpdateCurrentUser.mockClear();

     // Same as current
      await userEvent.clear(screen.getByLabelText(/New Password/i));
     await userEvent.clear(screen.getByLabelText(/Confirm New Password/i));
     await userEvent.type(screen.getByLabelText(/New Password/i), 'currentpass');
     await userEvent.type(screen.getByLabelText(/Confirm New Password/i), 'currentpass');
     await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));
     expect(await screen.findByRole('alert')).toHaveTextContent(/cannot be the same as the current/i);
     expect(mockUpdateCurrentUser).not.toHaveBeenCalled();
  });

  test('handles successful password change', async () => {
      mockUpdateCurrentUser.mockResolvedValueOnce({ ...mockAuthContextValue.user }); // API success
      render(<ProfilePage />);

      const currentPassInput = screen.getByLabelText(/Current Password/i);
      const newPassInput = screen.getByLabelText(/New Password/i);
      const confirmPassInput = screen.getByLabelText(/Confirm New Password/i);

      await userEvent.type(currentPassInput, 'oldCorrectPassword');
      await userEvent.type(newPassInput, 'newValidPassword123');
      await userEvent.type(confirmPassInput, 'newValidPassword123');

      await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));

      // Check API call
      await waitFor(() => expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1));
      expect(mockUpdateCurrentUser).toHaveBeenCalledWith({
          current_password: 'oldCorrectPassword',
          password: 'newValidPassword123',
          password_confirm: 'newValidPassword123',
      });

      // Check success toasts
      expect(mockShowSuccessToast).toHaveBeenCalledWith("Password changed successfully!");
      expect(mockShowInfoToast).toHaveBeenCalledWith(expect.stringContaining("Use the new password"));

      // Check fields cleared
      expect(currentPassInput).toHaveValue('');
      expect(newPassInput).toHaveValue('');
      expect(confirmPassInput).toHaveValue('');

      expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // No error message
  });

  test('shows error on failed password change (e.g., wrong current password)', async () => {
       mockUpdateCurrentUser.mockRejectedValueOnce({ response: { data: { current_password: ['Invalid current password.'] } } }); // Simulate API error
      render(<ProfilePage />);

      await userEvent.type(screen.getByLabelText(/Current Password/i), 'wrongCurrentPassword');
      await userEvent.type(screen.getByLabelText(/New Password/i), 'newValidPassword123');
      await userEvent.type(screen.getByLabelText(/Confirm New Password/i), 'newValidPassword123');

      await userEvent.click(screen.getByRole('button', { name: /Change Password/i }));

      // Check API call
      await waitFor(() => expect(mockUpdateCurrentUser).toHaveBeenCalledTimes(1));

       // Check error display
      expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid current password/i);
      expect(mockShowErrorToast).toHaveBeenCalledWith(expect.stringContaining('Invalid current password'));

      // Fields should NOT be cleared on error
      expect(screen.getByLabelText(/Current Password/i)).toHaveValue('wrongCurrentPassword');
  });


});