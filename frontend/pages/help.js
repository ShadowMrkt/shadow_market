import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import Layout from '../components/Layout';

export default function Help() {
  const router = useRouter();
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    // Replace with actual authentication logic.
    setAuthenticated(true);
  }, []);

  if (!authenticated) {
    router.push('/login');
    return null;
  }

  return (
    <Layout>
      <h1>Shadow Market Help &amp; Guidance</h1>
      <p>Welcome to Shadow Market! This page provides an in‑depth guide to using every feature of the platform.</p>
    </Layout>
  );
}
