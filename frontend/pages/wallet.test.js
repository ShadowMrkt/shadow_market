// frontend/pages/wallet.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for WalletPage component.
//           - Mocks dependencies (AuthContext, API, Router, child components, constants, notifications, formatters).
//           - Tests initial render, redirect, PGP auth check for balances.
//           - Tests balance display (success and failure).
//           - Tests withdrawal Step 1 (prepare success/failure, validation).
//           - Tests withdrawal Step 2 (execute success/failure, back button).

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import WalletPage from './wallet'; // Adjust path as needed

// --- Mock Dependencies ---

// Mock next/router
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    replace: mockRouterReplace, // Use replace for redirects
    query: {},
    asPath: '/wallet',
    isReady: true,
  }),
}));

// Mock context/AuthContext
let mockAuthContextValue = {
  user: { id: 'user1', username: 'testuser' },
  isPgpAuthenticated: true, // Default to true for most tests
  isLoading: false,
  // Other context values not directly used
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock utils/api
const mockGetWalletBalances = jest.fn();
const mockPrepareWithdrawal = jest.fn();
const mockExecuteWithdrawal = jest.fn();
jest.mock('../utils/api', () => ({ // Adjust path
  getWalletBalances: mockGetWalletBalances,
  prepareWithdrawal: mockPrepareWithdrawal,
  executeWithdrawal: mockExecuteWithdrawal,
}));

// Mock utils/notifications
const mockShowErrorToast = jest.fn();
const mockShowSuccessToast = jest.fn();
const mockShowInfoToast = jest.fn();
jest.mock('../utils/notifications', () => ({ // Adjust path
  showErrorToast: mockShowErrorToast,
  showSuccessToast: mockShowSuccessToast,
  showInfoToast: mockShowInfoToast,
}));

// Mock constants
jest.mock('../utils/constants', () => ({
  SUPPORTED_CURRENCIES: ['XMR', 'BTC'], // Keep consistent with mock balances
  CURRENCY_SYMBOLS: { XMR: 'ɱ', BTC: '₿' },
}));

// Mock formatters
jest.mock('../utils/formatters', () => ({
  formatCurrency: (value, currency) => {
    if (value === null || value === undefined) return 'N/A';
    const symbol = { XMR: 'ɱ', BTC: '₿' }[currency] || currency;
    // Simple mock formatting
    return `${symbol} ${Number(value).toFixed(4)}`;
  }
}));

// Mock child components
jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
// Mock WithdrawalInputForm - capture props and simulate submit
let withdrawalFormProps = {};
const mockWithdrawalFormSubmit = jest.fn(); // To simulate form submit from child
jest.mock('../components/WithdrawalInputForm', () => (props) => {
    withdrawalFormProps = props; // Capture props to inspect/modify in tests
    return (
        <form data-testid="withdrawal-input-form" onSubmit={mockWithdrawalFormSubmit}>
            {/* Simplified mock rendering */}
            <label>Currency<input value={props.currency} onChange={props.onCurrencyChange} disabled={props.disabled || props.isLoading} /></label>
            <label>Amount<input value={props.amount} onChange={props.onAmountChange} disabled={props.disabled || props.isLoading} /></label>
            <label>Address<input value={props.address} onChange={props.onAddressChange} disabled={props.disabled || props.isLoading} /></label>
            <button type="submit" disabled={props.disabled || props.isLoading}>
                {props.isLoading ? 'Preparing...' : 'Prepare Withdrawal'}
            </button>
        </form>
    );
});
// Mock PgpChallengeSigner - capture props and simulate submit
let pgpSignerProps = {};
const mockPgpSignerFormSubmit = jest.fn();
jest.mock('../components/PgpChallengeSigner', () => (props) => {
    pgpSignerProps = props;
    return (
         <form data-testid="pgp-signer-form" onSubmit={mockPgpSignerFormSubmit}>
            <p>Challenge: {props.challengeText}</p>
            <label>Signature<textarea value={props.signatureValue} onChange={props.onSignatureChange} disabled={props.disabled} /></label>
            <button type="submit" disabled={props.disabled}>Execute Withdrawal</button>
         </form>
    );
});
jest.mock('../components/LoadingSpinner', () => ({ size, message }) => <div data-testid={`spinner-${size || 'default'}`}>{message || 'Loading...'}</div>);
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert">{message}</div> : null);

// --- Test Data ---
const mockBalancesData = {
    XMR: { total: "1.5000", available: "1.4500", locked: "0.0500" },
    BTC: { total: "0.1000", available: "0.1000", locked: "0.0000" },
};

// --- Test Suite ---
describe('WalletPage Component', () => {

  beforeEach(() => {
    // Reset all mocks and context state
    jest.clearAllMocks();
    setMockAuthContext({
        user: { id: 'user1', username: 'testuser' },
        isPgpAuthenticated: true,
        isLoading: false,
    });
    mockWithdrawalFormSubmit.mockImplementation(e => e.preventDefault()); // Prevent default submit
    mockPgpSignerFormSubmit.mockImplementation(e => e.preventDefault()); // Prevent default submit
    mockGetWalletBalances.mockResolvedValue(mockBalancesData); // Default success
    withdrawalFormProps = {}; // Clear captured props
    pgpSignerProps = {};
  });

  test('renders loading state initially', () => {
    setMockAuthContext({ user: { id: 'user1' }, isPgpAuthenticated: true, isLoading: true });
    render(<WalletPage />);
    expect(screen.getByText(/Loading wallet.../i)).toBeInTheDocument();
  });

  test('redirects to login if user is null', () => {
    setMockAuthContext({ user: null, isLoading: false });
    render(<WalletPage />);
    expect(mockRouterReplace).toHaveBeenCalledWith('/login?next=/wallet');
  });

  test('shows PGP warning and no balances if not PGP authenticated', async () => {
    setMockAuthContext({ user: { id: 'user1' }, isPgpAuthenticated: false, isLoading: false });
    render(<WalletPage />);
    // Wait briefly for potential fetch attempt (which should be blocked)
    await screen.findByText(/Your Wallet/i);

    expect(mockGetWalletBalances).not.toHaveBeenCalled();
    expect(screen.getByText(/PGP authenticated session required to view balances/i)).toBeInTheDocument();
    expect(screen.queryByText(/Total/i)).not.toBeInTheDocument(); // Balance labels shouldn't render
    // Withdrawal form should also be blocked/disabled
     expect(screen.getByRole('button', { name: /Prepare Withdrawal/i })).toBeDisabled();
  });

  test('fetches and displays balances correctly when authenticated', async () => {
    render(<WalletPage />);

    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalledTimes(1));

    // Check balances are rendered using the mocked formatter
    expect(screen.getByText('XMR')).toBeInTheDocument();
    expect(screen.getByText('ɱ 1.5000', { selector: 'div.balanceValue' })).toBeInTheDocument(); // Total
    expect(screen.getByText('ɱ 1.4500', { selector: 'div.balanceValue' })).toBeInTheDocument(); // Available
    expect(screen.getByText('(ɱ 0.0500 Locked)')).toBeInTheDocument();

    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.getByText('₿ 0.1000', { selector: 'div.balanceValue' })).toBeInTheDocument(); // Total & Available
    expect(screen.getByText('(₿ 0.0000 Locked)')).toBeInTheDocument();
  });

  test('shows error if balance fetch fails', async () => {
    mockGetWalletBalances.mockRejectedValueOnce(new Error('API Error 500'));
    render(<WalletPage />);

    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalledTimes(1));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load wallet balances/i);
    expect(mockShowErrorToast).toHaveBeenCalledWith('API Error 500');
    expect(screen.queryByText(/Total/i)).not.toBeInTheDocument(); // Balances shouldn't render
  });

  // --- Withdrawal Step 1 Tests ---
   test('shows Step 1 form initially when authenticated', async () => {
    render(<WalletPage />);
    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled()); // Wait for balances
    expect(screen.getByTestId('withdrawal-input-form')).toBeInTheDocument();
    expect(screen.getByText(/Step 1: Enter Withdrawal Details/i)).toBeInTheDocument();
    expect(screen.queryByTestId('pgp-signer-form')).not.toBeInTheDocument();
  });

  test('shows validation error for insufficient funds', async () => {
    render(<WalletPage />);
    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());

    // Simulate entering amount greater than available XMR (1.4500)
    withdrawalFormProps.onAmountChange({ target: { value: '2.0' } });
    withdrawalFormProps.onAddressChange({ target: { value: 'some-xmr-address' } });
    withdrawalFormProps.onCurrencyChange({ target: { value: 'XMR' } }); // Ensure currency matches

    // Trigger the component's submit handler directly
    await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });

    expect(await screen.findByRole('alert')).toHaveTextContent(/Insufficient available funds/i);
    expect(mockPrepareWithdrawal).not.toHaveBeenCalled();
  });

    test('shows validation error for invalid amount', async () => {
    render(<WalletPage />);
    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());

    withdrawalFormProps.onAmountChange({ target: { value: 'invalid' } });
    withdrawalFormProps.onAddressChange({ target: { value: 'some-xmr-address' } });

    await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid amount specified/i);
    expect(mockPrepareWithdrawal).not.toHaveBeenCalled();
  });

   test('shows validation error for missing address', async () => {
    render(<WalletPage />);
    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());

    withdrawalFormProps.onAmountChange({ target: { value: '0.1' } });
    withdrawalFormProps.onAddressChange({ target: { value: ' ' } }); // Empty address

    await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });

    expect(await screen.findByRole('alert')).toHaveTextContent(/Destination address is required/i);
    expect(mockPrepareWithdrawal).not.toHaveBeenCalled();
  });

  test('calls prepareWithdrawal and proceeds to Step 2 on successful prepare', async () => {
    const prepResponse = { pgp_message_to_sign: 'SIGN THIS MESSAGE' };
    mockPrepareWithdrawal.mockResolvedValueOnce(prepResponse);
    render(<WalletPage />);
    await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());

    // Simulate valid input via captured props
    const amount = '0.1';
    const address = 'valid-xmr-address';
    withdrawalFormProps.onAmountChange({ target: { value: amount } });
    withdrawalFormProps.onAddressChange({ target: { value: address } });
    withdrawalFormProps.onCurrencyChange({ target: { value: 'XMR' } });

    // Trigger the component's submit handler
    await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });

    expect(mockPrepareWithdrawal).toHaveBeenCalledTimes(1);
    expect(mockPrepareWithdrawal).toHaveBeenCalledWith({
      currency: 'XMR', amount: amount, address: address
    });

    // Check UI changes to Step 2
    await waitFor(() => expect(screen.getByText(/Step 2: Confirm with PGP Signature/i)).toBeInTheDocument());
    expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument();
    expect(screen.getByTestId('challenge-text')).toHaveTextContent(prepResponse.pgp_message_to_sign);
    expect(mockShowInfoToast).toHaveBeenCalledWith("Withdrawal prepared. Please sign the confirmation message.");
    expect(screen.queryByTestId('withdrawal-input-form')).not.toBeInTheDocument();
  });

  test('shows error on failed prepareWithdrawal', async () => {
     mockPrepareWithdrawal.mockRejectedValueOnce(new Error('Prepare API Failed'));
     render(<WalletPage />);
     await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());

    // Simulate valid input
    withdrawalFormProps.onAmountChange({ target: { value: '0.1' } });
    withdrawalFormProps.onAddressChange({ target: { value: 'valid-xmr-address' } });

    // Trigger submit
    await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });

    expect(mockPrepareWithdrawal).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('alert')).toHaveTextContent('Prepare API Failed');
    expect(mockShowErrorToast).toHaveBeenCalledWith('Prepare API Failed');
    // Should remain on Step 1
    expect(screen.getByTestId('withdrawal-input-form')).toBeInTheDocument();
    expect(screen.queryByTestId('pgp-signer-form')).not.toBeInTheDocument();
  });

  // --- Withdrawal Step 2 Tests ---
   test('goes back to Step 1 from Step 2', async () => {
     // Setup Step 2
     mockPrepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS' });
     render(<WalletPage />);
     await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());
     withdrawalFormProps.onAmountChange({ target: { value: '0.1' } });
     withdrawalFormProps.onAddressChange({ target: { value: 'valid-xmr-address' } });
     await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });
     await waitFor(() => expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument());

     // Click Back button
     const backButton = screen.getByRole('button', { name: /Back/i });
     await userEvent.click(backButton);

     // Check back in Step 1
     expect(screen.getByTestId('withdrawal-input-form')).toBeInTheDocument();
     expect(screen.queryByTestId('pgp-signer-form')).not.toBeInTheDocument();
   });

   test('calls executeWithdrawal and resets on successful Step 2 submit', async () => {
       // Setup Step 2
       const amount = '0.1';
       const address = 'valid-xmr-address';
       const currency = 'XMR';
       mockPrepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS' });
       mockExecuteWithdrawal.mockResolvedValueOnce({ transaction_id: 'tx123' });
       render(<WalletPage />);
       await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalledTimes(1));
       withdrawalFormProps.onCurrencyChange({ target: { value: currency } });
       withdrawalFormProps.onAmountChange({ target: { value: amount } });
       withdrawalFormProps.onAddressChange({ target: { value: address } });
       await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });
       await waitFor(() => expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument());

       // Simulate signature input via captured props
       const signature = '-----BEGIN PGP SIGNATURE-----...';
       pgpSignerProps.onSignatureChange({ target: { value: signature } });

       // Trigger the component's submit handler (Step 2)
       await pgpSignerProps.onSubmit({ preventDefault: jest.fn() });

       // Check API call
       expect(mockExecuteWithdrawal).toHaveBeenCalledTimes(1);
       expect(mockExecuteWithdrawal).toHaveBeenCalledWith({
           currency: currency,
           amount: amount,
           address: address,
           pgp_confirmation_signature: signature,
       });

       // Check success toast and balance refresh
       expect(mockShowSuccessToast).toHaveBeenCalledWith(expect.stringContaining('Withdrawal successful!'));
       await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalledTimes(2)); // Initial + after success

       // Check UI reset to Step 1
       expect(screen.getByTestId('withdrawal-input-form')).toBeInTheDocument();
       expect(screen.queryByTestId('pgp-signer-form')).not.toBeInTheDocument();
       // Check form fields in step 1 are reset (by checking captured props again, or re-rendering and checking inputs)
       // Note: This assumes the component correctly clears state internally. A direct check is harder with the mock form.
   });

    test('shows error and stays on Step 2 on failed executeWithdrawal', async () => {
       // Setup Step 2
       mockPrepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS' });
       mockExecuteWithdrawal.mockRejectedValueOnce(new Error('Invalid PGP signature provided.'));
       render(<WalletPage />);
       await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());
       withdrawalFormProps.onAmountChange({ target: { value: '0.1' } });
       withdrawalFormProps.onAddressChange({ target: { value: 'valid-xmr-address' } });
       await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });
       await waitFor(() => expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument());

       // Simulate signature input
       const signature = '-----BAD SIGNATURE-----';
       pgpSignerProps.onSignatureChange({ target: { value: signature } });

        // Trigger the component's submit handler (Step 2)
       await pgpSignerProps.onSubmit({ preventDefault: jest.fn() });

        // Check API call
       expect(mockExecuteWithdrawal).toHaveBeenCalledTimes(1);

        // Check error display
       expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid PGP signature/i);
       expect(mockShowErrorToast).toHaveBeenCalledWith('Invalid PGP signature provided.');

       // Should remain on Step 2
       expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument();
       expect(screen.queryByTestId('withdrawal-input-form')).not.toBeInTheDocument();
       expect(mockGetWalletBalances).toHaveBeenCalledTimes(1); // No refresh on error

   });

    test('resets to Step 1 if executeWithdrawal fails with expired error', async () => {
       // Setup Step 2
       mockPrepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS' });
       // Simulate API error indicating expiration
       mockExecuteWithdrawal.mockRejectedValueOnce(new Error('Withdrawal confirmation expired or invalid.'));
       render(<WalletPage />);
       await waitFor(() => expect(mockGetWalletBalances).toHaveBeenCalled());
       withdrawalFormProps.onAmountChange({ target: { value: '0.1' } });
       withdrawalFormProps.onAddressChange({ target: { value: 'valid-xmr-address' } });
       await withdrawalFormProps.onSubmit({ preventDefault: jest.fn() });
       await waitFor(() => expect(screen.getByTestId('pgp-signer-form')).toBeInTheDocument());

       // Simulate signature input
       pgpSignerProps.onSignatureChange({ target: { value: 'some signature' } });

       // Trigger the component's submit handler (Step 2)
       await pgpSignerProps.onSubmit({ preventDefault: jest.fn() });

       // Check API call
       expect(mockExecuteWithdrawal).toHaveBeenCalledTimes(1);

        // Check error display
       expect(await screen.findByRole('alert')).toHaveTextContent(/Withdrawal confirmation expired or invalid/i);
       expect(mockShowErrorToast).toHaveBeenCalledWith('Withdrawal confirmation expired or invalid. Please start over.');

       // Should reset to Step 1
       expect(screen.getByTestId('withdrawal-input-form')).toBeInTheDocument();
       expect(screen.queryByTestId('pgp-signer-form')).not.toBeInTheDocument();
    });

});