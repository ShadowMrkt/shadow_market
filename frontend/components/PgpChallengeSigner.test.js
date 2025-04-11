// frontend/components/PgpChallengeSigner.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Basic tests for PgpChallengeSigner component.
//           - Tests rendering with/without challenge text.
//           - Tests copy button functionality and notifications (mocked).
//           - Tests signature input change handler.
//           - Tests disabled state.
//           - Tests accessibility attributes.

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import PgpChallengeSigner from './PgpChallengeSigner';

// Mock Notification utility used by the component
const mockNotifications = {
  showSuccessToast: jest.fn(),
  showErrorToast: jest.fn(),
};
jest.mock('../utils/notifications', () => mockNotifications); // Adjust path if needed

// Mock clipboard API
const mockWriteText = jest.fn();
Object.defineProperty(navigator, 'clipboard', {
  value: {
    writeText: mockWriteText,
  },
  writable: true,
});

describe('PgpChallengeSigner Component', () => {
  const mockOnChange = jest.fn();
  const defaultProps = {
    challengeText: '-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nMock Challenge Text',
    signatureValue: '',
    onSignatureChange: mockOnChange,
    username: 'testuser',
    disabled: false,
  };

  beforeEach(() => {
    // Clear mocks before each test
    jest.clearAllMocks();
    // Reset clipboard mock implementation for success by default
    mockWriteText.mockResolvedValue(undefined);
  });

  test('renders instructions, challenge label, and signature label', () => {
    render(<PgpChallengeSigner {...defaultProps} />);

    expect(screen.getByText('Instructions for PGP Signature:')).toBeInTheDocument();
    expect(screen.getByText(defaultProps.challengeLabel || /Challenge Text to Sign:/i)).toBeInTheDocument(); // Use default prop value if needed
    expect(screen.getByText(defaultProps.signatureLabel || /Paste Your PGP Signature Block:/i)).toBeInTheDocument();
    // Check for username mention in instructions
    expect(screen.getByText(`associated with user`, { exact: false })).toHaveTextContent(defaultProps.username);
  });

  test('displays challenge text in code block and enables copy button', () => {
    render(<PgpChallengeSigner {...defaultProps} />);

    const codeBlock = screen.getByText(defaultProps.challengeText, { selector: 'code' });
    expect(codeBlock).toBeInTheDocument();
    expect(codeBlock.closest('pre')).toHaveClass('code-block'); // Check global class

    const copyButton = screen.getByRole('button', { name: /Copy Challenge/i });
    expect(copyButton).toBeInTheDocument();
    expect(copyButton).toBeEnabled();
  });

  test('renders loading state when challengeText is null/empty', () => {
    render(<PgpChallengeSigner {...defaultProps} challengeText={null} />);
    expect(screen.getByText(/Loading challenge.../i)).toBeInTheDocument();
    // Copy button should not be rendered if no text
    expect(screen.queryByRole('button', { name: /Copy Challenge/i })).not.toBeInTheDocument();
  });

  test('calls clipboard writeText and shows success toast on copy click', async () => {
    render(<PgpChallengeSigner {...defaultProps} />);
    const copyButton = screen.getByRole('button', { name: /Copy Challenge/i });

    await userEvent.click(copyButton);

    expect(mockWriteText).toHaveBeenCalledTimes(1);
    expect(mockWriteText).toHaveBeenCalledWith(defaultProps.challengeText);
    // Wait for async toast call
    await waitFor(() => {
       expect(mockNotifications.showSuccessToast).toHaveBeenCalledWith('Challenge text copied to clipboard!');
    });
    expect(mockNotifications.showErrorToast).not.toHaveBeenCalled();
  });

  test('shows error toast if clipboard writeText fails', async () => {
    // Mock clipboard failure
    mockWriteText.mockRejectedValue(new Error('Copy failed'));

    render(<PgpChallengeSigner {...defaultProps} />);
    const copyButton = screen.getByRole('button', { name: /Copy Challenge/i });

    await userEvent.click(copyButton);

    expect(mockWriteText).toHaveBeenCalledTimes(1);
    await waitFor(() => {
       expect(mockNotifications.showErrorToast).toHaveBeenCalledWith('Failed to copy text automatically. Please copy manually.');
    });
    expect(mockNotifications.showSuccessToast).not.toHaveBeenCalled();
  });

  test('renders signature textarea and calls onChange handler', () => {
    const initialSignature = 'initial sig';
    render(<PgpChallengeSigner {...defaultProps} signatureValue={initialSignature} />);

    const textarea = screen.getByLabelText(defaultProps.signatureLabel || /Paste Your PGP Signature Block:/i);
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveValue(initialSignature);
    expect(textarea).not.toBeDisabled();

    const typedValue = 'new signature content';
    // Simulate typing in textarea
    fireEvent.change(textarea, { target: { value: typedValue } });

    expect(mockOnChange).toHaveBeenCalledTimes(1);
    // Check the event object passed to onChange
    const changeEvent = mockOnChange.mock.calls[0][0];
    expect(changeEvent.target.value).toBe(typedValue);
  });

  test('disables copy button and signature textarea when disabled prop is true', () => {
    render(<PgpChallengeSigner {...defaultProps} disabled={true} />);

    expect(screen.getByRole('button', { name: /Copy Challenge/i })).toBeDisabled();
    expect(screen.getByLabelText(defaultProps.signatureLabel || /Paste Your PGP Signature Block:/i)).toBeDisabled();
  });

  test('has correct accessibility attributes linking signature input', () => {
     // Use custom IDs to ensure test is robust
     const customChallengeId = 'custom-challenge-id';
     const customSignatureId = 'custom-signature-id';
    render(<PgpChallengeSigner {...defaultProps} challengeTextId={customChallengeId} signatureInputId={customSignatureId} />);

    const codeBlock = screen.getByText(defaultProps.challengeText, { selector: 'code' }).closest('pre');
    expect(codeBlock).toHaveAttribute('id', customChallengeId);

    const textarea = screen.getByLabelText(defaultProps.signatureLabel || /Paste Your PGP Signature Block:/i);
    expect(textarea).toHaveAttribute('id', customSignatureId);
    expect(textarea).toHaveAttribute('aria-describedby', customChallengeId);
  });

});