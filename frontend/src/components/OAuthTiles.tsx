"use client";

import { useState } from "react";
import { Check, Link2, Unlink } from "lucide-react";
import { toast } from "sonner";
import { startOAuth, disconnectOAuth } from "@/lib/api";

type PlatformKey = "tiktok" | "youtube" | "instagram" | "facebook";

const PLATFORM_LABELS: Record<PlatformKey, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

// One Meta OAuth flow grants both IG and FB. YouTube uses the "youtube" OAuth platform.
const OAUTH_PLATFORM_FOR: Record<PlatformKey, "tiktok" | "youtube" | "meta"> = {
  tiktok: "tiktok",
  youtube: "youtube",
  instagram: "meta",
  facebook: "meta",
};

export type OAuthTilesKind = "account" | "variation";

type OAuthTilesProps = {
  account: Record<string, unknown> & { id: number };
  onChange: () => void;
  kind?: OAuthTilesKind;
};

function isConnected(account: OAuthTilesProps["account"], p: PlatformKey): boolean {
  return Boolean(
    account[`${p}_connected`] ||
      account[`${p}_access_token`] ||
      account[`${p}_token`]
  );
}

export default function OAuthTiles({ account, onChange, kind = "account" }: OAuthTilesProps) {
  const [busy, setBusy] = useState<PlatformKey | null>(null);

  const handleConnect = async (p: PlatformKey) => {
    setBusy(p);
    try {
      const { authorize_url } = await startOAuth(OAUTH_PLATFORM_FOR[p], account.id, kind);
      const popup = window.open(authorize_url, "oauth", "width=600,height=720");
      if (!popup) {
        toast.error("Popup blocked — allow popups for this site");
        setBusy(null);
        return;
      }
      const listener = (ev: MessageEvent) => {
        if (ev.data?.type !== "oauth") return;
        window.removeEventListener("message", listener);
        setBusy(null);
        if (ev.data.status === "success") {
          toast.success(`${PLATFORM_LABELS[p]} connected`);
          onChange();
        } else toast.error(ev.data.message || "Connection failed");
      };
      window.addEventListener("message", listener);
      const poll = setInterval(() => {
        if (popup.closed) {
          clearInterval(poll);
          window.removeEventListener("message", listener);
          setBusy(null);
        }
      }, 800);
    } catch {
      toast.error("Failed to start OAuth — admin must configure the app first");
      setBusy(null);
    }
  };

  const handleDisconnect = async (p: PlatformKey) => {
    if (!confirm(`Disconnect ${PLATFORM_LABELS[p]}?`)) return;
    try {
      await disconnectOAuth(OAUTH_PLATFORM_FOR[p], account.id, kind);
      toast.success(`${PLATFORM_LABELS[p]} disconnected`);
      onChange();
    } catch {
      toast.error("Failed to disconnect");
    }
  };

  return (
    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
      {(Object.keys(PLATFORM_LABELS) as PlatformKey[]).map((p) => {
        const connected = isConnected(account, p);
        const handle = account[`${p}_handle`] as string | undefined;
        return (
          <div
            key={p}
            className={`rounded-lg border p-2.5 ${connected ? "border-emerald-500/40 bg-emerald-500/5" : "border-border"}`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold">{PLATFORM_LABELS[p]}</span>
              {connected ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : null}
            </div>
            {connected ? (
              <>
                <div className="mt-1 truncate text-[11px] text-muted-foreground">
                  {handle ? `@${handle.replace(/^@+/, "")}` : "Connected"}
                </div>
                <button
                  onClick={() => handleDisconnect(p)}
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-destructive"
                >
                  <Unlink className="h-3 w-3" /> Disconnect
                </button>
              </>
            ) : (
              <button
                onClick={() => handleConnect(p)}
                disabled={busy === p}
                className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-foreground px-2 py-1 text-[11px] font-medium text-background disabled:opacity-50"
              >
                <Link2 className="h-3 w-3" /> {busy === p ? "…" : "Connect"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
