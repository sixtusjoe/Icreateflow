"use client";

/** Help & Support.
 *
 *  There has never been a page here. The sidebar has linked to /help since
 *  the beginning and the route did not exist, so every click was a 404.
 *  That made this the one page in the redesign with nothing to copy — and
 *  the one where inventing content would have been easiest and worst.
 *
 *  So everything on it comes from somewhere real:
 *
 *  - The readiness checks are this workspace, read live from /api/brands
 *    and /api/settings. Every one of them is a thing that fails without
 *    saying so, and every one of them is a thing the reader can fix.
 *
 *  This is a user page, so it calls no admin endpoint and carries no
 *  admin check. It used to read /api/admin/site-config and, for an admin,
 *  print "the public address is unset" with a link to /admin — which put
 *  an admin-only fault on a page every user opens, and told a user nothing
 *  when it was hidden from them. That fault now lives where it can be
 *  acted on: "Needs an admin" on the admin Overview. The FAQ below still
 *  explains the symptom, because a user whose post did not go out deserves
 *  to know why; it just does not pretend they can fix it.
 *  - The refusal table is `_friendly_error` in main.py, quoted rather than
 *    paraphrased, because those strings are what the operator actually
 *    reads on the post screen.
 *  - The quiet-failure list is the set of things that produce no error at
 *    all. That card is the reason the page exists: a help page that only
 *    explains error messages is no help when the app says nothing.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  ExternalLink,
  FileText,
  Info,
  RefreshCw,
  Search,
  Send,
  Shield,
  X,
} from "lucide-react";
import {
  getBrands,
  getPost,
  getPosts,
  getSettings,
} from "@/lib/api";
import {
  Card,
  CardBody,
  CardHead,
  Chip,
  DotsMenu,
  FigureLine,
  FigureStrong,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  Skeleton,
  Tag,
} from "@/components/kit";

/* ------------------------------------------------------------------ */
/* the static reference material                                       */
/* ------------------------------------------------------------------ */

const STEPS: [string, string, string][] = [
  ["A brand", "Colour, timezone and the times of day it posts.", "Brands"],
  [
    "Accounts under it",
    "One master, the rest variations. Each needs its own sign-in per platform — the handle alone does nothing.",
    "Brands",
  ],
  ["A post, with slides", "Imported from a TikTok link, or uploaded.", "New Post"],
  [
    "A variation per account",
    "Keep the original picture, upload another, or make one with AI. The caption is rewritten per account.",
    "The editor",
  ],
  [
    "Build",
    "Renders the 3:4 slides and a 9:16 video for every account. Until this runs there are no files.",
    "The editor",
  ],
  [
    "A time on it",
    "A date and a slot. Without one a post stays a draft forever and nothing will chase it.",
    "Schedule",
  ],
  [
    "Dispatch",
    "Every 60 seconds the scheduler looks for anything due. This step needs the public address.",
    "Runs itself",
  ],
];

/** Quoted from `_friendly_error` in main.py — these are the exact lines the
 *  post screen shows, so searching for one finds it here. */
const REFUSALS: [string, string][] = [
  [
    "TikTok account has reached its active user cap",
    "This app's live-post quota, not your account's. Send the post to your TikTok drafts instead and publish it from the phone.",
  ],
  [
    "TikTok app not yet audited — video sent to drafts",
    "Not a failure. The video is in your TikTok inbox; open the app and publish it.",
  ],
  [
    "Account credentials expired — reconnect the account",
    "The token lapsed. Open the brand and press Connect on that platform's tile.",
  ],
  [
    "Instagram couldn't fetch the video — retrying will serve it through our server",
    "Instagram could not reach the file the first time. Press Retry once; the second attempt goes a different way.",
  ],
  [
    "Facebook requires identity verification",
    "Facebook wants a check on the Page itself. Open the Facebook app and complete it there — nothing here can clear it.",
  ],
  [
    "Rate limit hit — try again in a few hours",
    "The platform is throttling, not rejecting. The post is unchanged.",
  ],
  ["Content file missing — re-upload the clip", "The render was cleaned off disk. Build the post again."],
  ["Slot lapsed while artist was paused", "Nothing to do — it is re-scheduled automatically."],
];

const QUIET: [string, string][] = [
  [
    "A post sits past its time, still “Scheduled”",
    "The workspace has no public address. No log, no error, every minute — an admin sets it.",
  ],
  [
    "A slide imports with no text on it",
    "No Anthropic key, or neither reader could make out that image.",
  ],
  [
    "Every account posts the same caption",
    "Caption rewriting is off, or the Anthropic key is missing.",
  ],
  [
    "Post discovery shows nothing",
    "It has never run on this workspace — that is not the same as finding nothing.",
  ],
];

/** Grounded in the code, not in what a help page usually asks. */
const FAQ: [string, React.ReactNode, string][] = [
  [
    "Why has my scheduled post not gone out?",
    <>
      The dispatcher runs every 60 seconds, but it skips silently when the workspace has no
      public address set. It flips the post to <Mono>posting</Mono>, finds nowhere to serve the
      video from, sets it back to <Mono>scheduled</Mono> and writes no log — which is why there
      is nothing to find. Ask an admin to set the workspace&apos;s public address; it goes out on
      the next pass after that, with nothing to redo on the post itself.
    </>,
    "dispatcher 60 seconds public address posting scheduled log admin next pass",
  ],
  [
    "Do I have to connect every platform on every account?",
    <>
      Yes. A handle is only a name — posting needs a token for each account on each platform. One
      brand with two accounts and four platforms is eight separate sign-ins.
    </>,
    "connect platform account handle name token brand accounts sign-ins",
  ],
  [
    "What is the difference between the master account and a variation?",
    <>
      The master holds the original slides. A variation gets its own picture for any slide and its
      own rewritten caption, so the same post does not arrive on every account as the same file
      with the same words.
    </>,
    "master account variation original slides picture rewritten caption same file words",
  ],
  [
    "Why did TikTok put my video in drafts instead of posting it?",
    <>
      Either draft mode is on for that account, or TikTok returned{" "}
      <Mono>unaudited_client_can_only_post_to_private_accounts</Mono> — this app is not audited
      yet, so live posts are capped. Either way the video is in your TikTok inbox; open the app
      and publish it.
    </>,
    "tiktok drafts posting draft mode unaudited client private accounts audited capped inbox publish",
  ],
  [
    "Why is every account posting the same caption?",
    <>
      Caption rewriting is off under <b className="font-semibold text-muted-foreground">Clipping
      behaviour</b> in Settings, or the Anthropic key is missing. Rewrites are cached per account
      and platform, so each pair is only ever written once.
    </>,
    "same caption rewriting clipping behaviour settings anthropic key cached account platform",
  ],
  [
    "Can I change the size of the text on the slides?",
    <>
      Settings → <b className="font-semibold text-muted-foreground">Text on the slides</b>. A
      number scales its role everywhere it appears, so raising Title also moves the smaller title
      on a call-to-action slide. A post that is already built keeps its slides until you build it
      again.
    </>,
    "size text slides settings hook title body scales role call to action rebuild",
  ],
  [
    "Why does TikTok get pictures when everything else gets a video?",
    <>
      TikTok takes the slides as a photo set. The 9:16 video render is for YouTube, Instagram and
      Facebook only, so nothing under <b className="font-semibold text-muted-foreground">Video</b>{" "}
      in Settings reaches TikTok at all.
    </>,
    "tiktok pictures photo set video 9:16 render youtube instagram facebook settings",
  ],
  [
    "What does Build actually do?",
    <>
      It renders a 3:4 slide per account with the text burned in, converts each to 9:16, then
      builds one video per platform with that platform&rsquo;s length cap applied. Until it runs there
      are no files on disk and Preview has nothing to show.
    </>,
    "build renders 3:4 slide account text burned 9:16 video platform length cap files disk preview",
  ],
  [
    "I deleted a post by mistake — can I get it back?",
    <>
      No. Deleting a post removes its slides, its variations and its outputs in the same breath,
      and none of it is recoverable. Duplicate a post before you experiment on it.
    </>,
    "deleted post mistake back removes slides variations outputs recoverable duplicate",
  ],
];

/** There is no billing in this app — no plan column on `users`, no Stripe,
 *  nothing metered. These are the shapes the tiers would take, drawn in the
 *  app's own units so the limits mean something. The prices are placeholders
 *  and the card says so. */
const PLANS: { name: string; price: string; featured: boolean; who: string; lines: string[] }[] = [
  {
    name: "Starter",
    price: "£29",
    featured: false,
    who: "One operator, one brand",
    lines: ["1 brand", "2 accounts", "Slides, captions and scheduling", "Post discovery"],
  },
  {
    name: "Studio",
    price: "£79",
    featured: true,
    who: "Where most people land",
    lines: [
      "5 brands",
      "Unlimited accounts",
      "Everything in Starter",
      "Clipping and audio-to-video",
      "Make images with AI",
    ],
  },
  {
    name: "Agency",
    price: "£199",
    featured: false,
    who: "Several operators, many brands",
    lines: [
      "Unlimited brands",
      "Unlimited accounts",
      "Everything in Studio",
      "Several sign-ins per workspace",
      "Priority dispatch",
    ],
  },
];

const PLATFORMS = ["tiktok", "youtube", "instagram", "facebook"] as const;
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
/** Spelled under eleven, a numeral above — mixing the two in one sentence
 *  ("two accounts carry 8 handles") reads as a typo. */
const spell = (n: number) => WORDS[n] ?? String(n);

function Mono({ children }: { children: React.ReactNode }) {
  return <b className="font-mono text-[11px] font-semibold text-muted-foreground">{children}</b>;
}

/* ------------------------------------------------------------------ */
/* rows                                                                */
/* ------------------------------------------------------------------ */

type Tone = "stop" | "pause" | "done";
type Check = { tone: Tone; head: string; detail: string; where?: { label: string; href: string } };

function CheckRow({ tone, head, detail, where }: Check) {
  return (
    <div
      className={`flex items-start gap-2.5 rounded-[12px] border bg-card px-3 py-[11px] ${
        tone === "stop" ? "border-bad/30" : "border-border"
      }`}
    >
      <span
        className={`mt-px grid h-[26px] w-[26px] flex-none place-items-center rounded-full ${
          tone === "done"
            ? "bg-good/15 text-good"
            : tone === "stop"
              ? "bg-bad/[0.13] text-bad"
              : "bg-[rgba(235,104,52,0.13)] text-[#B25E09] dark:text-[#F2A25C]"
        }`}
      >
        {tone === "done" ? (
          <Check className="h-[13px] w-[13px]" strokeWidth={3} />
        ) : (
          <Info className="h-[13px] w-[13px]" strokeWidth={2.2} />
        )}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-foreground">{head}</span>
        <span className="text-[11px] leading-[1.5] text-subtle">{detail}</span>
      </span>
      {where && (
        <Chip href={where.href} className="mt-px flex-none self-center !px-[11px] !py-1.5 !text-[11.5px]">
          {where.label}
          <ArrowRight className="h-3 w-3 flex-none text-subtle" />
        </Chip>
      )}
    </div>
  );
}

function StepRow({ n, name, detail, where }: { n: number; name: string; detail: string; where: string }) {
  return (
    <div className="flex items-start gap-3 border-b border-line-2 px-1 py-[11px] last:border-b-0">
      <span className="mt-px grid h-[22px] w-[22px] flex-none place-items-center rounded-full border border-border bg-secondary text-[11px] font-extrabold text-muted-foreground">
        {n}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="text-[13px] font-semibold leading-normal text-foreground">{name}</span>
        <span className="text-[11px] leading-[1.5] text-subtle">{detail}</span>
      </span>
      <span className="flex-none self-center whitespace-nowrap rounded-lg bg-secondary px-[9px] py-1 text-[11px] font-semibold text-subtle">
        {where}
      </span>
    </div>
  );
}

function FaqItem({ q, a, open, onToggle }: { q: string; a: React.ReactNode; open: boolean; onToggle: () => void }) {
  return (
    <div className="border-b border-line-2 last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-0.5 py-[13px] text-left text-[13px] font-semibold text-foreground"
      >
        <span className="min-w-0 flex-1">{q}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 flex-none text-subtle transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="max-w-[86ch] px-0.5 pb-[15px] text-xs leading-[1.65] text-subtle">{a}</div>
      )}
    </div>
  );
}

function PlanCard({ name, price, featured, who, lines }: (typeof PLANS)[number]) {
  return (
    <div
      className={`flex flex-col rounded-[15px] border bg-card p-4 ${
        featured ? "border-subtle shadow-[inset_0_0_0_1px_var(--subtle)]" : "border-border"
      }`}
    >
      <div className="mb-[9px] flex items-center gap-2">
        <span className="flex-1 text-[13.5px] font-bold">{name}</span>
        {featured && <Tag tone="done">Likely fit</Tag>}
      </div>
      <div className="text-[26px] font-extrabold leading-[1.1] tracking-[-0.03em]">
        {price}
        <em className="ml-[3px] text-[11.5px] font-semibold not-italic text-subtle">/month</em>
      </div>
      <div className="mt-1 text-[11px] text-subtle">{who}</div>
      <ul className="mt-[13px] flex flex-col gap-[7px]">
        {lines.map((l) => (
          <li key={l} className="flex items-start gap-2 text-[11.5px] leading-[1.45] text-muted-foreground">
            <Check className="mt-0.5 h-3 w-3 flex-none text-good" strokeWidth={3} />
            {l}
          </li>
        ))}
      </ul>
      <a
        href="mailto:support@icreateflow.com?subject=Plans"
        className="mt-[15px] inline-flex items-center justify-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 text-[12.5px] font-semibold text-foreground shadow-card transition-colors hover:bg-secondary"
      >
        Tell us this one fits
      </a>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* page                                                                */
/* ------------------------------------------------------------------ */

type Account = Record<string, unknown> & { name: string };
type Brand = { id: number; name: string; accounts?: Account[] };

export default function HelpPage() {
  const [settings, setSettings] = useState<Record<string, string> | null>(null);
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [posts, setPosts] = useState<{ total: number; drafts: number; scheduled: number } | null>(null);
  const [built, setBuilt] = useState<boolean | null>(null);
  const [q, setQ] = useState("");
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  const load = useCallback(() => {
    getSettings().then(setSettings).catch(() => setSettings({}));
    getBrands().then(setBrands).catch(() => setBrands([]));
    getPosts()
      .then(async (rows: { id: number; status: string }[]) => {
        setPosts({
          total: rows.length,
          drafts: rows.filter((p) => p.status === "draft").length,
          scheduled: rows.filter((p) => p.status === "scheduled").length,
        });
        // "Has anything been built" needs the per-output file check, which
        // only the detail endpoint does. Capped at the ten newest so this
        // stays one screenful of requests on a big workspace.
        const probe = rows.slice(0, 10);
        const details = await Promise.all(
          probe.map((p) => getPost(p.id).catch(() => null)),
        );
        setBuilt(
          details.some((d) =>
            ((d?.outputs ?? []) as { files_on_disk?: boolean }[]).some((o) => o.files_on_disk),
          ),
        );
      })
      .catch(() => {
        setPosts(null);
        setBuilt(null);
      });
  }, []);

  useEffect(load, [load]);

  const accounts = useMemo(() => (brands ?? []).flatMap((b) => b.accounts ?? []), [brands]);
  const handles = useMemo(
    () => accounts.reduce((n, a) => n + PLATFORMS.filter((p) => a[`${p}_handle`]).length, 0),
    [accounts],
  );
  const tokens = useMemo(
    () => accounts.reduce((n, a) => n + PLATFORMS.filter((p) => a[`${p}_token`]).length, 0),
    [accounts],
  );

  const has = useCallback((k: string) => !!(settings?.[k] ?? "").trim(), [settings]);
  const loading = settings === null || brands === null;

  const checks: Check[] = useMemo(() => {
    if (loading) return [];
    const out: Check[] = [];
    if (handles > 0 && tokens === 0) {
      out.push({
        tone: "stop",
        head: "No account is signed in to anything",
        detail: `${spell(accounts.length)} account${accounts.length === 1 ? "" : "s"} carr${accounts.length === 1 ? "ies" : "y"} ${spell(handles)} platform handle${handles === 1 ? "" : "s"} between them and not one has a token. Nothing can post live, and Post Now will refuse every row.`,
        where: { label: "Brands", href: "/brands" },
      });
    } else if (handles > 0 && tokens < handles) {
      out.push({
        tone: "pause",
        head: `${handles - tokens} of ${handles} platform handles are not signed in`,
        detail: "Those rows will be skipped when a post goes out. The rest will send.",
        where: { label: "Brands", href: "/brands" },
      });
    }
    if (!has("openai_api_key")) {
      out.push({
        tone: "stop",
        head: "No OpenAI key",
        detail:
          "“Make it with AI” refuses on the Variations step. Accounts can still keep the original image or take an upload.",
        where: { label: "Settings", href: "/settings" },
      });
    }
    if (built === false) {
      out.push({
        tone: "pause",
        head: "Nothing has been built yet",
        detail:
          "There are no rendered slides on disk, so Preview and the slide-text editor have nothing to open. Building a post fills this in.",
        where: { label: "Posts", href: "/posts" },
      });
    }
    if (has("anthropic_api_key")) {
      out.push({
        tone: "done",
        head: "Slides can be read and captions rewritten",
        detail: has("google_vision_api_key")
          ? "The Anthropic key is set, with Google Vision behind it as the fallback reader."
          : "The Anthropic key is set. There is no fallback reader behind it.",
      });
    } else {
      out.push({
        tone: "stop",
        head: "No Anthropic key",
        detail:
          "Slides import with no text on them, and every account's caption goes out identical.",
        where: { label: "Settings", href: "/settings" },
      });
    }
    return out;
  }, [loading, handles, tokens, accounts.length, built, has]);

  const blocking = checks.filter((c) => c.tone === "stop").length;

  /* -------- search, over the page itself -------- */
  const needle = q.trim().toLowerCase();
  const hit = useCallback(
    (...parts: (string | undefined)[]) =>
      !needle || parts.filter(Boolean).join(" ").toLowerCase().includes(needle),
    [needle],
  );

  const fChecks = checks.filter((c) => hit(c.head, c.detail));
  const fSteps = STEPS.filter(([n, d, w]) => hit(n, d, w));
  const fFaq = FAQ.map((f, i) => [f, i] as const).filter(([[qq, , idx]]) => hit(qq, idx));
  const fRef = REFUSALS.filter(([a, b]) => hit(a, b));
  const fQuiet = QUIET.filter(([a, b]) => hit(a, b));
  const fPlans = PLANS.filter((p) =>
    hit(p.name, p.price, p.who, p.lines.join(" "), "plan pricing subscription billing"),
  );
  const matches =
    fChecks.length + fSteps.length + fFaq.length + fRef.length + fQuiet.length + fPlans.length;

  const facts: [string, string][] = [
    ["Brands", brands ? String(brands.length) : "—"],
    ["Accounts", brands ? String(accounts.length) : "—"],
    ["Platform sign-ins", brands ? `${tokens} of ${handles}` : "—"],
    [
      "Posts",
      posts
        ? `${posts.total}${posts.total ? ` — ${posts.scheduled} scheduled, ${posts.drafts} draft` : ""}`
        : "—",
    ],
    ["Rendered output", built === null ? "—" : built ? "on disk" : "none on disk"],
  ];

  return (
    <>
      <PageHead>
        <PageTitle
          title="Help & Support"
          sub="What is stopping you today, what the app means when it refuses, and how to reach someone."
        />
        <PageActions>
          <Chip href="/terms" icon={FileText}>
            Terms
          </Chip>
          <Chip href="/privacy" icon={Shield}>
            Privacy
          </Chip>
        </PageActions>
      </PageHead>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_372px]">
        <div className="flex min-w-0 flex-col gap-4 [&>*:last-child]:xl:flex-1">
          {(!needle || fChecks.length > 0) && (
            <Card className="flex flex-col">
              <CardHead
                title="What is stopping you right now"
                sub="Read from this workspace, not a checklist — every one of these fails without saying so"
                right={<DotsMenu items={[{ label: "Check again", icon: RefreshCw, onClick: load }]} />}
              />
              {/* The card fills its column so the two columns end level. The
                  rows stay at their own spacing — spreading them to reach the
                  bottom put sixty pixels between each one and made five
                  related checks read as five unrelated cards. */}
              <CardBody className="flex flex-1 flex-col">
                {loading ? (
                  <div className="flex flex-col gap-2">
                    <Skeleton className="h-[58px]" />
                    <Skeleton className="h-[58px]" />
                    <Skeleton className="h-[58px]" />
                  </div>
                ) : (
                  <div className="flex flex-1 flex-col">
                    {!needle && (
                      <FigureLine value={String(blocking)}>
                        of <FigureStrong>{checks.length}</FigureStrong> checks{" "}
                        {blocking === 0
                          ? "are blocking · nothing is in the way"
                          : `are blocking · nothing can go out until ${blocking === 1 ? "it is" : "they are"} fixed`}
                      </FigureLine>
                    )}
                    <div className="flex flex-col gap-2">
                      {fChecks.map((c) => (
                        <CheckRow key={c.head} {...c} />
                      ))}
                    </div>
                  </div>
                )}
              </CardBody>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4 [&>*:last-child]:xl:flex-1">
          <Card>
            <CardBody className="p-3.5 pt-3.5">
              <div className="relative flex items-center">
                <Search className="pointer-events-none absolute left-3 h-3.5 w-3.5 text-subtle" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => e.key === "Escape" && setQ("")}
                  placeholder="Search this page — try “drafts” or “caption”"
                  autoComplete="off"
                  spellCheck={false}
                  className="w-full rounded-[12px] border border-border bg-secondary px-[34px] py-2.5 text-[12.5px] text-foreground outline-none transition-colors placeholder:text-subtle focus:border-subtle focus:bg-card"
                />
                {q && (
                  <button
                    type="button"
                    aria-label="Clear"
                    onClick={() => setQ("")}
                    className="absolute right-2 grid h-5 w-5 place-items-center rounded-full text-subtle transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-[11px] w-[11px]" strokeWidth={2.4} />
                  </button>
                )}
              </div>
              {needle && (
                <div className="mt-2 text-[11px] text-subtle">
                  {matches
                    ? `${matches} match${matches === 1 ? "" : "es"} on this page`
                    : "Nothing here matches that."}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHead title="Get in touch" sub="A person reads these" />
            <CardBody className="flex flex-col gap-2 pt-2.5">
              {[
                ["support@icreateflow.com", "Anything that is not working", Send],
                ["security@icreateflow.com", "A vulnerability, or an account you did not open", Shield],
              ].map(([addr, why, Icon]) => {
                const I = Icon as React.ComponentType<{ className?: string }>;
                return (
                  <a
                    key={addr as string}
                    href={`mailto:${addr}`}
                    className="flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-3 py-2.5 transition-colors hover:bg-secondary"
                  >
                    <span className="grid h-[29px] w-[29px] flex-none place-items-center rounded-[9px] border border-border bg-secondary text-muted-foreground">
                      <I className="h-3.5 w-3.5" />
                    </span>
                    <span className="flex min-w-0 flex-col gap-px">
                      <span className="truncate font-mono text-[12.5px] font-semibold text-foreground">
                        {addr as string}
                      </span>
                      <span className="truncate text-[11px] text-subtle">{why as string}</span>
                    </span>
                    <ArrowRight className="ml-auto h-3.5 w-3.5 flex-none text-subtle" />
                  </a>
                );
              })}
              <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
                <Info className="mt-0.5 h-3 w-3 flex-none" />
                <span>
                  Include the post number, which account it was for, and the exact line the app
                  showed you. Those three make it a five-minute answer instead of a five-day one.
                </span>
              </div>
            </CardBody>
          </Card>

          <Card className="flex flex-col">
            <CardHead title="This workspace" sub="Worth pasting into the first message" />
            <CardBody className="flex flex-1 flex-col pt-2.5">
              <div className="flex flex-1 flex-col justify-between">
                {facts.map(([k, v]) => (
                  <div key={k} className="flex items-baseline gap-3 border-b border-line-2 px-0.5 py-2 last:border-b-0">
                    <span className="flex-1 text-xs text-subtle">{k}</span>
                    <span className="flex-none text-right text-xs font-semibold text-foreground">{v}</span>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        </div>
      </div>

      {(!needle || fSteps.length > 0) && (
        <Card>
          <CardHead
            title="How a post gets out"
            sub="Seven steps, in the order they run. A post stops at the first one that is not done, and mostly stops quietly"
            right={<DotsMenu items={[{ label: "Open Posts", icon: ExternalLink, href: "/posts" }]} />}
          />
          <CardBody className="pt-3">
            <div className="flex flex-col gap-0.5">
              {fSteps.map(([name, detail, where]) => (
                <StepRow key={name} n={STEPS.findIndex((s) => s[0] === name) + 1} name={name} detail={detail} where={where} />
              ))}
            </div>
            {!needle && (
              <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
                <Info className="mt-0.5 h-3 w-3 flex-none" />
                <span>
                  Steps 1, 2 and 7 are set once and then forgotten. The checks above say where this
                  workspace has stopped.
                </span>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {(!needle || fFaq.length > 0) && (
        <Card>
          <CardHead
            title="Common questions"
            sub="The nine that come up, answered from what the code actually does"
          />
          <CardBody className="pt-2">
            <div className="flex flex-col">
              {fFaq.map(([[question, answer], i]) => (
                <FaqItem
                  key={question}
                  q={question}
                  a={answer}
                  // A hit you have to click to read is not a hit.
                  open={needle ? true : openFaq === i}
                  onToggle={() => setOpenFaq((cur) => (cur === i ? null : i))}
                />
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_372px]">
        <div className="flex min-w-0 flex-col gap-4 [&>*:last-child]:xl:flex-1">
          {(!needle || fRef.length > 0) && (
            <Card>
              <CardHead title="When a post refuses" sub="The line the app shows you, and what to do about it" />
              <CardBody className="pt-3">
                <div className="flex flex-col">
                  <div className="grid grid-cols-1 gap-3.5 px-0.5 pb-2 text-[10.5px] font-bold uppercase tracking-[0.09em] text-subtle sm:grid-cols-[1fr_1.15fr]">
                    <span>What it says</span>
                    <span className="hidden sm:block">What it means</span>
                  </div>
                  {fRef.map(([said, means]) => (
                    <div
                      key={said}
                      className="grid grid-cols-1 items-start gap-1 border-t border-line-2 px-0.5 py-[11px] sm:grid-cols-[1fr_1.15fr] sm:gap-3.5"
                    >
                      <span className="text-xs font-semibold leading-[1.45] text-foreground">{said}</span>
                      <span className="text-[11.5px] leading-[1.5] text-subtle">{means}</span>
                    </div>
                  ))}
                </div>
                {!needle && (
                  <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
                    <Info className="mt-0.5 h-3 w-3 flex-none" />
                    <span>
                      Anything not on this list is shown as the platform worded it, trimmed to its
                      first line.
                    </span>
                  </div>
                )}
              </CardBody>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4 [&>*:last-child]:xl:flex-1">
          {(!needle || fQuiet.length > 0) && (
            <Card>
              <CardHead title="When it says nothing at all" sub="No error, no log — the hard ones" />
              <CardBody className="flex flex-col gap-2 pt-3">
                {fQuiet.map(([what, why]) => (
                  <div key={what} className="rounded-[12px] border border-border bg-card px-3 py-[11px]">
                    <div className="text-[13px] font-semibold leading-normal text-foreground">{what}</div>
                    <div className="mt-px text-[11px] leading-[1.5] text-subtle">{why}</div>
                  </div>
                ))}
                {!needle && (
                  <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
                    <Info className="mt-0.5 h-3 w-3 flex-none" />
                    <span>
                      Silence is the app&rsquo;s worst habit. If something has not happened and
                      nothing says why, it is almost always one of these four.
                    </span>
                  </div>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      {(!needle || fPlans.length > 0) && (
        <Card>
          <CardHead
            title={
              <span className="flex items-center gap-2">
                Plans <Tag tone="draft">Not live yet</Tag>
              </span>
            }
            sub="What the tiers will look like. Nothing here charges anything today"
          />
          <CardBody className="pt-3.5">
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
              {fPlans.map((p) => (
                <PlanCard key={p.name} {...p} />
              ))}
            </div>
            {!needle && (
              <div className="mt-3.5 flex items-start gap-2 rounded-[12px] border border-[rgba(235,104,52,0.3)] bg-[rgba(235,104,52,0.09)] px-3 py-2.5 text-[11px] leading-[1.5] text-[#B25E09] dark:text-[#F2A25C]">
                <Info className="mt-px h-[13px] w-[13px] flex-none" />
                <span>
                  There is no billing in the app yet — no plan on your account, nothing metered, and
                  no card is ever asked for. Every feature is on for everyone, including the three
                  above that are drawn as paid. The prices are placeholders.
                </span>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {needle && matches === 0 && (
        <Card>
          <CardBody className="text-xs text-subtle">
            Nothing here matches that. Try the search again, or mail support and paste what you
            typed.
          </CardBody>
        </Card>
      )}

      <Note>The checks at the top are read from your database each time this page opens.</Note>

    </>
  );
}
