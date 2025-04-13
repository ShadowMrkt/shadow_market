// frontend/utils/formatters.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 4 - Corrected failing formatDate test by ensuring the expected string is also generated using UTC timezone to match the function's default. Added more robust checks for YYYY-MM-DD handling and timezone override.
// 2025-04-09: Rev 3 - Added tests for renderStars, requiring @testing-library/react.
// 2025-04-09: Rev 2 - Added tests for formatPrice and formatCurrency.
// 2025-04-09: Rev 1 - Initial creation. Tests for formatDate function.

import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { formatDate, formatPrice, formatCurrency, renderStars } from './formatters'; // Adjust path as needed
import { CURRENCY_SYMBOLS } from './constants'; // Import needed constants
import { Decimal } from 'decimal.js'; // Import Decimal for testing formatPrice

// Mock console.error/warn to check for specific error logs if needed, and prevent test pollution
let consoleErrorSpy, consoleWarnSpy;
beforeAll(() => {
  consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {}); // Mock warn too for formatPrice default
});
afterAll(() => {
  consoleErrorSpy.mockRestore();
  consoleWarnSpy.mockRestore();
});
beforeEach(() =>{
    consoleErrorSpy.mockClear();
    consoleWarnSpy.mockClear();
});

describe('Utility Formatters', () => {

  // --- Tests for formatDate ---
  describe('formatDate', () => {
    test('should return "N/A" for null or undefined input', () => {
      expect(formatDate(null)).toBe('N/A');
      expect(formatDate(undefined)).toBe('N/A');
      expect(formatDate('')).toBe('N/A');
    });

    test('should return "Invalid Date" for invalid date strings', () => {
      expect(formatDate('not a date')).toBe('Invalid Date');
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error formatting date:", "not a date", "Invalid date input (Could not parse)");
      consoleErrorSpy.mockClear();
      expect(formatDate('2023-13-01')).toBe('Invalid Date'); // Invalid month
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error formatting date:", "2023-13-01", "Invalid date components (Month/Day out of range)");
      consoleErrorSpy.mockClear();
      expect(formatDate('2023-02-30')).toBe('Invalid Date'); // Invalid day for month
       expect(consoleErrorSpy).toHaveBeenCalledWith("Error formatting date:", "2023-02-30", "Invalid date components (Day invalid for month/year or parse error)");
    });

    test('should format a valid date string (YYYY-MM-DD) correctly with default options (UTC)', () => {
      const dateStr = '2024-07-15';
      // Expected format should also be generated using UTC
      const expectedFormat = new Date(Date.UTC(2024, 6, 15)).toLocaleDateString('en-US', { // Use specific locale for consistency
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
      });
      expect(formatDate(dateStr)).toBe(expectedFormat); // e.g., "Jul 15, 2024"
    });

    test('should format a valid ISO date string correctly with default options (UTC)', () => {
      const dateStr = '2024-03-01T10:30:00Z'; // Explicitly UTC
      // Expected format should also be generated using UTC
      const expectedFormat = new Date(dateStr).toLocaleDateString('en-US', { // Use specific locale
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
      });
      expect(formatDate(dateStr)).toBe(expectedFormat); // e.g., "Mar 1, 2024"
    });

    test('should format a Date object correctly with default options (displaying its UTC equivalent)', () => {
        const dateObj = new Date(Date.UTC(2023, 11, 25, 14, 0, 0)); // Dec 25, 2023 14:00 UTC
        const expectedFormat = dateObj.toLocaleDateString('en-US', { // Use specific locale
          year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' // Format expects the UTC representation
        });
        expect(formatDate(dateObj)).toBe(expectedFormat); // e.g., "Dec 25, 2023"
      });


    test('should format correctly with custom date options (default UTC)', () => {
      const dateStr = '2024-07-15';
      const options = { year: '2-digit', month: 'numeric', day: 'numeric' };
      // Expected format generated using UTC
      const expectedFormat = new Date(Date.UTC(2024, 6, 15)).toLocaleDateString('en-US', { // Use specific locale
        ...options, timeZone: 'UTC'
      });
      expect(formatDate(dateStr, options)).toBe(expectedFormat); // e.g., "7/15/24"
    });

    // <<< REV 4: Corrected expectation to use UTC >>>
    test('should format correctly with custom date and time options (default UTC)', () => {
      const dateStr = '2024-03-01T10:30:00Z'; // Explicitly UTC input
      const options = { hour: 'numeric', minute: '2-digit', hour12: true };
      // Expected format should also be generated using UTC
      const expectedFormat = new Date(dateStr).toLocaleString('en-US', { // Use specific locale
         year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC', ...options // Added timeZone: 'UTC' here
      });
      // Function defaults to UTC, so this should now match
      expect(formatDate(dateStr, options)).toBe(expectedFormat); // Should now pass, e.g., "Mar 1, 2024, 10:30 AM"
    });

    test('should format correctly when overriding timezone in options', () => {
        const dateStr = '2024-03-01T10:30:00Z'; // UTC input time
        // Use a timezone *without* DST on March 1st for predictability if ICU data is limited
        const targetTimeZone = 'America/Phoenix'; // UTC-7 year-round
        const options = {
            hour: 'numeric', minute: '2-digit', hour12: true, timeZone: targetTimeZone
        };
        // Generate expected format using the SAME timezone
        const expectedFormat = new Date(dateStr).toLocaleString('en-US', { // Use specific locale
           year: 'numeric', month: 'short', day: 'numeric', timeZone: targetTimeZone, ...options
        });
        // Pass the override timezone to the function
        expect(formatDate(dateStr, options)).toBe(expectedFormat); // e.g., "Mar 1, 2024, 3:30 AM" (for MST/UTC-7)
      });

     test('should handle timestamp number input', () => {
         const timestamp = Date.UTC(2024, 0, 1, 12, 0, 0); // Jan 1, 2024 12:00:00 UTC
         const expectedFormat = new Date(timestamp).toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
          });
         expect(formatDate(timestamp)).toBe(expectedFormat); // e.g., "Jan 1, 2024"
     });

  });

  // --- Tests for formatPrice ---
  describe('formatPrice', () => {
    test('should return null for null, undefined, or empty string input', () => {
      expect(formatPrice(null, 'XMR')).toBeNull();
      expect(formatPrice(undefined, 'BTC')).toBeNull();
      expect(formatPrice('', 'USD')).toBeNull();
    });

    test('should return null and log error for invalid number input', () => {
      expect(formatPrice('not a number', 'XMR')).toBeNull();
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error formatting price for XMR:", "not a number", "Input is not a valid number");
    });

    test('should format XMR with 6 decimal places', () => {
      expect(formatPrice(1.23456789, 'XMR')).toBe('1.234568');
      expect(formatPrice('10', 'XMR')).toBe('10.000000');
    });

    test('should format BTC with 8 decimal places', () => {
      expect(formatPrice(0.123456789, 'BTC')).toBe('0.12345679');
      expect(formatPrice('0.005', 'BTC')).toBe('0.00500000');
    });

     test('should format ETH with 6 decimal places', () => {
      expect(formatPrice(0.123456789, 'ETH')).toBe('0.123457');
      expect(formatPrice('123.45', 'ETH')).toBe('123.450000');
    });

    test('should format USD/FIAT with 2 decimal places', () => {
      expect(formatPrice(19.999, 'USD')).toBe('20.00');
      expect(formatPrice('100', 'EUR')).toBe('100.00');
      expect(formatPrice(50.1, 'GBP')).toBe('50.10');
    });

    test('should format unknown currency with 2 decimal places (default) and warn', () => {
        expect(formatPrice(123.456, 'XYZ')).toBe('123.46');
        expect(consoleWarnSpy).toHaveBeenCalledWith(expect.stringContaining("'XYZ'"));
        consoleWarnSpy.mockClear(); // Clear for next check

        expect(formatPrice('1000', 'ABC')).toBe('1000.00');
        expect(consoleWarnSpy).toHaveBeenCalledWith(expect.stringContaining("'ABC'"));
        consoleWarnSpy.mockClear();

        expect(formatPrice(99, null)).toBe('99.00');
        expect(consoleWarnSpy).toHaveBeenCalledWith(expect.stringContaining("'null'"));
      });


    test('should handle zero correctly', () => {
        expect(formatPrice(0, 'BTC')).toBe('0.00000000');
        expect(formatPrice('0', 'USD')).toBe('0.00');
        expect(formatPrice(new Decimal(0), 'XMR')).toBe('0.000000');
    });

    test('should handle negative zero correctly (output positive zero)', () => {
        expect(formatPrice(new Decimal('-0'), 'USD')).toBe('0.00');
        expect(formatPrice(new Decimal(-0.00000000001), 'BTC')).toBe('0.00000000');
    });

     test('should handle Decimal object input', () => {
        expect(formatPrice(new Decimal(0.0005), 'BTC')).toBe('0.00050000');
        expect(formatPrice(new Decimal('19.95'), 'USD')).toBe('19.95');
    });
  });

  // --- Tests for formatCurrency ---
  describe('formatCurrency', () => {
     test('should return "N/A" for null/undefined/empty input by default', () => {
        expect(formatCurrency(null, 'XMR')).toBe('N/A');
        expect(formatCurrency(undefined, 'BTC')).toBe('N/A');
        expect(formatCurrency('', 'USD')).toBe('N/A');
    });

     test('should return empty string for null/undefined/empty input if showNA is false', () => {
        expect(formatCurrency(null, 'XMR', { showNA: false })).toBe('');
        expect(formatCurrency(undefined, 'BTC', { showNA: false })).toBe('');
        expect(formatCurrency('', 'USD', { showNA: false })).toBe('');
    });

    test('should return "N/A" or "" for invalid number input', () => {
      expect(formatCurrency('not a number', 'XMR')).toBe('N/A');
      expect(formatCurrency('not a number', 'XMR', { showNA: false })).toBe('');
      // formatPrice should have logged the error
      expect(consoleErrorSpy).toHaveBeenCalledWith("Error formatting price for XMR:", "not a number", "Input is not a valid number");
    });

    test('should format currency correctly (Symbol + Price)', () => {
        expect(formatCurrency(1.2345678, 'XMR')).toBe(`${CURRENCY_SYMBOLS.XMR} 1.234568`); // XMR uses 6dp in formatPrice
        expect(formatCurrency(0.005, 'BTC')).toBe(`${CURRENCY_SYMBOLS.BTC} 0.00500000`);
        expect(formatCurrency(19.99, 'USD')).toBe(`${CURRENCY_SYMBOLS.USD} 19.99`);
        expect(formatCurrency('100.50', 'EUR')).toBe(`${CURRENCY_SYMBOLS.EUR} 100.50`);
    });

    test('should use currency code if symbol is missing', () => {
      expect(formatCurrency(123.456, 'XYZ')).toBe('XYZ 123.46');
      expect(consoleWarnSpy).toHaveBeenCalledWith(expect.stringContaining("'XYZ'")); // formatPrice warns
    });

     test('should handle zero correctly', () => {
        expect(formatCurrency(0, 'BTC')).toBe(`${CURRENCY_SYMBOLS.BTC} 0.00000000`);
        expect(formatCurrency('0', 'USD')).toBe(`${CURRENCY_SYMBOLS.USD} 0.00`);
        expect(formatCurrency(new Decimal(0), 'XMR')).toBe(`${CURRENCY_SYMBOLS.XMR} 0.000000`);
    });
  });

  // --- Tests for renderStars ---
  describe('renderStars', () => {
    test('should return "N/A" for null, undefined, or NaN input', () => {
      expect(renderStars(null)).toBe('N/A');
      expect(renderStars(undefined)).toBe('N/A');
      expect(renderStars(NaN)).toBe('N/A');
    });

    test('should render correct stars for integer rating', () => {
      render(renderStars(4));
      expect(screen.getByTitle('4.00 / 5')).toHaveTextContent('★★★★☆');
    });

    test('should render correct stars for half rating (e.g., 3.5)', () => {
      render(renderStars(3.5));
      expect(screen.getByTitle('3.50 / 5')).toHaveTextContent('★★★½☆');
    });

     test('should render correct stars for rating needing rounding (e.g., 3.7 -> 3.5)', () => {
      render(renderStars(3.7));
      // Check rounding logic - 3.7 rounds to 3.5 stars visually, title shows original
      expect(screen.getByTitle('3.70 / 5')).toHaveTextContent('★★★½☆');
    });

     test('should render correct stars for rating needing rounding (e.g., 3.8 -> 4.0)', () => {
      render(renderStars(3.8));
      // Check rounding logic - 3.8 rounds to 4.0 stars visually, title shows original
      expect(screen.getByTitle('3.80 / 5')).toHaveTextContent('★★★★☆');
    });

    test('should render correct stars for zero rating', () => {
      render(renderStars(0));
      expect(screen.getByTitle('0.00 / 5')).toHaveTextContent('☆☆☆☆☆');
    });

    test('should render correct stars for max rating', () => {
      render(renderStars(5));
      expect(screen.getByTitle('5.00 / 5')).toHaveTextContent('★★★★★');
    });

    test('should clamp rating below 0 to 0 stars', () => {
      render(renderStars(-1));
      // Title shows original value, visual stars are clamped
      expect(screen.getByTitle('-1.00 / 5')).toHaveTextContent('☆☆☆☆☆');
    });

    test('should clamp rating above 5 to 5 stars', () => {
      render(renderStars(6));
      // Title shows original value, visual stars are clamped
      expect(screen.getByTitle('6.00 / 5')).toHaveTextContent('★★★★★');
    });

     test('should render correct title attribute with formatted rating', () => {
        render(renderStars(4.2345));
        // Title uses original value formatted to 2dp
        expect(screen.getByTitle('4.23 / 5')).toBeInTheDocument();
        // Visual stars round to nearest 0.5 (4.23 -> 4.0)
        expect(screen.getByTitle('4.23 / 5')).toHaveTextContent('★★★★☆');
    });
  });

});