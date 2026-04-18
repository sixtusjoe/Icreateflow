import type { Metadata } from "next";
import Link from "next/link";
import LegalShell, { Section } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Privacy Policy — ICREATEFLOW",
  description:
    "How ICREATEFLOW collects, uses, shares, and protects your personal information when you use our content creation platform.",
};

export default function PrivacyPage() {
  return (
    <LegalShell
      title="Privacy Policy"
      subtitle="This Privacy Policy explains what information ICREATEFLOW collects about you, how we use it, who we share it with, and the choices you have."
      lastUpdated="April 17, 2026"
    >
      <Section number="1" title="Introduction" id="intro">
        <p>
          ICREATEFLOW (&ldquo;<strong>ICREATEFLOW</strong>&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;, or
          &ldquo;our&rdquo;) provides a multi-brand content creation and scheduling platform accessible at{" "}
          <a href="https://icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            icreateflow.com
          </a>{" "}
          (the &ldquo;<strong>Service</strong>&rdquo;). We respect your privacy and are committed to
          handling your personal information responsibly and transparently.
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
            <li><strong>Brand and workspace content</strong>: brand names, handles, timezones, uploaded images, videos, music, captions, and post metadata.</li>
            <li><strong>Third-party credentials</strong>: API keys or OAuth tokens you provide to connect AI providers or social platforms. These are encrypted at rest.</li>
            <li><strong>Communications</strong>: messages you send to support, feedback, and survey responses.</li>
            <li><strong>Billing information</strong>: handled by our payment processor; we receive only limited details (such as the last four digits of your card and billing country) needed to operate your subscription.</li>
          </ul>
        </div>

        <div>
          <h3 className="mb-2 text-base font-semibold text-foreground">b. Information collected automatically</h3>
          <ul className="list-disc space-y-2 pl-6">
            <li><strong>Usage data</strong>: actions you take in the Service, features used, generation jobs, and performance metrics.</li>
            <li><strong>Device and log data</strong>: IP address, browser type and version, operating system, referring pages, and timestamps.</li>
            <li><strong>Cookies and similar technologies</strong>: used to keep you signed in, remember preferences, and measure performance (see Section 7).</li>
          </ul>
        </div>

        <div>
          <h3 className="mb-2 text-base font-semibold text-foreground">c. Information from third parties</h3>
          <ul className="list-disc space-y-2 pl-6">
            <li>Data returned by connected social platforms (e.g., TikTok, YouTube, Instagram, Facebook) when you link an account, limited to the scopes you grant.</li>
            <li>Output from AI service providers (OCR results, generated images) associated with your generation requests.</li>
          </ul>
        </div>
      </Section>

      <Section number="3" title="How we use information" id="how-we-use">
        <ul className="list-disc space-y-2 pl-6">
          <li>Provide, operate, and maintain the Service, including rendering slides, generating images, and scheduling posts;</li>
          <li>Authenticate you, secure your account, and prevent fraud and abuse;</li>
          <li>Communicate with you about features, updates, security alerts, and support responses;</li>
          <li>Improve the Service through analytics, debugging, and user-experience research;</li>
          <li>Process payments and manage subscriptions;</li>
          <li>Comply with legal obligations and enforce our Terms.</li>
        </ul>
        <p>
          We do <strong>not</strong> sell your personal information, and we do <strong>not</strong>{" "}
          use your content to train our own AI models without your explicit consent.
        </p>
      </Section>

      <Section number="4" title="Legal bases (EEA/UK users)" id="legal-bases">
        <p>If the EU/UK GDPR applies to you, we process your personal data on these bases:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Contract</strong>: to provide the Service you requested;</li>
          <li><strong>Legitimate interests</strong>: to secure, improve, and promote the Service, where those interests are not overridden by your rights;</li>
          <li><strong>Consent</strong>: for optional cookies, marketing emails, and certain integrations (you can withdraw consent at any time);</li>
          <li><strong>Legal obligation</strong>: to comply with applicable laws.</li>
        </ul>
      </Section>

      <Section number="5" title="How we share information" id="sharing">
        <p>We share information only as described below:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Service providers</strong>: cloud hosting, database, storage, email delivery, payment processing, analytics, and AI providers (e.g., OCR and image-generation APIs) acting on our instructions under confidentiality obligations.</li>
          <li><strong>Connected platforms</strong>: when you authorize publication or scheduling, we send the necessary content and metadata to the platform you selected.</li>
          <li><strong>Business transfers</strong>: if ICREATEFLOW is involved in a merger, acquisition, or asset sale, information may be transferred as part of that transaction, subject to standard confidentiality protections.</li>
          <li><strong>Legal requirements</strong>: when required to comply with a law, valid legal process, or to protect the rights, property, or safety of ICREATEFLOW, our users, or the public.</li>
          <li><strong>With your consent</strong>: for any other purpose disclosed to you at the time.</li>
        </ul>
      </Section>

      <Section number="6" title="International transfers" id="transfers">
        <p>
          ICREATEFLOW and its service providers may process your information in countries other than the
          one in which you reside. Where required, we rely on appropriate safeguards such as the
          European Commission&rsquo;s Standard Contractual Clauses and equivalent frameworks to
          protect your information when it is transferred across borders.
        </p>
      </Section>

      <Section number="7" title="Cookies & similar technologies" id="cookies">
        <p>We use a small number of cookies:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li><strong>Essential</strong>: required for authentication, session security, and core functionality. These cannot be disabled.</li>
          <li><strong>Preference</strong>: remember your theme (light/dark), selected workspace, and similar settings.</li>
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
          <li>Generated assets (slides, videos, drafts) are retained until you delete them, your workspace is deleted, or your account is closed, whichever comes first.</li>
          <li>Security and audit logs are kept for a limited period and then deleted or anonymized.</li>
          <li>When information is no longer needed, we securely delete or de-identify it.</li>
        </ul>
      </Section>

      <Section number="9" title="Security" id="security">
        <p>
          We implement administrative, technical, and organizational measures designed to protect
          your information — including encryption in transit (TLS), encryption at rest for sensitive
          fields such as third-party credentials, access controls, and regular backups. No method of
          transmission or storage is 100% secure; if you become aware of any suspected security
          issue, please email{" "}
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
          <li>Port your data to another service in a commonly used, machine-readable format;</li>
          <li>Object to or restrict certain processing, including direct marketing;</li>
          <li>Withdraw consent at any time, without affecting the lawfulness of prior processing;</li>
          <li>Lodge a complaint with your local data-protection authority.</li>
        </ul>
        <p>
          You can exercise many of these rights directly from your account settings, or by contacting
          us at{" "}
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

      <Section number="12" title="Third-party links" id="third-parties">
        <p>
          The Service may contain links to third-party websites or integrations (such as TikTok,
          YouTube, Instagram, Facebook, or AI providers). Their privacy practices are governed by
          their own policies. We recommend reviewing those policies before using their services.
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
