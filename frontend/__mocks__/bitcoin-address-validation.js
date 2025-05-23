// frontend/__mocks__/bitcoin-address-validation.js

/**
 * Manual mock for the 'bitcoin-address-validation' module.
 * Jest automatically picks up files in __mocks__ folders adjacent to node_modules
 * and uses them instead of the actual module during tests.
 */

// Simple mock: returns true for non-empty strings that start with '1' or '3' or 'bc1', false otherwise.
// This provides *some* basic differentiation for testing purposes.
// Adjust this logic if your tests depend on more specific validation outcomes.
const validate = (address) => {
  console.log(`[MOCK] bitcoin-address-validation: Validating address: ${address}`); // Log that the mock is being used
  if (typeof address !== 'string' || address.trim().length === 0) {
    return false;
  }
  const trimmed = address.trim();
  // Basic checks for common mainnet address prefixes
  return trimmed.startsWith('1') || trimmed.startsWith('3') || trimmed.startsWith('bc1');
};

// Ensure all functions exported by the real module that your code *uses* are mocked.
// If your code only uses `validate`, this is sufficient. If it uses others, add mock functions for them too.
// For example:
// const getAddressInfo = jest.fn().mockReturnValue({ type: 'p2pkh', network: 'mainnet' });

module.exports = {
  validate,
  // getAddressInfo // Add other exports here if needed
};