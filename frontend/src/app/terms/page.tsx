import type { Metadata } from "next";
import Link from "next/link";
import LegalShell, { Section } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Terms & Conditions — Icreateflow",
  description:
    "The terms that govern your use of Icreateflow, a promotion and distribution platform for artists, brands, movies and podcasts.",
  alternates: { canonical: "/terms" },
  openGraph: {
    type: "article",
    url: "https://icreateflow.com/terms",
    title: "Terms & Conditions — Icreateflow",
    description:
      "The terms that govern your use of Icreateflow, a promotion and distribution platform for artists, brands, movies and podcasts.",
  },
};

export default function TermsPage() {
  return (
    <LegalShell
      title="Terms & Conditions"
      subtitle="Please read these terms carefully before using Icreateflow. By creating an account or using the Service, you agree to be bound by them."
      lastUpdated="April 19, 2026"
    >
      <Section number="1" title="Acceptance of these Terms" id="acceptance">
        <p>
          These Terms &amp; Conditions (the &ldquo;<strong>Terms</strong>&rdquo;) form a legally binding
          agreement between you and Icreateflow (&ldquo;<strong>Icreateflow</strong>&rdquo;, &ldquo;we&rdquo;,
          &ldquo;us&rdquo;, or &ldquo;our&rdquo;) governing your access to and use of the Icreateflow
          promotion platform, accessible at{" "}
          <a href="https://icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            icreateflow.com
          </a>
          , as well as its dashboards, APIs, campaign tools, and any related services (collectively, the &ldquo;<strong>Service</strong>&rdquo;).
        </p>
        <p>
          By creating an account, clicking &ldquo;I agree&rdquo;, or otherwise accessing the Service,
          you confirm that you have read, understood, and accepted these Terms and our{" "}
          <Link href="/privacy" className="font-medium underline underline-offset-2 hover:text-foreground">
            Privacy Policy
          </Link>
          . If you do not agree, you must not use the Service.
        </p>
      </Section>

      <Section number="2" title="Who may use the Service" id="eligibility">
        <p>
          You must be at least 18 years old (or the age of majority in your jurisdiction) and legally
          capable of entering into contracts to use the Service. If you are using the Service on
          behalf of an artist, label, brand, studio, podcast network, or other organization, you
          represent that you have authority to bind that organization to these Terms, and
          &ldquo;you&rdquo; refers to that organization.
        </p>
        <p>
          You may not use the Service if you are barred from receiving services under the laws of
          your country of residence or any other applicable jurisdiction.
        </p>
      </Section>

      <Section number="3" title="Accounts and security" id="accounts">
        <ul className="list-disc space-y-2 pl-6">
          <li>You are responsible for maintaining the confidentiality of your login credentials and for all activity that occurs under your account.</li>
          <li>You must provide accurate, current, and complete information — including details for each artist, brand, movie, podcast, or product being promoted — and keep that information up to date.</li>
          <li>Notify us immediately at <span className="font-medium">support@icreateflow.com</span> if you suspect any unauthorized access or breach of security.</li>
          <li>We may suspend or terminate accounts that show signs of compromise, abuse, or policy violation.</li>
        </ul>
      </Section>

      <Section number="4" title="The Service" id="service">
        <p>
          Icreateflow is a promotion and distribution platform that helps artists, brands, movie
          studios, podcasters, and other creators push their content across social platforms at
          scale. Depending on your plan, the Service may let you:
        </p>
        <ul className="list-disc space-y-2 pl-6">
          <li>Build a catalog of clips by uploading MP4s or syncing a public Google Drive folder;</li>
          <li>Register an unlimited network of &ldquo;variation&rdquo; accounts — your own TikTok, YouTube, Instagram, and Facebook handles — connected by OAuth;</li>
          <li>Launch <strong>campaigns</strong> with a posts-per-day cadence, a posting window in your timezone, and an optional view target that automatically stops the campaign when reached;</li>
          <li>Distribute each clip across every connected account and platform on a rotation that respects platform rate limits and audience fit;</li>
          <li>Generate unique image and overlay variations (for slide-format content) to reduce duplicate-detection risk on destination platforms;</li>
          <li>Track aggregated view counts, post status, and campaign progress in real time, and export campaign statistics as CSV;</li>
          <li>Pause and resume automatically when your catalog is exhausted or topped up.</li>
        </ul>
        <p>
          Icreateflow provides the tooling and automation. The Service is <strong>not</strong> a guarantee
          of views, streams, sales, chart position, or any specific promotional outcome. Results
          depend on the content, the accounts you connect, platform algorithms, and factors outside
          our control.
        </p>
        <p>
          We continuously improve the Service and may add, change, or remove features at any time.
          Material changes will be communicated through the Service or by email.
        </p>
      </Section>

      <Section number="5" title="Your content" id="content">
        <p>
          &ldquo;<strong>Your Content</strong>&rdquo; means any text, images, video, audio, music,
          trailers, episodes, captions, artwork, brand assets, API keys, and other material that you
          upload, import, generate, or otherwise make available through the Service — including all
          clips, captions, and promotional copy that the Service distributes on your behalf.
        </p>
        <p>
          You retain all ownership rights in Your Content. You grant Icreateflow a worldwide,
          non-exclusive, royalty-free license to host, store, reproduce, modify (for formatting,
          transcoding, or rendering), transmit, and display Your Content, and to publish it to the
          third-party platforms and accounts you have connected, solely for the purpose of operating
          the Service and delivering the promotion campaigns you configure.
        </p>
        <p>
          You represent and warrant that you own Your Content or have all rights, licenses,
          clearances, and permissions necessary — including from any featured artists, labels,
          rights-holders, distributors, studios, publishers, talent, or performers — to use Your
          Content on the Service and to publish it to the connected third-party platforms.
        </p>
      </Section>

      <Section number="6" title="AI-generated output" id="ai">
        <p>
          The Service uses third-party artificial-intelligence models (including, without limitation,
          OCR, language models, and image-generation models) to assist in producing promotional
          variations. You acknowledge that:
        </p>
        <ul className="list-disc space-y-2 pl-6">
          <li>AI output may contain inaccuracies, hallucinations, or unintended similarities to third-party material.</li>
          <li>You are solely responsible for reviewing, editing, and approving any AI-generated material before it is scheduled for distribution.</li>
          <li>The same or similar prompts may produce similar outputs for other users; Icreateflow cannot guarantee that any AI output is unique.</li>
          <li>Use of AI output is subject to the terms of the underlying model providers as well as these Terms.</li>
        </ul>
      </Section>

      <Section number="7" title="Acceptable use" id="acceptable-use">
        <p>You agree not to, and not to allow anyone else to:</p>
        <ul className="list-disc space-y-2 pl-6">
          <li>Upload, promote, or distribute content that is illegal, infringing, defamatory, harassing, hateful, sexually explicit involving minors, or that promotes violence or self-harm;</li>
          <li>Promote content that you do not have the rights to — including leaked music, pirated films or episodes, unlicensed trailers, or unauthorized recordings;</li>
          <li>Use the Service to run misleading advertising, engage in astroturfing, or impersonate any person, artist, brand, or entity;</li>
          <li>Inflate engagement through bots, click-farms, purchased views, or other artificial means — the Service distributes real content from real accounts you control;</li>
          <li>Connect accounts you do not own or are not authorized to operate;</li>
          <li>Reverse engineer, decompile, or attempt to derive source code from the Service except as permitted by law;</li>
          <li>Interfere with, overload, or disrupt the Service, its infrastructure, or other users;</li>
          <li>Bypass rate limits, access controls, or security measures;</li>
          <li>Use the Service to violate the rules, community guidelines, or monetization policies of any connected third-party platform (TikTok, YouTube, Instagram, Facebook, or others).</li>
        </ul>
        <p>
          We may remove content, pause campaigns, disable integrations, or suspend accounts that
          violate these rules, with or without notice, to protect the Service, its users, and the
          platforms we integrate with.
        </p>
      </Section>

      <Section number="8" title="Third-party platforms & connected accounts" id="third-parties">
        <p>
          When you connect the Service to a third-party platform (via OAuth or an API key), you
          authorize Icreateflow to access and act on that account on your behalf — including
          uploading videos, setting captions, reading published post metadata, and retrieving view
          and engagement statistics — to perform the promotional activity you have configured.
        </p>
        <p>
          You remain bound by the terms, policies, and community guidelines of those third-party
          platforms. If a platform suspends, limits, or removes an account or a post you published
          through the Service, that is a decision between you and that platform. We are not
          responsible for the availability, performance, policies, or enforcement actions of any
          third-party platform, and we may disable an integration at any time.
        </p>
      </Section>

      <Section number="9" title="Campaigns, plans, fees & billing" id="billing">
        <ul className="list-disc space-y-2 pl-6">
          <li>Paid plans, campaign credits, and any usage-based fees are described on our pricing page or in your order form.</li>
          <li>Fees are charged in advance for the applicable billing period and are non-refundable except where required by law. Unused campaign capacity does not roll over unless stated otherwise.</li>
          <li>You authorize us and our payment processor to charge the payment method on file. If a charge fails, we may suspend paid features until payment is received.</li>
          <li>Campaign targets (such as view goals) describe the point at which the Service stops pushing content — they are not a warranty that the target will be reached.</li>
          <li>We may change prices with at least 30 days&rsquo; prior notice; changes take effect at your next renewal.</li>
        </ul>
      </Section>

      <Section number="10" title="Intellectual property" id="ip">
        <p>
          The Service, including its software, design, and trademarks, is owned by Icreateflow and its
          licensors and is protected by intellectual-property laws. Except for the limited license to
          use the Service granted in these Terms, no rights are transferred to you.
        </p>
        <p>
          You may submit feedback, ideas, or suggestions about the Service. You agree that we may
          use that feedback without obligation or compensation to you.
        </p>
      </Section>

      <Section number="11" title="Termination" id="termination">
        <p>
          You may stop using the Service and delete your account at any time from the settings page.
          You may also end or reset any campaign at any time — historical campaign statistics remain
          downloadable for the retention period described in our Privacy Policy.
        </p>
        <p>
          We may suspend or terminate your access at any time, with or without notice, if we
          reasonably believe that you have breached these Terms or that continued access poses a
          risk to the Service, to us, to other users, or to the platforms we integrate with.
        </p>
        <p>
          Upon termination, your right to use the Service ends immediately. Sections that by their
          nature should survive (including ownership, disclaimers, limitations of liability, and
          governing law) will survive termination.
        </p>
      </Section>

      <Section number="12" title="Disclaimers" id="disclaimers">
        <p>
          THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; AND &ldquo;AS AVAILABLE&rdquo;, WITHOUT WARRANTIES OF ANY
          KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
          NON-INFRINGEMENT. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, SECURE, OR
          ERROR-FREE, THAT ANY CAMPAIGN WILL REACH ANY PARTICULAR VIEW, STREAM, OR SALES OUTCOME, OR
          THAT ANY AI-GENERATED OUTPUT WILL BE ACCURATE OR UNIQUE.
        </p>
      </Section>

      <Section number="13" title="Limitation of liability" id="liability">
        <p>
          TO THE MAXIMUM EXTENT PERMITTED BY LAW, Icreateflow AND ITS AFFILIATES WILL NOT BE LIABLE FOR
          ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF
          PROFITS, REVENUE, DATA, REPUTATION, OR GOODWILL, ARISING OUT OF OR IN CONNECTION WITH THESE
          TERMS OR THE SERVICE — including any action taken by a third-party platform against a
          connected account or a post distributed through the Service.
        </p>
        <p>
          OUR TOTAL LIABILITY FOR ALL CLAIMS ARISING OUT OF OR RELATING TO THESE TERMS OR THE SERVICE
          WILL NOT EXCEED THE GREATER OF (A) THE AMOUNTS YOU PAID US IN THE TWELVE MONTHS PRIOR TO
          THE EVENT GIVING RISE TO THE CLAIM, OR (B) US$100.
        </p>
      </Section>

      <Section number="14" title="Indemnification" id="indemnity">
        <p>
          You agree to defend, indemnify, and hold harmless Icreateflow, its affiliates, and their
          respective officers, directors, and employees from any claim or demand, including
          reasonable legal fees, arising out of (i) Your Content or the promotion of Your Content
          through the Service, (ii) your use of the Service, (iii) your violation of these Terms,
          (iv) any rights clearance you failed to obtain, or (v) your violation of any law or the
          rights of a third party.
        </p>
      </Section>

      <Section number="15" title="Changes to these Terms" id="changes">
        <p>
          We may update these Terms from time to time. When we do, we will revise the &ldquo;Last
          updated&rdquo; date at the top and, for material changes, provide additional notice through
          the Service or by email. Continued use of the Service after the updated Terms take effect
          constitutes acceptance of the revised Terms.
        </p>
      </Section>

      <Section number="16" title="Governing law & disputes" id="governing-law">
        <p>
          These Terms are governed by the laws of the jurisdiction in which Icreateflow is established,
          without regard to conflict-of-laws principles. Any dispute arising out of or relating to
          these Terms or the Service will be resolved exclusively in the competent courts of that
          jurisdiction, unless otherwise required by applicable consumer-protection law.
        </p>
      </Section>

      <Section number="17" title="Contact" id="contact">
        <p>
          Questions about these Terms? Reach us at{" "}
          <a href="mailto:legal@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            legal@icreateflow.com
          </a>
          . For security reports, use{" "}
          <a href="mailto:security@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            security@icreateflow.com
          </a>
          . For rights, takedown, or clearance questions, write to{" "}
          <a href="mailto:rights@icreateflow.com" className="font-medium underline underline-offset-2 hover:text-foreground">
            rights@icreateflow.com
          </a>
          .
        </p>
      </Section>
    </LegalShell>
  );
}
