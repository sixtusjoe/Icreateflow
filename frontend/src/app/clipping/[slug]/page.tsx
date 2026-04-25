"use client";

import { use, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Trash2,
  Edit2,
  Upload,
  Link2 as LinkIcon,
  Film,
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
import {
  getArtistBySlug,
  updateArtist,
  createVariation,
  updateArtistVariation,
  deleteArtistVariation,
  refreshVariationProfile,
  uploadClip,
  syncGdriveClips,
  updateClip,
  deleteClip,
  getArtistDashboard,
  startPromotion,
  stopPromotion,
  togglePausePromotion,
  resetPromotion,
  listCampaigns,
  downloadStatsCsv,
} from "@/lib/api";

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
};

type Clip = {
  id: number;
  source: "upload" | "gdrive";
  filename: string;
  caption?: string;
  times_posted: number;
  local_path?: string;
  gdrive_file_id?: string;
};

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

  const [showNewVariation, setShowNewVariation] = useState(false);
  const [newVar, setNewVar] = useState({
    name: "",
    tiktok_handle: "",
    youtube_handle: "",
    instagram_handle: "",
    facebook_handle: "",
  });
  const [gdriveUrl, setGdriveUrl] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [variationsOpen, setVariationsOpen] = useState(true);
  const [clipsOpen, setClipsOpen] = useState(true);

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
        setGdriveUrl(a.gdrive_folder_url || "");
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
    if (!confirm("Stop the current promotion?")) return;
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
    if (
      !confirm(
        "Reset the directory? All uploaded clips will be deleted and the current campaign archived. Historical stats remain downloadable."
      )
    )
      return;
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
    if (!confirm("Delete this variation?")) return;
    try {
      await deleteArtistVariation(vid);
      load();
      toast.success("Variation deleted");
    } catch {
      toast.error("Failed to delete");
    }
  };

  const handleUpload = async (files: FileList | null) => {
    if (id == null) return;
    if (!files || files.length === 0) return;
    try {
      for (const f of Array.from(files)) {
        await uploadClip(id, f, "");
      }
      toast.success(`Uploaded ${files.length} clip${files.length === 1 ? "" : "s"}`);
      load();
    } catch {
      toast.error("Upload failed");
    }
  };

  const handleGdriveSync = async () => {
    if (id == null) return;
    if (!gdriveUrl.trim()) return toast.error("Paste a Drive folder URL");
    setSyncing(true);
    try {
      const res = await syncGdriveClips(id, gdriveUrl.trim());
      toast.success(`Synced — ${res.added} new clip${res.added === 1 ? "" : "s"} (total ${res.total})`);
      load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "Drive sync failed");
    } finally {
      setSyncing(false);
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
    if (!confirm("Delete this clip?")) return;
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
                // target_reached and directory_exhausted are auto states — no manual toggle.
                const clickable = !reason || reason === "manual";
                const title = !clickable
                  ? undefined
                  : isPaused
                  ? "Click to resume"
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
                onClick={handleStopPromotion}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5" /> Stop
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
                onClick={handleResetPromotion}
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
                <div key={v.id} className="rounded-xl bg-muted/50 p-3">
                  <div className="flex items-center justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium break-all">{v.name}</div>
                      {(() => {
                        const handles = (["tiktok", "youtube", "instagram", "facebook"] as const)
                          .map((p) => {
                            const h = (v as any)[`${p}_handle`] as string | undefined;
                            return h ? `${p}: @${h.replace(/^@+/, "")}` : null;
                          })
                          .filter(Boolean);
                        return handles.length > 0 ? (
                          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                            {handles.map((h, i) => <span key={i}>{h}</span>)}
                          </div>
                        ) : null;
                      })()}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={async () => {
                          try {
                            const r = await refreshVariationProfile(v.id);
                            const results = (r?.results || {}) as Record<string, { status: string; handles?: Record<string, string>; error?: string }>;
                            const ok: string[] = [];
                            const fail: string[] = [];
                            for (const [p, res] of Object.entries(results)) {
                              if (res.status === "ok") ok.push(p);
                              else fail.push(`${p}: ${res.error || "failed"}`);
                            }
                            if (ok.length) toast.success(`Refreshed: ${ok.join(", ")}`);
                            if (fail.length) toast.error(fail.join(" · "));
                            load();
                          } catch (e: any) {
                            toast.error(e?.response?.data?.detail || "Failed to refresh");
                          }
                        }}
                        className="text-muted-foreground hover:text-foreground p-1"
                        title="Refresh handles from connected platforms"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => startEditVariation(v)}
                        className="text-muted-foreground hover:text-foreground p-1"
                        title="Edit variation"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => handleDeleteVariation(v.id)}
                        className="text-muted-foreground hover:text-destructive p-1"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                  <OAuthTiles account={v as unknown as Record<string, unknown> & { id: number }} kind="variation" onChange={load} />
                </div>
              )
            ))}
          </div>
        ))}
      </section>

      {/* Clips */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <div className={clipsOpen ? "mb-4 flex items-center justify-between" : "flex items-center justify-between"}>
          <button
            onClick={() => setClipsOpen((v) => !v)}
            className="flex items-center gap-2 text-base font-semibold hover:opacity-80"
            aria-expanded={clipsOpen}
          >
            {clipsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <Film className="h-4 w-4" /> Video directory ({clips.length})
          </button>
          {clipsOpen && (
            <label className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted cursor-pointer">
              <Upload className="h-3 w-3" /> Upload MP4
              <input
                type="file"
                multiple
                accept="video/mp4,video/*"
                onChange={(e) => handleUpload(e.target.files)}
                className="hidden"
              />
            </label>
          )}
        </div>

        {clipsOpen && (<>
        <div className="mb-4 flex flex-col gap-2 sm:flex-row">
          <input
            value={gdriveUrl}
            onChange={(e) => setGdriveUrl(e.target.value)}
            className={inputClass}
            placeholder="Public Google Drive folder URL"
          />
          <button
            onClick={handleGdriveSync}
            disabled={syncing}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background disabled:opacity-50"
          >
            <LinkIcon className="h-4 w-4" /> {syncing ? "Syncing…" : "Sync Drive"}
          </button>
        </div>

        {clips.length === 0 ? (
          <p className="text-sm text-muted-foreground">No clips yet. Upload MP4s or sync a Drive folder.</p>
        ) : (
          <div className="space-y-2">
            {clips.map((c) => (
              <div key={c.id} className="rounded-xl bg-muted/50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{c.filename}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {c.source} · posted {c.times_posted}×
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => startEditClip(c)}
                      className="text-muted-foreground hover:text-foreground p-1"
                    >
                      <Edit2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => handleDeleteClip(c.id)}
                      className="text-muted-foreground hover:text-destructive p-1"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                {editingClipId === c.id ? (
                  <div className="mt-2 flex gap-2">
                    <input
                      value={clipCaption}
                      onChange={(e) => setClipCaption(e.target.value)}
                      className={inputClass}
                      placeholder="Caption to post with this clip"
                    />
                    <button
                      onClick={saveClipCaption}
                      className="rounded-lg bg-foreground px-3 py-2 text-xs text-background"
                    >
                      <Save className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  c.caption && (
                    <div className="mt-1 text-xs text-muted-foreground">{c.caption}</div>
                  )
                )}
              </div>
            ))}
          </div>
        )}
        </>)}
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
