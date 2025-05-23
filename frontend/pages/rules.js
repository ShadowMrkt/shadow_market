// frontend/pages/rules.js
// --- REVISION HISTORY ---
// 2025-04-28: Rev 2 - SPECULATIVE CONTENT ADDED based on user request. (Gemini)
//           - Clarified prohibited items (Strict bans recommended).
//           - Added specific Vendor rules (OpSec, Multi-sig, PGP).
//           - Added new sections: IV. Dispute Resolution, V. Fees & Payments, VI. Account Security.
//           - Populated new sections with recommended rules/details.
// 2025-04-07: Rev 1 - Applied global CSS classes, removed inline styles, added dynamic date.
//           - Used .container-narrow, .card, .p-4, .mb-*, .mt-*, text utilities global classes.
//           - Updated "Last Updated" date dynamically using formatDate.
//           - Added TODO comments for market-specific rule customization.
//           - Added revision history block.

import React from 'react';
import Layout from '../components/Layout'; // Import main layout
import Link from 'next/link';
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
                        <strong>Violation of these rules may result in warnings, temporary suspension, or permanent banning from the market. Staff decisions are final. Use common sense and prioritize security.</strong>
                    </p>

                    <section>
                        <h2>I. General Conduct & Prohibitions</h2>
                        {/* --- START Speculative Content Rev 2 --- */}
                        <p className="mb-2">The following activities and items are strictly prohibited. Violation carries severe penalties, including permanent ban and potential loss of funds/bond.</p>
                        <ul className="list-disc pl-4">
                            <li className="mb-2">Do not engage in any activity harmful to the market infrastructure or other users (e.g., DDoS attacks, exploiting vulnerabilities, malicious code injection). Report vulnerabilities responsibly via support ticket.</li>
                            <li className="mb-2">
                                <strong>Zero Tolerance:</strong> Any discussion, trading, listing, or linking related to:
                                <ul className="list-circle pl-4 mt-1">
                                    <li>Child pornography (CP) / Child exploitation material.</li>
                                    <li>Terrorism financing, recruitment, or related materials.</li>
                                    <li>Murder-for-hire, assassination services, or contracts for physical harm.</li>
                                </ul>
                            </li>
                            <li className="mb-2">
                                <strong>Strict Ban:</strong> All firearms, ammunition, explosives, military-grade weapons, destructive devices, regulated weapon components, and related schematics/instructions.
                            </li>
                             <li className="mb-2">
                                <strong>Strict Ban:</strong> Fentanyl, its analogues (e.g., carfentanil), related dangerously potent synthetic opioids, and products knowingly laced with them. Selling substances misrepresented as being fentanyl-free when they are not is also strictly prohibited.
                            </li>
                            <li className="mb-2">
                                <strong>Strict Ban:</strong> Known poisons, highly toxic/corrosive chemicals intended for harm (e.g., ricin, sarin). Lab/research chemicals must be accurately described, legal in relevant jurisdictions, and not marketed for harmful purposes.
                            </li>
                             <li className="mb-2">
                                <strong>Strict Ban:</strong> Malware, viruses, ransomware, or other malicious software intended to cause harm or financial loss. (Security research tools may be permissible if clearly labeled and not weaponized).
                            </li>
                            <li className="mb-2">
                                <strong>Strict Ban:</strong> Doxxing (revealing private, identifying information), threatening violence, extortion, or targeted harassment against users or staff.
                            </li>
                            <li className="mb-2">Do not attempt to scam users (e.g., posting fake reviews, creating misleading listings, phishing links/messages, bait-and-switch tactics).</li>
                            <li className="mb-2">Do not attempt to circumvent the market's escrow or fee system (e.g., finalizing early without buyer confirmation/agreement, directing users off-site for payment or communication). All transaction-related activity must occur on the platform.</li>
                            <li className="mb-2">Do not spam listings, feedback sections, support tickets, user messages, or the forum. Keep communications relevant and concise.</li>
                            <li className="mb-2">Use the internal support ticket system for all official market issues. Do not rely on external communication unless explicitly instructed by verified staff for specific, authorized reasons (e.g., advanced PGP verification).</li>
                        </ul>
                        {/* --- END Speculative Content Rev 2 --- */}
                    </section>

                    <section className="mt-4">
                        <h2>II. Buyer Rules</h2>
                         <ul className="list-disc pl-4">
                            <li className="mb-2">Read listing descriptions, vendor profiles (including terms, shipping info, PGP key), and feedback carefully before placing an order. Understand what you are buying and the vendor's policies.</li>
                            <li className="mb-2">Do not place orders you do not intend to pay for within the specified payment window (typically 4 hours, see FAQ)[cite: 2].</li>
                            <li className="mb-2">Send the exact cryptocurrency amount specified to the unique payment address provided for your order. Do not reuse addresses. Account for network transaction fees separately to ensure the full amount arrives.</li>
                            <li className="mb-2">Finalize orders promptly (within the auto-finalize window, typically 14 days after shipping) ONLY upon receipt and verification of goods/services matching the description. Do NOT finalize early under pressure from a vendor. Early finalization voids escrow protection.</li>
                            <li className="mb-2">Utilize the dispute system fairly and only when necessary (e.g., non-receipt after sufficient time, item significantly not-as-described). Attempt communication with the vendor first via order messages to resolve issues amicably. Provide clear, concise, and factual evidence during disputes.</li>
                            <li className="mb-2">Do not leave dishonest, irrelevant, or retaliatory feedback. Feedback should reflect your genuine experience with the specific transaction and product/service quality.</li>
                            <li className="mb-2">Ensure your shipping address (if applicable) is accurate, complete, and properly formatted. Use the PGP encryption feature provided during checkout or pre-encrypt your details using the vendor's PGP key. Address errors are your responsibility.</li>
                            <li className="mb-2">Adhere to all Account Security rules (see Section VI). Protect your credentials and PGP key.</li>
                        </ul>
                    </section>

                    <section className="mt-4">
                        <h2>III. Vendor Rules</h2>
                         {/* --- START Speculative Content Rev 2 --- */}
                         <ul className="list-disc pl-4">
                            <li className="mb-2">Accurately describe all products/services, including quality, quantity, origin (if relevant), shipping methods/timescales, and any specific terms or conditions. No misleading titles, images, or descriptions. Clearly state if a product is intended for research/novelty purposes only.</li>
                             <li className="mb-2">Strictly adhere to the list of prohibited items (see Section I). Listing prohibited goods/services will result in immediate action, including potential bond forfeiture and permanent ban.</li>
                            <li className="mb-2">Ship orders promptly (within your stated timeframe, typically 1-3 business days unless otherwise specified) after payment confirmation, using the exact shipping method paid for by the buyer.</li>
                            <li className="mb-2">Mark orders as shipped promptly ONLY after actual dispatch. Provide valid tracking information if the shipping option included it. Falsely marking orders as shipped is prohibited.</li>
                            <li className="mb-2">Respond professionally and promptly (generally within 48 hours) to buyer inquiries via order messages and respond constructively to support tickets involving your orders.</li>
                            <li className="mb-2">Maintain excellent operational security (OpSec). Do not reuse usernames/PGP keys across markets. Avoid revealing identifying information. Sanitize product images. Secure your account and PGP key diligently.</li>
                            <li className="mb-2">Do not engage in feedback manipulation (e.g., offering incentives for positive feedback outside of legitimate market-approved promotions, threatening buyers over negative feedback, leaving retaliatory feedback).</li>
                            <li className="mb-2">Attempt to resolve issues with buyers fairly and professionally before a dispute is necessary. Cooperate fully and provide timely evidence during the dispute process if one is opened.</li>
                            <li className="mb-2">Pay the required vendor bond and adhere to all requirements associated with your vendor level or status. Understand that the bond is non-refundable and may be forfeit for serious rule violations.</li>
                            <li className="mb-2">Do not direct users off-site for communication or payment under any circumstances. All transactions and related communication must occur through the market platform's secure channels.</li>
                            <li className="mb-2">Securely handle buyer information (e.g., PGP-encrypted shipping details). Decrypt only when necessary for shipping and securely destroy this information promptly after order completion or a reasonable retention period for dispute resolution (e.g., 30 days post-finalization).</li>
                             <li className="mb-2">Provide your correct PGP public key on your vendor profile. Ensure it is accessible and functional for buyers to encrypt information.</li>
                             <li className="mb-2">Cooperate fully with the multi-signature escrow process. This includes providing necessary public keys during setup (if applicable) and signing valid release or refund transactions promptly when required by dispute resolution or buyer finalization.</li>
                        </ul>
                         {/* --- END Speculative Content Rev 2 --- */}
                    </section>

                    {/* --- START NEW SECTIONS (Speculative Content Rev 2) --- */}
                    <section className="mt-4">
                        <h2>IV. Dispute Resolution</h2>
                        <ul className="list-disc pl-4">
                            <li className="mb-2"><strong>Initiation:</strong> Disputes can be opened by the Buyer via the order page within the dispute window (typically 7 days post-shipment, check FAQ/order details) [cite: 2] but before the auto-finalize deadline.</li>
                            <li className="mb-2"><strong>Communication First:</strong> Buyers are strongly encouraged to communicate with the Vendor via order messages to attempt resolution before opening a formal dispute.</li>
                            <li className="mb-2"><strong>Process:</strong>
                                <ol className="list-decimal pl-4 mt-1">
                                    <li>Buyer opens dispute, providing a clear reason and initial evidence.</li>
                                    <li>Vendor is notified and typically has 48-72 hours to respond.</li>
                                    <li>Both parties submit relevant evidence (e.g., tracking info, photos, communication logs).</li>
                                    <li>A market Moderator reviews the case, evidence, and communication based on market rules.</li>
                                    <li>Moderator makes a ruling (e.g., full refund, partial refund, full release to vendor).</li>
                                    <li>Escrow funds are released according to the Moderator's decision (may require Moderator signature in multi-sig).</li>
                                </ol>
                            </li>
                            <li className="mb-2"><strong>Evidence:</strong> Be factual, concise, and provide clear evidence. Tampering with evidence is strictly prohibited.</li>
                            <li className="mb-2"><strong>Moderator Decision:</strong> Moderator rulings are based on the presented evidence and market rules. Decisions are final and binding. Abusive behavior towards moderators will not be tolerated.</li>
                        </ul>
                    </section>

                    <section className="mt-4">
                        <h2>V. Fees & Payments</h2>
                         <ul className="list-disc pl-4">
                            <li className="mb-2"><strong>Market Fee:</strong> A flat fee (currently 2.5%) is deducted from the order total upon successful finalization and release of funds to the vendor. This fee supports market operations and development.</li>
                             <li className="mb-2"><strong>Escrow:</strong> All transactions utilize the market's multi-signature (BTC, XMR) or standard (ETH, if applicable) escrow system. Direct deals are prohibited.</li>
                            <li className="mb-2"><strong>Accepted Currencies:</strong> Bitcoin (BTC), Monero (XMR), and Ethereum (ETH) are currently supported.</li>
                             <li className="mb-2"><strong>Payment Window:</strong> Buyers must send the exact payment amount to the provided address within the payment window (typically 4 hours [cite: 2]) or the order may be automatically cancelled.</li>
                            <li className="mb-2"><strong>Network Fees:</strong> Buyers are responsible for paying sufficient cryptocurrency network transaction fees to ensure their payment confirms in a timely manner. The market fee does not cover network fees.</li>
                            <li className="mb-2"><strong>Withdrawal Fees:</strong> Standard network transaction fees apply to withdrawals from your market wallet, deducted from the withdrawal amount. There may be a small additional market fee for withdrawals (check Wallet page).</li>
                        </ul>
                    </section>

                     <section className="mt-4">
                        <h2>VI. Account Security</h2>
                         <ul className="list-disc pl-4">
                             <li className="mb-2"><strong>Passwords:</strong> Use a strong, unique password for your Shadow Market account, not reused from any other site. Utilize a password manager.</li>
                             <li className="mb-2"><strong>PGP 2FA:</strong> PGP 2FA is mandatory for login and critical actions. Protect your PGP private key and its passphrase securely. Use offline backups.</li>
                             <li className="mb-2"><strong>Account Recovery:</strong> Account recovery is **IMPOSSIBLE** if you lose your password OR your PGP private key/passphrase. There are no exceptions. Secure your credentials.</li>
                            <li className="mb-2"><strong>WebAuthn/FIDO2:</strong> Where available, consider registering a WebAuthn device (like a YubiKey) for an additional secure login method.</li>
                            <li className="mb-2"><strong>Session Security:</strong> Log out when finished using the market. Be aware of session timeouts (standard user sessions expire after inactivity, see FAQ/settings). Do not use shared or untrusted computers.</li>
                            <li className="mb-2"><strong>Phishing:</strong> Be vigilant against phishing attempts. Verify the market URL carefully. Staff will NEVER ask for your password or PGP private key. Verify staff PGP keys if contacted directly.</li>
                             <li className="mb-2"><strong>Account Sharing:</strong> Do not share your account credentials or PGP key with anyone. Each user must have their own account.</li>
                        </ul>
                     </section>
                    {/* --- END NEW SECTIONS --- */}

                    <p className="mt-4 text-muted small"> {/* Use global text utilities */}
                         These rules are subject to change without prior notice. Please review them periodically. By accessing or using Shadow Market, you agree to abide by the current version of these rules. Failure to comply may lead to penalties determined by market staff.
                     </p>

                </div>
            </div>
        </Layout>
    );
}