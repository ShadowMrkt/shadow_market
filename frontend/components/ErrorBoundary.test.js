// frontend/components/ErrorBoundary.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for ErrorBoundary component.
//           - Tests rendering children normally.
//           - Tests catching errors and rendering fallback UI.
//           - Tests console error logging.
//           - Tests retry button functionality (mocking reload).
//           - Tests conditional display of error details based on NODE_ENV.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import ErrorBoundary from './ErrorBoundary'; // Adjust path as needed

// Helper component that throws an error when instructed
const ProblemChild = ({ shouldThrow = false }) => {
  if (shouldThrow) {
    throw new Error('Test error from ProblemChild');
  }
  return <div>Child content is okay</div>;
};

// Spy on console.error (and silence it during tests)
let consoleErrorSpy;
beforeAll(() => {
  consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {}); // Silence console.error
});
afterAll(() => {
  consoleErrorSpy.mockRestore(); // Restore original console.error
});

// Mock window.location.reload
const originalLocation = window.location;
beforeAll(() => {
  delete window.location;
  window.location = { ...originalLocation, reload: jest.fn() };
});
afterAll(() => {
  window.location = originalLocation; // Restore original location object
});


describe('ErrorBoundary Component', () => {

  beforeEach(() => {
    // Reset mocks before each test
    consoleErrorSpy.mockClear();
    window.location.reload.mockClear();
    // Reset NODE_ENV if modified in a test (Jest usually defaults to 'test')
    process.env.NODE_ENV = 'test';
  });

  test('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <ProblemChild />
      </ErrorBoundary>
    );
    expect(screen.getByText('Child content is okay')).toBeInTheDocument();
    // Fallback UI should not be visible
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/Oops! Something Went Wrong/i)).not.toBeInTheDocument();
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  test('catches error from child and renders fallback UI', () => {
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    // Check for fallback UI elements
    expect(screen.getByRole('alert')).toBeInTheDocument(); // Fallback container has role="alert"
    expect(screen.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toBeInTheDocument();
    expect(screen.getByText(/An unexpected error occurred/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Refresh Page/i })).toBeInTheDocument();

    // Check that original children are not rendered
    expect(screen.queryByText('Child content is okay')).not.toBeInTheDocument();
  });

  test('logs the error and errorInfo to console when error occurs', () => {
     render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    // Expect console.error to have been called (silenced by mock, but call count tracked)
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1);
    // Check the arguments passed to console.error
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "ErrorBoundary caught an error:",
      expect.any(Error), // The error object itself
      expect.objectContaining({
        componentStack: expect.any(String), // Check for component stack info
      })
    );
     expect(consoleErrorSpy.mock.calls[0][1].message).toBe('Test error from ProblemChild');
  });

  test('calls window.location.reload when retry button is clicked', async () => {
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    const retryButton = screen.getByRole('button', { name: /Refresh Page/i });
    await userEvent.click(retryButton);

    expect(window.location.reload).toHaveBeenCalledTimes(1);
  });

  test('shows error details in development environment', () => {
    process.env.NODE_ENV = 'development'; // Set NODE_ENV for this test
     render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    // Check if details element is present
    const detailsElement = screen.getByText('Error Details (Development Only)').closest('details');
    expect(detailsElement).toBeInTheDocument();

    // Optional: Check if details are initially closed or open based on component design
    // Optional: Click the summary to open and check for error content within the <pre> tag
    // const summary = screen.getByText('Error Details (Development Only)');
    // await userEvent.click(summary); // Open details
    // expect(screen.getByText(/Test error from ProblemChild/i)).toBeInTheDocument(); // Check error message visible
    // expect(screen.getByText(/Component Stack:/i)).toBeInTheDocument(); // Check stack visible
  });

  test('does NOT show error details in production environment', () => {
    process.env.NODE_ENV = 'production'; // Set NODE_ENV for this test
     render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    // Details should not be rendered
    expect(screen.queryByText('Error Details (Development Only)')).not.toBeInTheDocument();
    expect(screen.queryByText(/Component Stack:/i)).not.toBeInTheDocument();
    // Fallback UI should still be present
    expect(screen.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toBeInTheDocument();
  });

});