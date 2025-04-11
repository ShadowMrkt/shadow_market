// frontend/jest.config.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 12 - Simplified moduleNameMapper for path aliases.
//             - Removed specific subdirectory mappings ('@/components/', '@/context/', etc.).
//             - Relies solely on the general '@/' mapping based on tsconfig baseUrl '.'.
// (Previous revisions omitted)

const nextJest = require('next/jest')({
  // Provide the path to your Next.js app to load next.config.js and .env files in your test environment
  dir: './',
});

// Add any custom Jest configuration options to be passed to Jest
/** @type {import('jest').Config} */
const customJestConfig = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  testEnvironment: 'jest-environment-jsdom',

  // --- Module Name Mapper ---
  moduleNameMapper: {
    // --- CSS / Assets ---
    // Rely on next/jest for CSS/CSS Modules handling.
    // Asset mock for images/fonts etc.
    '\\.(gif|ttf|eot|svg|png|jpg|jpeg)$': '<rootDir>/__mocks__/fileMock.js',

    // --- Module Path Aliases ---
    // General alias based on tsconfig baseUrl '.'
    '^@/(.*)$': '<rootDir>/$1',
  },

  testPathIgnorePatterns: [
    '<rootDir>/node_modules/',
    '<rootDir>/.next/',
  ],
};

// createJestConfig is exported this way to ensure that next/jest can load the Next.js config which is async
module.exports = nextJest(customJestConfig);