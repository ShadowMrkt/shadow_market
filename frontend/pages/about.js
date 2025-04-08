// frontend/pages/about.js
import React from 'react';
import Layout from '../components/Layout'; // Import main layout
import Link from 'next/link'; // Optional: For linking

// Optional: Use global styles or define specific ones
const styles = {
    container: { maxWidth: '800px', margin: '2rem auto', padding: '1rem' }, // Use container-narrow?
    pgpKeyBlock: { // Style from globals.css or specific
        whiteSpace: 'pre-wrap', wordWrap: 'break-word', background: '#f8f9fa',
        padding: '1rem', border: '1px solid #dee2e6', borderRadius: '4px',
        maxHeight: '400px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.9em',
        marginTop: '1rem'
    },
    fingerprint: { fontWeight: 'bold', fontFamily: 'monospace' }
    // Add other styles if needed
};

export default function AboutPage() {
    // !!! REPLACE PLACEHOLDER PGP KEY WITH YOUR ACTUAL MARKET KEY !!!
    const marketPgpPublicKey = `-----BEGIN PGP PUBLIC KEY BLOCK-----

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
r3Jr9zFS8QA=
=S/W/
-----END PGP PUBLIC KEY BLOCK-----`;

    // !!! REPLACE WITH YOUR ACTUAL MARKET KEY FINGERPRINT !!!
    const marketPgpFingerprint = "C6B7 7403 03E7 6DA5 354F AB18 52F8 4D26 A4D5 B4F0";

    return (
        <Layout>
            {/* Use global .container or .container-narrow */}
            <div className="container" style={styles.container}>
                {/* Use global .card for styling */}
                <div className="card p-4">
                    <h1 className="mb-4">About Shadow Market</h1>

                    <section>
                        <h2>Our Philosophy</h2>
                        <p>
                            Shadow Market is built on the principles of privacy, security, and user empowerment.
                            We believe in providing a resilient platform for commerce outside the confines of traditional,
                            surveilled systems. Our commitment is to creating a fair and secure environment
                            using strong cryptography and operational security best practices.
                        </p>
                        {/* Add more about your market's specific mission/values */}
                    </section>

                    <section className="mt-4">
                        <h2>Key Security Features</h2>
                        <ul>
                            <li><strong>Exclusive Tor Operation:</strong> Accessible only via the Tor network for anonymity.</li>
                            <li><strong>Mandatory PGP 2FA:</strong> All accounts require PGP for robust two-factor authentication.</li>
                            <li><strong>Multi-Signature Escrow (Conceptual):</strong> Utilizing 2-of-3 multi-sig concepts for XMR, BTC, and ETH to minimize trust and protect funds during transactions (pending full implementation and audit).</li>
                            <li><strong>End-to-End Encrypted Communication:</strong> Internal support ticket system uses PGP encryption. No email is used. Vendor shipping info is encrypted for the vendor.</li>
                            <li><strong>Security-Focused Development:</strong> Continuous review, hardened configurations, and emphasis on secure coding practices.</li>
                            <li><strong>Warrant Canary:</strong> See our <Link href="/canary">Canary page</Link> for regular updates signed with our official key.</li>
                        </ul>
                        <p>
                            Learn more about our operations and rules on the <Link href="/faq">FAQ</Link> and <Link href="/rules">Rules</Link> pages.
                        </p>
                    </section>

                    <section className="mt-4">
                        <h2>Official Market PGP Key</h2>
                        <p>
                            This is the **only** official PGP key for Shadow Market administration and communication.
                            Use it to verify the Warrant Canary signature and encrypt any sensitive communication directed towards market staff (though using the support ticket system is preferred).
                            **Always verify the fingerprint.** Do not trust keys provided through other channels.
                        </p>
                        <p>
                            <strong>Fingerprint:</strong> <code style={styles.fingerprint}>{marketPgpFingerprint}</code>
                        </p>
                        <p><strong>Public Key Block:</strong></p>
                        <pre style={styles.pgpKeyBlock}><code>{marketPgpPublicKey}</code></pre>
                        <p>Import this key into your PGP software (e.g., GPG, Kleopatra).</p>
                    </section>

                    {/* Optional: Contact info (via ticket system), Team info (anonymous) */}

                </div>
            </div>
        </Layout>
    );
}