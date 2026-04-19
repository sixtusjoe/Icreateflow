import type { Metadata } from "next";
import Link from "next/link";
import LegalShell, { Section } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Privacy Policy — ICREATEFLOW",
  description:
    "How ICREATEFLOW collects, uses, shares, and protects your personal information when you use our promotion and distribution platform.",
};

export default function PrivacyPage() {
  return (
    <LegalShell
      title="Privacy Policy"
      subtitle="This Privacy Policy explains what information ICREATEFLOW collects about you, how we use it, who we share it with, and the choices you have."
      lastUpdated="April 19, 2026"
    >
      <Section number="1" title="Introduction" id="intro">
        <p>
          ICREATEFLOW (&ldquo;<strong>ICREATEFLOW</strong>&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;, or
          &ldquo;our&rdquo;) operates a promotion and distribution platform for artists, brands,
          movie studios, podcasters, and other creators at{" "}
          <a href="https://icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            icreateflow.com
          </a>{" "}
          (the &ldquo;<strong>Service</strong>&rdquo;). We help you push your clips, trailers,
          episodes, and product drops across a network of social accounts you control. We respect
          your privacy and are committed to handling your information responsibly and transparently.
        </p>
        <p>
          This Policy applies to the ICREATEFLOW web application, APIs, and related services. By using
          the Service, you agree to the collection and use of information in accordance with this
          Policy. It should be read alongside our{" "}
          <Link href="/terms" className="font-medium underline underline-offset-2 hover:text-foreground">
            Terms &amp; Conditions
          </Link>
          .
        </p>
      </Section>

      <Section number="2" title="Information we collect" id="what-we-collect">
        <p>We collect information in three main ways:</p>

        <div>
          <h3 className="mb-2 text-base font-semibold text-foreground">a. Information you provide</h3>
          <ul className="list-disc space-y-2 pl-6">
            <li><strong>Account details</strong>: name, email address, password (stored hashed), and optional profile information.</li>
            <li><strong>Artist, brand, and campaign content</strong>: artist names, brand names, handles, timezones, posting windows, view targets, uploaded clips, captions, artwork, trailers, episodes, and other promotional material.</li>
            <li><strong>Connected account credentials</strong>: OAuth tokens and optional API keys for the TikTok, YouTube, Instagram, Facebook, and Google Drive accounts you link to the Service. These are stored encrypted and used only to perform the distribution tasks you configure.</li>
            <li><strong>Communications</strong>: messages you send to support, feedback, clearance and takedown correspondence, and survey responses.</li>
            <li><strong>Billing information</strong>: handled by our payment processor; we receive only limited details (such as the last four digits of your card and billing country) needed to operate your subscription.</li>
          </ul>
        </div>

        <div>
          <h3 className="mb-2 text-base font-semibold text-foreground">b. Information collected automatically</h3>
          <ul className="list-disc space-y-2 pl-6">
            <li><strong>Usage data</strong>: actions you take in the Service, features used, campaigns launched, clips distributed, and performance metrics.</li>
            <li><strong>Device and log data</strong>: IP address, browser type and version, operating system, referring pages, and timestamps.</li>
            <li><strong>Cookies and similar technologies</strong>: used to keep you signed in, remember preferences, and measure performance (see Section 7).</li>
          </ul>
        </div>

        <div>
          <h3 className="mb-2 text-base font-semibold text-foreground">c. Information from third parties</h3>
          <ul className="list-disc space-y-2 pl-6">
            <li>Data returned by connected platforms (TikTok, YouTube, Instagram, Facebook, Google Drive) when you link an account, limited to the scopes you grant — for example, permission to upload videos, set captions, and read post IDs and view counts for the posts the Service published on your behalf.</li>
            <li>Output from AI service providers (OCR results, generated image variations) associated with your promotional jobs.</li>
          </ul>
        </div>
      </Section>

      <Section number="3" title="How we use information" id="how-we-use">
        <ul className="list-disc space-y-2 pl-6">
          <li>Operate the Service — schedule and distribute your clips across the accounts you have connected, rotate catalog items, and enforce posting windows and view targets;</li>
          <li>Compute aggregated campaign statistics, including per-platform posts and views, progress toward campaign targets, and CSV exports;</li>
          <li>Authenticate you, secure your account, and prevent fraud, abuse, and unauthorized posting;</li>
          <li>Communicate with you about features, updates, security alerts, campaign issues, and support responses;</li>
          <li>Improve the Service through analytics, debugging, and user-experience research;</li>
          <li>Process payments and manage subscriptions;</li>
          <li>Comply with legal obligations, platform-integration requirements, and enforce our Terms.</li>
        </ul>
        <p>
          We do <strong>not</strong> sell your personal information, and we do <strong>not</strong>{" "}
          use Your Content — including your clips, captions, or campaign data — to train our own AI
          models without your explicit consent.
        </p>
      </Section>

      <Section number="4" title="Legal bases (EEA/UK users)" id="legal-bases">
        <p>If the EU/UK GDPR applies to you, we process your personal data on these bases:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Contract</strong>: to provide the Service you requested, including running your promotion campaigns;</li>
          <li><strong>Legitimate interests</strong>: to secure, improve, and promote the Service, where those interests are not overridden by your rights;</li>
          <li><strong>Consent</strong>: for optional cookies, marketing emails, and optional integrations (you can withdraw consent at any time);</li>
          <li><strong>Legal obligation</strong>: to comply with applicable laws.</li>
        </ul>
      </Section>

      <Section number="5" title="How we share information" id="sharing">
        <p>We share information only as described below:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Connected platforms</strong>: when you authorize a campaign, we transmit the necessary clip files, captions, thumbnails, and metadata to the TikTok, YouTube, Instagram, and Facebook accounts you have connected, so the Service can publish on your behalf.</li>
          <li><strong>Service providers</strong>: cloud hosting, database, storage, email delivery, payment processing, analytics, and AI providers (for example, OCR and image-generation APIs) acting on our instructions under confidentiality obligations.</li>
          <li><strong>Business transfers</strong>: if ICREATEFLOW is involved in a merger, acquisition, or asset sale, information may be transferred as part of that transaction, subject to standard confidentiality protections.</li>
          <li><strong>Legal requirements</strong>: when required to comply with a law, valid legal process, rights-holder takedown notice, or to protect the rights, property, or safety of ICREATEFLOW, our users, rights-holders, or the public.</li>
          <li><strong>With your consent</strong>: for any other purpose disclosed to you at the time.</li>
        </ul>
      </Section>

      <Section number="6" title="International transfers" id="transfers">
        <p>
          ICREATEFLOW and its service providers may process your information in countries other than
          the one in which you reside. Where required, we rely on appropriate safeguards such as the
          European Commission&rsquo;s Standard Contractual Clauses and equivalent frameworks to
          protect your information when it is transferred across borders.
        </p>
      </Section>

      <Section number="7" title="Cookies & similar technologies" id="cookies">
        <p>We use a small number of cookies:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Essential</strong>: required for authentication, session security, and core functionality. These cannot be disabled.</li>
          <li><strong>Preference</strong>: remember your theme (light/dark), selected artist or brand workspace, and similar settings.</li>
          <li><strong>Analytics</strong>: aggregate usage data to help us improve the Service. We only enable analytics cookies with your consent where required by law.</li>
        </ul>
        <p>
          Most browsers let you manage cookies from their settings, including the ability to block
          or delete them. Blocking essential cookies will break parts of the Service.
        </p>
      </Section>

      <Section number="8" title="Data retention" id="retention">
        <ul className="list-disc space-y-2 pl-6">
          <li>Account information is retained while your account is active and for a reasonable period afterwards to satisfy legal, accounting, or reporting obligations.</li>
          <li>Uploaded clips and generated assets are retained until you delete them, reset the artist directory, or your account is closed — whichever comes first.</li>
          <li>Campaign statistics (posts, view counts, platform post IDs, captions) are retained after a campaign ends so that historical CSV exports remain available, even if the underlying clips have been removed.</li>
          <li>Security and audit logs are kept for a limited period and then deleted or anonymized.</li>
          <li>When information is no longer needed, we securely delete or de-identify it.</li>
        </ul>
      </Section>

      <Section number="9" title="Security" id="security">
        <p>
          We implement administrative, technical, and organizational measures designed to protect
          your information — including encryption in transit (TLS), encryption at rest for sensitive
          fields such as third-party OAuth tokens and API keys, least-privilege access controls,
          and regular backups. No method of transmission or storage is 100% secure; if you become
          aware of any suspected security issue, please email{" "}
          <a href="mailto:security@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            security@icreateflow.com
          </a>
          .
        </p>
      </Section>

      <Section number="10" title="Your rights and choices" id="rights">
        <p>Depending on your jurisdiction, you may have the right to:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li>Access the personal information we hold about you;</li>
          <li>Correct information that is inaccurate or incomplete;</li>
          <li>Request deletion (&ldquo;right to be forgotten&rdquo;), subject to legal limits;</li>
          <li>Port your data to another service in a commonly used, machine-readable format — including CSV exports of your campaign history directly from the dashboard;</li>
          <li>Disconnect any linked social or Drive account at any time from your workspace settings, which revokes ICREATEFLOW&rsquo;s access to that account;</li>
          <li>Object to or restrict certain processing, including direct marketing;</li>
          <li>Withdraw consent at any time, without affecting the lawfulness of prior processing;</li>
          <li>Lodge a complaint with your local data-protection authority.</li>
        </ul>
        <p>
          You can exercise many of these rights directly from your account settings, or by
          contacting us at{" "}
          <a href="mailto:privacy@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            privacy@icreateflow.com
          </a>
          . We may need to verify your identity before fulfilling a request.
        </p>
      </Section>

      <Section number="11" title="Children" id="children">
        <p>
          The Service is not directed to children under 13 (or the minimum age required in your
          country). We do not knowingly collect personal information from children. If you believe a
          child has provided us with information, contact us and we will take reasonable steps to
          delete it.
        </p>
      </Section>

      <Section number="12" title="Third-party links & integrations" id="third-parties">
        <p>
          The Service integrates with and links to third-party platforms (including TikTok,
          YouTube, Instagram, Facebook, Google Drive, and AI providers). Their collection and use of
          your information is governed by their own privacy policies. We recommend reviewing those
          policies before connecting your accounts or relying on their services.
        </p>
      </Section>

      <Section number="13" title="Changes to this Policy" id="changes">
        <p>
          We may update this Privacy Policy periodically. When we do, we will revise the &ldquo;Last
          updated&rdquo; date at the top of the page and, for material changes, provide additional
          notice through the Service or by email. Continued use of the Service after the updated
          Policy takes effect constitutes acceptance of the revised Policy.
        </p>
      </Section>

      <Section number="14" title="Contact us" id="contact">
        <p>
          If you have questions about this Privacy Policy or how we handle your information, contact
          us at{" "}
          <a href="mailto:privacy@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            privacy@icreateflow.com
          </a>
          . For general support, email{" "}
          <a href="mailto:support@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            support@icreateflow.com
          </a>
          .
        </p>
      </Section>
    </LegalShell>
  );
}
