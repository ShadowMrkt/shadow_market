// frontend/components/SearchComponent.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 2 - Added tests for form submission and navigation logic.
// 2025-04-09: Rev 1 - Initial creation. Tests for SearchComponent.

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react'; // Added waitFor
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import SearchComponent from './SearchComponent'; // Adjust path as needed

// Mock next/router
const mockRouterPush = jest.fn();
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: mockRouterPush,
    // Other router properties if needed by the component
  }),
}));

// Mock CSS Modules (if needed and not handled globally by Jest config)
// jest.mock('./SearchComponent.module.css', () => ({ ... }));

describe('SearchComponent', () => {

  beforeEach(() => {
    // Reset mocks before each test
    mockRouterPush.mockClear();
  });

  test('renders search input and submit button', () => {
    render(<SearchComponent />);
    expect(screen.getByRole('search')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Search products.../i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Submit search/i })).toBeInTheDocument();
  });

  test('updates input value on user typing', async () => {
    render(<SearchComponent />);
    const searchInput = screen.getByPlaceholderText(/Search products.../i);
    const testQuery = 'test search';
    await userEvent.type(searchInput, testQuery);
    expect(searchInput).toHaveValue(testQuery);
  });

  // --- NEW: Form Submission Tests ---

  test('calls router.push with correct URL on form submit with non-empty query', async () => {
    render(<SearchComponent />);
    const searchInput = screen.getByPlaceholderText(/Search products.../i);
    const submitButton = screen.getByRole('button', { name: /Submit search/i });
    const testQuery = 'My Product Query';
    const encodedQuery = encodeURIComponent(testQuery);

    await userEvent.type(searchInput, testQuery);
    await userEvent.click(submitButton);

    // router.push should be called once
    expect(mockRouterPush).toHaveBeenCalledTimes(1);
    // Check the argument passed to router.push
    expect(mockRouterPush).toHaveBeenCalledWith(`/search?q=${encodedQuery}`);
  });

   test('calls router.push with correct URL when pressing Enter in input', async () => {
    render(<SearchComponent />);
    const searchInput = screen.getByPlaceholderText(/Search products.../i);
    const testQuery = 'Enter Key Test';
    const encodedQuery = encodeURIComponent(testQuery);

    await userEvent.type(searchInput, testQuery);
    // Simulate pressing Enter key within the input field
    await fireEvent.submit(screen.getByRole('search')); // Submitting the form works like pressing Enter

    expect(mockRouterPush).toHaveBeenCalledTimes(1);
    expect(mockRouterPush).toHaveBeenCalledWith(`/search?q=${encodedQuery}`);
  });

  test('does not call router.push on form submit with empty query', async () => {
    render(<SearchComponent />);
    const submitButton = screen.getByRole('button', { name: /Submit search/i });

    // Submit with empty input
    await userEvent.click(submitButton);

    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  test('does not call router.push on form submit with whitespace-only query', async () => {
    render(<SearchComponent />);
    const searchInput = screen.getByPlaceholderText(/Search products.../i);
    const submitButton = screen.getByRole('button', { name: /Submit search/i });

    // Type only spaces
    await userEvent.type(searchInput, '   ');
    await userEvent.click(submitButton);

    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  // --- Accessibility Test ---
   test('has correct accessibility attributes', () => {
    render(<SearchComponent />);
    expect(screen.getByRole('search')).toBeInTheDocument();
    // Check input accessible name via aria-label (since visual label is hidden)
    expect(screen.getByRole('searchbox', { name: /Search products/i })).toBeInTheDocument();
    // Check button accessible name
    expect(screen.getByRole('button', { name: /Submit search/i })).toBeInTheDocument();
  });

});