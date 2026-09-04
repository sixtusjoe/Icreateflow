"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Pause,
  Square,
  RotateCcw,
  Download,
  Upload,
  Users,
  AlertTriangle,
  Activity,
} from "lucide-react";
import { toast } from "sonner";
import {
  getOutreachCampaign,
  getOutreachProgress,
  listOutreachTargets,
  importOutreachTargetsFile,
  importOutreachTargetsText,
  startOutreachCampaign,
  pauseOutreachCampaign,
  resumeOutreachCampaign,
  stopOutreachCampaign,
  retryOutreachFailed,
  downloadOutreachResults,
  assignOutreachAccount,
  unassignOutreachAccount,
  type OutreachAccount,
  type OutreachAudit,
  type OutreachCampaign,
  type OutreachImportSummary,
  type OutreachJob,
  type OutreachTarget,
} from "@/lib/api";
import { StatusPill, ProgressBar, inputClass, relativeTime, apiErrorMessage } from "../ui";

type Detail = {
  campaign: OutreachCampaign;
  target_counts: Record<string, number>;
  job_counts: Record<string, number>;
  recent_jobs: OutreachJob[];
  failed_jobs: OutreachJob[];
  assigned_account_ids: number[];
  eligible_account_ids: number[];
  accounts: OutreachAccount[];
  audit: OutreachAudit[];
  limits: { max_jobs: number; max_jobs_per_account: number; retry_limit: number };
  workers_enabled: boolean;
  driver: string;
};

const TARGET_TABS = ["all", "queued", "processing", "sent", "failed", "skipped", "paused"] as const;

export default function OutreachCampaignPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);

  const [detail, setDetail] = useState<Detail | null>(null);
  const [targets, setTargets] = useState<OutreachTarget[]>([]);
  const [targetTab, setTargetTab] = useState<(typeof TARGET_TABS)[number]>("all");
  const [busy, setBusy] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [pasted, setPasted] = useState("");
  const [summary, setSummary] = useState<OutreachImportSummary | null>(null);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());
  const fileRef = useRef<HTMLInputElement>(null);

  const loadDetail = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      setDetail(await getOutreachCampaign(id));
      setLastRefresh(Date.now());
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to load campaign"));
    }
  }, [id]);

  const loadTargets = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      const data = await listOutreachTargets(id, {
        status: targetTab === "all" ? undefined : targetTab,
        limit: 200,
      });
      setTargets(data.targets);
    } catch {
      /* the detail call already surfaced any auth/404 problem */
    }
  }, [id, targetTab]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  useEffect(() => {
    loadTargets();
  }, [loadTargets]);

  // Live monitoring: while a campaign is running the counters move on their
  // own, so poll the small progress endpoint every 3s and patch the
  // campaign in place — no full page reload, no flicker.
  const running = detail?.campaign.status === "running";
  useEffect(() => {
    if (!running || !Number.isFinite(id)) return;
    const iv = setInterval(async () => {
      try {
        const p = await getOutreachProgress(id);
        setLastRefresh(Date.now());
        setDetail((prev) =>
          prev
            ? {
                ...prev,
                campaign: {
                  ...prev.campaign,
                  status: p.status,
                  total_targets: p.total_targets,
                  queued_count: p.queued_count,
                  processed_count: p.processed_count,
                  successful_count: p.successful_count,
                  failed_count: p.failed_count,
                },
                target_counts: p.target_counts,
                recent_jobs: p.recent_jobs,
              }
            : prev,
        );
        if (p.status !== "running") {
          await loadDetail();
        }
        await loadTargets();
      } catch {
        /* transient — the next tick retries */
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [running, id, loadDetail, loadTargets]);

  const act = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(message);
      await loadDetail();
      await loadTargets();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Action failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async (file?: File) => {
    setBusy(true);
    try {
      const result = file
        ? await importOutreachTargetsFile(id, file)
        : await importOutreachTargetsText(id, pasted);
      setSummary(result);
      setPasted("");
      await loadDetail();
      await loadTargets();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Import failed"));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleExport = async () => {
    try {
      const blob = await downloadOutreachResults(id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `outreach-campaign-${id}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Export failed"));
    }
  };

  const accountsById = useMemo(() => {
    const map = new Map<number, OutreachAccount>();
    detail?.accounts.forEach((a) => map.set(a.id, a));
    return map;
  }, [detail]);

  if (!detail) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-foreground border-t-transparent" />
      </div>
    );
  }

  const c = detail.campaign;
  const status = c.status;

  return (
    <div className="mx-auto max-w-6xl">
      <Link
        href="/outreach"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> All campaigns
      </Link>

      {/* Header + actions */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl md:text-2xl font-bold tracking-tight">{c.name}</h1>
            <StatusPill status={status} />
          </div>
          {c.description && (
            <p className="mt-1 text-sm text-muted-foreground">{c.description}</p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            {c.platform} · retry limit {detail.limits.retry_limit} · max{" "}
            {detail.limits.max_jobs_per_account} jobs per account · driver{" "}
            <span className="font-mono">{detail.driver}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(status === "draft" || status === "stopped" || status === "completed") && (
            <ActionButton
              icon={<Play className="h-4 w-4" />}
              label="Start"
              primary
              disabled={busy}
              onClick={() => act(() => startOutreachCampaign(id), "Campaign started")}
            />
          )}
          {status === "running" && (
            <ActionButton
              icon={<Pause className="h-4 w-4" />}
              label="Pause"
              disabled={busy}
              onClick={() => act(() => pauseOutreachCampaign(id), "Campaign paused")}
            />
          )}
          {status === "paused" && (
            <ActionButton
              icon={<Play className="h-4 w-4" />}
              label="Resume"
              primary
              disabled={busy}
              onClick={() => act(() => resumeOutreachCampaign(id), "Campaign resumed")}
            />
          )}
          {(status === "running" || status === "paused") && (
            <ActionButton
              icon={<Square className="h-4 w-4" />}
              label="Stop"
              disabled={busy}
              onClick={() => act(() => stopOutreachCampaign(id), "Campaign stopped")}
            />
          )}
          <ActionButton
            icon={<RotateCcw className="h-4 w-4" />}
            label="Retry failed"
            disabled={busy || (detail.target_counts.failed ?? 0) === 0}
            onClick={() =>
              act(() => retryOutreachFailed(id), "Failed targets re-queued")
            }
          />
          <ActionButton
            icon={<Upload className="h-4 w-4" />}
            label="Import"
            disabled={busy}
            onClick={() => setShowImport(true)}
          />
          <ActionButton
            icon={<Download className="h-4 w-4" />}
            label="Export"
            onClick={handleExport}
          />
        </div>
      </div>

      {!detail.workers_enabled && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-500" />
          <p>
            All outreach workers are stopped by an administrator. Jobs stay queued until
            workers are re-enabled in the admin panel.
          </p>
        </div>
      )}

      {/* Progress */}
      <div className="mb-6 rounded-xl border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Progress</h2>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Activity className="h-3.5 w-3.5" />
            {running ? "live" : "paused"} · updated {relativeTime(new Date(lastRefresh).toISOString())}
          </span>
        </div>
        <ProgressBar
          processed={c.processed_count}
          total={c.total_targets}
          successful={c.successful_count}
        />
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Metric label="Targets" value={c.total_targets} />
          <Metric label="Queued" value={c.queued_count} />
          <Metric label="Processed" value={c.processed_count} />
          <Metric label="Successful" value={c.successful_count} tone="text-emerald-500" />
          <Metric label="Failed" value={c.failed_count} tone="text-destructive" />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Targets */}
        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-xl border border-border bg-card">
            <div className="flex flex-wrap items-center gap-1.5 border-b border-border p-3">
              {TARGET_TABS.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setTargetTab(tab)}
                  className={`rounded-lg px-2.5 py-1.5 text-xs font-medium capitalize transition-colors ${
                    targetTab === tab
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {tab}
                  {tab !== "all" && (
                    <span className="ml-1 tabular-nums opacity-70">
                      {detail.target_counts[tab] ?? 0}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="max-h-[480px] overflow-auto">
              {targets.length === 0 ? (
                <p className="p-6 text-center text-sm text-muted-foreground">
                  No targets {targetTab === "all" ? "imported yet" : `with status “${targetTab}”`}.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="px-4 py-2 font-medium">Username</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2 font-medium">Account</th>
                      <th className="px-4 py-2 font-medium">Attempts</th>
                      <th className="px-4 py-2 font-medium">Last attempt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targets.map((t) => (
                      <tr key={t.id} className="border-b border-border/60 last:border-0">
                        <td className="px-4 py-2">
                          <a
                            href={t.profile_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline"
                          >
                            @{t.username}
                          </a>
                          {t.error_message && (
                            <p className="mt-0.5 line-clamp-1 text-xs text-destructive">
                              {t.error_message}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          <StatusPill status={t.status} />
                        </td>
                        <td className="px-4 py-2 text-muted-foreground">
                          {t.assigned_account_id
                            ? accountsById.get(t.assigned_account_id)?.name ?? "—"
                            : "—"}
                        </td>
                        <td className="px-4 py-2 tabular-nums">{t.attempts}</td>
                        <td className="px-4 py-2 text-muted-foreground">
                          {relativeTime(t.sent_at || t.last_attempt_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Error log */}
          <Panel title="Error log" empty={detail.failed_jobs.length === 0} emptyText="No failures.">
            <ul className="divide-y divide-border/60">
              {detail.failed_jobs.map((job) => (
                <li key={job.id} className="px-4 py-2.5 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-muted-foreground">
                      job #{job.id} · {job.result_status ?? "error"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {relativeTime(job.completed_at)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-destructive">{job.error_message}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          <Panel
            title="Sending accounts"
            action={
              <Link href="/outreach/accounts" className="text-xs underline">
                Manage
              </Link>
            }
            empty={detail.accounts.length === 0}
            emptyText="No accounts for this platform."
          >
            <ul className="divide-y divide-border/60">
              {detail.accounts.map((a) => {
                const assigned = detail.assigned_account_ids.includes(a.id);
                const eligible = detail.eligible_account_ids.includes(a.id);
                return (
                  <li key={a.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="flex items-center gap-1.5 truncate text-sm font-medium">
                          <Users className="h-3.5 w-3.5 flex-shrink-0" /> {a.name}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {a.messages_processed} sent · {a.error_count} errors ·{" "}
                          {relativeTime(a.last_activity_at)}
                        </p>
                        {a.paused_reason && (
                          <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                            {a.paused_reason}
                          </p>
                        )}
                      </div>
                      <StatusPill status={a.enabled ? a.status : "stopped"} />
                    </div>
                    <button
                      onClick={() =>
                        act(
                          () =>
                            assigned
                              ? unassignOutreachAccount(id, a.id)
                              : assignOutreachAccount(id, a.id),
                          assigned ? "Account unassigned" : "Account assigned",
                        )
                      }
                      disabled={busy}
                      className="mt-2 w-full rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      {assigned ? "Remove from campaign" : "Assign to campaign"}
                    </button>
                    {!eligible && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Not currently eligible (disabled or paused).
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
            {detail.assigned_account_ids.length === 0 && detail.accounts.length > 0 && (
              <p className="border-t border-border/60 px-4 py-2.5 text-xs text-muted-foreground">
                No explicit assignment — every enabled {c.platform} account is eligible.
              </p>
            )}
          </Panel>

          <Panel
            title="Recent activity"
            empty={detail.recent_jobs.length === 0}
            emptyText="Nothing yet."
          >
            <ul className="divide-y divide-border/60">
              {detail.recent_jobs.map((job) => (
                <li key={job.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                  <span className="truncate">
                    job #{job.id}{" "}
                    <span className="text-muted-foreground">
                      · attempt {job.attempts}
                      {job.result_status ? ` · ${job.result_status}` : ""}
                    </span>
                  </span>
                  <StatusPill status={job.status} />
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Audit" empty={detail.audit.length === 0} emptyText="No actions yet.">
            <ul className="divide-y divide-border/60">
              {detail.audit.map((entry) => (
                <li key={entry.id} className="px-4 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{entry.action}</span>
                    <span className="text-xs text-muted-foreground">
                      {relativeTime(entry.created_at)}
                    </span>
                  </div>
                  {entry.detail && (
                    <p className="mt-0.5 text-xs text-muted-foreground">{entry.detail}</p>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      {/* Import modal */}
      {showImport && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => {
            setShowImport(false);
            setSummary(null);
          }}
        >
          <div
            className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-card p-5 md:p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold">Import targets</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              CSV with a <code>username</code> and/or <code>profile_url</code> column, or one
              handle per line. Duplicates and off-platform URLs are rejected before anything
              is saved.
            </p>

            <div className="mt-4 space-y-3">
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv,text/plain"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleImport(file);
                }}
                className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-foreground file:px-4 file:py-2 file:text-sm file:font-medium file:text-background"
              />
              <div className="relative text-center text-xs text-muted-foreground">or paste</div>
              <textarea
                rows={6}
                className={inputClass}
                placeholder={"username\nalice\nbob\nhttps://www.tiktok.com/@carol"}
                value={pasted}
                onChange={(e) => setPasted(e.target.value)}
              />
              <button
                onClick={() => handleImport()}
                disabled={busy || !pasted.trim()}
                className="w-full rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Importing…" : "Import pasted list"}
              </button>
            </div>

            {summary && (
              <div className="mt-5 rounded-xl border border-border p-4">
                <p className="text-sm font-medium">Import summary</p>
                <dl className="mt-2 space-y-1 text-sm">
                  <SummaryRow label="Imported" value={summary.imported} />
                  <SummaryRow label="Duplicates" value={summary.duplicates} />
                  <SummaryRow label="Invalid" value={summary.invalid} />
                  <SummaryRow label="Ready" value={summary.ready} strong />
                </dl>
                {summary.invalid_rows.length > 0 && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      Show {summary.invalid_rows.length} rejected row
                      {summary.invalid_rows.length === 1 ? "" : "s"}
                    </summary>
                    <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                      {summary.invalid_rows.map((row) => (
                        <li key={row.line}>
                          Line {row.line}: {row.reason}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}

            <button
              onClick={() => {
                setShowImport(false);
                setSummary(null);
              }}
              className="mt-5 w-full rounded-lg border border-border px-5 py-2.5 text-sm font-medium transition-colors hover:bg-muted"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled,
  primary,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex min-h-[40px] items-center gap-2 rounded-lg px-4 text-sm font-medium transition-colors disabled:opacity-40 ${
        primary
          ? "bg-foreground text-background hover:opacity-90"
          : "border border-border hover:bg-muted"
      }`}
    >
      {icon} {label}
    </button>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg bg-muted/50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold tabular-nums ${tone ?? ""}`}>
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function Panel({
  title,
  action,
  children,
  empty,
  emptyText,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  empty?: boolean;
  emptyText?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {empty ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        children
      )}
    </div>
  );
}

function SummaryRow({
  label,
  value,
  strong,
}: {
  label: string;
  value: number;
  strong?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={`tabular-nums ${strong ? "font-semibold" : ""}`}>
        {value.toLocaleString()}
      </dd>
    </div>
  );
}
