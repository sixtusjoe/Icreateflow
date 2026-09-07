"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, Loader2, Square } from "lucide-react";
import { toast } from "sonner";
import {
  getLeadSearchAvailability,
  startLeadSearch,
  getLeadSearch,
  cancelLeadSearch,
  listLeads,
  importLeads,
  type Lead,
  type LeadSearchAvailability,
  type LeadSearchRun,
} from "@/lib/api";
import { inputClass, apiErrorMessage } from "../ui";

/**
 * Find profiles to contact, instead of pasting a list you already have.
 *
 * Three steps, deliberately not one: describe who you want, watch it look,
 * then choose from what it found. Nothing reaches the campaign until the
 * last step — a search that comes back with rubbish should cost a glance,
 * not a cleanup.
 */
export function LeadFinder({
  campaignId,
  platform,
  onImported,
}: {
  campaignId: number;
  platform: string;
  onImported: () => void;
}) {
  const [availability, setAvailability] = useState<LeadSearchAvailability | null>(null);
  const [niche, setNiche] = useState("");
  const [location, setLocation] = useState("");
  const [interests, setInterests] = useState("");
  const [wanted, setWanted] = useState(50);
  const [commenters, setCommenters] = useState(false);
  const [accountId, setAccountId] = useState<number | undefined>();
  const [run, setRun] = useState<LeadSearchRun | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getLeadSearchAvailability(platform)
      .then((a) => {
        setAvailability(a);
        if (a.accounts[0]) setAccountId(a.accounts[0].id);
      })
      .catch(() => setAvailability(null));
  }, [platform]);

  const loadLeads = useCallback(async (searchId: number) => {
    try {
      const found = await listLeads(searchId);
      setLeads(found);
      // Pre-select what the model rated well; everything when nothing was
      // scored, since an unscored lead is unknown rather than bad.
      const scored = found.some((l) => l.score !== null);
      setChosen(
        new Set(
          found.filter((l) => (scored ? (l.score ?? 0) >= 60 : true)).map((l) => l.id)
        )
      );
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

  const handleStart = async () => {
    if (!niche.trim()) return toast.error("Describe who you are looking for");
    setBusy(true);
    setLeads([]);
    setChosen(new Set());
    try {
      const started = await startLeadSearch(campaignId, {
        niche: niche.trim(),
        location: location.trim() || undefined,
        interests: interests.trim() || undefined,
        wanted,
        platform,
        account_id: accountId,
        include_commenters: commenters,
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
      const summary = await importLeads(campaignId, [...chosen]);
      toast.success(`${summary.ready} target(s) added`);
      setLeads([]);
      setRun(null);
      onImported();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not import those leads"));
    } finally {
      setBusy(false);
    }
  };

  if (availability && !availability.available) {
    return (
      <div className="rounded-xl border border-border p-3 text-xs text-muted-foreground">
        {availability.unavailable_reason}
      </div>
    );
  }

  const account = availability?.accounts.find((a) => a.id === accountId);
  const running = run !== null && !run.done;

  return (
    <div className="rounded-xl border border-border p-3">
      {leads.length === 0 && !running && (
        <>
          <div className="space-y-2">
            <input
              className={inputClass}
              placeholder="Who are you looking for? e.g. fitness coaches"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
            />
            <div className="grid grid-cols-2 gap-2">
              <input
                className={inputClass}
                placeholder="Location (optional)"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
              <input
                className={inputClass}
                placeholder="Interests (optional)"
                value={interests}
                onChange={(e) => setInterests(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">How many</label>
              <input
                type="number"
                min={1}
                max={availability?.max_per_search ?? 300}
                className={`${inputClass} w-24`}
                value={wanted}
                onChange={(e) => setWanted(Number(e.target.value) || 1)}
              />
              {availability && availability.accounts.length > 1 && (
                <select
                  className={`${inputClass} flex-1`}
                  value={accountId}
                  onChange={(e) => setAccountId(Number(e.target.value))}
                >
                  {availability.accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} — {a.remaining_today} left today
                    </option>
                  ))}
                </select>
              )}
            </div>
            <label className="flex items-start gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={commenters}
                onChange={(e) => setCommenters(e.target.checked)}
              />
              <span>
                Also read who commented on the posts it finds. Finds more people,
                and opens a great many more pages — the likeliest way to get a
                discovery account restricted.
              </span>
            </label>
          </div>

          {account && (
            <p className="mt-2 text-xs text-muted-foreground">
              Using <strong>{account.name}</strong> — {account.used_today} profiles
              opened today, {account.remaining_today} left before the cap.
            </p>
          )}

          <button
            onClick={handleStart}
            disabled={busy || !niche.trim() || availability?.busy}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {availability?.busy ? "Another search is running" : "Find profiles"}
          </button>
        </>
      )}

      {running && run && (
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {run.message}
          </span>
          <button
            onClick={() => cancelLeadSearch(run.search_id)}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            <Square className="h-3 w-3" /> Stop
          </button>
        </div>
      )}

      {leads.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">
              {leads.length} found · {chosen.size} selected
            </p>
            <button
              onClick={() =>
                setChosen(
                  chosen.size === leads.length
                    ? new Set()
                    : new Set(leads.map((l) => l.id))
                )
              }
              className="text-xs underline"
            >
              {chosen.size === leads.length ? "none" : "all"}
            </button>
          </div>
          <ul className="mt-2 max-h-64 divide-y divide-border/60 overflow-y-auto rounded-lg border border-border">
            {leads.map((lead) => (
              <li key={lead.id} className="flex items-start gap-2 px-3 py-2">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={chosen.has(lead.id)}
                  onChange={(e) => {
                    const next = new Set(chosen);
                    if (e.target.checked) next.add(lead.id);
                    else next.delete(lead.id);
                    setChosen(next);
                  }}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">
                    @{lead.username}
                    {lead.score !== null && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        {lead.score}/100
                      </span>
                    )}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {lead.reason || lead.bio || lead.source}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <button
            onClick={handleImport}
            disabled={busy || chosen.size === 0}
            className="mt-3 w-full rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Importing…" : `Import ${chosen.size} as targets`}
          </button>
        </>
      )}
    </div>
  );
}
