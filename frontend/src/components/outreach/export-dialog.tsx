"use client";

/**
 * Export targets.
 *
 * The old export was the whole list, every column, every status — so the
 * work of picking "just the ones still to do" or "just the handles and
 * their links" happened in a spreadsheet afterwards, every time.
 *
 * Three choices, because those were the three: which statuses, how many,
 * and whether the bookkeeping columns are wanted at all. The counts sit
 * beside each status so the size of the file is known before it is asked
 * for rather than after it opens.
 */

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { downloadOutreachResults } from "@/lib/api";
import {
  Checkbox, Dialog, DialogBody, DialogFoot, DialogHead, Field, GhostButton, Hint, Input,
} from "@/components/kit/dialog";
import { PrimaryButton, PLATFORM_LABEL, n } from "@/components/kit";
import { apiErrorMessage } from "@/components/kit/format";

/** Every status a target can hold, in the order they happen. */
const STATUSES = [
  { key: "queued", label: "Still to do" },
  { key: "processing", label: "In flight" },
  { key: "sent", label: "Done" },
  { key: "failed", label: "Failed" },
  { key: "skipped", label: "Skipped" },
  { key: "paused", label: "Paused" },
] as const;

export function ExportDialog({
  open,
  onClose,
  campaignId,
  platform,
  counts,
}: {
  open: boolean;
  onClose: () => void;
  campaignId: number;
  platform: string;
  /** status -> how many, so the dialog can say what it will produce. */
  counts: Record<string, number>;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState("");
  const [linksOnly, setLinksOnly] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setPicked(new Set());
      setLimit("");
      setLinksOnly(true);
    }
  }, [open]);

  const available = STATUSES.filter((s) => (counts[s.key] ?? 0) > 0);

  // Nothing ticked means everything, which is both the old behaviour and
  // the one people expect from a filter they have not touched.
  const selectedTotal = useMemo(() => {
    const keys = picked.size ? [...picked] : available.map((s) => s.key);
    return keys.reduce((sum, k) => sum + (counts[k] ?? 0), 0);
  }, [picked, counts, available]);

  const capped = Number(limit);
  const willExport = limit.trim() && Number.isFinite(capped) && capped > 0
    ? Math.min(capped, selectedTotal)
    : selectedTotal;

  const limitInvalid = limit.trim() !== "" && (!Number.isFinite(capped) || capped < 1);

  const toggle = (key: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const run = async () => {
    setBusy(true);
    try {
      const blob = await downloadOutreachResults(campaignId, {
        status: picked.size ? [...picked].join(",") : undefined,
        limit: limit.trim() && !limitInvalid ? capped : undefined,
        links_only: linksOnly || undefined,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const parts = [`outreach-campaign-${campaignId}`, platform];
      if (picked.size) parts.push([...picked].sort().join("-"));
      if (linksOnly) parts.push("links");
      link.download = `${parts.join("-")}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Export failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} label="Export targets">
      <DialogHead
        title="Export targets"
        sub={`${PLATFORM_LABEL[platform] ?? platform} profile links, filtered how you like.`}
        onClose={onClose}
      />
      <DialogBody className="space-y-4">
        <div>
          <p className="mb-1 text-[11.5px] font-semibold text-muted-foreground">
            WHICH ONES
          </p>
          {available.length === 0 ? (
            <Hint>There are no targets to export yet.</Hint>
          ) : (
            <div className="grid gap-x-4 sm:grid-cols-2">
              {available.map((s) => (
                <Checkbox
                  key={s.key}
                  checked={picked.has(s.key)}
                  onChange={() => toggle(s.key)}
                >
                  {s.label}
                  <span className="ml-auto tabular-nums opacity-60">
                    {n(counts[s.key] ?? 0)}
                  </span>
                </Checkbox>
              ))}
            </div>
          )}
          <p className="mt-1 text-[11.5px] text-muted-foreground">
            Tick nothing to export every status.
          </p>
        </div>

        <Field label="HOW MANY (blank for all)">
          <Input
            type="number"
            min={1}
            value={limit}
            placeholder={String(selectedTotal)}
            onChange={(e) => setLimit(e.target.value)}
          />
        </Field>
        {limitInvalid ? <Hint tone="bad">Enter a number of 1 or more.</Hint> : null}

        <Checkbox checked={linksOnly} onChange={setLinksOnly}>
          Just the handle and its profile link
        </Checkbox>
        <p className="-mt-1 text-[11.5px] text-muted-foreground">
          {linksOnly
            ? "Two columns: username and the profile URL."
            : "Every column — status, attempts, which account, timestamps and the error."}
        </p>
      </DialogBody>
      <DialogFoot
        note={
          available.length === 0
            ? undefined
            : `${n(willExport)} row${willExport === 1 ? "" : "s"}`
        }
      >
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <PrimaryButton
          onClick={run}
          disabled={busy || limitInvalid || available.length === 0}
        >
          {busy ? "Preparing…" : "Download CSV"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
