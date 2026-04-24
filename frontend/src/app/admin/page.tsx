"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  Shield, Users, FileText, Music, Layers, Save, Activity, HardDrive,
  Calendar, Key, Trash2, AlertTriangle, CheckCircle2, XCircle, Link2, Bug,
  Mic2, Scissors, Video,
} from "lucide-react";
import { toast } from "sonner";
import {
  getAdminStats, getUsers, updateUser, approveUser, deleteAdminUser, getSiteConfig, updateSiteConfig,
  getAdminBrands, deleteAdminBrand, getAdminPosts, deleteAdminPost, getAdminAccounts,
  getAdminMusic, deleteAdminMusic, getAdminSchedule, getAdminApiKeys,
  getOAuthApps, updateOAuthApp,
  getAdminArtists, deleteAdminArtist,
  getAdminErrorLogs, clearAdminErrorLogs,
  getCacheStats, clearCache,
  getBrandCacheStats, clearBrandCache,
} from "@/lib/api";

type Tab = "overview" | "users" | "brands" | "artists" | "posts" | "accounts" | "music" | "schedule" | "oauth" | "errors" | "branding";

export default function AdminPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<any>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [brands, setBrands] = useState<any[]>([]);
  const [posts, setPosts] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [music, setMusic] = useState<any[]>([]);
  const [schedule, setSchedule] = useState<any[]>([]);
  const [apiKeys, setApiKeys] = useState<any[]>([]);
  const [oauth, setOauth] = useState<any>(null);
  const [artists, setArtists] = useState<any[]>([]);
  const [siteConfig, setSiteConfig] = useState<Record<string, string>>({});

  useEffect(() => {
    if (user && user.role !== "admin") { router.push("/dashboard"); return; }
    if (!user) return;
    reloadAll();
  }, [user]);

  const reloadAll = () => {
    getAdminStats().then(setStats).catch(() => {});
    getUsers().then(setUsers).catch(() => {});
    getAdminBrands().then(setBrands).catch(() => {});
    getAdminPosts().then(setPosts).catch(() => {});
    getAdminAccounts().then(setAccounts).catch(() => {});
    getAdminMusic().then(setMusic).catch(() => {});
    getAdminSchedule().then(setSchedule).catch(() => {});
    getAdminApiKeys().then(setApiKeys).catch(() => {});
    getOAuthApps().then(setOauth).catch(() => {});
    getAdminArtists().then(setArtists).catch(() => {});
    getSiteConfig().then(setSiteConfig).catch(() => {});
  };

  if (!user || user.role !== "admin") return null;

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "users", label: "Users" },
    { id: "brands", label: "Brands" },
    { id: "artists", label: "Artists" },
    { id: "posts", label: "Posts" },
    { id: "accounts", label: "Accounts" },
    { id: "music", label: "Music" },
    { id: "schedule", label: "Schedule" },
    { id: "oauth", label: "OAuth Apps" },
    { id: "errors", label: "Errors" },
    { id: "branding", label: "Branding" },
  ];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 md:mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-foreground">
          <Shield className="h-5 w-5 text-background" />
        </div>
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Admin Command Center</h1>
          <p className="mt-1 text-sm text-muted-foreground">Full visibility across every user on the platform.</p>
        </div>
      </div>

      <div className="mb-6 flex gap-1 overflow-x-auto rounded-lg border border-border p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`min-h-[40px] whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab stats={stats} />}
      {tab === "users" && <UsersTab users={users} currentUserId={user.id} onReload={reloadAll} />}
      {tab === "brands" && <BrandsTab brands={brands} onReload={reloadAll} />}
      {tab === "artists" && <ArtistsTab artists={artists} onReload={reloadAll} />}
      {tab === "posts" && <PostsTab posts={posts} onReload={reloadAll} />}
      {tab === "accounts" && <AccountsTab accounts={accounts} />}
      {tab === "music" && <MusicTab tracks={music} onReload={reloadAll} />}
      {tab === "schedule" && <ScheduleTab items={schedule} />}
      {tab === "oauth" && <OAuthTab oauth={oauth} onReload={reloadAll} />}
      {tab === "errors" && <ErrorsTab />}
      {tab === "branding" && <BrandingTab siteConfig={siteConfig} setSiteConfig={setSiteConfig} />}
    </div>
  );
}

/* ============================================================
 * OVERVIEW — platform health + stats + 24h activity
 * ============================================================ */
function OverviewTab({ stats }: { stats: any }) {
  if (!stats) return <div className="text-sm text-muted-foreground">Loading…</div>;
  const health = stats.health || {};
  const storage = stats.storage_mb || {};
  const healthCards = [
    { label: "CPU", value: health.cpu_percent, unit: "%" },
    { label: "Memory", value: health.mem_percent, unit: "%" },
    { label: "Disk", value: health.disk_percent, unit: "%" },
  ];

  return (
    <div className="space-y-6">
      <Section title="Platform health">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {healthCards.map((h) => (
            <HealthCard key={h.label} label={h.label} value={h.value} unit={h.unit} />
          ))}
          <Card icon={HardDrive} label="Storage" value={`${storage.total ?? 0} MB`}
            hint={`uploads ${storage.uploads ?? 0} · output ${storage.output ?? 0} · music ${storage.music ?? 0}`} />
        </div>
      </Section>

      <Section title="Totals · Brands">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
          <Card icon={Users} label="Users" value={stats.total_users} />
          <Card icon={Layers} label="Brands" value={stats.total_brands} />
          <Card icon={FileText} label="Posts" value={stats.total_posts} />
          <Card icon={Music} label="Music" value={stats.total_tracks} />
          <Card icon={Link2} label="Accounts" value={stats.total_accounts} />
        </div>
      </Section>

      <Section title="Totals · Clipping">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          <Card icon={Mic2} label="Artists" value={stats.total_artists ?? 0} />
          <Card icon={Link2} label="Variations" value={stats.total_variations ?? 0} />
          <Card icon={Video} label="Clips" value={stats.total_clips ?? 0} />
          <Card icon={Scissors} label="Clip posts" value={stats.total_clip_posts ?? 0} />
        </div>
      </Section>

      <Section title="Activity">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card icon={Activity} label="Scheduled" value={stats.scheduled_posts}
            hint={stats.scheduled_posts ? "in queue" : undefined} accent={stats.scheduled_posts > 0 ? "info" : undefined} />
          <Card icon={AlertTriangle} label="Failed posts" value={stats.failed_posts}
            accent={stats.failed_posts > 0 ? "danger" : undefined} />
          <Card icon={XCircle} label="Suspended" value={stats.suspended_users}
            accent={stats.suspended_users > 0 ? "warn" : undefined} />
          <Card icon={Calendar} label="24h" value={`+${stats.new_posts_24h} posts`}
            hint={`+${stats.new_users_24h} users`} />
        </div>
      </Section>
    </div>
  );
}

function Card({ icon: Icon, label, value, hint, accent }: any) {
  const accentCls =
    accent === "danger" ? "text-destructive" :
    accent === "warn" ? "text-amber-500" :
    accent === "info" ? "text-blue-500" : "";
  return (
    <div className="rounded-2xl bg-card p-4 md:p-5">
      <div className="flex items-center gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg bg-foreground`}>
          <Icon className="h-4 w-4 text-background" />
        </div>
        <div className="min-w-0">
          <p className={`text-lg md:text-xl font-bold tracking-tight truncate ${accentCls}`}>{value ?? "—"}</p>
          <p className="text-xs text-muted-foreground truncate">{label}</p>
          {hint && <p className="text-[11px] text-muted-foreground/70 truncate">{hint}</p>}
        </div>
      </div>
    </div>
  );
}

function HealthCard({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  const pct = value ?? 0;
  const tone = pct > 85 ? "bg-destructive" : pct > 65 ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="rounded-2xl bg-card p-4 md:p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-bold tabular-nums">{value == null ? "—" : `${value}${unit}`}</p>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: any }) {
  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{title}</h2>
      {children}
    </div>
  );
}

/* ============================================================
 * USERS — with delete
 * ============================================================ */
function UsersTab({ users, currentUserId, onReload }: any) {
  const handleRole = async (id: number, role: string) => {
    try { await updateUser(id, { role }); toast.success("Role updated"); onReload(); } catch { toast.error("Failed"); }
  };
  const handleStatus = async (id: number, status: string) => {
    try { await updateUser(id, { status }); toast.success("Status updated"); onReload(); } catch { toast.error("Failed"); }
  };
  const handleApprove = async (id: number, name: string) => {
    try { await approveUser(id); toast.success(`${name} approved`); onReload(); }
    catch (e: any) { toast.error(e.response?.data?.detail || "Failed to approve"); }
  };
  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete ${name} and ALL their brands, posts, music? This cannot be undone.`)) return;
    try { await deleteAdminUser(id); toast.success("User deleted"); onReload(); }
    catch (e: any) { toast.error(e.response?.data?.detail || "Failed"); }
  };

  const pendingUsers = users.filter((u: any) => u.status === "pending");
  const otherUsers = users.filter((u: any) => u.status !== "pending");

  return (
    <div className="space-y-4">
      {pendingUsers.length > 0 && (
        <div className="rounded-2xl border-2 border-amber-400/50 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/5 p-4">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <h3 className="text-sm font-bold text-foreground">
              Pending approval ({pendingUsers.length})
            </h3>
          </div>
          <div className="space-y-2">
            {pendingUsers.map((u: any) => (
              <div key={u.id} className="flex items-center justify-between gap-3 rounded-xl bg-background p-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{u.name}</div>
                  <div className="truncate text-xs text-muted-foreground">{u.email} · signed up {new Date(u.created_at).toLocaleString()}</div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => handleApprove(u.id, u.name)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-xs font-semibold text-background hover:opacity-90">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Approve
                  </button>
                  <button onClick={() => handleDelete(u.id, u.name)} title="Reject & delete"
                    className="inline-flex min-h-[32px] min-w-[32px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-2xl bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <Th>Name</Th><Th className="hidden md:table-cell">Email</Th><Th>Role</Th><Th>Status</Th><Th className="hidden md:table-cell">Joined</Th><Th></Th>
            </tr>
          </thead>
          <tbody>
            {otherUsers.map((u: any) => (
              <tr key={u.id} className="border-b border-border/50">
                <Td>
                  <div className="font-medium">{u.name}</div>
                  <div className="text-xs text-muted-foreground md:hidden">{u.email}</div>
                </Td>
                <Td className="hidden md:table-cell text-muted-foreground">{u.email}</Td>
                <Td>
                  <select value={u.role} onChange={(e) => handleRole(u.id, e.target.value)} disabled={u.id === currentUserId}
                    className="rounded-md border border-border bg-background px-2 py-1 text-base sm:text-xs">
                    <option value="user">User</option><option value="admin">Admin</option>
                  </select>
                </Td>
                <Td>
                  <select value={u.status} onChange={(e) => handleStatus(u.id, e.target.value)} disabled={u.id === currentUserId}
                    className="rounded-md border border-border bg-background px-2 py-1 text-base sm:text-xs">
                    <option value="active">Active</option><option value="suspended">Suspended</option>
                  </select>
                </Td>
                <Td className="hidden md:table-cell text-muted-foreground">{new Date(u.created_at).toLocaleDateString()}</Td>
                <Td>
                  {u.id !== currentUserId && (
                    <button onClick={() => handleDelete(u.id, u.name)} title="Delete user"
                      className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ============================================================
 * BRANDS / POSTS / ACCOUNTS / MUSIC / SCHEDULE
 * ============================================================ */
function BrandsTab({ brands, onReload }: any) {
  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete brand "${name}" and all its posts + accounts?`)) return;
    try { await deleteAdminBrand(id); toast.success("Brand deleted"); onReload(); }
    catch { toast.error("Failed"); }
  };
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <Th>Name</Th><Th>Owner</Th><Th className="hidden md:table-cell">Accounts</Th><Th className="hidden md:table-cell">Posts</Th><Th></Th>
          </tr>
        </thead>
        <tbody>
          {brands.map((b: any) => (
            <tr key={b.id} className="border-b border-border/50">
              <Td><div className="font-medium">{b.name}</div><div className="text-xs text-muted-foreground">/{b.slug}</div></Td>
              <Td>{b.user_name || "—"}<div className="text-xs text-muted-foreground hidden md:block">{b.user_email}</div></Td>
              <Td className="hidden md:table-cell">{b.account_count}</Td>
              <Td className="hidden md:table-cell">{b.post_count}</Td>
              <Td>
                <button onClick={() => handleDelete(b.id, b.name)}
                  className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArtistsTab({ artists, onReload }: any) {
  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete artist "${name}" and all variations, clips, and scheduled posts?`)) return;
    try { await deleteAdminArtist(id); toast.success("Artist deleted"); onReload(); }
    catch { toast.error("Failed"); }
  };
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <Th>Name</Th><Th>Owner</Th>
            <Th className="hidden md:table-cell">Variations</Th>
            <Th className="hidden md:table-cell">Clips</Th>
            <Th className="hidden md:table-cell">Posts</Th>
            <Th className="hidden md:table-cell">Views</Th>
            <Th></Th>
          </tr>
        </thead>
        <tbody>
          {artists.map((a: any) => (
            <tr key={a.id} className="border-b border-border/50">
              <Td><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground">/{a.slug}</div></Td>
              <Td>{a.user_name || "—"}<div className="text-xs text-muted-foreground hidden md:block">{a.user_email}</div></Td>
              <Td className="hidden md:table-cell">{a.variations_count ?? 0}</Td>
              <Td className="hidden md:table-cell">{a.clips_count ?? 0}</Td>
              <Td className="hidden md:table-cell">{a.posts_count ?? 0}</Td>
              <Td className="hidden md:table-cell">{(a.views_total ?? 0).toLocaleString()}</Td>
              <Td>
                <button onClick={() => handleDelete(a.id, a.name)}
                  className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PostsTab({ posts, onReload }: any) {
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const filtered = filterStatus === "all" ? posts : posts.filter((p: any) => p.status === filterStatus);
  const handleDelete = async (id: number) => {
    if (!confirm("Delete this post and all its slides/variations/outputs?")) return;
    try { await deleteAdminPost(id); toast.success("Post deleted"); onReload(); }
    catch { toast.error("Failed"); }
  };
  return (
    <div className="space-y-3">
      <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
        className="min-h-[44px] rounded-lg border border-border bg-background px-4 text-base sm:text-sm">
        <option value="all">All statuses</option>
        {["draft", "scheduled", "generating", "posting", "posted", "failed"].map(s => <option key={s}>{s}</option>)}
      </select>
      <div className="overflow-x-auto rounded-2xl bg-card">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left">
            <Th>Post</Th><Th>Brand</Th><Th>Owner</Th><Th>Status</Th><Th className="hidden md:table-cell">Date</Th><Th></Th>
          </tr></thead>
          <tbody>
            {filtered.map((p: any) => (
              <tr key={p.id} className="border-b border-border/50">
                <Td>#{p.post_number}</Td>
                <Td>{p.brand_name}</Td>
                <Td className="text-muted-foreground">{p.user_name || "—"}</Td>
                <Td><span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize">{p.status}</span></Td>
                <Td className="hidden md:table-cell text-muted-foreground">{p.date}</Td>
                <Td>
                  <button onClick={() => handleDelete(p.id)}
                    className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AccountsTab({ accounts }: any) {
  const platforms = ["tiktok", "youtube", "instagram", "facebook"] as const;
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left">
          <Th>Account</Th><Th>Brand</Th><Th>Owner</Th><Th>Connections</Th>
        </tr></thead>
        <tbody>
          {accounts.map((a: any) => (
            <tr key={a.id} className="border-b border-border/50">
              <Td><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground capitalize">{a.role}</div></Td>
              <Td>{a.brand_name}</Td>
              <Td className="text-muted-foreground">{a.user_name || "—"}</Td>
              <Td>
                <div className="flex flex-wrap gap-1.5">
                  {platforms.map((p) => {
                    const connected = !!a[`${p}_token`];
                    return (
                      <span key={p} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${connected ? "border-green-500/40 text-green-500" : "border-border text-muted-foreground"}`}>
                        {connected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />} {p}
                      </span>
                    );
                  })}
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MusicTab({ tracks, onReload }: any) {
  const handleDelete = async (id: number) => {
    if (!confirm("Delete this track?")) return;
    try { await deleteAdminMusic(id); toast.success("Deleted"); onReload(); }
    catch { toast.error("Failed"); }
  };
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left">
          <Th>Track</Th><Th>Owner</Th><Th className="hidden md:table-cell">Genre</Th><Th></Th>
        </tr></thead>
        <tbody>
          {tracks.map((t: any) => (
            <tr key={t.id} className="border-b border-border/50">
              <Td className="font-medium">{t.name}</Td>
              <Td>{t.user_name || "—"}</Td>
              <Td className="hidden md:table-cell text-muted-foreground">{t.genre || ""}</Td>
              <Td>
                <button onClick={() => handleDelete(t.id)}
                  className="inline-flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-destructive">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScheduleTab({ items }: any) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left">
          <Th>Date</Th><Th>Time</Th><Th>Post</Th><Th>Brand</Th><Th>Owner</Th><Th>Status</Th>
        </tr></thead>
        <tbody>
          {items.map((s: any) => (
            <tr key={s.id} className="border-b border-border/50">
              <Td>{s.date}</Td><Td>{s.scheduled_time || "—"}</Td>
              <Td>#{s.post_number}</Td><Td>{s.brand_name}</Td>
              <Td className="text-muted-foreground">{s.user_name || "—"}</Td>
              <Td><span className="rounded-full bg-muted px-2 py-0.5 text-[11px] capitalize">{s.status}</span></Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ============================================================
 * OAUTH APPS
 * ============================================================ */
function OAuthTab({ oauth, onReload }: any) {
  const [redirectBase, setRedirectBase] = useState("");
  useEffect(() => { if (oauth?.redirect_base) setRedirectBase(oauth.redirect_base); }, [oauth]);

  if (!oauth) return <div className="text-sm text-muted-foreground">Loading…</div>;

  const saveBase = async () => {
    try { await updateOAuthApp("_base", { redirect_base: redirectBase }); toast.success("Saved"); onReload(); }
    catch { toast.error("Failed"); }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-card p-4 md:p-6">
        <h3 className="mb-2 text-base font-semibold">Redirect base URL</h3>
        <p className="mb-3 text-xs text-muted-foreground">Used to build each platform callback URL. Set this once. e.g. <code>https://icreateflow.com</code></p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input value={redirectBase} onChange={(e) => setRedirectBase(e.target.value)}
            placeholder="https://icreateflow.com"
            className="min-h-[44px] flex-1 rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
          <button onClick={saveBase} className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background">
            <Save className="h-4 w-4" /> Save
          </button>
        </div>
      </div>
      {["tiktok", "youtube", "meta"].map((p) => <OAuthCard key={p} platform={p} data={oauth[p]} redirectBase={redirectBase} tiktokPrivacy={oauth.tiktok_privacy_level} onReload={onReload} />)}
      <GoogleDriveCard data={oauth.google_drive} onReload={onReload} />
    </div>
  );
}

function GoogleDriveCard({ data, onReload }: any) {
  const [apiKey, setApiKey] = useState("");
  const save = async () => {
    if (!apiKey) { toast.error("Enter an API key"); return; }
    try { await updateOAuthApp("google_drive", { api_key: apiKey }); toast.success("Google Drive key saved"); setApiKey(""); onReload(); }
    catch { toast.error("Failed"); }
  };
  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold">Google Drive</h3>
        <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${data?.configured ? "border-green-500/40 text-green-500" : "border-border text-muted-foreground"}`}>
          {data?.configured ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
          {data?.configured ? "Configured" : "Not configured"}
        </span>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">Server-side API key with Drive API enabled. Used to mirror public Drive folders into an artist&apos;s clip directory — shared across all users.</p>
      <div>
        <label className="mb-1 block text-xs text-muted-foreground">API Key {data?.api_key_preview && <span className="ml-1 text-muted-foreground/70">({data.api_key_preview})</span>}</label>
        <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
          placeholder={data?.api_key_preview ? "leave blank to keep existing" : "AIza..."}
          className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
      </div>
      <button onClick={save} className="mt-3 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background">
        <Save className="h-4 w-4" /> Save Google Drive
      </button>
    </div>
  );
}

function OAuthCard({ platform, data, redirectBase, tiktokPrivacy, onReload }: any) {
  const [clientId, setClientId] = useState(data?.client_id || "");
  const [clientSecret, setClientSecret] = useState("");
  const [privacy, setPrivacy] = useState(tiktokPrivacy || "SELF_ONLY");
  useEffect(() => { setClientId(data?.client_id || ""); }, [data]);
  useEffect(() => { if (tiktokPrivacy) setPrivacy(tiktokPrivacy); }, [tiktokPrivacy]);

  const save = async () => {
    const payload: any = { client_id: clientId };
    if (clientSecret) payload.client_secret = clientSecret;
    if (platform === "tiktok") payload.tiktok_privacy_level = privacy;
    try { await updateOAuthApp(platform, payload); toast.success(`${platform} saved`); setClientSecret(""); onReload(); }
    catch { toast.error("Failed"); }
  };

  const callback = redirectBase ? `${redirectBase.replace(/\/$/, "")}/api/oauth/${platform}/callback` : "(set redirect base first)";
  const metaHint = platform === "meta" ? "Single app grants both Instagram Business + Facebook Page access" : "";

  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold capitalize">{platform}</h3>
        <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${data?.configured ? "border-green-500/40 text-green-500" : "border-border text-muted-foreground"}`}>
          {data?.configured ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
          {data?.configured ? "Configured" : "Not configured"}
        </span>
      </div>
      {metaHint && <p className="mb-3 text-xs text-muted-foreground">{metaHint}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">Client ID</label>
          <input value={clientId} onChange={(e) => setClientId(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">Client Secret {data?.client_secret_preview && <span className="ml-1 text-muted-foreground/70">({data.client_secret_preview})</span>}</label>
          <input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)}
            placeholder={data?.client_secret_preview ? "leave blank to keep existing" : ""}
            className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
        </div>
      </div>
      <div className="mt-3">
        <label className="mb-1 block text-xs text-muted-foreground">Redirect URI (paste this into the {platform} developer console)</label>
        <code className="block break-all rounded-lg border border-border bg-background px-3 py-2 text-xs">{callback}</code>
      </div>
      {platform === "tiktok" && (
        <div className="mt-3">
          <label className="mb-1 block text-xs text-muted-foreground">
            Default privacy level — unaudited apps must use SELF_ONLY. Switch to PUBLIC_TO_EVERYONE after TikTok approves your app.
          </label>
          <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 text-base sm:text-sm">
            <option value="SELF_ONLY">SELF_ONLY (private — required while unaudited)</option>
            <option value="MUTUAL_FOLLOW_FRIENDS">MUTUAL_FOLLOW_FRIENDS</option>
            <option value="FOLLOWER_OF_CREATOR">FOLLOWER_OF_CREATOR</option>
            <option value="PUBLIC_TO_EVERYONE">PUBLIC_TO_EVERYONE (requires audited app)</option>
          </select>
        </div>
      )}
      <button onClick={save} className="mt-3 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background">
        <Save className="h-4 w-4" /> Save {platform}
      </button>
    </div>
  );
}

/* ============================================================
 * BRANDING
 * ============================================================ */
function BrandingTab({ siteConfig, setSiteConfig }: any) {
  const diversifyOn = !["0", "false", "False", ""].includes(siteConfig.clip_diversification_enabled ?? "1");
  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Site Branding</h2>
        <label className="mb-1.5 block text-sm font-medium">Site Name</label>
        <div className="flex gap-2">
          <input value={siteConfig.site_name || ""}
            onChange={(e) => setSiteConfig((s: any) => ({ ...s, site_name: e.target.value }))}
            className="min-h-[44px] flex-1 rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
          <button
            onClick={async () => { try { await updateSiteConfig("site_name", siteConfig.site_name || ""); toast.success("Saved"); } catch { toast.error("Failed"); } }}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-foreground px-4 text-background">
            <Save className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-2 text-base font-semibold">Clipping — Per-variation video diversification</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Re-encodes each clip with imperceptible video/audio changes per (clip, variation, platform) so the same clip posted across variations looks different to platform reuse detection. Turn off to post raw clips.
        </p>
        <label className="inline-flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={diversifyOn}
            onChange={async (e) => {
              const v = e.target.checked ? "1" : "0";
              setSiteConfig((s: any) => ({ ...s, clip_diversification_enabled: v }));
              try { await updateSiteConfig("clip_diversification_enabled", v); toast.success(e.target.checked ? "Diversification enabled" : "Diversification disabled"); }
              catch { toast.error("Failed to save"); }
            }}
            className="h-4 w-4"
          />
          <span className="text-sm font-medium">{diversifyOn ? "Enabled" : "Disabled"}</span>
        </label>
      </div>

      <CaptionVariantToggle siteConfig={siteConfig} setSiteConfig={setSiteConfig} />
      <PollIntervalCard siteConfig={siteConfig} setSiteConfig={setSiteConfig} />
      <CacheCleanupCard />
      <BrandCacheCleanupCard />
    </div>
  );
}

function PollIntervalCard({ siteConfig, setSiteConfig }: any) {
  const options = [
    { value: "60",   label: "1 minute" },
    { value: "120",  label: "2 minutes" },
    { value: "300",  label: "5 minutes (default)" },
    { value: "600",  label: "10 minutes" },
    { value: "900",  label: "15 minutes" },
    { value: "1800", label: "30 minutes" },
    { value: "3600", label: "1 hour" },
  ];
  const current = String(siteConfig.view_poll_interval_seconds ?? "300");
  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <h2 className="mb-2 text-base font-semibold">View poll cadence</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        How often the backend refreshes view counts for posted clips across TikTok & YouTube.
        Changes take effect on the next poll cycle — no restart needed.
      </p>
      <select
        value={current}
        onChange={async (e) => {
          const v = e.target.value;
          setSiteConfig((s: any) => ({ ...s, view_poll_interval_seconds: v }));
          try {
            await updateSiteConfig("view_poll_interval_seconds", v);
            toast.success("Poll cadence saved");
          } catch {
            toast.error("Failed to save");
          }
        }}
        className="min-h-[44px] w-full max-w-xs rounded-lg border border-border bg-background px-3 text-sm"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

function BrandCacheCleanupCard() {
  const [stats, setStats] = useState<any>(null);
  const [target, setTarget] = useState<"output" | "uploads" | "all">("output");
  const [date, setDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  });
  const [busy, setBusy] = useState(false);

  const load = () => { getBrandCacheStats().then(setStats).catch(() => setStats(null)); };
  useEffect(() => { load(); }, []);

  const fmtBytes = (n: number) => {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0; let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  };
  const fmtDate = (s?: string) => s ? new Date(s).toLocaleString() : "—";

  const run = async (wipeAll: boolean) => {
    const labels: Record<string, string> = {
      output: "generated post renders (output/)",
      uploads: "uploaded source slides (uploads/) — DESTRUCTIVE, breaks regenerate",
      all: "both output/ and uploads/",
    };
    const cutoff = wipeAll ? undefined : date;
    const scope = wipeAll
      ? `ALL ${labels[target]}`
      : `${labels[target]} older than ${cutoff}`;
    const confirmMsg = target === "uploads" || (target === "all" && wipeAll)
      ? `⚠ ${scope}\n\nThis deletes user-uploaded slide images. Posts you haven't regenerated will be unrecoverable.\n\nProceed?`
      : `Delete ${scope}? This cannot be undone.`;
    if (!confirm(confirmMsg)) return;
    setBusy(true);
    try {
      const r = await clearBrandCache(target, cutoff);
      toast.success(
        `Output: ${r.output_dirs_deleted} dirs (${fmtBytes(r.output_bytes_freed)}) · Uploads: ${r.uploads_files_deleted} files (${fmtBytes(r.uploads_bytes_freed)})`
      );
      load();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to clear brand cache");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <h2 className="mb-2 text-base font-semibold">Brands — Post artifacts cleanup</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        <strong>output/</strong> holds generated slides + videos per (brand, date, account, post). Safe to wipe — regenerating a post recreates everything. <strong>uploads/</strong> holds the original user-uploaded slide images — deleting them means the post can no longer be regenerated. Both trees are already auto-cleaned when the individual post or brand is deleted; this card lets you prune old entries in bulk.
      </p>

      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Generated renders (output/)</div>
          <div className="mt-1 text-sm font-semibold">
            {stats ? `${stats.output.count} files · ${fmtBytes(stats.output.bytes)}` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            oldest date segment: {stats?.output.oldest_date_segment || "—"}
          </div>
        </div>
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Uploaded sources (uploads/)</div>
          <div className="mt-1 text-sm font-semibold">
            {stats ? `${stats.uploads.count} files · ${fmtBytes(stats.uploads.bytes)}` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">oldest file: {stats ? fmtDate(stats.uploads.oldest_mtime) : "…"}</div>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium">Target</label>
          <select value={target} onChange={(e) => setTarget(e.target.value as any)}
            className="w-full min-h-[44px] rounded-lg border border-border bg-background px-3 text-base sm:text-sm">
            <option value="output">Generated renders only (safe)</option>
            <option value="uploads">Uploaded sources only (destructive)</option>
            <option value="all">Both (destructive)</option>
          </select>
        </div>
        <div className="w-full sm:w-48">
          <label className="mb-1 block text-xs font-medium">Older than (date)</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="w-full min-h-[44px] rounded-lg border border-border bg-background px-3 text-base sm:text-sm" />
          <div className="mt-1 text-[10px] text-muted-foreground">
            output/: matches YYYY-MM-DD path segment · uploads/: file mtime
          </div>
        </div>
        <div className="flex gap-2">
          <button disabled={busy} onClick={() => run(false)}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-border px-4 text-xs font-medium hover:bg-muted disabled:opacity-50">
            {busy ? "…" : "Clear older"}
          </button>
          <button disabled={busy} onClick={() => run(true)}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg bg-destructive px-4 text-xs font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-50">
            {busy ? "…" : "Wipe all"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CacheCleanupCard() {
  const [stats, setStats] = useState<any>(null);
  const [target, setTarget] = useState<"video_renders" | "caption_variants" | "all">("all");
  const [days, setDays] = useState<string>("30");
  const [busy, setBusy] = useState(false);

  const load = () => { getCacheStats().then(setStats).catch(() => setStats(null)); };
  useEffect(() => { load(); }, []);

  const fmtBytes = (n: number) => {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0; let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
  };
  const fmtDate = (s?: string) => s ? new Date(s).toLocaleString() : "—";

  const run = async (wipeAll: boolean) => {
    const labels: Record<string, string> = {
      video_renders: "diversified video renders",
      caption_variants: "caption variants",
      all: "all caches",
    };
    const olderDays = wipeAll ? undefined : Math.max(0, parseInt(days || "0", 10));
    const scope = wipeAll ? `ALL ${labels[target]}` : `${labels[target]} older than ${olderDays} days`;
    if (!confirm(`Delete ${scope}? This cannot be undone.`)) return;
    setBusy(true);
    try {
      const r = await clearCache(target, wipeAll ? undefined : olderDays);
      toast.success(`Deleted ${r.video_renders_deleted} files · ${r.caption_variants_deleted} rows`);
      load();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to clear cache");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <h2 className="mb-2 text-base font-semibold">Clipping — Cache cleanup</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        The diversified video renders and paraphrased captions are cached so re-posts are deterministic. They aren&apos;t auto-expired — delete old entries here to reclaim disk / DB space. FK cascades already clean these up when a clip or variation is deleted.
      </p>

      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Video renders</div>
          <div className="mt-1 text-sm font-semibold">
            {stats ? `${stats.video_renders.count} files · ${fmtBytes(stats.video_renders.bytes)}` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            last render: {stats ? fmtDate(stats.video_renders.newest) : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            oldest on disk: {stats ? fmtDate(stats.video_renders.oldest) : "…"}
          </div>
        </div>
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Caption variants</div>
          <div className="mt-1 text-sm font-semibold">
            {stats ? `${stats.caption_variants.count} rows` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">oldest: {stats ? fmtDate(stats.caption_variants.oldest) : "…"}</div>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium">Target</label>
          <select value={target} onChange={(e) => setTarget(e.target.value as any)}
            className="w-full min-h-[44px] rounded-lg border border-border bg-background px-3 text-base sm:text-sm">
            <option value="all">All (renders + captions)</option>
            <option value="video_renders">Video renders only</option>
            <option value="caption_variants">Caption variants only</option>
          </select>
        </div>
        <div className="w-full sm:w-40">
          <label className="mb-1 block text-xs font-medium">Older than (days)</label>
          <input type="number" min={0} value={days} onChange={(e) => setDays(e.target.value)}
            className="w-full min-h-[44px] rounded-lg border border-border bg-background px-3 text-base sm:text-sm" />
        </div>
        <div className="flex gap-2">
          <button disabled={busy} onClick={() => run(false)}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-border px-4 text-xs font-medium hover:bg-muted disabled:opacity-50">
            {busy ? "…" : "Clear older"}
          </button>
          <button disabled={busy} onClick={() => run(true)}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg bg-destructive px-4 text-xs font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-50">
            {busy ? "…" : "Wipe all"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CaptionVariantToggle({ siteConfig, setSiteConfig }: any) {
  const on = !["0", "false", "False", ""].includes(siteConfig.clip_caption_variants_enabled ?? "1");
  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <h2 className="mb-2 text-base font-semibold">Clipping — Per-variation caption paraphrasing</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        Uses Claude to rewrite each clip's caption per (clip, variation, platform) so the text fingerprint differs across accounts. Results are cached, so each combo generates once and re-uses the same paraphrase. Requires an Anthropic API key in Settings. Turn off to post the raw caption.
      </p>
      <label className="inline-flex items-center gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={on}
          onChange={async (e) => {
            const v = e.target.checked ? "1" : "0";
            setSiteConfig((s: any) => ({ ...s, clip_caption_variants_enabled: v }));
            try { await updateSiteConfig("clip_caption_variants_enabled", v); toast.success(e.target.checked ? "Caption variants enabled" : "Caption variants disabled"); }
            catch { toast.error("Failed to save"); }
          }}
          className="h-4 w-4"
        />
        <span className="text-sm font-medium">{on ? "Enabled" : "Disabled"}</span>
      </label>
    </div>
  );
}

/* ============================================================
 * Small table helpers
 * ============================================================ */
function Th({ children, className = "" }: any) {
  return <th className={`px-4 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground sm:px-5 ${className}`}>{children}</th>;
}
function Td({ children, className = "" }: any) {
  return <td className={`px-4 py-3 sm:px-5 ${className}`}>{children}</td>;
}

/* ============================================================
 * ERRORS — site-wide error log viewer
 * ============================================================ */
function ErrorsTab() {
  const [logs, setLogs] = useState<any[]>([]);
  const [source, setSource] = useState<string>("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    getAdminErrorLogs({ limit: 500, source: source || undefined })
      .then(setLogs)
      .catch(() => toast.error("Failed to load errors"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const handleClear = async () => {
    if (!confirm("Delete ALL error logs? This cannot be undone.")) return;
    try {
      await clearAdminErrorLogs();
      toast.success("Cleared");
      load();
    } catch {
      toast.error("Failed to clear");
    }
  };

  const sources = Array.from(new Set(logs.map((l) => l.source))).sort();

  return (
    <div className="rounded-2xl bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 md:p-5">
        <div className="flex items-center gap-2">
          <Bug className="h-4 w-4" />
          <h2 className="text-base font-semibold">Error log</h2>
          <span className="text-xs text-muted-foreground">({logs.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs outline-none focus:border-foreground"
          >
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            onClick={load}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Refresh
          </button>
          <button
            onClick={handleClear}
            className="inline-flex items-center gap-1 rounded-lg border border-red-500/40 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-500/10"
          >
            <Trash2 className="h-3 w-3" /> Clear all
          </button>
        </div>
      </div>
      {loading ? (
        <div className="p-6 text-sm text-muted-foreground">Loading…</div>
      ) : logs.length === 0 ? (
        <div className="p-6 text-sm text-muted-foreground">No errors recorded.</div>
      ) : (
        <div className="divide-y divide-border">
          {logs.map((l) => (
            <div key={l.id} className="p-4 md:p-5">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span className="rounded-md bg-red-500/10 px-1.5 py-0.5 font-medium text-red-600">
                  {l.level}
                </span>
                <span className="font-mono">{l.source}</span>
                <span>·</span>
                <span>{new Date(l.created_at).toLocaleString()}</span>
                {l.user_id && (
                  <>
                    <span>·</span>
                    <span>user #{l.user_id}</span>
                  </>
                )}
              </div>
              <div className="mt-1 text-sm break-words">{l.message}</div>
              {l.traceback && (
                <div className="mt-2">
                  <button
                    onClick={() => setExpanded(expanded === l.id ? null : l.id)}
                    className="text-[11px] text-muted-foreground hover:text-foreground underline"
                  >
                    {expanded === l.id ? "Hide" : "Show"} traceback
                  </button>
                  {expanded === l.id && (
                    <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-muted p-3 text-[11px] text-foreground whitespace-pre-wrap break-all">
                      {l.traceback}
                    </pre>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
