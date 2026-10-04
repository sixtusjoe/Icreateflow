"use client";

/**
 * The public pages' header. Below 860px the links and buttons fold into a
 * menu: the button opens a panel under the bar, and it closes on a link,
 * on Escape, and when the window is widened past the breakpoint (otherwise
 * it would sit open behind a bar that no longer shows its button).
 *
 * Nav items are plain links to the home page's sections. The preview drew
 * a chevron beside two of them; there are no menus behind them, and a
 * chevron promises one, so they are left off.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Icon } from "./Sprite";
import ThemeSwitch from "./ThemeSwitch";

const LINKS = [
  { href: "/#platform", label: "Platform" },
  { href: "/#who", label: "Who it's for" },
  { href: "/#how", label: "How it works" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#faq", label: "FAQ" },
];

export default function Nav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const wide = window.matchMedia("(min-width:861px)");
    const onWide = (e: MediaQueryListEvent) => { if (e.matches) setOpen(false); };
    window.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => { window.removeEventListener("keydown", onKey); wide.removeEventListener("change", onWide); };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <header className={`nav ${open ? "open" : ""}`}>
      <div className="wrap">
        <Link className="logo" href="/" aria-label="Icreateflow home">
          <span className="tile"><Icon id="mark" size={24} /></span><b>Icreateflow</b>
        </Link>
        <ul>
          {LINKS.map((l) => <li key={l.href}><Link href={l.href}>{l.label}</Link></li>)}
        </ul>
        <div className="right">
          <ThemeSwitch />
          <Link className="btn btn-ghost" href="/login">Log in</Link>
          <Link className="btn btn-ink" href="/register">
            <span className="long">Launch a campaign</span><span className="short">Start</span>
          </Link>
          <button type="button" className="menu-btn" aria-label="Menu" aria-expanded={open} aria-controls="mpanel"
            onClick={() => setOpen((o) => !o)}>
            <svg className="bars" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
            <svg className="x" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
      </div>
      <div className="mpanel" id="mpanel">
        <div className="wrap">
          {LINKS.map((l) => (
            <Link key={l.href} className="l" href={l.href} onClick={close}>{l.label} <Icon id="arr" size={16} /></Link>
          ))}
          <div className="acts">
            <Link className="btn btn-ghost" href="/login" onClick={close}>Log in</Link>
            <Link className="btn btn-ink" href="/register" onClick={close}>Launch a campaign</Link>
          </div>
        </div>
      </div>
    </header>
  );
}
