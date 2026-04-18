"use client";

import { Scissors } from "lucide-react";

export default function ClippingPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 md:mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-foreground">
          <Scissors className="h-5 w-5 text-background" />
        </div>
        <div>
          <h1 className="text-xl md:text-2xl font-bold tracking-tight">Clipping</h1>
          <p className="mt-1 text-sm text-muted-foreground">Turn long videos into short-form clips.</p>
        </div>
      </div>
      <div className="rounded-2xl bg-card p-8 text-center">
        <p className="text-muted-foreground">Coming soon.</p>
        <p className="mt-1 text-sm text-muted-foreground/60">We'll notify you when this is ready.</p>
      </div>
    </div>
  );
}
