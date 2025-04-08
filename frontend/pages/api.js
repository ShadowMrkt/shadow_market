export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.yourdomain.com';

export async function fetchProducts() {
  const res = await fetch(`${API_BASE_URL}/api/products/`);
  if (!res.ok) {
    throw new Error('Failed to fetch products');
  }
  return res.json();
}
