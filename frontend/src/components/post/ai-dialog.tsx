"use client";

/** Making — or changing — one slide's picture with AI.
 *
 *  Two jobs behind one dialog. `mode: "make"` draws a new image from the
 *  original as reference; `mode: "edit"` alters the image already there.
 *  The result is never used until it is approved, so the dialog says so.
 */

import { useEffect, useRef, useState } from "react";
import { Wand2 } from "lucide-react";
import { generateVariationImage } from "@/lib/api";
import { PrimaryButton } from "@/components/kit";
import { Dialog, DialogBody, DialogFoot, DialogHead, Field, GhostButton, Hint, Textarea } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";
import { SlideImage } from "./slide-image";

const PRESETS = [
  {
    label: "New person, same scene",
    prompt:
      "Generate a new photorealistic image using the same background, setting, lighting, and composition as the reference. Replace the person with a completely different person. Remove any text overlays. Keep the same overall vibe and environment.",
  },
  {
    label: "New person, new colours",
    prompt:
      "Generate a new photorealistic image with the same setting and composition as the reference but with a completely different color palette and lighting mood. Replace the person with a new person. Remove any text overlays.",
  },
  {
    label: "Same scene, no text",
    prompt:
      "Recreate this exact scene and setting with the same composition, lighting, and style. Remove all text overlays and captions. Keep everything else — the environment, the props, the overall mood — intact.",
  },
];

const WORKING = [
  "Reading your slide…",
  "Working out the composition…",
  "Drawing it…",
  "Still going, nearly there…",
  "Last touches…",
];

export type AiTarget = {
  variationId: number;
  slideNumber: number;
  accountName: string;
  /** What the slide says, for the reference block. */
  text: string;
  imageUrl?: string;
  mode: "make" | "edit";
};

export function AiDialog({
  target,
  onClose,
  onDone,
}: {
  target: AiTarget | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [prompt, setPrompt] = useState(PRESETS[0].prompt);
  const [preset, setPreset] = useState<number | null>(0);
  const [working, setWorking] = useState(false);
  const [msg, setMsg] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset when a different slide opens it, so nothing carries over.
  const key = target ? `${target.variationId}:${target.mode}` : "";
  const seen = useRef(key);
  if (seen.current !== key) {
    seen.current = key;
    if (!working) {
      setPrompt(PRESETS[0].prompt);
      setPreset(0);
      setError(null);
    }
  }

  useEffect(() => {
    if (!working) {
      if (timer.current) clearInterval(timer.current);
      return;
    }
    timer.current = setInterval(() => setMsg((i) => (i + 1) % WORKING.length), 1200);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [working]);

  if (!target) return null;
  const edit = target.mode === "edit";

  const go = async () => {
    setWorking(true);
    setError(null);
    setMsg(0);
    try {
      await generateVariationImage(target.variationId, prompt);
      onDone();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "The image service turned it down. Reword it and try again."));
    } finally {
      setWorking(false);
    }
  };

  return (
    <Dialog open onClose={working ? () => {} : onClose} label={edit ? "Change this image" : "Make it with AI"} size="md">
      <DialogHead
        title={edit ? `Change slide ${target.slideNumber}` : `Make slide ${target.slideNumber} with AI`}
        sub={
          edit
            ? "It edits the image that is already there, rather than drawing a new one from the original."
            : "It redraws the picture around the same words. The title and body are not touched."
        }
        onClose={working ? () => {} : onClose}
      />
      <DialogBody>
        <div className="flex items-center gap-3 rounded-[13px] border border-border bg-secondary px-3.5 py-3">
          <span className="h-[50px] w-[38px] flex-none overflow-hidden rounded-[9px] ring-1 ring-border">
            <SlideImage src={target.imageUrl} label={target.slideNumber} />
          </span>
          <div className="min-w-0">
            <div className="text-[9.5px] font-bold uppercase leading-normal tracking-[0.08em] text-subtle">
              Working from
            </div>
            <div className="truncate text-[13px] font-semibold leading-normal">{target.text || "This slide"}</div>
            <div className="text-[11px] leading-[1.45] text-subtle">
              {edit ? "Your edits are applied to this picture" : "This picture is the reference it draws around"}
            </div>
          </div>
        </div>

        <div className="mt-4">
          <div className="mb-2 text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
            Start from
          </div>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p, i) => (
              <button
                key={p.label}
                type="button"
                disabled={working}
                onClick={() => {
                  setPreset(i);
                  setPrompt(p.prompt);
                }}
                className={`whitespace-nowrap rounded-[10px] border px-3 py-[7px] text-[11.5px] font-semibold leading-normal transition-colors disabled:opacity-50 ${
                  preset === i
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3.5">
          <Field label="What it should make">
            <Textarea
              rows={4}
              value={prompt}
              disabled={working}
              onChange={(e) => {
                setPrompt(e.target.value);
                setPreset(null);
              }}
            />
          </Field>
        </div>

        {working && (
          <div className="mt-3.5 flex items-center gap-2.5 rounded-[12px] border border-border bg-secondary px-3.5 py-3 text-[12.5px] text-muted-foreground">
            <span className="flex flex-none gap-1" aria-hidden>
              {[0, 1, 2].map((i) => (
                <i
                  key={i}
                  className="h-1.5 w-1.5 rounded-full bg-subtle"
                  style={{ animation: `aihop 1.2s ease-in-out ${i * 0.16}s infinite` }}
                />
              ))}
            </span>
            {WORKING[msg]}
          </div>
        )}

        {error && !working && (
          <p className="mt-3.5 rounded-[12px] bg-destructive/10 px-3.5 py-2.5 text-[11.5px] leading-[1.5] text-destructive">
            {error}
          </p>
        )}

        {!working && !error && (
          <Hint>About 20 seconds. The result waits for your approval — nothing is built with it until you approve it.</Hint>
        )}

        <style>{`@keyframes aihop{0%,80%,100%{transform:translateY(0);opacity:.55}40%{transform:translateY(-5px);opacity:1}}`}</style>
      </DialogBody>
      <DialogFoot note={`Slide ${target.slideNumber} · ${target.accountName}`}>
        <GhostButton onClick={onClose} disabled={working}>
          Cancel
        </GhostButton>
        <PrimaryButton icon={Wand2} onClick={go} disabled={working || !prompt.trim()}>
          {working ? "Making it…" : error ? "Try again" : edit ? "Apply the change" : "Make it"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}
