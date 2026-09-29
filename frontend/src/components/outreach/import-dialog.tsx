"use client";

/**
 * Import targets.
 *
 * Two ways in — a CSV, or a pasted list — and one result panel. The
 * result is the point: the server rejects duplicates and off-platform
 * rows before anything is saved, and this says exactly how many of each,
 * with the rejected lines behind a disclosure so a bad file is diagnosable
 * without a second attempt.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Info, Upload } from "lucide-react";
import { toast } from "sonner";
import {
  importOutreachTargetsFile,
  importOutreachTargetsText,
  type OutreachImportSummary,
} from "@/lib/api";
import { Dialog, DialogBody, DialogFoot, DialogHead, GhostButton, Textarea } from "@/components/kit/dialog";
import { PrimaryButton } from "@/components/kit";
import { apiErrorMessage } from "@/components/kit/format";

export function ImportDialog({
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
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<OutreachImportSummary | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setPasted("");
      setSummary(null);
      setDragging(false);
    }
  }, [open]);

  const send = async (file?: File) => {
    setBusy(true);
    try {
      const result = file
        ? await importOutreachTargetsFile(campaignId, file)
        : await importOutreachTargetsText(campaignId, pasted);
      setSummary(result);
      setPasted("");
      onImported();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Import failed"));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const example =
    platform === "tiktok"
      ? "https://www.tiktok.com/@carol"
      : platform === "x"
        ? "https://x.com/carol"
        : "https://www.instagram.com/carol";

  return (
    <Dialog open={open} onClose={onClose} label="Import targets">
      <DialogHead
        title="Import targets"
        sub="Handles or profile links. Duplicates and off-platform rows are rejected before anything is saved."
        onClose={onClose}
      />

      {summary ? (
        <DialogBody>
          <div className="grid grid-cols-4 gap-[9px]">
            {[
              // `imported` is rows read, not rows kept — `ready` is what landed.
              { label: "READ", value: summary.imported },
              { label: "DUPLICATE", value: summary.duplicates },
              { label: "INVALID", value: summary.invalid },
              { label: "ADDED", value: summary.ready, ok: true },
            ].map((s) => (
              <div
                key={s.label}
                className={`rounded-[12px] border px-2 py-[13px] text-center ${
                  s.ok ? "border-good/28 bg-good/10" : "border-border bg-secondary"
                }`}
              >
                <div
                  className={`text-[21px] tracking-[-0.03em] tabular-nums leading-normal ${
                    s.ok ? "font-extrabold text-good" : s.value === 0 ? "font-bold text-subtle" : "font-extrabold text-foreground"
                  }`}
                >
                  {s.value.toLocaleString()}
                </div>
                <div className="mt-[3px] text-[9.5px] font-semibold leading-normal tracking-[0.02em] text-subtle">
                  {s.label}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3.5 flex items-start gap-[9px] rounded-[12px] bg-good/[0.09] px-3.5 py-3 text-[12.5px] leading-[1.5] text-muted-foreground">
            <Check className="mt-px h-[15px] w-[15px] flex-none text-good" strokeWidth={2.6} />
            <span>
              <b className="font-bold text-foreground">
                {summary.ready.toLocaleString()} target{summary.ready === 1 ? "" : "s"} added.
              </b>{" "}
              {summary.ready > 0
                ? "They are queued and will go out when the campaign runs."
                : "Nothing new was added — every row was already here or could not be read."}
            </span>
          </div>

          {summary.invalid_rows.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[11.5px] font-semibold leading-normal text-subtle">
                Show {summary.invalid_rows.length} rejected row
                {summary.invalid_rows.length === 1 ? "" : "s"}
                {summary.invalid_truncated ? ` (of ${summary.invalid_rows.length + summary.invalid_truncated})` : ""}
              </summary>
              <ul className="mt-2 max-h-[132px] overflow-auto rounded-[12px] border border-border bg-card px-3 py-1.5">
                {summary.invalid_rows.map((row) => (
                  <li
                    key={row.line}
                    className="flex gap-2.5 border-b border-line-2 py-[7px] text-[11.5px] leading-normal text-muted-foreground last:border-b-0"
                  >
                    <em className="flex-none font-mono not-italic text-subtle">line {row.line}</em>
                    {row.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </DialogBody>
      ) : (
        <DialogBody>
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files?.[0];
              if (f) void send(f);
            }}
            className={`flex cursor-pointer flex-col items-center gap-1.5 rounded-[14px] border-[1.5px] border-dashed px-5 py-[26px] text-center transition-colors ${
              dragging ? "border-subtle bg-card" : "border-border bg-secondary hover:border-subtle hover:bg-card"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv,text/plain"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void send(f);
              }}
            />
            <span className="mb-0.5 grid h-[38px] w-[38px] place-items-center rounded-[11px] border border-border bg-card text-muted-foreground">
              <Upload className="h-[17px] w-[17px]" strokeWidth={1.8} />
            </span>
            <span className="text-[13px] font-semibold leading-normal text-foreground">
              Drop a CSV here, or <b className="font-semibold underline">browse</b>
            </span>
            <span className="text-[11px] leading-normal text-subtle">
              A <code className="rounded-[5px] border border-border bg-secondary px-1 py-px font-mono text-[10.5px]">username</code>{" "}
              and/or{" "}
              <code className="rounded-[5px] border border-border bg-secondary px-1 py-px font-mono text-[10.5px]">profile_url</code>{" "}
              column
            </span>
          </label>

          <div className="my-3 flex items-center gap-3 text-[11px] leading-normal text-subtle before:h-px before:flex-1 before:bg-border before:content-[''] after:h-px after:flex-1 after:bg-border after:content-['']">
            <span>or paste a list</span>
          </div>

          <Textarea
            rows={7}
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            placeholder={`username\nalice\nbob\n${example}`}
          />
          <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] text-subtle">
            <Info className="mt-0.5 h-3 w-3 flex-none" />
            <span>One per line. A bare handle works; so does a full profile URL.</span>
          </div>
        </DialogBody>
      )}

      <DialogFoot>
        {summary ? (
          <PrimaryButton onClick={onClose}>Done</PrimaryButton>
        ) : (
          <>
            <GhostButton onClick={onClose} disabled={busy}>
              Cancel
            </GhostButton>
            <PrimaryButton icon={Upload} onClick={() => void send()} disabled={busy || !pasted.trim()}>
              {busy ? "Importing…" : "Import list"}
            </PrimaryButton>
          </>
        )}
      </DialogFoot>
    </Dialog>
  );
}
