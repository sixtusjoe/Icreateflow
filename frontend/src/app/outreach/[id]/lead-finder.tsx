"use client";

/**
 * Find profiles to contact, instead of pasting a list you already have.
 *
 * Three steps, deliberately not one: describe who you want, watch it look,
 * then choose from what it found. Nothing reaches the campaign until the
 * last step — a search that comes back with rubbish should cost a glance,
 * not a cleanup.
 *
 * The two ways in are genuinely different searches, so they are a segment
 * rather than a pile of optional fields: reading a post's audience ignores
 * the description entirely, and reading a description ignores the options
 * under the seed box. Showing only the half that applies is the difference
 * between a form and a guess.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Search, Sparkles, Square } from "lucide-react";
import { toast } from "sonner";
import {
  cancelLeadSearch,
  getLeadSearch,
  getLeadSearchAvailability,
  importLeads,
  listLeads,
  listOutreachCampaigns,
  listPendingLeads,
  startLeadSearch,
  type Lead,
  type LeadSearchAvailability,
  type LeadSearchRun,
  type OutreachCampaign,
} from "@/lib/api";
import {
  Checkbox,
  Dialog,
  DialogBody,
  DialogFoot,
  DialogHead,
  Field,
  FieldLabel,
  GhostButton,
  Hint,
  Input,
  Radio,
  Steps,
  Textarea,
} from "@/components/kit/dialog";
import { Avatar, Empty, PrimaryButton, Tabs, n } from "@/components/kit";
import { apiErrorMessage } from "@/components/kit/format";

/**
 * A link to a post, on any of the three platforms. This is the same
 * expression as `discovery._POST_URL`, which is what actually decides —
 * a looser or stricter copy here would describe one thing while the
 * server did another (a tiktok.com/t/ short link, for instance).
 */
const POST_LINK = /https?:\/\/\S*\/(video|reel|p|status)\/|tiktok\.com\/t\//i;

export function LeadFinderDialog({
  open,
  onClose,
  campaignId,
  platform,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  campaignId: number;
  platform: string;
  onImported: () => void;
}) {
  const [availability, setAvailability] = useState<LeadSearchAvailability | null>(null);
  const [mode, setMode] = useState<"seeds" | "niche">("seeds");
  const [niche, setNiche] = useState("");
  const [seeds, setSeeds] = useState("");
  const [location, setLocation] = useState("");
  const [interests, setInterests] = useState("");
  const [wanted, setWanted] = useState(50);
  const [commenters, setCommenters] = useState(true);
  const [likers, setLikers] = useState(false);
  const [replies, setReplies] = useState(true);
  const [enrich, setEnrich] = useState(false);
  const [accountId, setAccountId] = useState<number | undefined>();
  const [run, setRun] = useState<LeadSearchRun | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [campaigns, setCampaigns] = useState<OutreachCampaign[]>([]);
  const [pending, setPending] = useState(0);
  const [targets, setTargets] = useState<Set<number>>(new Set([campaignId]));

  useEffect(() => {
    if (!open) return;
    getLeadSearchAvailability(platform)
      .then((a) => {
        setAvailability(a);
        // The first account not already busy searching.
        const free = a.accounts.find((x) => !x.busy) ?? a.accounts[0];
        if (free) setAccountId(free.id);
      })
      .catch(() => setAvailability(null));
  }, [platform, open]);

  // Which campaigns the results can be split between — same platform only.
  useEffect(() => {
    if (!open) return;
    listOutreachCampaigns()
      .then((all) => setCampaigns(all.filter((c) => c.platform === platform)))
      .catch(() => setCampaigns([]));
  }, [platform, open]);

  // Anything found before and never imported is stranded: searches skip it
  // as already found, and no campaign holds it.
  useEffect(() => {
    if (!open) return;
    listPendingLeads(platform)
      .then((p) => setPending(p.length))
      .catch(() => setPending(0));
  }, [platform, open, leads.length]);

  const loadLeads = useCallback(async (searchId: number) => {
    try {
      const found = await listLeads(searchId);
      setLeads(found);
      // Everything, always. A score is an opinion about a bio that may be
      // missing, in another language, or simply wrong — using it to decide
      // what gets ticked means quietly dropping people who were worth
      // contacting. It sorts the list and shows a number; the choosing is
      // the operator's.
      setChosen(new Set(found.map((l) => l.id)));
    } catch {
      /* the run's own message already says what happened */
    }
  }, []);

  // A search takes minutes and outlives the request that started it.
  useEffect(() => {
    if (!run || run.done) return;
    const iv = setInterval(async () => {
      try {
        const next = await getLeadSearch(run.search_id);
        if (next.run) setRun(next.run);
        if (next.run?.done) {
          await loadLeads(run.search_id);
          if (next.run.status === "failed") toast.error(next.run.message);
        }
      } catch {
        /* a dropped poll is not a failed search */
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [run, loadLeads]);

  const postLinks = useMemo(() => seeds.split(/[\s,]+/).filter((s) => POST_LINK.test(s)), [seeds]);
  const seedsArePosts = postLinks.length > 0;
  const account = availability?.accounts.find((a) => a.id === accountId);
  const running = run !== null && !run.done;
  const step = leads.length > 0 ? 2 : running ? 1 : 0;

  const showPending = async () => {
    try {
      const found = await listPendingLeads(platform);
      setLeads(found);
      setChosen(new Set(found.map((l) => l.id)));
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not load those"));
    }
  };

  const handleStart = async () => {
    if (!niche.trim() && !seeds.trim())
      return toast.error("Describe who you want, or name accounts to read");
    setBusy(true);
    setLeads([]);
    setChosen(new Set());
    try {
      const started = await startLeadSearch(campaignId, {
        niche: mode === "niche" ? niche.trim() : "",
        seed_accounts: mode === "seeds" ? seeds.trim() || undefined : undefined,
        location: location.trim() || undefined,
        interests: interests.trim() || undefined,
        wanted,
        platform,
        account_id: accountId,
        include_commenters: commenters,
        include_likers: likers,
        include_replies: replies,
        enrich_profiles: enrich,
      });
      setRun(started);
      toast.success("Searching — a browser window is open, you can watch it");
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not start the search"));
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async () => {
    if (chosen.size === 0) return toast.error("Pick at least one profile");
    setBusy(true);
    try {
      const summary = await importLeads(campaignId, [...chosen], [...targets]);
      toast.success(
        summary.campaigns && summary.campaigns.length > 1
          ? summary.campaigns.map((c) => `${c.ready} to ${c.campaign_name}`).join(", ")
          : `${summary.ready} target(s) added`,
      );
      setLeads([]);
      setRun(null);
      onImported();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not import those leads"));
    } finally {
      setBusy(false);
    }
  };

  const canStart = mode === "seeds" ? !!seeds.trim() : !!niche.trim();

  return (
    <Dialog open={open} onClose={onClose} label="Find profiles" size="lg">
      <DialogHead
        title="Find profiles"
        sub="A discovery account reads real posts and collects who engaged. Nothing reaches this campaign until you pick from what it finds."
        onClose={onClose}
      />

      {availability && !availability.available ? (
        <DialogBody>
          <Empty icon={Search} title="Discovery is not available">
            {availability.unavailable_reason}
          </Empty>
        </DialogBody>
      ) : (
        <>
          <Steps steps={["Set up", "Searching", "Review"]} current={step} />

          {/* ---- 1. set up ------------------------------------------- */}
          {step === 0 && (
            <DialogBody>
              {availability && availability.accounts.length > 0 && (
                <>
                  <FieldLabel>Search from</FieldLabel>
                  <div className="flex flex-col gap-2">
                    {availability.accounts.map((a) => (
                      <Radio
                        key={a.id}
                        checked={a.id === accountId}
                        onChange={() => setAccountId(a.id)}
                        disabled={a.busy}
                      >
                        <span className="truncate text-[13px] font-semibold leading-normal text-foreground">
                          {a.name}
                        </span>
                        <span className="truncate text-[11px] leading-normal text-subtle">
                          {a.busy
                            ? "Running a search right now"
                            : `${n(a.used_today)} opened in the last 24 hours`}
                        </span>
                      </Radio>
                    ))}
                  </div>
                  <Hint>
                    A discovery account is separate from your senders, so looking around never spends a sending
                    account&apos;s budget.
                  </Hint>
                </>
              )}

              <FieldLabel className="mt-[18px]">Where to look</FieldLabel>
              <Tabs
                className="w-max"
                value={mode}
                onChange={(k) => setMode(k as "seeds" | "niche")}
                items={[
                  { key: "seeds", label: "From posts or accounts" },
                  { key: "niche", label: "By description" },
                ]}
              />

              {mode === "seeds" ? (
                <div className="mt-3">
                  <Textarea
                    rows={3}
                    value={seeds}
                    onChange={(e) => setSeeds(e.target.value)}
                    placeholder="https://www.instagram.com/artist/p/abc123/"
                  />
                  <Hint>
                    {seedsArePosts
                      ? `Reading the comments on ${
                          postLinks.length === 1 ? "that video" : `those ${postLinks.length} videos`
                        }${replies ? ", reply threads included" : ", top-level comments only"}. ` +
                        "Nothing is followed, liked or messaged; it only reads."
                      : seeds.trim()
                        ? "Reading followers directly. Everyone here chose to follow those accounts, which is a warmer list than a hashtag — it is also the most conspicuous thing this does, so keep the numbers modest."
                        : "One post or profile per line. Their audience is who gets read."}
                  </Hint>
                  <div className="mt-2.5 flex flex-col gap-0.5">
                    <Checkbox checked={commenters} onChange={setCommenters}>
                      People who commented
                    </Checkbox>
                    <Checkbox checked={likers} onChange={setLikers}>
                      People who liked{" "}
                      <em className="not-italic text-[11.5px] text-subtle">(one extra page load per post)</em>
                    </Checkbox>
                    <Checkbox checked={replies} onChange={setReplies}>
                      Open the reply threads{" "}
                      <em className="not-italic text-[11.5px] text-subtle">
                        (where most of a busy video&apos;s people are)
                      </em>
                    </Checkbox>
                    <Checkbox checked={enrich} onChange={setEnrich}>
                      Open each profile for bio and follower count{" "}
                      <em className="not-italic text-[11.5px] text-subtle">(slower)</em>
                    </Checkbox>
                  </div>
                </div>
              ) : (
                <div className="mt-3">
                  <div className="grid grid-cols-2 gap-2.5">
                    <Field label="Niche">
                      <Input value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="streetwear resellers" />
                    </Field>
                    <Field label="Location">
                      <Input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Lagos" />
                    </Field>
                  </div>
                  <Field label="Interests" className="mt-2.5">
                    <Input
                      value={interests}
                      onChange={(e) => setInterests(e.target.value)}
                      placeholder="sneakers, thrifting, hypebeast"
                    />
                  </Field>
                </div>
              )}

              <FieldLabel className="mt-[18px]">How many</FieldLabel>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={10}
                  max={availability?.max_per_search ?? 300}
                  step={10}
                  value={wanted}
                  onChange={(e) => setWanted(Number(e.target.value))}
                  className="flex-1 accent-[var(--chart-1)]"
                />
                <output className="min-w-[48px] text-right text-[17px] font-extrabold tabular-nums leading-normal text-foreground">
                  {wanted}
                </output>
                <span className="text-[11px] leading-normal text-subtle">max {n(availability?.max_per_search)}</span>
              </div>

              {account && (
                <Hint>
                  Using <b className="font-bold text-foreground">{account.name}</b> — {n(account.used_today)} profiles
                  opened in the last 24 hours. A search runs until the platform stops it.
                </Hint>
              )}

              {pending > 0 && (
                <button
                  type="button"
                  onClick={showPending}
                  className="mt-3 w-full rounded-[10px] border border-border bg-card px-3.5 py-[9px] text-[12px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  {pending} already found but in no campaign — review them
                </button>
              )}
            </DialogBody>
          )}

          {/* ---- 2. searching ---------------------------------------- */}
          {step === 1 && run && (
            <DialogBody>
              <div className="flex items-center gap-[11px]">
                <span className="h-[26px] w-[26px] flex-none animate-spin rounded-full border-[2.5px] border-border border-t-chart-1" />
                <span className="text-[13px] font-bold leading-normal text-foreground">{run.message}</span>
              </div>
              <div className="mt-3.5 grid grid-cols-3 gap-2">
                {[
                  { label: "FOUND", value: run.found },
                  { label: "WANTED", value: run.wanted },
                  { label: "LEFT", value: Math.max(run.wanted - run.found, 0) },
                ].map((s) => (
                  <div key={s.label} className="rounded-[11px] bg-secondary px-1.5 py-2.5 text-center">
                    <b className="block text-[17px] font-extrabold tracking-[-0.03em] tabular-nums leading-normal text-foreground">
                      {n(s.value)}
                    </b>
                    <span className="text-[9.5px] font-semibold leading-normal text-subtle">{s.label}</span>
                  </div>
                ))}
              </div>
              <Hint>
                This runs in a real browser and takes minutes. You can close this — the search keeps going, and the
                results are waiting here when it finishes.
              </Hint>
            </DialogBody>
          )}

          {/* ---- 3. review ------------------------------------------- */}
          {step === 2 && (
            <DialogBody>
              <div className="flex items-center gap-3 border-b border-border pb-2.5">
                <span className="text-[11.5px] tabular-nums leading-normal text-subtle">
                  {n(leads.length)} found · {n(chosen.size)} selected
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setChosen(chosen.size === leads.length ? new Set() : new Set(leads.map((l) => l.id)))
                  }
                  className="ml-auto text-[11.5px] font-semibold leading-normal text-muted-foreground underline transition-colors hover:text-foreground"
                >
                  {chosen.size === leads.length ? "Select none" : "Select all"}
                </button>
              </div>

              <div className="max-h-[268px] overflow-auto">
                {leads.map((lead) => {
                  const on = chosen.has(lead.id);
                  return (
                    <label
                      key={lead.id}
                      className="flex cursor-pointer items-center gap-2.5 border-b border-line-2 px-0.5 py-[9px] last:border-b-0"
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={(e) => {
                          const next = new Set(chosen);
                          if (e.target.checked) next.add(lead.id);
                          else next.delete(lead.id);
                          setChosen(next);
                        }}
                        className="pointer-events-none absolute opacity-0"
                      />
                      <span
                        className={`grid h-4 w-4 flex-none place-items-center rounded-[5px] border-[1.5px] ${
                          on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-transparent"
                        }`}
                      >
                        <Check className="h-[11px] w-[11px]" strokeWidth={3} />
                      </span>
                      <Avatar platform={platform} className="!h-[27px] !w-[27px]" />
                      <span className="flex min-w-0 flex-col gap-px">
                        <span className="truncate text-[12.5px] font-semibold leading-normal text-foreground">
                          @{lead.username}
                          {lead.score !== null && (
                            <span className="ml-2 text-[11px] font-normal text-subtle">{lead.score}/100</span>
                          )}
                        </span>
                        <span className="truncate text-[10.5px] leading-normal text-subtle">
                          {lead.followers != null && <span className="mr-2">{n(lead.followers)} followers</span>}
                          {lead.bio || lead.reason || lead.source}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>

              {campaigns.length > 1 && (
                <div className="mt-3 rounded-[12px] border border-border bg-secondary px-3 py-2.5">
                  <FieldLabel className="mb-1.5">Send these to</FieldLabel>
                  <div className="flex flex-col gap-0.5">
                    {campaigns.map((cc) => (
                      <Checkbox
                        key={cc.id}
                        checked={targets.has(cc.id)}
                        onChange={(v) => {
                          const next = new Set(targets);
                          if (v) next.add(cc.id);
                          else next.delete(cc.id);
                          setTargets(next);
                        }}
                      >
                        {cc.name}
                      </Checkbox>
                    ))}
                  </div>
                  {targets.size > 1 && (
                    <Hint>
                      Split evenly — about {Math.floor(chosen.size / targets.size)} each, dealt one at a time rather
                      than in blocks, so no campaign gets all the best leads.
                    </Hint>
                  )}
                </div>
              )}
            </DialogBody>
          )}

          <DialogFoot
            note={
              step === 0 && availability?.busy
                ? availability.busy_reason ?? "No search can start right now."
                : step === 1
                  ? "You can close this — the search keeps going."
                  : undefined
            }
          >
            {step === 0 && (
              <>
                <GhostButton onClick={onClose}>Cancel</GhostButton>
                <PrimaryButton
                  icon={Sparkles}
                  onClick={handleStart}
                  disabled={busy || !canStart || availability?.busy}
                >
                  {availability?.busy ? "Can’t start yet" : "Find profiles"}
                </PrimaryButton>
              </>
            )}
            {step === 1 && run && (
              <>
                <GhostButton onClick={onClose}>Close</GhostButton>
                <GhostButton
                  onClick={() => {
                    void cancelLeadSearch(run.search_id);
                    toast.success("Stopping the search");
                  }}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <Square className="h-3 w-3" /> Stop
                  </span>
                </GhostButton>
              </>
            )}
            {step === 2 && (
              <>
                <GhostButton
                  onClick={() => {
                    setLeads([]);
                    setRun(null);
                  }}
                >
                  Search again
                </GhostButton>
                <PrimaryButton onClick={handleImport} disabled={busy || chosen.size === 0 || targets.size === 0}>
                  {busy
                    ? "Importing…"
                    : targets.size > 1
                      ? `Import ${chosen.size} across ${targets.size} campaigns`
                      : `Import ${chosen.size} as targets`}
                </PrimaryButton>
              </>
            )}
          </DialogFoot>
        </>
      )}
    </Dialog>
  );
}
