"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle, Bot, Check, LayoutGrid, MessageSquare, RefreshCw, Search, Send, Users,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import {
  Card, Chip, DotsMenu, PageHead, PageTitle, PageActions, Tabs, Tag, Note, Empty,
} from "@/components/kit";
import { Initial, SampleBanner } from "@/components/admin/ui";

/**
 * Admin — Assistant inbox.
 *
 * The assistant answers first; a person can always answer after it. That
 * one rule decides most of this page:
 *
 *  - every thread opens with the question and the assistant's reply, so
 *    the default state of the inbox is "already answered"
 *  - a thread reaches a human when the assistant could not answer, when
 *    the person asked again after it tried, or when an admin types
 *  - the moment an admin replies, the assistant stops answering that
 *    thread. Two voices taking turns unannounced is how a support inbox
 *    loses track of what was promised to whom.
 *  - the badge counts what is waiting on a person, never the total
 *
 * **Nothing behind this exists.** The Ask panel has no model, no
 * transcript and no storage: a question typed into it today goes nowhere.
 * So the threads are sample, the page says so on its face, replies land in
 * this tab and nowhere else, and the note at the foot lists what has to be
 * built first. The page is here because the shape of the thing is the
 * decision — whether the assistant speaks first, what happens when it
 * cannot answer, who owns a thread once a person touches it.
 */

type Side = "them" | "ai" | "me" | "flag";
type Msg = { side: Side; text: string; when: string; meta?: string };
type Thread = {
  id: number; who: string; mail: string; state: "needs" | "ai" | "resolved";
  unread: boolean; route: string; when: string; ago: string;
  brands: number; posts: number; since: string; msgs: Msg[];
};

const THREADS: Thread[] = [
  {
    id: 1, who: "Marisa Bell", mail: "marisa@northbound.co", state: "needs", unread: true,
    route: "/schedule", when: "14:22", ago: "9 minutes ago", brands: 2, posts: 41, since: "March 2026",
    msgs: [
      { side: "them", when: "14:22", text: "My Thursday posts are still sitting there saying Scheduled. It's 2pm. Nothing in the log either. Am I doing something wrong?" },
      { side: "ai", when: "14:22", meta: "answered in 1.9s", text: "Almost certainly not you. The dispatcher runs every minute, but it skips silently when the workspace has no public address set: it flips the post to posting, finds nowhere to serve the video from, sets it back to scheduled and writes no log. That matches what you are seeing — right time, no error, no movement. Only an admin can set that address." },
      { side: "them", when: "14:31", text: "So there's nothing I can do on my end? Can someone actually set it? This is the third week." },
    ],
  },
  {
    id: 2, who: "Dee Okonkwo", mail: "dee@fourthfloor.studio", state: "ai", unread: false,
    route: "/posts/new", when: "11:04", ago: "3 hours ago", brands: 1, posts: 8, since: "August 2026",
    msgs: [
      { side: "them", when: "11:04", text: "What's the difference between the master account and a variation? I don't want the same caption going out on all four." },
      { side: "ai", when: "11:04", meta: "answered in 1.4s", text: "The master holds the original slides. A variation gets its own picture for any slide and its own rewritten caption, so the same post does not arrive on every account as the same file with the same words. Caption rewriting needs the Anthropic key, which this workspace has." },
    ],
  },
  {
    id: 3, who: "Tomas Reiner", mail: "t.reiner@pressplay.fm", state: "needs", unread: true,
    route: "/outreach/12", when: "Yesterday", ago: "yesterday, 17:40", brands: 1, posts: 0, since: "September 2026",
    msgs: [
      { side: "them", when: "17:40", text: "Campaign stopped by itself after about forty sends. Account says paused." },
      { side: "flag", when: "17:40", meta: "raised in 2.2s", text: "Could not answer: the account paused itself after five errors in a row, but the error text is not in my context and the campaign may also have run out of queued targets. Two possible causes, no way to tell them apart from here — raised for a person. They were told someone is looking, and nothing else." },
      { side: "me", when: "17:52", text: "That is the account pausing itself, not the campaign failing. Five browser errors in a row and it takes itself out so it does not burn the account. Open Outreach → Accounts and look at the one carrying the error count — if it says ERR_INTERNET_DISCONNECTED, the box lost its connection mid-run and nothing is wrong with the account itself. Clear the count there and press Resume. Does it show that error?" },
    ],
  },
  {
    id: 4, who: "Priya Raman", mail: "priya@halcyonrecords.com", state: "resolved", unread: false,
    route: "/brands", when: "Mon", ago: "Monday, 09:12", brands: 3, posts: 126, since: "January 2026",
    msgs: [
      { side: "them", when: "09:12", text: "Do I have to connect every platform on every account? I have eight accounts." },
      { side: "ai", when: "09:12", meta: "answered in 1.1s", text: "Yes. A handle is only a name — posting needs a token for each account on each platform, so eight accounts across four platforms is thirty-two sign-ins. There is no way around it: the token is what the platform checks." },
      { side: "them", when: "09:31", text: "Fine. At least now I know. Thanks." },
    ],
  },
];

const STATE: Record<Thread["state"], { tone: "stop" | "done" | "draft"; label: string }> = {
  needs: { tone: "stop", label: "Needs you" },
  ai: { tone: "done", label: "Assistant handled" },
  resolved: { tone: "draft", label: "Resolved" },
};

const CANNED = [
  "The public address is unset",
  "Tokens expire after 60 days",
  "TikTok sandbox puts posts in drafts",
  "Accounts pause themselves after five errors",
];

export default function AdminAssistantPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [threads, setThreads] = useState(THREADS);
  const [openId, setOpenId] = useState(1);
  const [filter, setFilter] = useState("needs");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  // Off by default on an open thread: the rule is that a person replying
  // takes the thread off the assistant, and this switch is how you hand it
  // back rather than a setting you have to remember to turn off.
  const [aiReplies, setAiReplies] = useState(false);

  useEffect(() => {
    if (user && user.role !== "admin") router.push("/dashboard");
  }, [user, router]);

  if (!user || user.role !== "admin") return null;

  const counts = {
    needs: threads.filter((t) => t.state === "needs").length,
    ai: threads.filter((t) => t.state === "ai").length,
    resolved: threads.filter((t) => t.state === "resolved").length,
  };

  const listed = threads.filter((t) => {
    if (t.state !== filter) return false;
    const q = query.trim().toLowerCase();
    return !q || t.who.toLowerCase().includes(q) ||
      t.msgs.some((m) => m.text.toLowerCase().includes(q));
  });

  const open = threads.find((t) => t.id === openId) ?? listed[0] ?? threads[0];
  const answeredAlone = counts.ai + counts.resolved;
  const raised = threads.reduce((a, t) => a + t.msgs.filter((m) => m.side === "flag").length, 0);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setThreads((prev) =>
      prev.map((t) =>
        t.id === open.id
          ? {
              ...t,
              unread: false,
              msgs: [...t.msgs, {
                side: "me" as Side, text,
                when: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              }],
            }
          : t
      )
    );
    setDraft("");
    setAiReplies(false);
    toast.message("Nothing was sent.", {
      description: "There is no thread table and no Ask transcript — this reply exists in this tab only.",
    });
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Assistant inbox"
                   sub="The assistant answers first. These are the ones that still want a person." />
        <PageActions>
          <Chip icon={RefreshCw} onClick={() => setThreads(THREADS)}>Reset the sample</Chip>
          <Chip icon={MessageSquare}>Needs you · {counts.needs}</Chip>
        </PageActions>
      </PageHead>

      <SampleBanner>
        <b className="text-foreground">Sample threads.</b> The Ask panel has no model and no storage behind
        it today — a question typed into it goes nowhere and nothing is kept. This is the design for what has
        to exist first; replying below changes this tab and nothing else.
      </SampleBanner>

      <div className="grid items-stretch gap-4 xl:grid-cols-[352px_1fr]">
        {/* ------------------------------------------------------ the list */}
        <Card className="flex flex-col overflow-hidden">
          <div className="p-3.5 pb-0">
            <label className="flex items-center gap-2.5 rounded-[11px] border border-border bg-secondary px-3 py-2">
              <Search className="h-[15px] w-[15px] flex-none text-subtle" />
              <input
                value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Search questions and replies"
                className="w-full border-0 bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-subtle"
              />
            </label>
          </div>
          <div className="border-b border-line-2 px-3 py-3">
            <Tabs
              items={[
                { key: "needs", label: "Needs you", count: counts.needs },
                { key: "ai", label: "Handled", count: counts.ai },
                { key: "resolved", label: "Resolved", count: counts.resolved },
              ]}
              value={filter}
              onChange={setFilter}
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            {listed.length === 0 ? (
              <Empty icon={MessageSquare} title="Nothing in here">
                {query ? "No thread matches that." : "No thread is in that state."}
              </Empty>
            ) : (
              listed.map((t) => {
                const last = t.msgs[t.msgs.length - 1];
                const pre = { me: "You: ", ai: "Assistant: ", them: "", flag: "Raised: " }[last.side];
                const on = t.id === open?.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setOpenId(t.id)}
                    className={`flex w-full items-start gap-2.5 border-b border-line-2 px-3.5 py-3 text-left transition-colors ${
                      on ? "bg-secondary" : "hover:bg-secondary/60"
                    }`}
                  >
                    <Initial name={t.who} size={32} />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <b className={`truncate text-[12.5px] ${t.unread ? "font-extrabold text-foreground" : "font-semibold text-foreground"}`}>
                          {t.who}
                        </b>
                        <i className="flex-none text-[10.5px] not-italic text-subtle">{t.when}</i>
                      </span>
                      <span className="line-clamp-2 text-[11px] leading-[1.45] text-subtle">
                        {pre}{last.text}
                      </span>
                      <span className="flex items-center gap-2">
                        <Tag tone={STATE[t.state].tone}>{STATE[t.state].label}</Tag>
                        <span className="truncate font-mono text-[10px] text-subtle">{t.route}</span>
                      </span>
                    </span>
                  </button>
                );
              })
            )}
          </div>
          <div className="flex items-start gap-2 border-t border-line-2 px-3.5 py-3 text-[11px] leading-[1.5] text-subtle">
            <Bot className="mt-px h-[14px] w-[14px] flex-none" />
            <span>
              The assistant answered <b className="font-bold text-foreground">{answeredAlone} of {threads.length}</b>{" "}
              on its own today, and raised <b className="font-bold text-foreground">{raised}</b> for you.
            </span>
          </div>
        </Card>

        {/* --------------------------------------------------- the thread */}
        <Card className="flex flex-col overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line-2 px-5 py-3.5">
            <Initial name={open.who} />
            <span className="flex min-w-0 flex-col">
              <b className="text-[13.5px] font-bold text-foreground">{open.who}</b>
              <i className="text-[11px] not-italic text-subtle">{open.mail}</i>
            </span>
            <span className="ml-auto flex flex-wrap items-center gap-2">
              <label className="flex cursor-pointer items-center gap-2 rounded-[11px] border border-border bg-card px-3 py-2 text-[11.5px] font-semibold text-muted-foreground">
                <input
                  type="checkbox" checked={aiReplies} onChange={(e) => setAiReplies(e.target.checked)}
                  className="h-[15px] w-[15px] accent-[var(--primary)]"
                />
                Assistant replies here
              </label>
              <Chip icon={Check} onClick={() => {
                setThreads((p) => p.map((t) => (t.id === open.id ? { ...t, state: "resolved", unread: false } : t)));
              }}>
                Mark resolved
              </Chip>
              <DotsMenu items={[
                { label: "See their account", icon: Users, href: "/admin/users" },
                { label: "Where they asked from", icon: LayoutGrid, href: open.route },
              ]} />
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 border-b border-line-2 bg-secondary px-5 py-2.5 text-[11px] text-subtle">
            <LayoutGrid className="h-[13px] w-[13px]" />
            Asked from <b className="font-mono font-semibold text-foreground">{open.route}</b> · {open.ago} ·{" "}
            {open.brands} brands · {open.posts} posts · with you since {open.since}
          </div>

          <div className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-5 py-4">
            {open.msgs.map((m, k) => <Bubble key={k} msg={m} />)}
          </div>

          <div className="border-t border-line-2 px-5 py-3.5">
            {!aiReplies && open.msgs.some((m) => m.side === "ai") && (
              <div className="mb-2.5 flex items-start gap-2 rounded-[11px] border border-border bg-secondary px-3 py-2.5 text-[11px] leading-[1.5] text-subtle">
                <Bot className="mt-px h-[14px] w-[14px] flex-none" />
                <span>
                  The assistant has answered once and this person came back.{" "}
                  <b className="font-bold text-foreground">Replying takes the thread off it</b> — it will not
                  answer here again unless you switch it back on above.
                </span>
              </div>
            )}
            <div className="mb-2 flex flex-wrap gap-1.5">
              {CANNED.map((c) => (
                <button
                  key={c} type="button" onClick={() => setDraft((d) => (d ? `${d} ${c}` : c))}
                  className="rounded-full border border-border bg-secondary px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
                >
                  {c}
                </button>
              ))}
            </div>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              placeholder="Write a reply. It would arrive in their Ask panel, under your name."
              className="w-full resize-y rounded-[12px] border border-border bg-card px-3.5 py-2.5 text-[12.5px] leading-[1.6] text-foreground outline-none transition-colors placeholder:text-subtle focus:border-subtle"
            />
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-subtle">
                Nothing is sent. There is nowhere for it to go yet.
              </span>
              <span className="ml-auto flex gap-2">
                <Chip disabled>Save as canned reply</Chip>
                <button
                  type="button" onClick={send} disabled={!draft.trim()}
                  className="inline-flex flex-none items-center gap-[7px] rounded-[11px] bg-primary px-4 py-[9px] text-[12.5px] font-bold text-primary-foreground transition-opacity disabled:cursor-default disabled:opacity-45"
                >
                  <Send className="h-3.5 w-3.5" />Send reply
                </button>
              </span>
            </div>
          </div>
        </Card>
      </div>

      <Note>
        <b className="text-foreground">When the assistant cannot answer it does not say so to the person.</b>{" "}
        It tells them someone is looking, marks the thread <i>Needs you</i>, and writes its reasoning into the
        thread where only an admin can read it — two possible causes and no way to choose between them is
        useful to you and useless to them.
        <br /><br />
        What has to exist before any of this is real: a <b className="text-foreground">thread</b> and{" "}
        <b className="text-foreground">message</b> table carrying who wrote each line — person, assistant or
        admin — the route the question came from, and the three states above; a model behind the Ask panel
        with the workspace&apos;s own state in its context, since every answer here is about this workspace and
        not the product in general; a rule that stops the assistant the moment an admin replies; and the Ask
        panel itself becoming a transcript rather than a suggestion box, so a reply has somewhere to arrive.
      </Note>
    </>
  );
}

function Bubble({ msg }: { msg: Msg }) {
  if (msg.side === "flag") {
    // Not a message. The assistant could not answer, so it called an admin
    // rather than telling the person it had failed — the person gets
    // "someone is looking at this", and the reasoning lands here.
    return (
      <div className="rounded-[14px] border border-dashed border-warn/40 bg-warn/[0.06] px-3.5 py-3">
        <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] font-bold text-warn">
          <AlertTriangle className="h-[15px] w-[15px]" />
          Raised for you
          {msg.meta && <em className="font-normal not-italic text-subtle">{msg.meta}</em>}
          <span className="rounded-full border border-warn/30 bg-warn/12 px-2 py-px text-[9.5px] font-bold uppercase tracking-[0.05em]">
            only you can see this
          </span>
        </div>
        <p className="text-[12.5px] leading-[1.6] text-muted-foreground">{msg.text}</p>
        <div className="mt-1.5 text-[10.5px] text-subtle">{msg.when}</div>
      </div>
    );
  }
  if (msg.side === "ai") {
    return (
      <div className="rounded-[14px] border border-border bg-secondary px-3.5 py-3">
        <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] font-bold text-foreground">
          <Bot className="h-[15px] w-[15px] text-subtle" />
          Assistant
          {msg.meta && <em className="font-normal not-italic text-subtle">{msg.meta}</em>}
          <span className="ml-auto flex gap-1.5">
            <Chip disabled className="px-2.5 py-1 text-[11px]">Answer again</Chip>
            <Chip disabled className="px-2.5 py-1 text-[11px]">Take over</Chip>
          </span>
        </div>
        <p className="text-[12.5px] leading-[1.6] text-muted-foreground">{msg.text}</p>
        <div className="mt-1.5 text-[10.5px] text-subtle">{msg.when}</div>
      </div>
    );
  }
  if (msg.side === "me") {
    return (
      <div className="ml-auto max-w-[86%] rounded-[14px] border border-lime/40 bg-lime/[0.12] px-3.5 py-3">
        <div className="mb-1.5 flex items-center gap-2 text-[11px] font-bold text-foreground">
          You<em className="font-normal not-italic text-subtle">took the thread over</em>
        </div>
        <p className="text-[12.5px] leading-[1.6] text-muted-foreground">{msg.text}</p>
        <div className="mt-1.5 text-[10.5px] text-subtle">{msg.when}</div>
      </div>
    );
  }
  return (
    <div className="max-w-[86%] rounded-[14px] border border-border bg-card px-3.5 py-3 shadow-card">
      <p className="text-[12.5px] leading-[1.6] text-foreground">{msg.text}</p>
      <div className="mt-1.5 text-[10.5px] text-subtle">{msg.when}</div>
    </div>
  );
}
