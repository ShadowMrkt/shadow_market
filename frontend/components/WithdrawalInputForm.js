// frontend/components/WithdrawalInputForm.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Refactored to use global CSS form classes, adjusted amount input type.
//           - Removed inline styles object.
//           - Applied .form-group, .form-label, .form-input, .form-select, .form-help-text, .button, .button-primary, .disabled classes from globals.css.
//           - Changed amount input to type="text" with inputMode="decimal".
//           - Removed fallback for SUPPORTED_CURRENCIES import.
//           - Added TODO for displaying balance/min withdrawal.
//           - Added revision history block.

import React from 'react';
import { SUPPORTED_CURRENCIES, CURRENCY_SYMBOLS } from '../utils/constants'; // Ensure constants are imported
import LoadingSpinner from './LoadingSpinner';

/**
 * Renders the input form for Step 1 of the withdrawal process (currency, amount, address).
 * Relies on global CSS classes for styling (.form-group, .form-label, etc.).
 *
 * @param {object} props - Component props.
 * @param {string} props.currency - Currently selected currency code.
 * @param {function} props.onCurrencyChange - Handler for currency select change.
 * @param {string} props.amount - Current amount input value.
 * @param {function} props.onAmountChange - Handler for amount input change.
 * @param {string} props.address - Current destination address input value.
 * @param {function} props.onAddressChange - Handler for address input change.
 * @param {function} props.onSubmit - Handler function from parent for form submission (triggers prepareWithdrawal).
 * @param {boolean} props.isLoading - Whether the prepare action is currently loading.
 * @param {boolean} props.disabled - Whether the form should be generally disabled (e.g., missing PGP auth).
 * @returns {React.ReactElement} The withdrawal input form component.
 */
const WithdrawalInputForm = ({
    currency, onCurrencyChange,
    amount, onAmountChange,
    address, onAddressChange,
    onSubmit, // Renamed for clarity, passed from parent WalletPage
    isLoading,
    disabled // General disabled state (e.g., missing PGP auth)
}) => {

    // Handler for the internal form submission that calls the parent's handler
    const handleInternalSubmit = (e) => {
        e.preventDefault(); // Prevent default browser form submission
        if (onSubmit) {
            onSubmit(e); // Call the handler passed from the parent page (handlePrepareWithdrawal)
        } else {
            console.warn("WithdrawalInputForm: No onSubmit prop provided.");
        }
    };

    const isButtonDisabled = isLoading || disabled;

    return (
        // Internal form element handles submission
        <form onSubmit={handleInternalSubmit}>
            {/* Currency Selection */}
            <div className="form-group">
                <label htmlFor="withdrawCurrency" className="form-label">Currency</label>
                <select
                    id="withdrawCurrency" // Unique ID
                    name="currency"
                    value={currency}
                    onChange={onCurrencyChange}
                    required
                    className="form-select" // Use global style
                    disabled={isLoading || disabled}
                    aria-describedby="withdrawCurrencyHelp"
                >
                    {/* Ensure SUPPORTED_CURRENCIES is correctly imported and populated */}
                    {(SUPPORTED_CURRENCIES).map(curr => (
                        <option key={curr} value={curr}>{curr} ({CURRENCY_SYMBOLS[curr] || curr})</option>
                    ))}
                </select>
                <small id="withdrawCurrencyHelp" className="form-help-text">Select the currency to withdraw.</small>
            </div>

            {/* Amount Input */}
            <div className="form-group">
                <label htmlFor="withdrawAmount" className="form-label">Amount</label>
                <input
                    // Use type="text" with inputMode="decimal" for better cross-browser decimal handling
                    type="text"
                    inputMode="decimal"
                    pattern="[0-9]*\.?[0-9]*" // Basic pattern for decimals
                    id="withdrawAmount" // Unique ID
                    name="amount"
                    value={amount}
                    onChange={onAmountChange}
                    required
                    className="form-input" // Use global style
                    placeholder="Enter amount to withdraw"
                    // step="any" // Not needed for type="text"
                    // min="0" // Basic validation, more specific check in parent/backend
                    disabled={isLoading || disabled}
                    aria-describedby="withdrawAmountHelp"
                />
                <small id="withdrawAmountHelp" className="form-help-text">Enter the exact amount. Check available balance & minimum withdrawal limits.</small>
                {/* TODO: Display available balance and minimum withdrawal dynamically */}
            </div>

            {/* Destination Address Input */}
            <div className="form-group">
                <label htmlFor="destinationAddress" className="form-label">Destination Address</label>
                <input
                    type="text"
                    id="destinationAddress" // Keep ID consistent if needed elsewhere
                    name="address" // Use 'address' to match parent state key
                    value={address}
                    onChange={onAddressChange}
                    required
                    className="form-input font-monospace" // Use global style + monospace
                    placeholder={`Enter valid ${currency} address`}
                    disabled={isLoading || disabled}
                    aria-describedby="destinationAddressHelp"
                />
                 <small id="destinationAddressHelp" className="form-help-text">Ensure the address is correct for {currency}. Withdrawals are irreversible.</small>
            </div>

            {/* Submit Button */}
            <button
                type="submit"
                disabled={isButtonDisabled}
                // Apply global button classes, including 'disabled' state class
                className={`button button-primary w-100 mt-3 ${isButtonDisabled ? 'disabled' : ''}`}
                title={disabled && !isLoading ? "PGP Authenticated Session Required" : ""} // Explain disabled reason
            >
                {isLoading ? <LoadingSpinner size="1em" /> : 'Prepare Withdrawal'}
            </button>
        </form>
    );
};

export default WithdrawalInputForm;