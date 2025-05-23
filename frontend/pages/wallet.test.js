// frontend/pages/wallet.test.js
// --- REVISION HISTORY ---
// 2025-04-28: Rev 44 - Mocked validation libraries (bitcoin-address-validation, monero-ts, ethers) within the test file to ensure predictable behavior in JSDOM, allowing handlePrepareWithdrawal to proceed past address check. Refined waitFor usage. (Gemini)
// 2025-04-28: Rev 43 - Reverted WithdrawalInputForm mock to include button (as in Rev 41). Changed interaction in tests involving Step 1 submission to use fireEvent.submit() on the form element instead of user.click() on the button, aiming to reliably trigger the form's onSubmit handler. (Gemini)
// 2025-04-28: Rev 42 - Revised WithdrawalInputForm mock to remove its internal button, ensuring tests click the button rendered by WalletPage within its form, triggering the correct onSubmit handler. (Gemini)
// 2025-04-28: Rev 41 - Replaced invalid/partial XMR addresses with a valid Testnet address in relevant tests. Updated assertion text in 'shows PGP warning' test. Added/refined act/waitFor usage for async operations. (Gemini)
// 2025-04-28: Rev 40 - Corrected expectation in 'invalid address format' test to check for error message on Step 1 instead of incorrectly expecting Step 2, aligning with improved validation in wallet.js Rev 18. (Gemini)
// ... previous history ...

import React from 'react';
import {
    render,
    screen,
    waitFor,
    within,
    act,
    fireEvent // Import fireEvent
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import WalletPage from './wallet'; // Targetting Rev 19+ of wallet.js

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

// Mock WithdrawalInputForm (reverted to Rev 41 version with button)
jest.mock('../components/WithdrawalInputForm', () => (props) => (
    <div data-testid="withdrawal-input-form-mock-content">
        <label>Currency <select name="currency" value={props.currency} onChange={props.onCurrencyChange} disabled={props.disabled || props.isLoading} aria-label="Currency">{['XMR', 'BTC'].map(curr => (<option key={curr} value={curr}>{curr}</option>))}</select></label>
        <label>Amount<input name="amount" type="number" value={props.amount} onChange={props.onAmountChange} disabled={props.disabled || props.isLoading} aria-label="Amount" /></label>
        <label>Address<input name="address" value={props.address} onChange={props.onAddressChange} disabled={props.disabled || props.isLoading} aria-label="Address" /></label>
        <button type="submit" disabled={props.disabled || props.isLoading} onClick={props.onSubmit}>
            {props.isLoading ? 'Preparing...' : 'Prepare Withdrawal'}
        </button>
        <input type="hidden" data-mock-prop-currency={props.currency} />
        <input type="hidden" data-mock-prop-amount={props.amount} />
        <input type="hidden" data-mock-prop-address={props.address} />
        <input type="hidden" data-mock-prop-disabled={props.disabled ? 'true' : 'false'} />
        <input type="hidden" data-mock-prop-loading={props.isLoading ? 'true' : 'false'} />
    </div>
));


// Mock PgpChallengeSigner
jest.mock('../components/PgpChallengeSigner', () => (props) => (
    <div data-testid="pgp-signer-form-mock-content">
        <p data-testid="challenge-text">Challenge: {props.challengeText}</p>
        <label>Signature<textarea data-testid="signature-input" value={props.signatureValue} onChange={props.onSignatureChange} disabled={props.disabled} aria-label="Signature" /></label>
    </div>
));
jest.mock('../components/LoadingSpinner', () => ({ size, message }) => <div data-testid={`spinner-${size || 'default'}`}>{message || 'Loading...'}</div>);

// --- Test Addresses ---
const VALID_XMR_TESTNET_ADDRESS = '9sZABNdyWspcpsgMUW2nN3LCEGJ3LpSmwQ4jV3e4XKf18J1z11KHF4fGfZ35Rmh4yQjY61U9QV9nHVt4y5F4qANg74zTEAT';
const VALID_BTC_TESTNET_ADDRESS = 'tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx';
const VALID_BTC_MAINNET_ADDRESS = '3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy';

// *** NEW: Mock the validation libraries used by the component's isValidAddress ***
jest.mock('bitcoin-address-validation', () => ({
    validate: jest.fn((address) => {
        // Simple mock: Return true only for our known valid test addresses
        // console.log(`[MOCK] bitcoin-address-validation: Validating address: ${address}`); // Keep mock log if helpful
        return [VALID_BTC_TESTNET_ADDRESS, VALID_BTC_MAINNET_ADDRESS].includes(address);
    }),
}));
jest.mock('monero-ts', () => ({
    MoneroUtils: {
        isValidAddress: jest.fn(async (address, networkType) => {
            // Simple mock: Return true only for our known valid test address
            // console.log(`[MOCK] monero-ts: Validating address: ${address}`); // Keep mock log if helpful
            return address === VALID_XMR_TESTNET_ADDRESS;
        }),
    },
    MoneroNetworkType: { // Include enum used by component
        MAINNET: 0,
        TESTNET: 1,
        STAGENET: 2,
    }
}));
jest.mock('ethers', () => ({
    isAddress: jest.fn((address) => {
        // Simple mock: Assume false for now as no ETH tests exist
        return false;
    }),
}));
// *** END NEW MOCKS ***


// --- Test Data ---
const mockBalancesData = {
    XMR: { total: "1.5000", available: "1.4500", locked: "0.0500" },
    BTC: { total: "0.1000", available: "0.1000", locked: "0.0000" },
};

// --- Helper Function ---
const getWithdrawalForm = (container = screen) => {
    const withdrawalSection = container.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
    if (!withdrawalSection) throw new Error("Could not find withdrawal section");
    const form = withdrawalSection.querySelector('form');
    if (!form) throw new Error("Could not find form within withdrawal section");
    return form;
}

// --- Test Suite ---
describe('WalletPage Component', () => {

    let mockApi;
    let mockNotifications;
    let consoleErrorSpy;
    let consoleWarnSpy;
    // Add refs for new mocks
    let mockValidateBitcoin;
    let mockMoneroIsValidAddress;
    let mockIsEthereumAddress;


    beforeEach(() => {
        mockApi = require('../utils/api');
        mockNotifications = require('../utils/notifications');
        // Get refs to newly mocked validation functions
        mockValidateBitcoin = require('bitcoin-address-validation').validate;
        mockMoneroIsValidAddress = require('monero-ts').MoneroUtils.isValidAddress;
        mockIsEthereumAddress = require('ethers').isAddress;

        // Clear all mocks
        jest.clearAllMocks();
        mockApi.getWalletBalances.mockClear();
        mockApi.prepareWithdrawal.mockClear();
        mockApi.executeWithdrawal.mockClear();
        // Clear validation mocks
        mockValidateBitcoin.mockClear();
        mockMoneroIsValidAddress.mockClear();
        mockIsEthereumAddress.mockClear();


        // Reset Auth Context
        setMockAuthContext({
            user: { id: 'user1', username: 'testuser' },
            isPgpAuthenticated: true,
            isLoading: false,
        });

        // Reset default API implementations
        mockApi.getWalletBalances.mockResolvedValue({ ...mockBalancesData });
        mockApi.prepareWithdrawal.mockResolvedValue({ pgp_message_to_sign: 'Default sign message', withdrawal_id: 'prepDefault123' });
        mockApi.executeWithdrawal.mockResolvedValue({ transaction_id: 'Default TXID' });

        // *** Reset default Validation mock implementations (important if tests override them) ***
        mockValidateBitcoin.mockImplementation((address) => [VALID_BTC_TESTNET_ADDRESS, VALID_BTC_MAINNET_ADDRESS].includes(address));
        mockMoneroIsValidAddress.mockImplementation(async (address) => address === VALID_XMR_TESTNET_ADDRESS);
        mockIsEthereumAddress.mockImplementation(() => false);


        // Suppress console messages
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

    // [Keep previously passing tests unchanged: renders loading, redirects, shows PGP warning, shows balance fetch error]
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

        const alert = await screen.findByTestId('balance-load-error-alert');
        expect(alert).toBeInTheDocument();
        expect(within(alert).getByText(/PGP authenticated session required\. Please re-login to authenticate PGP\./i)).toBeInTheDocument();
        expect(within(alert).getByRole('link', { name: /re-login to authenticate PGP/i })).toBeInTheDocument();

        expect(mockApi.getWalletBalances).not.toHaveBeenCalled();
        expect(screen.queryByTestId('balance-grid')).not.toBeInTheDocument();

        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(withdrawalSection).toBeInTheDocument();
        expect(within(withdrawalSection).queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
        expect(within(withdrawalSection).getByText(/PGP authenticated session required to withdraw funds\. Please/i)).toBeInTheDocument();
        expect(within(withdrawalSection).getByRole('link', { name: /re-login to authenticate PGP/i })).toBeInTheDocument();
    });

     test('shows error if balance fetch fails', async () => {
        const errorMsg = 'API Error 500 - Cannot reach server';
        mockApi.getWalletBalances.mockRejectedValueOnce(new Error(errorMsg));

        render(<WalletPage />);
        const alert = await screen.findByTestId('balance-load-error-alert', {}, { timeout: 14500 });

        expect(mockApi.getWalletBalances).toHaveBeenCalled();

        expect(alert).toBeInTheDocument();
        expect(within(alert).getByText(errorMsg)).toBeInTheDocument();
        expect(screen.queryByTestId('balance-grid')).not.toBeInTheDocument();
        expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);
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
        expect(within(screen.getByTestId('withdrawal-input-form-mock-content')).getByRole('button', { name: /Prepare Withdrawal/i })).toBeInTheDocument();
    });


    // --- Withdrawal Step 1 Tests ---
    test('shows Step 1 form initially when authenticated', async () => {
        render(<WalletPage />);
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        expect(screen.getByTestId('balance-grid')).toBeInTheDocument();
        expect(screen.queryByTestId('balance-load-error-alert')).not.toBeInTheDocument();
        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        expect(within(screen.getByTestId('withdrawal-input-form-mock-content')).getByRole('button', { name: /Prepare Withdrawal/i })).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
    });


    test('shows validation error for insufficient funds', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const currencySelect = within(mockFormContent).getByLabelText('Currency');
        const form = getWithdrawalForm();

        await user.selectOptions(currencySelect, 'XMR');
        await user.type(amountInput, '10.0'); // More than available XMR
        await user.type(addressInput, VALID_XMR_TESTNET_ADDRESS); // Use valid address

        // Use fireEvent.submit
        await act(async () => { fireEvent.submit(form); });

        // Assertions remain the same
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(/Insufficient available funds/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid amount (non-numeric)', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const form = getWithdrawalForm();

        await user.type(addressInput, 'someAddress'); // Irrelevant for this validation
        await user.type(amountInput, 'abc');

        // Use fireEvent.submit
        await act(async () => { fireEvent.submit(form); });

        // Assertions remain the same
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(/Invalid amount specified \(must be a number\)/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid amount (zero)', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const form = getWithdrawalForm();

        await user.type(addressInput, VALID_XMR_TESTNET_ADDRESS); // Use valid address
        await user.type(amountInput, '0');

        // Use fireEvent.submit
        await act(async () => { fireEvent.submit(form); });

        // Assertions remain the same
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(/Invalid amount specified \(must be positive\)/i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for missing address', async () => {
        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const form = getWithdrawalForm();

        await user.type(amountInput, '0.1');

        // Use fireEvent.submit
        await act(async () => { fireEvent.submit(form); });

        // Assertions remain the same
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(/Destination address is required\./i);
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
    });


    test('shows validation error for invalid address format', async () => {
        // Mock the validation libs to return false for this specific address
        // (Though default mocks might already handle this if address is not in the 'valid' list)
        const invalidAddress = 'this is definitely not a valid address';
        mockMoneroIsValidAddress.mockImplementation(async (addr) => addr === VALID_XMR_TESTNET_ADDRESS); // Ensure only valid one passes
        mockValidateBitcoin.mockImplementation((addr) => [VALID_BTC_TESTNET_ADDRESS, VALID_BTC_MAINNET_ADDRESS].includes(addr)); // Ensure only valid ones pass

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const currencySelect = within(mockFormContent).getByLabelText('Currency');
        const form = getWithdrawalForm();

        await user.selectOptions(currencySelect, 'XMR');
        await user.type(amountInput, '0.1');
        await user.type(addressInput, invalidAddress);

        // Use fireEvent.submit
        await act(async () => { fireEvent.submit(form); });

        // Assertions remain the same
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        const alert = await within(withdrawalSection).findByRole('alert');
        expect(alert).toHaveTextContent(/Invalid address format for XMR\. Please double-check\./i);

        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(mockApi.prepareWithdrawal).not.toHaveBeenCalled();
        expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
        // Check the validation mock was called correctly
        expect(mockMoneroIsValidAddress).toHaveBeenCalledWith(invalidAddress, expect.anything());
    });


    test('calls prepareWithdrawal and proceeds to Step 2 on successful prepare', async () => {
        const prepResponse = { pgp_message_to_sign: 'SIGN THIS MESSAGE PLEASE', withdrawal_id: 'prep123' };
        const prepareMock = mockApi.prepareWithdrawal.mockResolvedValueOnce(prepResponse);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const currencySelect = within(mockFormContent).getByLabelText('Currency');
        const form = getWithdrawalForm();

        const amount = '0.5';
        const address = VALID_XMR_TESTNET_ADDRESS; // Test with valid XMR address
        const currency = 'XMR';

        await user.selectOptions(currencySelect, currency);
        await user.type(amountInput, amount);
        await user.type(addressInput, address);

        // Use fireEvent.submit
        await act(async () => {
            fireEvent.submit(form);
            // Wait for prepareWithdrawal mock (should be called now)
            await waitFor(() => expect(prepareMock).toHaveBeenCalled());
        });

        // Check API call (should be called now)
        expect(prepareMock).toHaveBeenCalledWith({ currency, amount: amount.toString(), address });
        expect(prepareMock).toHaveBeenCalledTimes(1);
         // Check address validation mock was called and returned true
         expect(mockMoneroIsValidAddress).toHaveBeenCalledWith(address, expect.anything());
         await expect(mockMoneroIsValidAddress(address)).resolves.toBe(true); // Verify mock returns true

        // Now wait for Step 2 elements
        const step2Form = await screen.findByTestId('pgp-signer-form-mock-content', {}, { timeout: 5000 });
        expect(step2Form).toBeInTheDocument();
        expect(within(step2Form).getByTestId('challenge-text')).toHaveTextContent(`Challenge: ${prepResponse.pgp_message_to_sign}`);
        expect(screen.queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /^Back$/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Execute Withdrawal/i })).toBeInTheDocument();

        // Check toast
        await waitFor(() => expect(mockNotifications.showInfoToast).toHaveBeenCalledWith("Withdrawal prepared. Please sign the confirmation message."));
        expect(mockNotifications.showInfoToast).toHaveBeenCalledTimes(1);
    });


    test('shows error on failed prepareWithdrawal API call', async () => {
        const errorMsg = 'Prepare API Call Failed Miserably';
        const prepareMock = mockApi.prepareWithdrawal.mockRejectedValueOnce(new Error(errorMsg));

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountInput = within(mockFormContent).getByLabelText('Amount');
        const addressInput = within(mockFormContent).getByLabelText('Address');
        const currencySelect = within(mockFormContent).getByLabelText('Currency');
        const form = getWithdrawalForm();
        const validBtcAddress = VALID_BTC_MAINNET_ADDRESS; // Test with BTC

        await user.selectOptions(currencySelect, 'BTC');
        await user.type(amountInput, '0.01');
        await user.type(addressInput, validBtcAddress);

        // Use fireEvent.submit
        await act(async () => {
             fireEvent.submit(form);
             // Wait for prepareWithdrawal mock (should be called now)
             await waitFor(() => expect(prepareMock).toHaveBeenCalled());
        });

         // Check API call (should be called now)
         expect(prepareMock).toHaveBeenCalledWith({ currency: 'BTC', amount: '0.01', address: validBtcAddress });
         expect(prepareMock).toHaveBeenCalledTimes(1);
         // Check address validation mock was called and returned true
         expect(mockValidateBitcoin).toHaveBeenCalledWith(validBtcAddress);
         expect(mockValidateBitcoin(validBtcAddress)).toBe(true); // Verify mock returns true


        // Wait for error handling effects
        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        }, { timeout: 4000 });

        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);

        // Check UI remains on Step 1
        expect(screen.getByTestId('withdrawal-input-form-mock-content')).toBeInTheDocument();
        const submitButton = within(screen.getByTestId('withdrawal-input-form-mock-content')).getByRole('button', { name: /Prepare Withdrawal/i });
        await waitFor(() => expect(submitButton).not.toBeDisabled());
        expect(submitButton).toHaveTextContent('Prepare Withdrawal');
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();

        // Check error message display
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(errorMsg);
    });


    // --- Withdrawal Step 2 Tests ---
    test('goes back to Step 1 from Step 2 using Back button', async () => {
        const prepResponse = { pgp_message_to_sign: 'SIGN THIS TO GO BACK', withdrawal_id: 'prepGoBack' };
        const prepareMock = mockApi.prepareWithdrawal.mockResolvedValueOnce(prepResponse);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        // --- Perform Step 1 ---
        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const address = VALID_XMR_TESTNET_ADDRESS; // Use valid XMR
        await user.selectOptions(within(mockFormContent).getByLabelText('Currency'), 'XMR');
        await user.type(within(mockFormContent).getByLabelText('Amount'), '0.1');
        await user.type(within(mockFormContent).getByLabelText('Address'), address);
        const step1Form = getWithdrawalForm();
        await act(async () => {
             fireEvent.submit(step1Form);
             await waitFor(() => expect(prepareMock).toHaveBeenCalled()); // Should be called now
        });
         // Check address validation mock was called and returned true
         expect(mockMoneroIsValidAddress).toHaveBeenCalledWith(address, expect.anything());
         await expect(mockMoneroIsValidAddress(address)).resolves.toBe(true); // Verify mock returns true


        // Wait for Step 2 elements
        await screen.findByTestId('pgp-signer-form-mock-content', {}, {timeout: 3000});
        const backButton = screen.getByRole('button', { name: /^Back$/i });
        expect(backButton).toBeInTheDocument();

        // --- Click Back in Step 2 ---
        await act(async () => { await user.click(backButton); });

        // Wait for Step 1 elements to reappear
        const step1FormMockReappeared = await screen.findByTestId('withdrawal-input-form-mock-content', {}, {timeout: 3000});
        expect(step1FormMockReappeared).toBeInTheDocument();
        expect(within(step1FormMockReappeared).getByRole('button', { name: /Prepare Withdrawal/i })).toBeInTheDocument();

        // Step 2 elements should disappear
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /^Back$/i })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Execute Withdrawal/i })).not.toBeInTheDocument();

        // Assert inputs are cleared
        await waitFor(() => {
            expect(within(step1FormMockReappeared).getByLabelText('Amount')).toHaveValue(null);
            expect(within(step1FormMockReappeared).getByLabelText('Address')).toHaveValue('');
        });
    });

    test('calls executeWithdrawal and resets on successful Step 2 submit', async () => {
        const withdrawalId = 'prepSuccess123';
        const initialPrepareMock = mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR SUCCESS', withdrawal_id: withdrawalId });
        const execResponse = { transaction_id: 'tx12345success' };
        const executeMock = mockApi.executeWithdrawal.mockResolvedValueOnce(execResponse);
        const updatedBalances = { ...mockBalancesData, XMR: { ...mockBalancesData.XMR, available: "1.3500" } };
        const balanceRefreshMock = mockApi.getWalletBalances.mockResolvedValueOnce(mockBalancesData).mockResolvedValueOnce(updatedBalances);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });
        expect(balanceRefreshMock).toHaveBeenCalledTimes(1);

        // --- Perform Step 1 ---
        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const amountToWithdraw = '0.1';
        const address = VALID_XMR_TESTNET_ADDRESS; // Use valid XMR
        await user.selectOptions(within(mockFormContent).getByLabelText('Currency'), 'XMR');
        await user.type(within(mockFormContent).getByLabelText('Amount'), amountToWithdraw);
        await user.type(within(mockFormContent).getByLabelText('Address'), address);
        const step1Form = getWithdrawalForm();
        await act(async () => {
             fireEvent.submit(step1Form);
             await waitFor(() => expect(initialPrepareMock).toHaveBeenCalled()); // Should be called
         });
          // Check address validation mock was called and returned true
         expect(mockMoneroIsValidAddress).toHaveBeenCalledWith(address, expect.anything());
         await expect(mockMoneroIsValidAddress(address)).resolves.toBe(true); // Verify mock returns true


        // Wait for Step 2 elements
        const step2FormMock = await screen.findByTestId('pgp-signer-form-mock-content', {}, {timeout: 3000});
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i });

        // --- Perform Step 2 ---
        const signatureInput = within(step2FormMock).getByLabelText('Signature');
        const signature = '-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----';
        await user.type(signatureInput, signature);

        expect(executeMock).not.toHaveBeenCalled();
        await act(async () => {
             await user.click(executeButton);
             await waitFor(() => expect(executeMock).toHaveBeenCalled());
             await waitFor(() => expect(balanceRefreshMock).toHaveBeenCalledTimes(2));
         });

        // Wait for success toast
        await waitFor(() => {
            expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith(expect.stringContaining(`Withdrawal successful! Transaction ID: ${execResponse.transaction_id}`));
        }, { timeout: 4000 });

        // Wait for Step 1 elements to reappear
        const step1FormMockReappeared = await screen.findByTestId('withdrawal-input-form-mock-content', {}, {timeout: 3000});
        expect(step1FormMockReappeared).toBeInTheDocument();
        expect(within(step1FormMockReappeared).getByRole('button', { name: /Prepare Withdrawal/i })).toBeInTheDocument();

        // Wait for updated balances
        await waitFor(() => {
           expect(screen.getByTitle(`Available: ${updatedBalances.XMR.available}`)).toHaveTextContent(`ɱ ${Number(updatedBalances.XMR.available).toFixed(4)}`);
        }, { timeout: 3000 });

        // Check APIs & state
        expect(executeMock).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: signature });
        expect(executeMock).toHaveBeenCalledTimes(1);
        expect(mockNotifications.showSuccessToast).toHaveBeenCalledTimes(1);
        expect(balanceRefreshMock).toHaveBeenCalledTimes(2);
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Execute Withdrawal/i })).not.toBeInTheDocument();
        await waitFor(() => {
            expect(within(step1FormMockReappeared).getByLabelText('Amount')).toHaveValue(null);
            expect(within(step1FormMockReappeared).getByLabelText('Address')).toHaveValue('');
        });
    });


    test('shows error and stays on Step 2 on failed executeWithdrawal (e.g., invalid signature)', async () => {
        const withdrawalId = 'prepFailSign123';
        const prepareMock = mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR FAILURE', withdrawal_id: withdrawalId });
        const errorMsg = 'Invalid PGP signature provided.';
        const executeMock = mockApi.executeWithdrawal.mockRejectedValueOnce(new Error(errorMsg));

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });

        // --- Perform Step 1 ---
        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const address = VALID_XMR_TESTNET_ADDRESS; // Use valid XMR
        await user.selectOptions(within(mockFormContent).getByLabelText('Currency'), 'XMR');
        await user.type(within(mockFormContent).getByLabelText('Amount'), '0.1');
        await user.type(within(mockFormContent).getByLabelText('Address'), address);
        const step1Form = getWithdrawalForm();
        await act(async () => {
             fireEvent.submit(step1Form);
             await waitFor(() => expect(prepareMock).toHaveBeenCalled()); // Should be called
        });
         // Check address validation mock was called and returned true
         expect(mockMoneroIsValidAddress).toHaveBeenCalledWith(address, expect.anything());
         await expect(mockMoneroIsValidAddress(address)).resolves.toBe(true); // Verify mock returns true

        // Wait for Step 2 elements
        const step2FormMock = await screen.findByTestId('pgp-signer-form-mock-content', {}, {timeout: 3000});
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i });

        // --- Perform Step 2 ---
        const signatureInput = within(step2FormMock).getByLabelText('Signature');
        const badSignature = 'invalid-signature-for-test';
        await user.type(signatureInput, badSignature);

        await act(async () => {
             await user.click(executeButton);
             await waitFor(() => expect(executeMock).toHaveBeenCalled()); // Should be called
        });

        // Wait for error toast AND check component error message area
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(errorMsg);
        }, {timeout: 3000});
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(errorMsg); // Error message inside section

        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);
        expect(executeMock).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: badSignature });
        expect(executeMock).toHaveBeenCalledTimes(1);

        // Assert still on Step 2
        expect(screen.getByTestId('pgp-signer-form-mock-content')).toBeInTheDocument();
        expect(screen.getByLabelText('Signature')).toHaveValue(badSignature);
        expect(screen.getByRole('button', { name: /^Back$/i })).toBeInTheDocument();
        await waitFor(() => expect(executeButton).not.toBeDisabled());
        expect(screen.queryByTestId('withdrawal-input-form-mock-content')).not.toBeInTheDocument();
    });


    test('resets to Step 1 if executeWithdrawal fails with expired error', async () => {
        const withdrawalId = 'prepFailExp123';
        const prepareMock = mockApi.prepareWithdrawal.mockResolvedValueOnce({ pgp_message_to_sign: 'SIGN THIS FOR EXPIRY', withdrawal_id: withdrawalId });
        const expiryApiErrorMessage = require('../utils/constants').ERROR_MESSAGES.WITHDRAWAL_EXPIRED;
        const finalDisplayErrorMessage = 'Withdrawal expired or invalid. Please prepare a new withdrawal.';
        const executeMock = mockApi.executeWithdrawal.mockRejectedValueOnce(new Error(expiryApiErrorMessage));
        const balanceRefreshMock = mockApi.getWalletBalances.mockResolvedValue(mockBalancesData);

        render(<WalletPage />);
        const user = userEvent.setup();
        await screen.findByTestId('balance-grid', {}, { timeout: 14500 });
        expect(balanceRefreshMock).toHaveBeenCalledTimes(1);

        // --- Perform Step 1 ---
        const mockFormContent = screen.getByTestId('withdrawal-input-form-mock-content');
        const address = VALID_BTC_MAINNET_ADDRESS; // Use valid BTC
        await user.selectOptions(within(mockFormContent).getByLabelText('Currency'), 'BTC');
        await user.type(within(mockFormContent).getByLabelText('Amount'), '0.001');
        await user.type(within(mockFormContent).getByLabelText('Address'), address);
        const step1Form = getWithdrawalForm();
        await act(async () => {
            fireEvent.submit(step1Form);
            await waitFor(() => expect(prepareMock).toHaveBeenCalled()); // Should be called
        });
         // Check address validation mock was called and returned true
         expect(mockValidateBitcoin).toHaveBeenCalledWith(address);
         expect(mockValidateBitcoin(address)).toBe(true); // Verify mock returns true

        // Wait for Step 2 elements
        const step2FormMock = await screen.findByTestId('pgp-signer-form-mock-content', {}, {timeout: 7000});
        const executeButton = screen.getByRole('button', { name: /Execute Withdrawal/i });

        // --- Perform Step 2 ---
        const signatureInput = within(step2FormMock).getByLabelText('Signature');
        const signature = 'some-signature-that-will-trigger-expiry-error';
        await user.type(signatureInput, signature);

        await act(async () => {
            await user.click(executeButton);
            await waitFor(() => expect(executeMock).toHaveBeenCalled()); // Should be called
            await waitFor(() => expect(balanceRefreshMock).toHaveBeenCalledTimes(2)); // Should refresh
        });

        // Wait for error toast AND Step 1 elements reappearing
        const withdrawalSection = screen.getByRole('heading', { name: /Withdraw Funds/i }).closest('section');
        await waitFor(() => {
            expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(finalDisplayErrorMessage);
        }, {timeout: 3000});
        const step1FormMockReappeared = await screen.findByTestId('withdrawal-input-form-mock-content', {}, {timeout: 3000});
        expect(within(step1FormMockReappeared).getByRole('button', { name: /Prepare Withdrawal/i })).toBeInTheDocument();

        // Check API call
        expect(executeMock).toHaveBeenCalledWith({ withdrawal_id: withdrawalId, pgp_confirmation_signature: signature });
        expect(executeMock).toHaveBeenCalledTimes(1);
        expect(mockNotifications.showErrorToast).toHaveBeenCalledTimes(1);
        expect(await within(withdrawalSection).findByRole('alert')).toHaveTextContent(finalDisplayErrorMessage); // Error in Step 1 area

        // Assert final state (reset to Step 1)
        expect(step1FormMockReappeared).toBeInTheDocument();
        expect(screen.queryByTestId('pgp-signer-form-mock-content')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /^Back$/i })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Execute Withdrawal/i })).not.toBeInTheDocument();
        await waitFor(() => {
            expect(within(step1FormMockReappeared).getByLabelText('Amount')).toHaveValue(null);
            expect(within(step1FormMockReappeared).getByLabelText('Address')).toHaveValue('');
        }, {timeout: 2000});
        expect(balanceRefreshMock).toHaveBeenCalledTimes(2);
    });

}); // End describe block