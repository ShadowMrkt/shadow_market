// frontend/components/PaginationControls.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 3 - Fixed multiple elements error in 'does not call handlers when buttons are disabled' test by using rerender instead of a second render call. Added explicit disabled checks before clicking.
// 2025-04-09: Rev 2 - Added tests for click handlers and disabled states.
// 2025-04-09: Rev 1 - Initial creation. Basic rendering and null rendering tests.

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import PaginationControls from './PaginationControls'; // Adjust path as needed

// Mock CSS Modules if needed (ensure Jest config handles this, e.g., identity-obj-proxy)
// jest.mock('./PaginationControls.module.css', () => ({ ... }));

describe('PaginationControls Component', () => {
  const mockOnPrevious = jest.fn();
  const mockOnNext = jest.fn();

  const defaultProps = {
    currentPage: 3,
    totalPages: 5,
    totalCount: 45,
    onPrevious: mockOnPrevious,
    onNext: mockOnNext,
    hasPrevious: true,
    hasNext: true,
    isLoading: false,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders correctly with standard props', () => {
    render(<PaginationControls {...defaultProps} />);
    expect(screen.getByRole('navigation', { name: /Pagination/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeEnabled();
    // Check full text content for specificity
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages} (${defaultProps.totalCount} items)`)).toBeInTheDocument();
  });

  test('renders null if totalPages is 1 or less', () => {
    const { rerender } = render(<PaginationControls {...defaultProps} totalPages={1} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

    rerender(<PaginationControls {...defaultProps} totalPages={0} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

    // Explicitly test null case if necessary
    rerender(<PaginationControls {...defaultProps} totalPages={null} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  test('displays correct page info without totalCount', () => {
    render(<PaginationControls {...defaultProps} totalCount={0} />);
    // Check only the part without the count
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages}`)).toBeInTheDocument();
    // Ensure the count part isn't there
    expect(screen.queryByText(/\(\d+\s*items\)/)).not.toBeInTheDocument();
  });

  test('displays correct page info with totalCount', () => {
    render(<PaginationControls {...defaultProps} />);
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages} (${defaultProps.totalCount} items)`)).toBeInTheDocument();
  });

  test('calls onPrevious when Previous button is clicked', async () => {
    const user = userEvent.setup();
    render(<PaginationControls {...defaultProps} />);
    const prevButton = screen.getByRole('button', { name: /Go to Previous Page/i });
    await user.click(prevButton);
    expect(mockOnPrevious).toHaveBeenCalledTimes(1);
    expect(mockOnNext).not.toHaveBeenCalled();
  });

  test('calls onNext when Next button is clicked', async () => {
    const user = userEvent.setup();
    render(<PaginationControls {...defaultProps} />);
    const nextButton = screen.getByRole('button', { name: /Go to Next Page/i });
    await user.click(nextButton);
    expect(mockOnNext).toHaveBeenCalledTimes(1);
    expect(mockOnPrevious).not.toHaveBeenCalled();
  });

  test('disables Previous button when hasPrevious is false', () => {
    render(<PaginationControls {...defaultProps} hasPrevious={false} />);
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeDisabled();
  });

  test('disables Next button when hasNext is false', () => {
    render(<PaginationControls {...defaultProps} hasNext={false} />);
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeDisabled();
  });

  test('disables both buttons when isLoading is true', () => {
    render(<PaginationControls {...defaultProps} isLoading={true} />);
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeDisabled();
  });

  // <<< REV 3: Use rerender instead of second render call >>>
  test('does not call handlers when buttons are disabled', async () => {
    const user = userEvent.setup();

    // Test disabled Previous button
    // Capture rerender from the *initial* render
    const { rerender } = render(<PaginationControls {...defaultProps} hasPrevious={false} />);
    const prevButton = screen.getByRole('button', { name: /Go to Previous Page/i });
    expect(prevButton).toBeDisabled(); // Check it's disabled first
    await user.click(prevButton); // Attempt click
    expect(mockOnPrevious).not.toHaveBeenCalled(); // Verify handler wasn't called

    // Test disabled Next button using rerender
    // Update props of the *existing* component instance
    rerender(<PaginationControls {...defaultProps} hasNext={false} />);
    const nextButton = screen.getByRole('button', { name: /Go to Next Page/i });
    expect(nextButton).toBeDisabled(); // Check it's disabled after rerender
    await user.click(nextButton); // Attempt click
    expect(mockOnNext).not.toHaveBeenCalled(); // Verify handler wasn't called
  });

  test('has correct aria-labels on navigation and buttons', () => {
    render(<PaginationControls {...defaultProps} />);
    expect(screen.getByRole('navigation', { name: /Pagination/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeInTheDocument();
  });

});