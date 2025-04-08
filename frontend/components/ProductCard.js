// frontend/components/ProductCard.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Migrated to CSS Modules, added next/image, Decimal.js price formatting, improved a11y.
//           - Replaced inline styles with imports from ProductCard.module.css.
//           - Removed local CURRENCY_SYMBOLS, import from constants.
//           - Used Decimal.js for accurate price formatting.
//           - Replaced image placeholder with next/image component.
//           - Added aria-labels and titles for price acceptance status.
//           - Added placeholders for rating/sales.
//           - Added revision history block.

import React from 'react';
import Link from 'next/link';
import Image from 'next/image'; // Import Next.js Image component
import { Decimal } from 'decimal.js'; // Import Decimal.js for precise calculations
import { CURRENCY_SYMBOLS } from '../utils/constants'; // Import central currency symbols
import styles from './ProductCard.module.css'; // Import CSS Module

// TODO: Consider moving price formatting logic to utils/formatters.js if reused heavily
const formatPricePrecise = (price, currency) => {
    if (price === null || price === undefined) return null; // Return null if no price
    try {
        const p = new Decimal(price);
        let dp; // decimal places
        if (currency === 'BTC') dp = 8;
        else if (currency === 'XMR') dp = 6; // Common display, though Monero goes to 12
        else if (currency === 'ETH') dp = 6; // Common display
        else dp = 2; // Default for other/fiat?
        return p.toFixed(dp);
    } catch (e) {
        console.error("Price formatting error (Decimal.js):", e);
        return 'Error';
    }
};


export default function ProductCard({ product }) {
    if (!product) {
        return null; // Don't render if no product data
    }

    // Destructure product data - add fallbacks for safety
    const {
        slug,
        name = 'Unnamed Product',
        vendor, // Assuming vendor is { username: 'vendorName' }
        category, // Assuming category is { name: 'CatName', slug: 'cat-slug' }
        price_xmr,
        price_btc,
        price_eth,
        accepted_currencies = [],
        thumbnail_url, // TODO: Confirm actual prop name for image URL
        average_rating, // Example optional prop
        sales_count, // Example optional prop
    } = product;

    // Construct image source URL - use placeholder if none provided
    const imageUrl = thumbnail_url || '/images/placeholder-product.png'; // TODO: Ensure placeholder image exists at /public/images/placeholder-product.png

    // Helper to render price with acceptance status
    const renderPrice = (currency, price) => {
        const formattedPrice = formatPricePrecise(price, currency);
        // Only render if price is formatted successfully
        if (formattedPrice === null || formattedPrice === 'Error') {
             // Optionally render something if currency is accepted but price missing/error
             // if (accepted_currencies.includes(currency)) {
             //    return <p className={styles.priceNotSet}>{CURRENCY_SYMBOLS[currency] || currency} Price Unavailable</p>
             // }
             return null; // Don't show price if unavailable/error
        }

        const symbol = CURRENCY_SYMBOLS[currency] || currency;
        const accepts = accepted_currencies.includes(currency);
        const acceptanceClass = accepts ? styles.accepted : styles.notAccepted;
        const acceptanceText = accepts ? `${currency} Accepted` : `${currency} Not Accepted`;

        return (
            <p
                className={`${styles.price} ${acceptanceClass}`}
                title={acceptanceText}
                aria-label={`${symbol} ${formattedPrice} - ${acceptanceText}`}
            >
                {symbol} {formattedPrice}
                {/* Optional: Add explicit text indicator for screen readers */}
                {/* <span className={styles.visuallyHidden}> - {acceptanceText}</span> */}
            </p>
        );
    };

    return (
        <div className={styles.card}>
            <div className={styles.imageWrapper}>
                 <Link href={`/products/${slug}`} passHref legacyBehavior>
                    <a aria-label={`View product: ${name}`}> {/* Wrap Image in Link/anchor */}
                        <Image
                            src={imageUrl}
                            alt={`${name} - Product Image`} // Descriptive alt text
                            width={300} // Provide base width (adjust as needed)
                            height={200} // Provide base height (adjust as needed)
                            layout="responsive" // Makes image scale with wrapper
                            objectFit="cover" // How image should fit (cover, contain, etc.)
                            className={styles.productImage} // Optional class for specific image styling
                            // TODO: Consider adding placeholder="blur" and blurDataURL if using static imports or generating base64 previews
                        />
                    </a>
                </Link>
            </div>

            <div className={styles.cardContent}>
                 {category && (
                    <div className={styles.category}>
                        Category: <Link href={`/categories/${category.slug}`} className={styles.link}>{category.name}</Link>
                    </div>
                 )}
                {vendor && (
                    <div className={styles.vendor}>
                        Vendor: <Link href={`/vendors/${vendor.username}`} className={styles.link}>{vendor.username}</Link>
                    </div>
                )}

                <Link href={`/products/${slug}`} passHref legacyBehavior>
                     <a className={styles.nameLink}>{name}</a>
                </Link>

                {/* Optional: Rating and Sales Info */}
                {/* <div className={styles.metaInfo}>
                    {average_rating !== null && average_rating !== undefined && (
                        <span>⭐ {average_rating.toFixed(1)}</span>
                    )}
                    {sales_count !== null && sales_count !== undefined && (
                        <span> | {sales_count} Sales</span>
                    )}
                </div> */}


                <div className={styles.prices}>
                    {renderPrice('XMR', price_xmr)}
                    {renderPrice('BTC', price_btc)}
                    {renderPrice('ETH', price_eth)}
                    {/* Add more currencies if needed */}
                </div>
            </div>
        </div>
    );
}

// TODO: Create ProductCard.module.css with styles for card, imageWrapper, cardContent, links, prices, etc.
// TODO: Verify product prop structure (thumbnail_url, vendor.username, category.slug, average_rating, sales_count).
// TODO: Ensure /public/images/placeholder-product.png exists or update placeholder path.