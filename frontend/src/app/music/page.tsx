"use client";

import { useEffect, useState } from "react";
import { Music, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { getMusicTracks, uploadMusicTrack, deleteMusicTrack } from "@/lib/api";

export default function MusicPage() {
  const [tracks, setTracks] = useState<any[]>([]);
  const [showUpload, setShowUpload] = useState(false);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

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

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this track?")) return;
    try { await deleteMusicTrack(id); load(); toast.success("Deleted"); }
    catch { toast.error("Failed"); }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Music Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">Royalty-free background music for your videos.</p>
        </div>
        <button
          onClick={() => setShowUpload(!showUpload)}
          className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          <Upload className="h-4 w-4" /> Upload Track
        </button>
      </div>

      {showUpload && (
        <div className="mb-6 rounded-2xl bg-card p-6">
          <h3 className="mb-4 text-base font-semibold">Upload Royalty-Free Track</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium">Track Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Chill Vibes"
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground placeholder:text-muted-foreground" />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Genre</label>
              <input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="lo-fi, upbeat, etc."
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground placeholder:text-muted-foreground" />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium">Audio File (.mp3, .wav)</label>
              <input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground file:mr-3 file:border-0 file:bg-transparent file:text-sm file:font-medium" />
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={handleUpload} disabled={uploading}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50">
              {uploading ? "Uploading..." : "Upload"}
            </button>
            <button onClick={() => setShowUpload(false)}
              className="rounded-lg px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
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
          {tracks.map((track: any) => (
            <div key={track.id} className="flex items-center justify-between rounded-xl bg-card px-5 py-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground">
                  <Music className="h-3.5 w-3.5 text-background" />
                </div>
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
              <button onClick={() => handleDelete(track.id)}
                className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-destructive transition-colors">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
