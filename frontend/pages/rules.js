// frontend/pages/rules.js
// --- REVISION HISTORY ---
// 2025-04-07: Rev 1 - Applied global CSS classes, removed inline styles, added dynamic date.
//           - Used .container-narrow, .card, .p-4, .mb-*, .mt-*, text utilities global classes.
//           - Updated "Last Updated" date dynamically using formatDate.
//           - Added TODO comments for market-specific rule customization.
//           - Added revision history block.

import React from 'react';
import Layout from '../components/Layout'; // Import main layout
import Link from 'next/link'; // Import Link, though not currently used
import { formatDate } from '../utils/formatters'; // Import shared date formatter

// NOTE: This component relies entirely on global CSS classes defined in globals.css
// (e.g., .container-narrow, .card, .p-4, .mb-*, .mt-*, heading styles, text utilities etc.)

export default function RulesPage() {
    // Get current date for "Last Updated" - update this manually if rules change significantly without a code deployment
    const lastUpdatedDate = formatDate(new Date()); // Format current date

    return (
        <Layout>
            {/* Use global narrow container */}
            <div className="container-narrow">
                {/* Use global card style with padding */}
                <div className="card p-4">
                    <h1 className="mb-4">Market Rules</h1>

                    <p><strong>Last Updated:</strong> {lastUpdatedDate}</p>

                    {/* Use global text danger utility class */}
                    <p className="text-danger mb-4">
                        <strong>Violation of these rules may result in warnings, temporary suspension, or permanent banning from the market. All decisions by staff/moderators are final. Use common sense.</strong>
                    </p>

                    <section>
                        <h2>I. General Conduct & Prohibitions</h2>
                        {/* TODO: Review and customize ALL prohibited items/services meticulously based on market policy. */}
                        <ul className="list-disc pl-4"> {/* Example list styling if needed, or rely on default */}
                            <li className="mb-2">Do not engage in any activity harmful to the market infrastructure or other users (e.g., DDoS attacks, exploiting vulnerabilities).</li>
                            <li className="mb-2">No discussion or trading of illegal pornography (especially child pornography - CP), terrorism-related materials/funding, or murder-for-hire/assassination services. Zero tolerance policy, immediate permanent ban.</li>
                            <li className="mb-2">No weapons, explosives, poisons, or inherently dangerous chemicals unless specifically permitted in clearly designated categories and compliant with all applicable regulations (Define scope VERY clearly if allowing anything).</li>
                            <li className="mb-2">No fentanyl, its analogues, or related dangerously potent synthetic opioids unless explicitly stated otherwise and heavily restricted to specific, vetted vendors and categories (Define scope VERY clearly if allowing anything, or enforce complete ban).</li>
                            <li className="mb-2">No doxxing (revealing private information), threatening, or harassing other users or staff members. Maintain respectful communication.</li>
                            <li className="mb-2">Do not attempt to scam users (e.g., posting fake reviews, creating misleading listings, phishing links/messages, bait-and-switch tactics).</li>
                            <li className="mb-2">Do not attempt to circumvent the market's escrow or fee system (e.g., finalizing early without agreement, directing users off-site for payment).</li>
                            <li className="mb-2">Do not spam listings, feedback sections, support tickets, or user messages.</li>
                            <li className="mb-2">Use the internal support ticket system for all official market issues; do not rely on potentially insecure external communication methods unless instructed by verified staff for specific reasons.</li>
                        </ul>
                    </section>

                    <section className="mt-4">
                        <h2>II. Buyer Rules</h2>
                         <ul className="list-disc pl-4">
                            <li className="mb-2">Read listing descriptions, vendor profiles (including terms, shipping info, PGP key), and feedback carefully before placing an order. Understand what you are buying.</li>
                            <li className="mb-2">Do not place orders you do not intend to pay for within the specified payment window.</li>
                            <li className="mb-2">Send the exact cryptocurrency amount specified to the unique payment address provided for your order. Do not reuse addresses. Account for network transaction fees separately.</li>
                            <li className="mb-2">Finalize orders promptly (within the auto-finalize window) ONLY upon receipt and verification of goods/services matching the description. Do NOT finalize early under pressure from a vendor unless it's part of a pre-agreed specific process for certain item types (this is highly discouraged and carries risk).</li>
                            <li className="mb-2">Utilize the dispute system fairly and only when necessary (e.g., non-receipt after sufficient time, item significantly not-as-described). Attempt communication with the vendor first. Provide clear, concise, and factual evidence during disputes.</li>
                            <li className="mb-2">Do not leave dishonest, irrelevant, or retaliatory feedback. Feedback should reflect your genuine experience with the specific transaction.</li>
                            <li className="mb-2">Ensure your shipping address (if applicable) is accurate, complete, and properly formatted (whether entered directly and server-encrypted or pre-encrypted by you via PGP). Errors can lead to lost packages.</li>
                        </ul>
                    </section>

                    <section className="mt-4">
                        <h2>III. Vendor Rules</h2>
                         {/* TODO: Review and customize vendor rules based on market policy. */}
                         <ul className="list-disc pl-4">
                            <li className="mb-2">Accurately describe all products/services, including quality, quantity, origin (if relevant), and any specific terms or conditions. No misleading titles, images, or descriptions.</li>
                            <li className="mb-2">Ship orders promptly (within your stated timeframe) after payment confirmation, using the shipping method paid for by the buyer.</li>
                            <li className="mb-2">Mark orders as shipped promptly after dispatch. Provide valid tracking information where applicable and included in the shipping option.</li>
                            <li className="mb-2">Respond professionally and promptly (within a reasonable timeframe, e.g., 48-72 hours) to buyer inquiries via order messages and respond to support tickets involving your orders.</li>
                            <li className="mb-2">Maintain excellent operational security (OpSec) regarding your identity, location, communications, and packaging methods.</li>
                            <li className="mb-2">Strictly adhere to the list of prohibited items (see Section I). Listing prohibited goods/services will result in immediate action.</li>
                            <li className="mb-2">Do not engage in feedback manipulation (e.g., offering incentives for positive feedback outside of legitimate promotions, threatening buyers over negative feedback).</li>
                            <li className="mb-2">Attempt to resolve issues with buyers fairly and professionally before a dispute is necessary. Cooperate fully during the dispute process if one is opened.</li>
                            <li className="mb-2">Pay the required vendor bond (if applicable) and adhere to all requirements associated with your vendor level or status.</li>
                            <li className="mb-2">Do not direct users off-site for communication or payment under any circumstances. All transactions and related communication must occur through the market platform.</li>
                             <li className="mb-2">Securely handle buyer information (like PGP-encrypted shipping details) and destroy it after order completion/reasonable timeframe.</li>
                        </ul>
                    </section>

                    {/* TODO: Add other sections as needed (e.g., Dispute Resolution Process, Fees, Account Security specific rules) */}

                    <p className="mt-4 text-muted small"> {/* Use global text utilities */}
                         These rules are subject to change without prior notice. Please review them periodically. By accessing or using Shadow Market, you agree to abide by the current version of these rules. Failure to comply may lead to penalties determined by market staff.
                     </p>

                </div>
            </div>
        </Layout>
    );
}