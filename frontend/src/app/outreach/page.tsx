"use client";

/**
 * Outreach — every campaign, and the state of the queue behind them.
 *
 * Three reads fill it and each renders independently, so a slow or failed
 * call leaves the rest of the page standing: `listOutreachCampaigns` for
 * the table, `getOutreachSummary` for the pipeline, `listOutreachAccounts`
 * for the rail and for the platform counts the New Campaign dialog shows.
 *
 * The page has no search field, theme button, bell or avatar — those are
 * session controls and they live in the sidebar now, not on top of every
 * page.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Download,
  Eye,
  FileText,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  Square,
  Trash2,
  Upload,
  UserMinus,
  Users,
  MessageCircle,
  MessageSquare,
} from "lucide-react";
import { toast } from "sonner";
import {
  createOutreachCampaign,
  deleteOutreachCampaign,
  downloadOutreachResults,
  getOutreachSummary,
  listOutreachAccounts,
  listOutreachCampaigns,
  listOutreachTemplates,
  pauseOutreachCampaign,
  resumeOutreachCampaign,
  startOutreachCampaign,
  stopOutreachCampaign,
  type OutreachAccount,
  type OutreachCampaign,
  type OutreachTemplate,
} from "@/lib/api";
import {
  Avatar,
  Card,
  CardBody,
  CardHead,
  CAMPAIGN_TONE,
  Chip,
  ChipCount,
  DotsMenu,
  Empty,
  FigureLine,
  FigureStrong,
  Legend,
  Minis,
  MONO,
  n,
  Note,
  PageActions,
  PageHead,
  PageTitle,
  PLATFORM_LABEL,
  PrimaryButton,
  Progress,
  RailLink,
  SelectChip,
  Skeleton,
  StackBar,
  Tabs,
  Tag,
  TD,
  TH,
  TwoCol,
  type Band,
  type MenuItem,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import { NewCampaignDialog } from "@/components/outreach/new-campaign-dialog";
import { campaignPath } from "@/components/outreach/campaign-url";
import { apiErrorMessage } from "@/components/kit/format";

const ACTIVITY = {
  message: { label: "Message", icon: MessageCircle },
  follow: { label: "Follow", icon: Users },
  unfollow: { label: "Unfollow", icon: UserMinus },
  comment: { label: "Comment", icon: MessageSquare },
} as const;

const STATUS_TABS = ["all", "running", "paused", "draft", "stopped", "completed"] as const;

const PLATFORM_FILTER = [
  { key: "all", label: "All platforms" },
  { key: "instagram", label: "Instagram" },
  { key: "tiktok", label: "TikTok" },
  { key: "x", label: "X" },
];

const SORTS = [
  { key: "new", label: "Newest first" },
  { key: "old", label: "Oldest first" },
  { key: "targets", label: "Most targets" },
  { key: "sent", label: "Most delivered" },
];

type Summary = {
  targets: Record<string, number>;
  total_targets: number;
  attempted: number;
  delivery_rate: number;
};

/**
 * Campaigns per page.
 *
 * The campaign list used to render whole — fine at a dozen, a card the
 * length of the page at two hundred. Eight keeps the table inside one
 * screen alongside the pipeline cards and the filter bar, so the pager
 * is in reach rather than stranded at the bottom of a list nobody
 * scrolls. It also means the pager is there to be seen at the dozen
 * campaigns this account actually has: a page size the list never
 * reaches is a control nobody knows exists. The campaign detail page
 * pages its targets at twenty, against a taller rail.
 *
 * Paging happens here, not on the server: the filters and the sort are
 * already client-side over the full array. At a few thousand campaigns
 * this wants `limit`/`offset` and the filters moved into SQL.
 */
const PAGE_SIZE = 8;

export default function OutreachPage() {
  const router = useRouter();
  const [campaigns, setCampaigns] = useState<OutreachCampaign[] | null>(null);
  const [accounts, setAccounts] = useState<OutreachAccount[]>([]);
  const [templates, setTemplates] = useState<OutreachTemplate[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [status, setStatus] = useState<string>("all");
  const [platform, setPlatform] = useState("all");
  const [sort, setSort] = useState("new");
  const [page, setPage] = useState(0);
  const [showNew, setShowNew] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<OutreachCampaign | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const loadCampaigns = () =>
    listOutreachCampaigns()
      .then(setCampaigns)
      .catch(() => {
        setCampaigns([]);
        toast.error("Failed to load campaigns");
      });

  const loadSummary = () => getOutreachSummary().then(setSummary).catch(() => {});

  useEffect(() => {
    loadCampaigns();
    loadSummary();
    listOutreachAccounts().then(setAccounts).catch(() => {});
    listOutreachTemplates().then(setTemplates).catch(() => {});
  }, []);

  /* ---------------- pipeline ---------------- */

  const t = summary?.targets ?? {};
  const bands: Band[] = [
    { label: "Queued", value: (t.queued ?? 0) + (t.processing ?? 0), color: "var(--chart-1)" },
    { label: "Sent", value: t.sent ?? 0, color: "var(--chart-2)" },
    {
      label: "Held, skipped & failed",
      value: (t.paused ?? 0) + (t.skipped ?? 0) + (t.failed ?? 0),
      color: "var(--chart-3)",
    },
  ];
  const rate = (summary?.delivery_rate ?? 0) * 100;

  /* ---------------- accounts rail ---------------- */

  const byPlatform = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of accounts) c[a.platform] = (c[a.platform] ?? 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [accounts]);
  const enabledCount = accounts.filter((a) => a.enabled).length;
  const hotCount = accounts.filter((a) => a.consecutive_errors > 0).length;

  /* ---------------- table ---------------- */

  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const x of campaigns ?? []) c[x.status] = (c[x.status] ?? 0) + 1;
    return c;
  }, [campaigns]);

  const rows = useMemo(() => {
    const list = (campaigns ?? []).filter(
      (c) => (status === "all" || c.status === status) && (platform === "all" || c.platform === platform),
    );
    const by: Record<string, (a: OutreachCampaign, b: OutreachCampaign) => number> = {
      new: (a, b) => b.created_at.localeCompare(a.created_at),
      old: (a, b) => a.created_at.localeCompare(b.created_at),
      targets: (a, b) => (b.total_targets ?? 0) - (a.total_targets ?? 0),
      sent: (a, b) => (b.successful_count ?? 0) - (a.successful_count ?? 0),
    };
    return [...list].sort(by[sort]);
  }, [campaigns, status, platform, sort]);

  // Clamped rather than corrected: deleting the last campaign on the last
  // page leaves `page` pointing past the end, and a render that fixes it
  // by setting state paints an empty table first.
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const from = current * PAGE_SIZE;
  const shown = rows.slice(from, from + PAGE_SIZE);

  /* ---------------- actions ---------------- */

  /** Run controls. Each one refreshes both the row and the pipeline,
   *  because starting a campaign moves targets out of `queued`. */
  const run = async (c: OutreachCampaign, verb: "start" | "pause" | "resume" | "stop") => {
    setBusy(c.id);
    const call = { start: startOutreachCampaign, pause: pauseOutreachCampaign, resume: resumeOutreachCampaign, stop: stopOutreachCampaign }[verb];
    try {
      await call(c.id);
      await Promise.all([loadCampaigns(), loadSummary()]);
      toast.success(`“${c.name}” ${verb === "stop" ? "stopped" : verb === "pause" ? "paused" : verb === "resume" ? "resumed" : "started"}`);
    } catch (e) {
      toast.error(apiErrorMessage(e, `Could not ${verb} the campaign`));
    } finally {
      setBusy(null);
    }
  };

  const exportCsv = async (c: OutreachCampaign) => {
    try {
      const blob = await downloadOutreachResults(c.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${c.name.replace(/[^\w.-]+/g, "_")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not export"));
    }
  };

  /** A copy of the setup, never of the targets or the results — those
   *  belong to the run that produced them. */
  const duplicate = async (c: OutreachCampaign) => {
    try {
      const made = await createOutreachCampaign({
        name: `${c.name} (copy)`,
        description: c.description ?? undefined,
        platform: c.platform,
        activity: c.activity,
        ...(c.activity === "message" ? { message_template: c.message_template, template_id: c.template_id } : {}),
        ...(c.activity === "comment"
          ? {
              target_url: c.target_url ?? undefined,
              comment_count: c.comment_count,
              comment_variations: c.comment_variations,
            }
          : {}),
        max_jobs: c.max_jobs,
        max_jobs_per_account: c.max_jobs_per_account,
        retry_limit: c.retry_limit,
      });
      await loadCampaigns();
      toast.success(`“${made.name}” created — no targets copied`);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not duplicate"));
    }
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachCampaign(confirmDelete.id);
      setConfirmDelete(null);
      await Promise.all([loadCampaigns(), loadSummary()]);
      toast.success("Campaign deleted");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to delete"));
    } finally {
      setDeleting(false);
    }
  };

  /** What a row offers depends on where the campaign is. */
  const rowMenu = (c: OutreachCampaign): MenuItem[] => {
    const items: MenuItem[] = [{ label: "Open campaign", icon: Eye, href: campaignPath(c), kbd: "↵" }];
    const runs: MenuItem[] = [];
    if (c.status === "draft" || c.status === "stopped")
      runs.push({ label: "Start campaign", icon: Play, onClick: () => run(c, "start"), disabled: busy === c.id });
    if (c.status === "running")
      runs.push(
        { label: "Pause", icon: Pause, onClick: () => run(c, "pause"), disabled: busy === c.id },
        { label: "Stop", icon: Square, onClick: () => run(c, "stop"), disabled: busy === c.id },
      );
    if (c.status === "paused")
      runs.push(
        { label: "Resume", icon: Play, onClick: () => run(c, "resume"), disabled: busy === c.id },
        { label: "Stop", icon: Square, onClick: () => run(c, "stop"), disabled: busy === c.id },
      );
    if (runs.length) items.push("-", { label: "Run", group: true }, ...runs);
    items.push(
      "-",
      { label: "Targets", group: true },
      { label: "Import targets", icon: Upload, href: `${campaignPath(c)}?import=1` },
      { label: "Export as CSV", icon: Download, onClick: () => exportCsv(c) },
      "-",
      { label: "Duplicate", icon: Copy, onClick: () => duplicate(c) },
      { label: "Delete campaign", icon: Trash2, danger: true, onClick: () => setConfirmDelete(c) },
    );
    return items;
  };

  const loading = campaigns === null;

  return (
    <div className="flex flex-col gap-4" data-metrics>
      <PageHead>
        <PageTitle
          title="Outreach"
          sub="Import creator lists, queue DMs, and watch them go out across your sending accounts."
        />
        <PageActions>
          <Chip icon={Users} href="/outreach/accounts">
            Accounts
            <ChipCount>{accounts.length}</ChipCount>
          </Chip>
          <Chip icon={FileText} href="/outreach/templates">
            Templates
          </Chip>
          <PrimaryButton icon={Plus} onClick={() => setShowNew(true)}>
            New Campaign
          </PrimaryButton>
        </PageActions>
      </PageHead>

      <TwoCol
        main={
          // Both cards fill the row, so the pair ends level whichever of
          // the two happens to be carrying more.
          <Card className="flex flex-1 flex-col">
            <CardHead
              title="Target pipeline"
              sub={
                loading
                  ? "Counting…"
                  : `Every target across ${n(campaigns.length)} campaign${campaigns.length === 1 ? "" : "s"}, by state`
              }
              right={
                <DotsMenu
                  label="Target pipeline options"
                  items={[
                    { label: "Refresh counts", icon: RefreshCw, onClick: () => void loadSummary() },
                    { label: "Manage accounts", icon: Users, href: "/outreach/accounts" },
                  ]}
                />
              }
            />
            <CardBody className="flex flex-1 flex-col">
              {summary ? (
                <>
                  <FigureLine value={n(summary.total_targets)}>
                    targets · <FigureStrong>{rate.toFixed(1)}%</FigureStrong> of {n(summary.attempted)} attempted were
                    delivered
                  </FigureLine>
                  <StackBar bands={bands} total={summary.total_targets} />
                  <Legend bands={bands} />
                  <Minis
                    className="mt-auto"
                    cells={[
                      { label: "QUEUED", value: t.queued ?? 0 },
                      { label: "SENT", value: t.sent ?? 0 },
                      { label: "HELD", value: t.paused ?? 0 },
                      { label: "SKIPPED", value: t.skipped ?? 0 },
                      { label: "FAILED", value: t.failed ?? 0 },
                    ]}
                  />
                </>
              ) : (
                <div className="flex flex-col gap-3">
                  <Skeleton className="h-[34px] w-[260px]" />
                  <Skeleton className="h-2.5 w-full" />
                  <Skeleton className="h-[52px] w-full" />
                </div>
              )}
            </CardBody>
          </Card>
        }
        rail={
          <Card className="flex flex-1 flex-col">
            <CardHead
              title="Sending accounts"
              sub={`${enabledCount} enabled${hotCount ? ` · ${hotCount} with recent errors` : ""}`}
              right={
                <DotsMenu
                  label="Sending accounts options"
                  items={[
                    { label: "Add account", icon: Plus, href: "/outreach/accounts?add=1" },
                    { label: "Manage accounts", icon: Users, href: "/outreach/accounts" },
                  ]}
                />
              }
            />
            <CardBody className="flex flex-1 flex-col pt-2.5">
              {byPlatform.length === 0 ? (
                <p className="py-1 text-[12.5px] leading-[1.55] text-subtle">
                  No sending accounts yet. A campaign needs at least one enabled account to send from.
                </p>
              ) : (
                byPlatform.map(([p, c]) => (
                  <div key={p} className="flex items-center gap-[11px] border-b border-line-2 py-2 last:border-b-0">
                    <Avatar platform={p} />
                    <span className="text-[13px] font-semibold leading-normal text-foreground">
                      {PLATFORM_LABEL[p] ?? p}
                    </span>
                    <span className="ml-auto text-[13px] font-extrabold tabular-nums leading-normal text-foreground">
                      {c}
                    </span>
                  </div>
                ))
              )}
              <RailLink icon={ArrowRight} href="/outreach/accounts" className="mt-auto">
                Manage accounts
              </RailLink>
            </CardBody>
          </Card>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Tabs
          value={status}
          // A different filter is a different list. Page 4 of it may not
          // exist, and page 4 of the old one is not where anyone wants to
          // land, so every control that reshapes the list goes back to one.
          onChange={(v) => {
            setStatus(v);
            setPage(0);
          }}
          items={STATUS_TABS.map((k) => ({
            key: k,
            label: k === "all" ? "All" : k[0].toUpperCase() + k.slice(1),
            count: k === "all" ? (campaigns?.length ?? 0) : (statusCounts[k] ?? 0),
          }))}
        />
        <div className="ml-auto flex items-center gap-2">
          <SelectChip
            label="Platform"
            value={platform}
            options={PLATFORM_FILTER}
            onChange={(v) => {
              setPlatform(v);
              setPage(0);
            }}
          />
          <SelectChip
            label="Sort"
            value={sort}
            options={SORTS}
            onChange={(v) => {
              setSort(v);
              setPage(0);
            }}
          />
        </div>
      </div>

      <Card>
        {loading ? (
          <div className="flex flex-col gap-2 p-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[57px] w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <Empty
            icon={Send}
            title={campaigns.length === 0 ? "No campaigns yet" : "No campaigns in this state"}
            action={
              campaigns.length === 0 ? (
                <PrimaryButton icon={Plus} onClick={() => setShowNew(true)}>
                  New Campaign
                </PrimaryButton>
              ) : undefined
            }
          >
            {campaigns.length === 0
              ? "Create one, import a list of profiles, then press Start."
              : "Change the filter, or start a new campaign."}
          </Empty>
        ) : (
          <div className="overflow-x-auto px-1.5 pb-2 pt-4">
            <table className="w-full table-fixed border-collapse">
              <thead>
                <tr>
                  <th className={TH}>Campaign</th>
                  <th className={`${TH} w-[118px]`}>Activity</th>
                  <th className={`${TH} w-[92px] text-right`}>Targets</th>
                  <th className={`${TH} w-[168px] pl-[18px]`}>Delivered</th>
                  <th className={`${TH} w-[78px] text-right`}>Sent</th>
                  <th className={`${TH} w-[74px] text-right`}>Failed</th>
                  <th className={`${TH} w-[118px] pl-[18px]`}>Status</th>
                  <th className={`${TH} w-[44px]`} />
                </tr>
              </thead>
              <tbody>
                {shown.map((c) => {
                  const total = c.total_targets ?? 0;
                  const ok = c.successful_count ?? 0;
                  const act = ACTIVITY[c.activity] ?? ACTIVITY.message;
                  return (
                    <tr
                      key={c.id}
                      onClick={() => router.push(campaignPath(c))}
                      className="cursor-pointer transition-colors last:[&>td]:border-b-0 hover:bg-secondary"
                    >
                      <td className={TD}>
                        <div className="flex min-w-0 items-center gap-[11px]">
                          <Avatar platform={c.platform} />
                          <span className="flex min-w-0 flex-col gap-px">
                            <span className="truncate font-semibold text-foreground">{c.name}</span>
                            <span className="truncate text-[11px] leading-normal text-subtle">
                              {c.description || `Created ${c.created_at.slice(0, 10)}`}
                            </span>
                          </span>
                        </div>
                      </td>
                      <td className={TD}>
                        <span className="inline-flex items-center gap-1.5 text-xs font-semibold leading-normal text-muted-foreground">
                          <act.icon className="h-[13px] w-[13px] text-subtle" />
                          {act.label}
                        </span>
                      </td>
                      <td className={`${TD} ${MONO} text-right`}>{n(total)}</td>
                      <td className={`${TD} pl-[18px]`}>
                        <Progress pct={total ? (ok / total) * 100 : 0} />
                      </td>
                      <td className={`${TD} ${MONO} text-right font-extrabold`}>{n(ok)}</td>
                      <td className={`${TD} ${MONO} text-right text-subtle`}>{n(c.failed_count)}</td>
                      <td className={`${TD} pl-[18px]`}>
                        <Tag tone={CAMPAIGN_TONE[c.status] ?? "draft"}>
                          {c.status[0].toUpperCase() + c.status.slice(1)}
                        </Tag>
                      </td>
                      <td className={`${TD} text-right`} onClick={(e) => e.stopPropagation()}>
                        <DotsMenu label={`Actions for ${c.name}`} items={rowMenu(c)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {rows.length > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line-2 px-5 pb-4 pt-3 text-[11.5px] leading-normal text-subtle">
            <span className="tabular-nums">
              {(from + 1).toLocaleString()}&ndash;{Math.min(from + PAGE_SIZE, rows.length).toLocaleString()} of{" "}
              {rows.length.toLocaleString()}
            </span>
            <span className="flex gap-[7px]">
              <button
                type="button"
                aria-label="Previous page"
                onClick={() => setPage(Math.max(0, current - 1))}
                disabled={current === 0}
                className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:bg-card"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Next page"
                onClick={() => setPage(current + 1)}
                disabled={current + 1 >= pageCount}
                className="grid h-[30px] w-[30px] place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:bg-card"
              >
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        )}
      </Card>

      <Note>
        Delivered is measured against messages actually sent, not targets processed — a skipped or failed target is not
        a delivery.
      </Note>

      <NewCampaignDialog
        open={showNew}
        onClose={() => setShowNew(false)}
        accounts={accounts}
        templates={templates}
        onCreated={(c) => {
          setShowNew(false);
          toast.success(`Campaign “${c.name}” created`);
          router.push(campaignPath(c));
        }}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        onConfirm={doDelete}
        title="Delete campaign?"
        confirmLabel="Delete campaign"
        confirmText={confirmDelete?.name}
        busy={deleting}
        body={
          <>
            <b className="font-bold text-foreground">“{confirmDelete?.name}”</b> is removed for good, along with
            everything it produced. This cannot be undone.
          </>
        }
        bullets={[
          `${n(confirmDelete?.total_targets)} imported targets, including the ${n(confirmDelete?.successful_count)} already delivered`,
          "Every job, result and error message from its runs",
          "Its entry in the audit log",
        ]}
      />
    </div>
  );
}
