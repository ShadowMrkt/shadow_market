// frontend/components/Modal.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for Modal component.
//           - Tests conditional rendering based on isOpen.
//           - Tests onClose handler via button, overlay, and Escape key.
//           - Tests that clicking inside modal content does not close it.
//           - Tests basic ARIA attributes.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import Modal from './Modal'; // Adjust path as needed

// Mock CSS Modules
// jest.mock('./Modal.module.css', () => ({
//   overlay: 'overlay',
//   modal: 'modal',
//   closeButton: 'closeButton',
//   title: 'title',
// }));
// Note: Using identity-obj-proxy configured in jest.config.js is preferred

describe('Modal Component', () => {
  const mockOnClose = jest.fn();
  const modalTitle = 'Test Modal Title';
  const modalContent = 'This is the modal content.';
  const modalRootId = 'modal-root'; // For portal testing if used

  // Helper to create a div for React Portals if Modal uses it
  // Run this setup once before all tests in the suite if portals are used
  // beforeAll(() => {
  //   const portalRoot = document.createElement('div');
  //   portalRoot.setAttribute('id', modalRootId);
  //   document.body.appendChild(portalRoot);
  // });

  beforeEach(() => {
    // Reset mocks before each test
    mockOnClose.mockClear();
    // Clear body if portal cleanup is needed
    // document.body.innerHTML = '';
    // document.body.appendChild(portalRoot);
  });

  test('does not render when isOpen is false', () => {
    render(
      <Modal isOpen={false} onClose={mockOnClose} title={modalTitle}>
        <div>{modalContent}</div>
      </Modal>
    );
    // Check that the dialog role is not present
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // Check that content is not present
    expect(screen.queryByText(modalContent)).not.toBeInTheDocument();
  });

  test('renders correctly when isOpen is true', () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose} title={modalTitle}>
        <div data-testid="modal-children">{modalContent}</div>
      </Modal>
    );

    // Check modal container with role="dialog"
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    // Check title rendering and association
    const titleElement = screen.getByRole('heading', { name: modalTitle, level: 2 });
    expect(titleElement).toBeInTheDocument();
    expect(dialog).toHaveAttribute('aria-labelledby', titleElement.id);

    // Check children content
    expect(screen.getByTestId('modal-children')).toHaveTextContent(modalContent);

    // Check close button
    expect(screen.getByRole('button', { name: /Close Modal/i })).toBeInTheDocument();
  });

   test('renders correctly without a title', () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose}>
        <div>{modalContent}</div>
      </Modal>
    );
     const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).not.toHaveAttribute('aria-labelledby'); // Should not be labelled if no title
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument(); // No h2 title
    expect(screen.getByText(modalContent)).toBeInTheDocument();
  });

  test('calls onClose when close button is clicked', async () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose} title={modalTitle}>
        <div>{modalContent}</div>
      </Modal>
    );
    const closeButton = screen.getByRole('button', { name: /Close Modal/i });
    await userEvent.click(closeButton);
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  test('calls onClose when overlay is clicked', async () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose} title={modalTitle}>
        <div>{modalContent}</div>
      </Modal>
    );
    // The overlay is the element with role="dialog" in this setup
    const overlay = screen.getByRole('dialog');
    await userEvent.click(overlay); // Click directly on the overlay div
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  test('does NOT call onClose when clicking inside modal content', async () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose} title={modalTitle}>
        <div data-testid="modal-content-area">
            {modalContent}
            <button>Inner Button</button>
        </div>
      </Modal>
    );
    // Click specifically on the content area (or an element within it)
    await userEvent.click(screen.getByTestId('modal-content-area'));
    await userEvent.click(screen.getByRole('button', {name: /Inner Button/i}));
    expect(mockOnClose).not.toHaveBeenCalled();
  });

  test('calls onClose when Escape key is pressed', () => {
    render(
      <Modal isOpen={true} onClose={mockOnClose} title={modalTitle}>
        <div>{modalContent}</div>
      </Modal>
    );
    // Focus an element inside first perhaps, though Escape listener is usually global
    // screen.getByRole('dialog').focus(); // The mock modal div might need tabindex="-1" to be focusable

    // Simulate Escape key press on the document body
    fireEvent.keyDown(document.body, { key: 'Escape', code: 'Escape', keyCode: 27, charCode: 27 });

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

   test('does not call onClose on Escape key press when not open', () => {
    render(
      <Modal isOpen={false} onClose={mockOnClose} title={modalTitle}>
        <div>{modalContent}</div>
      </Modal>
    );
    fireEvent.keyDown(document.body, { key: 'Escape', code: 'Escape', keyCode: 27, charCode: 27 });
    expect(mockOnClose).not.toHaveBeenCalled();
  });

  // Note: Testing the actual focus trap behavior requires more complex setup,
  // often involving simulating Tab key presses and verifying document.activeElement.
  // This is generally better handled with E2E tests or dedicated focus trap libraries.
});