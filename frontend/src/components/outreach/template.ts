/**
 * The client's copy of the template rules.
 *
 * This is a mirror of `backend/services/outreach/templates.py`, not a
 * second opinion: the same regex, the same built-ins, the same limit, the
 * same order of checks. The server still validates — this only moves the
 * "no" to where the typing happens, so nobody fills in a whole dialog to
 * be told at Create that a brace is wrong.
 *
 * If the Python changes, change this with it.
 */

/** `{{ name }}` — letters, digits, underscore. Whitespace inside is tolerated. */
export const PLACEHOLDER_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;

/** Always available: filled from the target, campaign and account rows. */
export const BUILTIN_VARIABLES = ["username", "profile_url", "campaign_name", "account_name"];

export const MAX_BODY_LENGTH = 4000;

/** Placeholder names, in first-appearance order, deduplicated. */
export function extractVariables(body: string): string[] {
  const seen: string[] = [];
  for (const m of (body || "").matchAll(PLACEHOLDER_RE)) {
    if (!seen.includes(m[1])) seen.push(m[1]);
  }
  return seen;
}

/** The placeholders this campaign has to supply a value for. */
export function ownVariables(body: string): string[] {
  return extractVariables(body).filter((v) => !BUILTIN_VARIABLES.includes(v));
}

/** The message the server would give, or null when the body is fine. */
export function validateTemplate(body: string): string | null {
  if (!body || !body.trim()) return "A message campaign needs a body.";
  if (body.length > MAX_BODY_LENGTH)
    return `Body is ${body.length.toLocaleString()} characters; the limit is ${MAX_BODY_LENGTH.toLocaleString()}.`;
  // Strip the well-formed placeholders, then look for leftover braces.
  const residue = body.replace(PLACEHOLDER_RE, "");
  if (residue.includes("{{") || residue.includes("}}"))
    return "Malformed placeholder — use {{variable_name}}.";
  return null;
}

/** `{"offer": "..."}` as the create/update payload wants it, blanks dropped. */
export function varsPayload(values: Record<string, string>): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) if (v.trim()) out[k] = v.trim();
  return Object.keys(out).length ? out : undefined;
}
