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
} from "lucide-react";
import { toast } from "sonner";
import OAuthTiles from "@/components/OAuthTiles";
import {
  getArtistBySlug,
  updateArtist,
  createVariation,
  updateArtistVariation,
  deleteArtistVariation,
  uploadClip,
  syncGdriveClips,
  updateClip,
  deleteClip,
  getArtistDashboard,
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
};

const PLATFORMS = ["tiktok", "youtube", "instagram", "facebook"] as const;

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

  const [editingClipId, setEditingClipId] = useState<number | null>(null);
  const [clipCaption, setClipCaption] = useState("");

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
        getArtistDashboard(a.id).then(setDashboard).catch(() => {});
      })
      .catch(() => toast.error("Failed to load artist"));
  }, [slug]);

  useEffect(() => {
    load();
    const iv = setInterval(() => {
      if (id != null) getArtistDashboard(id).then(setDashboard).catch(() => {});
    }, 60000);
    return () => clearInterval(iv);
  }, [id, load]);

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
                ? new Date(dashboard.next_scheduled_at).toLocaleString()
                : "—"
            }
          />
        </div>
      )}

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

      {/* Variations */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Users className="h-4 w-4" /> Variations ({variations.length})
          </h2>
          <button
            onClick={() => setShowNewVariation(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>

        {showNewVariation && (
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

        {variations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No variations yet.</p>
        ) : (
          <div className="space-y-3">
            {variations.map((v) => (
              <div key={v.id} className="rounded-xl bg-muted/50 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{v.name}</span>
                  <button
                    onClick={() => handleDeleteVariation(v.id)}
                    className="text-muted-foreground hover:text-destructive p-1"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <OAuthTiles account={v as unknown as Record<string, unknown> & { id: number }} kind="variation" onChange={load} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Clips */}
      <section className="rounded-2xl bg-card p-4 md:p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Film className="h-4 w-4" /> Video directory ({clips.length})
          </h2>
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
        </div>

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
