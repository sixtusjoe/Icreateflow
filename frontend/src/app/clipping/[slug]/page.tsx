"use client";

import React, { use, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Trash2,
  Edit2,
  Users,
  Eye,
  BarChart3,
  Save,
  RefreshCw,
  X,
  Check,
  Play,
  Square,
  Download,
  AlertCircle,
  RotateCcw,
  Target,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import OAuthTiles from "@/components/OAuthTiles";
import { TikTokSettingsCard } from "@/components/TikTokSettingsCard";
import {
  getArtistBySlug,
  updateArtist,
  createVariation,
  updateArtistVariation,
  deleteArtistVariation,
  refreshVariationProfile,
  uploadVariationClip,
  syncVariationGdriveClips,
  catchupTodayPromotion,
  updateClip,
  deleteClip,
  getArtistDashboard,
  startPromotion,
  stopPromotion,
  togglePausePromotion,
  resetPromotion,
  listCampaigns,
  downloadStatsCsv,
  updateVariationTiktokSettings,
  getArtistFailedPosts,
  retryClipPost,
  clearArtistFailedPosts,
} from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";

type Variation = {
  id: number;
  name: string;
  tiktok_handle?: string;
  youtube_handle?: string;
  instagram_handle?: string;
  facebook_handle?: string;
  tiktok_connected?: boolean;
  youtube_connected?: boolean;
  instagram_connected?: boolean;
  facebook_connected?: boolean;
  gdrive_folder_url?: string | null;
  proxy_url?: string | null;
  paused_reason?: string | null;
  // TikTok Direct Post settings (Clipping pipeline persists per variation).
  tiktok_post_as_draft?: boolean | null;
  tiktok_privacy_level?: string | null;
  tiktok_disclosure_enabled?: boolean | null;
  tiktok_disclose_your_brand?: boolean | null;
  tiktok_disclose_branded_content?: boolean | null;
  tiktok_allow_comment?: boolean | null;
  tiktok_allow_duet?: boolean | null;
  tiktok_allow_stitch?: boolean | null;
  tiktok_consent_at?: string | null;
};

type Clip = {
  id: number;
  source: "upload" | "gdrive";
  filename: string;
  caption?: string;
  times_posted: number;
  local_path?: string;
  gdrive_file_id?: string;
  artist_account_id?: number | null;
};

// ── Collapsible failed-posts section ──────────────────────────────────────
function FailedPostsSection({
  failedPosts,
  retryingId,
  setRetryingId,
  setFailedPosts,
  artistId,
}: {
  failedPosts: any[];
  retryingId: number | null;
  setRetryingId: (id: number | null) => void;
  setFailedPosts: React.Dispatch<React.SetStateAction<any[]>>;
  artistId: number;
}) {
  const [open, setOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  // Cap-error retry modal
  const [capRetryPost, setCapRetryPost] = useState<any | null>(null);
  const [capRetrying, setCapRetrying] = useState(false);

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await clearArtistFailedPosts(artistId);
      setFailedPosts([]);
      setShowClearConfirm(false);
      toast.success("Cleared all failed posts");
    } catch {
      toast.error("Could not clear");
    } finally {
      setClearing(false);
    }
  };

  const isCapError = (fp: any) =>
    fp.platform === "tiktok" &&
    (fp.friendly_error || "").toLowerCase().includes("active user cap");

  const handleRetry = async (fp: any, mode: "normal" | "draft" = "normal") => {
    setRetryingId(fp.id);
    if (mode === "draft") setCapRetrying(true);
    try {
      const res = await retryClipPost(fp.id, mode);
      if (mode === "draft") {
        toast.success("Retry scheduled as draft — will post to TikTok inbox immediately");
        setCapRetryPost(null);
      } else {
        const msg = res.cooldown_hours >= 6
          ? `Retry scheduled — will post in ~6 hours (platform cap cooldown)`
          : `Retry scheduled — will post in ~2 minutes`;
        toast.success(msg);
      }
      setFailedPosts((prev) => prev.filter((p) => p.id !== fp.id));
    } catch {
      toast.error("Failed to retry");
    } finally {
      setRetryingId(null);
      setCapRetrying(false);
    }
  };

  return (
    <>
      <ConfirmModal
        open={showClearConfirm}
        onOpenChange={setShowClearConfirm}
        title="Clear all failed posts?"
        description={`This will permanently delete all ${failedPosts.length} failed post${failedPosts.length !== 1 ? "s" : ""} from your history. You won't be able to retry them afterward. Note: failed posts are also auto-cleared after 24 hours.`}
        confirmLabel="Yes, clear all"
        cancelLabel="Cancel"
        variant="danger"
        loading={clearing}
        onConfirm={handleClearAll}
      />

      {/* TikTok cap-error retry options modal */}
      {capRetryPost && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-background p-6 shadow-xl">
            <h3 className="text-base font-semibold">Retry TikTok post</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              This account has hit TikTok's active user cap. Choose how to retry:
            </p>
            <div className="mt-5 flex flex-col gap-2.5">
              <button
                onClick={() => handleRetry(capRetryPost, "draft")}
                disabled={capRetrying}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Post as draft</span>
                <span className="text-xs text-muted-foreground">Posts immediately to TikTok inbox — you publish from the app</span>
              </button>
              <button
                onClick={() => handleRetry(capRetryPost, "normal")}
                disabled={capRetrying}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Retry in 6 hours</span>
                <span className="text-xs text-muted-foreground">System retries direct post after the cap cooldown</span>
              </button>
              <button
                onClick={() => setCapRetryPost(null)}
                disabled={capRetrying}
                className="mt-1 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      <section className="rounded-2xl border border-destructive/30 bg-destructive/5 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 md:px-5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 flex-1 text-left"
        >
          <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
          <span className="text-sm font-semibold text-destructive whitespace-nowrap">Failed Posts</span>
          <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-xs font-semibold text-destructive shrink-0">
            {failedPosts.length}
          </span>
          <span className="text-xs text-muted-foreground hidden sm:inline whitespace-nowrap">· auto-cleared after 24 hours</span>
          <ChevronDown className={`h-4 w-4 text-destructive/60 ml-1 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        <button
          onClick={() => setShowClearConfirm(true)}
          disabled={clearing}
          className="shrink-0 text-xs text-destructive/70 hover:text-destructive font-medium disabled:opacity-50"
        >
          {clearing ? "Clearing…" : "Clear all"}
        </button>
      </div>
      {open && (
        <div className="divide-y divide-destructive/10 border-t border-destructive/20">
          {failedPosts.map((fp: any) => (
            <div key={fp.id} className="flex flex-col gap-1.5 px-4 py-3 md:px-5 sm:flex-row sm:items-center sm:gap-3">
              {/* Top row on mobile: platform badge + variation + retry button */}
              <div className="flex items-center gap-2 sm:contents">
                <span className="shrink-0 rounded-md bg-muted px-2 py-0.5 text-xs font-semibold capitalize">
                  {fp.platform}
                </span>
                <span className="text-xs text-muted-foreground shrink-0 flex-1 sm:flex-none truncate">
                  {fp.variation_name}
                </span>
                {/* Retry on mobile lives in this row, right-aligned */}
                <button
                  onClick={() => isCapError(fp) ? setCapRetryPost(fp) : handleRetry(fp)}
                  disabled={retryingId === fp.id}
                  className="sm:hidden ml-auto shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                >
                  <RotateCcw className="h-3 w-3" />
                  {retryingId === fp.id ? "Retrying…" : "Retry"}
                </button>
              </div>

              {/* Error message — full width on mobile */}
              <span className="text-xs text-destructive/90 sm:flex-1 sm:min-w-0 sm:truncate" title={fp.friendly_error}>
                {fp.friendly_error}
              </span>

              {/* Date — hidden on mobile */}
              {fp.scheduled_for && (
                <span className="shrink-0 text-xs text-muted-foreground/60 hidden sm:block">
                  {new Date(fp.scheduled_for).toLocaleDateString([], { month: "short", day: "numeric" })}
                  {" · "}
                  {new Date(fp.scheduled_for).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}

              {/* Retry on desktop */}
              <button
                onClick={() => isCapError(fp) ? setCapRetryPost(fp) : handleRetry(fp)}
                disabled={retryingId === fp.id}
                className="hidden sm:inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
              >
                <RotateCcw className="h-3 w-3" />
                {retryingId === fp.id ? "Retrying…" : "Retry"}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
    </>
  );
}

type Dashboard = {
  variations_count: number;
  active_clips: number;
  posts_today: number;
  posts_total: number;
  views_total: number;
  by_platform: Record<string, { posted: number; views: number }>;
  next_scheduled_at: string | null;
  is_active?: boolean;
  paused_reason?: string | null;
  view_target?: number | null;
  current_campaign?: Campaign | null;
  poll?: {
    interval_seconds: number;
    last_polled_at: string | null;
    next_poll_at: string;
  } | null;
  variation_next_clips?: Record<number, string | null>;
};

type Campaign = {
  id: number;
  artist_id: number;
  name: string;
  view_target?: number | null;
  started_at: string;
  ended_at?: string | null;
  status: "active" | "ended" | "reset";
  views_total: number;
  posts_total: number;
};

const PLATFORMS = ["tiktok", "youtube", "instagram", "facebook"] as const;

/**
 * Format a UTC ISO timestamp in the artist's configured scheduler timezone.
 * The tz saved on the scheduler is the single source of truth — the viewer's
 * browser tz is ignored so everyone sees the same wall-clock time.
 */
function formatInArtistTz(
  iso: string | null | undefined,
  tz: string,
  opts: { dateOnly?: boolean } = {},
): string {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "short",
      ...(opts.dateOnly ? {} : { timeStyle: "short", timeZoneName: "short" as const }),
      timeZone: tz || "US/Eastern",
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString();
  }
}

export default function ArtistPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);

  const [artist, setArtist] = useState<Record<string, unknown> | null>(null);
  const [id, setId] = useState<number | null>(null);
  const [variations, setVariations] = useState<Variation[]>([]);
  const [clips, setClips] = useState<Clip[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [failedPosts, setFailedPosts] = useState<any[]>([]);
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const [showNewVariation, setShowNewVariation] = useState(false);
  const [newVar, setNewVar] = useState({
    name: "",
    tiktok_handle: "",
    youtube_handle: "",
    instagram_handle: "",
    facebook_handle: "",
  });
  const [variationsOpen, setVariationsOpen] = useState(true);

  const [editingVarId, setEditingVarId] = useState<number | null>(null);
  const [editVar, setEditVar] = useState({
    name: "",
    tiktok_handle: "",
    youtube_handle: "",
    instagram_handle: "",
    facebook_handle: "",
  });

  const startEditVariation = (v: Variation) => {
    setEditingVarId(v.id);
    setEditVar({
      name: v.name || "",
      tiktok_handle: (v as any).tiktok_handle || "",
      youtube_handle: (v as any).youtube_handle || "",
      instagram_handle: (v as any).instagram_handle || "",
      facebook_handle: (v as any).facebook_handle || "",
    });
  };

  const saveEditVariation = async () => {
    if (editingVarId == null) return;
    const clean: Record<string, string> = { name: editVar.name };
    for (const k of ["tiktok_handle", "youtube_handle", "instagram_handle", "facebook_handle"] as const) {
      clean[k] = (editVar[k] || "").replace(/^@+/, "");
    }
    try {
      await updateArtistVariation(editingVarId, clean);
      setEditingVarId(null);
      load();
      toast.success("Variation updated");
    } catch { toast.error("Failed to update variation"); }
  };

  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [clipCaption, setClipCaption] = useState("");

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [startTarget, setStartTarget] = useState<string>("");
  const [startName, setStartName] = useState<string>("");
  const [startErrors, setStartErrors] = useState<string[]>([]);
  const [showReset, setShowReset] = useState(false);
  const [resetTarget, setResetTarget] = useState<string>("");
  const [resetName, setResetName] = useState<string>("");
  const [busy, setBusy] = useState(false);

  // Confirm modals for destructive actions
  const [confirmStop, setConfirmStop] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmDeleteVariation, setConfirmDeleteVariation] = useState<number | null>(null);
  const [confirmDeleteClip, setConfirmDeleteClip] = useState<number | null>(null);

  // Heartbeat: timestamp of the last successful dashboard refresh, used to
  // render "Updated Ns ago" so the user can see the poll loop is alive even
  // when the underlying numbers haven't changed.
  const [lastDashboardAt, setLastDashboardAt] = useState<number | null>(null);
  const [pollNow, setPollNow] = useState(() => Date.now());

  const [settings, setSettings] = useState({
    posts_per_day: 3,
    window_start: "09:00",
    window_end: "21:00",
    timezone: "US/Eastern",
  });

  const load = useCallback(() => {
    getArtistBySlug(slug)
      .then((a) => {
        setArtist(a);
        setId(a.id);
        setVariations(a.variations || []);
        setClips(a.clips || []);
        setSettings({
          posts_per_day: a.posts_per_day ?? 3,
          window_start: a.window_start ?? "09:00",
          window_end: a.window_end ?? "21:00",
          timezone: a.timezone ?? "US/Eastern",
        });
        getArtistDashboard(a.id)
          .then((d) => {
            setDashboard(d);
            setLastDashboardAt(Date.now());
          })
          .catch(() => {});
        getArtistFailedPosts(a.id).then(setFailedPosts).catch(() => {});
        listCampaigns(a.id).then(setCampaigns).catch(() => {});
      })
      .catch(() => toast.error("Failed to load artist"));
  }, [slug]);

  useEffect(() => {
    load();
    const iv = setInterval(() => {
      if (id != null) {
        getArtistDashboard(id)
          .then((d) => {
            setDashboard(d);
            setLastDashboardAt(Date.now());
          })
          .catch(() => {});
      }
    }, 30000);
    // Tick the "updated Ns ago" label every second so it counts up smoothly
    // between actual refreshes.
    const tick = setInterval(() => setPollNow(Date.now()), 1000);
    return () => {
      clearInterval(iv);
      clearInterval(tick);
    };
  }, [id, load]);

  const refreshCampaigns = useCallback(() => {
    if (id == null) return;
    listCampaigns(id).then(setCampaigns).catch(() => {});
    getArtistDashboard(id)
      .then((d) => {
        setDashboard(d);
        setLastDashboardAt(Date.now());
      })
      .catch(() => {});
  }, [id]);

  const handleStartPromotion = async () => {
    if (id == null) return;
    setStartErrors([]);
    setBusy(true);
    try {
      await startPromotion(id, {
        view_target: startTarget ? Number(startTarget) : undefined,
        campaign_name: startName || undefined,
      });
      toast.success("Promotion started");
      setStartTarget("");
      setStartName("");
      refreshCampaigns();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (detail && typeof detail === "object" && "errors" in (detail as Record<string, unknown>)) {
        setStartErrors((detail as { errors: string[] }).errors);
      } else {
        toast.error(typeof detail === "string" ? detail : "Failed to start promotion");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleStopPromotion = async () => {
    if (id == null) return;
    setBusy(true);
    try {
      await stopPromotion(id);
      toast.success("Promotion stopped");
      refreshCampaigns();
    } catch {
      toast.error("Failed to stop");
    } finally {
      setBusy(false);
    }
  };

  const handleResetPromotion = async () => {
    if (id == null) return;
    setBusy(true);
    try {
      await resetPromotion(id, {
        view_target: resetTarget ? Number(resetTarget) : undefined,
        campaign_name: resetName || undefined,
        delete_clips: true,
      });
      toast.success("Reset complete — upload new clips and start the next campaign");
      setShowReset(false);
      setResetTarget("");
      setResetName("");
      load();
    } catch {
      toast.error("Failed to reset");
    } finally {
      setBusy(false);
    }
  };

  const handleDownloadStats = async (campaign_id?: number) => {
    if (id == null) return;
    try {
      await downloadStatsCsv(id, { slug, campaign_id });
    } catch {
      toast.error("Download failed");
    }
  };

  const saveSettings = async () => {
    if (id == null) return;
    try {
      await updateArtist(id, settings);
      toast.success("Settings saved");
      load();
    } catch {
      toast.error("Failed to save");
    }
  };

  const handleCreateVariation = async () => {
    if (id == null) return;
    if (!newVar.name) return toast.error("Name required");
    const clean = { ...newVar };
    for (const k of ["tiktok_handle", "youtube_handle", "instagram_handle", "facebook_handle"] as const) {
      if (clean[k]) clean[k] = clean[k].replace(/^@+/, "");
    }
    try {
      await createVariation(id, clean);
      setShowNewVariation(false);
      setNewVar({
        name: "",
        tiktok_handle: "",
        youtube_handle: "",
        instagram_handle: "",
        facebook_handle: "",
      });
      load();
      toast.success("Variation added");
    } catch {
      toast.error("Failed to add variation");
    }
  };

  const handleDeleteVariation = async (vid: number) => {
    try {
      await deleteArtistVariation(vid);
      load();
      toast.success("Variation deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  const startEditClip = (c: Clip) => {
    setEditingClipId(c.id);
    setClipCaption(c.caption || "");
  };

  const saveClipCaption = async () => {
    if (editingClipId == null) return;
    try {
      await updateClip(editingClipId, { caption: clipCaption });
      setEditingClipId(null);
      load();
    } catch {
      toast.error("Failed to save caption");
    }
  };

  const handleDeleteClip = async (cid: number) => {
    try {
      await deleteClip(cid);
      load();
      toast.success("Clip deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  const inputClass =
    "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground placeholder:text-muted-foreground";

  if (!artist) {
    return (
      <div className="mx-auto max-w-5xl">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* ── Confirm modals ─────────────────────────────────────────────── */}
      <ConfirmModal
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title="Stop promotion?"
        description="This will stop the current promotion. You can restart it at any time."
        confirmLabel="Stop"
        variant="danger"
        loading={busy}
        onConfirm={async () => { setConfirmStop(false); await handleStopPromotion(); }}
      />
      <ConfirmModal
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset directory?"
        description="All uploaded clips will be deleted and the current campaign archived. Historical stats remain downloadable."
        confirmLabel="Yes, reset"
        variant="danger"
        loading={busy}
        onConfirm={async () => { setConfirmReset(false); await handleResetPromotion(); }}
      />
      <ConfirmModal
        open={confirmDeleteVariation !== null}
        onOpenChange={(o) => { if (!o) setConfirmDeleteVariation(null); }}
        title="Delete this variation?"
        description="This will permanently remove the variation and all its connection settings."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={async () => { const vid = confirmDeleteVariation; setConfirmDeleteVariation(null); if (vid !== null) await handleDeleteVariation(vid); }}
      />
      <ConfirmModal
        open={confirmDeleteClip !== null}
        onOpenChange={(o) => { if (!o) setConfirmDeleteClip(null); }}
        title="Delete this clip?"
        description="This clip will be permanently removed from the directory."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={async () => { const cid = confirmDeleteClip; setConfirmDeleteClip(null); if (cid !== null) await handleDeleteClip(cid); }}
      />
      {/* ─────────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <Link href="/clipping" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <h1 className="text-xl md:text-2xl font-bold">{String(artist.name)}</h1>
        <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
          {String(artist.slug)}
        </span>
      </div>

      {/* Top summary */}
      {dashboard && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard icon={<BarChart3 className="h-4 w-4" />} label="Posts today" value={dashboard.posts_today} />
          <StatCard icon={<BarChart3 className="h-4 w-4" />} label="Posts total" value={dashboard.posts_total} />
          <StatCard icon={<Eye className="h-4 w-4" />} label="Total views" value={dashboard.views_total.toLocaleString()} />
          <StatCard
            icon={<RefreshCw className="h-4 w-4" />}
            label="Next slot"
            value={
              dashboard.next_scheduled_at
                ? formatInArtistTz(dashboard.next_scheduled_at, settings.timezone)
                : "—"
            }
          />
        </div>
      )}

      {/* View-poll countdown */}
      {dashboard?.poll && <PollCountdown poll={dashboard.poll} />}

      {/* Per-platform */}
      {dashboard && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {PLATFORMS.map((p) => (
            <div key={p} className="rounded-xl bg-card p-3">
              <div className="text-xs font-semibold capitalize">{p}</div>
              <div className="mt-1 text-sm text-muted-foreground">
                {dashboard.by_platform[p]?.posted ?? 0} posted · {(dashboard.by_platform[p]?.views ?? 0).toLocaleString()} views
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Failed posts — collapsible */}
      {failedPosts.length > 0 && (
        <FailedPostsSection
          failedPosts={failedPosts}
          retryingId={retryingId}
          setRetryingId={setRetryingId}
          setFailedPosts={setFailedPosts}
          artistId={Number(artist.id)}
        />
      )}

      {/* Campaign / Promotion */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Target className="h-4 w-4" /> Campaign
            {lastDashboardAt != null && (
              <span
                className="ml-1 text-[10px] font-normal text-muted-foreground"
                title={`Last refresh: ${new Date(lastDashboardAt).toLocaleTimeString()}`}
              >
                · {Math.max(0, Math.floor((pollNow - lastDashboardAt) / 1000))}s ago
              </span>
            )}
          </h2>
          <div className="flex items-center gap-2">
            {dashboard?.is_active ? (
              (() => {
                const reason = dashboard.paused_reason;
                const isPaused = Boolean(reason);
                const label = reason === "target_reached"
                  ? "Target reached"
                  : reason === "directory_exhausted"
                  ? "Paused — add clips"
                  : reason === "manual"
                  ? "Paused"
                  : "Running";
                // All paused reasons are clickable — clicking clears
                // paused_reason and resumes. directory_exhausted/target_reached
                // were originally non-clickable (theory: "add a clip" or
                // "new campaign" was the only valid escape) but that left
                // users stuck when the auto-resume hook hadn't run yet
                // (e.g. silent NameError, or queued rows from before the
                // re-pause that they want to fire now).
                const clickable = true;
                const title = isPaused
                  ? reason === "directory_exhausted"
                    ? "Click to resume — fires queued slots until paused again"
                    : reason === "target_reached"
                    ? "Click to resume — view target already met"
                    : "Click to resume"
                  : "Click to pause";
                const handleClick = async () => {
                  if (!clickable || !id) return;
                  try {
                    await togglePausePromotion(id);
                    toast.success(isPaused ? "Resumed" : "Paused");
                    refreshCampaigns();
                  } catch {
                    toast.error("Failed to toggle pause");
                  }
                };
                return (
                  <button
                    type="button"
                    disabled={!clickable}
                    onClick={handleClick}
                    title={title}
                    className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition ${
                      isPaused
                        ? "bg-amber-500/15 text-amber-600 hover:bg-amber-500/25"
                        : "bg-emerald-500/15 text-emerald-600 hover:bg-emerald-500/25"
                    } ${clickable ? "cursor-pointer" : "cursor-default"}`}
                  >
                    {label}
                  </button>
                );
              })()
            ) : (
              <span className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                Stopped
              </span>
            )}
            <button
              onClick={() => handleDownloadStats()}
              className="inline-flex items-center justify-center rounded-lg border border-border p-1.5 hover:bg-muted"
              title="Download all stats for this artist"
              aria-label="Download stats"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {dashboard?.is_active && dashboard.current_campaign ? (
          <div className="space-y-4">
            <div>
              <div className="mb-1 text-sm font-medium">{dashboard.current_campaign.name}</div>
              <div className="text-xs text-muted-foreground">
                Started {formatInArtistTz(dashboard.current_campaign.started_at, settings.timezone)} ·{" "}
                {dashboard.posts_total} posts · {dashboard.views_total.toLocaleString()} views
              </div>
            </div>
            {dashboard.view_target != null && dashboard.view_target > 0 && (
              <div>
                <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                  <span>Progress to target</span>
                  <span>
                    {dashboard.views_total.toLocaleString()} /{" "}
                    {dashboard.view_target.toLocaleString()}
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-foreground"
                    style={{
                      width: `${Math.min(
                        100,
                        (dashboard.views_total / Math.max(1, dashboard.view_target)) * 100
                      )}%`,
                    }}
                  />
                </div>
              </div>
            )}
            {dashboard.paused_reason === "directory_exhausted" && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <span>
                  Every clip has been posted at least once. Upload new clips or sync more from
                  Drive and posting will resume automatically.
                </span>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setConfirmStop(true)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5" /> Stop
              </button>
              <button
                onClick={async () => {
                  if (id == null) return;
                  try {
                    const r = await catchupTodayPromotion(id);
                    if (r.inserted > 0) {
                      toast.success(`Catching up — ${r.inserted} post${r.inserted === 1 ? "" : "s"} queued`);
                    } else {
                      toast(`No catch-up posts queued (paused or no clip available).`);
                    }
                    load();
                  } catch (e: unknown) {
                    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                    toast.error(msg || "Catch-up failed");
                  }
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
                title="Plan a single now+30s post for today's missed slot(s)"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Catch up missed slots
              </button>
              <button
                onClick={() => setShowReset((s) => !s)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
              >
                <RotateCcw className="h-3.5 w-3.5" /> Reset directory
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Kick off a new campaign. Posting resumes at the next scheduled slot.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium">View target (optional)</label>
                <input
                  type="number"
                  min={0}
                  value={startTarget}
                  onChange={(e) => setStartTarget(e.target.value)}
                  className={inputClass}
                  placeholder="e.g. 1000000"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium">Campaign name (optional)</label>
                <input
                  value={startName}
                  onChange={(e) => setStartName(e.target.value)}
                  className={inputClass}
                  placeholder="e.g. Summer push"
                />
              </div>
            </div>
            {startErrors.length > 0 && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-400">
                <div className="mb-1 flex items-center gap-1.5 font-medium">
                  <AlertCircle className="h-4 w-4" /> Fix the following before starting:
                </div>
                <ul className="ml-5 list-disc space-y-0.5">
                  {startErrors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            <button
              onClick={handleStartPromotion}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" /> Start promotion
            </button>
          </div>
        )}

        {showReset && (
          <div className="mt-4 rounded-xl border border-border p-4 space-y-3">
            <div className="text-xs text-muted-foreground">
              This archives the current campaign (stats remain downloadable below), deletes all
              uploaded clips, and prepares a fresh campaign. Start it manually after uploading new
              clips.
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium">New view target (optional)</label>
                <input
                  type="number"
                  min={0}
                  value={resetTarget}
                  onChange={(e) => setResetTarget(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium">New campaign name (optional)</label>
                <input
                  value={resetName}
                  onChange={(e) => setResetName(e.target.value)}
                  className={inputClass}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setConfirmReset(true)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                <RotateCcw className="h-3.5 w-3.5" /> Confirm reset
              </button>
              <button
                onClick={() => setShowReset(false)}
                className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {campaigns.length > 0 && (
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Past campaigns</div>
            <div className="space-y-2">
              {campaigns
                .filter((c) => c.status !== "active")
                .map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-xs"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium text-foreground">{c.name}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {formatInArtistTz(c.started_at, settings.timezone, { dateOnly: true })}
                        {c.ended_at
                          ? ` → ${formatInArtistTz(c.ended_at, settings.timezone, { dateOnly: true })}`
                          : ""}
                        {" · "}
                        {c.posts_total} posts · {c.views_total.toLocaleString()} views ·{" "}
                        {c.status}
                      </div>
                    </div>
                    <button
                      onClick={() => handleDownloadStats(c.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-medium hover:bg-background"
                    >
                      <Download className="h-3 w-3" /> CSV
                    </button>
                  </div>
                ))}
            </div>
          </div>
        )}
      </section>

      {/* Variations */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <div className={variationsOpen ? "mb-4 flex items-center justify-between" : "flex items-center justify-between"}>
          <button
            onClick={() => setVariationsOpen((v) => !v)}
            className="flex items-center gap-2 text-base font-semibold hover:opacity-80"
            aria-expanded={variationsOpen}
          >
            {variationsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <Users className="h-4 w-4" /> Variations ({variations.length})
          </button>
          {variationsOpen && (
            <button
              onClick={() => setShowNewVariation(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
            >
              <Plus className="h-3 w-3" /> Add
            </button>
          )}
        </div>

        {variationsOpen && showNewVariation && (
          <div className="mb-4 rounded-xl border border-border p-4 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium">Name</label>
              <input
                value={newVar.name}
                onChange={(e) => setNewVar({ ...newVar, name: e.target.value })}
                className={inputClass}
                placeholder="e.g. DJNeon_variation1"
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {PLATFORMS.map((p) => (
                <div key={p}>
                  <label className="mb-1 block text-xs font-medium capitalize">{p} handle</label>
                  <input
                    value={newVar[`${p}_handle` as keyof typeof newVar]}
                    onChange={(e) => setNewVar({ ...newVar, [`${p}_handle`]: e.target.value })}
                    className={inputClass}
                    placeholder="handle (no @)"
                  />
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCreateVariation}
                className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background"
              >
                <Check className="h-3 w-3" /> Add variation
              </button>
              <button
                onClick={() => setShowNewVariation(false)}
                className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" /> Cancel
              </button>
            </div>
          </div>
        )}

        {variationsOpen && (variations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No variations yet.</p>
        ) : (
          <div className="space-y-3">
            {variations.map((v) => (
              editingVarId === v.id ? (
                <div key={v.id} className="rounded-xl border border-border p-3">
                  <h4 className="mb-3 text-sm font-semibold">Edit Variation</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium">Variation Name</label>
                      <input
                        value={editVar.name}
                        onChange={(e) => setEditVar({ ...editVar, name: e.target.value })}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
                      />
                    </div>
                    {(["tiktok", "youtube", "instagram", "facebook"] as const).map((p) => (
                      <div key={p}>
                        <label className="mb-1 block text-xs font-medium capitalize">{p} handle</label>
                        <input
                          value={editVar[`${p}_handle`]}
                          onChange={(e) => setEditVar({ ...editVar, [`${p}_handle`]: e.target.value })}
                          placeholder="handle (without @)"
                          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground"
                        />
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={saveEditVariation}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-90"
                    >
                      <Check className="h-3 w-3" /> Save
                    </button>
                    <button
                      onClick={() => setEditingVarId(null)}
                      className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" /> Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <VariationCard
                  key={v.id}
                  v={v}
                  clips={clips.filter((c) => c.artist_account_id === v.id)}
                  onChange={load}
                  onStartEdit={startEditVariation}
                  onDelete={(vid) => setConfirmDeleteVariation(vid)}
                  editingClipId={editingClipId}
                  clipCaption={clipCaption}
                  onStartEditClip={startEditClip}
                  onChangeCaption={setClipCaption}
                  onSaveCaption={saveClipCaption}
                  onDeleteClip={(cid) => setConfirmDeleteClip(cid)}
                  inputClass={inputClass}
                  nextClip={dashboard?.variation_next_clips?.[v.id] ?? null}
                />
              )
            ))}
          </div>
        ))}
      </section>

      {/* Settings */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <h2 className="mb-4 text-base font-semibold">Schedule settings</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium">Posts per day</label>
            <input
              type="number"
              min={1}
              max={24}
              value={settings.posts_per_day}
              onChange={(e) => setSettings({ ...settings, posts_per_day: Number(e.target.value) })}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">Timezone</label>
            <input
              value={settings.timezone}
              onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">Window start</label>
            <input
              type="time"
              value={settings.window_start}
              onChange={(e) => setSettings({ ...settings, window_start: e.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium">Window end</label>
            <input
              type="time"
              value={settings.window_end}
              onChange={(e) => setSettings({ ...settings, window_end: e.target.value })}
              className={inputClass}
            />
          </div>
        </div>
        <button
          onClick={saveSettings}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background"
        >
          <Save className="h-4 w-4" /> Save
        </button>
      </section>
    </div>
  );
}

// ── Collapsible variation card (non-edit view) ────────────────────────────
function VariationCard({
  v,
  clips,
  onChange,
  onStartEdit,
  onDelete,
  editingClipId,
  clipCaption,
  onStartEditClip,
  onChangeCaption,
  onSaveCaption,
  onDeleteClip,
  inputClass,
  nextClip,
}: {
  v: Variation;
  clips: Clip[];
  onChange: () => void;
  onStartEdit: (v: Variation) => void;
  onDelete: (id: number) => void;
  editingClipId: number | null;
  clipCaption: string;
  onStartEditClip: (c: Clip) => void;
  onChangeCaption: (s: string) => void;
  onSaveCaption: () => void;
  onDeleteClip: (id: number) => void;
  inputClass: string;
  nextClip?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const handles = (["tiktok", "youtube", "instagram", "facebook"] as const)
    .map((p) => {
      const h = (v as any)[`${p}_handle`] as string | undefined;
      return h ? `${p}: @${h.replace(/^@+/, "")}` : null;
    })
    .filter(Boolean);

  return (
    <div className="rounded-xl bg-muted/50 overflow-hidden">
      {/* Header — always visible */}
      <div className="flex items-center justify-between px-3 py-3">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 min-w-0 flex-1 text-left"
        >
          {open
            ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform" />
            : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform" />
          }
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium truncate">{v.name}</span>
              {v.paused_reason === "directory_exhausted" && (
                <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                  All clips posted
                </span>
              )}
              {v.paused_reason === "manual" && (
                <span className="shrink-0 rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-400">
                  Paused
                </span>
              )}
              {!v.paused_reason && nextClip && (
                <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-medium text-green-700 dark:text-green-400">
                  Next: {nextClip}
                </span>
              )}
              {!v.paused_reason && !nextClip && (
                <span className="shrink-0 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-medium text-green-700 dark:text-green-400">
                  Active
                </span>
              )}
            </div>
            {handles.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                {handles.map((h, i) => <span key={i}>{h}</span>)}
              </div>
            )}
          </div>
        </button>
        <div className="flex items-center gap-1 shrink-0 ml-2">
          <button
            onClick={async () => {
              try {
                const r = await refreshVariationProfile(v.id);
                const results = (r?.results || {}) as Record<string, { status: string; handles?: Record<string, string>; error?: string }>;
                const ok: string[] = []; const fail: string[] = [];
                for (const [p, res] of Object.entries(results)) {
                  if (res.status === "ok") ok.push(p); else fail.push(`${p}: ${res.error || "failed"}`);
                }
                if (ok.length) toast.success(`Refreshed: ${ok.join(", ")}`);
                if (fail.length) toast.error(fail.join(" · "));
                onChange();
              } catch (e: any) { toast.error(e?.response?.data?.detail || "Failed to refresh"); }
            }}
            className="text-muted-foreground hover:text-foreground p-1"
            title="Refresh handles from connected platforms"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => onStartEdit(v)} className="text-muted-foreground hover:text-foreground p-1" title="Edit variation">
            <Edit2 className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => onDelete(v.id)} className="text-muted-foreground hover:text-destructive p-1">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Collapsible body */}
      {open && (
        <div className="px-3 pb-3 border-t border-border/50 pt-3 space-y-3">
          <OAuthTiles account={v as unknown as Record<string, unknown> & { id: number }} kind="variation" onChange={onChange} />
          <VariationExtras
            v={v} clips={clips} onChange={onChange}
            editingClipId={editingClipId} clipCaption={clipCaption}
            onStartEditClip={onStartEditClip} onChangeCaption={onChangeCaption}
            onSaveCaption={onSaveCaption} onDeleteClip={onDeleteClip}
            inputClass={inputClass} nextClip={nextClip}
          />
        </div>
      )}
    </div>
  );
}

function VariationExtras({
  v,
  clips,
  onChange,
  editingClipId,
  clipCaption,
  onStartEditClip,
  onChangeCaption,
  onSaveCaption,
  onDeleteClip,
  inputClass,
  nextClip,
}: {
  v: Variation;
  clips: Clip[];
  onChange: () => void;
  editingClipId: number | null;
  clipCaption: string;
  onStartEditClip: (c: Clip) => void;
  onChangeCaption: (s: string) => void;
  onSaveCaption: () => void;
  onDeleteClip: (id: number) => void;
  inputClass: string;
  nextClip?: string | null;
}) {
  const [folder, setFolder] = useState(v.gdrive_folder_url || "");
  const [proxy, setProxy] = useState(v.proxy_url || "");
  const [syncing, setSyncing] = useState(false);
  const [savingProxy, setSavingProxy] = useState(false);
  const [clipsOpen, setClipsOpen] = useState(false);

  const onSync = async () => {
    if (!folder.trim()) return toast.error("Paste a Drive folder URL");
    setSyncing(true);
    try {
      const r = await syncVariationGdriveClips(v.id, folder.trim());
      toast.success(`Synced — ${r.added} new (${r.total} in this variation)`);
      onChange();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Drive sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const onUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    try {
      for (const f of Array.from(files)) await uploadVariationClip(v.id, f, "");
      toast.success(`Uploaded ${files.length} to ${v.name}`);
      onChange();
    } catch {
      toast.error("Upload failed");
    }
  };

  const onSaveProxy = async () => {
    setSavingProxy(true);
    try {
      // Empty string clears the proxy. The PUT endpoint persists "" as NULL via
      // the existing model_dump filter — it sends through.
      await updateArtistVariation(v.id, { proxy_url: proxy });
      toast.success(proxy ? "Proxy saved" : "Proxy cleared");
      onChange();
    } catch {
      toast.error("Could not save proxy");
    } finally {
      setSavingProxy(false);
    }
  };

  const onResume = async () => {
    try {
      await updateArtistVariation(v.id, { paused_reason: "" });
      toast.success(`${v.name} resumed`);
      onChange();
    } catch {
      toast.error("Could not resume");
    }
  };

  return (
    <div className="mt-3 space-y-2 border-t border-border pt-3">
      {v.paused_reason === "directory_exhausted" && (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <span>All clips posted — add new content</span>
          <button onClick={onResume} className="font-medium underline-offset-2 hover:underline">
            Resume
          </button>
        </div>
      )}
      {v.paused_reason === "no_clips" && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          No clips assigned to this variation and the shared pool is empty.
          Sync a Drive folder above (or upload an MP4) to give it something to post.
        </div>
      )}
      {v.paused_reason === "manual" && (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs text-blue-700 dark:text-blue-400">
          <span>Manually paused</span>
          <button onClick={onResume} className="font-medium underline-offset-2 hover:underline">
            Resume
          </button>
        </div>
      )}
      {nextClip && !v.paused_reason && (
        <div className="rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          Next post: <span className="font-medium text-foreground">{nextClip}</span>
        </div>
      )}

      <div>
        <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
          Drive folder for this variation
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="https://drive.google.com/drive/folders/..."
            className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-xs outline-none focus:border-foreground"
          />
          <div className="flex gap-2">
            <button
              onClick={onSync}
              disabled={syncing}
              className="flex-1 rounded-lg border border-border px-3 py-2 text-base sm:flex-none sm:text-xs font-medium hover:bg-muted disabled:opacity-50"
            >
              {syncing ? "Syncing…" : "Sync"}
            </button>
            <label className="flex flex-1 items-center justify-center rounded-lg border border-border px-3 py-2 text-base sm:flex-none sm:text-xs font-medium hover:bg-muted cursor-pointer">
              Upload
              <input
                type="file"
                multiple
                accept="video/mp4,video/*"
                onChange={(e) => onUpload(e.target.files)}
                className="hidden"
              />
            </label>
          </div>
        </div>
      </div>

      {/* Per-variation video directory: collapsed by default to keep the
          page short when an artist has many variations × many clips. */}
      <div>
        <button
          onClick={() => setClipsOpen((s) => !s)}
          className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
          aria-expanded={clipsOpen}
        >
          {clipsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Video directory ({clips.length} clip{clips.length === 1 ? "" : "s"})
        </button>
        {clipsOpen && (
          clips.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              No clips for this variation yet. Sync a Drive folder above or upload an MP4.
            </p>
          ) : (
            <div className="mt-2 space-y-2">
              {clips.map((c) => (
                <div key={c.id} className="rounded-lg bg-background/50 p-2 border border-border/50">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{c.filename}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {c.source} · posted {c.times_posted}×
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => onStartEditClip(c)}
                        className="text-muted-foreground hover:text-foreground p-1"
                      >
                        <Edit2 className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => onDeleteClip(c.id)}
                        className="text-muted-foreground hover:text-destructive p-1"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                  {editingClipId === c.id ? (
                    <div className="mt-2 flex gap-2">
                      <input
                        value={clipCaption}
                        onChange={(e) => onChangeCaption(e.target.value)}
                        className={inputClass}
                        placeholder="Caption to post with this clip"
                      />
                      <button
                        onClick={onSaveCaption}
                        className="rounded-lg bg-foreground px-3 py-2 text-xs text-background"
                      >
                        <Save className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    c.caption && (
                      <div className="mt-1 text-[11px] text-muted-foreground">{c.caption}</div>
                    )
                  )}
                </div>
              ))}
            </div>
          )
        )}
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
          Residential proxy URL (optional — leave empty to post direct)
        </label>
        <div className="flex gap-2">
          <input
            value={proxy}
            onChange={(e) => setProxy(e.target.value)}
            placeholder="http://user-session-abc:pass@gate.smartproxy.com:7000"
            className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-xs outline-none focus:border-foreground"
          />
          <button
            onClick={onSaveProxy}
            disabled={savingProxy}
            className="rounded-lg border border-border px-3 py-2 text-base sm:text-xs font-medium hover:bg-muted disabled:opacity-50"
          >
            {savingProxy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* TikTok posting settings — only when TikTok is connected for this
          variation. Required by TikTok's UX rules: privacy and disclosure
          must be picked per variation (no global default). The dispatcher
          refuses to fire TikTok posts until these are saved. */}
      {(v.tiktok_connected || v.tiktok_handle) && (
        <TikTokSettingsCard
          entityId={v.id}
          entityLabel={v.name || `Variation ${v.id}`}
          creatorInfoAccountId={v.id}
          creatorInfoKind="variation"
          initialValues={v}
          onSave={(payload) =>
            updateVariationTiktokSettings(v.id, payload).then(() => {
              onChange();
            })
          }
          onValidityChange={() => {
            // Clipping is unattended — there's no "Post Now" button to
            // gate. The dispatcher's pre-call guard handles invalid
            // variations by failing those clip_posts with a clear error.
            // Validity is surfaced via the in-card "needs setup" pill.
          }}
        />
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-xl bg-card p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon} {label}
      </div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

/**
 * Countdown to the next view-poll tick. The backend returns the poller's
 * interval + last/next poll ISO; we tick every second to animate.
 */
function PollCountdown({
  poll,
}: {
  poll: {
    interval_seconds: number;
    last_polled_at: string | null;
    next_poll_at: string;
  };
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const nextAt = new Date(poll.next_poll_at).getTime();
  const lastAt = poll.last_polled_at ? new Date(poll.last_polled_at).getTime() : null;
  const remaining = Math.max(0, Math.ceil((nextAt - now) / 1000));
  const pct =
    Math.min(
      100,
      Math.max(
        0,
        poll.interval_seconds > 0
          ? ((poll.interval_seconds - remaining) / poll.interval_seconds) * 100
          : 0,
      ),
    );
  const mm = Math.floor(remaining / 60);
  const ss = String(remaining % 60).padStart(2, "0");

  const lastAgo = (() => {
    if (!lastAt) return "never";
    const s = Math.max(0, Math.floor((now - lastAt) / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  })();

  return (
    <div className="rounded-xl bg-card p-3">
      <div className="flex items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <RefreshCw className="h-3.5 w-3.5" />
          <span>View poll</span>
        </div>
        <div className="flex items-center gap-3 font-medium">
          <span className="tabular-nums">
            {remaining === 0 ? "refreshing…" : `next in ${mm}:${ss}`}
          </span>
          <span className="text-muted-foreground">last: {lastAgo}</span>
        </div>
      </div>
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full bg-primary transition-[width] duration-1000 ease-linear"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
