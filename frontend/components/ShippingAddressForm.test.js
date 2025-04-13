// frontend/components/ShippingAddressForm.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 3 - Corrected the usage of rerender in the onChange test.
//                      - Used the rerender function obtained from the initial render call instead of calling the helper again.
// 2025-04-13 (Gemini): Rev 2 - Switched onChange test from fireEvent to userEvent.
//                      - Implemented rerender to simulate parent state update for controlled component.
//                      - Changed assertion to check final input value instead of event object value.
// 2025-04-09: Rev 1 - Initial creation. Basic tests for ShippingAddressForm component.

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import ShippingAddressForm from './ShippingAddressForm';

describe('ShippingAddressForm Component', () => {
  const mockOnChange = jest.fn();
  const initialFormData = {
    recipient_name: 'Test User',
    street_address: '123 Main St',
    address_line_2: 'Apt 4B',
    city: 'Anytown',
    state_province_region: 'CA',
    postal_code: '90210',
    country: 'USA',
    phone_number: '555-1234',
  };

  // Define defaultProps outside helper for use in rerender
  const defaultProps = {
    formData: initialFormData,
    onChange: mockOnChange,
    disabled: false,
  };

  // Helper function to render the component with props
  // Returns the result of render() which includes rerender
  const renderForm = (props = {}) => {
    const currentProps = { ...defaultProps, ...props }; // Merge initial/passed props
    return render(<ShippingAddressForm {...currentProps} />);
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset defaultProps formData before each test if needed, though usually handled by test isolation
    defaultProps.formData = { ...initialFormData };
  });

  // Test rendering of all fields
  test('renders all input fields with initial values', () => {
    renderForm();
    expect(screen.getByLabelText(/Full Name/i)).toHaveValue(initialFormData.recipient_name);
    // ... other initial value checks ...
    expect(screen.getByLabelText(/Street Address/i)).toHaveValue(initialFormData.street_address);
    expect(screen.getByLabelText(/Address Line 2/i)).toHaveValue(initialFormData.address_line_2);
    expect(screen.getByLabelText(/City/i)).toHaveValue(initialFormData.city);
    expect(screen.getByLabelText(/State\/Province\/Region/i)).toHaveValue(initialFormData.state_province_region);
    expect(screen.getByLabelText(/Postal Code/i)).toHaveValue(initialFormData.postal_code);
    expect(screen.getByLabelText(/Country/i)).toHaveValue(initialFormData.country);
    expect(screen.getByLabelText(/Phone Number/i)).toHaveValue(initialFormData.phone_number);
  });

  // <<< REV 3: Corrected rerender usage >>>
  test('calls onChange handler when an input value changes', async () => {
    const user = userEvent.setup();
    // Capture rerender from the *initial* render call using initial props
    const { rerender } = renderForm({ formData: initialFormData }); // Ensure fresh initial state
    const nameInput = screen.getByLabelText(/Full Name/i);
    const newName = 'New Test User';

    // Simulate user clearing the field and typing a new value
    await user.clear(nameInput);
    await user.type(nameInput, newName);

    // 1. Check that the onChange handler was called
    expect(mockOnChange).toHaveBeenCalled();

    // 2. Simulate the parent component updating state by re-rendering with new formData
    //    Use the rerender function from the initial render.
    const updatedFormData = { ...initialFormData, recipient_name: newName };
    rerender(<ShippingAddressForm {...defaultProps} formData={updatedFormData} />); // Pass *all* necessary props

    // 3. Check if the input field displays the new value *after* the rerender
    expect(nameInput).toHaveValue(newName);
  });

  // Test disabled state
  test('disables all input fields when disabled prop is true', () => {
    renderForm({ disabled: true });
    expect(screen.getByLabelText(/Full Name/i)).toBeDisabled();
    // ... (rest of disabled checks remain the same) ...
    expect(screen.getByLabelText(/Street Address/i)).toBeDisabled();
    expect(screen.getByLabelText(/Address Line 2/i)).toBeDisabled();
    expect(screen.getByLabelText(/City/i)).toBeDisabled();
    expect(screen.getByLabelText(/State\/Province\/Region/i)).toBeDisabled();
    expect(screen.getByLabelText(/Postal Code/i)).toBeDisabled();
    expect(screen.getByLabelText(/Country/i)).toBeDisabled();
    expect(screen.getByLabelText(/Phone Number/i)).toBeDisabled();
  });

  // Test required fields
  test('has required attribute on necessary fields', () => {
    renderForm();
    expect(screen.getByLabelText(/Full Name/i)).toBeRequired();
    expect(screen.getByLabelText(/Street Address/i)).toBeRequired();
    expect(screen.getByLabelText(/City/i)).toBeRequired();
    expect(screen.getByLabelText(/Postal Code/i)).toBeRequired();
    expect(screen.getByLabelText(/Country/i)).toBeRequired();
    // Optional fields
    expect(screen.getByLabelText(/Address Line 2/i)).not.toBeRequired();
    expect(screen.getByLabelText(/State\/Province\/Region/i)).not.toBeRequired();
    expect(screen.getByLabelText(/Phone Number/i)).not.toBeRequired();
  });
});