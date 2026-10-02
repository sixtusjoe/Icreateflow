"use client";

/**
 * The chat button on the public pages.
 *
 * There is no live chat behind it — the in-app Assistant is admin-only and
 * has no model or message store yet — so this panel does only what is
 * real: it answers the common questions straight from the FAQ, and a typed
 * question opens the visitor's email app addressed to support, with the
 * message already in it. It never shows a "sent" it did not do.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FAQ, SUPPORT_EMAIL } from "./faq";
import { Icon } from "./Sprite";

type Msg = { from: "bot" | "me"; text: string };

const HELLO: Msg = {
  from: "bot",
  text: "Hi 👋 Ask anything about promoting your catalog. These are the questions people ask most:",
};

export default function HelpChat() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([HELLO]);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const [asked, setAsked] = useState<string[]>([]);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [msgs, typing]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const reply = (text: string) => {
    setTyping(true);
    setTimeout(() => { setTyping(false); setMsgs((m) => [...m, { from: "bot", text }]); }, 650);
  };

  const ask = (q: string, a: string) => {
    setAsked((s) => [...s, q]);
    setMsgs((m) => [...m, { from: "me", text: q }]);
    reply(a);
  };

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setMsgs((m) => [...m, { from: "me", text }]);
    setDraft("");
    const subject = encodeURIComponent("A question from icreateflow.com");
    window.location.href = `mailto:${SUPPORT_EMAIL}?subject=${subject}&body=${encodeURIComponent(text)}`;
    reply(`Your email app should have opened with that message to ${SUPPORT_EMAIL}. Send it from there and the team will reply by email.`);
  };

  const left = FAQ.filter(([q]) => !asked.includes(q));

  return (
    <div className="chatw">
      {open && (
        <div className="chatp" role="dialog" aria-label="Questions">
          <div className="chath">
            <span className="tile"><Icon id="mark" size={22} /></span>
            <div>
              <b>Icreateflow</b>
              <small><span className="live" />Instant answers · the team replies by email</small>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </div>

          <div className="chatl" ref={list}>
            {msgs.map((m, i) => <div key={i} className={`cm ${m.from}`}>{m.text}</div>)}
            {typing && <div className="cm bot typing" aria-label="Typing"><i /><i /><i /></div>}
            {!typing && left.length > 0 && (
              <div className="chips">
                {left.map(([q, a]) => <button key={q} type="button" onClick={() => ask(q, a)}>{q}</button>)}
              </div>
            )}
          </div>

          <form className="chatf" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <textarea ref={input} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask anything…"
              aria-label="Your question"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button type="submit" aria-label="Send by email" disabled={!draft.trim()}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
            </button>
          </form>
          <div className="chatx">
            Questions you type go to <b>{SUPPORT_EMAIL}</b> · <Link href="/login">Log in for help</Link>
          </div>
        </div>
      )}

      <button type="button" className={`chatb ${open ? "on" : ""}`} onClick={() => { setOpen((o) => !o); setTimeout(() => input.current?.focus(), 50); }}
        aria-label={open ? "Close questions" : "Questions? Ask us"} aria-expanded={open}>
        {open ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z" /><path d="M8.5 11h.01M12 11h.01M15.5 11h.01" strokeWidth="2.6" strokeLinecap="round" /></svg>
        )}
        {!open && <span className="dot" />}
      </button>
    </div>
  );
}
