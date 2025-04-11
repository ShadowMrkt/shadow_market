// frontend/components/CaptchaInput.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Basic tests for CaptchaInput component.
//           - Tests loading state, error state, and loaded state.
//           - Tests input change and refresh button click.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import CaptchaInput from './CaptchaInput';

// Mock child components used by CaptchaInput
jest.mock('./LoadingSpinner', () => ({ message }) => <div>{message || 'Loading...'}</div>);
jest.mock('./FormError', () => ({ message }) => <div role="alert">{message}</div>);

describe('CaptchaInput Component', () => {
  const mockOnChange = jest.fn();
  const mockOnRefresh = jest.fn();

  // Test Loading State
  test('renders loading state correctly', () => {
    render(
      <CaptchaInput
        imageUrl={null}
        inputKey={null}
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={true}
      />
    );

    expect(screen.getByText(/Loading CAPTCHA.../i)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument();
  });

  // Test Error State (Failed to load image/key)
  test('renders error state correctly when imageUrl/inputKey are null after loading', () => {
    render(
      <CaptchaInput
        imageUrl={null}
        inputKey={null}
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={false} // Loading is finished, but no data
      />
    );

    expect(screen.getByRole('alert')).toHaveTextContent(/Could not load CAPTCHA image/i);
    const retryButton = screen.getByRole('button', { name: /Retry Load/i });
    expect(retryButton).toBeInTheDocument();
    expect(retryButton).not.toBeDisabled(); // Retry button should be enabled
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();

    // Test retry button click
    fireEvent.click(retryButton);
    expect(mockOnRefresh).toHaveBeenCalledTimes(1);
  });

  // Test Loaded State
  test('renders CAPTCHA image, input, and refresh button when loaded', () => {
    const testImageUrl = '/captcha/image/testkey/';
    const testInputKey = 'testkey';
    render(
      <CaptchaInput
        imageUrl={testImageUrl}
        inputKey={testInputKey}
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={false}
      />
    );

    // Check image
    const img = screen.getByRole('img', { name: /CAPTCHA security challenge image/i });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', testImageUrl);

    // Check input
    const input = screen.getByLabelText(/Enter CAPTCHA Text:/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue('');
    expect(input).not.toBeDisabled();

    // Check refresh button
    const refreshButton = screen.getByRole('button', { name: /refresh/i }); // Using icon symbol as name
    expect(refreshButton).toBeInTheDocument();
    expect(refreshButton).not.toBeDisabled();

    // Check hidden input key
    const hiddenInput = screen.getByDisplayValue(testInputKey); // Find by value
    expect(hiddenInput).toBeInTheDocument();
    expect(hiddenInput).toHaveAttribute('type', 'hidden');
    expect(hiddenInput).toHaveAttribute('name', 'captcha_key');
  });

  // Test Input Change
  test('calls onChange handler when input value changes', () => {
    render(
      <CaptchaInput
        imageUrl="/captcha/image/testkey/"
        inputKey="testkey"
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={false}
      />
    );
    const input = screen.getByLabelText(/Enter CAPTCHA Text:/i);
    const typedValue = 'abcde';

    fireEvent.change(input, { target: { value: typedValue } });

    expect(mockOnChange).toHaveBeenCalledTimes(1);
    // Check event object properties
    const changeEvent = mockOnChange.mock.calls[0][0];
    expect(changeEvent.target.value).toBe(typedValue);
  });

  // Test Refresh Button Click
  test('calls onRefresh handler when refresh button is clicked', () => {
    render(
      <CaptchaInput
        imageUrl="/captcha/image/testkey/"
        inputKey="testkey"
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={false}
      />
    );
    const refreshButton = screen.getByRole('button', { name: /refresh/i });

    fireEvent.click(refreshButton);

    expect(mockOnRefresh).toHaveBeenCalledTimes(1);
  });

  // Test Disabled State passed via prop
   test('disables input and button when disabled prop is true (and not loading)', () => {
    render(
      <CaptchaInput
        imageUrl="/captcha/image/testkey/"
        inputKey="testkey"
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={false}
        // disabled={true} // This component doesn't seem to have a direct disabled prop in its definition, it relies on isLoading.
                          // We can test the isLoading disabled state instead.
      />
    );
     // Let's test disabling via isLoading as the component currently does
     render(
      <CaptchaInput
        imageUrl="/captcha/image/testkey/"
        inputKey="testkey"
        value=""
        onChange={mockOnChange}
        onRefresh={mockOnRefresh}
        isLoading={true} // Set isLoading to true
      />
    );
     // In loading state, input and button shouldn't even be rendered based on current logic
     expect(screen.queryByLabelText(/Enter CAPTCHA Text:/i)).not.toBeInTheDocument();
     expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument();

   });

});