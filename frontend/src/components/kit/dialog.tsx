"use client";

/**
 * The glass dialogs the outreach pages open.
 *
 * Same material as the sidebar — blurred, saturated, lifted — stepped
 * opaque enough to carry body text over a blurred page. Two details are
 * deliberate and easy to lose:
 *
 *  - **No scrollbars inside the glass.** A grey track cuts straight
 *    through the material the panel is made of. The panes still scroll.
 *  - **The footer is pinned.** A long body scrolls under it rather than
 *    pushing the primary action off the bottom of the screen.
 */

import { useEffect, useId, useState } from "react";
import { Check, Info, Trash2, X } from "lucide-react";

/* ------------------------------------------------------------------ */
/* shell                                                               */
/* ------------------------------------------------------------------ */

const WIDTH = {
  sm: "max-w-[440px]",
  /** the destructive confirmation — wide enough that a consequence line does not wrap */
  confirm: "max-w-[492px]",
  md: "max-w-[536px]",
  lg: "max-w-[640px]",
  xl: "max-w-[880px]",
};

export function Dialog({
  open,
  onClose,
  label,
  size = "md",
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  size?: keyof typeof WIDTH;
  children: React.ReactNode;
}) {
  // Escape closes, and the page behind must not scroll while it is up.
  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onEsc);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onEsc);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      className="fixed inset-0 z-[200] flex items-center justify-center bg-[rgba(11,13,18,0.34)] p-6 backdrop-blur-[7px] max-sm:p-3 dark:bg-black/50"
    >
      <div
        className={`relative flex max-h-[calc(100dvh-48px)] max-sm:max-h-[calc(100dvh-24px)] w-full flex-col overflow-hidden rounded-[22px] border
                    border-[rgba(255,255,255,0.75)] bg-[rgba(255,255,255,0.84)] backdrop-blur-[28px] backdrop-saturate-[1.85]
                    shadow-[0_34px_80px_-24px_rgba(16,24,40,0.45),0_6px_20px_-8px_rgba(16,24,40,0.2),inset_0_1px_0_rgba(255,255,255,0.7)]
                    dark:border-white/10 dark:bg-[rgba(24,28,37,0.86)]
                    dark:shadow-[0_34px_80px_-24px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.1)]
                    [&_*]:[scrollbar-width:none] [&_*::-webkit-scrollbar]:hidden ${WIDTH[size]}`}
      >
        {/* the light catching the top edge — without it the glass reads flat */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-[120px]
                     bg-[linear-gradient(180deg,rgba(255,255,255,0.5),rgba(255,255,255,0))]
                     dark:bg-[linear-gradient(180deg,rgba(255,255,255,0.07),rgba(255,255,255,0))]"
        />
        {children}
      </div>
    </div>
  );
}

export function DialogHead({
  title,
  sub,
  icon,
  onClose,
}: {
  title: string;
  sub?: React.ReactNode;
  /** A tile to the left of the title — the destructive confirm wears a red one. */
  icon?: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="relative flex items-start gap-3.5 px-[22px] pt-5">
      {icon}
      <div className="min-w-0">
        <div className="text-[17px] font-extrabold leading-normal tracking-[-0.02em] text-foreground">{title}</div>
        {sub && <div className="mt-1 max-w-[46ch] text-xs leading-[1.5] text-subtle">{sub}</div>}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="ml-auto grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        <X className="h-[15px] w-[15px]" />
      </button>
    </div>
  );
}

export function DialogBody({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`relative min-h-0 overflow-y-auto px-[22px] pb-1 pt-[18px] ${className}`}>{children}</div>;
}

/**
 * The footer. `note` sits hard left and pushes the buttons right, which
 * is where a caveat about what the primary action will do belongs.
 *
 * The buttons never give up width: they are `flex-none` and the note is
 * the only thing allowed to shrink or wrap. Without that, a long note
 * squeezed the primary button until its label broke over two lines and
 * the whole footer grew a row.
 */
export function DialogFoot({ note, children }: { note?: React.ReactNode; children: React.ReactNode }) {
  return (
    // Wraps rather than overflows: three buttons do not fit a phone's width
    // in one row, and the last one ran off the dialog's edge.
    <div className="relative mt-auto flex flex-wrap items-center justify-end gap-3 px-[22px] pb-5 pt-4">
      {note && (
        <span className="mr-auto min-w-0 text-[11.5px] leading-[1.45] text-subtle">{note}</span>
      )}
      <span className={`flex max-w-full flex-wrap items-center justify-end gap-[9px] ${note ? "" : "ml-auto"}`}>
        {children}
      </span>
    </div>
  );
}

export function GhostButton({
  children,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...rest}
      className={`flex-none whitespace-nowrap rounded-[11px] border border-border bg-card px-4 py-[9px] text-[12.5px] font-semibold leading-normal text-foreground transition-colors hover:bg-secondary disabled:cursor-default disabled:opacity-45 ${className}`}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* form pieces                                                         */
/* ------------------------------------------------------------------ */

export function FieldLabel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`mb-[9px] text-[10.5px] font-bold uppercase leading-normal tracking-[0.09em] text-subtle ${className}`}>
      {children}
    </div>
  );
}

export function Hint({ children, tone }: { children: React.ReactNode; tone?: "bad" }) {
  return (
    <div className={`mt-2 flex items-start gap-1.5 text-[11px] leading-[1.5] ${tone === "bad" ? "text-bad" : "text-subtle"}`}>
      <Info className="mt-0.5 h-3 w-3 flex-none" />
      <span>{children}</span>
    </div>
  );
}

const FIELD =
  "w-full rounded-[12px] border border-border bg-card px-3 py-[9px] text-[12.5px] leading-normal text-foreground outline-none transition-colors placeholder:text-subtle focus:border-subtle";

export function Input(props: React.ComponentPropsWithRef<"input">) {
  const { className = "", ...rest } = props;
  return <input {...rest} className={`${FIELD} ${className}`} />;
}

/** `plain` is for prose — a caption, a note. The monospace default is for
 *  the things where a character's identity matters: a prompt, a URL, a
 *  template body. A caption set in mono reads as configuration. */
export function Textarea({
  plain,
  ...props
}: React.ComponentPropsWithRef<"textarea"> & { plain?: boolean }) {
  const { className = "", ...rest } = props;
  return (
    <textarea
      spellCheck={plain ? undefined : false}
      {...rest}
      className={`${FIELD} resize-y px-3.5 py-[11px] leading-[1.6] ${
        plain ? "text-[12.5px]" : "font-mono text-xs"
      } ${className}`}
    />
  );
}

/** A labelled field, stacked. */
export function Field({
  label,
  children,
  className = "",
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-[5px] ${className}`}>
      <span className="text-[11.5px] font-semibold leading-normal text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export function Checkbox({
  checked,
  onChange,
  children,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex cursor-pointer items-center gap-[9px] px-0.5 py-1.5 text-[12.5px] leading-normal text-muted-foreground ${
        disabled ? "cursor-default opacity-50" : ""
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="pointer-events-none absolute opacity-0"
      />
      <span
        className={`grid h-4 w-4 flex-none place-items-center rounded-[5px] border-[1.5px] transition-colors ${
          checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-transparent"
        }`}
      >
        <Check className="h-[11px] w-[11px]" strokeWidth={3} />
      </span>
      {children}
    </label>
  );
}

export function Radio({
  checked,
  onChange,
  children,
  right,
  disabled,
}: {
  checked: boolean;
  onChange: () => void;
  children: React.ReactNode;
  right?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      onClick={() => !disabled && onChange()}
      className={`flex items-center gap-2.5 rounded-[12px] border border-border bg-card px-3 py-2.5 transition-colors ${
        disabled ? "cursor-not-allowed opacity-55" : "cursor-pointer hover:bg-secondary"
      }`}
    >
      <span
        className={`grid h-[15px] w-[15px] flex-none place-items-center rounded-full border-[1.5px] ${
          checked
            ? "border-primary shadow-[inset_0_0_0_3.5px_var(--card),inset_0_0_0_9px_var(--primary)]"
            : "border-border"
        }`}
      />
      <span className="flex min-w-0 flex-col">{children}</span>
      {right}
    </label>
  );
}

/** The step rail on a multi-stage dialog. */
export function Steps({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="relative flex items-center gap-[9px] px-[22px] pt-4">
      {steps.map((s, i) => (
        <span key={s} className="contents">
          {i > 0 && <span className="h-px flex-1 bg-border" />}
          <span
            className={`flex items-center gap-[7px] text-[11.5px] font-semibold leading-normal ${
              i === current ? "text-foreground" : "text-subtle"
            }`}
          >
            <i
              className={`grid h-[19px] w-[19px] place-items-center rounded-full text-[10px] font-bold not-italic ${
                i < current
                  ? "bg-chart-1 text-black"
                  : i === current
                    ? "bg-primary text-primary-foreground"
                    : "bg-border text-muted-foreground"
              }`}
            >
              {i + 1}
            </i>
            {s}
          </span>
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* confirmations                                                       */
/* ------------------------------------------------------------------ */

export function DangerButton({
  children,
  className = "",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex flex-none items-center gap-[7px] whitespace-nowrap rounded-[11px] bg-bad px-4 py-[9px] text-[12.5px] font-bold leading-normal text-white
                  shadow-[0_8px_18px_-9px_rgba(229,72,77,0.7)] transition-[filter,opacity] hover:brightness-110
                  disabled:cursor-default disabled:opacity-45 disabled:hover:brightness-100 ${className}`}
    >
      {children}
    </button>
  );
}

/**
 * The destructive confirmation.
 *
 * `confirmText` guards the ones that cannot be undone and take other
 * records with them: the button stays dead until the name is typed back.
 * Everything else is a plain confirm — a campaign's targets are worth a
 * deliberate act, an account's row is not.
 */
type ConfirmProps = {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  body: React.ReactNode;
  /** What is destroyed — a red dot each. */
  bullets?: React.ReactNode[];
  /** What survives — a green check each. The pair is the whole point of the
   *  dialog: "are you sure?" tells the operator nothing they did not know. */
  keeps?: React.ReactNode[];
  note?: React.ReactNode;
  confirmLabel: string;
  confirmText?: string;
  busy?: boolean;
};

export function ConfirmDialog(props: ConfirmProps) {
  // The typed-name guard lives one level down so that closing the dialog
  // unmounts it. Resetting it from an effect on `open` would work, but it
  // is a cascading render to undo state that never needed to survive.
  return (
    <Dialog open={props.open} onClose={props.onClose} label={props.title} size="confirm">
      <ConfirmBody {...props} />
    </Dialog>
  );
}

function ConfirmBody({
  onClose,
  onConfirm,
  title,
  body,
  bullets,
  keeps,
  note,
  confirmLabel,
  confirmText,
  busy,
}: ConfirmProps) {
  const [typed, setTyped] = useState("");
  const id = useId();

  const armed = !confirmText || typed.trim() === confirmText.trim();

  return (
    <>
      <DialogHead
        title={title}
        sub={body}
        onClose={onClose}
        icon={
          <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-[11px] bg-bad/[0.13] text-bad">
            <Trash2 className="h-[17px] w-[17px]" />
          </span>
        }
      />
      <DialogBody>
        <div className="flex flex-col gap-[9px]">
          {bullets?.map((b, i) => (
            <div key={`x${i}`} className="flex items-start gap-[9px] text-[12.5px] leading-[1.5] text-muted-foreground">
              <span className="mt-[7px] h-[5px] w-[5px] flex-none rounded-full bg-bad" />
              <span>{b}</span>
            </div>
          ))}
          {keeps?.map((k, i) => (
            <div key={`k${i}`} className="flex items-start gap-[9px] text-[12.5px] leading-[1.5] text-subtle">
              <Check className="mt-[3px] h-[13px] w-[13px] flex-none text-good" strokeWidth={2.6} />
              <span>{k}</span>
            </div>
          ))}
        </div>
        {confirmText && (
          <div className="mt-4 border-t border-border pt-3.5">
            <label htmlFor={id} className="text-[11.5px] font-semibold leading-normal text-muted-foreground">
              Type <b className="font-mono text-[11.5px] font-bold text-foreground">{confirmText}</b> to confirm
            </label>
            <Input
              id={id}
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && armed && !busy && onConfirm()}
              placeholder={confirmText}
              className="mt-1.5"
              autoComplete="off"
            />
          </div>
        )}
        {note && <Hint>{note}</Hint>}
      </DialogBody>
      <DialogFoot>
        <GhostButton onClick={onClose} disabled={busy}>
          Cancel
        </GhostButton>
        <DangerButton onClick={onConfirm} disabled={!armed || busy}>
          <Trash2 className="h-3.5 w-3.5" />
          {busy ? "Working…" : confirmLabel}
        </DangerButton>
      </DialogFoot>
    </>
  );
}
