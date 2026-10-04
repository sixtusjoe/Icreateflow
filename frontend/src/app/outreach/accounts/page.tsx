"use client";

/**
 * Sending accounts — one table, two filters.
 *
 * The page used to be one section per platform. A table with a platform
 * filter says the same thing in less space and answers the question the
 * sections could not: "which of my accounts, on any platform, are in
 * trouble right now". The platform still matters — a campaign can only use
 * accounts on its own platform — so it keeps its own filter row rather
 * than being a column you have to read.
 *
 * The list re-reads itself every 15 seconds, because an account can pause
 * itself while nobody is looking.
 */

import { useEffect, useMemo, useState } from "react";
import {
  FileText,
  Info,
  KeyRound,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Smartphone,
  Timer,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import {
  deleteOutreachAccount,
  listOutreachAccounts,
  resumeOutreachAccount,
  updateOutreachAccount,
  type OutreachAccount,
} from "@/lib/api";
import {
  Avatar,
  BackLink,
  Card,
  CardBody,
  CardHead,
  Chip,
  DotsMenu,
  Empty,
  FigureLine,
  FigureStrong,
  MenuItem,
  Minis,
  MONO,
  n,
  PageActions,
  PageHead,
  PageTitle,
  PLATFORM_LABEL,
  PlatformIcon,
  PrimaryButton,
  Tabs,
  Tag,
  TD,
  TH,
  Tone,
  TwoCol,
} from "@/components/kit";
import { ConfirmDialog } from "@/components/kit/dialog";
import {
  AddAccountDialog,
  SwitchToPhoneDialog,
  ProxyDialog,
  RenameAccountDialog,
  SessionDialog,
} from "@/components/outreach/account-dialogs";
import { apiErrorMessage, relativeTime } from "@/components/kit/format";

const MAX_ACCOUNTS = 20;

/** Account status → the tone it wears. */
const STATE_TONE: Record<string, Tone> = {
  idle: "done",
  active: "live",
  paused: "pause",
  error: "stop",
};

const STATE_TABS = [
  { key: "all", label: "All" },
  { key: "enabled", label: "Enabled" },
  { key: "disabled", label: "Disabled" },
  { key: "errors", label: "With errors" },
];

export default function OutreachAccountsPage() {
  const [accounts, setAccounts] = useState<OutreachAccount[] | null>(null);
  const [state, setState] = useState("all");
  const [platform, setPlatform] = useState("all");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [sessionFor, setSessionFor] = useState<OutreachAccount | null>(null);
  const [sessionLive, setSessionLive] = useState(false);
  const [proxyFor, setProxyFor] = useState<OutreachAccount | null>(null);
  const [phoneFor, setPhoneFor] = useState<OutreachAccount | null>(null);
  const [renameFor, setRenameFor] = useState<OutreachAccount | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<OutreachAccount | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () =>
    listOutreachAccounts()
      .then(setAccounts)
      .catch((e) => {
        setAccounts([]);
        toast.error(apiErrorMessage(e, "Failed to load accounts"));
      });

  useEffect(() => {
    load();
    // An account can pause itself after repeated failures while nobody is
    // looking, and that is exactly the thing this page exists to show.
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  // `?add=1` opens the add dialog — that is how the outreach page's
  // "Add account" arrives here.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("add") === "1") setShowAdd(true);
  }, []);

  const all = accounts ?? [];
  const enabled = all.filter((a) => a.enabled);
  const disabled = all.filter((a) => !a.enabled);
  const flagged = all.filter((a) => a.consecutive_errors > 0);
  const sentTotal = all.reduce((s, a) => s + (a.messages_processed || 0), 0);
  const errTotal = all.reduce((s, a) => s + (a.error_count || 0), 0);

  const byPlatform = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of all) c[a.platform] = (c[a.platform] ?? 0) + 1;
    return Object.entries(c).sort((x, y) => y[1] - x[1]);
  }, [accounts]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((a) => {
      const okState =
        state === "all" ||
        (state === "errors" ? a.consecutive_errors > 0 : state === "enabled" ? a.enabled : !a.enabled);
      const okPlatform = platform === "all" || a.platform === platform;
      const okQuery = !q || a.name.toLowerCase().includes(q);
      return okState && okPlatform && okQuery;
    });
  }, [accounts, state, platform, query]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---------------- actions ---------------- */

  const patch = async (a: OutreachAccount, body: Parameters<typeof updateOutreachAccount>[1], msg: string) => {
    try {
      await updateOutreachAccount(a.id, body);
      await load();
      toast.success(msg);
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not update this account"));
    }
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteOutreachAccount(confirmDelete.id);
      setConfirmDelete(null);
      await load();
      toast.success("Account removed");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Failed to remove account"));
    } finally {
      setDeleting(false);
    }
  };

  const rowMenu = (a: OutreachAccount): MenuItem[] => [
    // A phone account signs in on the phone, not here.
    ...(a.via === "phone"
      ? []
      : [
          {
            label: a.has_session || a.session_reference ? "Re-login in browser" : "Sign in",
            icon: KeyRound,
            onClick: () => {
              setSessionLive(true);
              setSessionFor(a);
            },
          },
        ]),
    { label: "Rename", icon: Pencil, onClick: () => setRenameFor(a) },
    { label: "Proxy", icon: Shield, onClick: () => setProxyFor(a) },
    ...(a.platform === "tiktok"
      ? [{ label: a.via === "phone" ? "Phone settings" : "Switch to phone", icon: Smartphone, onClick: () => setPhoneFor(a) }]
      : []),
    "-",
    { label: "Sending", group: true },
    {
      label: a.enabled ? "Disable account" : "Enable account",
      icon: a.enabled ? Pause : Play,
      onClick: () => patch(a, { enabled: !a.enabled }, a.enabled ? "Account disabled" : "Account enabled"),
    },
    {
      label: a.purpose === "discovery" ? "Use for sending" : "Use for finding profiles",
      icon: Users,
      onClick: () =>
        patch(
          a,
          { purpose: a.purpose === "discovery" ? "sending" : "discovery" },
          a.purpose === "discovery"
            ? "Now used for sending messages"
            : "Now used for finding profiles — it will not be asked to send",
        ),
    },
    {
      label: "Clear error count",
      icon: Timer,
      disabled: a.status !== "paused" && a.consecutive_errors === 0,
      onClick: async () => {
        try {
          await resumeOutreachAccount(a.id);
          await load();
          toast.success("Account resumed");
        } catch (e) {
          toast.error(apiErrorMessage(e, "Failed to resume account"));
        }
      },
    },
    "-",
    { label: "Remove account", icon: Trash2, danger: true, onClick: () => setConfirmDelete(a) },
  ];

  const loading = accounts === null;
  const full = all.length >= MAX_ACCOUNTS;

  return (
    <div className="flex flex-col gap-4" data-metrics>
      <BackLink href="/outreach">Outreach</BackLink>

      <PageHead>
        <PageTitle
          title="Sending accounts"
          sub="The accounts your campaigns send from. Each one logs in through a real browser session."
        />
        <PageActions>
          <Chip icon={FileText} href="/outreach/templates">
            Templates
          </Chip>
          <PrimaryButton
            icon={Plus}
            disabled={full}
            title={full ? `The limit is ${MAX_ACCOUNTS} accounts` : undefined}
            onClick={() => setShowAdd(true)}
          >
            Add account
          </PrimaryButton>
        </PageActions>
      </PageHead>

      <TwoCol
        main={
          <Card>
            <CardHead
              title="Capacity"
              sub="What these accounts have carried, all time"
              right={
                <DotsMenu
                  label="Capacity options"
                  items={[
                    { label: "Refresh", icon: RefreshCw, onClick: () => void load() },
                    {
                      label: "Clear all error counts",
                      icon: Timer,
                      disabled: flagged.length === 0,
                      onClick: async () => {
                        try {
                          await Promise.all(flagged.map((a) => resumeOutreachAccount(a.id)));
                          await load();
                          toast.success(`${flagged.length} account${flagged.length === 1 ? "" : "s"} resumed`);
                        } catch (e) {
                          toast.error(apiErrorMessage(e, "Could not clear them all"));
                        }
                      },
                    },
                  ]}
                />
              }
            />
            <CardBody>
              <FigureLine value={n(sentTotal)}>
                messages sent · <FigureStrong>{n(errTotal)}</FigureStrong> failed tries along the way
              </FigureLine>
              <Minis
                cells={[
                  { label: "ACCOUNTS", value: all.length },
                  { label: "ENABLED", value: enabled.length },
                  { label: "DISABLED", value: disabled.length },
                  { label: "IDLE", value: all.filter((a) => a.status === "idle").length },
                  { label: "FLAGGED", value: flagged.length },
                ]}
              />
              <p className="mt-4 flex items-start gap-[7px] text-[11px] leading-[1.5] text-subtle">
                <Info className="mt-0.5 h-3 w-3 flex-none" />
                A failed try is one attempt, not one lost target — a target that succeeds on its third go
                counts two. An account auto-pauses after repeated failures, so one bad session cannot burn a
                whole campaign; clearing its count puts it back in rotation.
              </p>
            </CardBody>
          </Card>
        }
        rail={
          <Card>
            <CardHead
              title="By platform"
              sub="A campaign can only use accounts on its own platform"
              right={
                <DotsMenu
                  label="By platform options"
                  items={[{ label: "Add account", icon: Plus, onClick: () => setShowAdd(true) }]}
                />
              }
            />
            <CardBody className="pt-2.5">
              {byPlatform.length === 0 ? (
                <p className="py-1 text-[12.5px] leading-[1.55] text-subtle">No accounts yet.</p>
              ) : (
                byPlatform.map(([p, c]) => (
                  <div key={p} className="flex items-center gap-[11px] border-b border-line-2 py-[9px] last:border-b-0">
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
            </CardBody>
          </Card>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Tabs
          value={platform}
          onChange={setPlatform}
          items={[
            { key: "all", label: "All", count: all.length },
            ...byPlatform.map(([p, c]) => ({
              key: p,
              label: PLATFORM_LABEL[p] ?? p,
              count: c,
              icon: ({ className }: { className?: string }) => <PlatformIcon platform={p} className={className} />,
            })),
          ]}
        />
        <span className="h-6 w-px bg-border" />
        <Tabs
          value={state}
          onChange={setState}
          items={STATE_TABS.map((t) => ({
            key: t.key,
            label: t.label,
            count:
              t.key === "all"
                ? all.length
                : t.key === "enabled"
                  ? enabled.length
                  : t.key === "disabled"
                    ? disabled.length
                    : flagged.length,
          }))}
        />
        <div className="ml-auto">
          {searching || query ? (
            <div className="flex items-center gap-[7px] rounded-[11px] border border-border bg-card px-[13px] py-2 shadow-card">
              <Search className="h-3.5 w-3.5 flex-none text-subtle" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onBlur={() => !query && setSearching(false)}
                placeholder="Search accounts"
                className="w-[150px] border-0 bg-transparent text-[12.5px] leading-normal text-foreground outline-none placeholder:text-subtle"
              />
            </div>
          ) : (
            <Chip icon={Search} onClick={() => setSearching(true)}>
              Search accounts
            </Chip>
          )}
        </div>
      </div>

      <Card>
        {loading ? (
          <div className="p-4 text-[12.5px] leading-normal text-subtle">Loading accounts…</div>
        ) : rows.length === 0 ? (
          <Empty
            icon={Users}
            title={all.length === 0 ? "No accounts yet" : "No accounts match"}
            action={
              all.length === 0 ? (
                <PrimaryButton icon={Plus} onClick={() => setShowAdd(true)}>
                  Add account
                </PrimaryButton>
              ) : undefined
            }
          >
            {all.length === 0
              ? "A campaign needs at least one enabled account to send from."
              : "Nothing here on this platform in this state. Widen a filter, or add an account."}
          </Empty>
        ) : (
          <div className="overflow-x-auto px-1.5 pb-2 pt-4">
            <table className="w-full table-fixed border-collapse">
              <thead>
                <tr>
                  <th className={TH}>Account</th>
                  <th className={`${TH} w-[106px] max-md:hidden`}>Platform</th>
                  <th className={`${TH} w-[104px] max-md:w-[92px]`}>State</th>
                  <th className={`${TH} w-[92px] text-right max-md:hidden`}>Sent</th>
                  <th className={`${TH} w-[124px] text-right max-md:hidden`}>Failed tries</th>
                  <th className={`${TH} w-[126px] pl-[18px] max-md:hidden`}>Last active</th>
                  <th className={`${TH} w-[74px] max-md:w-[58px]`}>Sending</th>
                  <th className={`${TH} w-[44px]`} />
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const hot = a.consecutive_errors > 0;
                  return (
                    <tr key={a.id} className="transition-colors last:[&>td]:border-b-0 hover:bg-secondary">
                      <td className={TD}>
                        <div className="flex min-w-0 items-center gap-[11px]">
                          <Avatar platform={a.platform} />
                          <span className="flex min-w-0 flex-col gap-px">
                            <span className="truncate font-semibold text-foreground">{a.name}</span>
                            <span className="truncate text-[11px] leading-normal text-subtle">
                              {a.purpose === "discovery" ? "Finding profiles · " : ""}
                              {a.via === "phone"
                                ? phoneLine(a)
                                : a.has_session || a.session_reference
                                  ? a.session_reference || "session stored"
                                  : "no session"}
                            </span>
                            {/* Phones drop the Sent and Failed columns, so the counts ride under the name. */}
                            <span className={`truncate text-[11px] leading-normal md:hidden ${hot ? "font-semibold text-bad" : "text-subtle"}`}>
                              {n(a.messages_processed)} sent · {n(a.error_count)} failed
                            </span>
                          </span>
                        </div>
                      </td>
                      <td className={`${TD} text-xs font-semibold text-muted-foreground max-md:hidden`}>
                        {PLATFORM_LABEL[a.platform] ?? a.platform}
                      </td>
                      <td className={TD}>
                        <Tag tone={a.enabled ? (STATE_TONE[a.status] ?? "queue") : "draft"}>
                          {a.enabled ? a.status[0].toUpperCase() + a.status.slice(1) : "Off"}
                        </Tag>
                      </td>
                      <td className={`${TD} ${MONO} text-right max-md:hidden`}>{n(a.messages_processed)}</td>
                      <td className={`${TD} text-right max-md:hidden`}>
                        <span
                          className={`inline-flex flex-col items-end ${MONO} ${
                            hot ? "font-bold text-bad" : "text-subtle"
                          }`}
                        >
                          {n(a.error_count)}
                          {hot && (
                            <em className="font-sans text-[10px] font-semibold not-italic opacity-85">
                              +{a.consecutive_errors} in a row
                            </em>
                          )}
                        </span>
                      </td>
                      <td className={`${TD} pl-[18px] text-xs text-subtle max-md:hidden`}>{relativeTime(a.last_activity_at)}</td>
                      <td className={TD}>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={a.enabled}
                          aria-label={`${a.enabled ? "Disable" : "Enable"} ${a.name}`}
                          onClick={() =>
                            patch(a, { enabled: !a.enabled }, a.enabled ? "Account disabled" : "Account enabled")
                          }
                          className={`inline-flex h-[18px] w-8 items-center rounded-full p-0.5 transition-colors ${
                            a.enabled ? "bg-chart-1" : "bg-border"
                          }`}
                        >
                          <i
                            className={`h-3.5 w-3.5 rounded-full bg-card shadow-[0_1px_2px_rgba(16,24,40,0.3)] transition-transform ${
                              a.enabled ? "translate-x-[14px]" : ""
                            }`}
                          />
                        </button>
                      </td>
                      <td className={`${TD} text-right`}>
                        <DotsMenu label={`Actions for ${a.name}`} items={rowMenu(a)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <AddAccountDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        defaultPlatform={platform === "all" ? "tiktok" : platform}
        onCreated={(made, signIn) => {
          setShowAdd(false);
          void load();
          toast.success(`“${made.name}” added — it needs a session before it can send`);
          // The account row has to exist before a session can hang off it,
          // so step two starts here rather than inside the add dialog.
          setSessionLive(signIn);
          setSessionFor(made);
        }}
      />

      <SessionDialog
        account={sessionFor}
        startLive={sessionLive}
        onClose={() => setSessionFor(null)}
        onSaved={load}
      />

      <ProxyDialog account={proxyFor} onClose={() => setProxyFor(null)} onSaved={load} />
      <SwitchToPhoneDialog account={phoneFor} onClose={() => setPhoneFor(null)} onSaved={load} />

      <RenameAccountDialog account={renameFor} onClose={() => setRenameFor(null)} onSaved={load} />

      <ConfirmDialog
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        onConfirm={doDelete}
        title="Remove sending account?"
        confirmLabel="Remove account"
        busy={deleting}
        body={
          <>
            <b className="font-bold text-foreground">“{confirmDelete?.name}”</b> and its stored session are deleted.
            Campaigns it was assigned to keep running from whatever else is assigned.
          </>
        }
        bullets={[
          `Its ${n(confirmDelete?.messages_processed)} sent messages keep their history — nothing already delivered is undone`,
          "The encrypted browser session is destroyed; signing in again means a fresh capture",
          "Any campaign left with no eligible account will fail to start until one is assigned",
        ]}
      />
    </div>
  );
}

/** Under a phone account's name: which TikTok user, and whether the app has linked it. */
function phoneLine(a: OutreachAccount): string {
  const who = a.device_handle ? `@${a.device_handle}` : "no username";
  if (!a.companion_device) return `Phone · ${who} · waiting for the app to link it`;
  if (!a.companion_seen_at) return `Phone · ${who} · linked`;
  const mins = Math.max(0, Math.round((Date.now() - new Date(a.companion_seen_at).getTime()) / 60000));
  const seen = mins < 1 ? "just now" : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
  return `Phone · ${who} · seen ${seen}`;
}
