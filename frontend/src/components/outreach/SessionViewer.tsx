"use client";

/**
 * The sign-in browser, live in the page.
 *
 * The browser that captures a session runs on the server, so without this
 * the only way to drive it was a VNC client over an SSH tunnel — fine for an
 * operator, impossible for a customer.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, Keyboard as KeyboardIcon } from "lucide-react";
import { issueViewerTicket, viewerSocketUrl } from "@/lib/api";

/** X11 keysyms for the keys a login form actually needs. */
const NAMED_KEYS: Record<string, number> = {
  Backspace: 0xff08,
  Tab: 0xff09,
  Enter: 0xff0d,
  Escape: 0xff1b,
  Delete: 0xffff,
  Home: 0xff50,
  End: 0xff57,
  ArrowLeft: 0xff51,
  ArrowUp: 0xff52,
  ArrowRight: 0xff53,
  ArrowDown: 0xff54,
};

/** A character's keysym. Latin-1 maps to itself; everything else is the
 *  codepoint with the Unicode flag set. noVNC's own table cannot be
 *  imported — the package exports only `core/rfb.js`. */
function keysymFor(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0;
  return cp >= 0x20 && cp <= 0xff ? cp : 0x01000000 | cp;
}

export function SessionViewer({
  accountId,
  onError,
}: {
  accountId: number;
  onError?: (message: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const typing = useRef<HTMLTextAreaElement>(null);
  const rfbRef = useRef<{ sendKey: (k: number, c: string | null, d?: boolean) => void } | null>(null);
  const [state, setState] = useState<"connecting" | "live" | "lost">("connecting");
  const [expanded, setExpanded] = useState(false);
  const [touch, setTouch] = useState(false);

  useEffect(() => {
    setTouch(window.matchMedia("(pointer: coarse)").matches);
  }, []);

  useEffect(() => {
    let rfb: { disconnect: () => void } | null = null;
    let cancelled = false;

    (async () => {
      try {
        // Imported here rather than at module scope: noVNC touches window on
        // load, which breaks a server-rendered page.
        const { default: RFB } = await import("@novnc/novnc");
        const ticket = await issueViewerTicket(accountId);
        if (cancelled || !holder.current) return;

        const client = new RFB(holder.current, viewerSocketUrl(ticket));
        // Scale rather than crop: a 1440x900 desktop has to be usable in a
        // panel on a phone.
        client.scaleViewport = true;
        client.resizeSession = false;
        client.addEventListener("connect", () => setState("live"));
        client.addEventListener("disconnect", () => setState("lost"));
        rfb = client;
        rfbRef.current = client as unknown as typeof rfbRef.current;
      } catch (e) {
        if (cancelled) return;
        setState("lost");
        onError?.(e instanceof Error ? e.message : "Could not open the browser");
      }
    })();

    return () => {
      cancelled = true;
      rfbRef.current = null;
      try {
        rfb?.disconnect();
      } catch {
        /* already gone */
      }
    };
  }, [accountId, onError]);

  // Escape leaves the expanded view, which is the only way out on a phone
  // where there is no visible chrome.
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  /** Raise the on-screen keyboard.
   *
   *  noVNC focuses its `<canvas>`, and a canvas never opens one — browsers
   *  only do that for an editable element. So a real textarea takes the
   *  focus and its characters are forwarded as key events.
   */
  const openKeyboard = useCallback(() => {
    typing.current?.focus();
  }, []);

  const onTyped = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    e.target.value = "";
    for (const ch of text) rfbRef.current?.sendKey(keysymFor(ch), null);
  };

  const onSpecialKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const keysym = NAMED_KEYS[e.key];
    if (!keysym) return; // an ordinary character; onTyped handles it
    e.preventDefault();
    rfbRef.current?.sendKey(keysym, null);
  };

  return (
    <div
      className={
        expanded
          ? "fixed inset-0 z-[60] flex flex-col bg-black"
          : "relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-black"
      }
    >
      <div className="absolute right-2 top-2 z-10 flex gap-1">
        {touch && (
          <button
            type="button"
            onClick={openKeyboard}
            aria-label="Show keyboard"
            className="rounded-md bg-black/60 p-2 text-white backdrop-blur hover:bg-black/80"
          >
            <KeyboardIcon className="h-4 w-4" />
          </button>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? "Exit full screen" : "Full screen"}
          className="rounded-md bg-black/60 p-2 text-white backdrop-blur hover:bg-black/80"
        >
          {expanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>
      </div>

      <div ref={holder} className="min-h-0 flex-1" onClick={touch ? openKeyboard : undefined} />

      {/* Focusable and invisible, but never display:none — that cannot take
          focus, and taking focus is the whole point. */}
      <textarea
        ref={typing}
        onChange={onTyped}
        onKeyDown={onSpecialKey}
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        aria-hidden
        className="absolute h-px w-px opacity-0"
        style={{ left: -9999, top: 0 }}
      />

      {state !== "live" && (
        <p className="bg-background px-3 py-2 text-xs text-muted-foreground">
          {state === "connecting" ? "Opening…" : "Disconnected."}
        </p>
      )}
    </div>
  );
}
