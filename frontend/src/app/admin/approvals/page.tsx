"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, CheckCircle2, Download, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import {
  Card, CardHead, CardBody, Chip, DotsMenu, PageHead, PageTitle, PageActions,
  Empty, Note, Skeleton, MONO,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import { Initial, Stat } from "@/components/admin/ui";
import { getUsers, approveUser, deleteAdminUser } from "@/lib/api";

/**
 * Admin — Approvals.
 *
 * Registration is self-service and lands in `pending`:
 *
 *   POST /api/auth/register    creates the row with status="pending" and
 *                              fire-and-forgets a "you are pending" email
 *   POST /api/auth/login       refuses pending with 403
 *   POST /api/admin/users/{id}/approve   pending -> active
 *
 * Two gaps this page has to be honest about, both found in the code:
 *
 *  - **Approving tells them nothing.** The approve endpoint flips the
 *    status and sends no email. The person finds out by trying to sign in
 *    again, which they have no reason to do. Registration mails them;
 *    being let in does not.
 *  - **There is no way to refuse.** No endpoint, no "refused" status — the
 *    column holds active, suspended or pending. Turning somebody away
 *    means deleting the row, which for an account that has never signed in
 *    removes that row and nothing else. So the Refuse button here *is*
 *    that delete, and the dialog says so in those words rather than
 *    pretending a rejection was recorded.
 */

/** Addresses that exist to be thrown away. Not a judgement on its own —
 *  it is the one signal registration gives us for free, and the card below
 *  says how little else there is. */
const DISPOSABLE = new Set([
  "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
  "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com",
  "dispostable.com", "maildrop.cc", "throwawaymail.com", "temp-mail.org",
]);

type Row = Record<string, unknown>;
const s = (r: Row, k: string) => (r[k] == null ? "" : String(r[k]));

/** Reading the clock is not something a render may do, so both of these
 *  sit outside the component. */
function signedInThisWeek(users: Row[]) {
  const cutoff = Date.now() - 7 * 86_400_000;
  return users.filter(
    (u) => s(u, "status") === "active" && s(u, "last_login") &&
      new Date(s(u, "last_login")).getTime() > cutoff
  ).length;
}

const waited = (iso: string) => {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) {
    const hrs = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
    return hrs <= 1 ? "under an hour" : `${hrs} hours`;
  }
  return days === 1 ? "1 day" : `${days} days`;
};

export default function AdminApprovalsPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [users, setUsers] = useState<Row[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [refusing, setRefusing] = useState<Row | null>(null);

  const load = useCallback(() => {
    getUsers()
      .then(setUsers)
      .catch(() => setUsers([]))
      .finally(() => setBusy(false));
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

  if (!user || user.role !== "admin") return null;

  const queue = (users ?? [])
    .filter((u) => s(u, "status") === "pending")
    .sort((a, b) => s(a, "created_at").localeCompare(s(b, "created_at")));

  const disposable = queue.filter((u) => DISPOSABLE.has(s(u, "email").split("@")[1]?.toLowerCase() ?? ""));
  const oldest = queue[0];
  // "Approved this week" is a count this instance cannot keep: nothing
  // records when a status changed. `last_login` is the closest honest
  // proxy — someone who signed in this week was approved by then.
  const activeThisWeek = signedInThisWeek(users ?? []);

  const toggle = (id: number) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const approve = async (ids: number[]) => {
    setBusy(true);
    const done: number[] = [];
    for (const id of ids) {
      try { await approveUser(id); done.push(id); } catch { /* reported below */ }
    }
    setBusy(false);
    setPicked(new Set());
    if (done.length === ids.length) {
      toast.success(
        ids.length === 1
          ? "Approved. They can sign in now — but nothing has told them so."
          : `${done.length} approved. None of them has been told.`
      );
    } else {
      toast.error(`${done.length} of ${ids.length} went through.`);
    }
    load();
  };

  const exportCsv = () => {
    const head = ["id", "name", "email", "created_at"];
    const body = queue.map((u) => head.map((k) => `"${s(u, k).replace(/"/g, '""')}"`).join(","));
    const blob = new Blob([[head.join(","), ...body].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pending-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <>
      <PageHead>
        <PageTitle title="Approvals" sub="Everyone who signed up and cannot get in until you say so." />
        <PageActions>
          <Chip icon={Download} onClick={exportCsv} disabled={!queue.length}>Export as CSV</Chip>
          <Chip icon={RefreshCw} onClick={refresh} disabled={busy}>{busy ? "Working…" : "Refresh"}</Chip>
        </PageActions>
      </PageHead>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat value={queue.length} label="Waiting" note="cannot sign in until you act"
              tone={queue.length ? "warn" : undefined} />
        <Stat value={oldest ? waited(s(oldest, "created_at")) : "—"} label="Longest wait"
              note={oldest ? s(oldest, "name") : "nobody is waiting"} />
        <Stat value={activeThisWeek} label="Signed in this week"
              note="nothing records when a status changed" />
        <Stat value={disposable.length} label="Flagged addresses"
              note="disposable email domains" tone={disposable.length ? "warn" : undefined} />
      </div>

      <Card>
        <CardHead
          title="Waiting"
          sub="Oldest first — a signup that sits here is somebody who cannot sign in"
          right={
            <DotsMenu items={[
              { label: "Approve everyone", disabled: !queue.length, onClick: () => approve(queue.map((u) => Number(u.id))) },
              { label: "Export as CSV", disabled: !queue.length, onClick: exportCsv },
              "-",
              { label: "See all users", href: "/admin/users" },
            ]} />
          }
        />

        {users === null ? (
          <div className="flex flex-col gap-2 p-5">
            {[0, 1, 2].map((k) => <Skeleton key={k} className="h-16" />)}
          </div>
        ) : queue.length === 0 ? (
          <Empty icon={CheckCircle2} title="Nobody is waiting">
            Signups land here the moment somebody registers. They cannot sign in until you approve them, so
            this page is worth a look when someone says they are locked out.
          </Empty>
        ) : (
          <>
            {picked.size > 0 && (
              <div className="flex flex-wrap items-center gap-3 border-y border-line-2 bg-secondary px-5 py-2.5">
                <span className="text-[11.5px] font-semibold text-muted-foreground">{picked.size} selected</span>
                <span className="ml-auto flex gap-2">
                  <Chip onClick={() => approve([...picked])} disabled={busy}>Approve selected</Chip>
                  <Chip onClick={() => setPicked(new Set())}>Clear</Chip>
                </span>
              </div>
            )}
            <div className="flex flex-col">
              {queue.map((p) => {
                const id = Number(p.id);
                const domain = s(p, "email").split("@")[1]?.toLowerCase() ?? "";
                const flagged = DISPOSABLE.has(domain);
                const when = new Date(s(p, "created_at"));
                return (
                  <div key={id} className="flex flex-wrap items-center gap-3 border-b border-line-2 px-5 py-3.5 last:border-b-0 hover:bg-secondary">
                    <label className="flex flex-none cursor-pointer items-center">
                      <input
                        type="checkbox" checked={picked.has(id)} onChange={() => toggle(id)}
                        aria-label={`Select ${s(p, "name")}`}
                        className="h-[17px] w-[17px] accent-[var(--primary)]"
                      />
                    </label>
                    <Initial name={s(p, "name")} />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="flex flex-wrap items-center gap-2.5">
                        <b className="text-[13.5px] font-bold text-foreground">{s(p, "name")}</b>
                        {flagged && (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/30 bg-warn/12 px-2 py-0.5 text-[10px] font-bold text-warn">
                            <AlertTriangle className="h-[11px] w-[11px]" />Disposable address
                          </span>
                        )}
                      </span>
                      <span className="text-[11.5px] text-muted-foreground">{s(p, "email")}</span>
                      <span className="text-[10.5px] text-subtle">
                        Registered {when.toLocaleDateString()} at{" "}
                        {when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · waiting{" "}
                        {waited(s(p, "created_at"))}
                      </span>
                    </span>
                    <span className="ml-auto flex flex-none items-center gap-2">
                      <Chip danger onClick={() => setRefusing(p)}>Refuse</Chip>
                      <Chip icon={Check} onClick={() => approve([id])} disabled={busy}>Approve</Chip>
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Card>

      <div className="grid items-stretch gap-4 lg:grid-cols-2">
        <Card className="flex flex-col">
          <CardHead title="What approving does" sub="And what it does not" />
          <CardBody className="flex flex-1 flex-col">
            <Step tone="ok" title="Their status becomes active">
              They can sign in from that second. Nothing else changes — no brand, no workspace, no defaults
              are created for them.
            </Step>
            <Step tone="bad" title="They are not told">
              The approve endpoint sends no email. They registered, got a “you are pending” mail, and then
              nothing — the only way they learn they are in is by trying to sign in again, which they have no
              reason to do. An approval email is the smallest fix on this page.
            </Step>
            <Step tone="bad" title="Refusing is not a thing">
              There is no reject endpoint and no “refused” status — the column holds active, suspended or
              pending. So the Refuse button deletes the row, which for an account that has never signed in
              removes that row and nothing else. They can register again with the same address.
            </Step>
          </CardBody>
        </Card>

        <Card className="flex flex-col">
          <CardHead title="What you know about them" sub="Everything registration captures" />
          <CardBody className="flex flex-1 flex-col">
            {oldest ? (
              <>
                <Kv label="Name">{s(oldest, "name")}</Kv>
                <Kv label="Email">{s(oldest, "email")}</Kv>
                <Kv label="Registered">{new Date(s(oldest, "created_at")).toLocaleString()}</Kv>
              </>
            ) : (
              <>
                <Kv label="Name">whatever they typed</Kv>
                <Kv label="Email">whatever they typed</Kv>
                <Kv label="Registered">the moment they pressed the button</Kv>
              </>
            )}
            <Kv label="Sign-in attempts since" muted>not recorded</Kv>
            <Kv label="Where they came from" muted>not recorded</Kv>
            <Kv label="Anything they typed" muted>nothing else is asked</Kv>
            <div className="mt-auto pt-3 text-[11px] leading-[1.55] text-subtle">
              Registration takes a name, an email and a password. That is the whole basis for the decision,
              which is why the disposable-address flag above is worth having — it needs nothing but a domain
              list — and why a “why do you want an account” box at signup would be worth more than anything
              else on this screen.
            </div>
          </CardBody>
        </Card>
      </div>

      <Note>
        Wired: the queue (<span className={MONO}>GET /api/admin/users</span>, filtered to pending),{" "}
        <span className={MONO}>POST /api/admin/users/{"{id}"}/approve</span>, approving several at once (one
        call each — there is no bulk endpoint), and refusing by way of{" "}
        <span className={MONO}>DELETE /api/admin/users/{"{id}"}</span>. Not wired: an approval email, and a
        “refused” state that would stop the same address coming straight back.{" "}
        <Link href="/admin/users" className="font-semibold text-foreground underline underline-offset-2">
          Everyone else is on Users
        </Link>.
      </Note>

      {refusing && (
        <ConfirmDialog
          open
          onClose={() => setRefusing(null)}
          title={`Refuse ${s(refusing, "name")}?`}
          body="There is no “refused” state, so this deletes the account row instead."
          bullets={[
            "Their account row is removed. They have never signed in, so there is nothing else to remove.",
            "They are told nothing — no refusal email exists.",
            "Nothing stops them registering again with the same address, and it lands back on this page.",
          ]}
          keeps={["Leaving them pending is the other option: they stay locked out and stay on this list."]}
          confirmLabel="Refuse and delete"
          onConfirm={async () => {
            try {
              await deleteAdminUser(Number(refusing.id));
              toast.success("Refused. The account row is gone.");
            } catch {
              toast.error("That did not go through.");
            }
            setRefusing(null);
            load();
          }}
        />
      )}
    </>
  );
}

function Step({ tone, title, children }: { tone: "ok" | "bad"; title: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-line-2 py-3 last:border-b-0 last:pb-0">
      <span className={`mt-px grid h-[30px] w-[30px] flex-none place-items-center rounded-[10px] ${
        tone === "ok" ? "bg-good/12 text-good" : "bg-warn/12 text-warn"}`}>
        {tone === "ok" ? <Check className="h-[15px] w-[15px]" /> : <AlertTriangle className="h-[15px] w-[15px]" />}
      </span>
      <span className="min-w-0">
        <b className="block text-[12.5px] font-bold text-foreground">{title}</b>
        <i className="mt-0.5 block text-[11px] not-italic leading-[1.55] text-subtle">{children}</i>
      </span>
    </div>
  );
}

function Kv({ label, children, muted }: { label: string; children: React.ReactNode; muted?: boolean }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-line-2 py-2 last:border-b-0">
      <span className="flex-1 text-[11.5px] text-subtle">{label}</span>
      <b className={`text-[11.5px] font-semibold ${muted ? "text-subtle" : "text-foreground"}`}>{children}</b>
    </div>
  );
}
