"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  Shield, Users, FileText, Music, Layers, Save, Activity, HardDrive,
  Calendar, Key, Trash2, AlertTriangle, CheckCircle2, XCircle, Link2, Bug,
  Mic2, Scissors, Video, Mail, Eye, EyeOff, Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ui/confirm-modal";
import {
  getAdminStats, getUsers, updateUser, approveUser, deleteAdminUser, getSiteConfig, updateSiteConfig,
  getAdminBrands, deleteAdminBrand, getAdminPosts, deleteAdminPost, getAdminAccounts,
  getAdminMusic, deleteAdminMusic, getAdminSchedule, getAdminApiKeys,
  getOAuthApps, updateOAuthApp,
  getAdminArtists, deleteAdminArtist,
  getAdminErrorLogs, clearAdminErrorLogs,
  clearAdminAudioToVideo,
  getCacheStats, clearCache,
  getBrandCacheStats, clearBrandCache,
  sendTestEmail,
  uploadAsset,
  getOutreachSettings, updateOutreachSettings,
} from "@/lib/api";

type Tab = "overview" | "users" | "brands" | "artists" | "posts" | "accounts" | "music" | "schedule" | "oauth" | "errors" | "branding" | "email" | "outreach";

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
    { id: "email", label: "Email / SMTP" },
    { id: "outreach", label: "Outreach" },
  ];

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 md:mb-8 flex items-center gap-3">
        <Shield className="h-7 w-7 shrink-0 text-foreground" strokeWidth={1.75} />
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
      {tab === "email" && <EmailTab siteConfig={siteConfig} setSiteConfig={setSiteConfig} adminEmail={user?.email} />}
      {tab === "outreach" && <OutreachTab />}
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
        <Icon className="h-6 w-6 shrink-0 text-foreground" strokeWidth={1.75} />
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
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
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
  const handleDelete = (id: number, name: string) => {
    setConfirm({ title: "Delete user", description: `Delete ${name} and ALL their brands, posts, music? This cannot be undone.`, onConfirm: async () => { try { await deleteAdminUser(id); toast.success("User deleted"); onReload(); } catch (e: any) { toast.error(e.response?.data?.detail || "Failed"); } } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

/* ============================================================
 * BRANDS / POSTS / ACCOUNTS / MUSIC / SCHEDULE
 * ============================================================ */
function BrandsTab({ brands, onReload }: any) {
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const handleDelete = (id: number, name: string) => {
    setConfirm({ title: "Delete brand", description: `Delete brand "${name}" and all its posts + accounts? This cannot be undone.`, onConfirm: async () => { try { await deleteAdminBrand(id); toast.success("Brand deleted"); onReload(); } catch { toast.error("Failed"); } } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

function ArtistsTab({ artists, onReload }: any) {
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const handleDelete = (id: number, name: string) => {
    setConfirm({ title: "Delete artist", description: `Delete artist "${name}" and all variations, clips, and scheduled posts? This cannot be undone.`, onConfirm: async () => { try { await deleteAdminArtist(id); toast.success("Artist deleted"); onReload(); } catch { toast.error("Failed"); } } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

function PostsTab({ posts, onReload }: any) {
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const filtered = filterStatus === "all" ? posts : posts.filter((p: any) => p.status === filterStatus);
  const handleDelete = (id: number) => {
    setConfirm({ title: "Delete post", description: "Delete this post and all its slides, variations, and outputs? This cannot be undone.", onConfirm: async () => { try { await deleteAdminPost(id); toast.success("Post deleted"); onReload(); } catch { toast.error("Failed"); } } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
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
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const handleDelete = (id: number) => {
    setConfirm({ title: "Delete track", description: "Delete this music track? This cannot be undone.", onConfirm: async () => { try { await deleteAdminMusic(id); toast.success("Deleted"); onReload(); } catch { toast.error("Failed"); } } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
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
      {["tiktok", "youtube", "meta", "instagram"].map((p) => <OAuthCard key={p} platform={p} data={oauth[p]} redirectBase={redirectBase} onReload={onReload} />)}
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

function OAuthCard({ platform, data, redirectBase, onReload }: any) {
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const [clientId, setClientId] = useState(data?.client_id || "");
  const [clientSecret, setClientSecret] = useState("");
  // IG-only: verify_token used by Facebook's webhook subscription handshake.
  // Stored in full (not masked) on the GET because the admin needs to copy
  // it into the developer console UI.
  const [webhookToken, setWebhookToken] = useState<string>(data?.webhook_verify_token || "");
  useEffect(() => { setClientId(data?.client_id || ""); }, [data]);
  useEffect(() => { setWebhookToken(data?.webhook_verify_token || ""); }, [data]);

  const save = async () => {
    const payload: any = { client_id: clientId };
    if (clientSecret) payload.client_secret = clientSecret;
    if (platform === "instagram") payload.webhook_verify_token = webhookToken;
    try {
      await updateOAuthApp(platform, payload);
      toast.success(`${platform} saved`);
      setClientSecret("");
      onReload();
    } catch (e: any) { toast.error(e?.response?.data?.detail || "Failed"); }
  };

  const generateWebhookToken = () => {
    // 32 hex chars from crypto.getRandomValues — long enough that brute
    // force is hopeless, short enough to paste into Facebook's UI.
    const buf = new Uint8Array(16);
    crypto.getRandomValues(buf);
    const tok = Array.from(buf).map((b) => b.toString(16).padStart(2, "0")).join("");
    setWebhookToken(tok);
  };

  const copy = async (text: string, label: string) => {
    try { await navigator.clipboard.writeText(text); toast.success(`${label} copied`); }
    catch { toast.error("Copy failed"); }
  };

  const clearAll = () => {
    setConfirm({ title: `Clear ${platform} credentials`, description: `Clear ${platform} Client ID and Secret? Users won't be able to connect ${platform} until you set them again.`, onConfirm: async () => { try { await updateOAuthApp(platform, { client_id: "", client_secret: "" }); setClientId(""); setClientSecret(""); toast.success(`${platform} credentials cleared`); onReload(); } catch { toast.error("Failed to clear"); } } });
  };

  const callback = redirectBase ? `${redirectBase.replace(/\/$/, "")}/api/oauth/${platform}/callback` : "(set redirect base first)";
  const metaHint =
    platform === "meta"
      ? "Facebook Login app — grants Facebook Pages + linked Instagram Business in one flow."
      : platform === "instagram"
      ? "Standalone Instagram Login app — for users who don't link Instagram to a Facebook Page."
      : "";

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
      {platform === "instagram" && (
        <div className="mt-3 rounded-xl border border-border bg-muted/30 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-xs font-semibold">Webhook subscription</h4>
            <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] ${webhookToken ? "border-green-500/40 text-green-500" : "border-border text-muted-foreground"}`}>
              {webhookToken ? "Ready" : "Not set"}
            </span>
          </div>
          <p className="mb-2 text-[11px] text-muted-foreground">
            Facebook calls our callback URL with <code>?hub.mode=subscribe&hub.verify_token=…</code> to verify webhook subscriptions. Set a token here, copy it into the developer console&apos;s &quot;Verify token&quot; field, then save the webhook config.
          </p>
          <label className="mb-1 block text-xs text-muted-foreground">Verify token</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={webhookToken}
              onChange={(e) => setWebhookToken(e.target.value)}
              placeholder="click Generate or paste your own"
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-xs outline-none focus:border-foreground"
            />
            <button
              type="button"
              onClick={generateWebhookToken}
              className="rounded-lg border border-border px-3 py-2 text-base sm:text-xs font-medium hover:bg-muted"
            >
              Generate
            </button>
            {webhookToken && (
              <button
                type="button"
                onClick={() => copy(webhookToken, "Verify token")}
                className="rounded-lg border border-border px-3 py-2 text-base sm:text-xs font-medium hover:bg-muted"
              >
                Copy
              </button>
            )}
          </div>
          <label className="mt-3 mb-1 block text-xs text-muted-foreground">Webhook callback URL (same as redirect URI)</label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <code className="min-w-0 flex-1 break-all rounded-lg border border-border bg-background px-3 py-2 text-xs">{callback}</code>
            <button
              type="button"
              onClick={() => copy(callback, "Callback URL")}
              className="rounded-lg border border-border px-3 py-2 text-base sm:text-xs font-medium hover:bg-muted"
            >
              Copy
            </button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Don&apos;t forget to click <span className="font-medium">Save instagram</span> below after changing the verify token.
          </p>
        </div>
      )}
      {/* TikTok privacy used to live here as a global default. TikTok's
          UX rules require the user to manually pick privacy on every
          flow with no default value, so the setting moved per-(post,
          variation) on the Brand Generate tab and per-variation on the
          Clipping dashboard. The admin tile is intentionally gone. */}
      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={save} className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 text-sm font-medium text-background">
          <Save className="h-4 w-4" /> Save {platform}
        </button>
        {(data?.configured || data?.client_id || data?.client_secret_preview) && (
          <button
            onClick={clearAll}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-destructive/40 px-4 text-sm font-medium text-destructive hover:bg-destructive/10"
          >
            Clear credentials
          </button>
        )}
      </div>
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

/* ============================================================
 * BRANDING
 * ============================================================ */
function BrandingTab({ siteConfig, setSiteConfig }: any) {
  const [uploading, setUploading] = useState<Record<string, boolean>>({});

  const saveCfg = async (key: string, value: string) => {
    try { await updateSiteConfig(key, value); toast.success("Saved"); }
    catch { toast.error("Failed"); }
  };

  const handleUpload = async (type: "logo" | "favicon", file: File) => {
    setUploading((u) => ({ ...u, [type]: true }));
    try {
      const { url } = await uploadAsset(type, file);
      const key = type === "logo" ? "site_logo_url" : "site_favicon_url";
      setSiteConfig((s: any) => ({ ...s, [key]: url }));
      toast.success(`${type === "logo" ? "Logo" : "Favicon"} uploaded`);
    } catch {
      toast.error("Upload failed");
    } finally {
      setUploading((u) => ({ ...u, [type]: false }));
    }
  };

  const AssetUpload = ({ type, label }: { type: "logo" | "favicon"; label: string }) => {
    const key = type === "logo" ? "site_logo_url" : "site_favicon_url";
    const currentUrl = siteConfig[key] || "";
    return (
      <div className="mb-5">
        <label className="mb-2 block text-sm font-medium">{label}</label>
        <div className="flex items-center gap-4">
          {currentUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={currentUrl} alt={label} className="h-12 w-auto max-w-[120px] rounded-lg object-contain border border-border bg-muted p-1" />
          ) : (
            <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-dashed border-border bg-muted text-muted-foreground text-xs">
              None
            </div>
          )}
          <label className={`inline-flex min-h-[40px] cursor-pointer items-center gap-2 rounded-lg border border-border bg-background px-4 text-sm font-medium transition-colors hover:bg-muted ${uploading[type] ? "opacity-50 pointer-events-none" : ""}`}>
            {uploading[type] ? <span className="animate-spin">⏳</span> : <Save className="h-4 w-4" />}
            {uploading[type] ? "Uploading…" : "Upload image"}
            <input
              type="file"
              accept="image/*"
              className="sr-only"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(type, f); }}
            />
          </label>
          {currentUrl && (
            <button onClick={() => { setSiteConfig((s: any) => ({ ...s, [key]: "" })); saveCfg(key, ""); }}
              className="text-xs text-muted-foreground hover:text-destructive">
              Remove
            </button>
          )}
        </div>
        {currentUrl && <p className="mt-1.5 text-xs text-muted-foreground truncate max-w-sm">{currentUrl}</p>}
      </div>
    );
  };

  const cfgField = (key: string, label: string, placeholder?: string) => (
    <div className="mb-4">
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        <input value={siteConfig[key] || ""}
          onChange={(e) => setSiteConfig((s: any) => ({ ...s, [key]: e.target.value }))}
          placeholder={placeholder}
          className="min-h-[44px] flex-1 rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
        <button onClick={() => saveCfg(key, siteConfig[key] || "")}
          className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-foreground px-4 text-background">
          <Save className="h-4 w-4" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-card p-4 md:p-6">
        <h2 className="mb-5 text-base font-semibold">Site Branding</h2>
        {cfgField("site_name", "Site Name")}
        <AssetUpload type="logo" label="Logo" />
        <AssetUpload type="favicon" label="Favicon" />
      </div>

      <PollIntervalCard siteConfig={siteConfig} setSiteConfig={setSiteConfig} />
      <CacheCleanupCard />
      <BrandCacheCleanupCard />
      <AudioToVideoStorageCard />
    </div>
  );
}

function AudioToVideoStorageCard() {
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const run = (scope: "videos" | "backgrounds" | "covers" | "all", title: string, description: string) => {
    setConfirm({
      title,
      description,
      onConfirm: async () => {
        setBusy((b) => ({ ...b, [scope]: true }));
        try {
          const r = await clearAdminAudioToVideo(scope);
          toast.success(`Cleared — ${r.deleted_files} file(s) deleted`);
        } catch {
          toast.error("Failed to clear");
        } finally {
          setBusy((b) => ({ ...b, [scope]: false }));
        }
      },
    });
  };

  const rows: { scope: "videos" | "backgrounds" | "covers"; icon: any; label: string; sub: string; desc: string }[] = [
    {
      scope: "videos",
      icon: Video,
      label: "Clip videos",
      sub: "uploads/*/audio/video/ · output/*/audio_clips/",
      desc: "Deletes all uploaded and exported clip MP4/WebM files and clears the audio_video_clips database records. Artists will need to re-record and re-assign their clips.",
    },
    {
      scope: "backgrounds",
      icon: Layers,
      label: "Background images",
      sub: "uploads/*/audio/bg/",
      desc: "Deletes all uploaded background images used on clip overlays. Artists will need to re-upload backgrounds. Does not affect clips or DB records.",
    },
    {
      scope: "covers",
      icon: Music,
      label: "Cover art",
      sub: "uploads/*/audio/cover/",
      desc: "Deletes all uploaded album cover art images. Artists will need to re-upload covers. Does not affect clips or DB records.",
    },
  ];

  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <div className="mb-1 flex items-center gap-2">
        <Scissors className="h-4 w-4" />
        <h2 className="text-base font-semibold">Audio-to-Video — Storage cleanup</h2>
      </div>
      <p className="mb-5 text-xs text-muted-foreground">
        Free up disk space by removing uploaded clip files, background images, or cover art. Each action is irreversible — artists will need to re-upload deleted assets.
      </p>

      <div className="space-y-3">
        {rows.map(({ scope, icon: Icon, label, sub, desc }) => (
          <div key={scope} className="rounded-xl border border-border p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{label}</p>
                  <p className="text-[11px] font-mono text-muted-foreground/70 truncate">{sub}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
                </div>
              </div>
              <button
                disabled={!!busy[scope]}
                onClick={() =>
                  run(
                    scope,
                    `Clear ${label.toLowerCase()}?`,
                    `${desc}\n\nThis cannot be undone.`
                  )
                }
                className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
              >
                {busy[scope] ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                Clear
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-destructive">Clear everything</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Removes all clip videos, background images, and cover art in one action. Also clears all audio_video_clips DB records. This wipes the slate clean for all artists on the platform.
            </p>
          </div>
          <button
            disabled={!!busy["all"]}
            onClick={() =>
              run(
                "all",
                "Clear ALL audio-to-video storage?",
                "This will delete ALL clip videos, background images, and cover art across every artist, and clear all DB records.\n\nThis cannot be undone."
              )
            }
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:opacity-90 transition-colors disabled:opacity-50"
          >
            {busy["all"] ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            Wipe all
          </button>
        </div>
      </div>

      {confirm && (
        <ConfirmModal
          open
          onOpenChange={(o) => !o && setConfirm(null)}
          variant="danger"
          title={confirm.title}
          description={confirm.description}
          onConfirm={confirm.onConfirm}
        />
      )}
    </div>
  );
}

function EmailTab({ siteConfig, setSiteConfig, adminEmail }: any) {
  const [showPassword, setShowPassword] = useState(false);
  const [testingEmail, setTestingEmail] = useState(false);

  const saveCfg = async (key: string, value: string) => {
    try { await updateSiteConfig(key, value); toast.success("Saved"); }
    catch { toast.error("Failed"); }
  };

  const smtpField = (key: string, label: string, type = "text", placeholder?: string) => (
    <div className="mb-4">
      <label className="mb-1.5 block text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        {type === "password" ? (
          <div className="relative flex-1">
            <input
              type={showPassword ? "text" : "password"}
              value={siteConfig[key] || ""}
              onChange={(e) => setSiteConfig((s: any) => ({ ...s, [key]: e.target.value }))}
              placeholder={placeholder}
              className="min-h-[44px] w-full rounded-lg border border-border bg-background px-4 pr-10 text-base sm:text-sm"
            />
            <button type="button" onClick={() => setShowPassword((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground">
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        ) : (
          <input type={type} value={siteConfig[key] || ""}
            onChange={(e) => setSiteConfig((s: any) => ({ ...s, [key]: e.target.value }))}
            placeholder={placeholder}
            className="min-h-[44px] flex-1 rounded-lg border border-border bg-background px-4 text-base sm:text-sm" />
        )}
        <button onClick={() => saveCfg(key, siteConfig[key] || "")}
          className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-foreground px-4 text-background">
          <Save className="h-4 w-4" />
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-card p-4 md:p-6">
        <div className="mb-5 flex items-center gap-2">
          <Mail className="h-5 w-5" />
          <h2 className="text-base font-semibold">SMTP Email Configuration</h2>
        </div>
        <p className="mb-5 text-sm text-muted-foreground">
          Configure SMTP to enable email notifications, password resets, and OTP codes.
          Leave <strong>SMTP Host</strong> empty to disable all email sending.
        </p>
        {smtpField("smtp_host", "SMTP Host", "text", "smtp.gmail.com")}
        {smtpField("smtp_port", "SMTP Port", "number", "587")}
        {smtpField("smtp_user", "SMTP Username / Email", "email")}
        {smtpField("smtp_password", "SMTP Password", "password")}
        {smtpField("smtp_from_email", "From Email Address", "email", "noreply@yourdomain.com")}
        {smtpField("smtp_from_name", "From Name", "text", "iCreateFlow")}

        <div className="mt-2 border-t border-border pt-4">
          <p className="mb-3 text-xs text-muted-foreground">
            Send a test email to <strong>{adminEmail}</strong> to verify your SMTP settings.
          </p>
          <button
            onClick={async () => {
              setTestingEmail(true);
              try {
                await sendTestEmail();
                toast.success("Test email sent — check your inbox");
              } catch (e: any) {
                toast.error(e?.response?.data?.detail || "Failed to send test email");
              } finally { setTestingEmail(false); }
            }}
            disabled={testingEmail}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-border px-5 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
          >
            <Mail className="h-4 w-4" />
            {testingEmail ? "Sending…" : "Send Test Email"}
          </button>
        </div>
      </div>
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
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
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
    setConfirm({ title: wipeAll ? "Wipe all brand artifacts" : "Clear brand cache", description: confirmMsg, onConfirm: async () => {
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
    } });
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

function CacheCleanupCard() {
  const [confirm, setConfirm] = useState<{ title: string; description: string; onConfirm: () => void } | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [target, setTarget] = useState<"video_renders" | "caption_variants" | "passthrough_clips" | "all">("all");
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
      passthrough_clips: "passthrough clip downloads",
      all: "all caches",
    };
    const olderDays = wipeAll ? undefined : Math.max(0, parseInt(days || "0", 10));
    const scope = wipeAll ? `ALL ${labels[target]}` : `${labels[target]} older than ${olderDays} days`;
    setConfirm({ title: wipeAll ? "Wipe all cache" : "Clear cache", description: `Delete ${scope}? This cannot be undone.`, onConfirm: async () => {
      setBusy(true);
      try {
        const r = await clearCache(target, wipeAll ? undefined : olderDays);
        toast.success(`Deleted ${r.video_renders_deleted ?? 0} renders · ${r.passthrough_clips_deleted ?? 0} passthrough · ${r.caption_variants_deleted ?? 0} captions`);
        load();
      } catch (e: any) {
        toast.error(e?.response?.data?.detail || "Failed to clear cache");
      } finally {
        setBusy(false);
      }
    } });
  };

  return (
    <div className="rounded-2xl bg-card p-4 md:p-6">
      <h2 className="mb-2 text-base font-semibold">Clipping — Cache cleanup</h2>
      <p className="mb-4 text-xs text-muted-foreground">
        The diversified video renders, paraphrased captions, and passthrough clip downloads are cached so re-posts are deterministic and don&apos;t re-fetch the source from Google Drive every time. The scheduler also runs a nightly TTL sweep (default 30 days, configurable via <code>cache_ttl_days</code>). Use the controls below to clear manually.
      </p>

      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Video renders</div>
          <div className="mt-1 text-sm font-semibold">
            {stats ? `${stats.video_renders.count} files · ${fmtBytes(stats.video_renders.bytes)}` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            last run: {stats ? fmtDate(stats.video_renders.last_run) : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            newest on disk: {stats ? fmtDate(stats.video_renders.newest) : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            oldest on disk: {stats ? fmtDate(stats.video_renders.oldest) : "…"}
          </div>
        </div>
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">Passthrough clips</div>
          <div className="mt-1 text-sm font-semibold">
            {stats?.passthrough_clips ? `${stats.passthrough_clips.count} files · ${fmtBytes(stats.passthrough_clips.bytes)}` : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            newest on disk: {stats?.passthrough_clips ? fmtDate(stats.passthrough_clips.newest) : "…"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            oldest on disk: {stats?.passthrough_clips ? fmtDate(stats.passthrough_clips.oldest) : "…"}
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
            <option value="all">All (renders + passthrough + captions)</option>
            <option value="video_renders">Video renders only</option>
            <option value="passthrough_clips">Passthrough clips only</option>
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
      {confirm && <ConfirmModal open onOpenChange={(o) => !o && setConfirm(null)} variant="danger" title={confirm.title} description={confirm.description} onConfirm={confirm.onConfirm} />}
    </div>
  );
}

// Diversification, caption-variants, and catch-up toggles moved to user
// settings (/settings) so each user controls their own posting behaviour.

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
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

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
    setClearing(true);
    try {
      await clearAdminErrorLogs();
      toast.success("Cleared");
      setConfirmClear(false);
      load();
    } catch {
      toast.error("Failed to clear");
    } finally {
      setClearing(false);
    }
  };

  const sources = Array.from(new Set(logs.map((l) => l.source))).sort();

  return (
    <>
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
            onClick={() => setConfirmClear(true)}
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
    <ConfirmModal
      open={confirmClear}
      onOpenChange={setConfirmClear}
      title="Clear all error logs?"
      description="This will permanently delete all error log entries. This cannot be undone."
      confirmLabel="Clear all"
      variant="danger"
      loading={clearing}
      onConfirm={handleClear}
    />
    </>
  );
}


/* ============================================================
 * OUTREACH — worker limits, driver, and the global kill switch
 * ============================================================ */
type OutreachSettings = {
  values: Record<string, string | number | boolean>;
  spec: Record<string, { default: number; min: number; max: number }>;
  drivers: string[];
  max_sending_accounts: number;
};

function OutreachTab() {
  const [settings, setSettings] = useState<OutreachSettings | null>(null);
  const [values, setValues] = useState<Record<string, string | number | boolean>>({});
  const [saving, setSaving] = useState(false);

  const load = () =>
    getOutreachSettings()
      .then((s: OutreachSettings) => {
        setSettings(s);
        setValues(s.values);
      })
      .catch(() => toast.error("Failed to load outreach settings"));

  useEffect(() => {
    load();
  }, []);

  const save = async (patch: Record<string, string | number | boolean>) => {
    setSaving(true);
    try {
      const result = await updateOutreachSettings(patch);
      setValues(result.values);
      toast.success("Outreach settings saved");
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const workersOn = values.outreach_workers_enabled !== false;

  const LABELS: Record<string, string> = {
    outreach_max_jobs_per_campaign: "Maximum jobs per campaign",
    outreach_max_jobs_per_account: "Maximum jobs per account (per campaign)",
    outreach_retry_limit: "Retry limit",
    outreach_worker_concurrency: "Worker concurrency",
    outreach_account_error_threshold: "Errors before an account auto-pauses",
    outreach_job_lease_seconds: "Job lease (seconds)",
    outreach_retry_backoff_seconds: "Retry backoff (seconds)",
    outreach_min_send_interval_seconds: "Minimum gap between sends, per account (seconds)",
    outreach_worker_idle_seconds: "Worker idle poll (seconds)",
  };

  return (
    <div className="space-y-6">
      <Section title="Workers">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium">
                {workersOn ? "Workers are running" : "All workers stopped"}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Stopping workers leaves every campaign and job exactly where it is —
                nothing is cancelled, and sending resumes when you switch this back on.
              </p>
            </div>
            <button
              onClick={() => save({ outreach_workers_enabled: !workersOn })}
              disabled={saving}
              className={`min-h-[44px] whitespace-nowrap rounded-lg px-5 text-sm font-medium transition-opacity hover:opacity-90 disabled:opacity-50 ${
                workersOn ? "bg-destructive text-white" : "bg-foreground text-background"
              }`}
            >
              {workersOn ? "Stop all workers" : "Start workers"}
            </button>
          </div>
        </div>
      </Section>

      <Section title="Sending mode">
        <div className="rounded-xl border border-border bg-card p-5">
          <select
            value={String(values.outreach_driver ?? "mock") === "mock" ? "mock" : "auto"}
            onChange={(e) => save({ outreach_driver: e.target.value })}
            disabled={saving}
            className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
          >
            <option value="auto">Send for real</option>
            <option value="mock">Rehearse — contacts nothing</option>
          </select>
          <p className="mt-2 text-sm text-muted-foreground">
            Rehearsing runs campaigns end to end — queue, retries, accounts, reporting —
            without contacting any platform. Sending for real routes each job by its
            account&apos;s platform, so TikTok and Instagram campaigns can run at the same
            time in the same worker.
          </p>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Advanced: pin one driver
            </summary>
            <select
              value={String(values.outreach_driver ?? "mock")}
              onChange={(e) => save({ outreach_driver: e.target.value })}
              disabled={saving}
              className="mt-2 w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
            >
              <option value="auto">auto — route by platform</option>
              {settings.drivers.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <p className="mt-2 text-xs text-muted-foreground">
              Only for debugging one platform. Naming a single browser driver here does
              not force it: apart from <code>mock</code>, jobs are still routed by their
              account&apos;s platform, because a TikTok selector table finds nothing on an
              Instagram profile.
            </p>
          </details>
        </div>
      </Section>

      <Section title="Limits">
        <div className="grid gap-4 rounded-xl border border-border bg-card p-5 sm:grid-cols-2">
          {Object.keys(settings.spec).map((key) => (
            <div key={key}>
              <label className="mb-1.5 block text-sm font-medium">
                {LABELS[key] ?? key}
              </label>
              <input
                type="number"
                min={settings.spec[key].min}
                max={settings.spec[key].max}
                value={String(values[key] ?? settings.spec[key].default)}
                onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                onBlur={(e) => {
                  const next = Number(e.target.value);
                  if (Number.isFinite(next) && next !== settings.values[key]) {
                    save({ [key]: next });
                  }
                }}
                className="w-full rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                default {settings.spec[key].default} · range {settings.spec[key].min}–
                {settings.spec[key].max}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Campaigns can override the first three per campaign; these are the defaults.
          A change takes effect on each worker&apos;s next job — no restart needed.
        </p>
      </Section>
    </div>
  );
}
