// frontend/pages/index.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Migrated to CSS Modules, improved getStaticProps error handling, refined content structure.
//           - Replaced className string with CSS Module import (Index.module.css).
//           - Added try/catch block in getStaticProps.
//           - Added check for empty products array in render.
//           - Changed H1 title to be more descriptive.
//           - Added basic container class.
//           - Added revision history block.

import React from 'react';
import { fetchProducts } from '../utils/api'; // Assumes fetchProducts fetches public product data
import Layout from '../components/Layout';
import ProductCard from '../components/ProductCard'; // Assumes this component exists
import styles from './Index.module.css'; // Import CSS Module

// Component to render the Home page
export default function Home({ products, error }) {
  return (
    <Layout>
      <div className={styles.container}>
        {/* Changed title to be more descriptive than just site name */}
        <h1 className={styles.title}>Featured Products</h1>

        {/* Display error message if fetching failed during build/revalidation */}
        {error && (
          <div className={styles.error}>
             <p>Could not load products at this time. Please try again later.</p>
             <p><small>Error: {error}</small></p>
          </div>
        )}

        {/* Display products or a 'no products' message */}
        {!error && products && products.length > 0 ? (
          <div className={styles.productsGrid}>
            {products.map((product) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>
        ) : (
          // Show message only if no error occurred but products are empty
          !error && <p className={styles.noProducts}>No products are currently available.</p>
        )}
      </div>
    </Layout>
  );
}

// Fetch data at build time (Static Site Generation)
export async function getStaticProps() {
  // Set a revalidation time (in seconds) to periodically update the data
  const REVALIDATE_TIME = 60; // Re-fetch every 60 seconds

  try {
    // Assuming fetchProducts can be called without authentication context here
    const products = await fetchProducts({ limit: 20 }); // Example: fetch first 20 products
    // console.log(`Workspaceed ${products?.length || 0} products for static home page.`);

    // Ensure products is an array, even if API returns null/undefined
    const safeProducts = Array.isArray(products) ? products : [];

    return {
      props: {
        products: safeProducts,
        error: null, // No error
      },
      revalidate: REVALIDATE_TIME, // Enable Incremental Static Regeneration (ISR)
    };
  } catch (err) {
    console.error("Error fetching products in getStaticProps (index.js):", err);
    // In case of error, return empty products array and an error message
    // This prevents the build from failing and shows an error on the page
    return {
      props: {
        products: [],
        error: err.message || "Failed to fetch products.",
      },
      // Consider shorter revalidate time on error? Or stick to standard time.
      revalidate: REVALIDATE_TIME,
    };
    // Alternatively, to show a 404 page on error:
    // return { notFound: true };
  }
}

// TODO: Create Index.module.css to style .container, .title, .productsGrid, .noProducts, .error
// TODO: Ensure ProductCard component exists and handles the 'product' prop correctly.
// TODO: Ensure fetchProducts API endpoint exists and works without auth for this context.