// frontend/components/PaginationControls.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Migrated to CSS Modules, added nav element, adjusted props.
//           - Replaced inline styles with CSS Module import (PaginationControls.module.css).
//           - Adapted styles for dark theme via CSS Module.
//           - Added 'hasPrevious' and 'hasNext' props for more robust button disabling.
//           - Wrapped controls in a <nav> element with aria-label for accessibility.
//           - Added revision history block.

import React from 'react';
import styles from './PaginationControls.module.css'; // Import CSS Module

/**
 * Renders Previous/Next pagination controls.
 *
 * @param {object} props - Component props.
 * @param {number} props.currentPage - The current active page number.
 * @param {number} props.totalPages - The total number of pages available.
 * @param {number} props.totalCount - The total number of items across all pages.
 * @param {function} props.onPrevious - Function to call when Previous button is clicked.
 * @param {function} props.onNext - Function to call when Next button is clicked.
 * @param {boolean} props.hasPrevious - Whether a previous page exists (from API response).
 * @param {boolean} props.hasNext - Whether a next page exists (from API response).
 * @param {boolean} props.isLoading - Whether data is currently loading (disables buttons).
 * @returns {React.ReactElement | null} The pagination controls or null if not needed.
 */
const PaginationControls = ({
    currentPage,
    totalPages,
    totalCount,
    onPrevious,
    onNext,
    hasPrevious,
    hasNext,
    isLoading
}) => {
    // Don't render controls if only one page or zero pages
    if (!totalPages || totalPages <= 1) {
        return null;
    }

    return (
        // Wrap in <nav> for semantic pagination controls
        <nav className={styles.paginationControls} aria-label="Pagination">
            <button
                onClick={onPrevious}
                // Disable if loading OR if there's no previous page according to API
                disabled={!hasPrevious || isLoading}
                className={styles.pageButton} // Use module style or combine with global .button
                aria-label="Go to Previous Page"
            >
                &laquo; Previous
            </button>
            <span className={styles.pageInfo}>
                Page {currentPage} of {totalPages}
                {totalCount > 0 && ` (${totalCount} items)`}
            </span>
            <button
                onClick={onNext}
                // Disable if loading OR if there's no next page according to API
                disabled={!hasNext || isLoading}
                className={styles.pageButton} // Use module style or combine with global .button
                aria-label="Go to Next Page"
            >
                Next &raquo;
            </button>
        </nav>
    );
};

export default PaginationControls;

// TODO: Create PaginationControls.module.css to style the controls for the dark theme.