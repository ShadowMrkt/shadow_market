// frontend/pages/profile.test.js
// --- REVISION HISTORY ---
// 2025-04-23 (Gemini): Rev 35 - Added checks for spinner absence within buttons in final `waitFor` blocks after async operations, attempting to further stabilize tests and potentially resolve lingering act warnings.
// 2025-04-23 (Gemini): Rev 34 - Added jest.spyOn for console.error/log in specific tests to suppress expected error/log messages during test runs (e.g., Address/PGP/Password update failures, Vendor Apply/Status failures).
// 2025-04-23 (Gemini): Rev 33 - Removed incorrect assertion expecting "Refresh Status" button in tests for terminal vendor statuses ('approved', 'rejected'), fixing test failures introduced in Rev 32. Component does not show refresh for final states.
// ... (previous history omitted for brevity) ...

import React from 'react';
import { render, screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRouter } from 'next/router';
import { useAuth } from '../context/AuthContext';
import ProfilePage from './profile'; // Assuming profile.js is Rev 19/20 or compatible
import { updateCurrentUser, applyForVendor, getVendorApplicationStatus, ApiError } from '../utils/api';
import { formatDate } from '../utils/formatters';
import { showErrorToast, showSuccessToast, showInfoToast } from '../utils/notifications';
import { MIN_PASSWORD_LENGTH } from '../utils/constants';

// --- Mocks ---
jest.mock('next/router', () => ({
    useRouter: jest.fn(),
}));

jest.mock('../utils/api', () => ({
    updateCurrentUser: jest.fn(),
    applyForVendor: jest.fn(),
    getVendorApplicationStatus: jest.fn(),
    ApiError: class extends Error {
        constructor(message, status = 500, data = null) {
            super(message);
            this.status = status;
            this.data = data;
            this.name = 'ApiError';
        }
    }
}));


jest.mock('../utils/notifications', () => ({
    showErrorToast: jest.fn(),
    showSuccessToast: jest.fn(),
    showInfoToast: jest.fn(),
}));

jest.mock('../context/AuthContext', () => {
    const originalModule = jest.requireActual('../context/AuthContext');
    return {
        __esModule: true,
        ...originalModule,
        useAuth: jest.fn(),
    };
});

// Mock PgpChallengeSigner carefully
jest.mock('../components/PgpChallengeSigner', () => {
    const MockPgpChallengeSigner = ({ isOpen, onSuccess, onFail, onCancel, errorMessage, challenge }) => {
        if (!isOpen) return null;
        return (
            <div data-testid="mock-pgp-signer">
                {errorMessage && <div role="alert">{errorMessage}</div>}
                <p>Challenge: {challenge?.challenge_text}</p>
                {/* IMPORTANT: Wrap callbacks in act here IF THEY CAUSE STATE UPDATES IN THE PARENT *DIRECTLY*,
                    otherwise the act in the test clicking the button is sufficient.
                    Since onSuccess/onFail/onCancel *trigger* state updates in ProfilePage, wrapping them
                    here ensures they run within the test's act context triggered by userEvent.click */}
                <button onClick={() => act(() => { onSuccess('mockSignedChallenge'); })}>Confirm Signature</button>
                <button onClick={() => act(() => { onFail('Mock PGP Signer Failure'); })}>Fail Signature</button>
                <button onClick={() => act(() => { onCancel(); })}>Cancel Signature</button>
            </div>
        );
    };
    MockPgpChallengeSigner.displayName = 'MockPgpChallengeSigner';
    return MockPgpChallengeSigner;
});
// Mock LoadingSpinner to allow querying its absence
jest.mock('../components/LoadingSpinner', () => ({ size }) => <div data-testid={`spinner-${size || 'default'}`}>Loading...</div>);
// Mock Button to easily check for spinner presence/absence via data-testid
jest.mock('../components/ui/Button', () => ({ children, isLoading, ...props }) => (
    <button {...props}>
        {isLoading ? <div data-testid="button-spinner">Loading...</div> : children}
    </button>
));
// Mock FormError to ensure role="alert" is present
jest.mock('../components/FormError', () => ({ message }) => message ? <div role="alert" data-testid="form-error">{message}</div> : null);


// Default mock user data
const defaultMockUser = {
    username: 'testuser',
    date_joined: '2025-01-01T00:00:00Z',
    last_login: '2025-04-09T12:00:00Z',
    is_vendor: false,
    vendor_level: null,
    btc_withdrawal_address: 'initialBTCAddress',
    eth_withdrawal_address: '0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B', // Valid format
    pgp_public_key: '-----BEGIN PGP PUBLIC KEY BLOCK-----\nVersion: MockKey\nInitial PGP Key Data\n-----END PGP PUBLIC KEY BLOCK-----',
    login_phrase: 'correct horse battery staple',
};

const mockPgpChallenge = {
    challenge_text: 'Please sign this challenge text.',
    nonce: 'mockNonce123',
};

const validPgpKeyNew = '-----BEGIN PGP PUBLIC KEY BLOCK-----\nVersion: MockKey New\nNew Key Data\n-----END PGP PUBLIC KEY BLOCK-----';

const dateTimeOptions = {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: 'numeric', timeZoneName: 'short', timeZone: 'UTC'
};
const dateOnlyOptions = {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
};

let mockRouterReplace;
let defaultMockAuthContextValue;


describe('ProfilePage Component', () => {
    beforeEach(() => {
        jest.clearAllMocks();

        // Reset mocks to default successful states or defined initial states
        updateCurrentUser.mockResolvedValue({ ...defaultMockUser });
        applyForVendor.mockResolvedValue(mockPgpChallenge); // Default: step 1 succeeds
        getVendorApplicationStatus.mockResolvedValue(null); // Default: no existing application

        mockRouterReplace = jest.fn();
        useRouter.mockReturnValue({
            replace: mockRouterReplace,
            query: {},
            pathname: '/profile',
            isReady: true,
            push: jest.fn(),
        });

        defaultMockAuthContextValue = {
            user: { ...defaultMockUser },
            loading: false,
            isPgpAuthenticated: true, // Default: PGP auth done
            setUser: jest.fn(),
            login: jest.fn(),
            logout: jest.fn(),
            checkAuth: jest.fn(),
            startPgpAuthProcess: jest.fn(),
            completePgpAuthProcess: jest.fn(),
        };
        useAuth.mockReturnValue(defaultMockAuthContextValue);
    });

    // Helper to modify mock context for specific tests
    const setMockAuthContext = (overrides) => {
        const currentMockValue = useAuth(); // Get potentially already modified value if chaining calls
        useAuth.mockReturnValue({ ...currentMockValue, ...overrides });
    };

    // Helper for awaiting initial effects/renders if needed - useful for complex loads
    const waitForInitialRender = async () => {
        // Prefer waiting for a specific element indicating load finished
        // but a small timeout wrapped in act can sometimes help stabilize initial effects
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    }

    test('renders user information (non-vendor)', async () => {
        render(<ProfilePage />);
        // Wait specifically for the side effect we know happens on load for non-vendors
        await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));

        expect(screen.getByText('Username:')).toBeInTheDocument();
        expect(screen.getByText(defaultMockUser.username)).toBeInTheDocument();
        expect(screen.getByText('Joined:')).toBeInTheDocument();
        expect(screen.getByText(formatDate(defaultMockUser.date_joined, dateOnlyOptions))).toBeInTheDocument();
        expect(screen.getByText('Last Login:')).toBeInTheDocument();
        expect(screen.getByText(formatDate(defaultMockUser.last_login, dateTimeOptions))).toBeInTheDocument();
        const accountInfoSection = screen.getByRole('heading', { name: /Account Information/i }).closest('section');
        expect(within(accountInfoSection).getByText('Vendor Status:')).toBeInTheDocument();
        expect(within(accountInfoSection).getByText(/^No$/)).toBeInTheDocument(); // Check non-vendor status
        expect(screen.getByText('Login Phrase (Anti-Phishing):')).toBeInTheDocument();
        expect(screen.getByText(defaultMockUser.login_phrase)).toBeInTheDocument();
        expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toHaveValue(defaultMockUser.btc_withdrawal_address);
        expect(screen.getByLabelText(/Ethereum \(ETH\) Address/i)).toHaveValue(defaultMockUser.eth_withdrawal_address);
        expect(screen.getByLabelText(/Current PGP Key/i)).toHaveValue(defaultMockUser.pgp_public_key);
    });

    test('renders user information (vendor)', async () => {
        setMockAuthContext({ user: { ...defaultMockUser, is_vendor: true, vendor_level: 2 } });
        render(<ProfilePage />);
        // Wait for initial render to settle; vendor status check won't be called
        await waitForInitialRender();

        // Vendor status check should NOT have been called if is_vendor is true
        expect(getVendorApplicationStatus).not.toHaveBeenCalled();

        const accountInfoSection = screen.getByRole('heading', { name: /Account Information/i }).closest('section');
        expect(within(accountInfoSection).getByText('Vendor Status:')).toBeInTheDocument();
        expect(within(accountInfoSection).getByText(/^Yes$/)).toBeInTheDocument(); // Check vendor status
        // Vendor application section should not be rendered
        expect(screen.queryByRole('heading', { name: /Vendor Status/i, level: 2, exact: false })).not.toBeInTheDocument();
    });

    test('redirects to login if user is not logged in', async () => {
        // <<< REVISION 34: Suppress expected console.log from profile.js >>>
        const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
        setMockAuthContext({ user: null, loading: false });
        render(<ProfilePage />);
        // Wait for the redirect effect
        await waitFor(() => {
            expect(mockRouterReplace).toHaveBeenCalledWith('/login?next=/profile');
        });
        consoleLogSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
    });

    test('disables forms if PGP is not authenticated', async () => {
        setMockAuthContext({ isPgpAuthenticated: false });
        render(<ProfilePage />);
        // Wait for the PGP auth required message to appear
        await screen.findByRole('heading', { name: /PGP Authentication Required/i });

        expect(screen.getByRole('heading', { name: /PGP Authentication Required/i })).toBeInTheDocument();
        // Check forms are disabled
        expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toBeDisabled();
        expect(screen.getByRole('button', { name: /Save Addresses/i })).toBeDisabled();
        expect(screen.getByLabelText(/Current PGP Key/i)).toBeDisabled();
        expect(screen.getByRole('button', { name: /Update PGP Key/i })).toBeDisabled();
        expect(screen.getByLabelText(/Current Password/i)).toBeDisabled();
        expect(screen.getByRole('button', { name: /Change Password/i })).toBeDisabled();

        // Check vendor section - apply button should be present but disabled
        const vendorSection = screen.getByRole('heading', { name: /Vendor Status/i, level: 2 }).closest('section');
        // Wait for the button specifically as its rendering depends on async state potentially
        const applyButton = await within(vendorSection).findByRole('button', { name: /Apply for Vendor Status/i });
        expect(applyButton).toBeInTheDocument();
        expect(applyButton).toBeDisabled();

        expect(screen.getByRole('link', { name: /re-authenticate with PGP/i })).toBeInTheDocument();
        // Vendor status check should NOT have been called if PGP is not authenticated
        expect(getVendorApplicationStatus).not.toHaveBeenCalled();
    });

    // --- Address Update Tests ---
    describe('Address Update', () => {
        test('updates address fields and handles successful save', async () => {
             // <<< REVISION 34: Suppress expected console.log >>>
            const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
            const updatedUserResponse = { ...defaultMockUser, btc_withdrawal_address: 'newBTCAddress' };
            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Request challenge
                .mockResolvedValueOnce(updatedUserResponse); // Step 2: Submit update

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1)); // Initial load check
            const user = userEvent.setup();
            const btcInput = screen.getByLabelText(/Bitcoin \(BTC\) Address/i);
            const saveButton = screen.getByRole('button', { name: /Save Addresses/i });

            // Simulate user input and first API call trigger (request challenge)
            await act(async () => {
                await user.clear(btcInput);
                await user.type(btcInput, 'newBTCAddress');
                await user.click(saveButton);
            });

            // Wait for the modal and confirm button to appear
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'addresses' });
            // Save button should be disabled while modal is open
            expect(saveButton).toBeDisabled();
            // <<< REVISION 35: Check for spinner in button >>>
            expect(within(saveButton).getByTestId('button-spinner')).toBeInTheDocument();

            // Simulate PGP confirmation and second API call trigger (submit update)
            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for ALL final effects after successful modal confirmation
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2);
                expect(updateCurrentUser).toHaveBeenNthCalledWith(2, {
                    btc_withdrawal_address: 'newBTCAddress',
                    eth_withdrawal_address: defaultMockUser.eth_withdrawal_address, // Ensure unchanged fields are sent
                    signed_challenge: 'mockSignedChallenge'
                });
                // Check context update
                expect(useAuth().setUser).toHaveBeenCalledWith(updatedUserResponse);
                // Check notifications
                expect(showSuccessToast).toHaveBeenCalledWith("Withdrawal addresses updated successfully!");
                // Check modal is closed
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check input field reflects the change (driven by context update)
                expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toHaveValue('newBTCAddress');
                // Check button is re-enabled AND spinner is gone
                expect(saveButton).toBeEnabled();
                // <<< REVISION 35: Check for spinner absence in button >>>
                expect(within(saveButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });
            consoleLogSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });

        test('shows error on failed address save', async () => {
            // <<< REVISION 34: Suppress expected console.log/error >>>
            const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            const rawErrorMessage = 'Invalid format provided.';
            const errorData = { btc_withdrawal_address: [rawErrorMessage] };
            const apiError = new ApiError('Invalid BTC address format', 400, errorData);
            const expectedDisplayedError = JSON.stringify(errorData); // Component logic uses stringify

            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Request challenge (succeeds)
                .mockRejectedValueOnce(apiError); // Step 2: Submit update (fails)

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const btcInput = screen.getByLabelText(/Bitcoin \(BTC\) Address/i);
            const saveButton = screen.getByRole('button', { name: /Save Addresses/i });
            const addressSection = screen.getByRole('heading', { name: /Withdrawal Addresses/i }).closest('section');

            // Simulate user input and first API call trigger
            await act(async () => {
                await user.clear(btcInput);
                await user.type(btcInput, 'invalid-btc');
                await user.click(saveButton);
            });

            // Wait for modal
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'addresses' });
            // Save button should be disabled while modal is open
            expect(saveButton).toBeDisabled();
            // <<< REVISION 35: Check for spinner in button >>>
            expect(within(saveButton).getByTestId('button-spinner')).toBeInTheDocument();

            // Simulate PGP confirmation and second API call trigger (which will fail)
            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for final outcomes AFTER modal confirmation leads to failure
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2); // Both calls attempted
                // Check modal is CLOSED (new behavior in Rev 17+)
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check error toast
                expect(showErrorToast).toHaveBeenCalledWith(expectedDisplayedError);
                // Check error displayed in the address section (not modal)
                expect(within(addressSection).getByRole('alert')).toHaveTextContent(expectedDisplayedError);
                // Check button is re-enabled AND spinner is gone
                expect(saveButton).toBeEnabled();
                // <<< REVISION 35: Check for spinner absence in button >>>
                expect(within(saveButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });

            // Check state was not updated
            expect(useAuth().setUser).not.toHaveBeenCalled();
            // Input should retain the invalid value user typed
            expect(screen.getByLabelText(/Bitcoin \(BTC\) Address/i)).toHaveValue('invalid-btc');
            consoleLogSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
            consoleErrorSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });
    });

    // --- PGP Key Update Tests ---
    describe('PGP Key Update', () => {
        test('shows PGP format error on client-side validation fail', async () => {
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const pgpInput = screen.getByLabelText(/Current PGP Key/i);
            const updateButton = screen.getByRole('button', { name: /Update PGP Key/i });
            const pgpSection = screen.getByRole('heading', { name: /PGP Public Key/i }).closest('section');

            // Simulate invalid input and click
            await act(async () => {
                await user.clear(pgpInput);
                await user.type(pgpInput, 'this is not a pgp key');
                await user.click(updateButton);
            });

            // Wait for client-side validation error
            await waitFor(() => {
                expect(within(pgpSection).getByRole('alert')).toHaveTextContent(/Invalid PGP key format/i);
                expect(showErrorToast).toHaveBeenCalledWith("Invalid PGP key format. Please ensure you paste the entire block including BEGIN/END markers.");
            });

            // Ensure API was not called due to client-side validation failure
            expect(updateCurrentUser).not.toHaveBeenCalled();
        });

        test('opens confirmation modal on valid PGP update initiation', async () => {
            updateCurrentUser.mockResolvedValueOnce(mockPgpChallenge); // API call for challenge succeeds
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const pgpInput = screen.getByLabelText(/Current PGP Key/i);
            const updateButton = screen.getByRole('button', { name: /Update PGP Key/i });

            // Simulate valid input and click
            await act(async () => {
                await user.clear(pgpInput);
                await user.type(pgpInput, validPgpKeyNew); // Use the valid new key
                await user.click(updateButton);
            });

            // Wait for modal to appear after successful challenge request
            await waitFor(() => {
                expect(screen.getByTestId('mock-pgp-signer')).toBeInTheDocument();
                // Check no error message initially in the modal
                expect(within(screen.getByTestId('mock-pgp-signer')).queryByRole('alert')).not.toBeInTheDocument();
                // Check API call for challenge
                expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'pgp_key' });
                // Check button is disabled AND spinner is present
                expect(updateButton).toBeDisabled();
                // <<< REVISION 35: Check for spinner in button >>>
                expect(within(updateButton).getByTestId('button-spinner')).toBeInTheDocument();
            });
        });

        test('closes PGP modal on cancel', async () => {
            updateCurrentUser.mockResolvedValueOnce(mockPgpChallenge); // Challenge request succeeds
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const pgpInput = screen.getByLabelText(/Current PGP Key/i);
            const updateButton = screen.getByRole('button', { name: /Update PGP Key/i });

            // Initiate the update
            await act(async () => {
                await user.clear(pgpInput);
                await user.type(pgpInput, validPgpKeyNew);
                await user.click(updateButton);
            });

            // Wait for modal and get cancel button
            const cancelButton = await screen.findByRole('button', { name: /Cancel Signature/i });
            // Check button is disabled
            expect(updateButton).toBeDisabled();

            // Click cancel
            await act(async () => {
                await user.click(cancelButton);
            });

            // Wait for modal to close and check toast
            await waitFor(() => {
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                expect(showInfoToast).toHaveBeenCalledWith("PGP authentication cancelled.");
                // Check button is re-enabled AND spinner is gone
                expect(updateButton).toBeEnabled();
                // <<< REVISION 35: Check for spinner absence in button >>>
                expect(within(updateButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });
            // Only the challenge request call should have happened
            expect(updateCurrentUser).toHaveBeenCalledTimes(1);
        });

        test('handles successful PGP key update via modal confirmation', async () => {
            const updatedUserResponse = { ...defaultMockUser, pgp_public_key: validPgpKeyNew };
            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Request challenge
                .mockResolvedValueOnce(updatedUserResponse); // Step 2: Submit update

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const pgpInput = screen.getByLabelText(/Current PGP Key/i);
            const updateButton = screen.getByRole('button', { name: /Update PGP Key/i });

            // Initiate update
            await act(async () => {
                await user.clear(pgpInput);
                await user.type(pgpInput, validPgpKeyNew);
                await user.click(updateButton);
            });

            // Confirm in modal
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'pgp_key' });
            // Check button is disabled
            expect(updateButton).toBeDisabled();
            // <<< REVISION 35: Check for spinner in button >>>
            expect(within(updateButton).getByTestId('button-spinner')).toBeInTheDocument();


            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for final successful state
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2);
                expect(updateCurrentUser).toHaveBeenNthCalledWith(2, {
                    pgp_public_key: validPgpKeyNew,
                    signed_challenge: 'mockSignedChallenge'
                });
                expect(useAuth().setUser).toHaveBeenCalledWith(updatedUserResponse);
                expect(showSuccessToast).toHaveBeenCalledWith("PGP Key updated successfully!");
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check input field reflects the change (driven by context update)
                expect(screen.getByLabelText(/Current PGP Key/i)).toHaveValue(validPgpKeyNew);
                // Check button is re-enabled AND spinner is gone
                expect(updateButton).toBeEnabled();
                 // <<< REVISION 35: Check for spinner absence in button >>>
                 expect(within(updateButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });
        });

        test('shows error on failed PGP key update', async () => {
            // <<< REVISION 34: Suppress expected console.error >>>
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            const rawErrorMessage = 'Invalid key fingerprint.';
            const errorData = { pgp_public_key: [rawErrorMessage] };
            const apiError = new ApiError(rawErrorMessage, 400, errorData);
            const expectedDisplayedError = JSON.stringify(errorData); // Component logic uses stringify

            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Challenge ok
                .mockRejectedValueOnce(apiError); // Step 2: Submit fails

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const pgpInput = screen.getByLabelText(/Current PGP Key/i);
            const updateButton = screen.getByRole('button', { name: /Update PGP Key/i });
            const pgpSection = screen.getByRole('heading', { name: /PGP Public Key/i }).closest('section');

            // Initiate update
            await act(async () => {
                await user.clear(pgpInput);
                await user.type(pgpInput, validPgpKeyNew);
                await user.click(updateButton);
            });

            // Confirm in modal (which leads to failure)
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'pgp_key' });
            // Check button is disabled
            expect(updateButton).toBeDisabled();
             // <<< REVISION 35: Check for spinner in button >>>
             expect(within(updateButton).getByTestId('button-spinner')).toBeInTheDocument();

            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for final failure state
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2); // Both calls attempted
                // Check modal is CLOSED
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check error toast
                expect(showErrorToast).toHaveBeenCalledWith(expectedDisplayedError);
                // Check error displayed in the PGP section
                expect(within(pgpSection).getByRole('alert')).toHaveTextContent(expectedDisplayedError);
                // Check button is re-enabled AND spinner is gone
                expect(updateButton).toBeEnabled();
                 // <<< REVISION 35: Check for spinner absence in button >>>
                 expect(within(updateButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });

            // Check state not updated
            expect(useAuth().setUser).not.toHaveBeenCalled();
            // Input should retain the value user typed
             expect(screen.getByLabelText(/Current PGP Key/i)).toHaveValue(validPgpKeyNew);
             consoleErrorSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });
    });

    // --- Password Change Tests ---
    describe('Password Change', () => {
        test('shows password validation error: missing fields', async () => {
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const passwordSection = screen.getByRole('heading', { name: /Change Password/i }).closest('section');

            // Click change with empty fields
            await act(async () => { await user.click(changeButton); });

            // Wait for client-side error
            await waitFor(() => {
                expect(within(passwordSection).getByRole('alert')).toHaveTextContent(/password fields are required/i);
                expect(showErrorToast).toHaveBeenCalledWith("All password fields are required.");
            });
            expect(updateCurrentUser).not.toHaveBeenCalled(); // API not called
        });

        test('shows password validation error: mismatch', async () => {
             render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const validLengthPass1 = 'a'.repeat(MIN_PASSWORD_LENGTH);
            const validLengthPass2 = 'b'.repeat(MIN_PASSWORD_LENGTH); // Different password
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const passwordSection = screen.getByRole('heading', { name: /Change Password/i }).closest('section');

            // Enter mismatching new passwords
            await act(async () => {
                await user.type(screen.getByLabelText(/Current Password/i), 'currentpass');
                await user.type(screen.getByLabelText(/^New Password/i), validLengthPass1);
                await user.type(screen.getByLabelText(/Confirm New Password/i), validLengthPass2);
                await user.click(changeButton);
            });

             // Wait for client-side error
            await waitFor(() => {
                expect(within(passwordSection).getByRole('alert')).toHaveTextContent("New passwords do not match.");
                expect(showErrorToast).toHaveBeenCalledWith("New passwords do not match.");
            });
            expect(updateCurrentUser).not.toHaveBeenCalled(); // API not called
        });

        test('shows password validation error: too short', async () => {
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const shortPassword = 'a'.repeat(MIN_PASSWORD_LENGTH - 1);
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const passwordSection = screen.getByRole('heading', { name: /Change Password/i }).closest('section');

            // Enter short password
            await act(async () => {
                await user.type(screen.getByLabelText(/Current Password/i), 'currentpass');
                await user.type(screen.getByLabelText(/^New Password/i), shortPassword);
                await user.type(screen.getByLabelText(/Confirm New Password/i), shortPassword);
                await user.click(changeButton);
            });

            // Wait for client-side error
            await waitFor(() => {
                 expect(within(passwordSection).getByRole('alert')).toHaveTextContent(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
                 expect(showErrorToast).toHaveBeenCalledWith(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
            });
            expect(updateCurrentUser).not.toHaveBeenCalled(); // API not called
        });

        test('shows password validation error: new same as current', async () => {
             render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const currentPasswordValue = 'a'.repeat(MIN_PASSWORD_LENGTH);
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const passwordSection = screen.getByRole('heading', { name: /Change Password/i }).closest('section');

            // Enter new password same as current
            await act(async () => {
                await user.type(screen.getByLabelText(/Current Password/i), currentPasswordValue);
                await user.type(screen.getByLabelText(/^New Password/i), currentPasswordValue);
                await user.type(screen.getByLabelText(/Confirm New Password/i), currentPasswordValue);
                await user.click(changeButton);
            });

            // Wait for client-side error
            await waitFor(() => {
                 expect(within(passwordSection).getByRole('alert')).toHaveTextContent(/New password cannot be the same as the current password/i);
                expect(showErrorToast).toHaveBeenCalledWith("New password cannot be the same as the current password.");
            });
            expect(updateCurrentUser).not.toHaveBeenCalled(); // API not called
        });


        test('handles successful password change', async () => {
            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Challenge ok
                .mockResolvedValueOnce(undefined); // Step 2: Submit ok (no user data returned on pw change)

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const currentPassInput = screen.getByLabelText(/Current Password/i);
            const newPassInput = screen.getByLabelText(/^New Password/i);
            const confirmPassInput = screen.getByLabelText(/Confirm New Password/i);
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const newPassword = 'b'.repeat(MIN_PASSWORD_LENGTH);

            // Enter valid data and initiate change
            await act(async () => {
                await user.type(currentPassInput, 'oldCorrectPassword');
                await user.type(newPassInput, newPassword);
                await user.type(confirmPassInput, newPassword);
                await user.click(changeButton);
            });

            // Confirm in modal
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'password' });
            // Check button is disabled
            expect(changeButton).toBeDisabled();
            // <<< REVISION 35: Check for spinner in button >>>
            expect(within(changeButton).getByTestId('button-spinner')).toBeInTheDocument();


            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for final success state
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2);
                expect(updateCurrentUser).toHaveBeenNthCalledWith(2, {
                    current_password: 'oldCorrectPassword',
                    password: newPassword,
                    signed_challenge: 'mockSignedChallenge'
                });
                expect(showSuccessToast).toHaveBeenCalledWith("Password changed successfully!");
                // Check fields are cleared
                expect(currentPassInput).toHaveValue('');
                expect(newPassInput).toHaveValue('');
                expect(confirmPassInput).toHaveValue('');
                // Check modal closed
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check button is re-enabled AND spinner is gone
                expect(changeButton).toBeEnabled();
                 // <<< REVISION 35: Check for spinner absence in button >>>
                 expect(within(changeButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });
             // Password change shouldn't call setUser context
            expect(useAuth().setUser).not.toHaveBeenCalled();
        });

        test('shows error on failed password change (e.g., wrong current password)', async () => {
            // <<< REVISION 34: Suppress expected console.error >>>
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            const rawErrorMessage = 'Invalid current password.';
            const errorData = { current_password: [rawErrorMessage] };
            const apiError = new ApiError(rawErrorMessage, 400, errorData);
            const expectedDisplayedError = JSON.stringify(errorData); // Component logic uses stringify

            updateCurrentUser
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Challenge ok
                .mockRejectedValueOnce(apiError); // Step 2: Submit fails

            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1));
            const user = userEvent.setup();
            const currentPassInput = screen.getByLabelText(/Current Password/i);
            const newPassInput = screen.getByLabelText(/^New Password/i);
            const confirmPassInput = screen.getByLabelText(/Confirm New Password/i);
            const changeButton = screen.getByRole('button', { name: /Change Password/i });
            const passwordSection = screen.getByRole('heading', { name: /Change Password/i }).closest('section');

            const newPassword = 'b'.repeat(MIN_PASSWORD_LENGTH);
            const wrongCurrentPassword = 'wrongCurrentPassword';

            // Enter data with wrong current pass and initiate
            await act(async () => {
                await user.type(currentPassInput, wrongCurrentPassword);
                await user.type(newPassInput, newPassword);
                await user.type(confirmPassInput, newPassword);
                await user.click(changeButton);
            });

            // Confirm in modal (leads to failure)
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(updateCurrentUser).toHaveBeenCalledWith({ request_pgp_challenge_for: 'password' });
             // Check button is disabled
             expect(changeButton).toBeDisabled();
             // <<< REVISION 35: Check for spinner in button >>>
             expect(within(changeButton).getByTestId('button-spinner')).toBeInTheDocument();

            await act(async () => {
                await user.click(confirmButton);
            });

            // Wait for final failure state
            await waitFor(() => {
                expect(updateCurrentUser).toHaveBeenCalledTimes(2); // Both calls attempted
                // Check modal is CLOSED
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
                // Check error toast
                expect(showErrorToast).toHaveBeenCalledWith(expectedDisplayedError);
                // Check error displayed in the password section
                expect(within(passwordSection).getByRole('alert')).toHaveTextContent(expectedDisplayedError);
                 // Check button is re-enabled AND spinner is gone
                 expect(changeButton).toBeEnabled();
                  // <<< REVISION 35: Check for spinner absence in button >>>
                  expect(within(changeButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });

            // Check fields were NOT cleared
            expect(currentPassInput).toHaveValue(wrongCurrentPassword);
            expect(newPassInput).toHaveValue(newPassword);
            expect(confirmPassInput).toHaveValue(newPassword);
            expect(useAuth().setUser).not.toHaveBeenCalled();
            consoleErrorSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });
    });

    // --- Vendor Application Section Tests ---
    describe('Vendor Application Section', () => {
        test('does not render vendor application section if user is already a vendor', async () => {
            setMockAuthContext({ user: { ...defaultMockUser, is_vendor: true } });
            render(<ProfilePage />);
            await waitForInitialRender();
            expect(getVendorApplicationStatus).not.toHaveBeenCalled();
            expect(screen.queryByRole('heading', { name: /Vendor Status/i, level: 2, exact: false })).not.toBeInTheDocument();
        });

        test('shows "Apply for Vendor Status" button when not vendor and no application exists', async () => {
            getVendorApplicationStatus.mockResolvedValue(null); // Explicitly ensure no app exists
            render(<ProfilePage />);
            await waitFor(() => expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1)); // Wait for initial check

            expect(screen.getByRole('button', { name: /Apply for Vendor Status/i })).toBeInTheDocument();
            // Status display section should not be there
            expect(screen.queryByText(/Your Vendor Application Status:/i)).not.toBeInTheDocument();
        });

        test('calls applyForVendor API (challenge request) and opens PGP modal on apply click', async () => {
            getVendorApplicationStatus.mockResolvedValue(null); // No existing app
            applyForVendor.mockResolvedValueOnce(mockPgpChallenge); // Challenge request succeeds

            render(<ProfilePage />);
            const user = userEvent.setup();
            // Wait for initial status check and button to appear
            const applyButton = await screen.findByRole('button', { name: /Apply for Vendor Status/i });

            // Click apply
            await act(async () => { await user.click(applyButton); });

            // Wait for modal to appear and check API call
            await waitFor(() => {
                expect(screen.getByTestId('mock-pgp-signer')).toBeInTheDocument();
                expect(applyForVendor).toHaveBeenCalledWith(); // First call has no args
                 // Check button is disabled AND spinner present
                 expect(applyButton).toBeDisabled();
                 // <<< REVISION 35: Check for spinner in button >>>
                 expect(within(applyButton).getByTestId('button-spinner')).toBeInTheDocument();
            });
             // No success toast yet
            expect(showSuccessToast).not.toHaveBeenCalled();
        });

       test('submits application via modal, shows success, and fetches/displays new status', async () => {
            const finalStatus = { id: 'appReview123', status: 'pending_review', status_display: 'Pending Review', created_at: new Date().toISOString() };
            getVendorApplicationStatus
                .mockResolvedValueOnce(null) // Initial: No application
                .mockResolvedValueOnce(finalStatus); // After submit: New status fetched

            applyForVendor
                .mockResolvedValueOnce(mockPgpChallenge) // Step 1: Request challenge
                .mockResolvedValueOnce({}); // Step 2: Submit application (returns empty object on success typically)

            render(<ProfilePage />);
            const user = userEvent.setup();
            const applyButton = await screen.findByRole('button', { name: /Apply for Vendor Status/i }); // Wait for button

            // Click Apply
            await act(async () => { await user.click(applyButton); });

            // Modal appears, get confirm button
            const confirmButton = await screen.findByRole('button', { name: /Confirm Signature/i });
            expect(applyForVendor).toHaveBeenCalledTimes(1); // Challenge request done
            // Check button is disabled
            expect(applyButton).toBeDisabled();
             // <<< REVISION 35: Check for spinner in button >>>
             expect(within(applyButton).getByTestId('button-spinner')).toBeInTheDocument();


            // Click Confirm in Modal
            await act(async () => { await user.click(confirmButton); });

            // Wait for ALL final effects after successful submission
            await waitFor(() => {
                // Check API calls
                expect(applyForVendor).toHaveBeenCalledTimes(2); // Second call (submit)
                expect(applyForVendor).toHaveBeenNthCalledWith(2, { signed_challenge: 'mockSignedChallenge' });
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(2); // Initial + refresh after submit

                // Check UI Updates
                expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                expect(screen.getByText(finalStatus.status_display || finalStatus.status)).toBeInTheDocument(); // Display new status (prefer display)
                expect(showSuccessToast).toHaveBeenCalledWith("Vendor application submitted successfully.");
                expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument(); // Modal closed
                expect(screen.queryByRole('button', { name: /Apply for Vendor Status/i })).not.toBeInTheDocument(); // Apply button gone

                // Check refresh button exists after successful submission
                const refreshButton = screen.getByRole('button', { name: /Refresh Status/i });
                expect(refreshButton).toBeInTheDocument();
                // <<< REVISION 35: Check refresh button doesn't have spinner initially >>>
                expect(within(refreshButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });
        });


        test('shows error message if applyForVendor API fails (initial challenge request)', async () => {
            // <<< REVISION 34: Suppress expected console.error >>>
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            const errorMessage = 'Application limit reached';
            const apiError = new ApiError(errorMessage, 429, { detail: errorMessage });
            applyForVendor.mockRejectedValueOnce(apiError); // Challenge request fails
            getVendorApplicationStatus.mockResolvedValue(null); // No initial app

            render(<ProfilePage />);
            const user = userEvent.setup();
            // Wait for the button to be available initially
            const applyButton = await screen.findByRole('button', { name: /Apply for Vendor Status/i });
            const vendorSection = screen.getByRole('heading', { name: /Vendor Status/i, level: 2 }).closest('section');

            // Click apply (triggers failed API call)
            await act(async () => { await user.click(applyButton); });

            // Wait for error state
            await waitFor(() => {
                expect(within(vendorSection).getByRole('alert')).toHaveTextContent(errorMessage);
                expect(showErrorToast).toHaveBeenCalledWith(errorMessage);
                // Apply button should still be visible, enabled AND spinner gone after error
                expect(applyButton).toBeInTheDocument();
                expect(applyButton).toBeEnabled();
                // <<< REVISION 35: Check for spinner absence in button >>>
                expect(within(applyButton).queryByTestId('button-spinner')).not.toBeInTheDocument();
            });

            // Modal should not have opened
             expect(screen.queryByTestId('mock-pgp-signer')).not.toBeInTheDocument();
             consoleErrorSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });

        // --- Tests for displaying existing statuses ---
        test('fetches and displays existing "pending_bond" application status on load', async () => {
            const mockApp = { id: 'appBond123', status: 'pending_bond', status_display: 'Pending Bond Payment', bond_amount: '0.5', bond_currency: 'XMR', created_at: '2025-04-10T10:00:00Z' };
            getVendorApplicationStatus.mockResolvedValue(mockApp);
            render(<ProfilePage />);

            await waitFor(() => {
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                expect(screen.getByText(mockApp.status_display || mockApp.status)).toBeInTheDocument(); // Check status display/identifier
                // Check specific text for pending_bond
                expect(screen.getByText(/Action Required: Please deposit the required bond amount \(0.5 XMR\) to your wallet./i)).toBeInTheDocument();
                // Check Refresh button exists
                expect(screen.getByRole('button', { name: /Refresh Status/i })).toBeInTheDocument();
            });
            // Apply button should not be there if status exists
            expect(screen.queryByRole('button', { name: /Apply for Vendor Status/i })).not.toBeInTheDocument();
        });

        test('fetches and displays existing "pending_review" application status on load', async () => {
            const mockApp = { id: 'appReview', status: 'pending_review', status_display: 'Pending Review', created_at: '2025-04-11T11:00:00Z' };
            getVendorApplicationStatus.mockResolvedValue(mockApp);
            render(<ProfilePage />);

             await waitFor(() => {
                 expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                 expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                 expect(screen.getByText(mockApp.status_display || mockApp.status)).toBeInTheDocument();
                 expect(screen.getByText(/Your application is currently under review./i)).toBeInTheDocument(); // Check specific text
                 // Check Refresh button exists
                 expect(screen.getByRole('button', { name: /Refresh Status/i })).toBeInTheDocument();
             });
              expect(screen.queryByRole('button', { name: /Apply for Vendor Status/i })).not.toBeInTheDocument();
        });

         test('fetches and displays existing "approved" application status on load', async () => {
            const mockApp = { id: 'appApproved', status: 'approved', status_display: 'Approved', created_at: '2025-04-12T12:00:00Z' };
            getVendorApplicationStatus.mockResolvedValue(mockApp);
            render(<ProfilePage />);

              await waitFor(() => {
                  expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                  expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                  expect(screen.getByText(mockApp.status_display || mockApp.status)).toBeInTheDocument();
                  expect(screen.getByText(/Congratulations! Your vendor application has been approved./i)).toBeInTheDocument(); // Check specific text
              });
               expect(screen.queryByRole('button', { name: /Apply for Vendor Status/i })).not.toBeInTheDocument();
               expect(screen.queryByRole('button', { name: /Refresh Status/i })).not.toBeInTheDocument();
        });

        test('fetches and displays existing "rejected" application status on load', async () => {
            const mockApp = { id: 'appRejected', status: 'rejected', status_display: 'Rejected', rejection_reason: 'Insufficient info', created_at: '2025-04-13T13:00:00Z' };
            getVendorApplicationStatus.mockResolvedValue(mockApp);
            render(<ProfilePage />);

            await waitFor(() => {
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                expect(screen.getByText(mockApp.status_display || mockApp.status)).toBeInTheDocument();
                expect(screen.getByText(/Reason: Insufficient info/i)).toBeInTheDocument(); // Check reason
                expect(screen.getByText(/Unfortunately, your vendor application has been rejected./i)).toBeInTheDocument(); // Check specific text
            });
            expect(screen.queryByRole('button', { name: /Apply for Vendor Status/i })).not.toBeInTheDocument();
            expect(screen.queryByRole('button', { name: /Refresh Status/i })).not.toBeInTheDocument();
        });

        test('fetches and displays existing "rejected" application status without reason', async () => {
            const mockApp = { id: 'appRejectedNR', status: 'rejected', status_display: 'Rejected', rejection_reason: null, created_at: '2025-04-14T14:00:00Z' };
            getVendorApplicationStatus.mockResolvedValue(mockApp);
            render(<ProfilePage />);

            await waitFor(() => {
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                expect(screen.getByText(/Your Vendor Application Status:/i)).toBeInTheDocument();
                expect(screen.getByText(mockApp.status_display || mockApp.status)).toBeInTheDocument();
                expect(screen.getByText(/Reason: No reason provided./i)).toBeInTheDocument(); // Check default text
                expect(screen.getByText(/Unfortunately, your vendor application has been rejected./i)).toBeInTheDocument(); // Check specific text
            });
             expect(screen.queryByRole('button', { name: /Refresh Status/i })).not.toBeInTheDocument();
        });

       test('clicking "Refresh Status" calls getVendorApplicationStatus again and updates UI', async () => {
           const initialStatus = { id: 'appReview', status: 'pending_review', status_display: 'Pending Review', created_at: '2025-04-11T11:00:00Z' };
           const refreshedStatus = { id: 'appReview', status: 'approved', status_display: 'Approved', created_at: '2025-04-11T11:00:00Z' }; // Status changed
           getVendorApplicationStatus
               .mockResolvedValueOnce(initialStatus) // Initial load
               .mockResolvedValueOnce(refreshedStatus); // Refresh call

           render(<ProfilePage />);
           const user = userEvent.setup();

           // Wait for initial status and refresh button
           const refreshButton = await screen.findByRole('button', { name: /Refresh Status/i });
           expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
           expect(screen.getByText(initialStatus.status_display || initialStatus.status)).toBeInTheDocument(); // Check initial status displayed (prefer display)

           // Click Refresh
           await act(async () => {
               await user.click(refreshButton);
           });

           // Wait for refresh effects
           await waitFor(() => {
               expect(getVendorApplicationStatus).toHaveBeenCalledTimes(2); // Called again
               expect(showInfoToast).toHaveBeenCalledWith("Refreshing application status...");
               // Check UI updated to new status
               expect(screen.getByText(refreshedStatus.status_display || refreshedStatus.status)).toBeInTheDocument();
               // Old status display should be gone
               expect(screen.queryByText(initialStatus.status_display || initialStatus.status)).not.toBeInTheDocument();
               // Refresh button should *disappear* after refresh because the new status is 'approved' (terminal)
               expect(screen.queryByRole('button', { name: /Refresh Status/i })).not.toBeInTheDocument();
           });
       });


        test('shows error if fetching application status fails (not 404)', async () => {
            // <<< REVISION 34: Suppress expected console.error >>>
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            const errorMessage = 'Server Timeout';
            const apiError = new ApiError(errorMessage, 504);
            getVendorApplicationStatus.mockRejectedValue(apiError); // Initial fetch fails
            render(<ProfilePage />);
            const vendorSection = screen.getByRole('heading', { name: /Vendor Status/i, level: 2 }).closest('section');

            // Wait for the error state after initial load attempt
            await waitFor(() => {
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                // Expect the error message to be shown *within the vendor section*
                expect(within(vendorSection).getByRole('alert')).toHaveTextContent(errorMessage);
                expect(showErrorToast).toHaveBeenCalledWith(errorMessage);
            });
            // Apply button SHOULD appear alongside error
            const applyButton = await screen.findByRole('button', { name: /Apply for Vendor Status/i });
            expect(applyButton).toBeInTheDocument();
            expect(applyButton).toBeEnabled(); // Should be enabled if error occurred before application started
            consoleErrorSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });

        test('handles 404 error from getVendorApplicationStatus gracefully (shows apply button)', async () => {
            // <<< REVISION 34: Suppress expected console.log >>>
            // This comes from the catch block in getVendorApplicationStatus in api.js
            const consoleLogSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
            const notFoundError = new ApiError('Not Found', 404);
            getVendorApplicationStatus.mockRejectedValue(notFoundError); // API returns 404
            render(<ProfilePage />);
            const vendorSection = screen.getByRole('heading', { name: /Vendor Status/i, level: 2 }).closest('section');

            // Wait for the state after the 404 response
            await waitFor(() => {
                expect(getVendorApplicationStatus).toHaveBeenCalledTimes(1);
                // 404 means no application, so Apply button should show
                expect(screen.getByRole('button', { name: /Apply for Vendor Status/i })).toBeInTheDocument();
            });
            // No error message should be displayed in the UI for 404
            expect(within(vendorSection).queryByRole('alert')).not.toBeInTheDocument();
            expect(showErrorToast).not.toHaveBeenCalled();
             // Ensure Apply button is enabled
            expect(screen.getByRole('button', { name: /Apply for Vendor Status/i })).toBeEnabled();
            consoleLogSpy.mockRestore(); // <<< REVISION 34: Restore spy >>>
        });

        test('does not fetch application status if PGP is not authenticated', async () => {
            setMockAuthContext({ isPgpAuthenticated: false });
            render(<ProfilePage />);
            // Wait for the PGP auth required message to appear
            await screen.findByRole('heading', { name: /PGP Authentication Required/i });
            // Status check should definitely not have been called
            expect(getVendorApplicationStatus).not.toHaveBeenCalled();
        });
    });
});