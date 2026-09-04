"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Scissors, Trash2, Users, Film, Eye, BarChart3 } from "lucide-react";
import { toast } from "sonner";
import { getArtists, createArtist, deleteArtist } from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";

type Artist = {
  id: number;
  name: string;
  slug: string;
  timezone: string;
  posts_per_day: number;
  variations_count: number;
  clips_count: number;
  posts_count: number;
  views_total: number;
};

export default function ClippingPage() {
  const [artists, setArtists] = useState<Artist[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<{id: number; name: string} | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState({
    name: "",
    slug: "",
    timezone: "US/Eastern",
    posts_per_day: 3,
    window_start: "09:00",
    window_end: "21:00",
  });

  const load = () =>
    getArtists()
      .then(setArtists)
      .catch(() => toast.error("Failed to load artists"));

  useEffect(() => {
    load();
  }, []);

  const handleCreate = async () => {
    if (!form.name || !form.slug) return toast.error("Name and slug required");
    try {
      await createArtist(form);
      setForm({
        name: "",
        slug: "",
        timezone: "US/Eastern",
        posts_per_day: 3,
        window_start: "09:00",
        window_end: "21:00",
      });
      setShowNew(false);
      load();
      toast.success("Artist created");
    } catch {
      toast.error("Failed to create artist");
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteArtist(confirmDelete.id);
      load();
      toast.success("Artist deleted");
      setConfirmDelete(null);
    } catch {
      toast.error("Failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  const inputClass =
    "w-full rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none transition-colors focus:border-foreground placeholder:text-muted-foreground";

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 md:mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <Scissors className="h-7 w-7 shrink-0 text-foreground" strokeWidth={1.75} />
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-tight">Clipping</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Artists — each with variations, a video directory, and a dispatch schedule.
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="inline-flex min-h-[44px] w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          <Plus className="h-4 w-4" /> Add Artist
        </button>
      </div>

      {showNew && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => setShowNew(false)}
        >
          <div
            className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card p-5 md:p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="mb-5 text-lg font-semibold">New Artist</h2>
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium">Artist Name</label>
                <input
                  placeholder="e.g. DJ Neon"
                  value={form.name}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      name: e.target.value,
                      slug: e.target.value.toLowerCase().replace(/[^a-z0-9]/g, ""),
                    })
                  }
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium">Slug (URL-safe)</label>
                <input
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  className={inputClass}
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Timezone</label>
                  <input
                    value={form.timezone}
                    onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Posts per day</label>
                  <input
                    type="number"
                    min={1}
                    max={24}
                    value={form.posts_per_day}
                    onChange={(e) =>
                      setForm({ ...form, posts_per_day: parseInt(e.target.value || "3", 10) })
                    }
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Window start</label>
                  <input
                    type="time"
                    value={form.window_start}
                    onChange={(e) => setForm({ ...form, window_start: e.target.value })}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Window end</label>
                  <input
                    type="time"
                    value={form.window_end}
                    onChange={(e) => setForm({ ...form, window_end: e.target.value })}
                    className={inputClass}
                  />
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleCreate}
                  className="flex-1 min-h-[44px] rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90"
                >
                  Create Artist
                </button>
                <button
                  onClick={() => setShowNew(false)}
                  className="min-h-[44px] rounded-lg px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {artists.length === 0 ? (
        <div className="rounded-2xl bg-card p-8 text-center">
          <p className="text-muted-foreground">No artists yet.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">
            Click &quot;Add Artist&quot; to get started.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {artists.map((a) => (
            <div key={a.id} className="rounded-2xl bg-card p-4 md:p-5">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/clipping/${a.slug}`} className="group">
                  <h3 className="text-lg font-semibold group-hover:underline">{a.name}</h3>
                  <span className="inline-block mt-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                    {a.slug}
                  </span>
                </Link>
                <button
                  onClick={() => setConfirmDelete({id: a.id, name: a.name})}
                  className="text-muted-foreground hover:text-destructive p-1"
                  title="Delete artist"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Users className="h-3.5 w-3.5" /> {a.variations_count} variations
                </div>
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Film className="h-3.5 w-3.5" /> {a.clips_count} clips
                </div>
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <BarChart3 className="h-3.5 w-3.5" /> {a.posts_count} posts
                </div>
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Eye className="h-3.5 w-3.5" /> {a.views_total.toLocaleString()} views
                </div>
              </div>
              <div className="mt-4">
                <Link
                  href={`/clipping/${a.slug}`}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                >
                  Open dashboard
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(o) => { if (!o) setConfirmDelete(null); }}
        title={`Delete "${confirmDelete?.name}"?`}
        description="This will permanently delete the artist and all its clips, variations, and scheduled posts. This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
