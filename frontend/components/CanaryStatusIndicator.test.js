// frontend/components/CanaryStatusIndicator.test.js
// --- REVISION HISTORY ---
// 2025-04-13 (Gemini): Rev 2 - Updated tests to assert against CSS Module class names (styles.*) instead of plain strings.
//                         - Imported the CSS module `styles`.
//                         - Refined className prop test to check for base, state, and custom classes using CSS Modules.
// 2025-04-09: Rev 1 - Initial creation. Tests for CanaryStatusIndicator component.
//                   - Tests loading, error, missing data, invalid date, valid, due, and expired states.
//                   - Uses fake timers to control date comparisons.
//                   - Checks text, icons, CSS classes, title attribute, and link destination.

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import CanaryStatusIndicator from './CanaryStatusIndicator';
import styles from './CanaryStatusIndicator.module.css'; // <<< REV 2: Import CSS Module
import { formatDate } from '../utils/formatters'; // Import the actual formatter

// Mock the Link component minimally if needed, or test its props
jest.mock('next/link', () => ({ children, href, passHref, legacyBehavior, ...rest }) => (
  // Mock matches the component's Rev 4 usage (Link renders the anchor)
  <a href={href} {...rest}>{children}</a>
));

// --- Configuration (match component's config) ---
const UPDATE_WARNING_DAYS = 14;
const EXPIRY_DAYS = 30;
// -------------------------------------------------

describe('CanaryStatusIndicator Component', () => {
  const baseDate = new Date('2025-04-01T12:00:00.000Z');

  // Use fake timers to control the current date
  beforeAll(() => {
    jest.useFakeTimers();
    jest.setSystemTime(baseDate);
  });

  afterAll(() => {
    jest.useRealTimers();
  });

  test('renders loading state correctly', () => {
    render(<CanaryStatusIndicator isLoading={true} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusLoading); // <<< REV 2: Use styles.*
    expect(link).toHaveAttribute('aria-label', 'Loading canary status...');
    expect(screen.getByText('⏳')).toBeInTheDocument(); // Loading icon
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

  test('renders error state correctly', () => {
    render(<CanaryStatusIndicator error={new Error('Fetch failed')} isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusError); // <<< REV 2: Use styles.*
    expect(link).toHaveAttribute('aria-label', expect.stringContaining('Error loading canary: Fetch failed'));
    expect(screen.getByText('❓')).toBeInTheDocument(); // Error icon
    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

  test('renders missing data state correctly', () => {
    render(<CanaryStatusIndicator lastUpdated={null} isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusError); // <<< REV 2: Treat missing as error (Use styles.*)
    expect(link).toHaveAttribute('aria-label', 'Warrant canary data is unavailable.');
    expect(screen.getByText('❓')).toBeInTheDocument(); // Error icon
    expect(screen.getByText('No Data')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

   test('renders invalid date state correctly', () => {
    render(<CanaryStatusIndicator lastUpdated="invalid-date-string" isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusError); // <<< REV 2: Treat invalid date as error (Use styles.*)
    expect(link).toHaveAttribute('aria-label', 'Warrant canary date is invalid or could not be parsed.');
    expect(screen.getByText('❓')).toBeInTheDocument(); // Error icon
    expect(screen.getByText('Date Error')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

  test('renders VALID state correctly', () => {
    // Set last updated date to 5 days ago (within warning period)
    const validDate = new Date(baseDate);
    validDate.setDate(baseDate.getDate() - 5);
    const validDateString = validDate.toISOString().split('T')[0]; // YYYY-MM-DD

    render(<CanaryStatusIndicator lastUpdated={validDateString} isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusValid); // <<< REV 2: Use styles.*
    expect(link).toHaveAttribute('aria-label', expect.stringContaining(`Warrant Canary Valid: Last Updated ${formatDate(validDateString)}`));
    expect(screen.getByText('✅')).toBeInTheDocument(); // Valid icon
    expect(screen.getByText('Canary Valid')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

  test('renders UPDATE_DUE state correctly', () => {
    // Set last updated date to (UPDATE_WARNING_DAYS + 1) days ago
    const dueDate = new Date(baseDate);
    dueDate.setDate(baseDate.getDate() - (UPDATE_WARNING_DAYS + 1));
    const dueDateString = dueDate.toISOString().split('T')[0];

    render(<CanaryStatusIndicator lastUpdated={dueDateString} isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusWarning); // <<< REV 2: Use styles.*
    expect(link).toHaveAttribute('aria-label', expect.stringContaining(`Warrant Canary Update Recommended: Last Updated ${formatDate(dueDateString)}`));
    expect(screen.getByText('⚠️')).toBeInTheDocument(); // Warning icon
    expect(screen.getByText('Canary Update Due')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

   test('renders EXPIRED state correctly', () => {
    // Set last updated date to (EXPIRY_DAYS + 1) days ago
    const expiredDate = new Date(baseDate);
    expiredDate.setDate(baseDate.getDate() - (EXPIRY_DAYS + 1));
    const expiredDateString = expiredDate.toISOString().split('T')[0];

    render(<CanaryStatusIndicator lastUpdated={expiredDateString} isLoading={false} />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass(styles.indicator); // <<< REV 2: Check base class
    expect(link).toHaveClass(styles.statusExpired); // <<< REV 2: Use styles.*
    expect(link).toHaveAttribute('aria-label', expect.stringContaining(`WARRANT CANARY EXPIRED: Last Updated ${formatDate(expiredDateString)}`));
    expect(screen.getByText('❌')).toBeInTheDocument(); // Expired icon
    expect(screen.getByText('Canary Expired')).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/canary');
  });

   test('applies additional className prop', () => {
    const customClass = 'my-extra-class';
    render(<CanaryStatusIndicator isLoading={true} className={customClass} />);
    const link = screen.getByRole('link');
    // <<< REV 2: Use styles.* and check all classes are present >>>
    expect(link).toHaveClass(styles.indicator, styles.statusLoading, customClass);
  });

});