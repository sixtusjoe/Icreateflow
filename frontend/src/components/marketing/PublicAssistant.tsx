"use client";

/**
 * The assistant on the public pages — the very same component the signed-in
 * pages use (button, the note that arrives on its own, the panel), so it
 * looks and behaves identically. Only the words differ: a visitor has no
 * workspace for it to read, so it talks about the page in front of them.
 *
 * Same rule as inside the app: nothing here is a claim about live state,
 * only descriptions of what the product and the page do.
 */
import { usePathname } from "next/navigation";
import Assistant, { type Blurb, type Head } from "@/components/Assistant";
import { FAQ } from "./faq";

const HEAD: Head = {
  title: "Ask about Icreateflow",
  tag: "Visitors",
  sub: "It knows how campaigns, clips and outreach work",
};

const ASKS = FAQ.map(([q]) => q);

const HOME: Blurb = {
  title: "What Icreateflow does, in one place",
  line: "Your catalog goes out across your own TikTok, YouTube, Instagram and Facebook accounts until a view target is hit.",
  panel: [
    "You connect your own accounts. Nothing is ever posted from an account you do not control.",
    "Each handle gets its own variation — overlays, captions, generated faces — so no two posts arrive as the same file.",
    "When the view target is hit, posting stops on its own. Nobody has to remember to switch it off.",
  ],
  asks: ASKS,
};

const LEGAL_ASKS = [
  "What data do you keep about my accounts?",
  "Can I delete my account myself?",
  "Who do I contact about this policy?",
  ...ASKS.slice(0, 3),
];

const BLURBS: Record<string, Blurb> = {
  "/": HOME,
  "/terms": {
    title: "The rules for using Icreateflow",
    line: "What you agree to when you sign up, section by section. The index on the left jumps to each one.",
    panel: [
      "The date at the top is the version you are reading. When the terms change, that date changes with them.",
      "The index beside the text follows you as you scroll, so you always know which section you are in.",
      "The Privacy Policy sits beside these terms — the link is in the card at the top of this page.",
    ],
    asks: LEGAL_ASKS,
  },
  "/privacy": {
    title: "What we keep, and why",
    line: "What Icreateflow stores about you and your accounts, section by section. The index on the left jumps to each.",
    panel: [
      "The date at the top is the version you are reading. When the policy changes, that date changes with it.",
      "You can delete your account yourself from the Account page once you are signed in.",
      "The Terms sit beside this policy — the link is in the card at the top of this page.",
    ],
    asks: LEGAL_ASKS,
  },
};

export default function PublicAssistant() {
  const route = usePathname();
  // Keyed on the route, as AppShell does, so a new page starts it fresh.
  return <Assistant key={route} route={route} blurb={BLURBS[route] ?? HOME} head={HEAD} />;
}
