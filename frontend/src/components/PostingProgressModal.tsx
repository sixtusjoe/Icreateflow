"use client"

import { useEffect, useState } from "react"
import { Loader2, CheckCircle2, XCircle, MinusCircle, RotateCcw } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { retryOutput } from "@/lib/api"

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
  output_id?: number
  account_name: string
  platforms: Record<string, { status: string; error?: string; friendly_error?: string; draft?: boolean }>
}

interface PostingProgressModalProps {
  open: boolean
  /** Platform keys that are being posted to — shown as spinners while posting. */
  platforms?: string[]
  /** When set, posting is done and results are shown. */
  results?: PostResult[] | null
  onClose?: () => void
}

const PLATFORM_LABELS_FULL: Record<string, string> = {
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
}

function isCapError(error?: string) {
  return !!(error && (error.toLowerCase().includes("reached_active_user_cap") || error.toLowerCase().includes("active_user_cap")))
}

export function PostingProgressModal({
  open,
  platforms = [],
  results: initialResults,
  onClose,
}: PostingProgressModalProps) {
  const [msgIdx, setMsgIdx] = useState(0)
  const [results, setResults] = useState<PostResult[] | null | undefined>(initialResults)
  const [retryingKey, setRetryingKey] = useState<string | null>(null) // "outputId:platform"
  const [capRetry, setCapRetry] = useState<{ outputId: number; platform: string } | null>(null)

  // Sync external results into local state
  useEffect(() => { setResults(initialResults) }, [initialResults])

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

  const handleRetry = async (outputId: number, platform: string, mode: "normal" | "draft" | "delayed") => {
    const key = `${outputId}:${platform}`
    setRetryingKey(key)
    setCapRetry(null)
    try {
      const res = await retryOutput(outputId, mode)
      // Update the local results with the new platform status
      setResults((prev) =>
        (prev ?? []).map((r) => {
          if (r.output_id !== outputId) return r
          const updated = { ...r.platforms }
          const platResult = res.platforms?.[platform]
          if (platResult) updated[platform] = platResult
          return { ...r, platforms: updated }
        })
      )
    } catch {
      // Keep the existing error shown
    } finally {
      setRetryingKey(null)
    }
  }

  return (
    <>
      {/* TikTok cap-error retry options modal */}
      {capRetry && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-background p-6 shadow-xl">
            <h3 className="text-base font-semibold">Retry TikTok post</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              This account has hit TikTok's active user cap. Choose how to retry:
            </p>
            <div className="mt-5 flex flex-col gap-2.5">
              <button
                onClick={() => handleRetry(capRetry.outputId, capRetry.platform, "draft")}
                disabled={!!retryingKey}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Post as draft</span>
                <span className="text-xs text-muted-foreground">Posts immediately to TikTok inbox — you publish from the app</span>
              </button>
              <button
                onClick={() => handleRetry(capRetry.outputId, capRetry.platform, "delayed")}
                disabled={!!retryingKey}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted disabled:opacity-50"
              >
                <span className="text-sm font-medium">Retry in 6 hours</span>
                <span className="text-xs text-muted-foreground">System retries direct post after the cap cooldown</span>
              </button>
              <button
                onClick={() => setCapRetry(null)}
                disabled={!!retryingKey}
                className="mt-1 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

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
                    <div className="space-y-2">
                      {Object.entries(r.platforms).map(([plat, v]) => {
                        const retryKey = `${r.output_id}:${plat}`
                        const isRetrying = retryingKey === retryKey
                        return (
                          <div key={plat} className="flex items-start gap-2 text-xs">
                            {v.status === "posted" ? (
                              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                            ) : v.status === "failed" ? (
                              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
                            ) : (
                              <MinusCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            )}
                            <div className="flex flex-1 flex-wrap items-start justify-between gap-1.5">
                              <span>
                                <span className="font-medium">{PLATFORM_LABELS_FULL[plat] ?? plat}</span>
                                {v.status === "posted" && v.draft && (
                                  <span className="ml-1 text-amber-500">— posted to drafts</span>
                                )}
                                {v.status === "failed" && (v.friendly_error || v.error) && (
                                  <span className="ml-1 text-destructive/80">— {(v.friendly_error || v.error || "").slice(0, 120)}</span>
                                )}
                                {v.status === "skipped" && (
                                  <span className="ml-1 text-muted-foreground">— skipped (not connected)</span>
                                )}
                              </span>
                              {v.status === "failed" && r.output_id && (
                                <button
                                  onClick={() => {
                                    if (isCapError(v.error) && plat === "tiktok") {
                                      setCapRetry({ outputId: r.output_id!, platform: plat })
                                    } else {
                                      handleRetry(r.output_id!, plat, "normal")
                                    }
                                  }}
                                  disabled={isRetrying || !!retryingKey}
                                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                                >
                                  {isRetrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                                  {isRetrying ? "Retrying…" : "Retry"}
                                </button>
                              )}
                            </div>
                          </div>
                        )
                      })}
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
    </>
  )
}
