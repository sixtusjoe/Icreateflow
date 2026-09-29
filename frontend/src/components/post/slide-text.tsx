"use client";

/** Where the words sit on a slide.
 *
 *  The backend renders at 768x1024 and takes x/y as a 0..1 ratio of the
 *  frame, so the canvas is that frame at 280px and every size is scaled by
 *  CANVAS/768. Dragging writes the same two ratios the sliders used to — X
 *  and Y were sliders, which is a poor way to say "put it there".
 *
 *  Nothing here is stored. `RegenerateSlide` takes the geometry as request
 *  arguments and no table holds it, so reopening resets to the defaults for
 *  the slide type and a full rebuild wipes every hand-placed slide. The
 *  dialog says so rather than letting it be discovered.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Check, RefreshCw } from "lucide-react";
import { regenerateSlide } from "@/lib/api";
import { PrimaryButton } from "@/components/kit";
import { Dialog, DialogBody, DialogFoot, Field, GhostButton, Hint, Textarea } from "@/components/kit/dialog";
import { apiErrorMessage } from "@/components/kit/format";
import { toast } from "sonner";
import { SlideImage } from "./slide-image";

const CANVAS = 280;
const SCALE = CANVAS / 768;

type BlockKey = "title" | "body" | "cta";
type Block = { size: number; x: number; y: number; zoom: number };

/** The defaults the backend falls back to, per slide type. */
const DEFAULTS: Record<string, Partial<Record<BlockKey, [number, number, number]>>> = {
  hook: { title: [56, 0.5, 0.3] },
  content: { title: [52, 0.5, 0.28], body: [38, 0.5, 0.48] },
  cta: { title: [48, 0.5, 0.25], body: [34, 0.5, 0.45], cta: [42, 0.5, 0.75] },
};
const RANGE: Record<BlockKey, [number, number]> = { title: [16, 120], body: [12, 100], cta: [12, 100] };
const BLOCK_LABEL: Record<BlockKey, string> = { title: "Title", body: "Body", cta: "CTA" };
const TYPE_LABEL: Record<string, string> = { hook: "Hook", content: "Content", cta: "Call to action" };
const WEIGHTS = ["Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"] as const;
const WEIGHT_PX: Record<string, number> = {
  Light: 300,
  Regular: 400,
  Medium: 500,
  SemiBold: 600,
  Bold: 700,
  ExtraBold: 800,
  Black: 900,
};

export type EditableSlide = {
  slide_number: number;
  type: string;
  title_text?: string | null;
  body_text?: string | null;
  cta_text?: string | null;
  imageUrl?: string;
};

const freshFor = (type: string): Record<string, Block> =>
  Object.fromEntries(
    Object.entries(DEFAULTS[type] ?? DEFAULTS.content).map(([k, v]) => [
      k,
      { size: v![0], x: v![1], y: v![2], zoom: 1 },
    ]),
  );

export function SlideTextDialog({
  open,
  postId,
  accountId,
  accountName,
  slides,
  startAt,
  onClose,
  onDone,
}: {
  open: boolean;
  postId: number;
  accountId: number;
  accountName: string;
  slides: EditableSlide[];
  startAt: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [at, setAt] = useState(startAt);
  const [blocks, setBlocks] = useState<Record<string, Block>>({});
  const [texts, setTexts] = useState<Record<BlockKey, string>>({ title: "", body: "", cta: "" });
  const [active, setActive] = useState<BlockKey>("title");
  const [weight, setWeight] = useState("Bold");
  const [style, setStyle] = useState<"stroke" | "background">("stroke");
  const [snap, setSnap] = useState<{ x: boolean; y: boolean }>({ x: false, y: false });
  const [busy, setBusy] = useState(false);

  const slide = slides[at];

  const reset = useCallback(
    (index: number) => {
      const s = slides[index];
      if (!s) return;
      const b = freshFor(s.type);
      const t = { title: s.title_text ?? "", body: s.body_text ?? "", cta: s.cta_text ?? "" };
      setBlocks(b);
      setTexts(t);
      // Select the first block that actually says something. Six of these
      // slides have no title, and selecting an empty title left the Text
      // field blank beside a canvas that plainly had words on it — and
      // selected a block the chip row does not even offer.
      const ks = Object.keys(b) as BlockKey[];
      setActive(ks.find((k) => t[k]?.trim()) ?? ks[0] ?? "title");
    },
    [slides],
  );

  useEffect(() => {
    if (open) {
      setAt(startAt);
      reset(startAt);
    }
  }, [open, startAt, reset]);

  const go = (index: number) => {
    const next = (index + slides.length) % slides.length;
    setAt(next);
    reset(next);
  };

  const keys = useMemo(() => (Object.keys(blocks) as BlockKey[]).filter((k) => texts[k]?.trim()), [blocks, texts]);
  const current = blocks[active];

  const move = (k: BlockKey, x: number, y: number) => {
    const sx = Math.abs(x - 0.5) < 0.022 ? 0.5 : Math.min(1, Math.max(0, x));
    const sy = Math.abs(y - 0.5) < 0.022 ? 0.5 : Math.min(1, Math.max(0, y));
    setSnap({ x: sx === 0.5, y: sy === 0.5 });
    setBlocks((b) => ({ ...b, [k]: { ...b[k], x: sx, y: sy } }));
  };

  const nudge = (dx: number, dy: number) =>
    setBlocks((b) => ({
      ...b,
      [active]: {
        ...b[active],
        x: Math.min(1, Math.max(0, +(b[active].x + dx).toFixed(2))),
        y: Math.min(1, Math.max(0, +(b[active].y + dy).toFixed(2))),
      },
    }));

  const rebuild = async () => {
    if (!slide) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        account_id: accountId,
        slide_number: slide.slide_number,
        title_text: texts.title,
        body_text: texts.body,
        cta_text: texts.cta,
        font_weight: weight,
        text_style: style,
      };
      (Object.keys(blocks) as BlockKey[]).forEach((k) => {
        body[`font_size_${k}`] = blocks[k].size;
        body[`x_ratio_${k}`] = blocks[k].x;
        body[`y_ratio_${k}`] = blocks[k].y;
        body[`scale_${k}`] = blocks[k].zoom;
      });
      await regenerateSlide(postId, body as never);
      toast.success(`Slide ${slide.slide_number} rebuilt`);
      onDone();
      onClose();
    } catch (e) {
      toast.error(apiErrorMessage(e, "Could not rebuild that slide"));
    } finally {
      setBusy(false);
    }
  };

  if (!open || !slide || !current) return null;

  return (
    <Dialog open onClose={onClose} label="Move the text on this slide" size="xl">
      <div className="relative flex items-start gap-3.5 px-[22px] pt-5">
        <div className="min-w-0">
          <div className="text-[17px] font-extrabold leading-normal tracking-[-0.02em]">Slide text · {accountName}</div>
          <div className="mt-1 text-xs leading-[1.5] text-subtle">
            Drag a block where you want it. Arrow keys nudge by one percent.
          </div>
        </div>
        <div className="ml-auto flex flex-none items-center gap-1">
          <PagerButton onClick={() => go(at - 1)} label="Previous slide">
            <ChevronLeft className="h-[13px] w-[13px]" />
          </PagerButton>
          <span className="whitespace-nowrap px-1 text-[11.5px] font-semibold leading-normal text-subtle">
            Slide <b className="tabular-nums text-foreground">{slide.slide_number}</b> of {slides.length}
          </span>
          <PagerButton onClick={() => go(at + 1)} label="Next slide">
            <ChevronRight className="h-[13px] w-[13px]" />
          </PagerButton>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          ✕
        </button>
      </div>

      <DialogBody>
        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[280px_1fr]">
          <div>
            <div
              className="relative overflow-hidden rounded-[13px] border border-border"
              style={{
                width: CANVAS,
                height: Math.round((CANVAS * 4) / 3),
                background: slide.imageUrl ? undefined : "linear-gradient(150deg,#6b7280,#374151)",
                touchAction: "none",
                userSelect: "none",
              }}
            >
              {slide.imageUrl && (
                <span className="absolute inset-0">
                  <SlideImage src={slide.imageUrl} />
                </span>
              )}
              <span
                className={`pointer-events-none absolute bottom-0 top-0 w-px bg-chart-1 transition-opacity ${snap.x ? "opacity-90" : "opacity-0"}`}
                style={{ left: "50%" }}
              />
              <span
                className={`pointer-events-none absolute left-0 right-0 h-px bg-chart-1 transition-opacity ${snap.y ? "opacity-90" : "opacity-0"}`}
                style={{ top: "50%" }}
              />
              {keys.map((k) => (
                <TextBlock
                  key={k}
                  text={texts[k]}
                  block={blocks[k]}
                  weight={WEIGHT_PX[weight]}
                  panel={style === "background"}
                  selected={k === active}
                  onSelect={() => setActive(k)}
                  onMove={(x, y) => move(k, x, y)}
                  onRelease={() => setSnap({ x: false, y: false })}
                  onNudge={nudge}
                />
              ))}
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <span className="mr-auto text-[11px] leading-normal text-subtle">
                {TYPE_LABEL[slide.type] ?? slide.type} slide
              </span>
              <GhostButton onClick={() => reset(at)}>
                <RefreshCw className="mr-1.5 inline h-3 w-3" />
                Reset layout
              </GhostButton>
            </div>
          </div>

          <div className="flex min-w-0 flex-col gap-3.5">
            <div className="flex w-fit items-center gap-[2px] rounded-[10px] border border-border bg-secondary p-[2px]">
              {keys.map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setActive(k)}
                  aria-pressed={k === active}
                  className={`rounded-[8px] px-3 py-[5px] text-[11.5px] font-semibold leading-normal transition-colors ${
                    k === active ? "bg-card text-foreground shadow-card" : "text-subtle hover:text-foreground"
                  }`}
                >
                  {BLOCK_LABEL[k]}
                </button>
              ))}
            </div>

            <Field label="Text">
              <Textarea
                rows={2}
                plain
                value={texts[active]}
                onChange={(e) => setTexts((t) => ({ ...t, [active]: e.target.value }))}
              />
            </Field>

            <Slider
              label="Size"
              value={current.size}
              min={RANGE[active][0]}
              max={RANGE[active][1]}
              display={`${current.size}px`}
              onChange={(v) => setBlocks((b) => ({ ...b, [active]: { ...b[active], size: v } }))}
            />
            <Slider
              label="Zoom"
              value={Math.round(current.zoom * 100)}
              min={30}
              max={300}
              display={`${Math.round(current.zoom * 100)}%`}
              onChange={(v) => setBlocks((b) => ({ ...b, [active]: { ...b[active], zoom: v / 100 } }))}
            />

            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between text-[11.5px] font-semibold leading-normal text-muted-foreground">
                <span>Where it sits</span>
                <b className="font-bold tabular-nums text-foreground">
                  {current.x.toFixed(2)} · {current.y.toFixed(2)}
                </b>
              </div>
              <div className="flex gap-1.5">
                <NudgeButton onClick={() => nudge(0, -0.02)} label="Move up">
                  <ChevronUp className="h-[13px] w-[13px]" />
                </NudgeButton>
                <NudgeButton onClick={() => nudge(-0.02, 0)} label="Move left">
                  <ChevronLeft className="h-[13px] w-[13px]" />
                </NudgeButton>
                <NudgeButton
                  onClick={() => setBlocks((b) => ({ ...b, [active]: { ...b[active], x: 0.5, y: 0.5 } }))}
                  label="Centre"
                >
                  <Check className="h-[13px] w-[13px]" />
                  <em className="not-italic">Centre</em>
                </NudgeButton>
                <NudgeButton onClick={() => nudge(0.02, 0)} label="Move right">
                  <ChevronRight className="h-[13px] w-[13px]" />
                </NudgeButton>
                <NudgeButton onClick={() => nudge(0, 0.02)} label="Move down">
                  <ChevronDown className="h-[13px] w-[13px]" />
                </NudgeButton>
              </div>
            </div>

            <div className="h-px bg-border" />
            <div className="text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle">
              The whole slide
            </div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <Field label="Weight">
                <select
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                  className="w-full rounded-[12px] border border-border bg-card px-3 py-[9px] text-[12.5px] leading-normal outline-none focus:border-subtle"
                >
                  {WEIGHTS.map((w) => (
                    <option key={w}>{w}</option>
                  ))}
                </select>
              </Field>
              <Field label="Style">
                <div className="flex items-center gap-[2px] rounded-[10px] border border-border bg-secondary p-[2px]">
                  {(["stroke", "background"] as const).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setStyle(s)}
                      aria-pressed={style === s}
                      className={`flex-1 rounded-[8px] px-3 py-[5px] text-center text-[11.5px] font-semibold leading-normal transition-colors ${
                        style === s ? "bg-card text-foreground shadow-card" : "text-subtle hover:text-foreground"
                      }`}
                    >
                      {s === "stroke" ? "Outline" : "Panel"}
                    </button>
                  ))}
                </div>
              </Field>
            </div>
            <Hint>
              These positions are not saved anywhere — building the post again puts every slide back to its default
              layout.
            </Hint>
          </div>
        </div>
      </DialogBody>

      <DialogFoot note={`Rebuilds this one slide, for ${accountName} only.`}>
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <PrimaryButton icon={RefreshCw} onClick={rebuild} disabled={busy}>
          {busy ? "Rebuilding…" : "Rebuild this slide"}
        </PrimaryButton>
      </DialogFoot>
    </Dialog>
  );
}

function TextBlock({
  text,
  block,
  weight,
  panel,
  selected,
  onSelect,
  onMove,
  onRelease,
  onNudge,
}: {
  text: string;
  block: Block;
  weight: number;
  panel: boolean;
  selected: boolean;
  onSelect: () => void;
  onMove: (x: number, y: number) => void;
  onRelease: () => void;
  onNudge: (dx: number, dy: number) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const stroke = Math.max(3, Math.floor(block.size / 14)) * SCALE;

  return (
    <div
      tabIndex={0}
      role="button"
      aria-label="Drag to move this text"
      onPointerDown={(e) => {
        onSelect();
        const el = e.currentTarget;
        const box = el.parentElement!.getBoundingClientRect();
        const offX = e.clientX - (box.left + block.x * box.width);
        const offY = e.clientY - (box.top + block.y * box.height);
        el.setPointerCapture(e.pointerId);
        setDragging(true);
        const onPointerMove = (m: PointerEvent) =>
          onMove((m.clientX - offX - box.left) / box.width, (m.clientY - offY - box.top) / box.height);
        const stop = () => {
          setDragging(false);
          onRelease();
          el.removeEventListener("pointermove", onPointerMove);
          el.removeEventListener("pointerup", stop);
        };
        el.addEventListener("pointermove", onPointerMove);
        el.addEventListener("pointerup", stop);
      }}
      onKeyDown={(e) => {
        const d: Record<string, [number, number]> = {
          ArrowUp: [0, -0.01],
          ArrowDown: [0, 0.01],
          ArrowLeft: [-0.01, 0],
          ArrowRight: [0.01, 0],
        };
        if (!d[e.key]) return;
        e.preventDefault();
        onSelect();
        onNudge(d[e.key][0], d[e.key][1]);
      }}
      className={`absolute w-[88%] break-words rounded-[5px] text-center text-white outline-offset-[3px] ${
        dragging ? "cursor-grabbing" : "cursor-grab"
      } ${selected ? "outline outline-1 outline-white" : "outline-dashed outline-1 outline-transparent hover:outline-white/50"}`}
      style={{
        left: `${block.x * 100}%`,
        top: `${block.y * 100}%`,
        transform: `translate(-50%,-50%) scale(${block.zoom})`,
        fontSize: block.size * SCALE,
        fontWeight: weight,
        lineHeight: 1.3,
        ...(panel
          ? {}
          : {
              WebkitTextStroke: `${stroke}px #000`,
              paintOrder: "stroke fill" as React.CSSProperties["paintOrder"],
            }),
      }}
    >
      {panel ? (
        <span className="inline-block rounded-[0.45em] bg-black/[0.67] px-[0.55em] py-[0.27em]">{text}</span>
      ) : (
        text
      )}
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  display,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  display: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-[11.5px] font-semibold leading-normal text-muted-foreground">
        <span>{label}</span>
        <b className="font-bold tabular-nums text-foreground">{display}</b>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-foreground"
      />
    </div>
  );
}

function PagerButton({ children, onClick, label }: { children: React.ReactNode; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="grid h-[26px] w-[26px] place-items-center rounded-[8px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    >
      {children}
    </button>
  );
}

function NudgeButton({ children, onClick, label }: { children: React.ReactNode; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="inline-flex h-[30px] items-center gap-1.5 rounded-[9px] border border-border bg-card px-[9px] text-[11px] font-semibold leading-normal text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    >
      {children}
    </button>
  );
}
