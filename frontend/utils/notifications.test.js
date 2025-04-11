// frontend/utils/notifications.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 3 - Added tests for showInfoToast and showWarningToast.
// 2025-04-09: Rev 2 - Added tests for showErrorToast.
// 2025-04-09: Rev 1 - Initial creation. Tests for showSuccessToast.

import { toast } from 'react-toastify';
import { showSuccessToast, showErrorToast, showInfoToast, showWarningToast } from './notifications'; // Adjust path
import { TOAST_SUCCESS_DURATION, TOAST_ERROR_DURATION } from './constants'; // Import constants used internally

// Mock the react-toastify library
jest.mock('react-toastify', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warn: jest.fn(),
  },
}));

// Mock console.error
let consoleErrorSpy;
beforeAll(() => {
  consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterAll(() => {
  consoleErrorSpy.mockRestore();
});
beforeEach(() => {
  jest.clearAllMocks();
  consoleErrorSpy.mockClear();
});

describe('Notification Utilities', () => {

  // --- Base expected config from notifications.js ---
  const baseExpectedConfig = {
    position: "top-right",
    autoClose: TOAST_SUCCESS_DURATION, // Default autoClose
    hideProgressBar: false,
    closeOnClick: true,
    pauseOnHover: true,
    draggable: true,
    progress: undefined,
    theme: "dark",
  };

  // Expected config specifically for errors
   const errorExpectedConfig = {
    ...baseExpectedConfig,
    autoClose: TOAST_ERROR_DURATION, // Error uses specific duration
   };

  // --- Tests for showSuccessToast ---
  describe('showSuccessToast', () => {
    test('should call toast.success with message and default config', () => {
      const message = 'Operation successful!';
      showSuccessToast(message);
      expect(toast.success).toHaveBeenCalledTimes(1);
      expect(toast.success).toHaveBeenCalledWith(message, baseExpectedConfig);
    });

    test('should call toast.success merging default config with options', () => {
      const message = 'Profile Updated';
      const options = { autoClose: 1000, position: 'bottom-center', toastId: 'profile-update' };
      showSuccessToast(message, options);
      expect(toast.success).toHaveBeenCalledTimes(1);
      expect(toast.success).toHaveBeenCalledWith(message, {
        ...baseExpectedConfig,
        ...options,
      });
    });

     test('should handle null/undefined message with default text', () => {
      showSuccessToast(null);
      expect(toast.success).toHaveBeenCalledWith('Success!', baseExpectedConfig);
      toast.success.mockClear();
      showSuccessToast(undefined);
       expect(toast.success).toHaveBeenCalledWith('Success!', baseExpectedConfig);
    });

     test('should convert non-string message to string', () => {
      showSuccessToast(123);
      expect(toast.success).toHaveBeenCalledWith('123', baseExpectedConfig);
      toast.success.mockClear();
      showSuccessToast({ data: 'value' });
      expect(toast.success).toHaveBeenCalledWith('[object Object]', baseExpectedConfig);
    });
  });

  // --- Tests for showErrorToast ---
  describe('showErrorToast', () => {
     test('should call toast.error with string message and error config', () => {
      const message = 'Something went wrong!';
      showErrorToast(message);
      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(toast.error).toHaveBeenCalledWith(message, errorExpectedConfig);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", message);
    });

    test('should call toast.error with message from Error object', () => {
      const errorMessage = 'Network Error Occurred';
      const errorObj = new Error(errorMessage);
      showErrorToast(errorObj);
      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(toast.error).toHaveBeenCalledWith(errorMessage, errorExpectedConfig);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", errorObj);
    });

    test('should truncate long messages for display', () => {
      const longMessage = 'This is a very long error message that definitely exceeds the one hundred and fifty character limit imposed by the notification utility function to prevent UI overflow and keep things tidy for the user experience.'; // > 150 chars
      const truncatedMessage = longMessage.substring(0, 147) + '...';
      showErrorToast(longMessage);
      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(toast.error).toHaveBeenCalledWith(truncatedMessage, errorExpectedConfig);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", longMessage);
    });

     test('should call console.error with the original error object/value', () => {
      const errorObj = new Error('Detailed Error');
      showErrorToast(errorObj);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", errorObj);
      consoleErrorSpy.mockClear();
      const otherValue = { code: 500, status: 'Internal Error' };
      showErrorToast(otherValue);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", otherValue);
     });

     test('should handle null/undefined error with default message', () => {
      showErrorToast(null);
      expect(toast.error).toHaveBeenCalledWith('An unknown error occurred.', errorExpectedConfig);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", null);
      toast.error.mockClear(); consoleErrorSpy.mockClear();
      showErrorToast(undefined);
      expect(toast.error).toHaveBeenCalledWith('An unknown error occurred.', errorExpectedConfig);
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", undefined);
    });

     test('should convert other data types to string for display', () => {
        const errorData = { code: 404 };
        showErrorToast(errorData);
        expect(toast.error).toHaveBeenCalledWith('[object Object]', errorExpectedConfig);
        expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", errorData);
        toast.error.mockClear(); consoleErrorSpy.mockClear();
        showErrorToast(500);
        expect(toast.error).toHaveBeenCalledWith('500', errorExpectedConfig);
        expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", 500);
     });

    test('should merge default error config with passed options', () => {
      const message = 'Specific error';
      const options = { toastId: 'specific-error-id', position: 'top-left' };
      showErrorToast(message, options);
      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(toast.error).toHaveBeenCalledWith(message, {
        ...errorExpectedConfig,
        ...options,
      });
       expect(consoleErrorSpy).toHaveBeenCalledWith("Error Toast Triggered:", message);
    });
  });

  // --- NEW: Tests for showInfoToast ---
  describe('showInfoToast', () => {
     test('should call toast.info with message and default config', () => {
      const message = 'Informational message.';
      showInfoToast(message);
      expect(toast.info).toHaveBeenCalledTimes(1);
      expect(toast.info).toHaveBeenCalledWith(message, baseExpectedConfig);
    });

    test('should call toast.info merging default config with options', () => {
      const message = 'FYI';
      const options = { autoClose: 2000, toastId: 'info-toast' };
      showInfoToast(message, options);
      expect(toast.info).toHaveBeenCalledTimes(1);
      expect(toast.info).toHaveBeenCalledWith(message, {
        ...baseExpectedConfig,
        ...options,
      });
    });

     test('should handle null/undefined message with default text', () => {
      showInfoToast(null);
      expect(toast.info).toHaveBeenCalledWith('Info', baseExpectedConfig);
      toast.info.mockClear();
      showInfoToast(undefined);
       expect(toast.info).toHaveBeenCalledWith('Info', baseExpectedConfig);
    });

     test('should convert non-string message to string', () => {
      showInfoToast(true); // Boolean example
      expect(toast.info).toHaveBeenCalledWith('true', baseExpectedConfig);
    });
  });

  // --- NEW: Tests for showWarningToast ---
  describe('showWarningToast', () => {
     test('should call toast.warn with message and default config', () => {
      const message = 'This is a warning.';
      showWarningToast(message);
      expect(toast.warn).toHaveBeenCalledTimes(1);
      expect(toast.warn).toHaveBeenCalledWith(message, baseExpectedConfig); // Uses default config
    });

    test('should call toast.warn merging default config with options', () => {
      const message = 'Warning!';
      const options = { autoClose: 7000, toastId: 'warn-toast' };
      showWarningToast(message, options);
      expect(toast.warn).toHaveBeenCalledTimes(1);
      expect(toast.warn).toHaveBeenCalledWith(message, {
        ...baseExpectedConfig,
        ...options,
      });
    });

     test('should handle null/undefined message with default text', () => {
      showWarningToast(null);
      expect(toast.warn).toHaveBeenCalledWith('Warning', baseExpectedConfig);
      toast.warn.mockClear();
      showWarningToast(undefined);
       expect(toast.warn).toHaveBeenCalledWith('Warning', baseExpectedConfig);
    });

     test('should convert non-string message to string', () => {
      showWarningToast(['a', 'b']); // Array example
      expect(toast.warn).toHaveBeenCalledWith('a,b', baseExpectedConfig); // Default array stringification
    });
  });

});