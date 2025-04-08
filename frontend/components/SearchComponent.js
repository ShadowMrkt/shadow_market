// frontend/components/SearchComponent.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Initial implementation.
//           - Renders search input field within a form.
//           - Uses state to manage input value.
//           - Navigates to /search?q=[query] on form submission.
//           - Uses CSS Modules for styling.

import React, { useState } from 'react';
import { useRouter } from 'next/router';
import styles from './SearchComponent.module.css'; // Import CSS Module

/**
 * Renders a search input form that navigates to a search results page on submission.
 */
const SearchComponent = () => {
    const router = useRouter();
    const [query, setQuery] = useState('');

    const handleInputChange = (event) => {
        setQuery(event.target.value);
    };

    const handleSearchSubmit = (event) => {
        event.preventDefault(); // Prevent default form submission (page reload)
        const trimmedQuery = query.trim();

        if (trimmedQuery) {
            // Navigate to the search results page with the query parameter
            router.push(`/search?q=${encodeURIComponent(trimmedQuery)}`);
            // Optionally clear the input after submission
            // setQuery('');
        } else {
            // Optionally provide feedback if submitted empty, or just do nothing
            console.log("Empty search query submitted.");
        }
    };

    return (
        // Using onSubmit on the form captures Enter key presses in the input
        <form onSubmit={handleSearchSubmit} className={styles.searchForm} role="search">
            {/* Visually hidden label for accessibility */}
            <label htmlFor="site-search" className={styles.visuallyHidden}>Search</label>
            <input
                type="search" // Use semantic search input type
                id="site-search"
                name="q" // Standard query parameter name
                className={`form-input ${styles.searchInput}`} // Use global + module class
                placeholder="Search products..."
                value={query}
                onChange={handleInputChange}
                aria-label="Search products" // Use aria-label as visible label is hidden
            />
            {/* Optional: Add a submit button (could be an icon) */}
             <button type="submit" className={`button button-secondary ${styles.searchButton}`} aria-label="Submit search">
                 {/* Search Icon SVG or Text */}
                 <svg xmlns="http://www.w3.org/2000/svg" height="1em" viewBox="0 0 512 512" fill="currentColor">
                     <path d="M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376c-34.4 25.2-76.8 40-122.7 40C93.1 416 0 322.9 0 208S93.1 0 208 0S416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z"/>
                 </svg>
             </button>
        </form>
    );
};

export default SearchComponent;

// TODO: Create SearchComponent.module.css for custom layout/styling.
// TODO: Integrate this component into Layout.js where the placeholder currently exists.
// TODO: Create the actual search results page at /search.