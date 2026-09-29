"use client";

/** A slide thumbnail that degrades instead of breaking.
 *
 *  A rendered file can be missing — cleared off disk, or never built — and
 *  the browser's broken-image glyph says nothing useful. This falls back to
 *  the slide number on the same surface the placeholder uses, so a gap looks
 *  deliberate rather than damaged.
 */

import { useState } from "react";
import { ImageOff } from "lucide-react";

export function SlideImage({
  src,
  label,
  className = "",
  alt = "",
}: {
  src?: string | null;
  label?: number | string;
  className?: string;
  alt?: string;
}) {
  const [broken, setBroken] = useState(false);

  if (!src || broken)
    return (
      <span
        title={src ? "This file is not on disk" : "Nothing here yet"}
        className={`grid h-full w-full place-items-center gap-0.5 bg-secondary text-subtle ${className}`}
      >
        {label !== undefined ? (
          <span className="text-xs font-bold tabular-nums">{label}</span>
        ) : (
          <ImageOff className="h-4 w-4" />
        )}
      </span>
    );

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} onError={() => setBroken(true)} className={`h-full w-full object-cover ${className}`} />
  );
}
