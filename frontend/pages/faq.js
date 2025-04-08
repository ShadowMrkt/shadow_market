// frontend/pages/faq.js
// --- REVISION HISTORY ---
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
                            {/* TODO: Fill in market description */}
                            A: Shadow Market is a Tor-based marketplace focused on security and user privacy. [Add more detail about your market's specific goals/niche, e.g., multi-sig only, specific categories].
                        </p>

                        <h3 className={styles.question}>Q: Is this market secure?</h3>
                        <p className={styles.answer}>
                            A: We employ several security measures, including mandatory PGP 2FA, multi-signature escrow, encrypted messaging (where applicable), and operate exclusively on Tor. However, absolute security cannot be guaranteed. Users must also practice good Operational Security (OpSec). See our About page (if it exists) or Rules for more details. {/* Consider linking to /rules instead of /about if more relevant */}
                        </p>

                         <h3 className={styles.question}>Q: Are there market fees?</h3>
                         <p className={styles.answer}>
                            {/* TODO: Fill in actual fee percentages */}
                             A: Yes, standard market fees apply to finalized orders to cover operational costs and development. Current fees are [X]% for standard escrow and [Y]% for multi-sig escrow, deducted from the vendor payout during escrow release. Specific fees might vary per category or vendor level; check the Rules page for definitive details.
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
                         <p className={styles.answer}>
                            {/* TODO: Fill in actual auto-finalize duration */}
                             A: If you do not finalize or open a dispute within a set period after the vendor marks the order as shipped (typically [X] days - check the <Link href="/rules">Market Rules</Link>), the order may be automatically finalized by the system. It is your responsibility to track your orders and take action within the allowed timeframe.
                         </p>
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
                          <p className={styles.answer}>
                            {/* TODO: Fill in vendor application process */}
                            A: [Explain your vendor application/approval process here - e.g., Minimum account age/history, application via support ticket, requirements for PGP/description, bond payment details]. Check the specific requirements detailed on the [Link to Vendor Application Info if available] page or in the Market Rules.
                          </p>

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

// TODO: Create Faq.module.css for .question and .answer styles.