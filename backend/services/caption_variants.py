"""Per-(clip, variation, platform) caption paraphrasing for clipping only.

Phase 2 of the anti-reuse stack. Each variation+platform gets its own
paraphrased version of the clip's base caption so platforms see distinct
text fingerprints across the re-posts. Results are cached in
`clip_caption_variants` keyed by (clip_id, variation_id, platform), so:
  * Re-running the dispatcher returns the same text (idempotent).
  * Editing the clip's base caption invalidates and regenerates on next post.

Uses Claude (same Anthropic key we use for OCR). Falls back to the raw
base caption on any failure — never blocks a post.

The brands/Post Now pipeline DOES NOT call this. Clipping only.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import urllib.request
import urllib.error
from typing import Optional

import database as db


# Phrases that strongly indicate the model refused / asked for clarification
# instead of producing a rewrite. If the model output matches any of these we
# must NOT post it — fall back to the original caption.
_REFUSAL_PATTERNS = [
    r"\bi need (?:the|more|a) ",
    r"\bi don'?t have ",
    r"\bi (?:can'?t|cannot) ",
    r"\bas an ai\b",
    r"\bcould you (?:provide|share|clarify) ",
    r"\bplease (?:provide|share|clarify) ",
    r"\bthe original (?:only|just) shows\b",
    r"\bthis is just a (?:hashtag|emoji)\b",
    r"\bno actual (?:caption|content)\b",
    r"\bneeds? rewriting\??\s*$",
    r"\bcaption text to rewrite\b",
    r"\bwhat (?:would|do) you\b",
    r"^i'?m (?:sorry|unable) ",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), re.IGNORECASE)


def _caption_is_trivial(text: str) -> bool:
    """True when the caption has no meaningful words to rewrite.

    A caption that's just hashtags / mentions / emoji / whitespace can't be
    paraphrased — asking an LLM to rewrite it produces a clarification reply
    like 'I need the original caption text to rewrite...' which then gets
    posted verbatim. Skip the LLM in this case.
    """
    t = (text or "").strip()
    if not t:
        return True
    # Strip hashtags and @mentions, then strip emoji/symbols and whitespace.
    stripped = re.sub(r"[#@]\w+", " ", t)
    # Keep letters/digits; drop everything else.
    alnum = re.sub(r"[^\w\s]", " ", stripped, flags=re.UNICODE)
    words = [w for w in alnum.split() if any(c.isalpha() for c in w) and len(w) >= 2]
    # Need at least 2 real words (3+ chars of content combined) to attempt a rewrite.
    return len(words) < 2 or sum(len(w) for w in words) < 4


def _looks_like_refusal(variant: str, base_caption: str) -> bool:
    """Reject LLM outputs that are meta-replies instead of rewrites."""
    v = (variant or "").strip()
    if not v:
        return True
    if _REFUSAL_RE.search(v):
        return True
    # Contains the literal base caption AND trailing prose — often a
    # "the original only shows: X. This is just ..." pattern.
    if base_caption and base_caption in v and len(v) > len(base_caption) * 3:
        return True
    # Extremely long compared to source (hallucinated preamble).
    if base_caption and len(v) > max(400, len(base_caption) * 4):
        return True
    return False


# Platform-specific guardrails. Kept conservative — we want the text to
# stay in the creator's voice, not to look AI-rewritten.
_PLATFORM_NOTES = {
    "tiktok": "Keep it punchy. Hashtags allowed at the end. No @mentions.",
    "youtube": "This is a YouTube Shorts title+description. 1–3 short lines. Hashtags at the end.",
    "instagram": "Instagram Reels caption. Emojis welcome. Hashtags at the end.",
    "facebook": "Facebook Reels description. Slightly more conversational. Hashtags at the end.",
}


def _seed_hint(clip_id: int, variation_id: int, platform: str) -> str:
    """Stable short hash to mix into the prompt so variants differ across
    (variation, platform) even when the base caption is identical."""
    h = hashlib.sha256(f"{clip_id}:{variation_id}:{platform}".encode()).hexdigest()
    return h[:8]


def _build_prompt(base_caption: str, platform: str, seed: str) -> str:
    notes = _PLATFORM_NOTES.get(platform, "")
    return f"""Rewrite the caption below so it reads like a different human wrote it, without changing the meaning. This is one of several variation accounts re-posting the same video — the text must NOT look like a duplicate to the platform's reuse detection.

Rules:
- Same meaning, different wording. Reorder, substitute synonyms, vary punctuation/emojis.
- Keep the same approximate length (±30%).
- Do NOT add new claims, facts, names, prices, or links that weren't in the original.
- Preserve hashtags as a set but you MAY reorder them and drop at most one.
- No @mentions that weren't in the original.
- {notes}
- Output ONLY the new caption, no preamble, no quotes, no "Here's a rewrite:".

variation-seed: {seed}

Original:
{base_caption}
"""


async def _call_claude(prompt: str, api_key: str) -> Optional[str]:
    """Thin wrapper over the Anthropic messages API. Runs the blocking
    urlopen in a thread so the dispatcher loop isn't blocked."""

    def _do():
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        content = data.get("content") or []
        if not content:
            return None
        return (content[0].get("text") or "").strip() or None

    return await asyncio.to_thread(_do)


async def _get_api_key(database, user_id: Optional[int] = None) -> Optional[str]:
    if user_id:
        user_map = await db.get_user_settings(database, user_id)
        user_key = user_map.get("anthropic_api_key")
        if user_key:
            return user_key
    for k in ("anthropic_api_key", "claude_api_key"):
        v = await db.get_setting(database, k)
        if v:
            return v
    return os.environ.get("ANTHROPIC_API_KEY") or None


async def get_variant(
    database,
    clip_id: int,
    variation_id: int,
    platform: str,
    base_caption: str,
    user_id: Optional[int] = None,
) -> str:
    """Return a paraphrased caption for this (clip, variation, platform).

    * Cache hit with matching source_caption → return cached text.
    * Cache miss or source_caption drift → regenerate via Claude and upsert.
    * Any failure (no API key, network error, empty output) → return the
      original base_caption so the post still goes out.
    """
    base_caption = (base_caption or "").strip()
    if not base_caption:
        return ""

    # Trivial captions (just hashtags / emoji / a couple chars) produce
    # LLM refusals, not rewrites. Skip the model and post the original.
    if _caption_is_trivial(base_caption):
        return base_caption

    try:
        cached = await db.get_clip_caption_variant(database, clip_id, variation_id, platform)
    except Exception:
        cached = None

    if (
        cached
        and (cached.get("source_caption") or "") == base_caption
        and cached.get("caption")
        and not _looks_like_refusal(cached["caption"], base_caption)
    ):
        return cached["caption"]

    api_key = await _get_api_key(database, user_id=user_id)
    if not api_key:
        return base_caption

    seed = _seed_hint(clip_id, variation_id, platform)
    prompt = _build_prompt(base_caption, platform, seed)
    try:
        variant = await _call_claude(prompt, api_key)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception):
        variant = None

    # Reject empty OR refusal-shaped output. NEVER post an LLM meta-reply.
    if not variant or _looks_like_refusal(variant, base_caption):
        return base_caption

    # Defensive length cap — TikTok caps at ~2200 chars, the others are
    # more generous. Never let a hallucinated long rewrite through.
    if len(variant) > 2200:
        variant = variant[:2200]

    try:
        await db.upsert_clip_caption_variant(
            database, clip_id, variation_id, platform,
            caption=variant, source_caption=base_caption,
        )
    except Exception:
        # Caching failed but the variant is still usable for this post.
        pass
    return variant
