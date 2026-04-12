"use client";

import { useEffect, useState } from "react";
import { Download, Eye, Trash2, Plus } from "lucide-react";
import { getPosts, getBrands, getDownloadUrl, deletePost } from "@/lib/api";
import { toast } from "sonner";
import Link from "next/link";

export default function PostsLibraryPage() {
  const [posts, setPosts] = useState<any[]>([]);
  const [brands, setBrands] = useState<any[]>([]);
  const [filterBrand, setFilterBrand] = useState<string>("all");

  useEffect(() => {
    getBrands().then(setBrands).catch(() => {});
  }, []);

  const loadPosts = () => {
    const params: any = {};
    if (filterBrand !== "all") params.brand_id = Number(filterBrand);
    getPosts(params).then(setPosts).catch(() => {});
  };

  useEffect(() => { loadPosts(); }, [filterBrand]);

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this post and all its data?")) return;
    try {
      await deletePost(id);
      loadPosts();
      toast.success("Post deleted");
    } catch { toast.error("Failed to delete"); }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Posts Library</h1>
          <p className="mt-1 text-sm text-muted-foreground">Browse and manage all your posts.</p>
        </div>
        <div className="flex gap-3">
          <select
            value={filterBrand}
            onChange={(e) => setFilterBrand(e.target.value)}
            className="rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
          >
            <option value="all">All Brands</option>
            {brands.map((b: any) => (
              <option key={b.id} value={String(b.id)}>{b.name}</option>
            ))}
          </select>
          <Link href="/posts/new"
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90">
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
            <div key={post.id} className="flex items-center justify-between rounded-xl bg-card px-5 py-3.5">
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium">Post #{post.post_number}</span>
                <span className="text-sm text-muted-foreground">{post.date}</span>
                <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize">{post.status}</span>
                <span className="text-xs text-muted-foreground">{post.slide_count} slides</span>
                {post.scheduled_time && (
                  <span className="text-xs text-muted-foreground">@ {post.scheduled_time}</span>
                )}
              </div>
              <div className="flex gap-1.5">
                <Link href={`/posts/new?edit=${post.id}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                  <Eye className="h-3 w-3" /> View
                </Link>
                <a href={getDownloadUrl(post.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted">
                  <Download className="h-3 w-3" /> Download
                </a>
                <button onClick={() => handleDelete(post.id)}
                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
