// frontend/jest.setup.js
// --- REVISION HISTORY ---
// 2025-04-08: Rev 1 - Initial creation.
//           - Imported @testing-library/jest-dom to extend Jest matchers for DOM testing.

// This file runs once per test file *after* the test framework is installed in the environment.
// Use it to import test helpers or set up global configurations/mocks for your tests.

// Import Jest DOM extensions from @testing-library/jest-dom
// This adds helpful matchers specifically for working with the DOM, making tests more readable.
// Examples: .toBeInTheDocument(), .toHaveTextContent(), .toBeVisible(), .toHaveAttribute() etc.
import '@testing-library/jest-dom';

// --- Optional Global Setup ---
// You can add other global setup here if needed for your test environment.
// For example:
//
// // Mocking localStorage (if used extensively and needs a consistent mock)
// const localStorageMock = (() => {
//   let store = {};
//   return {
//     getItem: (key) => store[key] || null,
//     setItem: (key, value) => { store[key] = value.toString(); },
//     removeItem: (key) => { delete store[key]; },
//     clear: () => { store = {}; }
//   };
// })();
// Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// // Mocking Fetch API (though libraries like 'jest-fetch-mock' are often preferred)
// global.fetch = jest.fn(() =>
//   Promise.resolve({
//     json: () => Promise.resolve({ mockData: 'value' }),
//   })
// );

// // Reset mocks before each test (can also be done in jest.config.js or individual test files)
// beforeEach(() => {
//   // Reset specific mocks if needed
//   // e.g., if using jest.fn() for mocks: fetch.mockClear();
// });

// // Clean up after tests if necessary
// afterAll(() => {
//   // Global cleanup actions
// });