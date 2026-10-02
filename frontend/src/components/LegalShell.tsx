/**
 * The frame for the legal pages (Terms & Conditions, Privacy Policy): the
 * public site's nav and footer, a hero with glass cards, and a section
 * index that follows the reader down the page. The pages pass their text
 * through unchanged — this file changes the frame, never the wording.
 *
 * The cards say only what is true: the page's own "last updated" date, a
 * reading time counted from the words actually on the page, and a link to
 * the other policy. (The preview had a line promising members an email
 * before material changes; nothing sends one, so it is not here.)
 */
import MarketingShell from "@/components/marketing/MarketingShell";
import LegalBody from "@/components/marketing/LegalBody";

type Props = {
  title: string;
  subtitle?: string;
  lastUpdated: string;
  children: React.ReactNode;
};

/** The hero headline per page: a plain lead-in, then the softer half. */
const HEADLINE: Record<string, [string, string]> = {
  "Terms & Conditions": ["The terms of using", "Icreateflow."],
  "Privacy Policy": ["How we handle", "your data."],
};

export default function LegalShell({ title, subtitle, lastUpdated, children }: Props) {
  const [lead, soft] = HEADLINE[title] ?? [title, ""];
  const other = title === "Privacy Policy"
    ? { href: "/terms", label: "Terms & Conditions" }
    : { href: "/privacy", label: "Privacy Policy" };

  return (
    <MarketingShell>
      <LegalBody title={title} lead={lead} soft={soft} subtitle={subtitle} lastUpdated={lastUpdated} other={other}>
        {children}
      </LegalBody>
    </MarketingShell>
  );
}

export function Section({
  id,
  number,
  title,
  children,
}: {
  id?: string;
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  // Every section needs an id for the index; the pages give most of them one.
  return (
    <section id={id ?? `section-${number}`} className="scroll-mt-28" data-legal-section>
      <h2>{number}. {title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}
