"use client";

/** Any slide image, full size.
 *
 *  Every image on the editor is a thumbnail of something that ends up on a
 *  phone screen, so every one of them opens here. Escape and the backdrop
 *  both close it.
 */

import { useEffect } from "react";
import { X } from "lucide-react";

export function Lightbox({
  src,
  caption,
  onClose,
}: {
  src: string | null;
  caption?: string;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!src) return;
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onEsc);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onEsc);
      document.body.style.overflow = prev;
    };
  }, [src, onClose]);

  if (!src) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={caption || "Full size"}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-3.5 bg-[rgba(10,12,16,0.86)] p-6 backdrop-blur-[6px]"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute right-[22px] top-5 grid h-9 w-9 place-items-center rounded-[11px] border border-white/20 bg-white/10 text-white transition-colors hover:bg-white/20"
      >
        <X className="h-[17px] w-[17px]" />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={caption || "Slide"}
        className="max-h-[80vh] max-w-[min(90vw,520px)] rounded-[14px] object-contain shadow-[0_30px_70px_-30px_rgba(0,0,0,0.9)]"
      />
      {caption && <figcaption className="text-[12.5px] font-semibold text-white/80">{caption}</figcaption>}
    </div>
  );
}
