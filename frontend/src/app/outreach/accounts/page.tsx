"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Users,
  Trash2,
  KeyRound,
  PlayCircle,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import {
  listOutreachAccounts,
  createOutreachAccount,
  updateOutreachAccount,
  deleteOutreachAccount,
  setOutreachAccountSession,
  resumeOutreachAccount,
  type OutreachAccount,
  startBrowserLogin,
  getBrowserLoginState,
  type BrowserLoginState,
} from "@/lib/api";
import { ConfirmModal } from "@/components/ui/confirm-modal";
import { StatusPill, PageIcon, Toggle, inputClass, relativeTime, apiErrorMessage } from "../ui";

const MAX_ACCOUNTS = 20;

export default function OutreachAccountsPage() {
  const [accounts, setAccounts] = useState<OutreachAccount[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("tiktok");
  const [busy, setBusy] = useState(false);
  const [sessionFor, setSessionFor] = useState<OutreachAccount | null>(null);
  const [sessionJson, setSessionJson] = useState("");
  const [login, setLogin] = useState<BrowserLoginState | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<OutreachAccount | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () =>
    listOutreachAccounts()
      .then(setAccounts)
      .catch((e) => toast.error(apiErrorMessage(e, "Failed to load accounts")));

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  const handleCreate = async () => {
    if (!name.trim()) return toast.error("Account name is required");
    setBusy(true);
    try {
      await createOutreachAccount({ name: name.trim(), platform });
      setName("");
      setPlatform("tiktok");
      setShowNew(false);
      load();
      toast.success("Account added");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to add account"));
    } finally {
      setBusy(false);
    }
  };

  // Ask whether this host can open a login window, whenever the modal opens.
  useEffect(() => {
    if (!sessionFor) return setLogin(null);
    let live = true;
    getBrowserLoginState(sessionFor.id)
      .then((s) => live && setLogin(s))
      .catch(() => live && setLogin(null));
    return () => {
      live = false;
    };
  }, [sessionFor]);

  // While a window is open, poll until it resolves. Signing in takes
  // minutes, so the request that started it returned long ago.
  useEffect(() => {
    if (!sessionFor || !login?.running) return;
    const iv = setInterval(async () => {
      try {
        const next = await getBrowserLoginState(sessionFor.id);
        setLogin(next);
        if (next.capture?.status === "saved") {
          toast.success(next.capture.message);
          load();
          setSessionFor(null);
        } else if (next.capture?.status === "failed") {
          toast.error(next.capture.message);
        }
      } catch {
        /* keep polling — a dropped poll is not a failed sign-in */
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [sessionFor, login?.running]);

  const handleBrowserLogin = async () => {
    if (!sessionFor) return;
    try {
      const capture = await startBrowserLogin(sessionFor.id);
      setLogin((prev) => (prev ? { ...prev, running: true, capture } : prev));
      toast.success("A browser window is opening — sign in there");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not open a sign-in window"));
    }
  };

  const handleToggle = async (account: OutreachAccount) => {
    try {
      await updateOutreachAccount(account.id, { enabled: !account.enabled });
      load();
      toast.success(account.enabled ? "Account disabled" : "Account enabled");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to update account"));
    }
  };

  const handleResume = async (account: OutreachAccount) => {
    try {
      await resumeOutreachAccount(account.id);
      load();
      toast.success("Account resumed");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to resume account"));
    }
  };

  const handleSession = async () => {
    if (!sessionFor) return;
    setBusy(true);
    try {
      await setOutreachAccountSession(sessionFor.id, sessionJson);
      setSessionFor(null);
      setSessionJson("");
      load();
      toast.success("Session stored (encrypted)");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to store session"));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachAccount(confirmDelete.id);
      setConfirmDelete(null);
      load();
      toast.success("Account removed");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to remove account"));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <Link
        href="/outreach"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Outreach
      </Link>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <PageIcon icon={Users} />
          <div>
            <h1 className="text-xl md:text-2xl font-bold tracking-tight">Sending accounts</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {accounts.length} of {MAX_ACCOUNTS} accounts. Each worker runs an account in its
              own isolated browser session.
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowNew(true)}
          disabled={accounts.length >= MAX_ACCOUNTS}
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          <Plus className="h-4 w-4" /> Add account
        </button>
      </div>

      {accounts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <Users className="mx-auto h-8 w-8 text-muted-foreground" />
          <p className="mt-3 text-sm font-medium">No sending accounts</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add an account, then attach an authorized browser session to it.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Messages</th>
                <th className="px-4 py-3 font-medium">Last activity</th>
                <th className="px-4 py-3 font-medium">Errors</th>
                <th className="px-4 py-3 font-medium">Enabled</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-b border-border/60 last:border-0 align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium">{a.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {a.platform} ·{" "}
                      {a.has_session ? (
                        <>session stored {relativeTime(a.session_updated_at)}</>
                      ) : (
                        <span className="text-amber-600 dark:text-amber-400">no session</span>
                      )}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={a.status} />
                    {a.paused_reason && (
                      <p className="mt-1 max-w-[240px] text-xs text-amber-600 dark:text-amber-400">
                        {a.paused_reason}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 tabular-nums">{a.messages_processed}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {relativeTime(a.last_activity_at)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="tabular-nums">{a.error_count}</span>
                    {a.last_error && (
                      <p className="mt-0.5 max-w-[220px] truncate text-xs text-destructive">
                        {a.last_error}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Toggle
                      checked={a.enabled}
                      onChange={() => handleToggle(a)}
                      label={`${a.enabled ? "Disable" : "Enable"} ${a.name}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {a.status === "paused" && (
                        <button
                          onClick={() => handleResume(a)}
                          title="Clear auto-pause"
                          className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          <PlayCircle className="h-4 w-4" />
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setSessionFor(a);
                          setSessionJson("");
                        }}
                        title="Attach browser session"
                        className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <KeyRound className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => setConfirmDelete(a)}
                        title="Remove account"
                        className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew && (
        <Modal onClose={() => setShowNew(false)} title="Add sending account">
          <label className="mb-1.5 block text-sm font-medium">Name</label>
          <input
            className={inputClass}
            placeholder="e.g. Sender 1"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <label className="mb-1.5 mt-4 block text-sm font-medium">Platform</label>
          <select
            className={inputClass}
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram</option>
          </select>
          <p className="mt-2 text-xs text-muted-foreground">
            A label for you — the account is authorized separately by attaching a browser
            session. The platform cannot be changed later, and an account can only be
            assigned to campaigns on the same platform.
          </p>
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              onClick={() => setShowNew(false)}
              className="min-h-[44px] rounded-lg border border-border px-5 text-sm font-medium hover:bg-muted"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={busy}
              className="min-h-[44px] rounded-lg bg-foreground px-5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Adding…" : "Add account"}
            </button>
          </div>
        </Modal>
      )}

      {sessionFor && (
        <Modal
          onClose={() => setSessionFor(null)}
          title={`Attach a session to “${sessionFor.name}”`}
        >
          {login?.available && (
            <div className="mb-4 rounded-lg border border-border p-3">
              <p className="text-sm font-medium">
                Sign in to {sessionFor.platform} in a browser
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Opens a real {sessionFor.platform} login window on this machine. Sign in
                by hand and the session is captured automatically — no copy-paste, and no
                password ever reaches this app.
              </p>
              {login.capture && !login.capture.done ? (
                <p className="mt-3 text-xs font-medium text-amber-600 dark:text-amber-500">
                  {login.capture.message}
                </p>
              ) : (
                <button
                  onClick={handleBrowserLogin}
                  className="mt-3 min-h-[40px] rounded-lg bg-foreground px-4 text-sm font-medium text-background hover:opacity-90"
                >
                  Open {sessionFor.platform} sign-in
                </button>
              )}
              {login.capture?.status === "failed" && (
                <p className="mt-2 text-xs text-red-500">{login.capture.message}</p>
              )}
            </div>
          )}

          <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-500" />
            <p>
              {login?.available ? "Or paste" : "Paste"} the Playwright{" "}
              <code>storage_state</code> JSON for an account you are authorized to send
              from. It is encrypted before storage and never returned by the API. Never
              paste a password here — this system does not accept one.
            </p>
          </div>
          <textarea
            rows={8}
            className={`${inputClass} font-mono text-xs`}
            placeholder='{"cookies": [...], "origins": [...]}'
            value={sessionJson}
            onChange={(e) => setSessionJson(e.target.value)}
          />
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              onClick={() => setSessionFor(null)}
              className="min-h-[44px] rounded-lg border border-border px-5 text-sm font-medium hover:bg-muted"
            >
              Cancel
            </button>
            <button
              onClick={handleSession}
              disabled={busy || !sessionJson.trim()}
              className="min-h-[44px] rounded-lg bg-foreground px-5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Saving…" : "Store session"}
            </button>
          </div>
        </Modal>
      )}

      <ConfirmModal
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="Remove sending account?"
        description={`“${confirmDelete?.name}” and its stored session will be deleted. Jobs already sent keep their history.`}
        confirmLabel="Remove"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card p-5 md:p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-5 text-lg font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}
