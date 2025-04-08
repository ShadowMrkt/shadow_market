// frontend/components/ui/Button.test.js
// --- REVISION HISTORY ---
// 2025-04-08: Rev 1 - Initial creation. Basic tests for Button component.
//           - Test rendering with children.
//           - Test onClick handler invocation.
//           - Test disabled state.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom'; // Ensure matchers are available

// Import the component to test
// Adjust the path if your Button component is exported differently or located elsewhere
import Button from './Button';

// Describe block groups related tests for the Button component
describe('Button Component', () => {
  // Test case 1: Ensure the button renders with the correct text
  test('renders button with children text', () => {
    const buttonText = 'Click Me';
    render(<Button>{buttonText}</Button>);

    // Find the button element by its role and accessible name (text content)
    // Using a case-insensitive regex (/i) makes the match more robust
    const buttonElement = screen.getByRole('button', { name: /click me/i });

    // Assert that the button element is present in the document
    expect(buttonElement).toBeInTheDocument();
    // Assert that the button has the correct text content
    expect(buttonElement).toHaveTextContent(buttonText);
  });

  // Test case 2: Ensure the onClick handler is called when the button is clicked
  test('calls onClick handler when clicked', () => {
    // Create a mock function using jest.fn() to track calls
    const handleClick = jest.fn();

    render(<Button onClick={handleClick}>Clickable</Button>);

    // Find the button element
    const buttonElement = screen.getByRole('button', { name: /clickable/i });

    // Simulate a user click event on the button
    fireEvent.click(buttonElement);

    // Assert that the mock function was called exactly once
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  // Test case 3: Ensure the button is disabled when the disabled prop is true
  test('is disabled when disabled prop is true', () => {
    const handleClick = jest.fn(); // Also test that onClick is not called
    render(
      <Button onClick={handleClick} disabled={true}>
        Disabled Button
      </Button>
    );

    // Find the button element
    const buttonElement = screen.getByRole('button', { name: /disabled button/i });

    // Assert that the button element has the disabled attribute
    expect(buttonElement).toBeDisabled();

    // Attempt to click the disabled button
    fireEvent.click(buttonElement);

    // Assert that the onClick handler was NOT called
    expect(handleClick).not.toHaveBeenCalled();
  });

  // --- Add more tests based on Button.js specific features ---
  // Example: Testing variants or custom class names
  // test('applies correct class for variant prop', () => {
  //   render(<Button variant="primary">Primary Action</Button>);
  //   const buttonElement = screen.getByRole('button', { name: /primary action/i });
  //   // NOTE: Replace 'button-primary' with the actual class your component uses!
  //   expect(buttonElement).toHaveClass('button-primary');
  // });

  // Example: Testing if it renders an icon if passed as a prop
  // test('renders icon when icon prop is provided', () => {
  //   const MockIcon = () => <svg data-testid="mock-icon"></svg>;
  //   render(<Button icon={<MockIcon />}>Button With Icon</Button>);
  //   expect(screen.getByTestId('mock-icon')).toBeInTheDocument();
  // });
});