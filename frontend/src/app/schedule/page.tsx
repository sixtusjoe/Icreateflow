"use client";

import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { getSchedule, getBrands } from "@/lib/api";

export default function SchedulePage() {
  const [scheduled, setScheduled] = useState<any[]>([]);
  const [brands, setBrands] = useState<any[]>([]);
  const [filterBrand, setFilterBrand] = useState<string>("all");

  useEffect(() => { getBrands().then(setBrands).catch(() => {}); }, []);

  useEffect(() => {
    const brandId = filterBrand !== "all" ? Number(filterBrand) : undefined;
    getSchedule(brandId).then(setScheduled).catch(() => {});
  }, [filterBrand]);

  const byDate: Record<string, any[]> = {};
  scheduled.forEach((p) => {
    if (!byDate[p.date]) byDate[p.date] = [];
    byDate[p.date].push(p);
  });

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Schedule</h1>
          <p className="mt-1 text-sm text-muted-foreground">Upcoming scheduled posts by date.</p>
        </div>
        <select
          value={filterBrand}
          onChange={(e) => setFilterBrand(e.target.value)}
          className="rounded-lg border border-border bg-background px-4 py-2.5 text-sm outline-none focus:border-foreground"
        >
          <option value="all">All Brands</option>
          {brands.map((b: any) => (
            <option key={b.id} value={String(b.id)}>{b.name}</option>
          ))}
        </select>
      </div>

      {Object.keys(byDate).length === 0 ? (
        <div className="rounded-2xl bg-card p-8 text-center">
          <p className="text-muted-foreground">No scheduled posts.</p>
          <p className="mt-1 text-sm text-muted-foreground/60">Create and schedule posts from the New Post page.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(byDate)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([date, posts]) => (
              <div key={date}>
                <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{date}</h2>
                <div className="space-y-2">
                  {posts
                    .sort((a, b) => (a.scheduled_time || "").localeCompare(b.scheduled_time || ""))
                    .map((post) => (
                      <div key={post.id} className="flex items-center justify-between rounded-xl bg-card px-5 py-3.5">
                        <div className="flex items-center gap-4">
                          <span className="w-14 text-center text-sm font-bold">
                            {post.scheduled_time || "--:--"}
                          </span>
                          <span className="rounded-md bg-foreground px-2 py-0.5 text-xs font-medium text-background">
                            {post.brand_name}
                          </span>
                          <span className="text-sm">Post #{post.post_number}</span>
                        </div>
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize">
                          {post.status}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
