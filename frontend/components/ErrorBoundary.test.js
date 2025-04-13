// frontend/components/ErrorBoundary.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 3 - Changed consoleErrorSpy assertion from toHaveBeenCalledTimes(1) to check for the specific call using toHaveBeenCalledWith, acknowledging React/JSDOM may log other errors.
// 2025-04-13 (Gemini): Rev 2 - Added debug logging to inspect consoleErrorSpy calls.
// 2025-04-09: Rev 1 - Initial creation. Tests for ErrorBoundary component.

import React from 'react';
import { render, screen } from '@testing-library/react'; // Removed fireEvent
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
    // @ts-ignore
  window.location = { ...originalLocation, reload: jest.fn() };
});
afterAll(() => {
    // @ts-ignore
  window.location = originalLocation; // Restore original location object
});


describe('ErrorBoundary Component', () => {

  beforeEach(() => {
    // Reset mocks before each test
    consoleErrorSpy.mockClear();
    // @ts-ignore
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
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toBeInTheDocument();
    expect(screen.getByText(/An unexpected error occurred/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Refresh Page/i })).toBeInTheDocument();
    expect(screen.queryByText('Child content is okay')).not.toBeInTheDocument();
  });

  // <<< REV 3: Changed assertion from times(1) to ensure the specific call happened >>>
  test('logs the error and errorInfo to console when error occurs', () => {
     render(
       <ErrorBoundary>
         <ProblemChild shouldThrow={true} />
       </ErrorBoundary>
     );

     // Check that *our specific log message* was called, ignoring other potential React/JSDOM errors.
     expect(consoleErrorSpy).toHaveBeenCalledWith(
       "ErrorBoundary caught an error:",
       expect.any(Error), // The error object itself
       expect.objectContaining({
         componentStack: expect.any(String), // Check for component stack info
       })
     );

     // Find the specific call matching our pattern and check the error message
     const ourCallArgs = consoleErrorSpy.mock.calls.find(call => call[0] === "ErrorBoundary caught an error:");
     expect(ourCallArgs).toBeDefined(); // Ensure our call actually happened
     expect(ourCallArgs[1].message).toBe('Test error from ProblemChild'); // Check the error message

     // REMOVED: expect(consoleErrorSpy).toHaveBeenCalledTimes(1); // This was unreliable
   });


  test('calls window.location.reload when retry button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );

    const retryButton = screen.getByRole('button', { name: /Refresh Page/i });
    await user.click(retryButton);

    // @ts-ignore
    expect(window.location.reload).toHaveBeenCalledTimes(1);
  });

  test('shows error details in development environment', () => {
    process.env.NODE_ENV = 'development'; // Set NODE_ENV for this test
    render(
      <ErrorBoundary>
        <ProblemChild shouldThrow={true} />
      </ErrorBoundary>
    );
    const detailsElement = screen.getByText('Error Details (Development Only)').closest('details');
    expect(detailsElement).toBeInTheDocument();
  });

  test('does NOT show error details in production environment', () => {
    process.env.NODE_ENV = 'production'; // Set NODE_ENV for this test
     render(
       <ErrorBoundary>
         <ProblemChild shouldThrow={true} />
       </ErrorBoundary>
     );
    expect(screen.queryByText('Error Details (Development Only)')).not.toBeInTheDocument();
    expect(screen.queryByText(/Component Stack:/i)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Oops! Something Went Wrong/i })).toBeInTheDocument();
  });

});