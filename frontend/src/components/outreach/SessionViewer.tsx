"use client";

/**
 * The sign-in browser, live in the page.
 *
 * The browser that captures a session runs on the server, so without this
 * the only way to drive it was a VNC client over an SSH tunnel — fine for an
 * operator, impossible for a customer. noVNC renders it into a canvas here
 * and sends clicks and keystrokes back.
 */
import { useEffect, useRef, useState } from "react";
import { issueViewerTicket, viewerSocketUrl } from "@/lib/api";

export function SessionViewer({
  accountId,
  onError,
}: {
  accountId: number;
  onError?: (message: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"connecting" | "live" | "lost">("connecting");

  useEffect(() => {
    let rfb: { disconnect: () => void } | null = null;
    let cancelled = false;

    (async () => {
      try {
        // Imported here rather than at module scope: noVNC touches window
        // on load, which breaks a server-rendered page.
        const { default: RFB } = await import("@novnc/novnc");
        const ticket = await issueViewerTicket(accountId);
        if (cancelled || !holder.current) return;

        const client = new RFB(holder.current, viewerSocketUrl(ticket));
        // Scale rather than crop: a 1440x900 desktop has to be usable in a
        // modal on a phone.
        client.scaleViewport = true;
        client.resizeSession = false;
        client.addEventListener("connect", () => setState("live"));
        client.addEventListener("disconnect", () => setState("lost"));
        rfb = client;
      } catch (e) {
        if (cancelled) return;
        setState("lost");
        onError?.(e instanceof Error ? e.message : "Could not open the browser");
      }
    })();

    return () => {
      cancelled = true;
      try {
        rfb?.disconnect();
      } catch {
        /* already gone */
      }
    };
  }, [accountId, onError]);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-black">
      <div ref={holder} className="h-[min(62vh,560px)] w-full" />
      {state !== "live" && (
        <p className="border-t border-border bg-background px-3 py-2 text-xs text-muted-foreground">
          {state === "connecting" ? "Opening…" : "Disconnected."}
        </p>
      )}
    </div>
  );
}
