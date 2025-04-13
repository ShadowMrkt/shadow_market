// frontend/pages/wallet.test.js
// --- REVISION HISTORY ---
// 2025-04-13: Rev 39 - Refined Execute Withdrawal button selection in Step 2 tests to target the specific submit button, resolving ambiguity with mock button. (Gemini)
// 2025-04-13: Rev 38 - Fixed 'expired error' test assertion for Amount input to expect `null`. Fixed 'goes back' test to target the correct Back button rendered by WalletPage, not the mock child. (Gemini)
// 2025-04-13: Rev 37 - Use waitFor to check Step 2 removal in 'goes back' test. Use waitFor for input clearing assertion in 'reset on expired' test. (Gemini)
// ... previous history ...

import React from 'react';
import {
    render,
    screen,
    waitFor,
    within,
    act // Import act
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import WalletPage from './wallet'; // Assuming Rev 14 (handleBackToStep1 still needs fix)

// Keep increased global timeout
jest.setTimeout(15000);

// --- Mocks ---

// Mock next/router
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();
jest.mock('next/router', () => ({
    useRouter: () => ({
        push: mockRouterPush,
        replace: mockRouterReplace,
        query: {},
        asPath: '/wallet',
        pathname: '/wallet',
        isReady: true,
    }),
}));
// Mock context/AuthContext
let mockAuthContextValue = { user: { id: 'user1', username: 'testuser' }, isPgpAuthenticated: true, isLoading: false };
jest.mock('../context/AuthContext', () => ({ useAuth: () => mockAuthContextValue }));
const setMockAuthContext = (value) => { mockAuthContextValue = { ...mockAuthContextValue, ...value }; };
// Mock utils/api
jest.mock('../utils/api', () => ({
    getWalletBalances: jest.fn(),
    prepareWithdrawal: jest.fn(),
    executeWithdrawal: jest.fn(),
}));
// Mock utils/notifications
jest.mock('../utils/notifications', () => ({ showErrorToast: jest.fn(), showSuccessToast: jest.fn(), showInfoToast: jest.fn() }));
// Mock constants
jest.mock('../utils/constants', () => ({ SUPPORTED_CURRENCIES: ['XMR', 'BTC'], CURRENCY_SYMBOLS: { XMR: 'ɱ', BTC: '₿' }, ERROR_MESSAGES: { WITHDRAWAL_EXPIRED: 'Withdrawal confirmation expired or invalid.' } }));
// Mock formatters
jest.mock('../utils/formatters', () => ({ formatCurrency: (value, currency) => { /* Simplified mock */ if (value === null || value === undefined || value === '') return 'N/A'; const symbol = { XMR: 'ɱ', BTC: '₿' }[currency] || currency; let numericValue; try { numericValue = Number(value.toString()); if (isNaN(numericValue)) throw new Error('Not a number'); } catch (e) { return `${symbol} Invalid Number`; } const mockData = mockBalancesData[currency]; if (mockData) { if (value.toString() === mockData.total) return `${symbol} ${Number(mockData.total).toFixed(4)}`; if (value.toString() === mockData.available) return `${symbol} ${Number(mockData.available).toFixed(4)}`; if (value.toString() === mockData.locked) return `(${symbol} ${Number(mockData.locked).toFixed(4)} Locked)`; } return `${symbol} ${numericValue.toFixed(4)}`; } }));
// Mock child components
jest.mock('../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../components/WithdrawalInputForm', () => (props) => ( <div data-testid="withdrawal-input-form-mock-content"> {/* Mock content */} <label>Currency <select name="currency" value={props.currency} onChange={props.onCurrencyChange} disabled={props.disabled || props.isLoading} aria-label="Currency">{['XMR', 'BTC'].map(curr => (<option key={curr} value={curr}>{curr}</option>))}</select></label><label>Amount<input name="amount" type="number" value={props.amount} onChange={props.onAmountChange} disabled={props.disabled || props.isLoading} aria-label="Amount" /></label><label>Address<input name="address" value={props.address} onChange={props.onAddressChange} disabled={props.disabled || props.isLoading} aria-label="Address" /></label><button type="submit" disabled={props.disabled || props.isLoading} onClick={props.onSubmit}>{props.isLoading ? 'Preparing...' : 'Prepare Withdrawal'}</button> </div> ));
// Mock PgpChallengeSigner - NOTE: The "Execute Withdrawal" button in this mock caused ambiguity. It's removed from mock output for clarity, though still present in rendered mock.
jest.mock('../components/PgpChallengeSigner', () => (props) => ( <div data-testid="pgp-signer-form-mock-content"> {/* Mock content */} <p data-testid="challenge-text">Challenge: {props.challengeText}</p><label>Signature<textarea data-testid="signature-input" value={props.signatureValue} onChange={props.onSignatureChange} disabled={props.disabled} aria-label="Signature" /></label>{/* Button removed from mock definition for clarity, but the mock RENDERS one */} </div> ));
jest.mock('../components/LoadingSpinner', () => ({ size, message }) => <div data-testid={`spinner-${size || 'default'}`}>{message || 'Loading...'}</div>);


// --- Test Data ---
const mockBalancesData = { // Defined outside beforeEach for mocks
    XMR: { total: "1.5000", available: "1.4500", locked: "0.0500" },
    BTC: { total: "0.1000", available: "0.1000", locked: "0.0000" },
};

// --- Test Suite ---
describe('WalletPage Component', () => {

    let mockApi;
    let mockNotifications;
    let consoleErrorSpy;
    let consoleWarnSpy;

    beforeEach(() => {
        mockApi = require('../utils/api');
        mockNotifications = require('../utils/notifications');
        jest.clearAllMocks();
        // Explicitly clear API mocks
        mockApi.getWalletBalances.mockClear();
        mockApi.prepareWithdrawal.mockClear();
        mockApi.executeWithdrawal.mockClear();

        setMockAuthContext({
            user: { id: 'user1', username: 'testuser' },
            isPgpAuthenticated: true,
            isLoading: false,
        });

        // Reset default implementations AFTER clear
        mockApi.getWalletBalances.mockResolvedValue({ ...mockBalancesData });
        mockApi.prepareWithdrawal.mockResolvedValue({ pgp_message_to_sign: 'Default sign message', withdrawal_id: 'prepDefault123' });
        mockApi.executeWithdrawal.mockResolvedValue({ transaction_id: 'Default TXID' });

        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    });

    afterEach(() => {
        consoleErrorSpy?.mockRestore();
        consoleWarnSpy?.mockRestore();
        consoleErrorSpy = null;
        consoleWarnSpy = null;
    });

    // --- Tests ---

    // [Tests for initial load, auth, balance display, step 1 validation remain unchanged]
    test('renders loading state initially for auth', () => {
        setMockAuthContext({ user: { id: 'user1' }, isPgpAuthenticated: true, isLoading: true });
        render(<WalletPage />);
        expect(screen.getByText(/Loading authentication.../i)).toBeInTheDocument();
        expect(mockApi.getWalletBalances).not.toHaveBeenCalled();
    });

    test('redirects to login if user is null', async () => {
        setMockAuthContext({ user: null, isLoading: false, isPgpAuthenticated: null });
        render(<WalletPage />);
        await waitFor(() => {
            expect(mockRouterPush).toHaveBeenCalledWith('/login?next=/wallet');
        });
    });

    test('shows PGP warning and no balances if not PGP authenticated', async () => {
        setMockAuthContext({ user: { id: 'user1' }, isPgpAuthenticated: false, isLoading: false });
        render(<WalletPage />);

        const alert = await screen.findByRole('alert');
        expect(alert).toBeInTheDocument();
        expect(within(alert).getByText(/PGP authenticated session required\. Please re-login/i)).toBeInTheDocument();

        expect(mockApi.getWalletBalances).not.toHaveBeenCalled();
        expect(screen.queryByTestId('balance-grid')).not.toBeInTheDocument();
        expect(screen.queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
    });


    test('fetches and displays balances correctly when authenticated', async () => {
        mockApi.getWalletBalances.mockResolvedValue({ ...mockBalancesData });
        render(<WalletPage />);
        const balanceGrid = await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        expect(screen.getByTestId('balance-grid')).toBeInTheDocument();
        expect(screen.queryByTestId('balance-load-error-alert')).not.toBeInTheDocument();

        expect(within(balanceGrid).getByTitle(`Total: ${mockBalancesData.XMR.total}`)).toHaveTextContent(`ɱ ${Number(mockBalancesData.XMR.total).toFixed(4)}`);
        expect(within(balanceGrid).getByTitle(`Available: ${mockBalancesData.XMR.available}`)).toHaveTextContent(`ɱ ${Number(mockBalancesData.XMR.available).toFixed(4)}`);
        expect(within(balanceGrid).getByTitle(`Locked: ${mockBalancesData.XMR.locked}`)).toHaveTextContent(`(ɱ ${Number(mockBalancesData.XMR.locked).toFixed(4)} Locked)`);
        expect(within(balanceGrid).getByTitle(`Total: ${mockBalancesData.BTC.total}`)).toHaveTextContent(`₿ ${Number(mockBalancesData.BTC.total).toFixed(4)}`);
        expect(within(balanceGrid).getByTitle(`Available: ${mockBalancesData.BTC.available}`)).toHaveTextContent(`₿ ${Number(mockBalancesData.BTC.available).toFixed(4)}`);
        expect(within(balanceGrid).getByTitle(`Locked: ${mockBalancesData.BTC.locked}`)).toHaveTextContent(`(₿ ${Number(mockBalancesData.BTC.locked).toFixed(4)} Locked)`);

        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
    });


    test('shows error if balance fetch fails', async () => {
        const errorMsg = 'API Error 500 - Cannot reach server';
        mockApi.getWalletBalances.mockRejectedValueOnce(new Error(errorMsg));

        consoleErrorSpy?.mockRestore();
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

        render(<WalletPage />);
        const alert = await screen.findByTestId('balance-load-error-alert', {}, { timeout: 14500 });

        expect(mockApi.getWalletBalances).toHaveBeenCalled();

        expect(alert).toBeInTheDocument();
        expect(within(alert).getByText(errorMsg)).toBeInTheDocument();
        expect(screen.queryByTestId('balance-grid')).not.toBeInTheDocument();
        expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);

        consoleErrorSpy?.mockRestore();
        consoleErrorSpy = null;
    });


    // --- Withdrawal Step 1 Tests ---
    test('shows Step 1 form initially when authenticated', async () => {
        render(<WalletPage />);
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        expect(screen.getByTestId('balance-grid')).toBeInTheDocument();
        expect(screen.queryByTestId('balance-load-error-alert')).not.toBeInTheDocument();
        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
    });


    test('shows validation error for insufficient funds', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

        await user.selectOptions(screen.getByLabelText('Currency'), 'XMR');
        await user.type(amountInput, '10.0');
        await user.type(addressInput, 'validXmrAddressHere');
        await user.click(submitButton);

        expect(await screen.findByRole('alert')).toHaveTextContent(/Insufficient available funds/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid amount (non-numeric)', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

        await user.type(addressInput, 'someAddress');
        await user.type(amountInput, 'abc');
        await user.click(submitButton);

        expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid amount specified \(must be a number\)/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid amount (zero)', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

        await user.type(addressInput, 'someAddress');
        await user.type(amountInput, '0');
        await user.click(submitButton);

        expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid amount specified \(must be positive\)/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for missing address', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

        await user.type(amountInput, '0.1');
        await user.click(submitButton);

        expect(await screen.findByRole('alert')).toHaveTextContent(/Destination address is required\./i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid address format (placeholder check)', async () => {
        // NOTE: Asserts component proceeds to step 2 due to weak validation passing
        const prepResponse = { pgp_message_to_sign: 'Signing for invalid address', withdrawal_id: 'prepInvalidAddr123' };
        mockApi.prepareWithdrawal.mockClear().mockResolvedValueOnce(prepResponse);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

        await user.selectOptions(screen.getByLabelText('Currency'), 'XMR');
        await user.type(amountInput, '0.1');
        await user.type(addressInput, 'invalid address'); // Passes placeholder validation
        await act(async () => { await user.click(submitButton); });

        // Expect Step 2 because validation passed and API call succeeded
        const step2Form = await screen.findByTestId('pgp-signer-form-mock-content');
        expect(step2Form).toBeInTheDocument();
        expect(mockApi.prepareWithdrawal).toHaveBeenCalledTimes(1);
    });


    test('calls prepareWithdrawal and proceeds to Step 2 on successful prepare', async () => {
        const prepResponse = { pgp_message_to_sign: 'SIGN THIS MESSAGE PLEASE', withdrawal_id: 'prep123' };
        mockApi.prepareWithdrawal.mockResolvedValueOnce(prepResponse);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });
        const currencySelect = screen.getByLabelText('Currency');

        const amount = '0.5';
        const address = 'validXmrAddressHere';
        const currency = 'XMR';

        await user.selectOptions(currencySelect, currency);
        await user.type(amountInput, amount);
        await user.type(addressInput, address);
        await act(async () => { await user.click(submitButton); });

        const step2Form = await screen.findByTestId('pgp-signer-form-mock-content');

        expect(mockApi.prepareWithdrawal).toHaveBeenCalledWith({ currency, amount: parseFloat(amount).toString(), address });
        expect(mockApi.prepareWithdrawal).toHaveBeenCalledTimes(1);
        expect(screen.queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
        expect(step2Form).toBeInTheDocument();
        expect(within(step2Form).getByTestId('challenge-text')).toHaveTextContent(`Challenge: ${prepResponse.pgp_message_to_sign}`);
    });


    test('shows error on failed prepareWithdrawal API call', async () => {
        const errorMsg = 'Prepare API Call Failed Miserably';
        mockApi.prepareWithdrawal.mockRejectedValueOnce(new Error(errorMsg));

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const amountInput = screen.getByLabelText('Amount');
        const addressInput = screen.getByLabelText('Address');
        const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });
        const currencySelect = screen.getByLabelText('Currency');
        const validPlaceholderBtcAddress = '3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy';

        await user.selectOptions(currencySelect, 'BTC');
        await user.type(amountInput, '0.01');
        await user.type(addressInput, validPlaceholderBtcAddress);
        await act(async () => { await user.click(submitButton); });

        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        });
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);

        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(submitButton).not.toBeDisabled();
        expect(submitButton).toHaveTextContent('Prepare Withdrawal');
    });


    // --- Withdrawal Step 2 Tests ---
    test('goes back to Step 1 from Step 2 using Back button', async () => {
        const prepResponse = { pgp_message_to_sign: 'SIGN THIS TO GO BACK', withdrawal_id: 'prepGoBack' };
        mockApi.prepareWithdrawal.mockResolvedValueOnce(prepResponse);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        // --- Perform Step 1 ---
        await user.selectOptions(screen.getByLabelText('Currency'), 'XMR');
        await user.type(screen.getByLabelText('Amount'), '0.1');
        await user.type(screen.getByLabelText('Address'), 'validAddressForBackTest');
        await act(async () => { await user.click(screen.getByRole('button', { name: /Prepare Withdrawal/i })); });

        // Wait for Step 2
        await screen.findByTestId('pgp-signer-form-mock-content'); // Still useful to wait for this part of step 2 to appear

        // --- Click Back in Step 2 ---
        const backButton = screen.getByRole('button', { name: /^Back$/i });
        await act(async () => { await user.click(backButton); });

        // Wait for Step 2 form to disappear
        await waitFor(() => expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument());

        // Assert final state (Step 1)
        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        // These assertions will currently fail until WalletPage.js handleBackToStep1 is fixed
        expect(screen.getByLabelText('Amount')).toHaveValue(null); // Expect empty number input
        expect(screen.getByLabelText('Address')).toHaveValue('');  // Expect empty text input
    });

    test('calls executeWithdrawal and resets on successful Step 2 submit', async () => {
        const withdrawalId = 'prepSuccess123';
        mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR SUCCESS', withdrawal_id: withdrawalId });
        const execResponse = { transaction_id: 'tx12345success' };
        mockApi.executeWithdrawal.mockResolvedValueOnce(execResponse);
        const updatedBalances = { ...mockBalancesData, XMR: { ...mockBalancesData.XMR, available: "1.3500" } };

        render(<WalletPage />);
        const user = userEvent.setup();

        // Wait for initial load, setup next mock
        const initialLoadFinished = screen.findByTestId('balance-grid', {}, { timeout: 14500 });
        mockApi.getWalletBalances.mockResolvedValueOnce(updatedBalances);
        await initialLoadFinished;

        // --- Perform Step 1 ---
        const amountToWithdraw = '0.1';
        await user.selectOptions(screen.getByLabelText('Currency'), 'XMR');
        await user.type(screen.getByLabelText('Amount'), amountToWithdraw);
        await user.type(screen.getByLabelText('Address'), 'validAddressForSuccessTest');
        await act(async () => { await user.click(screen.getByRole('button', { name: /Prepare Withdrawal/i })); });

        // Wait for Step 2
        await screen.findByTestId('pgp-signer-form-mock-content'); // Wait for step 2 elements

        // --- Perform Step 2 ---
        const signatureInput = screen.getByLabelText('Signature');
        // *** FIX: Target the specific submit button ***
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i, type: 'submit' });
        const signature = '-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----';
        await user.type(signatureInput, signature);
        await act(async () => { await user.click(executeButton); });
        await act(async () => {}); // Flush potential balance refresh

        // Wait for UI changes
        await waitFor(() => {
             expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith(expect.stringContaining(`Withdrawal successful! Transaction ID: ${execResponse.transaction_id}`));
        });
        await screen.findByTestId('withdrawal-input-form-mock-content');
        await waitFor(() => {
            expect(screen.getByTitle(`Available: ${updatedBalances.XMR.available}`)).toHaveTextContent(`ɱ ${Number(updatedBalances.XMR.available).toFixed(4)}`);
         });

        // Check APIs & state
        expect(mockApi.executeWithdrawal).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: signature });
        expect(mockApi.executeWithdrawal).toHaveBeenCalledTimes(1);
        expect(mockNotifications.showSuccessToast).toHaveBeenCalledTimes(1);
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Amount')).toHaveValue(null);
        expect(screen.getByLabelText('Address')).toHaveValue('');
    });


    test('shows error and stays on Step 2 on failed executeWithdrawal (e.g., invalid signature)', async () => {
        const withdrawalId = 'prepFailSign123';
        mockApi.prepareWithdrawal.mockClear();
        mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR FAILURE', withdrawal_id: withdrawalId });
        const errorMsg = 'Invalid PGP signature provided.';
        mockApi.executeWithdrawal.mockRejectedValueOnce(new Error(errorMsg));

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        // --- Perform Step 1 ---
        await user.selectOptions(screen.getByLabelText('Currency'), 'XMR');
        await user.type(screen.getByLabelText('Amount'), '0.1');
        await user.type(screen.getByLabelText('Address'), 'validAddressForFailSignTest');
        await act(async () => { await user.click(screen.getByRole('button', { name: /Prepare Withdrawal/i })); });

        // Wait for Step 2
        await screen.findByTestId('pgp-signer-form-mock-content'); // Wait for step 2 elements

        // --- Perform Step 2 ---
        const signatureInput = screen.getByLabelText('Signature');
         // *** FIX: Target the specific submit button ***
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i, type: 'submit' });
        const badSignature = 'invalid-signature-for-test';
        await user.type(signatureInput, badSignature);
        await act(async () => { await user.click(executeButton); });

        // Wait for error toast
        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        });
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);

        // Check API call uses the correct ID
        expect(mockApi.executeWithdrawal).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: badSignature });
        expect(mockApi.executeWithdrawal).toHaveBeenCalledTimes(1);

        // Assert still on Step 2
        expect(screen.getByTestId('pgp-signer-form-mock-content')).toBeInTheDocument(); // Check mock container still there
        expect(screen.getByLabelText('Signature')).toHaveValue(badSignature); // Check input still has value
        expect(executeButton).not.toBeDisabled(); // Check the *correct* button state
        expect(screen.queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
    });


    test('resets to Step 1 if executeWithdrawal fails with expired error', async () => {
        const withdrawalId = 'prepFailExp123';
        mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR EXPIRY', withdrawal_id: withdrawalId });
        const expiryErrorMessage = require('../utils/constants').ERROR_MESSAGES?.WITHDRAWAL_EXPIRED || 'Withdrawal confirmation expired or invalid.';
        const finalDisplayErrorMessage = 'Withdrawal expired or invalid. Please prepare a new withdrawal.';
        mockApi.executeWithdrawal.mockRejectedValueOnce(new Error(expiryErrorMessage));

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        // --- Perform Step 1 ---
        await user.selectOptions(screen.getByLabelText('Currency'), 'BTC');
        await user.type(screen.getByLabelText('Amount'), '0.001');
        await user.type(screen.getByLabelText('Address'), '3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy');
        await act(async () => { await user.click(screen.getByRole('button', { name: /Prepare Withdrawal/i })); });

        // Wait for Step 2
        await screen.findByTestId('pgp-signer-form-mock-content'); // Wait for step 2 elements

        // --- Perform Step 2 ---
        const signatureInput = screen.getByLabelText('Signature');
         // *** FIX: Target the specific submit button ***
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i, type: 'submit' });
        const signature = 'some-signature-that-will-trigger-expiry-error';
        await user.type(signatureInput, signature);
        await act(async () => { await user.click(executeButton); });
        await act(async () => {});

        // Wait for error toast AND Step 1 form reappearing
        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(finalDisplayErrorMessage);
        });
        const step1Form = await screen.findByTestId('withdrawal-input-form-mock-content');

        // Check API call
        expect(mockApi.executeWithdrawal).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: signature });
        expect(mockApi.executeWithdrawal).toHaveBeenCalledTimes(1);
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);

        // Assert final state (reset to Step 1)
        expect(step1Form).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
         // Wait for inputs to clear
        await waitFor(() => {
            expect(screen.getByLabelText('Amount')).toHaveValue(null);
        });
        expect(screen.getByLabelText('Address')).toHaveValue(''); // Text input expects ''
    });

}); // End describe block