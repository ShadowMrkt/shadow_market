// frontend/components/HelpModal.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 2 - Updated tests to match refactored HelpModal using standard Modal component.
//           - Mocked the standard Modal component.
//           - Tests now check props passed to Modal and rendering of children.
// 2025-04-09: Rev 1 - Initial creation. Tests for original HelpModal implementation.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import HelpModal from './HelpModal'; // Adjust path as needed

// --- Mock the standard Modal component ---
// We capture the props passed to it and render its children
let capturedModalProps = {};
jest.mock('./Modal', () => (props) => {
  capturedModalProps = props; // Store props passed to Modal
  // Only render children if isOpen is true, mimicking Modal behavior
  return props.isOpen ? <div data-testid="mock-modal">{props.children}</div> : null;
});
// --------------------------------------

describe('HelpModal Component (Refactored)', () => {
  const mockOnClose = jest.fn();

  beforeEach(() => {
    // Reset mocks and captured props before each test
    mockOnClose.mockClear();
    capturedModalProps = {};
  });

  test('does not render Modal when isOpen is false', () => {
    const { container } = render(<HelpModal isOpen={false} onClose={mockOnClose} />);
    // Check that our mock modal content isn't rendered
    expect(screen.queryByTestId('mock-modal')).not.toBeInTheDocument();
    // Check that Modal component wasn't effectively rendered (or received isOpen=false)
    expect(capturedModalProps.isOpen).toBe(false);
  });

  test('renders standard Modal with correct props and children when isOpen is true', () => {
    render(<HelpModal isOpen={true} onClose={mockOnClose} />);

    // Check that the standard Modal was rendered (via our mock)
    expect(screen.getByTestId('mock-modal')).toBeInTheDocument();

    // Check props passed to the standard Modal component
    expect(capturedModalProps.isOpen).toBe(true);
    expect(capturedModalProps.onClose).toBe(mockOnClose); // Check if the correct function was passed
    expect(capturedModalProps.title).toBe('Quick Help & Hints');

    // Check that the children (help content) were rendered inside the mock modal
    expect(screen.getByText(/Sign Up:/i)).toBeInTheDocument();
    expect(screen.getByText(/Login:/i)).toBeInTheDocument();
    expect(screen.getByText(/Payments:/i)).toBeInTheDocument();
    expect(screen.getByText(/For more detailed instructions/i)).toBeInTheDocument();
  });

  // Note: We no longer test overlay/button clicks directly on HelpModal,
  // as that functionality is now handled and tested within the standard Modal component itself.
  // We trust that if HelpModal passes the correct `onClose` prop to Modal,
  // the standard Modal will invoke it correctly.

});