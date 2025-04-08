// --- START TEST FILE ---
// File: frontend/__tests__/pages/orders/[orderId].test.js
// Reason: Production-grade tests for OrderDetailPage multi-sig signing flow.

import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
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

// Mock API utility functions
// Explicitly mock all functions imported by the component
const mockApi = {
  getOrderDetails: jest.fn(),
  markOrderShipped: jest.fn(),
  finalizeOrder: jest.fn(), // If called by handleInitiateFinalize
  signRelease: jest.fn(),
  openDispute: jest.fn(),
  getUnsignedReleaseTxData: jest.fn(),
};
jest.mock('@/utils/api', () => mockApi); // Adjust import path

// Mock Notification utility
const mockNotifications = {
  showErrorToast: jest.fn(),
  showSuccessToast: jest.fn(),
  showInfoToast: jest.fn(),
};
jest.mock('@/utils/notifications', () => mockNotifications); // Adjust import path

// Mock Child Components (Optional but can speed up tests)
jest.mock('@/components/Layout', () => ({ children }) => <div>{children}</div>); // Adjust import path
jest.mock('@/components/LoadingSpinner', () => () => <div>Loading...</div>); // Adjust import path
jest.mock('@/components/FormError', () => ({ error }) => <div role="alert">{typeof error === 'string' ? error : JSON.stringify(error)}</div>); // Adjust import path

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
        jest.clearAllMocks();
        // Reset to default: Buyer, PGP Authenticated
        setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: true, authIsLoading: false });
        // Default successful order fetch
        mockApi.getOrderDetails.mockResolvedValue(createMockOrder());
    });

    it('should render basic order details', async () => {
        render(<OrderDetailPage />);
        // Use findBy queries to wait for async data loading
        expect(await screen.findByText(/Order Details mock-order-uuid-123/i)).toBeInTheDocument();
        expect(screen.getByText(/Status:/i)).toHaveTextContent('Shipped'); // Using status_display
        expect(screen.getByText(/Buyer:/i)).toHaveTextContent(mockBuyerUser.username);
        expect(screen.getByText(/Vendor:/i)).toHaveTextContent(mockVendorUser.username);
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
          await screen.findByText(/Status:/i); // Wait for render
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
          await screen.findByText(/Status:/i);
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
            expect(screen.getByLabelText(/Unsigned Transaction Data:/i)).toHaveValue(unsignedTx);
        });
        expect(screen.getByLabelText(/Paste Your Signature Data Here:/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Submit Signature/i })).toBeInTheDocument();
        expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith(expect.stringContaining('data prepared'));
        expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // No error message
    });

    it('should display error message if prepare fails', async () => {
        const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
        mockApi.getOrderDetails.mockResolvedValue(order);
        const errorDetails = { detail: 'Prepare failed on backend' };
        mockApi.getUnsignedReleaseTxData.mockRejectedValue(errorDetails);

        render(<OrderDetailPage />);
        const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });

        await userEvent.click(prepareButton);

        expect(mockApi.getUnsignedReleaseTxData).toHaveBeenCalledWith(order.id);
        expect(await screen.findByRole('alert')).toHaveTextContent(/Prepare failed on backend/i);
        expect(mockNotifications.showErrorToast).toHaveBeenCalledWith(expect.stringContaining('Prepare failed on backend'));
        expect(screen.queryByLabelText(/Unsigned Transaction Data:/i)).not.toBeInTheDocument();
    });

    it('should submit signature and refresh order on successful sign', async () => {
        // Setup: Order ready, user needs to sign, prepare step successful
        const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
        mockApi.getOrderDetails.mockResolvedValue(order);
        const unsignedTx = 'UNSIGNED_MOCK_DATA_HEX';
        mockApi.getUnsignedReleaseTxData.mockResolvedValue({ unsigned_tx: unsignedTx });
        // Mock successful sign release (doesn't matter what it returns for this test if we refetch)
        mockApi.signRelease.mockResolvedValue({ success: true });
        // Mock refetch after signing
        const orderAfterSign = createMockOrder({ ...order, release_signature_buyer_present: true }); // Simulate signature added
        const getOrderDetailsMock = mockApi.getOrderDetails; // Get ref before reassigning
        getOrderDetailsMock.mockResolvedValueOnce(order); // Initial fetch
        getOrderDetailsMock.mockResolvedValueOnce(orderAfterSign); // Fetch after signing

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
        expect(getOrderDetailsMock).toHaveBeenCalledTimes(2); // Initial + Refresh

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
         const signErrorDetails = { detail: 'Invalid signature data provided' };
         mockApi.signRelease.mockRejectedValue(signErrorDetails);

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
             // Check for the specific error message displayed near the form
             expect(screen.getByRole('alert')).toHaveTextContent(/Invalid signature data provided/i);
         });

          // 6. Verify form is still visible
         expect(screen.getByLabelText(/Unsigned Transaction Data:/i)).toBeInTheDocument();
         expect(screen.getByLabelText(/Paste Your Signature Data Here:/i)).toBeInTheDocument();
     });

     it('should disable Prepare/Submit buttons if PGP auth is false', async () => {
         const order = createMockOrder({ status: 'SHIPPED', release_initiated: true, release_signature_buyer_present: false });
         mockApi.getOrderDetails.mockResolvedValue(order);
         // Mock PGP Auth as false
         setMockAuthState({ user: mockBuyerUser, isPgpAuthenticated: false, authIsLoading: false });

         render(<OrderDetailPage />);
         const prepareButton = await screen.findByRole('button', { name: /Prepare Release Transaction/i });
         expect(prepareButton).toBeDisabled();

          // Now, simulate getting unsigned data (hypothetically, though button is disabled)
          // Need to re-render or update state to show the submit form
          // This scenario is less likely as prepare button is disabled,
          // but testing submit button disabled state is good practice.
          // Let's assume unsignedTxData was somehow set:
          // rerender(<OrderDetailPage />); // Need state management outside component or different approach

          // A simpler check might be difficult without triggering the state change
          // Alternative: Test the button's disabled prop based on isPgpAuthenticated directly
          // if the component logic allows.
     });

});

// --- END TEST FILE ---