// frontend/pages/products/index.js
// <<< REVISED FOR ENTERPRISE GRADE: Added Filters UI, Robust State/URL Sync, Clearer Feedback >>>

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link'; // Keep Link for potential use
import { getProducts, getCategories } from '../../utils/api'; // <<< Ensure path is correct, ADDED getCategories >>>
import Layout from '../../components/Layout'; // <<< Ensure path is correct >>>
// <<< ADDED: Import necessary components and constants >>>
import ProductCard from '../../components/ProductCard';
import PaginationControls from '../../components/PaginationControls';
import LoadingSpinner from '../../components/LoadingSpinner';
import FormError from '../../components/FormError';
import { DEFAULT_PAGE_SIZE } from '../../utils/constants'; // Import page size
import debounce from 'lodash.debounce'; // Already imported

// Styles (ensure consistency with globals.css)
const styles = {
    container: { maxWidth: '1200px', margin: '2rem auto', padding: '1rem' }, // Wider container?
    title: { marginBottom: '1.5rem', borderBottom: '1px solid #eee', paddingBottom: '0.5rem' },
    mainContent: { display: 'grid', gridTemplateColumns: '220px 1fr', gap: '2rem', alignItems: 'start' }, // Sidebar + Grid layout
    sidebar: { background: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #dee2e6', position: 'sticky', top: '2rem' }, // Sticky sidebar
    filterGroup: { marginBottom: '1.5rem' },
    filterLabel: { fontWeight: 'bold', marginBottom: '0.5rem', display: 'block' },
    productGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }, // Responsive product grid
    loadingContainer: { textAlign: 'center', padding: '4rem', gridColumn: '1 / -1' }, // Span full grid width
    noProductsMessage: { textAlign: 'center', padding: '4rem', fontStyle: 'italic', color: '#6c757d', gridColumn: '1 / -1' },
    // Use global form/button classes (.form-group, .form-label, .form-input, .form-select, .button, etc.)
};

// Define available sorting options
const SORT_OPTIONS = [
    { value: '', label: 'Default (Relevance)' },
    { value: 'price_asc', label: 'Price: Low to High' },
    { value: 'price_desc', label: 'Price: High to Low' },
    { value: 'created_at_desc', label: 'Newest First' },
    // Add other options supported by backend API (e.g., vendor rating)
];

export default function ProductsListPage() {
    const router = useRouter();

    // State for products and fetch status
    const [productsData, setProductsData] = useState({ results: [], count: 0, next: null, previous: null });
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');

    // State for filters and pagination - Initialize from URL query
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedCategory, setSelectedCategory] = useState(''); // <<< ADDED: Category filter state >>>
    const [selectedSort, setSelectedSort] = useState(''); // <<< ADDED: Sorting state >>>
    const [currentPage, setCurrentPage] = useState(1);

    // <<< ADDED: State for categories list >>>
    const [categories, setCategories] = useState([]);
    const [isLoadingCategories, setIsLoadingCategories] = useState(true);

    // --- Effects ---

    // Initialize filters from URL query on mount and route changes
    useEffect(() => {
        if (router.isReady) {
            setSearchTerm(router.query.search || '');
            setSelectedCategory(router.query.category || '');
            setSelectedSort(router.query.ordering || ''); // DRF uses 'ordering'
            setCurrentPage(parseInt(router.query.page || '1', 10));
        }
    }, [router.isReady, router.query]);

    // Fetch categories on mount
    useEffect(() => {
        const fetchCategories = async () => {
            setIsLoadingCategories(true);
            try {
                // <<< BEST PRACTICE: Fetch only needed fields if API supports it >>>
                // Assuming getCategories returns a flat list like [{ name: '...', slug: '...' }]
                const catData = await getCategories({ limit: 200 }); // Fetch all categories (adjust limit?)
                setCategories(catData.results || []);
            } catch (err) {
                console.error("Failed to fetch categories:", err);
                // Non-critical error, maybe show a subtle message or just don't show filter
            } finally { setIsLoadingCategories(false); }
        };
        fetchCategories();
    }, []); // Fetch only once

    // Debounced function to update URL/fetch products after search input stops typing
    const debouncedUpdateSearch = useMemo(
        () => debounce((value) => {
            updateFilters({ search: value, page: 1 }); // Reset to page 1 on new search
        }, 500), // 500ms debounce delay
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [] // No dependencies, create once
    );

    // Update search term state immediately, but debounce the actual filter update
    const handleSearchChange = (e) => {
        const value = e.target.value;
        setSearchTerm(value);
        debouncedUpdateSearch(value);
    };

    // Function to update filters in state and URL query parameters
    const updateFilters = useCallback((newFilters) => {
        // Merge new filters with existing ones from current state
        const currentParams = {
            search: searchTerm,
            category: selectedCategory,
            ordering: selectedSort,
            page: currentPage,
        };
        const mergedFilters = { ...currentParams, ...newFilters };

        // Prepare query params, removing empty values
        const queryParams = {};
        if (mergedFilters.search) queryParams.search = mergedFilters.search;
        if (mergedFilters.category) queryParams.category = mergedFilters.category;
        if (mergedFilters.ordering) queryParams.ordering = mergedFilters.ordering;
        if (mergedFilters.page && mergedFilters.page > 1) queryParams.page = mergedFilters.page; // Only include page > 1

        // Push changes to URL
        router.push({
            pathname: '/products',
            query: queryParams,
        }, undefined, { shallow: true }); // Use shallow routing to avoid full page reload

        // Update state (though useEffect listening to router.query will trigger fetch)
        // It's often good to update state directly too for responsiveness if needed
        // setSearchTerm(mergedFilters.search || '');
        // setSelectedCategory(mergedFilters.category || '');
        // setSelectedSort(mergedFilters.ordering || '');
        // setCurrentPage(mergedFilters.page || 1);

    }, [router, searchTerm, selectedCategory, selectedSort, currentPage]); // Depend on state values

    // Fetch products whenever relevant query parameters change
    useEffect(() => {
        if (!router.isReady) return; // Wait for router

        const fetchProducts = async () => {
            setIsLoading(true); setError('');
            const params = {
                limit: DEFAULT_PAGE_SIZE,
                offset: (currentPage - 1) * DEFAULT_PAGE_SIZE,
                search: searchTerm || undefined, // Send undefined if empty
                category: selectedCategory || undefined,
                ordering: selectedSort || undefined,
            };
            // Remove undefined params before sending
            Object.keys(params).forEach(key => params[key] === undefined && delete params[key]);

            try {
                console.log("Fetching products with params:", params); // Debug log
                const data = await getProducts(params);
                setProductsData(data); // Expecting { count, next, previous, results }
            } catch (err) {
                console.error("Fetch products failed:", err);
                setError(err.message || "Failed to load products. Please try refreshing.");
                setProductsData({ results: [], count: 0, next: null, previous: null }); // Reset data on error
            } finally { setIsLoading(false); }
        };

        fetchProducts();
    }, [router.isReady, currentPage, searchTerm, selectedCategory, selectedSort]); // Re-fetch when these change


    // --- Render Logic ---

    return (
        <Layout>
            <div style={styles.container}>
                <h1 style={styles.title}>Browse Products</h1>

                {/* <<< ADDED: Display general fetch error >>> */}
                 <FormError message={error} />

                 <div style={styles.mainContent}>
                    {/* --- Sidebar Filters --- */}
                     <aside style={styles.sidebar}>
                         <h4>Filters & Sort</h4>

                         {/* Search Filter */}
                         <div style={styles.filterGroup} className="form-group">
                            <label htmlFor="search" style={styles.filterLabel} className="form-label">Search</label>
                            <input
                                type="search"
                                id="search"
                                value={searchTerm}
                                onChange={handleSearchChange} // Uses debounced update
                                placeholder="Search products..."
                                className="form-input"
                             />
                         </div>

                        {/* Category Filter */}
                         <div style={styles.filterGroup} className="form-group">
                             <label htmlFor="category" style={styles.filterLabel} className="form-label">Category</label>
                            <select
                                id="category"
                                value={selectedCategory}
                                onChange={(e) => updateFilters({ category: e.target.value, page: 1 })} // Reset page on filter change
                                className="form-select"
                                disabled={isLoadingCategories}
                            >
                                 <option value="">All Categories</option>
                                 {categories.map(cat => (
                                    <option key={cat.slug} value={cat.slug}>{cat.name}</option>
                                 ))}
                             </select>
                             {isLoadingCategories && <small className="form-help-text">Loading categories...</small>}
                         </div>

                         {/* Sort Options */}
                         <div style={styles.filterGroup} className="form-group">
                            <label htmlFor="sort" style={styles.filterLabel} className="form-label">Sort By</label>
                            <select
                                id="sort"
                                value={selectedSort}
                                onChange={(e) => updateFilters({ ordering: e.target.value, page: 1 })} // Reset page
                                className="form-select"
                             >
                                {SORT_OPTIONS.map(opt => (
                                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                            </select>
                         </div>

                         {/* TODO: Add Price Range filter? Needs backend support */}
                         {/* TODO: Add Vendor filter? Needs backend support/UI */}

                     </aside>

                     {/* --- Product Grid & Pagination --- */}
                     <main>
                        {isLoading && (
                            <div style={styles.loadingContainer}>
                                <LoadingSpinner message="Loading products..." />
                            </div>
                        )}

                        {!isLoading && !error && productsData.results.length > 0 && (
                            <>
                                <div style={styles.productGrid}>
                                     {productsData.results.map(product => (
                                        <ProductCard key={product.id} product={product} />
                                     ))}
                                </div>
                                 <PaginationControls
                                    currentPage={currentPage}
                                    totalPages={Math.ceil(productsData.count / DEFAULT_PAGE_SIZE)}
                                    totalCount={productsData.count}
                                    onPrevious={() => updateFilters({ page: currentPage - 1 })}
                                    onNext={() => updateFilters({ page: currentPage + 1 })}
                                    isLoading={isLoading} // Disable pagination while loading next page
                                />
                            </>
                        )}

                        {!isLoading && !error && productsData.results.length === 0 && (
                             <div style={styles.noProductsMessage}>
                                 No products found matching your criteria. Try adjusting your filters.
                             </div>
                        )}
                    </main>
                 </div>
            </div>
        </Layout>
    );
}