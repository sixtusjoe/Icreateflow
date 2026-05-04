"use client";

import { useState } from "react";
import { Check, Link2, Unlink } from "lucide-react";
import { toast } from "sonner";
import {
  startOAuth,
  disconnectOAuth,
  assignMetaAsset,
  type MetaAsset,
} from "@/lib/api";

type PlatformKey = "tiktok" | "youtube" | "instagram" | "facebook";

const PLATFORM_LABELS: Record<PlatformKey, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

// The Instagram tile asks for "instagram" — backend transparently falls
// back to the Meta FB-Login app if the standalone Instagram app isn't
// configured, so existing deployments keep working.
const OAUTH_PLATFORM_FOR: Record<PlatformKey, "tiktok" | "youtube" | "meta" | "instagram"> = {
  tiktok: "tiktok",
  youtube: "youtube",
  instagram: "instagram",
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

type PickState = {
  assets: MetaAsset[];
  assignToken: string;
  platformLabel: string;
} | null;

export default function OAuthTiles({ account, onChange, kind = "account" }: OAuthTilesProps) {
  const [busy, setBusy] = useState<PlatformKey | null>(null);
  const [pick, setPick] = useState<PickState>(null);
  const [submittingAsset, setSubmittingAsset] = useState(false);

  const handleConnect = async (p: PlatformKey) => {
    // CRITICAL: open the popup SYNCHRONOUSLY inside the click handler.
    // Mobile Safari, Firefox iOS and some webviews block window.open()
    // calls that happen after an await — they require the open to be
    // a direct user-gesture descendant. We open about:blank now and
    // navigate it once we have the authorize URL below.
    const popup = window.open("about:blank", "oauth", "width=600,height=720");
    if (!popup) {
      toast.error("Popup blocked — allow popups for this site (Settings → Site permissions)");
      return;
    }
    setBusy(p);
    try {
      const { authorize_url } = await startOAuth(OAUTH_PLATFORM_FOR[p], account.id, kind);
      popup.location.href = authorize_url;
      // iOS Safari (and some embedded webviews) drops `window.opener`
      // across an external OAuth domain, so the success postMessage
      // never reaches us. We treat popup-close as a "definitely done"
      // signal: refetch state so the connected handle/avatar appear
      // even when the message path failed. `messageHandled` keeps the
      // happy path from double-firing toasts/onChange.
      let messageHandled = false;
      const listener = (ev: MessageEvent) => {
        if (ev.data?.type !== "oauth") return;
        if (ev.data.status === "pick_asset") {
          // Multi-asset grant — show selection modal. Don't clear listener
          // yet, popup might also send a final status.
          window.removeEventListener("message", listener);
          setBusy(null);
          messageHandled = true;
          setPick({
            assets: ev.data.assets || [],
            assignToken: ev.data.assign_token,
            platformLabel: PLATFORM_LABELS[p],
          });
          return;
        }
        window.removeEventListener("message", listener);
        setBusy(null);
        messageHandled = true;
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
          if (!messageHandled) {
            // Fallback: assume the OAuth flow completed (the backend
            // writes tokens before rendering the close-html), refetch
            // state, and let the parent decide whether the tile shows
            // as connected.
            onChange();
          }
        }
      }, 800);
    } catch (e: any) {
      // We opened a popup synchronously above. If startOAuth failed,
      // close the empty popup so the user isn't left with about:blank.
      try { popup.close(); } catch {}
      toast.error(
        e?.response?.data?.detail
          || "Failed to start OAuth — admin must configure the app first"
      );
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

  const submitAssetChoice = async (asset: MetaAsset) => {
    if (!pick) return;
    setSubmittingAsset(true);
    try {
      await assignMetaAsset({
        assign_token: pick.assignToken,
        page_id: asset.page_id ?? undefined,
        ig_user_id: asset.ig_user_id ?? undefined,
      });
      toast.success(`Connected ${asset.page_name || asset.ig_handle || "page"}`);
      setPick(null);
      onChange();
    } catch {
      toast.error("Failed to assign — reconnect and try again");
    } finally {
      setSubmittingAsset(false);
    }
  };

  return (
    <>
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

      {pick ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-border bg-background p-4 shadow-xl">
            <h3 className="text-sm font-semibold">Pick a Page for this variation</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              You granted multiple Pages / Instagram accounts. Pick the one that belongs to <b>this</b> variation. Each variation needs its own connection — repeat for the others.
            </p>
            <div className="mt-3 space-y-2 max-h-80 overflow-auto">
              {pick.assets.map((a, i) => (
                <button
                  key={`${a.page_id || a.ig_user_id || i}`}
                  disabled={submittingAsset}
                  onClick={() => submitAssetChoice(a)}
                  className="w-full rounded-lg border border-border p-3 text-left hover:border-emerald-500/60 hover:bg-emerald-500/5 disabled:opacity-50"
                >
                  <div className="text-sm font-medium">
                    {a.page_name || (a.ig_handle ? `@${a.ig_handle}` : "Untitled")}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {a.page_id ? `Page · ${a.page_id}` : "Standalone IG"}
                    {a.ig_handle ? ` · IG @${a.ig_handle}` : ""}
                  </div>
                </button>
              ))}
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => setPick(null)}
                disabled={submittingAsset}
                className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
