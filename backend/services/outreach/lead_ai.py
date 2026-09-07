"""The two places a language model earns its keep in lead discovery.

It does not do the searching. Finding profiles is browsing, and a model
cannot browse — what it can do is decide *what* to look for, and afterwards
decide what was worth finding:

* **Expansion.** "fitness coaches in Lagos" is not a query any site accepts.
  Turning it into hashtags and search terms is guesswork a model is good at
  and a person finds tedious.
* **Relevance.** A hashtag returns everyone who used it. Reading three
  hundred bios to find the forty that match is exactly the work worth
  handing over, and it is the difference between a lead list and a pile of
  usernames.

Both degrade rather than fail. With no API key, expansion falls back to the
operator's own words and scoring is skipped — a search still runs, it is
just less discriminating. Discovery must not depend on a third party being
reachable.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.request
from typing import Any, Optional

import database as db

MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT_SECONDS = 30

#: Bios scored per request. Large enough to be worth a round trip, small
#: enough that one bad batch does not lose a whole search.
SCORE_BATCH = 25


async def api_key(database, user_id: Optional[int] = None) -> Optional[str]:
    """The same key resolution the rest of the app uses."""
    if user_id:
        try:
            user_map = await db.get_user_settings(database, user_id)
            if user_map.get("anthropic_api_key"):
                return user_map["anthropic_api_key"]
        except Exception:  # noqa: BLE001 — fall through to the global key
            pass
    for key in ("anthropic_api_key", "claude_api_key"):
        try:
            value = await db.get_setting(database, key)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            return value
    return os.environ.get("ANTHROPIC_API_KEY") or None


async def _ask(prompt: str, key: str, max_tokens: int = 800) -> Optional[str]:
    """One completion. Blocking urlopen in a thread, as elsewhere here."""

    def _do() -> Optional[str]:
        body = json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }).encode("utf-8")
        req = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read())
        content = data.get("content") or []
        return ((content[0].get("text") if content else "") or "").strip() or None

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001 — the caller falls back
        print(f"[discovery] model call failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def _json_block(text: str) -> Any:
    """Pull the JSON out of a reply that may be wrapped in prose or fences."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    start = min([i for i in (candidate.find("{"), candidate.find("[")) if i >= 0] or [-1])
    if start < 0:
        return None
    try:
        return json.loads(candidate[start:])
    except ValueError:
        return None


def _fallback_queries(niche: str, location: str, interests: str) -> dict[str, list[str]]:
    """What to search when there is no model available.

    The operator's own words, cleaned up. Worse than expansion, and far
    better than refusing to run.
    """
    # Split each field on its own. Joining them first merges the niche with
    # the first interest into one nonsense phrase.
    pieces = re.split(r"[,\n]+", niche) + re.split(r"[,\n]+", interests)
    terms = [w.strip() for w in pieces if w.strip()][:5] or [niche.strip()]
    tags = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in terms]
    if location.strip():
        tags += [re.sub(r"[^a-z0-9]", "", f"{t}{location}".lower()) for t in terms[:2]]
    return {
        "hashtags": [t for t in dict.fromkeys(tags) if 2 < len(t) < 30][:6],
        "terms": [t for t in dict.fromkeys(terms) if t][:4],
    }


async def expand_query(
    database, niche: str, location: str = "", interests: str = "",
    platform: str = "instagram", user_id: Optional[int] = None,
) -> dict[str, list[str]]:
    """Turn a description of who you want into things a site can be asked."""
    niche, location, interests = niche.strip(), (location or "").strip(), (interests or "").strip()
    key = await api_key(database, user_id)
    if not key:
        return _fallback_queries(niche, location, interests)

    prompt = (
        f"I am looking for {platform} accounts to contact about a business "
        f"partnership.\n\n"
        f"Who: {niche}\n"
        f"Where: {location or 'anywhere'}\n"
        f"Interests: {interests or 'not specified'}\n\n"
        f"Give me hashtags and search terms that would surface accounts like "
        f"this on {platform}. Hashtags without the #, lowercase, no spaces. "
        f"Search terms as a person would type them.\n\n"
        f"Reply with JSON only:\n"
        f'{{"hashtags": ["..."], "terms": ["..."]}}\n'
        f"At most 8 hashtags and 5 terms. Prefer specific over broad — "
        f"#fitness returns the world, #lagosfitnesscoach returns the people."
    )
    parsed = _json_block(await _ask(prompt, key) or "")
    if not isinstance(parsed, dict):
        return _fallback_queries(niche, location, interests)

    def clean(values: Any, limit: int) -> list[str]:
        out = []
        for v in values if isinstance(values, list) else []:
            v = str(v).strip().lstrip("#")
            if v and v not in out:
                out.append(v)
        return out[:limit]

    hashtags = clean(parsed.get("hashtags"), 8)
    terms = clean(parsed.get("terms"), 5)
    if not hashtags and not terms:
        return _fallback_queries(niche, location, interests)
    return {"hashtags": hashtags, "terms": terms}


async def score_leads(
    database, leads: list[dict[str, Any]], niche: str, location: str = "",
    interests: str = "", user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Score each lead 0-100 for fit, with a short reason.

    Returns the same list with `score` and `reason` filled in where the
    model had an opinion. Unscored leads keep `score = None`, which the UI
    shows as unrated rather than as zero — an unscored lead is unknown, not
    bad, and sorting it to the bottom would quietly hide it.
    """
    key = await api_key(database, user_id)
    scorable = [l for l in leads if (l.get("bio") or l.get("display_name"))]
    if not key or not scorable:
        return leads

    by_username = {l["username"]: l for l in leads}
    for start in range(0, len(scorable), SCORE_BATCH):
        batch = scorable[start:start + SCORE_BATCH]
        described = "\n".join(
            f"- {l['username']}: {(l.get('display_name') or '')} — "
            f"{(l.get('bio') or '')[:200]}"
            for l in batch
        )
        prompt = (
            f"I am looking for accounts matching:\n"
            f"Who: {niche}\n"
            f"Where: {location or 'anywhere'}\n"
            f"Interests: {interests or 'not specified'}\n\n"
            f"Score each account 0-100 for how well it matches, with a "
            f"reason of at most 8 words. 0 means clearly not a match; 100 "
            f"means exactly what I asked for. Brands, shops and fan pages "
            f"score low unless I asked for them.\n\n"
            f"Accounts:\n{described}\n\n"
            f"Reply with JSON only:\n"
            f'[{{"username": "...", "score": 0, "reason": "..."}}]'
        )
        parsed = _json_block(await _ask(prompt, key, max_tokens=2000) or "")
        for row in parsed if isinstance(parsed, list) else []:
            lead = by_username.get(str(row.get("username", "")).strip().lstrip("@"))
            if not lead:
                continue
            try:
                score = int(row.get("score"))
            except (TypeError, ValueError):
                continue
            lead["score"] = max(0, min(100, score))
            lead["reason"] = (str(row.get("reason") or "").strip() or None)
    return leads
