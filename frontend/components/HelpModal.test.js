// frontend/components/HelpModal.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 3 - Removed incorrect assertion checking capturedModalProps when isOpen is false, as the mock component is never rendered in that case. Relied on queryByTestId check.
// 2025-04-09: Rev 2 - Updated tests to match refactored HelpModal using standard Modal component.
//                      - Mocked the standard Modal component.
//                      - Tests now check props passed to Modal and rendering of children.
// 2025-04-09: Rev 1 - Initial creation. Tests for original HelpModal implementation.

import React from 'react';
import { render, screen } from '@testing-library/react';
// import userEvent from '@testing-library/user-event'; // No user events needed now
import '@testing-library/jest-dom';
import HelpModal from './HelpModal'; // Adjust path as needed

// --- Mock the standard Modal component ---
let capturedModalProps = {};
// Use a named function for better snapshot/debug output if needed
jest.mock('./Modal', () => {
  const MockModal = (props) => {
      capturedModalProps = { ...props }; // Store props passed to Modal
      // Only render children if isOpen is true, mimicking Modal behavior
      return props.isOpen ? <div data-testid="mock-modal">{props.children}</div> : null;
  };
  return MockModal; // Return the mock component function
});
// --------------------------------------

describe('HelpModal Component (Refactored)', () => {
  const mockOnClose = jest.fn();

  beforeEach(() => {
    // Reset mocks and captured props before each test
    mockOnClose.mockClear();
    capturedModalProps = {}; // Reset captured props
  });

  // <<< REV 3: Removed incorrect assertion >>>
  test('does not render Modal when isOpen is false', () => {
    render(<HelpModal isOpen={false} onClose={mockOnClose} />);

    // Check that our mock modal content isn't rendered (primary check)
    expect(screen.queryByTestId('mock-modal')).not.toBeInTheDocument();

    // REMOVED: expect(capturedModalProps.isOpen).toBe(false);
    // This assertion was incorrect because if HelpModal returns null when isOpen is false,
    // the mocked Modal component is never rendered, and capturedModalProps is never set.
    // The queryByTestId check above is sufficient to confirm the Modal isn't visible/rendered.
  });

  test('renders standard Modal with correct props and children when isOpen is true', () => {
    render(<HelpModal isOpen={true} onClose={mockOnClose} />);

    // Check that the standard Modal was rendered (via our mock)
    expect(screen.getByTestId('mock-modal')).toBeInTheDocument();

    // Check props passed to the standard Modal component
    expect(capturedModalProps.isOpen).toBe(true);
    expect(capturedModalProps.onClose).toBe(mockOnClose);
    expect(capturedModalProps.title).toBe('Quick Help & Hints');

    // Check that the children (help content) were rendered inside the mock modal
    expect(screen.getByText(/Sign Up:/i)).toBeInTheDocument();
    expect(screen.getByText(/Login:/i)).toBeInTheDocument();
    expect(screen.getByText(/Payments:/i)).toBeInTheDocument();
    expect(screen.getByText(/For more detailed instructions/i)).toBeInTheDocument();
  });

});