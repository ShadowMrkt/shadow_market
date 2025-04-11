// frontend/components/PaginationControls.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 2 - Added tests for click handlers and disabled states.
// 2025-04-09: Rev 1 - Initial creation. Basic rendering and null rendering tests.

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import PaginationControls from './PaginationControls'; // Adjust path as needed

// Mock CSS Modules (assuming Jest is configured, e.g., with identity-obj-proxy)
// jest.mock('./PaginationControls.module.css', () => ({
//   paginationControls: 'paginationControls',
//   pageButton: 'pageButton',
//   pageInfo: 'pageInfo',
// }));

describe('PaginationControls Component', () => {
  const mockOnPrevious = jest.fn();
  const mockOnNext = jest.fn();

  const defaultProps = {
    currentPage: 3, // Start on a middle page
    totalPages: 5,
    totalCount: 45,
    onPrevious: mockOnPrevious,
    onNext: mockOnNext,
    hasPrevious: true, // Assume has previous by default
    hasNext: true,     // Assume has next by default
    isLoading: false,
  };

  beforeEach(() => {
    // Reset mocks before each test
    jest.clearAllMocks();
  });

  test('renders correctly with standard props', () => {
    render(<PaginationControls {...defaultProps} />);

    expect(screen.getByRole('navigation', { name: /Pagination/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeEnabled();
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages} (${defaultProps.totalCount} items)`)).toBeInTheDocument();
  });

  test('renders null if totalPages is 1 or less', () => {
    const { rerender } = render(<PaginationControls {...defaultProps} totalPages={1} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

    rerender(<PaginationControls {...defaultProps} totalPages={0} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();

     rerender(<PaginationControls {...defaultProps} totalPages={null} />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

   test('displays correct page info without totalCount', () => {
    render(<PaginationControls {...defaultProps} totalCount={0} />);
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages}`)).toBeInTheDocument();
    expect(screen.queryByText(/\(.*\)/)).not.toBeInTheDocument();
  });

   test('displays correct page info with totalCount', () => {
    render(<PaginationControls {...defaultProps} />);
    expect(screen.getByText(`Page ${defaultProps.currentPage} of ${defaultProps.totalPages} (${defaultProps.totalCount} items)`)).toBeInTheDocument();
  });

  // --- NEW: Click Handler Tests ---
  test('calls onPrevious when Previous button is clicked', async () => {
    render(<PaginationControls {...defaultProps} />);
    const prevButton = screen.getByRole('button', { name: /Go to Previous Page/i });
    await userEvent.click(prevButton);
    expect(mockOnPrevious).toHaveBeenCalledTimes(1);
    expect(mockOnNext).not.toHaveBeenCalled();
  });

  test('calls onNext when Next button is clicked', async () => {
    render(<PaginationControls {...defaultProps} />);
    const nextButton = screen.getByRole('button', { name: /Go to Next Page/i });
    await userEvent.click(nextButton);
    expect(mockOnNext).toHaveBeenCalledTimes(1);
    expect(mockOnPrevious).not.toHaveBeenCalled();
  });

  // --- NEW: Disabled State Tests ---
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

  test('does not call handlers when buttons are disabled', async () => {
    // Test disabled Previous button
    render(<PaginationControls {...defaultProps} hasPrevious={false} />);
    const prevButton = screen.getByRole('button', { name: /Go to Previous Page/i });
    await userEvent.click(prevButton);
    expect(mockOnPrevious).not.toHaveBeenCalled();

     // Test disabled Next button
    render(<PaginationControls {...defaultProps} hasNext={false} />); // Rerender with different props
    const nextButton = screen.getByRole('button', { name: /Go to Next Page/i });
    await userEvent.click(nextButton);
    expect(mockOnNext).not.toHaveBeenCalled();
  });

  // --- NEW: Accessibility Test (Optional but good) ---
   test('has correct aria-labels on navigation and buttons', () => {
    render(<PaginationControls {...defaultProps} />);
    expect(screen.getByRole('navigation', { name: /Pagination/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Previous Page/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Go to Next Page/i })).toBeInTheDocument();
  });

});