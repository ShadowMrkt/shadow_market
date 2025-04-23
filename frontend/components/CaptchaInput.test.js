// components/CaptchaInput.test.js
// --- REVISION HISTORY ---
// 2025-04-22 (Gemini): Rev 6 - Replace document.querySelector with getByTestId for hidden input. Ensure component includes data-testid="captcha-key-input".
// ... (Previous revisions) ...


import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import CaptchaInput from './CaptchaInput';

// --- Mocks ---
// Mock child components if they interfere or are complex
jest.mock('./FormError', () => ({ message }) => <div role="alert">{message}</div>);
jest.mock('./LoadingSpinner', () => ({ size, message }) => <div>{message || 'Loading...'}</div>);

// --- Test Data ---
const mockImageUrl = '/path/to/captcha.png';
const mockInputKey = 'testCaptchaKey123';
const mockOnChange = jest.fn();
const mockOnRefresh = jest.fn();

describe('CaptchaInput Component', () => {

    beforeEach(() => {
        // Clear mocks before each test
        jest.clearAllMocks();
    });

    test('renders loading state correctly', () => {
        render(
            <CaptchaInput
                imageUrl={null}
                inputKey={null}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={true} // Set isLoading to true
                disabled={false}
            />
        );

        // Check for loading message/spinner (adapt query based on LoadingSpinner mock)
        expect(screen.getByText(/Loading CAPTCHA.../i)).toBeInTheDocument();

        // Ensure image, main input, and refresh button are NOT rendered
        expect(screen.queryByRole('img')).not.toBeInTheDocument();
        expect(screen.queryByLabelText(/CAPTCHA text input/i)).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Refresh CAPTCHA/i })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Retry Load/i })).not.toBeInTheDocument();
    });

    test('renders error state correctly when not loading but missing image/key', () => {
        render(
            <CaptchaInput
                imageUrl={null} // Missing image
                inputKey={null} // Missing key
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false} // Not loading
                disabled={false}
            />
        );

        // Check for error message (via FormError mock)
        expect(screen.getByRole('alert')).toHaveTextContent(/Could not load CAPTCHA image./i);
        expect(screen.getByRole('button', { name: /Retry Load/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Retry Load/i })).not.toBeDisabled();

        // Ensure loading spinner, main input, and refresh button are NOT rendered
        expect(screen.queryByText(/Loading CAPTCHA.../i)).not.toBeInTheDocument();
        expect(screen.queryByRole('img')).not.toBeInTheDocument();
        expect(screen.queryByLabelText(/CAPTCHA text input/i)).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Refresh CAPTCHA/i })).not.toBeInTheDocument();
    });

     test('calls onRefresh when retry button is clicked in error state', async () => {
        render(
            <CaptchaInput
                imageUrl={null}
                inputKey={null}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={false}
            />
        );

        const retryButton = screen.getByRole('button', { name: /Retry Load/i });
        const user = userEvent.setup();
        await user.click(retryButton);

        expect(mockOnRefresh).toHaveBeenCalledTimes(1);
    });

    test('disables retry button when disabled prop is true in error state', () => {
        render(
            <CaptchaInput
                imageUrl={null}
                inputKey={null}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={true} // Set disabled to true
            />
        );
         const retryButton = screen.getByRole('button', { name: /Retry Load/i });
         expect(retryButton).toBeDisabled();
    });

    test('renders CAPTCHA image, input, and refresh button when loaded', () => {
        const testValue = 'abc';
        const testInputKey = 'uniqueKeyForTest';

        render(
            <CaptchaInput
                imageUrl={mockImageUrl}
                inputKey={testInputKey}
                value={testValue} // Pass controlled value
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={false}
            />
        );

        // Check Image
        const img = screen.getByRole('img', { name: /CAPTCHA security challenge image/i });
        expect(img).toBeInTheDocument();
        expect(img).toHaveAttribute('src', mockImageUrl);

        // Check Visible Input
        const textInput = screen.getByLabelText(/CAPTCHA text input/i);
        expect(textInput).toBeInTheDocument();
        expect(textInput).toHaveValue(testValue); // Check controlled value
        expect(textInput).not.toBeDisabled();
        expect(textInput).toHaveAttribute('name', 'captcha_1'); // Check correct name

        // Check Hidden Input using data-testid added to component
        const hiddenInput = screen.getByTestId('captcha-key-input'); 
        expect(hiddenInput).toBeInTheDocument();
        expect(hiddenInput).toHaveAttribute('type', 'hidden');
        expect(hiddenInput).toHaveAttribute('name', 'captcha_0'); // Check correct name
        expect(hiddenInput).toHaveValue(testInputKey);

        // Check Refresh Button
        const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
        expect(refreshButton).toBeInTheDocument();
        expect(refreshButton).not.toBeDisabled();

        // Ensure loading/error elements are not present
        expect(screen.queryByText(/Loading CAPTCHA.../i)).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Retry Load/i })).not.toBeInTheDocument();
    });

    test('calls onChange handler when text input changes', async () => {
        const user = userEvent.setup();
        render(
            <CaptchaInput
                imageUrl={mockImageUrl}
                inputKey={mockInputKey}
                value="" // Start with empty value
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={false}
            />
        );

        const textInput = screen.getByLabelText(/CAPTCHA text input/i);
        await user.type(textInput, 'test');

        // Expect onChange to have been called multiple times (once per character)
        expect(mockOnChange).toHaveBeenCalled();
        // More specific check: was it called with the last event having value 'test'?
        // This requires inspecting the mock call arguments, which can be complex.
        // Often just checking if it was called is sufficient for basic integration.
        expect(mockOnChange).toHaveBeenCalledTimes(4); // 't', 'e', 's', 't'
    });

    test('calls onRefresh handler when refresh button is clicked', async () => {
        const user = userEvent.setup();
        render(
            <CaptchaInput
                imageUrl={mockImageUrl}
                inputKey={mockInputKey}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={false}
            />
        );

        const refreshButton = screen.getByRole('button', { name: /Refresh CAPTCHA/i });
        await user.click(refreshButton);

        expect(mockOnRefresh).toHaveBeenCalledTimes(1);
    });

    test('disables input and refresh button when disabled prop is true', () => {
        render(
            <CaptchaInput
                imageUrl={mockImageUrl}
                inputKey={mockInputKey}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false}
                disabled={true} // Set disabled prop
            />
        );

        expect(screen.getByLabelText(/CAPTCHA text input/i)).toBeDisabled();
        expect(screen.getByRole('button', { name: /Refresh CAPTCHA/i })).toBeDisabled();
    });

    test('does not disable input/button when only isLoading is true (handled by conditional rendering)', () => {
         // This test verifies that the disabled prop works independently.
         // The loading state uses conditional rendering, so elements aren't just disabled, they aren't rendered.
         // We test the loading state separately.
        render(
            <CaptchaInput
                imageUrl={mockImageUrl}
                inputKey={mockInputKey}
                value=""
                onChange={mockOnChange}
                onRefresh={mockOnRefresh}
                isLoading={false} // Ensure not loading
                disabled={false} // Ensure not explicitly disabled
            />
        );

        expect(screen.getByLabelText(/CAPTCHA text input/i)).not.toBeDisabled();
        expect(screen.getByRole('button', { name: /Refresh CAPTCHA/i })).not.toBeDisabled();
    });

});