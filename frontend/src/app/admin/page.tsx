"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  Shield, Users, FileText, Music, Layers, Save, Activity, HardDrive,
  Calendar, Key, Trash2, AlertTriangle, CheckCircle2, XCircle, Link2, Bug,
} from "lucide-react";
import { toast } from "sonner";
import {
  getAdminStats, getUsers, updateUser, deleteAdminUser, getSiteConfig, updateSiteConfig,
  getAdminBrands, deleteAdminBrand, getAdminPosts, deleteAdminPost, getAdminAccounts,
  getAdminMusic, deleteAdminMusic, getAdminSchedule, getAdminApiKeys,
  getOAuthApps, updateOAuthApp,
  getAdminArtists, deleteAdminArtist,
  getAdminErrorLogs, clearAdminErrorLogs,
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

      <Section title="Totals">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
          <Card icon={Users} label="Users" value={stats.total_users} />
          <Card icon={Layers} label="Brands" value={stats.total_brands} />
          <Card icon={FileText} label="Posts" value={stats.total_posts} />
          <Card icon={Music} label="Music" value={stats.total_tracks} />
          <Card icon={Link2} label="Accounts" value={stats.total_accounts} />
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
  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete ${name} and ALL their brands, posts, music? This cannot be undone.`)) return;
    try { await deleteAdminUser(id); toast.success("User deleted"); onReload(); }
    catch (e: any) { toast.error(e.response?.data?.detail || "Failed"); }
  };
  return (
    <div className="overflow-x-auto rounded-2xl bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <Th>Name</Th><Th className="hidden md:table-cell">Email</Th><Th>Role</Th><Th>Status</Th><Th className="hidden md:table-cell">Joined</Th><Th></Th>
          </tr>
        </thead>
        <tbody>
          {users.map((u: any) => (
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
      {["tiktok", "youtube", "meta"].map((p) => <OAuthCard key={p} platform={p} data={oauth[p]} redirectBase={redirectBase} onReload={onReload} />)}
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
  const [clientId, setClientId] = useState(data?.client_id || "");
  const [clientSecret, setClientSecret] = useState("");
  useEffect(() => { setClientId(data?.client_id || ""); }, [data]);

  const save = async () => {
    const payload: any = { client_id: clientId };
    if (clientSecret) payload.client_secret = clientSecret;
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
  return (
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
