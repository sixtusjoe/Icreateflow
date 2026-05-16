"use client"

import { useEffect, useRef, useState } from "react"
import { Wand2, X } from "lucide-react"
import { generateVariationImage } from "@/lib/api"

const PRESETS = [
  { label: "Similar — different colors", prompt: "Recreate this image with a completely different color palette and mood. Keep the exact same composition, subject matter, and photorealistic style — only change the colors and lighting tones." },
  { label: "Similar — different placement", prompt: "Recreate this image with the subjects repositioned or recomposed. Keep the same photorealistic style, lighting, and theme — only change how elements are arranged in the frame." },
  { label: "Remove all text", prompt: "Recreate this image with all text, words, labels, and typography completely removed. Inpaint those areas naturally to match the surrounding visual style and background." },
]

const PROGRESS_MESSAGES = [
  "Analyzing your slide…",
  "Crafting the composition…",
  "Generating image…",
  "Adding final touches…",
  "Almost there…",
]

interface AIGenerateModalProps {
  open: boolean
  variationId: number
  slideImageUrl?: string
  slideTitle?: string
  isEdit?: boolean   // true when editing an already-generated image
  onClose: () => void
  onSuccess: () => void
}

export function AIGenerateModal({
  open,
  variationId,
  slideImageUrl,
  slideTitle,
  isEdit = false,
  onClose,
  onSuccess,
}: AIGenerateModalProps) {
  const [prompt, setPrompt] = useState("")
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [msgIdx, setMsgIdx] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setPrompt("")
      setSelectedPreset(null)
      setError(null)
      setGenerating(false)
      setMsgIdx(0)
      setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [open])

  // Cycle progress messages while generating
  useEffect(() => {
    if (!generating) return
    const iv = setInterval(() => setMsgIdx((i) => (i + 1) % PROGRESS_MESSAGES.length), 2500)
    return () => clearInterval(iv)
  }, [generating])

  const selectPreset = (idx: number) => {
    setSelectedPreset(idx)
    setPrompt(PRESETS[idx].prompt)
    textareaRef.current?.focus()
  }

  const handleGenerate = async () => {
    if (!prompt.trim()) return
    setGenerating(true)
    setError(null)
    try {
      await generateVariationImage(variationId, prompt.trim(), true)
      onSuccess()
      onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || "Generation failed")
      setGenerating(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl bg-background shadow-2xl ring-1 ring-border">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Wand2 className="h-4 w-4 text-foreground" />
            <span className="text-sm font-semibold">{isEdit ? "Edit Generated Image" : "AI Generate Image"}</span>
          </div>
          <button
            onClick={onClose}
            disabled={generating}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">

          {/* Reference image + title */}
          {(slideImageUrl || slideTitle) && (
            <div className="flex items-center gap-3 rounded-xl bg-muted/50 px-3 py-2.5">
              {slideImageUrl && (
                <img
                  src={slideImageUrl}
                  alt="Reference slide"
                  className="h-14 w-10 shrink-0 rounded-md object-cover ring-1 ring-border"
                />
              )}
              <div className="min-w-0">
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Reference slide</p>
                {slideTitle && (
                  <p className="mt-0.5 truncate text-sm font-medium">{slideTitle}</p>
                )}
                <p className="mt-0.5 text-[11px] text-muted-foreground">{isEdit ? "Edits will be applied to this image" : "Image will be used as visual context"}</p>
              </div>
            </div>
          )}

          {/* Preset chips */}
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Quick presets</p>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p, i) => (
                <button
                  key={i}
                  onClick={() => selectPreset(i)}
                  disabled={generating}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-40 ${
                    selectedPreset === i
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-background text-foreground hover:bg-muted"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Prompt textarea */}
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">
              Prompt <span className="text-muted-foreground/60">(edit or write your own)</span>
            </p>
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => { setPrompt(e.target.value); setSelectedPreset(null) }}
              disabled={generating}
              rows={4}
              placeholder="Describe the image you want — be specific about style, lighting, and mood for best results…"
              className="w-full resize-none rounded-xl border border-border bg-muted/30 px-3.5 py-3 text-sm outline-none placeholder:text-muted-foreground/50 focus:border-foreground disabled:opacity-50"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="rounded-xl bg-destructive/10 px-3.5 py-2.5 text-xs text-destructive">{error}</p>
          )}

          {/* Progress */}
          {generating && (
            <div className="flex items-center gap-3 rounded-xl bg-muted/50 px-4 py-3">
              <div className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="h-2 w-2 rounded-full bg-foreground/60"
                    style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </div>
              <p className="text-sm text-muted-foreground">{PROGRESS_MESSAGES[msgIdx]}</p>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onClose}
              disabled={generating}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={handleGenerate}
              disabled={generating || !prompt.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              <Wand2 className="h-3.5 w-3.5" />
              {generating ? "Generating…" : "Generate"}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.6; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
