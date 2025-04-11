// --- START TEST FILE ---
// File: frontend/__tests__/pages/orders/[orderId].test.js
// Reason: Production-grade tests for OrderDetailPage multi-sig signing flow.
// --- REVISION HISTORY ---
// 2025-04-09: Rev 12 - Changed vendor assertion to find the link within the 'Product' section.
// 2025-04-09: Rev 11 - Reverted vendor assertion to find label then search within parent paragraph. Removed inline PGP warning check in disable test.
// 2025-04-09: Rev 10 - Scoped vendor link search to Participants section. Simplified disabled button test check.
// 2025-04-09: Rev 9 - Adjusted title assertion using custom function. Changed vendor assertion to find link by name. Changed disabled submit button test to check for absence.
// 2025-04-09: Rev 8 - Adjusted title assertion to handle split text. Adjusted disabled button test to check for button absence or error message presence.
// 2025-04-09: Rev 7 - Changed mocking strategy again to import, mock, then require mocked modules to fix ReferenceError.
// 2025-04-09: Rev 6 - Defined jest.fn() directly inside jest.mock factory for notifications module.
// 2025-04-09: Rev 5 - Defined jest.fn() directly inside jest.mock factory for api module.
// 2025-04-09: Rev 4 - Corrected jest.mock factory function syntax to fix initialization error (attempt 1).
// 2025-04-09: Rev 3 - Changed assertion again for basic details test to find username within the label's parent paragraph.
//             - Changed PGP auth error test to use findByText instead of findByRole.
// 2025-04-09: Rev 2 - Fixed assertions for basic details and PGP auth error display.
//           - Changed `toHaveTextContent` assertion for user details to check the parent `p`.
//           - Changed PGP auth error test to look for text content in `.error-message` div instead of `role="alert"`.
// 2025-04-08: Rev 1 - Initial creation. Tests for OrderDetailPage multi-sig signing flow.


import React from 'react';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react'; // Import 'within'
import userEvent from '@testing-library/user-event';
import OrderDetailPage from '@/pages/orders/[orderId]'; // Adjust import path as per your structure

// --- Mock Dependencies ---
// Mock Next.js router
const mockRouterPush = jest.fn();
jest.mock('next/router', () => ({
  useRouter: () => ({
    query: { orderId: 'mock-order-uuid-123' },
    isReady: true,
    push: mockRouterPush, // Mock push for potential redirects
  }),
}));

// Mock Auth Context
const mockBuyerUser = { id: 'user-buyer-1', username: 'buyer1', is_staff: false };
const mockVendorUser = { id: 'user-vendor-1', username: 'vendor1', is_staff: false };
let mockAuthContextState = { // Define a mutable state for mocking
  user: mockBuyerUser,
  isPgpAuthenticated: true,
  authIsLoading: false,
};
jest.mock('@/context/AuthContext', () => ({ // Adjust import path
  useAuth: jest.fn(() => mockAuthContextState),
}));
// Helper to update mock auth state easily in tests
const setMockAuthState = (authState) => {
    mockAuthContextState = { ...mockAuthContextState, ...authState };
};

// --- Mocking Strategy (Import, Mock, Require) ---
// 1. Import the actual modules (optional, but helps IDE)
import * as apiUtils from '@/utils/api';
import * as notificationUtils from '@/utils/notifications';

// 2. Tell Jest to mock the modules (auto-mocking exports with jest.fn())
jest.mock('@/utils/api');
jest.mock('@/utils/notifications');

// 3. Require the mocked modules to get access to the mock functions
const mockApi = require('@/utils/api');
const mockNotifications = require('@/utils/notifications');
// --- END Mocking Strategy ---


// Mock Child Components (Optional but can speed up tests)
jest.mock('@/components/Layout', () => ({ children }) => <div>{children}</div>); // Adjust import path
jest.mock('@/components/LoadingSpinner', () => () => <div>Loading...</div>); // Adjust import path
// Mock FormError just in case it's used elsewhere in the component
jest.mock('@/components/FormError', () => ({ message, className }) => message ? <div role="alert" className={`mock-form-error ${className}`}>{typeof message === 'string' ? message : JSON.stringify(message)}</div> : null); // Adjust import path

// --- Mock Data ---
const createMockOrder = (overrides = {}) => ({
    id: 'mock-order-uuid-123',
    buyer: { id: 'user-buyer-1', username: 'buyer1' },
    vendor: { id: 'user-vendor-1', username: 'vendor1' },
    product: { id: 'prod-1', name: 'Test Product', slug: 'test-product', is_digital: false, vendor: { username: 'vendor1'} },
    quantity: 1,
    selected_currency: 'BTC',
    total_price_native_selected: '0.01',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    payment_deadline: new Date(Date.now() + 86400000).toISOString(),
    auto_finalize_deadline: new Date(Date.now() + 86400000 * 14).toISOString(),
    dispute_deadline: null,
    selected_shipping_option: { name: 'Standard' },
    encrypted_shipping_info: '--- ENCRYPTED BLOB ---',
    escrow_type: 'multi-sig',
    payment: {
        payment_address: 'mockBTCaddress',
        expected_amount_native: '0.01',
        received_amount_native: '0.01',
        is_confirmed: true,
        confirmations_received: 6,
        confirmations_needed: 3,
        transaction_hash: 'mockPaymentTxHash',
    },
    release_initiated: false,
    release_signature_buyer: null,
    release_signature_vendor: null,
    // Use presence flags if backend provides them, otherwise derive from signatures above
    release_signature_buyer_present: false,
    release_signature_vendor_present: false,
    release_tx_broadcast_hash: null,
    status: 'SHIPPED', // Default ready state
    status_display: 'Shipped', // Add status display if used
    ...overrides,
});

// --- Test Suite ---
describe('OrderDetailPage Multi-Sig Signing Flow', () => {

    beforeEach(() => {
        jest.clearAllMocks(); // Clear mocks defined with jest.fn()
        // Reset to default: Buyer, PGP Authenticated
        setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });
        // Default successful order fetch - use the mocked module references
        mockApi.getOrderDetails.mockResolvedValue(createMockOrder());
    });

    it('should render basic order details', async () => {
        render(<OrderDetailPage />);

        // REV 9 Fix: Find heading by role/level and use custom text matcher function
        const heading = await screen.findByRole('heading', {
             level: 1,
             name: (content, element) => /Order Details.*mock-ord.../.test(element.textContent) // Check combined text
        });
        expect(heading).toBeInTheDocument();

        // Find the label and check the parent paragraph's content
        const statusLabel = screen.getByText((content, element) => element.tagName.toLowerCase() === 'strong' && content.trim() === 'Status:');
        expect(statusLabel.closest('p')).toHaveTextContent('Status: Shipped'); // Check parent P
        // Find the parent paragraph of the label, then check for username *within* that paragraph
        const buyerLabel = screen.getByText('Buyer:');
        expect(within(buyerLabel.closest('p')).getByText(mockBuyerUser.username)).toBeInTheDocument();

        // REV 12 Fix: Find the "Product" section and search within it for the vendor link
        const productHeading = screen.getByRole('heading', { name: 'Product', level: 2});
        const productSection = productHeading.closest('section'); // Find the wrapping section
        expect(within(productSection).getByRole('link', { name: mockVendorUser.username })).toBeInTheDocument();
    });

    it('should show "Prepare Release" button for buyer when appropriate', async () => {
        const order = createMockOrder({
            status: 'SHIPPED',
            release_initiated: true,
            release_signature_buyer_present: false, // Buyer needs to sign
            release_signature_vendor_present: true, // Vendor already signed
        });
        mockApi.getOrderDetails.mockResolvedValue(order);
        setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });

        render(<OrderDetailPage />);
        expect(await screen.findByRole('button', { name: /Prepare Release Transaction/i })).toBeEnabled();
    });

     it('should show "Prepare Release" button for vendor when appropriate', async () => {
         const order = createMockOrder({
             status: 'SHIPPED',
             release_initiated: true,
             release_signature_vendor_present: false, // Vendor needs to sign
             release_signature_buyer_present: true, // Buyer already signed
         });
         mockApi.getOrderDetails.mockResolvedValue(order);
         setMockAuthState({ user: mockVendorUser, isPgpAuthenticated: true, authIsLoading: false }); // Set user to vendor

         render(<OrderDetailPage />);
         expect(await screen.findByRole('button', { name: /Prepare Release Transaction/i })).toBeEnabled();
     });

     it('should NOT show "Prepare Release" if release not initiated', async () => {
          const order = createMockOrder({ status: 'SHIPPED', release_initiated: false }); // Release NOT initiated
          mockApi.getOrderDetails.mockResolvedValue(order);
          setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });

          render(<OrderDetailPage />);
          await screen.findByText('Status:'); // Wait for render
          expect(screen.queryByRole('button', { name: /Prepare Release Transaction/i })).not.toBeInTheDocument();
     });

     it('should NOT show "Prepare Release" if user already signed', async () => {
          const order = createMockOrder({
               status: 'SHIPPED',
               release_initiated: true,
               release_signature_buyer_present: true, // Buyer ALREADY signed
               release_signature_vendor_present: false,
          });
          mockApi.getOrderDetails.mockResolvedValue(order);
          setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });

          render(<OrderDetailPage />);
          await screen.findByText('Status:');
          expect(screen.queryByRole('button', { name: /Prepare Release Transaction/i })).not.toBeInTheDocument();
     });


    it('should call getUnsignedReleaseTxData, display data and form on successful prepare', async () => {
        const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
        mockApi.getOrderDetails.mockResolvedValue(order);
        const unsignedTx = 'UNSIGNED_MOCK_DATA_HEX';
        mockApi.getUnsignedReleaseTxData.mockResolvedValue({ unsigned_tx: unsignedTx });

        render(<OrderDetailPage />);
        const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });

        await userEvent.click(prepareButton);

        expect(mockApi.getUnsignedReleaseTxData).toHaveBeenCalledWith(order.id);
        await waitFor(() => {
            // Check the textarea value for unsigned data
            expect(screen.getByLabelText(/Unsigned Transaction Data:/i)).toHaveValue(unsignedTx);
        });
        expect(screen.getByLabelText(/Paste Your Signature Data Here:/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Submit Signature/i })).toBeInTheDocument();
        expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith(expect.stringContaining('data prepared'));
        expect(screen.queryByText(/Prepare failed on backend/i)).not.toBeInTheDocument();
    });

    it('should display error message if prepare fails', async () => {
        const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
        mockApi.getOrderDetails.mockResolvedValue(order);
        // Use an Error object for better simulation
        const prepareError = new Error('Prepare failed on backend');
        mockApi.getUnsignedReleaseTxData.mockRejectedValue(prepareError);

        render(<OrderDetailPage />);
        const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });

        await userEvent.click(prepareButton);

        expect(mockApi.getUnsignedReleaseTxData).toHaveBeenCalledWith(order.id);
        // Wait for the specific error message to appear within the FormError component (rendered by the signing flow)
        expect(await screen.findByText(/Prepare failed on backend/i)).toBeInTheDocument();
        // Check if the error text exists within an element having the mock FormError class
        expect(screen.getByText(/Prepare failed on backend/i).closest('.mock-form-error')).toBeInTheDocument();
        expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(expect.stringContaining('Prepare failed on backend'));
        expect(screen.queryByLabelText(/Unsigned Transaction Data:/i)).not.toBeInTheDocument();
    });


    it('should submit signature and refresh order on successful sign', async () => {
        // Setup: Order ready, user needs to sign, prepare step successful
        const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
        // mockApi.getOrderDetails needs to be used multiple times
        mockApi.getOrderDetails.mockResolvedValueOnce(order); // Initial fetch
        const unsignedTx = 'UNSIGNED_MOCK_DATA_HEX';
        mockApi.getUnsignedReleaseTxData.mockResolvedValue({ unsigned_tx: unsignedTx });
        // Mock successful sign release
        mockApi.signRelease.mockResolvedValue({ success: true });
        // Mock refetch after signing
        const orderAfterSign = createMockOrder({ ...order, release_signature_buyer_present: true }); // Simulate signature added
        mockApi.getOrderDetails.mockResolvedValueOnce(orderAfterSign); // Fetch after signing

        render(<OrderDetailPage />);

        // 1. Prepare
        const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });
        await userEvent.click(prepareButton);
        await screen.findByLabelText(/Unsigned Transaction Data:/i); // Wait for form

        // 2. Input signature
        const signatureInput = screen.getByLabelText(/Paste Your Signature Data Here:/i);
        const submitButton = screen.getByRole('button', { name: /Submit Signature/i });
        const pastedSignature = 'USER_SIGNED_DATA';
        await userEvent.type(signatureInput, pastedSignature);

        // 3. Submit
        await userEvent.click(submitButton);

        // 4. Verify API call
        expect(mockApi.signRelease).toHaveBeenCalledWith(order.id, { signature_data: pastedSignature });

        // 5. Verify success notification
        await waitFor(() => {
            expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith(expect.stringContaining('Signature submitted successfully'));
        });

        // 6. Verify order details were refetched
        expect(mockApi.getOrderDetails).toHaveBeenCalledTimes(2); // Initial + Refresh

        // 7. Verify signing form is hidden (because unsignedTxData should be cleared)
        await waitFor(() => {
           expect(screen.queryByLabelText(/Unsigned Transaction Data:/i)).not.toBeInTheDocument();
        });
    });

     it('should display error message if signing fails', async () => {
         // Setup: Order ready, user needs to sign, prepare step successful
         const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
         mockApi.getOrderDetails.mockResolvedValue(order);
         const unsignedTx = 'UNSIGNED_MOCK_DATA_HEX';
         mockApi.getUnsignedReleaseTxData.mockResolvedValue({ unsigned_tx: unsignedTx });
         // Mock failed sign release
         const signError = new Error('Invalid signature data provided');
         mockApi.signRelease.mockRejectedValue(signError);

         render(<OrderDetailPage />);

         // 1. Prepare
         const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });
         await userEvent.click(prepareButton);
         await screen.findByLabelText(/Unsigned Transaction Data:/i); // Wait for form

         // 2. Input signature
         const signatureInput = screen.getByLabelText(/Paste Your Signature Data Here:/i);
         const submitButton = screen.getByRole('button', { name: /Submit Signature/i });
         const pastedSignature = 'INVALID_USER_SIGNED_DATA';
         await userEvent.type(signatureInput, pastedSignature);

         // 3. Submit
         await userEvent.click(submitButton);

         // 4. Verify API call
         expect(mockApi.signRelease).toHaveBeenCalledWith(order.id, { signature_data: pastedSignature });

         // 5. Verify error notification and message display
         await waitFor(() => {
             expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(expect.stringContaining('Invalid signature data provided'));
             // Check for the specific error message displayed near the form (using FormError)
             expect(screen.getByText(/Invalid signature data provided/i)).toBeInTheDocument();
             // Check it's inside the FormError mock
             expect(screen.getByText(/Invalid signature data provided/i).closest('.mock-form-error')).toBeInTheDocument();
         });

          // 6. Verify form is still visible
         expect(screen.getByLabelText(/Unsigned Transaction Data:/i)).toBeInTheDocument();
         expect(screen.getByLabelText(/Paste Your Signature Data Here:/i)).toBeInTheDocument();
     });

    it('should show early error message if PGP auth is false on load', async () => {
        const order = createMockOrder();
        mockApi.getOrderDetails.mockResolvedValue(order); // Still mock this, though it shouldn't be called ideally
        // Mock PGP Auth as false *before* initial render
        setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: false, authIsLoading: false });

        render(<OrderDetailPage />);

        // REV 3 Fix: Look for the specific error text using findByText
        const errorMessageElement = await screen.findByText(/PGP authentication required to view order details/i);
        expect(errorMessageElement).toBeInTheDocument();
        // Optional: Check the class if needed, but finding by text is usually sufficient
        expect(errorMessageElement).toHaveClass('error-message');

        // Assert that the main order content (like the prepare button) is NOT rendered
        expect(screen.queryByRole('button', { name: /Prepare Release Transaction/i })).not.toBeInTheDocument();
    });


     it('should disable Prepare/Submit buttons if PGP auth is false later', async () => {
         const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
         mockApi.getOrderDetails.mockResolvedValue(order);
         // Mock PGP Auth as initially true
         setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });

         const { rerender } = render(<OrderDetailPage />);
         const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });
         expect(prepareButton).toBeEnabled(); // Initially enabled

         // --- Simulate PGP Auth becoming false (e.g., context update) ---
         setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: false, authIsLoading: false });
         rerender(<OrderDetailPage />); // Rerender with updated context

         // REV 8 Fix: Assert the button is NOT present OR the PGP error IS present
         await waitFor(() => {
            expect(screen.queryByRole('button', { name: /Prepare Release Transaction/i })).not.toBeInTheDocument();
         });
         // Also check the main PGP error message appears
         expect(await screen.findByText(/PGP authentication required to view order details/i)).toBeInTheDocument();


          // --- Simulate getting unsigned data then PGP failing ---
          // Reset to PGP true, prepare, then set PGP false
          setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });
          rerender(<OrderDetailPage />);
          const unsignedTx = 'UNSIGNED_MOCK_DATA_HEX';
          mockApi.getUnsignedReleaseTxData.mockResolvedValue({ unsigned_tx: unsignedTx });
          // Ensure the prepare button exists before clicking
          const prepareButtonAgain = await screen.findByRole('button', { name: /Prepare Release Transaction/i });
          await userEvent.click(prepareButtonAgain);
          await screen.findByLabelText(/Paste Your Signature Data Here:/i); // Wait for form

          // Now set PGP auth to false
          setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: false, authIsLoading: false });
          rerender(<OrderDetailPage />);

          // REV 10 Fix: Assert the submit button is NOT present anymore
          await waitFor(() => {
             expect(screen.queryByRole('button', { name: /Submit Signature/i })).not.toBeInTheDocument();
          });
          // Optionally, also check that the prepare button is gone from this state
          expect(screen.queryByRole('button', { name: /Prepare Release Transaction/i })).not.toBeInTheDocument();
          // REV 11 Fix: Remove assertion for inline warning

     });

});

// --- END TEST FILE ---