/**
 * Readable campaign URLs.
 *
 * `/outreach/17` becomes `/outreach/2nd-tiktok-camp-17`: the name is what
 * you read, the trailing id is what resolves it.
 *
 * The id stays because the name cannot carry the URL on its own. Nothing
 * makes `outreach_campaigns.name` unique — two campaigns may share a name,
 * and one of them would become unreachable — and the name is editable, so
 * a rename would break every link and bookmark already out there. Keeping
 * the id means the slug is decoration: it can be stale, wrong, or missing
 * entirely and the page still opens the right campaign.
 *
 * Old bare-number links keep working, which matters because they are in
 * people's history already.
 */

/** A name, reduced to something that can sit in a path segment. */
export function slugify(name: string): string {
  return (name || "")
    .normalize("NFKD")
    // Strip accents, then anything that is not a letter, digit or space.
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/g, "");
}

/** Where a campaign lives. */
export function campaignPath(campaign: { id: number; name?: string | null }): string {
  const slug = slugify(campaign.name ?? "");
  // A name of only punctuation or emoji slugifies to nothing; the bare id
  // is still a valid URL, just not a pretty one.
  return slug ? `/outreach/${slug}-${campaign.id}` : `/outreach/${campaign.id}`;
}

/**
 * The id inside a route param, from either shape.
 *
 * Returns NaN when there is no id to find, which the page treats the same
 * way it treats any other unloadable campaign.
 */
export function campaignIdFromParam(param: string | string[] | undefined): number {
  const raw = Array.isArray(param) ? param[0] : param;
  if (!raw) return NaN;
  const match = /(?:^|-)(\d+)$/.exec(raw);
  return match ? Number(match[1]) : NaN;
}
