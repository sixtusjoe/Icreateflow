"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, Check, ExternalLink, Info, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import {
  Card, CardHead, CardBody, Chip, DotsMenu, PageHead, PageTitle, PageActions,
  PrimaryButton, BackLink, Tag, TD, MONO, Note, Skeleton, Empty,
} from "@/components/kit";
import { ConfirmDialog, Field, Input, FieldLabel } from "@/components/kit/dialog";
import { Initial, NoEndpoint, RolePill, Sub, STATUS_TONE } from "@/components/admin/ui";
import { num } from "@/components/admin/charts";
import {
  getUsers, updateUser, approveUser, deleteAdminUser,
  getAdminBrands, getAdminPosts, getAdminAccounts, getAdminMusic, getAdminArtists,
  listOutreachCampaigns, listOutreachAccounts, listOutreachAudit,
  getAdminUserProfile, type ProfileKey, avatarSrc,
} from "@/lib/api";

/**
 * Admin — one user.
 *
 * Its own page, reached from the list. Everything an admin can do to a
 * person, with the half that has no endpoint behind it drawn and tagged
 * rather than quietly missing.
 *
 * Phone, location, company and time zone have no columns on users. They
 * are the person's own, set on their Account page and kept as rows in
 * user_settings; this page reads them through
 * GET /api/admin/users/{id}/profile and shows them read-only, because what
 * someone says about themselves is theirs to change.
 */

type Row = Record<string, unknown>;
const s = (r: Row, k: string) => (r[k] == null ? "" : String(r[k]));
const nOf = (r: Row, k: string) => Number(r[k] ?? 0);

const ago = (iso: string) => {
  if (!iso) return "never signed in";
  const gap = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (gap <= 0) return "today";
  if (gap === 1) return "yesterday";
  if (gap < 31) return `${gap} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

const daysSince = (iso: string) =>
  iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000) : 0;

export default function AdminUserPage() {
  const { user: me } = useAuth();
  const router = useRouter();
  const id = Number(useParams().id);

  const [person, setPerson] = useState<Row | null>(null);
  const [missing, setMissing] = useState(false);
  const [brands, setBrands] = useState<Row[]>([]);
  const [posts, setPosts] = useState<Row[]>([]);
  const [postAccts, setPostAccts] = useState<Row[]>([]);
  const [music, setMusic] = useState<Row[]>([]);
  const [artists, setArtists] = useState<Row[]>([]);
  const [camps, setCamps] = useState<Row[]>([]);
  const [senders, setSenders] = useState<Row[]>([]);
  const [audit, setAudit] = useState<Row[]>([]);
  const [profile, setProfile] = useState<Record<ProfileKey, string> | null>(null);

  // The form. Seeded once the person lands, and only what the schema has.
  const [form, setForm] = useState({ name: "", email: "", role: "user", status: "active", email_notifications: true });
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(() => {
    getUsers()
      .then((all: Row[]) => {
        // There is no GET /api/admin/users/{id}; the list is the only way
        // to read one, so the page asks for all of them and picks.
        const found = all.find((u) => Number(u.id) === id) ?? null;
        setPerson(found);
        setMissing(!found);
        if (found) {
          setForm({
            name: s(found, "name"),
            email: s(found, "email"),
            role: s(found, "role") || "user",
            status: s(found, "status") || "active",
            email_notifications: found.email_notifications !== false,
          });
        }
      })
      .catch(() => setMissing(true));
    getAdminUserProfile(id).then(setProfile).catch(() => {});
    getAdminBrands().then((r: Row[]) => setBrands(r.filter((b) => nOf(b, "user_id") === id))).catch(() => {});
    getAdminPosts({ user_id: id }).then(setPosts).catch(() => {});
    getAdminAccounts().then((r: Row[]) => setPostAccts(r.filter((a) => nOf(a, "user_id") === id))).catch(() => {});
    getAdminMusic().then((r: Row[]) => setMusic(r.filter((m) => nOf(m, "user_id") === id))).catch(() => {});
    getAdminArtists().then((r: Row[]) => setArtists(r.filter((a) => nOf(a, "user_id") === id))).catch(() => {});
    listOutreachCampaigns().then((r: Row[]) => setCamps(r.filter((c) => nOf(c, "user_id") === id))).catch(() => {});
    listOutreachAccounts().then((r: Row[]) => setSenders(r.filter((a) => nOf(a, "user_id") === id))).catch(() => {});
    // The audit log is instance-wide for an admin and every row carries the
    // user it belongs to, so this is their history and nobody else's.
    listOutreachAudit({ limit: 500 })
      .then((r: Row[]) => setAudit(r.filter((a) => nOf(a, "user_id") === id).slice(0, 12)))
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    if (me && me.role !== "admin") { router.push("/dashboard"); return; }
    if (!me) return;
    load();
  }, [me, router, load]);

  if (!me || me.role !== "admin") return null;

  if (missing) {
    return (
      <>
        <PageHead><PageTitle title="No such account" above={<BackLink href="/admin/users">All users</BackLink>} /></PageHead>
        <Card>
          <Empty icon={AlertTriangle} title={`Nobody on this instance has id ${id}`}>
            They may have been deleted. The list has everyone who is left.
          </Empty>
        </Card>
      </>
    );
  }

  if (!person) {
    return (
      <>
        <PageHead><PageTitle title="Loading…" above={<BackLink href="/admin/users">All users</BackLink>} /></PageHead>
        <Skeleton className="h-[140px]" />
        <Skeleton className="h-[300px]" />
      </>
    );
  }

  const self = id === me.id;
  const status = s(person, "status") || "active";
  const dirty =
    form.name !== s(person, "name") || form.email !== s(person, "email") ||
    form.role !== (s(person, "role") || "user") || form.status !== status ||
    form.email_notifications !== (person.email_notifications !== false);

  const save = async () => {
    setSaving(true);
    try {
      await updateUser(id, form);
      toast.success("Saved.");
      load();
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "That did not save.");
    } finally {
      setSaving(false);
    }
  };

  const OWNS: [string, number][] = [
    ["Brands", brands.length],
    ["Posting accounts", postAccts.length],
    ["Posts", posts.length],
    ["Campaigns", camps.length],
    ["Sending accounts", senders.length],
  ];

  /* ------------------------------------------------------------ stuck work */
  // Everything here is read from their own rows. The repairs are what
  // support gets asked for; whether this page can run them is a separate
  // question, and each row answers it.
  type Stuck = { title: string; sub: string; why: string; action: string; state: "none" | "scoped" | "ok" };
  const stuck: Stuck[] = [];
  for (const c of camps) {
    const queued = nOf(c, "total_targets") - nOf(c, "processed_count");
    if (s(c, "status") === "running" && queued > 0) {
      stuck.push({
        title: `Campaign ${nOf(c, "id")} — “${s(c, "name")}”`,
        sub: `${num(queued)} targets still queued`,
        why: "Running with work outstanding. If nothing has moved for a day, the worker is not claiming its jobs.",
        action: "Retry failed targets", state: "scoped",
      });
    }
  }
  for (const a of senders) {
    if (nOf(a, "consecutive_errors") > 0) {
      stuck.push({
        title: `Sending account “${s(a, "name")}”`,
        sub: `${s(a, "status")} · ${nOf(a, "consecutive_errors")} errors in a row`,
        why: s(a, "last_error")
          ? `Last error: ${s(a, "last_error").slice(0, 120)}`
          : "At five in a row the account pauses itself so it does not burn the login.",
        action: "Clear the pause", state: "scoped",
      });
    }
  }
  for (const p of posts) {
    if (["generating", "posting"].includes(s(p, "status")) && daysSince(s(p, "updated_at") || s(p, "created_at")) >= 1) {
      stuck.push({
        title: `Post #${s(p, "post_number") || s(p, "id")} — stuck in “${s(p, "status")}”`,
        sub: `no movement for ${daysSince(s(p, "updated_at") || s(p, "created_at"))} days`,
        why: "A render that never finished leaves the post unopenable, and nothing retries it.",
        action: "Reset to draft", state: "none",
      });
    }
  }

  return (
    <>
      <PageHead>
        <PageTitle
          title={s(person, "name") || s(person, "email")}
          above={<BackLink href="/admin/users">All users</BackLink>}
          sub={`${s(person, "email")} · joined ${s(person, "created_at").slice(0, 10)} · last seen ${ago(s(person, "last_login"))}`}
        />
        <PageActions>
          {status === "pending" && (
            <Chip
              icon={Check}
              onClick={async () => {
                try { await approveUser(id); toast.success("Approved. They can sign in now."); load(); }
                catch { toast.error("That did not go through."); }
              }}
            >
              Approve
            </Chip>
          )}
          <PrimaryButton icon={Check} onClick={save} disabled={!dirty || saving}>
            {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
          </PrimaryButton>
          <DotsMenu
            items={[
              { label: "Copy user id", onClick: () => navigator.clipboard?.writeText(String(id)) },
              { label: "Copy email", onClick: () => navigator.clipboard?.writeText(s(person, "email")) },
              "-",
              { label: "Delete account", danger: true, disabled: self, onClick: () => setConfirm(true) },
            ]}
          />
        </PageActions>
      </PageHead>

      <Card>
        <div className="flex flex-wrap items-center gap-3 px-5 pb-3.5 pt-[18px]">
          <Initial name={s(person, "name")} size={46} src={avatarSrc(person.avatar_url)} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <b className="text-[17px] font-extrabold tracking-[-0.02em] text-foreground">{s(person, "name")}</b>
              <Tag tone={STATUS_TONE[status] ?? "draft"}>{status.replace(/^./, (c) => c.toUpperCase())}</Tag>
              <RolePill role={s(person, "role") || "user"} />
            </div>
            <div className="mt-0.5 text-[11.5px] text-subtle">{s(person, "email")}</div>
          </div>
          <span className="ml-auto flex items-center gap-2">
            {/* Admins read every user's data through the admin endpoints;
                nothing lets one sign in *as* somebody, so this is drawn and
                dead rather than left out. */}
            <Chip
              icon={ExternalLink}
              disabled
              title="No endpoint: nothing signs an admin in as another user."
            >
              Open their workspace<NoEndpoint />
            </Chip>
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2.5 px-5 pb-[18px] sm:grid-cols-3 lg:grid-cols-5">
          {OWNS.map(([label, v]) => (
            <div key={label} className="rounded-[12px] border border-border bg-secondary px-3.5 py-2.5">
              <b className={`block text-[20px] font-extrabold leading-tight tracking-[-0.03em] tabular-nums ${v ? "text-foreground" : "text-subtle"}`}>
                {num(v)}
              </b>
              <i className="mt-0.5 block text-[10.5px] not-italic text-subtle">{label}</i>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid items-stretch gap-4 lg:grid-cols-2">
        {/* ------------------------------------------------------ profile */}
        <Card className="flex flex-col">
          <CardHead title="Profile" sub="Who they are and how to reach them" />
          <CardBody className="flex flex-1 flex-col gap-3.5">
            <div className="grid gap-3.5 sm:grid-cols-2">
              <Field label="Display name">
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <div>
                <Field label="Email">
                  <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </Field>
                <Why>Changing this changes what they sign in with.</Why>
              </div>
            </div>
            <div className="grid gap-3.5 sm:grid-cols-2">
              <Theirs label="Phone" value={profile?.profile_phone} />
              <Theirs label="Location" value={profile?.profile_location} />
            </div>
            <div className="grid gap-3.5 sm:grid-cols-2">
              <Theirs label="Company" value={profile?.profile_company} />
              <Theirs label="Time zone" value={profile?.profile_timezone}
                      hint="Brands carry their own time zone for posting; this one is the person's." />
            </div>
            <div>
              <FieldLabel>Email notifications</FieldLabel>
              <Seg
                value={form.email_notifications ? "on" : "off"}
                options={[["on", "On"], ["off", "Off"]]}
                onChange={(v) => setForm({ ...form, email_notifications: v === "on" })}
              />
              <Why>
                <span className={MONO}>users.email_notifications</span>. Off means the app sends them nothing
                at all; they can switch it themselves on their Account page, as well as through the unsubscribe link.
              </Why>
            </div>
            <div className="mt-auto pt-1 text-[11px] leading-[1.55] text-subtle">
              Phone, location, company and time zone are theirs: they set them on their Account page, and you
              can read them here but not change them. Name, email and the email switch are yours to change too.
            </div>
          </CardBody>
        </Card>

        {/* ------------------------------------------------------- access */}
        <Card className="flex flex-col">
          <CardHead title="Access" sub="Role and status are the only two levers the schema has" />
          <CardBody className="flex flex-1 flex-col gap-3.5">
            <div>
              <FieldLabel>Role</FieldLabel>
              <Seg
                value={form.role}
                options={[["user", "User"], ["admin", "Admin"]]}
                disabled={self}
                onChange={(v) => setForm({ ...form, role: v })}
              />
              <Why>Admin sees every user&apos;s data and this whole area.</Why>
            </div>
            <div>
              <FieldLabel>Status</FieldLabel>
              <Seg
                value={form.status}
                options={[["active", "Active"], ["suspended", "Suspended"], ["pending", "Pending"]]}
                disabled={self}
                onChange={(v) => setForm({ ...form, status: v })}
              />
              <Why>
                Suspended blocks sign-in and leaves everything they own intact. There is no separate
                “blocked”: the column allows active, suspended or pending and nothing else.
              </Why>
            </div>

            <div className="border-t border-line-2 pt-3.5">
              <Sub>Password &amp; sign-in</Sub>
              <div className="flex flex-col gap-3">
                <Dead
                  label="Send a reset email"
                  tag="no endpoint"
                  button="Email a reset link"
                  hint="forgot-password mails an OTP to the address on the account — and silently does nothing when email is not configured."
                />
                <Dead
                  label="Set a temporary password"
                  tag="no endpoint"
                  button="Set and force a change"
                  hint="A user changes their own with their current one. Nothing lets an admin set it."
                />
                <Dead
                  label="Sessions"
                  tag="no endpoint"
                  button="Sign them out everywhere"
                  hint="Tokens are stateless JWTs with a fixed expiry; there is no session list to revoke."
                />
              </div>
            </div>
          </CardBody>
        </Card>
      </div>

      {/* ------------------------------------------------------ stuck work */}
      <Card>
        <CardHead title="Stuck work"
                  sub="What support gets asked to fix, and whether this page can fix it" />
        <CardBody>
          {stuck.length === 0 ? (
            <div className="rounded-[12px] border border-good/25 bg-good/[0.07] px-4 py-3.5 text-[12.5px] font-semibold text-good">
              Nothing of theirs is stuck.
            </div>
          ) : (
            <div className="flex flex-col">
              {stuck.map((j, k) => (
                <div key={k} className="flex flex-wrap items-start gap-3 border-b border-line-2 py-3 last:border-b-0">
                  <span className={`mt-px grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] ${
                    j.state === "ok" ? "bg-good/12 text-good" : "bg-warn/12 text-warn"}`}>
                    {j.state === "ok" ? <Check className="h-[15px] w-[15px]" /> : <AlertTriangle className="h-[15px] w-[15px]" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <b className="block text-[12.5px] font-bold text-foreground">{j.title}</b>
                    <em className="block text-[11px] not-italic text-muted-foreground">{j.sub}</em>
                    <i className="mt-0.5 block text-[11px] not-italic leading-[1.55] text-subtle">{j.why}</i>
                  </span>
                  <span className="flex flex-none items-center gap-1.5">
                    <Chip disabled title={j.state === "none"
                      ? "No endpoint does this."
                      : "The endpoint exists but refuses an admin acting for somebody else."}>
                      {j.action}
                    </Chip>
                    <NoEndpoint soft={j.state === "scoped"}>
                      {j.state === "scoped" ? "user-scoped" : "no endpoint"}
                    </NoEndpoint>
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-3 text-[11px] leading-[1.55] text-subtle">
            The repairs that exist are scoped to the account that owns the thing —{" "}
            <span className={MONO}>_own_account</span> and <span className={MONO}>_scope</span> refuse an admin
            acting for somebody else. Admin equivalents are the work.
          </div>
        </CardBody>
      </Card>

      <div className="grid items-stretch gap-4 lg:grid-cols-2">
        {/* ------------------------------------------- plan: nothing is real */}
        <Card className="flex flex-col border-warn/30">
          <CardHead
            title={<span className="flex items-center gap-2">Plan &amp; payment
              <span className="rounded-full border border-warn/30 bg-warn/12 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.06em] text-warn">sample</span>
            </span>}
            sub="No subscriptions table, no provider, no invoices" />
          <CardBody className="flex flex-1 flex-col">
            <div className="flex items-baseline gap-2.5">
              <b className="text-[17px] font-extrabold text-foreground">Studio</b>
              <span className="text-[11.5px] text-subtle">£79 a month · since March 2026</span>
            </div>
            <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px] text-subtle">
              <span>Next charge <b className="font-bold text-foreground">1 Oct</b></span>
              <span>Method <b className="font-bold text-foreground">Visa ·· 4242</b></span>
              <span>Lifetime <b className="font-bold text-foreground">£553</b></span>
            </div>
            <div className="mt-3.5 flex flex-wrap gap-2">
              <Chip disabled>Change plan</Chip>
              <Chip disabled>Refund last charge</Chip>
              <Chip disabled>Cancel at period end</Chip>
            </div>
            <div className="mt-auto flex items-start gap-2.5 rounded-[12px] border border-warn/25 bg-warn/[0.07] px-3.5 py-3 pt-3 text-[11px] leading-[1.55] text-muted-foreground"
                 style={{ marginTop: "auto" }}>
              <Info className="mt-px h-[14px] w-[14px] flex-none text-warn" />
              <span>
                Every figure here is invented. There is no subscriptions table, no payment provider and no
                invoice anywhere in the backend — nothing on this instance knows what anyone pays.
              </span>
            </div>
          </CardBody>
        </Card>

        {/* -------------------------------------------------- what they did */}
        <Card className="flex flex-col">
          <CardHead title="What they did"
                    sub="From the outreach audit log, which an admin sees instance-wide" />
          {audit.length === 0 ? (
            <CardBody className="flex-1">
              <div className="text-[12px] text-subtle">
                Nothing of theirs is in the audit log. It records outreach only — campaigns started and
                stopped, imports, accounts pausing — so an account that has not used outreach has no history
                here.
              </div>
            </CardBody>
          ) : (
            <div className="max-h-[300px] flex-1 overflow-y-auto px-5 pb-2 pt-2">
              <table className="w-full table-fixed border-collapse">
                <tbody>
                  {audit.map((a, k) => (
                    <tr key={k}>
                      <td className={`${TD} w-[132px] whitespace-nowrap`}>
                        <span className={MONO}>{s(a, "created_at").slice(0, 16).replace("T", " ")}</span>
                      </td>
                      <td className={`${TD} w-[150px] truncate text-[11.5px] text-muted-foreground`}>
                        {s(a, "action")}
                      </td>
                      {/* A browser error arrives here as a wrapped call log
                          hundreds of characters long. Two lines of it is the
                          part that says what happened; the rest is the stack
                          the error log already keeps. */}
                      <td className={`${TD} text-[12px] text-muted-foreground`}>
                        <span className="line-clamp-2 break-words">
                          {s(a, "detail") || `${s(a, "entity_type")} ${s(a, "entity_id")}`}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {/* ---------------------------------------------------------- delete */}
      <Card className="border-bad/30">
        <CardHead title="Delete this account" sub="Cascades, immediately, with no undo" />
        <CardBody>
          <div className="text-[12.5px] leading-[1.6] text-muted-foreground">
            Deleting <b className="font-bold text-foreground">{s(person, "name")}</b> removes everything of
            theirs, in this order:
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-[12px]">
              <li>every brand they own, and under each: posting accounts, posts, slides, variations and rendered output</li>
              <li>their artists, and under each: clips, variations and scheduled clip posts</li>
              <li>their outreach campaigns, the targets inside them and the queued jobs</li>
              <li>their sending accounts and the logins stored on those accounts</li>
              <li>their music tracks and their settings row</li>
              <li>the account itself</li>
            </ol>
          </div>
          <div className="mt-3.5 flex items-start gap-2.5 rounded-[12px] border border-border bg-secondary px-3.5 py-3 text-[11px] leading-[1.55] text-muted-foreground">
            <Info className="mt-px h-[14px] w-[14px] flex-none text-subtle" />
            <span>
              A campaign that is running is stopped as part of this, and a job the worker is holding right now
              is dropped. That is the cost of deleting mid-run — it is a line on the confirm dialog, not a
              reason the delete is refused. The whole cascade runs in one transaction: either the account goes
              or none of it does.
            </span>
          </div>
          <div className="mt-3.5 flex flex-wrap gap-2">
            <Chip
              onClick={async () => {
                try { await updateUser(id, { status: "suspended" }); toast.success("Suspended. Everything they own is untouched."); load(); }
                catch { toast.error("That did not go through."); }
              }}
              disabled={self || status === "suspended"}
            >
              Suspend instead
            </Chip>
            <button
              type="button"
              onClick={() => setConfirm(true)}
              disabled={self}
              title={self ? "You cannot delete your own account." : undefined}
              className="inline-flex flex-none items-center gap-[7px] rounded-[11px] bg-bad px-4 py-[9px] text-[12.5px] font-bold text-white shadow-[0_8px_18px_-9px_rgba(229,72,77,0.7)] transition-[filter] hover:brightness-110 disabled:cursor-default disabled:opacity-45 disabled:hover:brightness-100"
            >
              <Trash2 className="h-3.5 w-3.5" />Delete account
            </button>
          </div>
        </CardBody>
      </Card>

      <Note>
        Delete always wins: the endpoint clears the outreach and clipping rows as part of the same
        transaction, so a campaign being active is not a veto. It is the same cascade a person runs when
        they delete their own account from the Account page. Their profile details live in{" "}
        <span className={MONO}>user_settings</span>, which cascades with the account.
      </Note>

      {confirm && (
        <ConfirmDialog
          open
          onClose={() => setConfirm(false)}
          title={`Delete ${s(person, "name")}?`}
          body="Immediately, with no undo, and it takes everything of theirs with it."
          bullets={[
            `${brands.length} brands and everything under them`,
            `${camps.length} outreach campaigns, their targets and queued jobs`,
            `${senders.length} sending accounts and the logins stored on them`,
            `${artists.length} artists, their clips and scheduled clip posts`,
            `${music.length} music tracks and their settings row`,
          ]}
          keeps={["A campaign of theirs that is running is stopped as part of this — being mid-run does not stop the delete"]}
          note="Suspending instead keeps everything and only blocks sign-in."
          confirmLabel="Delete the account"
          confirmText={s(person, "name")}
          onConfirm={async () => {
            try {
              await deleteAdminUser(id);
              toast.success("Account deleted.");
              router.push("/admin/users");
            } catch {
              toast.error("That did not go through.");
            }
          }}
        />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ bits */

/**
 * A control drawn for something the schema or the API cannot do.
 *
 * It is here rather than absent on purpose: a screen that silently omits
 * what it cannot do teaches you it cannot be done, and nobody ever asks
 * for it again.
 */
function Dead({ label, tag, placeholder, hint, button }: {
  label: string; tag: string; placeholder?: string; hint?: string; button?: string;
}) {
  return (
    <div>
      <FieldLabel>
        {label}
        <NoEndpoint>{tag}</NoEndpoint>
      </FieldLabel>
      {button ? (
        <button
          type="button" disabled
          className="mt-1.5 w-full cursor-default rounded-[11px] border border-border bg-secondary px-3 py-2 text-[12px] font-semibold text-subtle opacity-70"
        >
          {button}
        </button>
      ) : (
        <input
          disabled placeholder={placeholder}
          className="mt-1.5 w-full cursor-default rounded-[11px] border border-border bg-secondary px-3 py-2 text-[12.5px] text-subtle opacity-70 outline-none"
        />
      )}
      {hint && <div className="mt-1 text-[11px] leading-[1.5] text-subtle">{hint}</div>}
    </div>
  );
}

/** A detail the person set about themselves: shown, not editable here. */
function Theirs({ label, value, hint }: { label: string; value?: string; hint?: string }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div className={`mt-1.5 w-full rounded-[11px] border border-border bg-secondary px-3 py-2 text-[12.5px] ${
        value ? "text-foreground" : "text-subtle"}`}>
        {value || "Not set"}
      </div>
      {hint && <div className="mt-1 text-[11px] leading-[1.5] text-subtle">{hint}</div>}
    </div>
  );
}

/** The sentence under a control that says what it will actually do. */
function Why({ children }: { children: React.ReactNode }) {
  return <div className="mt-1.5 text-[11px] leading-[1.5] text-subtle">{children}</div>;
}

/** A small segmented control — two or three mutually exclusive states. */
function Seg({ value, options, onChange, disabled }: {
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-1.5 flex w-fit flex-wrap items-center gap-[3px] rounded-[12px] border border-border bg-card p-[3px]">
      {options.map(([k, label]) => (
        <button
          key={k}
          type="button"
          disabled={disabled}
          onClick={() => onChange(k)}
          aria-pressed={k === value}
          title={disabled ? "You cannot change this on your own account." : undefined}
          className={`rounded-[9px] px-[11px] py-1.5 text-[12.5px] font-semibold transition-colors ${
            k === value
              ? "bg-primary text-primary-foreground"
              : disabled
                ? "cursor-default text-muted-foreground opacity-40"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
