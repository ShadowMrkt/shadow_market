// frontend/components/ShippingAddressForm.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Basic tests for ShippingAddressForm component.
//           - Tests rendering of all input fields.
//           - Tests if onChange handler is called correctly.
//           - Tests if fields are disabled correctly.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
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

  // Helper function to render the component with props
  const renderForm = (props = {}) => {
    const defaultProps = {
      formData: initialFormData,
      onChange: mockOnChange,
      disabled: false,
      ...props,
    };
    return render(<ShippingAddressForm {...defaultProps} />);
  };

  // Test rendering of all fields
  test('renders all input fields with initial values', () => {
    renderForm();

    expect(screen.getByLabelText(/Full Name/i)).toHaveValue(initialFormData.recipient_name);
    expect(screen.getByLabelText(/Street Address/i)).toHaveValue(initialFormData.street_address);
    expect(screen.getByLabelText(/Address Line 2/i)).toHaveValue(initialFormData.address_line_2);
    expect(screen.getByLabelText(/City/i)).toHaveValue(initialFormData.city);
    expect(screen.getByLabelText(/State\/Province\/Region/i)).toHaveValue(initialFormData.state_province_region);
    expect(screen.getByLabelText(/Postal Code/i)).toHaveValue(initialFormData.postal_code);
    expect(screen.getByLabelText(/Country/i)).toHaveValue(initialFormData.country);
    expect(screen.getByLabelText(/Phone Number/i)).toHaveValue(initialFormData.phone_number);
  });

  // Test onChange handler
  test('calls onChange handler when an input value changes', () => {
    renderForm();
    const nameInput = screen.getByLabelText(/Full Name/i);
    const newName = 'New Test User';

    fireEvent.change(nameInput, { target: { value: newName, name: 'recipient_name' } });

    expect(mockOnChange).toHaveBeenCalledTimes(1);
    // Check if the event object passed to onChange has the correct target properties
    // Note: We don't check formData state here as it's managed by the parent
    const changeEvent = mockOnChange.mock.calls[0][0];
    expect(changeEvent.target.name).toBe('recipient_name');
    expect(changeEvent.target.value).toBe(newName);
  });

  // Test disabled state
  test('disables all input fields when disabled prop is true', () => {
    renderForm({ disabled: true });

    expect(screen.getByLabelText(/Full Name/i)).toBeDisabled();
    expect(screen.getByLabelText(/Street Address/i)).toBeDisabled();
    expect(screen.getByLabelText(/Address Line 2/i)).toBeDisabled();
    expect(screen.getByLabelText(/City/i)).toBeDisabled();
    expect(screen.getByLabelText(/State\/Province\/Region/i)).toBeDisabled();
    expect(screen.getByLabelText(/Postal Code/i)).toBeDisabled();
    expect(screen.getByLabelText(/Country/i)).toBeDisabled();
    expect(screen.getByLabelText(/Phone Number/i)).toBeDisabled();
  });

  // Test required fields (basic check based on props, actual validation is browser/parent)
  test('has required attribute on necessary fields', () => {
    renderForm();
    expect(screen.getByLabelText(/Full Name/i)).toBeRequired();
    expect(screen.getByLabelText(/Street Address/i)).toBeRequired();
    expect(screen.getByLabelText(/City/i)).toBeRequired();
    expect(screen.getByLabelText(/Postal Code/i)).toBeRequired();
    expect(screen.getByLabelText(/Country/i)).toBeRequired();
    // Optional fields should not be required
    expect(screen.getByLabelText(/Address Line 2/i)).not.toBeRequired();
    expect(screen.getByLabelText(/State\/Province\/Region/i)).not.toBeRequired();
    expect(screen.getByLabelText(/Phone Number/i)).not.toBeRequired();
  });
});