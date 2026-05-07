"use client"

import { useEffect, useState } from "react"
import { Loader2, CheckCircle2, XCircle, MinusCircle } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const PLATFORM_LABELS: Record<string, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
}

const PROGRESS_MESSAGES = [
  "Uploading video files…",
  "Connecting to platforms…",
  "Submitting posts…",
  "Waiting for confirmation…",
  "Almost done…",
]

interface PostResult {
  account_name: string
  platforms: Record<string, { status: string; error?: string }>
}

interface PostingProgressModalProps {
  open: boolean
  /** Platform keys that are being posted to — shown as spinners while posting. */
  platforms?: string[]
  /** When set, posting is done and results are shown. */
  results?: PostResult[] | null
  onClose?: () => void
}

export function PostingProgressModal({
  open,
  platforms = [],
  results,
  onClose,
}: PostingProgressModalProps) {
  const [msgIdx, setMsgIdx] = useState(0)

  // Rotate status messages while posting (no results yet)
  useEffect(() => {
    if (!open || results) return
    const iv = setInterval(() => {
      setMsgIdx((i) => (i + 1) % PROGRESS_MESSAGES.length)
    }, 2800)
    return () => clearInterval(iv)
  }, [open, results])

  // Reset message index each time the modal opens for a new post
  useEffect(() => {
    if (open && !results) setMsgIdx(0)
  }, [open, results])

  const isDone = !!results
  const anyOk = results?.some((r) =>
    Object.values(r.platforms).some((v) => v.status === "posted")
  )

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && isDone && onClose) onClose() }}>
      <DialogContent showCloseButton={isDone} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isDone ? "Post Results" : "Posting…"}</DialogTitle>
        </DialogHeader>

        {!isDone ? (
          /* Posting in progress */
          <div className="flex flex-col items-center gap-5 py-6">
            <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-muted">
              <Loader2 className="h-8 w-8 animate-spin text-foreground" />
            </div>
            <p className="text-sm font-medium text-foreground">
              {PROGRESS_MESSAGES[msgIdx]}
            </p>
            {platforms.length > 0 && (
              <div className="flex flex-wrap justify-center gap-2">
                {platforms.map((p) => (
                  <span
                    key={p}
                    className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs font-medium"
                  >
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60" />
                    {PLATFORM_LABELS[p] ?? p}
                  </span>
                ))}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              This may take up to 60 seconds
            </p>
          </div>
        ) : (
          /* Results */
          <div className="flex flex-col gap-4 py-2">
            <div className="flex items-center gap-2">
              {anyOk ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              ) : (
                <XCircle className="h-5 w-5 shrink-0 text-destructive" />
              )}
              <p className="text-sm font-medium">
                {anyOk ? "Posted successfully" : "Nothing was posted"}
              </p>
            </div>

            <div className="space-y-3">
              {(results ?? []).map((r, i) => (
                <div key={i} className="rounded-lg border border-border bg-muted/40 p-3">
                  <p className="mb-2 text-xs font-semibold text-foreground">{r.account_name}</p>
                  <div className="space-y-1">
                    {Object.entries(r.platforms).map(([plat, v]) => (
                      <div key={plat} className="flex items-start gap-2 text-xs">
                        {v.status === "posted" ? (
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                        ) : v.status === "failed" ? (
                          <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
                        ) : (
                          <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span>
                          <span className="font-medium capitalize">{PLATFORM_LABELS[plat] ?? plat}</span>
                          {v.status === "failed" && v.error && (
                            <span className="ml-1 text-destructive/80">— {v.error.slice(0, 120)}</span>
                          )}
                          {v.status === "skipped" && (
                            <span className="ml-1 text-muted-foreground">— skipped (not connected)</span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
