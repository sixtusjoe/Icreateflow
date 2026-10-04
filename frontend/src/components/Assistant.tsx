"use client";

/** The assistant — a button on every page, and an unprompted note that
 *  says what the page in front of you is for.
 *
 *  Two rules it follows:
 *
 *  - Admin only. It is rendered for nobody else rather than rendered and
 *    refusing, so it cannot become a button that silently does nothing.
 *  - Nothing it says is a claim about live state. The write-ups below are
 *    descriptions of what a page does and what commonly goes wrong on it,
 *    which stay true; a hardcoded "one post stuck since 13 Apr" would
 *    become a lie the moment it was fixed. The model, when it is wired,
 *    is what will read the actual numbers.
 *
 *  Dismissal is remembered per route: a "go away" on Posts is about the
 *  note on Posts, not about every page for the rest of the session.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Info, Send, X, Zap } from "lucide-react";
import { Tag } from "@/components/kit";

export type Blurb = {
  /** The nudge headline. */
  title: string;
  /** The nudge body, typed in. The note is a fixed 216px square, which fits
   *  a two-line title and about 110 characters here. Longer copy is clipped
   *  rather than pushing the footer out — keep it under that. */
  line: string;
  /** What the panel's bubble cycles through. */
  panel: string[];
  /** What to offer under "Try asking". */
  asks: string[];
};

const FALLBACK: Blurb = {
  title: "Ask about anything on this page",
  line: "I can read your brands, posts, schedule and settings, and say what is actually set.",
  panel: [
    "I read the same tables this page does, so I can tell you what is set rather than what should be.",
    "Most things that go wrong here fail quietly — no error, no log. Ask and I will say which one it was.",
    "If something has not happened, start by asking me what is blocking it.",
  ],
  asks: [
    "What is blocking a post right now?",
    "Which accounts still need connecting?",
    "What would break if I removed the Anthropic key?",
    "Why is every account posting the same caption?",
    "What happens when I press Build?",
    "How do I get TikTok to post live instead of to drafts?",
  ],
};

/** Longest prefix wins, so /posts/new beats /posts. */
const BLURBS: [string, Blurb][] = [
  [
    "/posts/new",
    {
      title: "Building a post, start to finish",
      line: "Slides come in from a TikTok link or an upload, then each account gets its own picture and caption.",
      panel: [
        "A post is slides plus one variation per account. The master keeps the original; every variation can swap a picture and gets its caption rewritten.",
        "Nothing is rendered until you press Build. Until then there are no files, and Preview has nothing to show.",
        "Importing reads the text off each slide with Claude, with Google Vision behind it. Without an Anthropic key the slides come in blank.",
      ],
      asks: [
        "What does each step on this page do?",
        "Why did my import come in with no text?",
        "What is the difference between the master and a variation?",
        "What happens when I press Build?",
        "Why can I not use “Make it with AI”?",
        "Do I have to set a time before it will go out?",
      ],
    },
  ],
  [
    "/posts",
    {
      title: "Everything you have made",
      line: "Drafts, scheduled posts and the ones that went out — and what each is still waiting on.",
      panel: [
        "A post with no time on it stays a draft forever. Nothing will chase it, and nothing will tell you.",
        "Deleting a post takes its slides, variations and outputs with it, and none of that is recoverable. Duplicate before you experiment.",
        "“Built” means rendered files on disk. A post can look finished and have nothing behind it if the output folder was cleaned.",
      ],
      asks: [
        "Which of these posts is actually ready to go?",
        "Why is this post still a draft?",
        "What does deleting a post remove?",
        "How do I duplicate a post before changing it?",
        "What does Built mean here?",
        "Why can I not open Preview on this one?",
      ],
    },
  ],
  [
    "/brands",
    {
      title: "Where accounts get their sign-ins",
      line: "A handle is only a name. Posting needs a token per account per platform, connected here and nowhere else.",
      panel: [
        "One brand with two accounts and four platforms is eight separate sign-ins. A handle without a token posts nothing.",
        "The master account holds the original slides. Variations get their own picture per slide and their own rewritten caption.",
        "Colour, timezone and the times of day a brand posts are set here, per brand — not in Settings.",
      ],
      asks: [
        "Which accounts still need connecting?",
        "Why does a handle alone not post anything?",
        "What is the difference between the master and a variation?",
        "Where do posting times come from?",
        "What happens when a token expires?",
        "How many sign-ins does this brand need?",
      ],
    },
  ],
  [
    "/schedule",
    {
      title: "What is queued, and what is stuck",
      line: "The scheduler looks every 60 seconds. When it cannot send, it puts the post back without saying why.",
      panel: [
        "Dispatch runs every minute. With no public address set it flips a post to posting, finds nowhere to serve the video from, sets it back, and writes no log.",
        "A post sitting past its time in Scheduled is almost always that — not a platform refusing it.",
        "The public address is an admin setting. Nothing on this page or in Settings can fix it.",
      ],
      asks: [
        "Why has this post not gone out?",
        "What does the scheduler actually do every minute?",
        "Where do I set the public address?",
        "Why is a post overdue but still Scheduled?",
        "What timezone are these times in?",
        "Can I send one of these right now?",
      ],
    },
  ],
  [
    "/music",
    {
      title: "The audio that goes under a render",
      line: "Tracks here get attached per post and per platform — TikTok never sees them, because it takes photos.",
      panel: [
        "Music is attached per post, and can differ per platform. The legacy slot falls back to whichever platform track is set.",
        "The 9:16 video render is for YouTube, Instagram and Facebook. TikTok takes the slides as a photo set, so no audio reaches it.",
        "A track only reaches a post once that post has been built again — changing it does not touch an existing render.",
      ],
      asks: [
        "Which posts is this track on?",
        "Why does TikTok not get the music?",
        "Can I use a different track per platform?",
        "Do I have to rebuild a post after changing its music?",
        "What formats can I upload here?",
        "Why is my video silent?",
      ],
    },
  ],
  [
    "/outreach",
    {
      title: "Campaigns, and why a send stops",
      line: "Targets move through queued, processing, sent, failed and skipped — each for a reason worth reading.",
      panel: [
        "A campaign only sends while it is running and inside its window. Paused or outside the window, targets sit queued and nothing is wrong.",
        "Skipped is not failed. It usually means the target was filtered out before a send was attempted.",
        "Each account has its own limits. A campaign spreads across the accounts you gave it, not evenly but within what each will take.",
      ],
      asks: [
        "Why has this campaign stopped sending?",
        "What is the difference between skipped and failed?",
        "Which accounts are doing the sending here?",
        "What do the per-account limits do?",
        "Why are targets still queued?",
        "How do I retry the ones that failed?",
      ],
    },
  ],
  [
    "/clipping",
    {
      title: "One clip, made to differ per account",
      line: "Re-encoding and caption rewriting are what stop the same clip arriving twice as the same file.",
      panel: [
        "Re-encoding makes imperceptible changes per account and platform, so the same clip does not arrive twice as an identical file.",
        "Caption rewriting asks Claude for one caption per account and platform, cached so each pair is written once. It needs the Anthropic key.",
        "Post discovery finds videos you published from your phone and adds them for view tracking. It is part of Clipping, not a setting.",
      ],
      asks: [
        "What does re-encoding actually change?",
        "Why is every account posting the same caption?",
        "What is post discovery and has it ever run?",
        "Where are these two switches set?",
        "Why did this clip fail to post?",
        "How is a clip different from a post?",
      ],
    },
  ],
  [
    "/settings",
    {
      title: "The keys the whole app runs on",
      line: "A missing key is not an empty box — it is a feature that fails quietly three pages away.",
      panel: [
        "Anthropic and OpenAI are stored against your account. Google Vision is one key for the workspace.",
        "Without an OpenAI key, “Make it with AI” refuses on the Variations step and says very little about why.",
        "The slide and video defaults here scale the renderer's own numbers. A post already built keeps its slides until you build it again.",
      ],
      asks: [
        "Which features are switched off right now?",
        "What breaks without the OpenAI key?",
        "Are these keys shared with other users?",
        "What do the text sizes actually change?",
        "Why is oauth_redirect_base not on this page?",
        "Does changing a default touch a post already built?",
      ],
    },
  ],
  [
    "/admin",
    {
      title: "The settings only you can reach",
      line: "Platform sign-in credentials and the public address live here — including the one that stops dispatch.",
      panel: [
        "oauth_redirect_base is the public address the platforms fetch a video from. Without it, nothing is ever dispatched.",
        "These are site-wide credentials, not per-account tokens. The per-account sign-ins happen on Brands.",
        "Changing a platform's app credentials invalidates the sign-ins made with the old ones.",
      ],
      asks: [
        "What does oauth_redirect_base do?",
        "Why is nothing being dispatched?",
        "What is the difference between these and the Brands sign-ins?",
        "What happens if I change a client secret?",
        "How do I test the email configuration?",
        "Which of these are required to post at all?",
      ],
    },
  ],
  [
    "/help",
    {
      title: "What is stopping you, in one place",
      line: "The checks above are read live. Everything below them is what the app means when it refuses.",
      panel: [
        "The checks at the top of this page are read from your own tables each time it opens, not from a fixed list.",
        "The refusal table is the app's own error vocabulary — the exact lines the post screen shows you.",
        "The card about silence is the one that matters most. A thing that fails with no message is the hardest to find.",
      ],
      asks: [
        "What is blocking a post right now?",
        "Which accounts still need connecting?",
        "What would break if I removed the Anthropic key?",
        "Why is every account posting the same caption?",
        "What happens when I press Build?",
        "How do I get TikTok to post live instead of to drafts?",
      ],
    },
  ],
];

export function blurbFor(pathname: string): Blurb {
  let best: Blurb | null = null;
  let bestLen = -1;
  for (const [prefix, b] of BLURBS) {
    if ((pathname === prefix || pathname.startsWith(prefix + "/")) && prefix.length > bestLen) {
      best = b;
      bestLen = prefix.length;
    }
  }
  return best ?? FALLBACK;
}

/* ------------------------------------------------------------------ */

const FIRST_DELAY = 2200;
const RETURN_DELAY = 5000;
/** How long the note stays before it gets out of the way on its own. It is
 *  216px in the bottom-right corner and it takes pointer events, so
 *  anything under it — a card's own menu, a button — cannot be clicked
 *  while it is up. Sitting there until dismissed made it an obstacle. */
const LINGER = 12000;

/** A typewriter that cleans up after itself. A timer left running behind a
 *  closed panel is a leak, not an animation. */
function useTypewriter(text: string, startDelay: number) {
  const [shown, setShown] = useState("");
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    timer.current = setTimeout(() => {
      if (reduce) {
        setShown(text);
        setDone(true);
        return;
      }
      let i = 0;
      const step = () => {
        i += 1;
        setShown(text.slice(0, i));
        if (i < text.length) {
          // a hair slower after a full stop, which is how reading feels
          timer.current = setTimeout(step, /[.,—]/.test(text[i - 1]) ? 120 : 18);
        } else {
          setDone(true);
        }
      };
      step();
    }, startDelay);

    return () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [text, startDelay]);

  return { shown, done };
}

const CARET =
  "after:ml-0.5 after:inline-block after:h-[0.95em] after:w-0.5 after:align-[-1px] after:bg-current after:opacity-80 after:content-['']";

function Nudge({ blurb, onOpen, onDismiss }: { blurb: Blurb; onOpen: () => void; onDismiss: () => void }) {
  const { shown, done } = useTypewriter(blurb.line, 420);
  return (
    <div
      role="status"
      onClick={onOpen}
      className="fixed bottom-[78px] right-[22px] z-[25] flex h-[216px] max-md:hidden w-[216px] cursor-pointer flex-col rounded-[20px] border border-white/[0.16] p-[15px] text-left
                 bg-[linear-gradient(152deg,color-mix(in_srgb,var(--primary)_94%,transparent),color-mix(in_srgb,var(--primary)_86%,transparent))]
                 shadow-[0_22px_48px_-16px_rgba(11,13,18,0.5),inset_0_1px_0_rgba(255,255,255,0.18)]
                 backdrop-blur-[24px] backdrop-saturate-[1.8]
                 motion-safe:animate-[nudgein_.38s_cubic-bezier(.2,.9,.3,1.12)_both]
                 after:absolute after:-bottom-[5px] after:right-7 after:h-2.5 after:w-2.5 after:rotate-45 after:border-b after:border-r after:border-white/[0.16] after:content-['']
                 after:bg-[color-mix(in_srgb,var(--primary)_90%,transparent)]
                 dark:border-[rgba(11,13,18,0.16)] dark:after:border-[rgba(11,13,18,0.16)]"
    >
      {/* a light sweeping across the glass, so it reads as glass and as alive */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]
                   motion-safe:before:absolute motion-safe:before:inset-y-0 motion-safe:before:-left-1/2 motion-safe:before:w-[42%]
                   motion-safe:before:-skew-x-[14deg] motion-safe:before:content-['']
                   motion-safe:before:bg-[linear-gradient(100deg,transparent,rgba(255,255,255,0.16),transparent)]
                   motion-safe:before:animate-[sweep_6s_ease-in-out_.55s_infinite]
                   dark:motion-safe:before:bg-[linear-gradient(100deg,transparent,rgba(11,13,18,0.1),transparent)]"
      />
      <span className="mb-[13px] flex items-start justify-between">
        <span className="relative grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] border border-white/[0.14] bg-white/[0.14] text-primary-foreground
                         motion-safe:after:absolute motion-safe:after:-inset-1 motion-safe:after:rounded-[14px] motion-safe:after:border-[1.5px] motion-safe:after:border-white/40 motion-safe:after:content-['']
                         motion-safe:after:animate-[halo_2.6s_ease-out_infinite]
                         dark:border-[rgba(11,13,18,0.12)] dark:bg-[rgba(11,13,18,0.1)] dark:motion-safe:after:border-[rgba(11,13,18,0.32)]">
          <Zap className="h-[15px] w-[15px]" />
        </span>
        <button
          type="button"
          aria-label="Dismiss"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          className="relative z-[1] grid h-[22px] w-[22px] flex-none place-items-center rounded-[7px] text-[color-mix(in_srgb,var(--primary-foreground)_62%,transparent)] transition-colors hover:bg-white/[0.14] hover:text-primary-foreground dark:hover:bg-[rgba(11,13,18,0.1)]"
        >
          <X className="h-[11px] w-[11px]" strokeWidth={2.6} />
        </button>
      </span>
      <span className="mb-1.5 text-[13px] font-bold leading-[1.35] text-primary-foreground">
        {blurb.title}
      </span>
      <span
        className={`overflow-hidden text-[11.5px] leading-[1.5] text-[color-mix(in_srgb,var(--primary-foreground)_74%,transparent)] ${
          done ? "" : CARET
        }`}
      >
        {shown}
      </span>
      <span className="mt-auto flex items-center gap-1.5 border-t border-white/[0.14] pt-[11px] text-[11.5px] font-semibold text-primary-foreground dark:border-[rgba(11,13,18,0.14)]">
        Ask me
        <ArrowRight className="h-[13px] w-[13px] transition-transform" />
      </span>
    </div>
  );
}

/** The panel's header. The signed-in pages use the default; the public
 *  pages pass their own, because a visitor has no workspace to read. */
export type Head = { title: string; tag: string; sub: string };

const WORKSPACE_HEAD: Head = {
  title: "Ask about this workspace",
  tag: "Admins",
  sub: "It reads your brands, posts and settings — not a manual",
};

function Panel({ blurb, head, onClose }: { blurb: Blurb; head: Head; onClose: () => void }) {
  const [line, setLine] = useState(0);
  const [draft, setDraft] = useState("");
  const { shown, done } = useTypewriter(blurb.panel[line % blurb.panel.length], 900);

  // Hold the finished line for a beat, then move to the next one.
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setLine((n) => n + 1), 3400);
    return () => clearTimeout(t);
  }, [done]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed bottom-[22px] right-[22px] z-[61] flex w-[378px] max-w-[calc(100vw-32px)] flex-col overflow-hidden rounded-[20px] border border-white/[0.55]
                 bg-[color-mix(in_srgb,var(--card)_62%,transparent)] backdrop-blur-[26px] backdrop-saturate-[1.8]
                 shadow-[0_30px_70px_-20px_rgba(11,13,18,0.42),0_2px_8px_-2px_rgba(11,13,18,0.12),inset_0_1px_0_rgba(255,255,255,0.7)]
                 motion-safe:animate-[pop_.22s_cubic-bezier(.2,.9,.3,1.1)_both]
                 dark:border-white/[0.12] dark:bg-[color-mix(in_srgb,var(--card)_58%,transparent)]
                 dark:shadow-[0_30px_70px_-20px_rgba(0,0,0,0.7),inset_0_1px_0_rgba(255,255,255,0.08)]"
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(160deg,rgba(255,255,255,0.55),rgba(255,255,255,0)_42%)] dark:bg-[linear-gradient(160deg,rgba(255,255,255,0.09),rgba(255,255,255,0)_45%)]"
      />
      <div className="relative grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-2.5 gap-y-[3px] border-b border-line-2 p-[14px_15px]">
        <span className="row-span-2 grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] bg-primary text-primary-foreground">
          <Zap className="h-[15px] w-[15px]" />
        </span>
        <span className="min-w-0 text-[13px] font-semibold">{head.title}</span>
        <Tag tone="draft">{head.tag}</Tag>
        <button
          type="button"
          aria-label="Close the assistant"
          onClick={onClose}
          className="grid h-[26px] w-[26px] flex-none place-items-center rounded-lg bg-[color-mix(in_srgb,var(--secondary)_70%,transparent)] text-subtle transition-colors hover:bg-secondary hover:text-foreground"
        >
          <X className="h-3 w-3" strokeWidth={2.4} />
        </button>
        <span className="col-start-2 col-end-[-1] text-[10.5px] leading-[1.4] text-subtle">
          {head.sub}
        </span>
      </div>

      <div className="relative max-h-[calc(100dvh-180px)] overflow-y-auto p-[15px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="flex items-start gap-[9px]">
          <span className="grid h-6 w-6 flex-none place-items-center rounded-lg bg-primary text-primary-foreground">
            <Zap className="h-3 w-3" />
          </span>
          <div className="min-h-[80px] flex-1 rounded-[14px] rounded-tl-[5px] border border-border bg-[color-mix(in_srgb,var(--card)_72%,transparent)] px-[13px] py-[11px]">
            <p
              className={`m-0 whitespace-pre-wrap text-xs leading-[1.6] text-muted-foreground ${done ? "" : CARET}`}
            >
              {shown}
            </p>
          </div>
        </div>
        <div className="relative ml-[33px] mt-2.5 flex items-start gap-1.5 text-[10.5px] leading-[1.45] text-subtle">
          <Info className="mt-0.5 h-[11px] w-[11px] flex-none" />
          <span>
            A scripted example, cycling through things that are true of this page. The model
            behind them is not connected yet.
          </span>
        </div>

        <div className="mb-[9px] mt-4 text-[10.5px] font-bold uppercase tracking-[0.09em] text-subtle">
          Try asking
        </div>
        <div className="flex flex-col gap-[7px]">
          {blurb.asks.map((sg) => (
            <button
              key={sg}
              type="button"
              onClick={() => setDraft(sg)}
              className="rounded-[11px] border border-border bg-[color-mix(in_srgb,var(--card)_70%,transparent)] px-3 py-[9px] text-left text-xs text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
            >
              {sg}
            </button>
          ))}
        </div>
      </div>

      <div className="relative flex gap-2 border-t border-line-2 p-[12px_15px]">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask anything about your setup…"
          disabled
          className="min-w-0 flex-1 rounded-[11px] border border-border bg-[color-mix(in_srgb,var(--secondary)_70%,transparent)] px-3 py-[9px] text-[12.5px] text-foreground outline-none placeholder:text-subtle"
        />
        <button
          type="button"
          disabled
          aria-label="Send"
          className="flex-none rounded-[11px] bg-primary px-[13px] py-[9px] text-primary-foreground opacity-45"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export default function Assistant({
  route,
  blurb = blurbFor(route),
  head = WORKSPACE_HEAD,
}: {
  route: string;
  /** What to say on this route. Defaults to the signed-in pages' write-ups. */
  blurb?: Blurb;
  head?: Head;
}) {
  const [open, setOpen] = useState(false);
  const [nudge, setNudge] = useState(false);
  // Per route: a "go away" on Posts is about the note on Posts. AppShell
  // keys this component on the route, so a new page remounts it and every
  // piece of state below starts fresh — no effect has to reset anything.
  const key = `assistant_nudge_seen:${route}`;
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === "undefined") return true;
    try {
      return sessionStorage.getItem(key) === "1";
    } catch {
      return false; // private window or blocked storage — show it
    }
  });
  // Whether the assistant has already had its turn here, which is what makes
  // the second appearance a return rather than a first arrival.
  const met = useRef(false);

  // It arrives on its own once the page has settled, and again a few seconds
  // after the panel is closed. Never over an open panel.
  useEffect(() => {
    if (dismissed || open || nudge) return;
    const t = setTimeout(
      () => {
        met.current = true;
        setNudge(true);
      },
      met.current ? RETURN_DELAY : FIRST_DELAY,
    );
    return () => clearTimeout(t);
  }, [dismissed, open, nudge]);

  // ...and it leaves on its own, so it is never a permanent obstacle over
  // whatever sits in that corner.
  useEffect(() => {
    if (!nudge) return;
    const t = setTimeout(() => setNudge(false), LINGER);
    return () => clearTimeout(t);
  }, [nudge]);

  /** The × — gone for the session, on this page. */
  const dismiss = useCallback(() => {
    setNudge(false);
    setDismissed(true);
    try {
      sessionStorage.setItem(key, "1");
    } catch {
      /* nothing to remember it with */
    }
  }, [key]);

  /** Opening it is not a dismissal, so the note is free to come back — and
   *  asking again undoes an earlier ×. The × means "not now"; reaching for
   *  the assistant afterwards says the note is welcome again. Without this,
   *  one × on a page left that page noteless for the rest of the session
   *  even after the user had gone back to the assistant of their own accord. */
  const openPanel = useCallback(() => {
    met.current = true;
    setNudge(false);
    setDismissed(false);
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* nothing was remembering it anyway */
    }
    setOpen(true);
  }, [key]);

  return (
    <>
      {nudge && !open && <Nudge blurb={blurb} onOpen={openPanel} onDismiss={dismiss} />}
      {open ? (
        <Panel blurb={blurb} head={head} onClose={() => setOpen(false)} />
      ) : (
        <button
          type="button"
          aria-label="Ask the assistant"
          onClick={openPanel}
          className="fixed bottom-[22px] right-[22px] z-[25] flex items-center gap-2 rounded-full bg-primary px-[17px] py-3 max-md:bottom-4 max-md:right-4 max-md:p-3 text-[12.5px] font-bold text-primary-foreground shadow-[0_12px_26px_-10px_rgba(11,13,18,0.6)] transition-[filter] hover:brightness-110"
        >
          <Zap className="h-[15px] w-[15px]" />
          <span className="max-md:sr-only">Ask</span>
        </button>
      )}
    </>
  );
}
