// frontend/utils/formatters.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 3 - Added tests for renderStars, requiring @testing-library/react.
// 2025-04-09: Rev 2 - Added tests for formatPrice and formatCurrency.
// 2025-04-09: Rev 1 - Initial creation. Tests for formatDate function.

// --- NEW: Import render from @testing-library/react ---
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom'; // Keep for matchers like toHaveAttribute

import { formatDate, formatPrice, formatCurrency, renderStars } from './formatters'; // Adjust path as needed
import { CURRENCY_SYMBOLS } from './constants'; // Import needed constants
import { Decimal } from 'decimal.js'; // Import Decimal for testing formatPrice

// Mock console.error to check for specific error logs if needed, and prevent test pollution
let consoleErrorSpy;
beforeAll(() => {
  consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterAll(() => {
  consoleErrorSpy.mockRestore();
});
beforeEach(() =>{
    consoleErrorSpy.mockClear();
});

describe('Utility Formatters', () => {

  // --- Tests for formatDate ---
  describe('formatDate', () => {
    // (Tests from previous step remain here)
    test('should return "N/A" for null or undefined input', () => {
      expect(formatDate(null)).toBe('N/A');
      expect(formatDate(undefined)).toBe('N/A');
    });

    test('should return "Invalid Date" for invalid date strings', () => {
      expect(formatDate('not a date')).toBe('Invalid Date');
      expect(formatDate('2023-13-01')).toBe('Invalid Date');
      expect(consoleErrorSpy).toHaveBeenCalled();
    });

    test('should format a valid date string (YYYY-MM-DD) correctly with default options', () => {
      const dateStr = '2024-07-15';
      const expectedFormat = new Date(dateStr + 'T00:00:00Z').toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
      });
      expect(formatDate(dateStr)).toBe(expectedFormat);
    });

     test('should format a valid ISO date string correctly with default options', () => {
      const dateStr = '2024-03-01T10:30:00Z';
      const expectedFormat = new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
      });
      expect(formatDate(dateStr)).toBe(expectedFormat);
    });

    test('should format a Date object correctly with default options', () => {
      const dateObj = new Date(2023, 11, 25); // Dec 25, 2023
      const expectedFormat = dateObj.toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric'
      });
      expect(formatDate(dateObj)).toBe(expectedFormat);
    });

    test('should format correctly with custom date options', () => {
      const dateStr = '2024-07-15';
      const options = { year: '2-digit', month: 'numeric', day: 'numeric' };
       const expectedFormat = new Date(dateStr + 'T00:00:00Z').toLocaleDateString(undefined, {
        ...options, timeZone: 'UTC'
      });
      expect(formatDate(dateStr, options)).toBe(expectedFormat);
    });

     test('should format correctly with custom date and time options', () => {
      const dateStr = '2024-03-01T10:30:00Z';
      const options = { hour: 'numeric', minute: '2-digit', hour12: true };
      const expectedFormat = new Date(dateStr).toLocaleString(undefined, {
         year: 'numeric', month: 'short', day: 'numeric', ...options
      });
      expect(formatDate(dateStr, options)).toBe(expectedFormat);
    });
  });

  // --- Tests for formatPrice ---
  describe('formatPrice', () => {
    // (Tests from previous step remain here)
     test('should return null for null, undefined, or empty string input', () => {
      expect(formatPrice(null, 'XMR')).toBeNull();
      expect(formatPrice(undefined, 'BTC')).toBeNull();
      expect(formatPrice('', 'USD')).toBeNull();
    });

    test('should return null and log error for invalid number input', () => {
      expect(formatPrice('not a number', 'XMR')).toBeNull();
      expect(consoleErrorSpy).toHaveBeenCalled();
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

    test('should format unknown currency with 2 decimal places (default)', () => {
        expect(formatPrice(123.456, 'XYZ')).toBe('123.46');
        expect(formatPrice('1000', 'ABC')).toBe('1000.00');
        expect(formatPrice(99, null)).toBe('99.00');
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
    // (Tests from previous step remain here)
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
      expect(consoleErrorSpy).toHaveBeenCalled();
    });

    test('should format currency correctly (Symbol + Price)', () => {
       expect(formatCurrency(1.234567, 'XMR')).toBe(`${CURRENCY_SYMBOLS.XMR} 1.234567`);
       expect(formatCurrency(0.005, 'BTC')).toBe(`${CURRENCY_SYMBOLS.BTC} 0.00500000`);
       expect(formatCurrency(19.99, 'USD')).toBe(`${CURRENCY_SYMBOLS.USD} 19.99`);
       expect(formatCurrency('100.50', 'EUR')).toBe(`${CURRENCY_SYMBOLS.EUR} 100.50`);
    });

    test('should use currency code if symbol is missing', () => {
      expect(formatCurrency(123.456, 'XYZ')).toBe('XYZ 123.46');
    });

     test('should handle zero correctly', () => {
        expect(formatCurrency(0, 'BTC')).toBe(`${CURRENCY_SYMBOLS.BTC} 0.00000000`);
        expect(formatCurrency('0', 'USD')).toBe(`${CURRENCY_SYMBOLS.USD} 0.00`);
        expect(formatCurrency(new Decimal(0), 'XMR')).toBe(`${CURRENCY_SYMBOLS.XMR} 0.000000`);
    });
  });

  // --- NEW: Tests for renderStars ---
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
      expect(screen.getByTitle('3.70 / 5')).toHaveTextContent('★★★½☆'); // Rounds down to 3.5
    });

     test('should render correct stars for rating needing rounding (e.g., 3.8 -> 4.0)', () => {
      render(renderStars(3.8));
      expect(screen.getByTitle('3.80 / 5')).toHaveTextContent('★★★★☆'); // Rounds up to 4.0
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
      expect(screen.getByTitle('-1.00 / 5')).toHaveTextContent('☆☆☆☆☆'); // Clamped to 0
    });

    test('should clamp rating above 5 to 5 stars', () => {
      render(renderStars(6));
      expect(screen.getByTitle('6.00 / 5')).toHaveTextContent('★★★★★'); // Clamped to 5
    });

     test('should render correct title attribute with formatted rating', () => {
        render(renderStars(4.2345));
        // Rating value in title should be precise, max is fixed at 5
        expect(screen.getByTitle('4.23 / 5')).toBeInTheDocument();
        // Text content reflects rounding to nearest 0.5
        expect(screen.getByTitle('4.23 / 5')).toHaveTextContent('★★★★☆'); // Rounds down to 4.0
    });
  });

});