"use client";

import { useEffect, useState } from "react";
import { Download, Eye, Trash2, Plus, CalendarOff } from "lucide-react";
import { getPosts, getBrands, getDownloadUrl, deletePost, unschedulePost } from "@/lib/api";
import { toast } from "sonner";
import Link from "next/link";
import { ConfirmModal } from "@/components/ui/confirm-modal";

export default function PostsLibraryPage() {
  const [posts, setPosts] = useState<any[]>([]);
  const [brands, setBrands] = useState<any[]>([]);
  const [filterBrand, setFilterBrand] = useState<string>("all");

  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [confirmUnschedule, setConfirmUnschedule] = useState<number | null>(null);
  const [unscheduling, setUnscheduling] = useState(false);

  useEffect(() => {
    getBrands().then(setBrands).catch(() => {});
  }, []);

  const loadPosts = () => {
    const params: any = {};
    if (filterBrand !== "all") params.brand_id = Number(filterBrand);
    getPosts(params).then(setPosts).catch(() => {});
  };

  useEffect(() => { loadPosts(); }, [filterBrand]);

  const handleDelete = async () => {
    if (confirmDelete === null) return;
    setDeleting(true);
    try {
      await deletePost(confirmDelete);
      loadPosts();
      toast.success("Post deleted");
      setConfirmDelete(null);
    } catch { toast.error("Failed to delete"); }
    finally { setDeleting(false); }
  };

  const handleUnschedule = async () => {
    if (confirmUnschedule === null) return;
    setUnscheduling(true);
    try {
      await unschedulePost(confirmUnschedule);
      loadPosts();
      toast.success("Post moved back to draft");
      setConfirmUnschedule(null);
    } catch { toast.error("Failed to unschedule"); }
    finally { setUnscheduling(false); }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 md:mb-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Posts Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">Browse and manage all your posts.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:gap-3">
          <select
            value={filterBrand}
            onChange={(e) => setFilterBrand(e.target.value)}
            className="min-h-[44px] rounded-lg border border-border bg-background px-4 py-2.5 text-base sm:text-sm outline-none focus:border-foreground"
          >
            <option value="all">All Brands</option>
            {brands.map((b: any) => (
              <option key={b.id} value={String(b.id)}>{b.name}</option>
            ))}
          </select>
          <Link href="/posts/new"
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
            <Plus className="h-4 w-4" /> New Post
          </Link>
        </div>
      </div>

      {posts.length === 0 ? (
        <div className="rounded-2xl bg-card p-8 text-center">
          <p className="text-muted-foreground">No posts yet.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">Create your first post to get started.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {posts.map((post: any) => (
            <div key={post.id} className="flex flex-col gap-3 rounded-xl bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:py-3.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 sm:gap-4">
                <span className="text-sm font-medium">Post #{post.post_number}</span>
                <span className="text-sm text-muted-foreground">{post.date}</span>
                <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize">{post.status}</span>
                <span className="text-xs text-muted-foreground">{post.slide_count} slides</span>
                {post.scheduled_time && (
                  <span className="text-xs text-muted-foreground">@ {post.scheduled_time}</span>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Link href={`/posts/new?edit=${post.id}`}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                  <Eye className="h-3 w-3" /> View
                </Link>
                <a href={getDownloadUrl(post.id)}
                  className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                  <Download className="h-3 w-3" /> Download
                </a>
                {post.status === "scheduled" && (
                  <button
                    onClick={() => setConfirmUnschedule(post.id)}
                    title="Move back to draft"
                    className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-amber-500 transition-colors"
                  >
                    <CalendarOff className="h-3.5 w-3.5" />
                  </button>
                )}
                <button onClick={() => setConfirmDelete(post.id)}
                  className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Unschedule confirmation */}
      <ConfirmModal
        open={confirmUnschedule !== null}
        onOpenChange={(o) => { if (!o) setConfirmUnschedule(null); }}
        title="Unschedule post?"
        description="This will cancel the scheduled time and move the post back to draft. All slides and generated videos are kept — you can reschedule it any time."
        confirmLabel="Unschedule"
        variant="default"
        loading={unscheduling}
        onConfirm={handleUnschedule}
      />

      {/* Delete confirmation */}
      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(o) => { if (!o) setConfirmDelete(null); }}
        title="Delete post?"
        description="This will permanently delete the post and all its slides, variations, and generated videos. This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}
