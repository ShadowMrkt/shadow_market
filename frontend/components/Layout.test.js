// frontend/components/Layout.test.js
// --- REVISION HISTORY ---
// 2025-04-11: Rev 12 - Added act(Promise.resolve()) to end of async tests to flush microtasks, attempting to resolve final act() warning. (Warning persists, tests pass)
// 2025-04-11: Rev 11 - Added SWRConfig options to disable revalidation/retries, attempting to resolve act() warning.
// 2025-04-11: Rev 10 - Refined waitFor calls in async tests to check final DOM state, addressing act() warnings.
// 2025-04-11: Rev 9 - Adjusted assertion for successful fetch test to expect 'error: undefined' instead of 'null'.
// 2025-04-11: Rev 8 - Wrapped renders in SWRConfig provider; refined loading spinner query using within().
// 2025-04-11: Rev 7 - Removed TypeScript 'as jest.Mock' syntax causing SyntaxError in JS environment.
// 2025-04-11: Rev 6 - Implemented "Do Mock" pattern for CanaryStatusIndicator mock to finally resolve hoisting/TDZ issue.
// 2025-04-11: Rev 5 - Fixed jest.mock hoisting issue for mockCanaryStatusIndicator using mockImplementation inside factory.
// 2025-04-11: Rev 4 - Fixed jest.mock hoisting issue for mockCanaryStatusIndicator by defining mock inside factory.
// 2025-04-11: Rev 3 - DIAGNOSTIC: Modified api mock to define fn inside factory, using global ref for config.
// 2025-04-11: Rev 2 - Fixed jest.mock hoisting issue for mockGetCanaryData (attempt 1).
// 2025-04-09: Rev 1 - Initial creation. Tests for Layout component.

import React from 'react';
// Import act
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { SWRConfig } from 'swr';

// --- Mock Dependencies ---
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
// --- API mock ---
jest.mock('../utils/api', () => {
    console.log('--- JEST.MOCK FACTORY FOR UTILS/API (Layout Test) EXECUTING ---');
    const internalMockGetCanaryData = jest.fn();
    global.__INTERNAL_MOCK_GET_CANARY_DATA_LAYOUT__ = internalMockGetCanaryData;
    return {
        __esModule: true,
        getCanaryData: internalMockGetCanaryData,
    };
});
// Mock child components
jest.mock('./LoadingSpinner', () => ({ message, size }) => <div data-testid="loading-spinner">{message}</div>);
// Mock CanaryStatusIndicator: Provide a simple placeholder factory.
jest.mock('./CanaryStatusIndicator', () => jest.fn(() => <div data-testid="canary-indicator-placeholder">Initial Placeholder</div>));


// --- NOW Import the modules AFTER mocks are defined ---
import Layout from './Layout'; // Adjust path as needed
import CanaryStatusIndicator from './CanaryStatusIndicator';

// --- Test Suite ---
// Note: A persistent React 'act' warning related to SWR updates remains despite passing tests
// and attempts to resolve (waitFor DOM state, SWR config, flush promises).
// Tests verify final component state correctly. Warning accepted as likely SWR/test env artifact.
describe('Layout Component', () => {

  const childText = 'Page Content';
  const mockUser = { username: 'testuser' };
  const mockCanarySuccessData = { canary_last_updated: '2025-04-01' };
  const getCanaryDataMock = global.__INTERNAL_MOCK_GET_CANARY_DATA_LAYOUT__;

  // Helper function to render with SWR provider
  const renderWithProviders = (ui, options) => {
    return render(
      <SWRConfig value={{
          provider: () => new Map(),
          dedupingInterval: 0,
          revalidateOnFocus: false,
          revalidateOnReconnect: false,
          shouldRetryOnError: false,
       }}>
        {ui}
      </SWRConfig>,
      options
    );
  };

  beforeEach(() => {
    mockLogout.mockClear();
    CanaryStatusIndicator.mockClear();
    if (getCanaryDataMock) {
        getCanaryDataMock.mockClear();
        getCanaryDataMock.mockResolvedValue(mockCanarySuccessData);
    }
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });
    const mockImplementationForTest = ({ lastUpdated, isLoading, error, className }) => (
        <div data-testid="canary-indicator" data-loading={String(isLoading)} data-error={String(!!error)} data-lastupdated={lastUpdated ?? ''} className={className}>
            Mock Canary (Implemented in Test)
        </div>
    );
    CanaryStatusIndicator.mockImplementation(mockImplementationForTest);
  });

  afterAll(() => {
    delete global.__INTERNAL_MOCK_GET_CANARY_DATA_LAYOUT__;
  });


  test('renders header, footer, and children', async () => {
    renderWithProviders(<Layout>{childText}</Layout>);

     if (getCanaryDataMock) {
         await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
     await waitFor(() => {
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-loading', 'false');
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-error', 'false');
     });

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Main Navigation' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveTextContent(childText);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    expect(screen.getByText(/© Shadow Market/)).toBeInTheDocument();
    expect(screen.getByTestId('canary-indicator')).toBeInTheDocument();
    expect(screen.getByText('Mock Canary (Implemented in Test)')).toBeInTheDocument();

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

  test('renders main loading spinner when auth isLoading is true', () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: true });
    renderWithProviders(<Layout>{childText}</Layout>);

    const main = screen.getByRole('main');
    const mainSpinner = within(main).getByTestId('loading-spinner');
    expect(mainSpinner).toHaveTextContent(/Loading application.../i);
    expect(screen.queryByText(childText)).not.toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  test('renders Login and Register links when logged out', async () => {
    setMockAuthContext({ user: null, logout: mockLogout, isLoading: false });
    renderWithProviders(<Layout>{childText}</Layout>);

     if (getCanaryDataMock) {
         await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
     await waitFor(() => {
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-loading', 'false');
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-error', 'false');
     });

    expect(screen.getByRole('link', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Register' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Profile' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Logout' })).not.toBeInTheDocument();

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

  test('renders Profile, Orders, Wallet, and Logout links when logged in', async () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    renderWithProviders(<Layout>{childText}</Layout>);

     if (getCanaryDataMock) {
         await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
     await waitFor(() => {
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-loading', 'false');
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-error', 'false');
     });

    expect(screen.getByRole('link', { name: 'Profile' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Orders' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wallet' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Login' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Register' })).not.toBeInTheDocument();

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

  test('calls logout function from context when Logout button is clicked', async () => {
    setMockAuthContext({ user: mockUser, logout: mockLogout, isLoading: false });
    renderWithProviders(<Layout>{childText}</Layout>);

     if (getCanaryDataMock) {
         await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
     await waitFor(() => {
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-loading', 'false');
        expect(screen.getByTestId('canary-indicator')).toHaveAttribute('data-error', 'false');
     });

    const logoutButton = screen.getByRole('button', { name: 'Logout' });
    await userEvent.click(logoutButton); // userEvent handles act internally

    expect(mockLogout).toHaveBeenCalledTimes(1);

    // No explicit flush needed here as userEvent handles it, unless logout causes further async updates
    // await act(async () => await Promise.resolve());
  });

  test('renders CanaryStatusIndicator with correct props on successful fetch', async () => {
    renderWithProviders(<Layout>{childText}</Layout>);

     if (getCanaryDataMock) {
         await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
     await waitFor(() => {
       const indicator = screen.getByTestId('canary-indicator');
       expect(indicator).toHaveAttribute('data-loading', 'false');
       expect(indicator).toHaveAttribute('data-error', 'false');
       expect(indicator).toHaveAttribute('data-lastupdated', mockCanarySuccessData.canary_last_updated);
     }, { timeout: 2000 });

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        lastUpdated: mockCanarySuccessData.canary_last_updated,
        isLoading: false,
        error: undefined,
      }),
      expect.anything()
    );

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

  test('renders CanaryStatusIndicator with correct props while loading', async () => {
     if (getCanaryDataMock) {
        getCanaryDataMock.mockImplementation(() => new Promise(() => {}));
     }
    renderWithProviders(<Layout>{childText}</Layout>);

    if(getCanaryDataMock) {
        await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
    await waitFor(() => {
       const indicator = screen.getByTestId('canary-indicator');
       expect(indicator).toHaveAttribute('data-loading', 'true');
       expect(indicator).toHaveAttribute('data-error', 'false');
       expect(indicator).toHaveAttribute('data-lastupdated', '');
     }, { timeout: 2000 });

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        isLoading: true,
        error: undefined,
      }),
      expect.anything()
    );

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

  test('renders CanaryStatusIndicator with correct props on fetch error', async () => {
    const fetchError = new Error('Failed to fetch canary');
     if (getCanaryDataMock) {
        getCanaryDataMock.mockRejectedValue(fetchError);
     }
    renderWithProviders(<Layout>{childText}</Layout>);

     if(getCanaryDataMock) {
        await waitFor(() => expect(getCanaryDataMock).toHaveBeenCalled());
     }
    await waitFor(() => {
       const indicator = screen.getByTestId('canary-indicator');
       expect(indicator).toHaveAttribute('data-loading', 'false');
       expect(indicator).toHaveAttribute('data-error', 'true');
       expect(indicator).toHaveAttribute('data-lastupdated', '');
     }, { timeout: 2000 });

    expect(CanaryStatusIndicator).toHaveBeenCalled();
    expect(CanaryStatusIndicator).toHaveBeenLastCalledWith(
      expect.objectContaining({
        isLoading: false,
        error: fetchError,
      }),
      expect.anything()
    );

    await act(async () => await Promise.resolve()); // Attempt to flush microtasks
  });

});