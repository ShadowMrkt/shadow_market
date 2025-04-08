// frontend/pages/pgp-guide.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global CSS classes, removed inline styles.
//           - Used .container-narrow, .card, .code-block, .warning-message global classes.
//           - Applied margin utilities (e.g., mb-3) for list item spacing.
//           - Ensured external links have target/rel attributes.
//           - Added revision history block.

import React from 'react';
import Layout from '../components/Layout'; // Import main layout
import Link from 'next/link'; // Optional: For linking within the site

// NOTE: This component now relies on global CSS classes defined in globals.css
// (e.g., .container-narrow, .card, .p-4, .mb-*, .code-block, .warning-message, heading styles, etc.)

export default function PgpGuidePage() {
    return (
        <Layout>
            {/* Use global narrow container for better text readability */}
            <div className="container-narrow">
                {/* Use global card style for content section */}
                <div className="card p-4"> {/* Add padding utility class */}
                    <h1 className="mb-4">PGP Setup & Usage Guide</h1>

                    <p>
                        Pretty Good Privacy (PGP), often implemented using GnuPG (Gnu Privacy Guard), is essential for using Shadow Market securely.
                        It provides strong two-factor authentication (2FA) for your account and allows for secure, encrypted communication.
                    </p>

                    {/* Use global warning message style */}
                    <div className="warning-message">
                        <strong>Important:</strong> Your account security depends on keeping your PGP <strong>private key</strong> and its <strong>passphrase</strong> secure and secret. Never share your private key or passphrase with anyone, including market staff. Back up your private key securely. If you lose access to your private key, you will likely lose access to your account permanently.
                    </div>

                    <section>
                        <h2>1. Why PGP?</h2>
                        <ul>
                            {/* Use margin bottom utility for spacing */}
                            <li className="mb-2"><strong>Mandatory 2FA:</strong> Logging into Shadow Market requires signing a unique challenge message with your PGP private key. This proves you control the key linked to your account, even if someone steals your password.</li>
                            <li className="mb-2"><strong>Encrypted Communication:</strong> PGP is used for encrypting sensitive information like support ticket messages and potentially shipping details, ensuring only the intended recipient can read them.</li>
                        </ul>
                    </section>

                    <section className="mt-4">
                        <h2>2. Getting PGP Software</h2>
                        <p>You need PGP software installed on your computer (preferably on a secure OS like Tails or Whonix). Common options include:</p>
                        <ul>
                            <li className="mb-2"><strong>GnuPG (gpg):</strong> The command-line standard. Available for Linux, macOS, Windows. (<a href="https://gnupg.org/" target="_blank" rel="noopener noreferrer">gnupg.org</a>)</li>
                            <li className="mb-2"><strong>Kleopatra:</strong> A popular graphical interface for GnuPG, available for Windows and Linux (part of Gpg4win / KDE).</li>
                            <li className="mb-2"><strong>GPG Suite / GPG Keychain:</strong> A popular option for macOS. (<a href="https://gpgtools.org/" target="_blank" rel="noopener noreferrer">gpgtools.org</a>)</li>
                            {/* Add other relevant software recommendations */}
                        </ul>
                        <p>Download software only from official sources and verify signatures if possible.</p>
                    </section>

                    <section className="mt-4">
                        <h2>3. Generating Your PGP Key Pair</h2>
                        <p>If you don't already have a strong PGP key pair (public and private key), you need to generate one. Follow the instructions for your chosen software. General steps often involve:</p>
                        <ol>
                            <li className="mb-2">Choosing the key type (RSA, ECC - use modern defaults like RSA 4096 or Ed25519/Curve25519).</li>
                            <li className="mb-2">Choosing the key size (e.g., 4096 bits for RSA).</li>
                            <li className="mb-2">Setting an expiration date (optional, but recommended).</li>
                            <li className="mb-2">Providing a User ID (often Name and Email, but you can use pseudonyms or leave email blank for anonymity).</li>
                            <li className="mb-2">Setting a <strong>strong, unique passphrase</strong> to protect your private key. Store this passphrase securely (e.g., in a trusted password manager).</li>
                        </ol>
                        <p><strong>Security Tip:</strong> Generate your keys on an offline, secure system if possible.</p>
                    </section>

                    <section className="mt-4">
                        <h2>4. Exporting Your Public Key (for Registration)</h2>
                        <p>During registration or on your profile page on Shadow Market, you must provide your PGP <strong>public</strong> key block. Your software will have an option to export your public key. Ensure you export it in ASCII-armored format. It will look similar to this:</p>
                        {/* Use global code block style */}
                        <pre className="code-block"><code>
{`-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: GnuPG vX.X.X (...)

mQINBF... [LONG BLOCK OF ALPHANUMERIC CHARACTERS] ... ABC=
-----END PGP PUBLIC KEY BLOCK-----`}
                        </code></pre>
                        <p>Copy the <em>entire</em> block, including the BEGIN and END lines, and paste it into the appropriate field.</p>
                    </section>

                     <section className="mt-4">
                        <h2>5. Signing the Login Challenge (PGP 2FA)</h2>
                        <p>When you log in (after entering username/password), you will be presented with a unique challenge message block.</p>
                        <ol>
                              <li className="mb-3">Copy the entire challenge text block presented on the login page (use the 'Copy Challenge' button if available).</li>
                              <li className="mb-3">Open your PGP software (e.g., Kleopatra's Clipboard tools, or `gpg` command line).</li>
                              <li className="mb-3">Use the "Sign" function (or equivalent) with your <strong>private key</strong> associated with your market account. Ensure you select the correct key if you have multiple. You will likely need to enter your PGP passphrase.</li>
                              <li className="mb-3">Make sure you create an <strong>ASCII armored signature</strong>. Depending on your tool, this might be called "clearsign" (which includes the original message) or a "detached signature" (which doesn't). The market should accept either format containing the signature block. Do *not* encrypt the challenge.</li>
                              <li className="mb-3">The signature block itself will look similar to this:</li>
                         </ol>
                        {/* Use global code block style */}
                         <pre className="code-block"><code>
{`-----BEGIN PGP SIGNATURE-----
Version: GnuPG vX.X.X (...)

iQIzBAABCAAdFiEE... [LONG BLOCK OF ALPHANUMERIC CHARACTERS] ...xyz=
-----END PGP SIGNATURE-----`}
                         </code></pre>
                         <p>Copy the <strong>entire signature block</strong> (including BEGIN/END lines, and potentially the signed message if using clearsign) and paste it into the signature field on the Shadow Market login page to complete your login.</p>
                    </section>

                    <p className="mt-4 text-muted small"> {/* Use global text utility classes */}
                         Disclaimer: This is a general guide. Specific steps may vary depending on your operating system and PGP software version. Please consult the official documentation for your chosen software for detailed instructions. Practice good OpSec at all times.
                     </p>

                </div>
            </div>
        </Layout>
    );
}