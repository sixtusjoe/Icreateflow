"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Download, Plus, RefreshCw, Search, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import {
  Card, Chip, DotsMenu, PageHead, PageTitle, PageActions, PrimaryButton, Tabs,
  Tag, TH, TD, MONO, Note, Empty, Skeleton,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import { Initial, RolePill, Stat, STATUS_TONE } from "@/components/admin/ui";
import {
  getUsers, updateUser, approveUser, deleteAdminUser, avatarSrc,
  getAdminBrands, getAdminPosts, listOutreachCampaigns,
} from "@/lib/api";

/**
 * Admin — Users.
 *
 * The list is a list. Opening somebody is a page of its own: a management
 * surface with a delete button on it does not belong in a 40%-wide column
 * beside the thing you are scrolling.
 *
 * Rows per page is eight, the same as the campaign list, and for the same
 * reason — it keeps the table inside one screen under the stat cards and
 * the filter bar, and it means the pager is visible at the size the list
 * actually is. A page size the list never reaches is a control nobody
 * knows exists.
 */
const PAGE_SIZE = 8;

type Row = Record<string, unknown>;
const s = (r: Row, k: string) => (r[k] == null ? "" : String(r[k]));

const ago = (iso: string) => {
  if (!iso) return "never signed in";
  const gap = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (gap <= 0) return "today";
  if (gap === 1) return "yesterday";
  if (gap < 31) return `${gap} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

const FILTERS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "pending", label: "Waiting" },
  { key: "suspended", label: "Suspended" },
  { key: "admins", label: "Admins" },
];

export default function AdminUsersPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [users, setUsers] = useState<Row[] | null>(null);
  const [brands, setBrands] = useState<Row[]>([]);
  const [posts, setPosts] = useState<Row[]>([]);
  const [camps, setCamps] = useState<Row[]>([]);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<Row | null>(null);

  const load = useCallback(() => {
    Promise.all([
      getUsers().then(setUsers).catch(() => setUsers([])),
      getAdminBrands().then(setBrands).catch(() => {}),
      getAdminPosts().then(setPosts).catch(() => {}),
      listOutreachCampaigns().then(setCamps).catch(() => {}),
    ]).finally(() => setBusy(false));
  }, []);

  /** What the Refresh chip does. `load` on its own never touches state
   *  before a request is out, so the first load can run straight from the
   *  effect without a cascading render behind it. */
  const refresh = useCallback(() => { setBusy(true); load(); }, [load]);

  useEffect(() => {
    if (user && user.role !== "admin") { router.push("/dashboard"); return; }
    if (!user) return;
    load();
  }, [user, router, load]);

  const counts = useMemo(() => {
    const by = (k: string) => (users ?? []).filter((u) => s(u, "status") === k).length;
    return {
      all: users?.length ?? 0,
      active: by("active"),
      pending: by("pending"),
      suspended: by("suspended"),
      admins: (users ?? []).filter((u) => s(u, "role") === "admin").length,
    };
  }, [users]);

  const owned = useMemo(() => {
    const tally = (rows: Row[], key: string) =>
      rows.reduce<Record<string, number>>((m, r) => {
        const k = s(r, key);
        return k ? { ...m, [k]: (m[k] || 0) + 1 } : m;
      }, {});
    return { brands: tally(brands, "user_id"), posts: tally(posts, "user_id"), camps: tally(camps, "user_id") };
  }, [brands, posts, camps]);

  if (!user || user.role !== "admin") return null;

  const rows = (users ?? []).filter((u) => {
    if (filter === "admins" ? s(u, "role") !== "admin" : filter !== "all" && s(u, "status") !== filter) return false;
    const q = query.trim().toLowerCase();
    return !q || s(u, "name").toLowerCase().includes(q) || s(u, "email").toLowerCase().includes(q);
  });

  // Clamped rather than corrected: suspending the last person on the last
  // page leaves `page` pointing past the end, and a render that fixes it by
  // setting state paints an empty table first.
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const from = current * PAGE_SIZE;
  const shown = rows.slice(from, from + PAGE_SIZE);

  const act = async (id: number, work: Promise<unknown>, done: string) => {
    try {
      await work;
      toast.success(done);
      load();
    } catch {
      toast.error("That did not go through.");
    }
  };

  const exportCsv = () => {
    const head = ["id", "name", "email", "role", "status", "created_at", "last_login"];
    const body = rows.map((u) => head.map((k) => `"${s(u, k).replace(/"/g, '""')}"`).join(","));
    const blob = new Blob([[head.join(","), ...body].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `users-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Users" sub="Everyone on the instance. Open one to manage it." />
        <PageActions>
          <Chip icon={Download} onClick={exportCsv}>Export as CSV</Chip>
          <Chip icon={RefreshCw} onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "Refresh"}</Chip>
          {/* Drawn and disabled rather than left out. Registration is
              self-service with an approval step; there is no endpoint that
              creates an account on somebody's behalf, and a screen that
              silently omits that teaches you it cannot be done. */}
          <PrimaryButton
            icon={Plus}
            disabled
            title="No endpoint: registration is self-service, and nothing creates an account for someone else."
          >
            Invite someone
            <span className="ml-1.5 rounded-full border border-white/20 bg-white/10 px-[7px] py-px text-[9.5px] font-bold uppercase tracking-[0.05em]">
              no endpoint
            </span>
          </PrimaryButton>
        </PageActions>
      </PageHead>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat value={counts.all} label="Everyone" note="accounts on the instance" />
        <Stat value={counts.active} label="Active" note="can sign in right now" />
        <Stat value={counts.pending} label="Waiting" note="approve or refuse them"
              tone={counts.pending ? "warn" : undefined} />
        <Stat value={counts.suspended} label="Suspended" note="kept, but locked out" />
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Tabs
          items={FILTERS.map((f) => ({ ...f, count: counts[f.key as keyof typeof counts] }))}
          value={filter}
          onChange={(k) => { setFilter(k); setPage(0); }}
        />
        <label className="ml-auto flex min-w-[240px] flex-1 items-center gap-2.5 rounded-[11px] border border-border bg-card px-3.5 py-2 shadow-card sm:flex-none">
          <Search className="h-[15px] w-[15px] flex-none text-subtle" />
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(0); }}
            placeholder="Search name or email"
            className="w-full border-0 bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-subtle"
          />
        </label>
      </div>

      <Card>
        {users === null ? (
          <div className="flex flex-col gap-2 p-5">
            {[0, 1, 2, 3, 4].map((k) => <Skeleton key={k} className="h-12" />)}
          </div>
        ) : rows.length === 0 ? (
          <Empty icon={UserPlus} title="Nobody matches that">
            {query ? <>No account&apos;s name or email contains “{query}”.</> : "No account is in that state."}
          </Empty>
        ) : (
          <>
            <div className="overflow-x-auto px-5 pt-4">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={TH}>Person</th>
                    <th className={TH}>Role</th>
                    <th className={TH}>Status</th>
                    <th className={TH}>Joined</th>
                    <th className={TH}>Last seen</th>
                    <th className={`${TH} text-right`}>Brands</th>
                    <th className={`${TH} text-right`}>Posts</th>
                    <th className={`${TH} text-right`}>Campaigns</th>
                    <th className={TH} />
                  </tr>
                </thead>
                <tbody>
                  {shown.map((u) => {
                    const id = Number(u.id);
                    const status = s(u, "status") || "active";
                    const self = id === user.id;
                    return (
                      <tr key={id} className="group">
                        <td className={TD}>
                          <Link href={`/admin/users/${id}`} className="flex items-center gap-2.5">
                            <Initial name={s(u, "name")} size={32} src={avatarSrc(u.avatar_url)} />
                            <span className="flex min-w-0 flex-col">
                              <span className="truncate font-semibold text-foreground">{s(u, "name")}</span>
                              <span className="truncate text-[10.5px] text-subtle">{s(u, "email")}</span>
                            </span>
                          </Link>
                        </td>
                        <td className={TD}><RolePill role={s(u, "role") || "user"} /></td>
                        <td className={TD}>
                          <Tag tone={STATUS_TONE[status] ?? "draft"}>
                            {status.replace(/^./, (c) => c.toUpperCase())}
                          </Tag>
                        </td>
                        <td className={`${TD} whitespace-nowrap`}>
                          <span className={MONO}>{s(u, "created_at").slice(0, 10)}</span>
                        </td>
                        <td className={`${TD} whitespace-nowrap text-[11.5px] text-subtle`}>
                          {ago(s(u, "last_login"))}
                        </td>
                        <td className={`${TD} text-right font-semibold tabular-nums`}>{owned.brands[String(id)] ?? 0}</td>
                        <td className={`${TD} text-right font-semibold tabular-nums`}>{owned.posts[String(id)] ?? 0}</td>
                        <td className={`${TD} text-right font-semibold tabular-nums`}>{owned.camps[String(id)] ?? 0}</td>
                        <td className={`${TD} text-right`}>
                          <DotsMenu
                            label={`Actions for ${s(u, "name")}`}
                            items={[
                              { label: "Open this account", href: `/admin/users/${id}` },
                              ...(status === "pending"
                                ? [{ label: "Approve", onClick: () => act(id, approveUser(id), "Approved. They can sign in now.") }]
                                : []),
                              {
                                label: s(u, "role") === "admin" ? "Make a normal user" : "Make admin",
                                disabled: self,
                                onClick: () => act(id, updateUser(id, { role: s(u, "role") === "admin" ? "user" : "admin" }), "Role changed."),
                              },
                              "-",
                              status === "suspended"
                                ? { label: "Lift the suspension", onClick: () => act(id, updateUser(id, { status: "active" }), "They can sign in again.") }
                                : { label: "Suspend", disabled: self, onClick: () => act(id, updateUser(id, { status: "suspended" }), "Suspended. Everything they own is untouched.") },
                              { label: "Delete account", danger: true, disabled: self, onClick: () => setConfirm(u) },
                            ]}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {rows.length > PAGE_SIZE && (
              <div className="flex items-center justify-between gap-3 border-t border-line-2 px-5 pb-4 pt-3 text-[11.5px] tabular-nums text-subtle">
                <span>{from + 1}–{Math.min(from + PAGE_SIZE, rows.length)} of {rows.length}</span>
                <span className="flex gap-1.5">
                  <button
                    onClick={() => setPage(current - 1)} disabled={current === 0} aria-label="Previous page"
                    className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-subtle transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40"
                  >
                    <ArrowLeft className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setPage(current + 1)} disabled={current >= pageCount - 1} aria-label="Next page"
                    className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-subtle transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40"
                  >
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </span>
              </div>
            )}
          </>
        )}
      </Card>

      <Note>
        A row opens the account. Approving, suspending, renaming and deleting are wired —{" "}
        <span className={MONO}>PUT /api/admin/users/{"{id}"}</span> takes name, role and status, and nothing
        else. Inviting somebody is not: registration is self-service with an approval step, and there is no
        endpoint that creates an account on their behalf.
      </Note>

      {confirm && (
        <ConfirmDialog
          open
          onClose={() => setConfirm(null)}
          title={`Delete ${s(confirm, "name")}?`}
          body="Immediately, with no undo, and it takes everything of theirs with it."
          bullets={[
            "Their brands, and under each: posting accounts, posts, slides, variations and rendered output",
            "Their outreach campaigns, the targets inside them and the queued jobs",
            "Their sending accounts and the logins stored on those accounts",
            "Their artists, clips and scheduled clip posts",
            "Their music tracks, their settings row and the account itself",
          ]}
          keeps={[
            "A campaign of theirs that is running is stopped as part of this — being mid-run does not stop the delete",
          ]}
          note="Suspending instead keeps everything and only blocks sign-in."
          confirmLabel="Delete the account"
          confirmText={s(confirm, "name")}
          busy={busy}
          onConfirm={async () => {
            await act(Number(confirm.id), deleteAdminUser(Number(confirm.id)), "Account deleted.");
            setConfirm(null);
          }}
        />
      )}
    </>
  );
}
