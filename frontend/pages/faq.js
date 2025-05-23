// frontend/pages/faq.js
// --- REVISION HISTORY ---
// 2025-04-28: Rev 5 - Filled in placeholder content for "How do I become a vendor?". (Gemini)
// 2025-04-09: Rev 4 - Updated auto-finalize deadline content based on user input.
// 2025-04-09: Rev 3 - Updated "Are there market fees?" content based on user input.
// 2025-04-09: Rev 2 - Updated "What is Shadow Market?" content based on user input.
// 2025-04-07: Rev 1 - Applied global classes, used CSS Module for Q&A styling.
//           - Removed inline styles object.
//           - Applied global .container-narrow, .card, .p-4, .mb-*, .mt-* classes.
//           - Created Faq.module.css for custom .question and .answer styles (dark theme).
//           - Added TODO comments for content placeholders.
//           - Verified internal links.
//           - Added revision history block.

import React from 'react';
import Layout from '../components/Layout'; // Import main layout
import Link from 'next/link';
import styles from './Faq.module.css'; // Import CSS Module for custom styles

// NOTE: This component relies on global CSS classes from globals.css
// (e.g., .container-narrow, .card, .p-4, .mb-*, .mt-*, heading styles, etc.)
// and custom styles from Faq.module.css (.question, .answer).

export default function FaqPage() {
    return (
        <Layout>
            {/* Use global narrow container */}
            <div className="container-narrow">
                 {/* Use global card style with padding */}
                <div className="card p-4">
                    <h1 className="mb-4">Frequently Asked Questions (FAQ)</h1>

                    {/* General Section */}
                    <section>
                        <h2>General</h2>
                        <h3 className={styles.question}>Q: What is Shadow Market?</h3>
                        <p className={styles.answer}>
                            A: Shadow Market is a next-generation, Tor-based marketplace engineered from the ground up with paramount focus on state-of-the-art security and user privacy, learning from the successes and failures of past markets. Our specific goals are to provide a resilient and trustworthy platform by mandating cutting-edge security practices, including:
                        </p>
                        <ul className={`${styles.answer} list-disc pl-4`}> {/* Apply answer style and list style */}
                            <li className="mb-2">
                                <strong>Mandatory PGP:</strong> Used not only for login (2FA) but also required for signing all critical actions (withdrawals, order finalization, profile changes) to ensure user intent and non-repudiation.
                            </li>
                            <li className="mb-2">
                                <strong>Modern Authentication:</strong> Support for WebAuthn/FIDO2 alongside PGP for flexible and secure access.
                            </li>
                            <li className="mb-2">
                                <strong>Robust Multi-Signature Escrow:</strong> Utilizing 2-of-3 multi-sig as standard for all transactions, employing Bitcoin Taproot and native Monero multi-sig for enhanced privacy and security of funds. Direct payments are discouraged or disabled.
                            </li>
                            <li className="mb-2">
                                <strong>Immutable Ledger:</strong> An internal, double-entry accounting system meticulously tracks all platform value, subject to constant reconciliation and integrity checks.
                            </li>
                            <li className="mb-2">
                                <strong>Operational Security:</strong> Built with hardened infrastructure principles, leveraging tools like HashiCorp Vault for secrets management, and designed exclusively for the Tor network to maximize user anonymity.
                            </li>
                            <li className="mb-2">
                                <strong>Familiar Structure, Enhanced Security:</strong> While offering categories and core functionality inspired by legendary markets, every feature is implemented with modern security paradigms to resist historical attack vectors and protect users.
                            </li>
                        </ul>

                        <h3 className={styles.question}>Q: Is this market secure?</h3>
                        <p className={styles.answer}>
                            A: We employ several security measures, including mandatory PGP 2FA, multi-signature escrow, encrypted messaging (where applicable), and operate exclusively on Tor. However, absolute security cannot be guaranteed. Users must also practice good Operational Security (OpSec). See our <Link href="/rules">Rules page</Link> for more details.
                        </p>

                         <h3 className={styles.question}>Q: Are there market fees?</h3>
                         <p className={styles.answer}>
                            A: Yes, a standard market fee applies to all finalized orders to cover operational costs, security infrastructure, and continuous development. Since Shadow Market exclusively uses multi-signature escrow for all transactions to maximize user fund security, the current fee is a flat 2.5%, deducted from the vendor payout automatically during the escrow release process. While this is the standard rate, specific promotional adjustments or variations based on vendor tier might occasionally apply; always check the official <Link href="/rules">Rules page</Link> for the most current and definitive details.
                         </p>
                    </section>

                    {/* PGP & Security Section */}
                    <section className="mt-4">
                        <h2>PGP & Security</h2>
                        <h3 className={styles.question}>Q: Why is PGP mandatory?</h3>
                        <p className={styles.answer}>
                            A: PGP provides essential two-factor authentication (2FA) for logins, preventing unauthorized access even if your password is compromised. It is also used for encrypting sensitive communications like shipping details (unless you pre-encrypt) and potentially support messages. See our <Link href="/pgp-guide">PGP Guide</Link> for setup instructions.
                        </p>

                        <h3 className={styles.question}>Q: I lost my PGP key / password. Can I recover my account?</h3>
                        <p className={`${styles.answer} text-danger font-weight-bold`}> {/* Use global text classes */}
                            A: Due to our security model, account recovery without your password AND access to your PGP private key (for signing the login challenge) is **impossible**. We cannot reset passwords or bypass PGP 2FA. It is critical that you protect your credentials and securely back up your PGP private key and its passphrase. Account loss due to lost credentials/keys is permanent.
                        </p>

                         <h3 className={styles.question}>Q: How do I verify the market's PGP key?</h3>
                         <p className={styles.answer}>
                             A: Our official market PGP key fingerprint and potentially the key itself can be found on the <Link href="/canary">Warrant Canary</Link> page or other official market communication channels (specify if applicable, e.g., forum thread). Always verify the key fingerprint meticulously against multiple trusted sources before importing or using it.
                         </p>
                    </section>

                    {/* Orders & Escrow Section */}
                    <section className="mt-4">
                        <h2>Orders & Escrow</h2>
                        <h3 className={styles.question}>Q: How does the escrow work?</h3>
                        <p className={styles.answer}>
                            A: We primarily use a 2-of-3 multi-signature (multi-sig) escrow system for supported cryptocurrencies (XMR, BTC). Funds are held in a unique address requiring signatures from 2 out of 3 parties (Buyer, Vendor, Market Moderator) to be released. This significantly reduces risk as no single party controls the funds during the transaction. Standard market-held escrow may be used for other currencies or specific situations.
                        </p>

                         <h3 className={styles.question}>Q: When should I finalize an order?</h3>
                         <p className={styles.answer}>
                             A: Only finalize an order AFTER you have received your item/service and confirmed it matches the description and is satisfactory. Finalizing releases the escrowed funds to the vendor and marks the transaction as complete. This action typically cannot be undone. If using multi-sig, finalizing often involves providing your signature.
                         </p>

                         <h3 className={styles.question}>Q: What is the auto-finalize deadline?</h3>
                         {/* --- UPDATED CONTENT --- */}
                         <p className={styles.answer}>
                             A: If you do not finalize or open a dispute within a set period after the vendor marks the order as shipped (typically 14 days - check the <Link href="/rules">Market Rules</Link>), the order may be automatically finalized by the system. It is your responsibility to track your orders and take action within the allowed timeframe.
                         </p>
                         {/* --- END UPDATED CONTENT --- */}
                    </section>

                     {/* Disputes Section */}
                    <section className="mt-4">
                         <h2>Disputes</h2>
                         <h3 className={styles.question}>Q: When should I open a dispute?</h3>
                         <p className={styles.answer}>
                             A: Open a dispute before the auto-finalize deadline if you haven't received your order after a reasonable shipping time has passed, or if the item received is incorrect, damaged, or significantly not as described. It is highly recommended to attempt communication with the vendor via order messages first to resolve the issue amicably.
                          </p>

                          <h3 className={styles.question}>Q: What happens in a dispute?</h3>
                          <p className={styles.answer}>
                              A: A market moderator will be assigned to review the order details, messages between buyer and vendor, and any evidence provided by both parties. Based on the evidence and market rules, the moderator will make a ruling on how the escrowed funds should be distributed (e.g., full refund to buyer, full release to vendor, partial split). Moderator decisions are typically final.
                          </p>
                     </section>

                      {/* Vendors Section */}
                     <section className="mt-4">
                          <h2>Vendors</h2>
                          <h3 className={styles.question}>Q: How do I become a vendor?</h3>
                           {/* --- UPDATED CONTENT (Rev 5) --- */}
                          <p className={styles.answer}>
                              A: Becoming a vendor on Shadow Market involves demonstrating trustworthiness and commitment to security. The general process is:
                          </p>
                          <ol className={`${styles.answer} list-decimal pl-4 mb-3`}>
                                <li className="mb-2">
                                    <strong>Prerequisites:</strong> You must have an established user account in good standing (e.g., minimum account age, positive transaction history if applicable - specific requirements are in the Market Rules). You must have PGP configured correctly on your account.
                                </li>
                                <li className="mb-2">
                                    <strong>Application:</strong> Navigate to the 'Become a Vendor' page [TODO: Link to `/vendor-application` or similar if it exists] or follow instructions in the <Link href="/rules">Market Rules</Link>. You will typically need to provide a description of your intended listings, verify your identity via a PGP signed message challenge issued during the application, and agree to the vendor terms.
                                </li>
                                <li className="mb-2">
                                    <strong>Bond Payment:</strong> If your initial application details are satisfactory, you will be required to pay a non-refundable vendor bond (currently payable in BTC). The specific bond amount is listed in the <Link href="/rules">Market Rules</Link>. You will be provided with a unique BTC deposit address during the application process.
                                </li>
                                <li className="mb-2">
                                    <strong>Review:</strong> Once the bond payment is confirmed on the blockchain, your application will be reviewed by market staff. This involves verifying your PGP signature, checking your statement, and ensuring compliance with market rules.
                                </li>
                                <li className="mb-2">
                                    <strong>Approval:</strong> If approved, your account will be granted vendor status, allowing you to create listings. You will receive a notification upon approval.
                                </li>
                           </ol>
                           <p className={`${styles.answer} font-italic`}> {/* Use global italic class if available */}
                               Please note: The vendor application process is thorough to ensure market integrity. Falsifying information or failing PGP verification will result in rejection. Ensure you read the <Link href="/rules">Market Rules</Link> completely before applying.
                           </p>
                          {/* --- END UPDATED CONTENT --- */}

                           <h3 className={styles.question}>Q: What is the vendor bond?</h3>
                           <p className={styles.answer}>
                               A: Approved vendors are required to pay a non-refundable bond (amount specified in Market Rules) as a security deposit and to demonstrate commitment. This bond may be forfeit in cases of serious rule violations or exit scams. The bond amount can be found in the <Link href="/rules">Market Rules</Link>.
                           </p>
                      </section>

                    {/* TODO: Add more relevant Q&A sections/items as needed */}

                </div>
            </div>
        </Layout>
    );
}