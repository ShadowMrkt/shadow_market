// frontend/components/Layout.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for Layout component.
//           - Mocks dependencies (AuthContext, API, SWR, Next components, child components).
//           - Tests basic structure rendering (header, footer, children).
//           - Tests conditional rendering of nav links based on auth state.
//           - Tests logout button functionality.
//           - Tests passing props to CanaryStatusIndicator based on mocked API/SWR state.

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import Layout from './Layout'; // Adjust path as needed

// --- Mock Dependencies ---

// Mock next/head
jest.mock('next/head', () => {
  return {
    __esModule: true,
    default: ({ children }) => <>{children}</>, // Render children to check content
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
  isLoading: false, // Default to auth check complete
};
jest.mock('../context/AuthContext', () => ({ // Adjust path
  useAuth: () => mockAuthContextValue,
}));
const setMockAuthContext = (value) => {
  mockAuthContextValue = { ...mockAuthContextValue, ...value };
};

// Mock utils/api (specifically getCanaryData used by Layout's SWR)
const mockGetCanaryData = jest.fn();
jest.mock('../utils/api', () => ({ // Adjust path
  getCanaryData: mockGetCanaryData,
}));

// Mock child components
jest.mock('./LoadingSpinner', () => ({ message, size }) => <div data-testid="loading-spinner">{message}</div>);
// Mock CanaryStatusIndicator to check props passed to it
const mockCanaryStatusIndicator = jest.fn(({ lastUpdated, isLoading, error, className }) => (
    <div data-testid="canary-indicator" data-loading={isLoading} data-error={!!error} data-lastupdated={lastUpdated} className={className}>
      Mock Canary
    </div>
));
jest.mock('./CanaryStatusIndicator', () => mockCanaryStatusIndicator);

// --- Test Suite ---
describe('Layout Component', () => {

  const childText = 'Page Content';
  const mockUser = { username: 'testuser' };
  const mockCanarySuccessData = { canary_last_updated: '2025-04-01' };

  beforeEach(() => {
    // Reset mocks and context state
    jest.clearAllMocks();
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });
    mockGetCanaryData.mockResolvedValue(mockCanarySuccessData); // Default SWR success
  });

  test('renders header, footer, and children', async () => {
    render(<Layout>{childText}</Layout>);

    // Wait for potential async operations like SWR
    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled());

    expect(screen.getByRole('banner')).toBeInTheDocument(); // Header
    expect(screen.getByRole('navigation', { name: 'Main Navigation' })).toBeInTheDocument(); // Nav
    expect(screen.getByRole('main')).toHaveTextContent(childText); // Main content with children
    expect(screen.getByRole('contentinfo')).toBeInTheDocument(); // Footer
    expect(screen.getByText(/© Shadow Market/)).toBeInTheDocument(); // Footer text
  });

  test('renders main loading spinner when auth isLoading is true', () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: true });
    render(<Layout>{childText}</Layout>);

    expect(screen.getByTestId('loading-spinner')).toHaveTextContent(/Loading application.../i);
    // Children should likely not be rendered in this loading state
    expect(screen.queryByText(childText)).not.toBeInTheDocument();
    // Header/Footer might still render depending on design choice
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  test('renders Login and Register links when logged out', async () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);
    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled()); // Wait for SWR

    expect(screen.getByRole('link', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Register' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Profile' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Logout' })).not.toBeInTheDocument();
  });

  test('renders Profile, Orders, Wallet, and Logout links when logged in', async () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);
    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled()); // Wait for SWR

    expect(screen.getByRole('link', { name: 'Profile' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Orders' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wallet' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Register' })).not.toBeInTheDocument();
  });

  test('calls logout function from context when Logout button is clicked', async () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    render(<Layout>{childText}</Layout>);
    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled()); // Wait for SWR

    const logoutButton = screen.getByRole('button', { name: 'Logout' });
    await userEvent.click(logoutButton);

    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  test('renders CanaryStatusIndicator with correct props on successful fetch', async () => {
    mockGetCanaryData.mockResolvedValue(mockCanarySuccessData);
    render(<Layout>{childText}</Layout>);

    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled());

    // Check the props passed to the mocked CanaryStatusIndicator
    expect(mockCanaryStatusIndicator).toHaveBeenCalledWith(
      expect.objectContaining({
        lastUpdated: mockCanarySuccessData.canary_last_updated,
        isLoading: false, // Should be false after successful fetch
        error: null,
      }),
      expect.anything() // Second argument is ref context, ignore here
    );
    expect(screen.getByTestId('canary-indicator')).toBeInTheDocument();
  });

   test('renders CanaryStatusIndicator with correct props while loading', async () => {
    // Simulate SWR loading state (no data, no error, isValidating true - tricky to mock directly, let's mock API pending)
    mockGetCanaryData.mockImplementation(() => new Promise(() => {})); // Promise that never resolves
    render(<Layout>{childText}</Layout>);

     // Need to wait for the indicator to render even in loading state
     await screen.findByTestId('canary-indicator');

    // Check the props passed to the mocked CanaryStatusIndicator
    expect(mockCanaryStatusIndicator).toHaveBeenCalledWith(
      expect.objectContaining({
        lastUpdated: undefined, // No data yet
        isLoading: true, // Should be true initially
        error: null,
      }),
      expect.anything()
    );
  });

   test('renders CanaryStatusIndicator with correct props on fetch error', async () => {
    const fetchError = new Error('Failed to fetch canary');
    mockGetCanaryData.mockRejectedValue(fetchError);
    render(<Layout>{childText}</Layout>);

    await waitFor(() => expect(mockGetCanaryData).toHaveBeenCalled());

    // Check the props passed to the mocked CanaryStatusIndicator
    expect(mockCanaryStatusIndicator).toHaveBeenCalledWith(
      expect.objectContaining({
        lastUpdated: undefined,
        isLoading: false, // Loading finished
        error: fetchError, // Error object passed
      }),
      expect.anything()
    );
     expect(screen.getByTestId('canary-indicator')).toBeInTheDocument();
     expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-error', 'true');
  });

});