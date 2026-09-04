"use client";

import { useEffect, useState } from "react";
import { Music, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { getMusicTracks, uploadMusicTrack, updateMusicTrack, deleteMusicTrack } from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";

const PLATFORMS: { key: string; label: string }[] = [
  { key: "youtube", label: "YouTube" },
  { key: "instagram", label: "Instagram" },
  { key: "facebook", label: "Facebook" },
];

export default function MusicPage() {
  const [tracks, setTracks] = useState<any[]>([]);
  const [showUpload, setShowUpload] = useState(false);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () => getMusicTracks().then(setTracks).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleUpload = async () => {
    if (!name || !file) return toast.error("Name and file required");
    setUploading(true);
    try {
      await uploadMusicTrack(name, genre, file);
      setName(""); setGenre(""); setFile(null); setShowUpload(false);
      load();
      toast.success("Track uploaded");
    } catch { toast.error("Upload failed"); }
    finally { setUploading(false); }
  };

  const handleDelete = async () => {
    if (confirmDelete === null) return;
    setDeleting(true);
    try { await deleteMusicTrack(confirmDelete); load(); toast.success("Deleted"); setConfirmDelete(null); }
    catch { toast.error("Failed"); }
    finally { setDeleting(false); }
  };

  const togglePlatform = async (track: any, platform: string) => {
    const current = new Set(
      (track.platforms_allowed || "").split(",").map((s: string) => s.trim()).filter(Boolean),
    );
    if (current.has(platform)) current.delete(platform);
    else current.add(platform);
    const csv = Array.from(current).join(",");
    // Optimistic update
    setTracks((prev) => prev.map((t) => (t.id === track.id ? { ...t, platforms_allowed: csv } : t)));
    try { await updateMusicTrack(track.id, { platforms_allowed: csv }); }
    catch { toast.error("Failed to update platforms"); load(); }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 md:mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Music Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">Royalty-free background music for your videos.</p>
        </div>
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          <Upload className="h-4 w-4" /> Upload Track
        </button>
      </div>

      {showUpload && (
        <div className="mb-6 rounded-2xl bg-card p-4 md:p-6">
          <h3 className="mb-4 text-base font-semibold">Upload Royalty-Free Track</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="mb-1.5 block text-sm font-medium">Track Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Chill Vibes"
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground placeholder:text-muted-foreground" />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Genre</label>
              <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="lo-fi, upbeat, etc."
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground placeholder:text-muted-foreground" />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Audio File (.mp3, .wav)</label>
              <input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium" />
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <button onClick={handleUpload} disabled={uploading}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
              {uploading ? "Uploading..." : "Upload"}
            </button>
            <button onClick={() => setShowUpload(false)}
              className="min-h-[44px] rounded-lg px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
              Cancel
            </button>
          </div>
        </div>
      )}

      {tracks.length === 0 ? (
        <div className="rounded-2xl bg-card p-8 text-center">
          <p className="text-muted-foreground">No tracks yet.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">Upload royalty-free background music for your videos.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {tracks.map((track: any) => {
            const allowed = new Set(
              (track.platforms_allowed || "").split(",").map((s: string) => s.trim()).filter(Boolean),
            );
            return (
              <div key={track.id} className="flex flex-col gap-3 rounded-xl bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:py-3.5">
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <Music className="h-5 w-5 shrink-0 text-foreground" strokeWidth={1.75} />
                  <span className="text-sm font-medium">{track.name}</span>
                  {track.genre && (
                    <span className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">{track.genre}</span>
                  )}
                  {track.is_custom && (
                    <span className="rounded-md bg-foreground/10 px-2 py-0.5 text-[11px] font-medium">custom</span>
                  )}
                  {track.duration && (
                    <span className="text-xs text-muted-foreground">{Math.round(track.duration)}s</span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                  <div className="flex items-center gap-1 rounded-lg border border-border p-1">
                    {PLATFORMS.map((p) => {
                      const on = allowed.has(p.key);
                      return (
                        <button
                          key={p.key}
                          onClick={() => togglePlatform(track, p.key)}
                          title={`${on ? "Cleared for" : "Not cleared for"} ${p.label}`}
                          className={
                            "rounded-md px-2 py-1 text-[11px] font-medium transition-colors " +
                            (on ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted")
                          }
                        >
                          {p.label}
                        </button>
                      );
                    })}
                  </div>
                  <button onClick={() => setConfirmDelete(track.id)}
                    className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-destructive transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(o) => { if (!o) setConfirmDelete(null); }}
        title="Delete track?"
        description="This will permanently delete the music track."
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
