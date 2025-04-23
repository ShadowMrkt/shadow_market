// frontend/components/Layout.test.js
// --- REVISION HISTORY ---
// 2025-04-23 (Gemini): Rev 15 - Corrected useSWR mock assertion to expect the actual key ("canaryData") used in the component.
// 2025-04-23 (Gemini): Rev 14 - Removed TypeScript 'as jest.Mock' syntax causing SyntaxError in JS environment. Mocking useSWR should still resolve original act() warning.
// 2025-04-23 (Gemini): Rev 13 - Mocked useSWR directly to control its return values and prevent internal SWR state updates from causing act() warnings. Removed getCanaryData mock and SWRConfig provider as they are no longer needed with useSWR mocked. Simplified async assertions.
// ... (previous history omitted for brevity) ...

import React from 'react';
import { render, screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import useSWR from 'swr'; // Import useSWR *after* mocking

// --- Mock Dependencies ---
// Mock swr first
jest.mock('swr');

// Mock next/head
jest.mock('next/head', () => {
  return {
    __esModule: true,
    default: ({ children }) => <>{children}</>,
  };
});
// Mock next/link
jest.mock('next/link', () => ({ children, href, className, title }) => <a href={href} className={className} title={title}>{children}</a>);
// Mock next/image
jest.mock('next/image', () => ({ src, alt, width, height, priority }) => (
  // eslint-disable-next-line @next/next/no-img-element
  <img src={src} alt={alt} width={width} height={height} loading={priority ? 'eager' : 'lazy'}/>
));
// Mock context/AuthContext
const mockLogout = jest.fn();
let mockAuthContextValue = {
  user: null,
  logout: mockLogout,
  isLoading: false,
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock child components
jest.mock('./LoadingSpinner', () => ({ message, size }) => <div data-testid="loading-spinner">{message}</div>);
// Mock CanaryStatusIndicator: Provide a simple placeholder factory.
jest.mock('./CanaryStatusIndicator', () => jest.fn(() => <div data-testid="canary-indicator-placeholder">Initial Placeholder</div>));


// --- NOW Import the modules AFTER mocks are defined ---
import Layout from './Layout'; // Adjust path as needed
import CanaryStatusIndicator from './CanaryStatusIndicator'; // Import the mocked version

// --- Test Suite ---
describe('Layout Component', () => {

  const childText = 'Page Content';
  const mockUser = { username: 'testuser' };
  const mockCanarySuccessData = { canary_last_updated: '2025-04-01' };
  const mockCanaryError = new Error('Failed to fetch canary');

  // Assign the mocked useSWR (Jest automatically replaces the import)
  const mockedUseSWR = useSWR;

  beforeEach(() => {
    mockLogout.mockClear();
    CanaryStatusIndicator.mockClear();
    // Clear the SWR mock directly
    if (jest.isMockFunction(mockedUseSWR)) {
        mockedUseSWR.mockClear();
    }
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });

    // Default mock for useSWR (successful state)
    if (jest.isMockFunction(mockedUseSWR)) {
        mockedUseSWR.mockReturnValue({
            data: mockCanarySuccessData,
            error: undefined,
            isLoading: false,
            isValidating: false,
            mutate: jest.fn(),
        });
    }

    // Re-apply the mock implementation for CanaryStatusIndicator for each test
    const mockImplementationForTest = ({ lastUpdated, isLoading, error, className }) => (
        <div data-testid="canary-indicator" data-loading={String(isLoading)} data-error={String(!!error)} data-lastupdated={lastUpdated ?? ''} className={className}>
            Mock Canary (Implemented in Test)
        </div>
    );
    // No casting needed for the component mock either
    if (jest.isMockFunction(CanaryStatusIndicator)) {
        CanaryStatusIndicator.mockImplementation(mockImplementationForTest);
    }
  });

  test('renders header, footer, and children', () => {
    render(<Layout>{childText}</Layout>);

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Main Navigation' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent(childText);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    expect(screen.getByText(/© Shadow Market/)).toBeInTheDocument();
    expect(screen.getByTestId('canary-indicator')).toBeInTheDocument();
    expect(screen.getByText('Mock Canary (Implemented in Test)')).toBeInTheDocument();

    // Check the SWR hook was called with the CORRECT key
    expect(mockedUseSWR).toHaveBeenCalledWith('canaryData', expect.any(Function), expect.any(Object)); // Check key, fetcher, and options object
  });

  test('renders main loading spinner when auth isLoading is true', () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: true });
    render(<Layout>{childText}</Layout>);

    const main = screen.getByRole('main');
    const mainSpinner = within(main).getByTestId('loading-spinner');
    expect(mainSpinner).toHaveTextContent(/Loading application.../i);
    expect(screen.queryByText(childText)).not.toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  test('renders Login and Register links when logged out', () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);

    expect(screen.getByRole('link', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Register' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Profile' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Logout' })).not.toBeInTheDocument();
    expect(mockedUseSWR).toHaveBeenCalled();
  });

  test('renders Profile, Orders, Wallet, and Logout links when logged in', () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);

    expect(screen.getByRole('link', { name: 'Profile' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Orders' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wallet' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Register' })).not.toBeInTheDocument();
    expect(mockedUseSWR).toHaveBeenCalled();
  });

  test('calls logout function from context when Logout button is clicked', async () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);

    const logoutButton = screen.getByRole('button', { name: 'Logout' });
    await userEvent.click(logoutButton);

    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  test('renders CanaryStatusIndicator with correct props on successful fetch', () => {
    // useSWR mock defaults to success state in beforeEach
    render(<Layout>{childText}</Layout>);

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        lastUpdated: mockCanarySuccessData.canary_last_updated,
        isLoading: false,
        error: undefined,
      }),
      expect.anything() // Context argument
    );

    const indicator = screen.getByTestId('canary-indicator');
    expect(indicator).toHaveAttribute('data-loading', 'false');
    expect(indicator).toHaveAttribute('data-error', 'false');
    expect(indicator).toHaveAttribute('data-lastupdated', mockCanarySuccessData.canary_last_updated);
  });

  test('renders CanaryStatusIndicator with correct props while loading', () => {
    // Override the SWR mock for this test
    if (jest.isMockFunction(mockedUseSWR)) {
        mockedUseSWR.mockReturnValue({
            data: undefined,
            error: undefined,
            isLoading: true, // Simulate loading state
            isValidating: true,
            mutate: jest.fn(),
        });
    }

    render(<Layout>{childText}</Layout>);

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        lastUpdated: undefined,
        isLoading: true,
        error: undefined,
      }),
      expect.anything()
    );

    const indicator = screen.getByTestId('canary-indicator');
    expect(indicator).toHaveAttribute('data-loading', 'true');
    expect(indicator).toHaveAttribute('data-error', 'false');
    expect(indicator).toHaveAttribute('data-lastupdated', '');
  });

  test('renders CanaryStatusIndicator with correct props on fetch error', () => {
     // Override the SWR mock for this test
    if (jest.isMockFunction(mockedUseSWR)) {
         mockedUseSWR.mockReturnValue({
            data: undefined,
            error: mockCanaryError, // Simulate error state
            isLoading: false,
            isValidating: false,
            mutate: jest.fn(),
        });
    }

    render(<Layout>{childText}</Layout>);

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        lastUpdated: undefined,
        isLoading: false,
        error: mockCanaryError,
      }),
      expect.anything()
    );

    const indicator = screen.getByTestId('canary-indicator');
    expect(indicator).toHaveAttribute('data-loading', 'false');
    expect(indicator).toHaveAttribute('data-error', 'true');
    expect(indicator).toHaveAttribute('data-lastupdated', '');
  });

});