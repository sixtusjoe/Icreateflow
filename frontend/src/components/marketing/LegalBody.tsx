"use client";

/**
 * The legal pages' hero, glass cards and section index, around the text
 * the page passes in.
 *
 * The reading time and the index are read from the rendered article (its
 * words, and its [data-legal-section] headings) in a ref callback, so they
 * can never disagree with what the page actually says. The active entry in
 * the index follows the section nearest the top of the screen.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type Entry = { id: string; label: string };

export default function LegalBody({
  title, lead, soft, subtitle, lastUpdated, other, children,
}: {
  title: string; lead: string; soft: string; subtitle?: string; lastUpdated: string;
  other: { href: string; label: string }; children: React.ReactNode;
}) {
  const [minutes, setMinutes] = useState<number | null>(null);
  const [toc, setToc] = useState<Entry[]>([]);
  const [active, setActive] = useState("");

  const measure = useCallback((el: HTMLElement | null) => {
    if (!el) return;
    const words = (el.innerText || "").split(/\s+/).filter(Boolean).length;
    setMinutes(Math.max(1, Math.round(words / 230)));
    setToc(Array.from(el.querySelectorAll<HTMLElement>("[data-legal-section]")).map((s) => ({
      id: s.id, label: s.querySelector("h2")?.textContent ?? s.id,
    })));
  }, []);

  useEffect(() => {
    if (!toc.length) return;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
    }, { rootMargin: "-30% 0px -60% 0px" });
    toc.forEach((t) => { const el = document.getElementById(t.id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, [toc]);

  return (
    <main>
      <section className="hero legal-hero">
        <div className="shapes"><i /><i /><i /><i /></div>
        <div className="wrap">
          <div>
            <span className="chip"><em>LEGAL</em>{title}</span>
            <h1>{lead} {soft && <span>{soft}</span>}</h1>
            {subtitle && <p className="sub">{subtitle}</p>}
          </div>
          <div className="legal-stack" aria-hidden="true">
            <div className="g lA">
              <div className="k"><span className="live" />Last updated</div>
              <b style={{ display: "block", fontSize: 26, fontWeight: 600, letterSpacing: "-.03em", marginTop: 8 }}>{lastUpdated}</b>
              <div style={{ fontSize: 12, color: "var(--glass-muted)", marginTop: 4 }}>The version you are reading</div>
            </div>
            <div className="g lB">
              <div className="k">Reading time</div>
              <b style={{ display: "block", fontSize: 34, fontWeight: 600, letterSpacing: "-.04em", marginTop: 6 }}>
                {minutes == null ? "—" : `${minutes} min`}
              </b>
              <div className="bar"><i style={{ width: minutes == null ? 0 : "100%" }} /></div>
            </div>
            <div className="g lC">
              <div className="k">Also read</div>
              <div style={{ display: "grid", gap: 8, marginTop: 10, fontSize: 14, fontWeight: 600 }}>
                <Link href={other.href} tabIndex={-1}>{other.label} →</Link>
                <Link href="/help" tabIndex={-1}>Help &amp; Support →</Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="wrap toc">
        <nav aria-label="Sections">
          {toc.map((t) => (
            <a key={t.id} href={`#${t.id}`} className={t.id === (active || toc[0]?.id) ? "on" : ""}>{t.label}</a>
          ))}
        </nav>
        <article className="doc" ref={measure}>
          {children}
        </article>
      </div>
    </main>
  );
}
