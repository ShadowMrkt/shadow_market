// cypress/e2e/login.cy.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial E2E test for the login flow.
//           - Covers Step 1 (Credentials + CAPTCHA) and Step 2 (PGP Challenge).
//           - Includes notes about handling CAPTCHA and PGP signing in E2E.

describe('Login Flow', () => {
  beforeEach(() => {
    // Visit the login page before each test in this block
    cy.visit('/login');
  });

  it('should allow a user to log in successfully (with mock/test values)', () => {
    // --- Step 1: Credentials and CAPTCHA ---
    cy.log('Starting Login Step 1');

    // Wait for CAPTCHA image to potentially load (adjust selector if needed)
    // Using a timeout ensures we wait even if the image isn't immediately present
    cy.get('img[alt="CAPTCHA security challenge image"]', { timeout: 10000 }).should('be.visible');

    // Input username and password
    // Use environment variables or fixtures for credentials in real tests
    cy.get('input#username').should('be.visible').type('testbuyer');
    cy.get('input#password').should('be.visible').type('password123'); // Use test credentials

    // Input mock CAPTCHA value
    // NOTE: This assumes the CAPTCHA input is visible and interactable.
    // Real-world testing requires bypassing/solving CAPTCHA.
    cy.get('input#captchaInput').should('be.visible').type('testcaptcha'); // Mock value

    // Click the "Next" button
    cy.get('button[type="submit"]').contains(/Next: PGP Challenge/i).should('be.visible').click();

    // --- Step 2: PGP Challenge ---
    cy.log('Starting Login Step 2');

    // Wait for Step 2 elements to appear
    cy.contains('Step 2 of 2: Verify PGP Signature', { timeout: 10000 }).should('be.visible');

    // Check if login phrase is displayed (optional but good verification)
    cy.get('.alert-info strong').should('exist'); // Check for the strong tag within the alert

    // Get challenge text (optional, mainly for debugging E2E)
    // cy.get('pre.code-block').invoke('text').as('challengeText');

    // Input mock PGP signature
    // NOTE: Real-world testing requires a valid signature for the specific challenge
    // generated for the test user, or a backend bypass mechanism.
    const mockSignature = `-----BEGIN PGP SIGNATURE-----
Version: GnuPG vX.X.X

mockSignatureDataForTesting==
-----END PGP SIGNATURE-----`;
    cy.get('textarea#pgpSignatureInput').should('be.visible').type(mockSignature, { delay: 0 }); // Use delay 0 for faster pasting

    // Click the final "Login" button
    cy.get('button[type="submit"]').contains(/Login/i).should('be.visible').click();

    // --- Assertion ---
    // Check for successful redirection or presence of an element on the target page
    // Example: Redirect to profile page
    cy.url().should('include', '/profile', { timeout: 10000 }); // Wait for redirection
    // Example: Check for a welcome message on the profile page
    cy.contains(/Your Profile/i).should('be.visible');

    cy.log('Login Successful');
  });

  it('should show error on invalid credentials in Step 1', () => {
    cy.log('Testing Invalid Credentials Step 1');
    cy.get('img[alt="CAPTCHA security challenge image"]', { timeout: 10000 }).should('be.visible');

    cy.get('input#username').type('wronguser');
    cy.get('input#password').type('wrongpassword');
    cy.get('input#captchaInput').type('testcaptcha'); // Assuming CAPTCHA is bypassed/mocked
    cy.get('button[type="submit"]').contains(/Next: PGP Challenge/i).click();

    // Assert that an error message is shown (check for the .error-message class or specific text)
    cy.get('.error-message').should('be.visible').and('contain.text', 'Invalid username, password, or CAPTCHA.');
    // Assert that we are still on Step 1 (check for Step 1 indicator or password field)
    cy.contains('Step 1 of 2').should('be.visible');
    cy.get('input#password').should('be.visible'); // Password field should still be there
  });

  // Add more tests: Invalid CAPTCHA, invalid PGP signature, etc.
});