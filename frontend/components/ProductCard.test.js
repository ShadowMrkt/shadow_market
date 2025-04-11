// frontend/components/ProductCard.test.js
// --- REVISION HISTORY ---
// 2025-04-09: Rev 1 - Initial creation. Tests for ProductCard component.
//           - Mocks next/link and next/image.
//           - Tests rendering with full data, missing data, and price acceptance logic.

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import ProductCard from './ProductCard'; // Adjust path as needed
import { CURRENCY_SYMBOLS } from '../utils/constants'; // Import constants

// Mock next/link
jest.mock('next/link', () => ({ children, href, passHref, legacyBehavior, ...rest }) => (
  <a href={href} {...rest}>{children}</a>
));

// Mock next/image
jest.mock('next/image', () => ({ src, alt, width, height, layout, objectFit, className, priority }) => (
  // eslint-disable-next-line @next/next/no-img-element
  <img src={src} alt={alt} width={width} height={height} className={className} style={{ objectFit: objectFit }} loading={priority ? 'eager' : 'lazy'}/>
));

// Sample Product Data
const mockProduct = {
  id: 'prod123',
  slug: 'test-product-slug',
  name: 'My Test Product',
  vendor: { username: 'testvendor' },
  category: { name: 'Test Category', slug: 'test-category' },
  price_xmr: '1.250000',
  price_btc: '0.00100000',
  price_eth: null, // Price not set for ETH
  accepted_currencies: ['XMR', 'BTC'], // Accepts XMR and BTC
  thumbnail_url: '/images/test-product.jpg',
  // average_rating: 4.5, // Example optional fields
  // sales_count: 100,
};

const mockProductMinimal = {
  id: 'prod456',
  slug: 'minimal-product',
  name: 'Minimal Product',
  vendor: null, // No vendor
  category: null, // No category
  price_xmr: '0.5',
  price_btc: null,
  price_eth: null,
  accepted_currencies: ['XMR'], // Only XMR
  thumbnail_url: null, // No thumbnail
};


describe('ProductCard Component', () => {
  test('renders correctly with full product data', () => {
    render(<ProductCard product={mockProduct} />);

    // Check Image
    const img = screen.getByRole('img', { name: /My Test Product - Product Image/i });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', mockProduct.thumbnail_url);

    // Check Category Link
    const categoryLink = screen.getByRole('link', { name: mockProduct.category.name });
    expect(categoryLink).toBeInTheDocument();
    expect(categoryLink).toHaveAttribute('href', `/categories/${mockProduct.category.slug}`);

    // Check Vendor Link
    const vendorLink = screen.getByRole('link', { name: mockProduct.vendor.username });
    expect(vendorLink).toBeInTheDocument();
    expect(vendorLink).toHaveAttribute('href', `/vendors/${mockProduct.vendor.username}`);

    // Check Product Name Link
    const productLink = screen.getByRole('link', { name: mockProduct.name });
    expect(productLink).toBeInTheDocument();
    expect(productLink).toHaveAttribute('href', `/products/${mockProduct.slug}`);
    expect(productLink).toHaveTextContent(mockProduct.name);

    // Check Prices and Acceptance
    const xmrPrice = screen.getByText((content, node) => node.textContent === `${CURRENCY_SYMBOLS.XMR} 1.250000`);
    expect(xmrPrice).toBeInTheDocument();
    expect(xmrPrice).toHaveClass('accepted');
    expect(xmrPrice.closest('p')).toHaveAttribute('title', 'XMR Accepted');

    const btcPrice = screen.getByText((content, node) => node.textContent === `${CURRENCY_SYMBOLS.BTC} 0.00100000`);
    expect(btcPrice).toBeInTheDocument();
    expect(btcPrice).toHaveClass('accepted');
    expect(btcPrice.closest('p')).toHaveAttribute('title', 'BTC Accepted');

    // ETH price is null, shouldn't render
    expect(screen.queryByText(CURRENCY_SYMBOLS.ETH, { exact: false })).not.toBeInTheDocument();
  });

  test('renders correctly with minimal product data', () => {
    render(<ProductCard product={mockProductMinimal} />);

     // Check Image (should use placeholder)
    const img = screen.getByRole('img', { name: /Minimal Product - Product Image/i });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', '/images/placeholder-product.png'); // Check placeholder

    // Category and Vendor should not be rendered
    expect(screen.queryByText(/Category:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Vendor:/i)).not.toBeInTheDocument();

     // Check Product Name Link
    const productLink = screen.getByRole('link', { name: mockProductMinimal.name });
    expect(productLink).toBeInTheDocument();
    expect(productLink).toHaveAttribute('href', `/products/${mockProductMinimal.slug}`);
    expect(productLink).toHaveTextContent(mockProductMinimal.name);

    // Check Prices and Acceptance
    const xmrPrice = screen.getByText((content, node) => node.textContent === `${CURRENCY_SYMBOLS.XMR} 0.500000`);
    expect(xmrPrice).toBeInTheDocument();
    expect(xmrPrice).toHaveClass('accepted');
    expect(xmrPrice.closest('p')).toHaveAttribute('title', 'XMR Accepted');

    // BTC and ETH prices are null, shouldn't render
    expect(screen.queryByText(CURRENCY_SYMBOLS.BTC, { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByText(CURRENCY_SYMBOLS.ETH, { exact: false })).not.toBeInTheDocument();
  });

   test('renders price as not accepted if currency not in accepted_currencies', () => {
     const productWithBtcNotAccepted = {
       ...mockProduct,
       accepted_currencies: ['XMR'], // Only accept XMR
     };
    render(<ProductCard product={productWithBtcNotAccepted} />);

    // Check BTC Price is rendered but marked as not accepted
    const btcPrice = screen.getByText((content, node) => node.textContent === `${CURRENCY_SYMBOLS.BTC} 0.00100000`);
    expect(btcPrice).toBeInTheDocument();
    expect(btcPrice).toHaveClass('notAccepted'); // Check class
    expect(btcPrice.closest('p')).toHaveAttribute('title', 'BTC Not Accepted'); // Check title
  });

  test('returns null if no product prop is provided', () => {
    const { container } = render(<ProductCard product={null} />);
    // Check that the container is empty
    expect(container.firstChild).toBeNull();
  });

  // Optional: Add tests for rating/sales display if those props are implemented
  // test('displays rating and sales count if provided', () => { ... });

});