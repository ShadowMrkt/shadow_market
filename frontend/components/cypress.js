// frontend/cypress.config.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial setup for E2E testing with Cypress.
//           - Added basic e2e configuration block.
//           - Set baseUrl for local development.

const { defineConfig } = require('cypress');

module.exports = defineConfig({
  e2e: {
    // Base URL for cy.visit() and cy.request() commands
    baseUrl: 'http://localhost:3000', // Adjust if your local frontend runs elsewhere

    // Optional: Setup Node event listeners if needed (e.g., for tasks)
    setupNodeEvents(on, config) {
      // implement node event listeners here
    },

    // Optional: Increase default command timeout if needed (e.g., for slow API responses)
    // defaultCommandTimeout: 5000, // Default is 4000ms

    // Specify the location of spec files (tests)
    // specPattern: 'cypress/e2e/**/*.cy.{js,jsx,ts,tsx}', // Default pattern
  },

  // Add other configurations if needed (component testing, viewport size, etc.)
  // viewportWidth: 1280,
  // viewportHeight: 720,
});