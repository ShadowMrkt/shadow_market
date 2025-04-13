// frontend/components/ShippingAddressForm.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 2 - No code changes needed. Added comments explaining the likely cause of the onChange test failure resides in the test file's assertion logic for controlled components.
// 2025-04-07: Rev 1 - Refactored to use global CSS form classes.
//           - Removed inline styles object.
//           - Applied .form-group, .form-label, .form-input classes from globals.css.
//           - Added revision history block.

import React from 'react';

/**
 * Renders a form section for collecting standard shipping address details.
 * Relies on global CSS classes for styling (.form-group, .form-label, .form-input).
 * This is a controlled component; state logic (value updates) must be handled by the parent component.
 *
 * @param {object} props - Component props.
 * @param {object} props.formData - Object containing the current address values (e.g., { recipient_name: '', street_address: '', ... }). Parent state.
 * @param {function} props.onChange - Function called when any input field changes (passes the event object). Parent uses this to update state.
 * @param {boolean} [props.disabled=false] - Whether all input fields should be disabled.
 * @returns {React.ReactElement} The shipping address form fields.
 */
const ShippingAddressForm = ({ formData = {}, onChange, disabled = false }) => {
    // Provide default empty strings in formData lookup to avoid uncontrolled component warnings if parent sends null/undefined
    const getValue = (fieldName) => formData[fieldName] ?? '';

    // --- Note for Test File (`ShippingAddressForm.test.js`) ---
    // The test failure "calls onChange handler..." (Expected: "New Test User" / Received: "Test User")
    // is likely due to how the test asserts on the event object for this controlled component.
    // The component correctly calls the `onChange` prop passed by the parent.
    // The test should:
    // 1. Verify `mockOnChange` was called.
    // 2. Optionally, verify the arguments passed *to* the mock if needed (the event object itself).
    // 3. To verify the *result* of the change, the test needs to ensure the mock parent updates state
    //    correctly and then assert on the input's *displayed value* after re-render, e.g.,
    //    `await waitFor(() => expect(screen.getByLabelText(/Full Name/i)).toHaveValue("New Test User"));`
    // The component code itself is standard and likely does not need changes for this test failure.
    // ----

    return (
        <>
            {/* Use global CSS classes for consistent form styling */}
            <div className="form-group">
                <label htmlFor="recipient_name" className="form-label">Full Name</label>
                <input
                    type="text"
                    name="recipient_name"
                    id="recipient_name"
                    value={getValue('recipient_name')} // Controlled by formData prop
                    onChange={onChange} // Propagated to parent handler
                    required
                    className="form-input"
                    disabled={disabled}
                    autoComplete="name"
                />
            </div>
            <div className="form-group">
                <label htmlFor="street_address" className="form-label">Street Address</label>
                <input
                    type="text"
                    name="street_address"
                    id="street_address"
                    value={getValue('street_address')}
                    onChange={onChange}
                    required
                    className="form-input"
                    disabled={disabled}
                    autoComplete="street-address"
                />
            </div>
            <div className="form-group">
                <label htmlFor="address_line_2" className="form-label">Address Line 2 <span className="text-muted">(Optional)</span></label>
                <input
                    type="text"
                    name="address_line_2"
                    id="address_line_2"
                    value={getValue('address_line_2')}
                    onChange={onChange}
                    className="form-input"
                    disabled={disabled}
                    autoComplete="address-line2"
                />
            </div>
            <div className="form-group">
                <label htmlFor="city" className="form-label">City</label>
                <input
                    type="text"
                    name="city"
                    id="city"
                    value={getValue('city')}
                    onChange={onChange}
                    required
                    className="form-input"
                    disabled={disabled}
                    autoComplete="address-level2"
                />
            </div>
            <div className="form-group">
                <label htmlFor="state_province_region" className="form-label">State/Province/Region <span className="text-muted">(Optional)</span></label>
                <input
                    type="text"
                    name="state_province_region"
                    id="state_province_region"
                    value={getValue('state_province_region')}
                    onChange={onChange}
                    className="form-input"
                    disabled={disabled}
                    autoComplete="address-level1"
                />
            </div>
            <div className="form-group">
                <label htmlFor="postal_code" className="form-label">Postal Code</label>
                <input
                    type="text"
                    name="postal_code"
                    id="postal_code"
                    value={getValue('postal_code')}
                    onChange={onChange}
                    required
                    className="form-input"
                    disabled={disabled}
                    autoComplete="postal-code"
                />
            </div>
            <div className="form-group">
                <label htmlFor="country" className="form-label">Country</label>
                <input
                    type="text"
                    name="country"
                    id="country"
                    value={getValue('country')}
                    onChange={onChange}
                    required
                    className="form-input"
                    disabled={disabled}
                    autoComplete="country-name"
                />
            </div>
            <div className="form-group">
                <label htmlFor="phone_number" className="form-label">Phone Number <span className="text-muted">(Optional)</span></label>
                <input
                    type="tel"
                    name="phone_number"
                    id="phone_number"
                    value={getValue('phone_number')}
                    onChange={onChange}
                    className="form-input"
                    disabled={disabled}
                    autoComplete="tel"
                    placeholder="Optional, for delivery issues"
                />
                 <small className="form-help-text">Consider privacy implications before providing.</small>
            </div>
        </>
    );
};

export default ShippingAddressForm;