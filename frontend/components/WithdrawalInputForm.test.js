// frontend/components/WithdrawalInputForm.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Basic tests for WithdrawalInputForm component.
//           - Tests rendering, input changes, form submission, and disabled/loading states.

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import WithdrawalInputForm from './WithdrawalInputForm';
import { SUPPORTED_CURRENCIES } from '../utils/constants'; // Import needed constants

// Mock child components
jest.mock('./LoadingSpinner', () => () => <div>Loading...</div>);

// Mock constants if they are not available in the test environment easily
// (Though importing directly is usually better if setup allows)
// jest.mock('../utils/constants', () => ({
//   SUPPORTED_CURRENCIES: ['XMR', 'BTC', 'ETH'],
//   CURRENCY_SYMBOLS: { XMR: 'ɱ', BTC: '₿', ETH: 'Ξ' },
// }));


describe('WithdrawalInputForm Component', () => {
  const mockOnCurrencyChange = jest.fn();
  const mockOnAmountChange = jest.fn();
  const mockOnAddressChange = jest.fn();
  const mockOnSubmit = jest.fn();

  const defaultProps = {
    currency: 'XMR',
    onCurrencyChange: mockOnCurrencyChange,
    amount: '0.5',
    onAmountChange: mockOnAmountChange,
    address: 'monero-address-here',
    onAddressChange: mockOnAddressChange,
    onSubmit: mockOnSubmit,
    isLoading: false,
    disabled: false,
    balances: { // Mock balance data for context if needed (not directly tested here)
        XMR: { available: '1.0', total: '1.0', locked: '0'},
        BTC: { available: '0.1', total: '0.1', locked: '0'},
        ETH: { available: '2.0', total: '2.0', locked: '0'},
    }
  };

  beforeEach(() => {
    // Clear mocks before each test
    jest.clearAllMocks();
  });

  test('renders currency select, amount input, address input, and submit button', () => {
    render(<WithdrawalInputForm {...defaultProps} />);

    // Check select rendering
    const currencySelect = screen.getByLabelText(/Currency/i);
    expect(currencySelect).toBeInTheDocument();
    expect(currencySelect).toHaveValue(defaultProps.currency);
    // Check if options are rendered (example check for one)
    expect(screen.getByRole('option', { name: /XMR/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /BTC/i })).toBeInTheDocument();

    // Check amount input
    expect(screen.getByLabelText(/Amount/i)).toHaveValue(defaultProps.amount);

    // Check address input
    expect(screen.getByLabelText(/Destination Address/i)).toHaveValue(defaultProps.address);

    // Check submit button
    expect(screen.getByRole('button', { name: /Prepare Withdrawal/i })).toBeEnabled();
  });

  test('calls onCurrencyChange when currency is selected', () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    const currencySelect = screen.getByLabelText(/Currency/i);

    fireEvent.change(currencySelect, { target: { value: 'BTC' } });

    expect(mockOnCurrencyChange).toHaveBeenCalledTimes(1);
    const changeEvent = mockOnCurrencyChange.mock.calls[0][0];
    expect(changeEvent.target.value).toBe('BTC');
  });

  test('calls onAmountChange when amount input changes', () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    const amountInput = screen.getByLabelText(/Amount/i);
    const newAmount = '1.23';

    fireEvent.change(amountInput, { target: { value: newAmount } });

    expect(mockOnAmountChange).toHaveBeenCalledTimes(1);
    const changeEvent = mockOnAmountChange.mock.calls[0][0];
    expect(changeEvent.target.value).toBe(newAmount);
  });

  test('calls onAddressChange when address input changes', () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    const addressInput = screen.getByLabelText(/Destination Address/i);
    const newAddress = 'new-btc-address';

    fireEvent.change(addressInput, { target: { value: newAddress } });

    expect(mockOnAddressChange).toHaveBeenCalledTimes(1);
    const changeEvent = mockOnAddressChange.mock.calls[0][0];
    expect(changeEvent.target.value).toBe(newAddress);
  });

  test('calls onSubmit when form is submitted', async () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    const submitButton = screen.getByRole('button', { name: /Prepare Withdrawal/i });

    await userEvent.click(submitButton);

    expect(mockOnSubmit).toHaveBeenCalledTimes(1);
    // Check if preventDefault was likely called (passed the event object)
    expect(mockOnSubmit.mock.calls[0][0]).toBeDefined();
  });

   test('calls onSubmit when Enter key is pressed in an input', async () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    const addressInput = screen.getByLabelText(/Destination Address/i);

    // Simulate pressing Enter in the address input
    await userEvent.type(addressInput, '{enter}');

    expect(mockOnSubmit).toHaveBeenCalledTimes(1);
   });

  test('disables select, inputs, and button when disabled prop is true', () => {
    render(<WithdrawalInputForm {...defaultProps} disabled={true} />);

    expect(screen.getByLabelText(/Currency/i)).toBeDisabled();
    expect(screen.getByLabelText(/Amount/i)).toBeDisabled();
    expect(screen.getByLabelText(/Destination Address/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /Prepare Withdrawal/i })).toBeDisabled();
  });

  test('disables select, inputs, and button, and shows spinner when isLoading prop is true', () => {
    render(<WithdrawalInputForm {...defaultProps} isLoading={true} />);

    expect(screen.getByLabelText(/Currency/i)).toBeDisabled();
    expect(screen.getByLabelText(/Amount/i)).toBeDisabled();
    expect(screen.getByLabelText(/Destination Address/i)).toBeDisabled();

    const submitButton = screen.getByRole('button'); // Find button generically
    expect(submitButton).toBeDisabled();
    // Check if the spinner message is rendered instead of the button text
    expect(screen.getByText(/Loading.../i)).toBeInTheDocument();
    expect(screen.queryByText(/Prepare Withdrawal/i)).not.toBeInTheDocument();
  });

  test('has required attributes on necessary fields', () => {
    render(<WithdrawalInputForm {...defaultProps} />);
    expect(screen.getByLabelText(/Currency/i)).toBeRequired();
    expect(screen.getByLabelText(/Amount/i)).toBeRequired();
    expect(screen.getByLabelText(/Destination Address/i)).toBeRequired();
  });
});