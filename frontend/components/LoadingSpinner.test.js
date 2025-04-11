// frontend/components/LoadingSpinner.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial test suite creation for LoadingSpinner component.
//             - Covers basic rendering, default/custom props (size, message, className),
//             - and accessibility attributes. Assumes CSS Modules are handled by Jest config.

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom'; // Import jest-dom matchers

import LoadingSpinner from './LoadingSpinner';

// Mocking CSS Modules: Jest needs to be configured to handle CSS module imports.
// Usually done via moduleNameMapper in jest.config.js mapping *.module.css to 'identity-obj-proxy'.
// This mock assumes styles.spinnerContainer = 'spinnerContainer', etc.

describe('LoadingSpinner', () => {
  test('renders without crashing', () => {
    render(<LoadingSpinner />);
    // Check if the main container with the status role is rendered
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  test('renders with default props', () => {
    render(<LoadingSpinner />);
    const container = screen.getByRole('status');
    const spinnerElement = container.querySelector('div'); // Get the inner spinner div

    // Check default accessibility role
    expect(container).toBeInTheDocument();

    // Check for default class (assuming identity-obj-proxy)
    expect(container).toHaveClass('spinnerContainer');

    // Check if the inner spinner element is present and has its base class and aria-hidden
    expect(spinnerElement).toBeInTheDocument();
    expect(spinnerElement).toHaveClass('spinnerBase');
    expect(spinnerElement).toHaveAttribute('aria-hidden', 'true');

    // Check default size style (width and height)
    expect(spinnerElement).toHaveStyle('width: 1.5em');
    expect(spinnerElement).toHaveStyle('height: 1.5em');
    // Checking the complex calc for borderWidth might be brittle, focus on width/height
    // expect(spinnerElement).toHaveStyle('borderWidth: max(2px, calc(1.5em / 8))');

    // Check that the message span is not rendered
    expect(screen.queryByText(/.+/)).not.toBeInTheDocument(); // Check no text content exists
    // Or more specifically check for the message element class
    expect(container.querySelector('.messageText')).not.toBeInTheDocument();
  });

  test('renders with custom size', () => {
    const customSize = '32px';
    render(<LoadingSpinner size={customSize} />);
    const spinnerElement = screen.getByRole('status').querySelector('div');

    expect(spinnerElement).toHaveStyle(`width: ${customSize}`);
    expect(spinnerElement).toHaveStyle(`height: ${customSize}`);
    // Optionally check the calculated border width if consistency is critical
    expect(spinnerElement).toHaveStyle(`borderWidth: max(2px, calc(${customSize} / 8))`);
  });

  test('renders with message', () => {
    const testMessage = 'Loading data...';
    render(<LoadingSpinner message={testMessage} />);

    // Check if the message text is rendered
    expect(screen.getByText(testMessage)).toBeInTheDocument();

    // Check if the message span has the correct class
    expect(screen.getByText(testMessage)).toHaveClass('messageText');
  });

  test('does not render message when message prop is null or empty', () => {
    const { rerender } = render(<LoadingSpinner message={null} />);
    // Check specifically for the message span element using its class
    expect(screen.queryByText(/.+/)).not.toBeInTheDocument();
    expect(screen.getByRole('status').querySelector('.messageText')).not.toBeInTheDocument();


    rerender(<LoadingSpinner message="" />);
    expect(screen.queryByText(/.+/)).not.toBeInTheDocument();
    expect(screen.getByRole('status').querySelector('.messageText')).not.toBeInTheDocument();
  });

  test('applies additional className to the container', () => {
    const additionalClass = 'my-custom-spinner-class';
    render(<LoadingSpinner className={additionalClass} />);
    const container = screen.getByRole('status');

    expect(container).toHaveClass('spinnerContainer'); // Default module class
    expect(container).toHaveClass(additionalClass);   // Additional class
  });

  test('has correct accessibility attributes', () => {
    render(<LoadingSpinner message="Processing" />);
    const container = screen.getByRole('status');
    const spinnerElement = container.querySelector('div'); // Inner spinner

    // Container should have role="status" (implicitly checked by getByRole)
    expect(container).toBeInTheDocument();

    // Decorative spinner element should be hidden from screen readers
    expect(spinnerElement).toHaveAttribute('aria-hidden', 'true');

    // Message, when present, should be announced as part of the status
    expect(screen.getByText('Processing')).toBeInTheDocument();
  });
});