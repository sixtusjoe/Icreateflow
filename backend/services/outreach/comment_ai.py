"""Rewrite a reply so no two are the same.

TikTok hides a comment it has seen before. A campaign posting one line
under a hundred comments is posting the same string a hundred times, and
most of those never appear to anyone — the reply is sent, the account is
spent, and nobody reads it.

So each reply is paraphrased before it goes out: same meaning, same
voice, different words. The campaign's lines stay what the operator
wrote; this varies them.

Never blocks a reply. Every failure — no key, a refusal, a timeout, an
answer that looks nothing like the original — falls back to the line as
written, which is exactly what would have been posted without this.

Raw HTTP rather than the SDK, deliberately: the Anthropic client this
project already has (services/caption_variants.py, doing this same job
for clip captions) is written this way, the SDK is not installed here or
on the server, and one shape for both is worth more than the nicer call.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Optional, Sequence

import database as db

#: Opus, not a cheaper model, because the whole job is sounding like a
#: person rather than a template. The bill is small either way — a reply
#: is a few hundred tokens in and a few dozen out, so a thousand of them
#: costs on the order of a pound or two. Change it here if that is wrong.
MODEL = "claude-opus-5"

#: A paraphrase of one line needs no deliberation, and effort is what
#: that costs.
EFFORT = "low"

#: Long enough for a sentence and the odd emoji, short enough that a
#: runaway answer cannot become a comment.
MAX_TOKENS = 200

#: How long to wait before giving up and posting the line as written.
TIMEOUT_SECONDS = 20

#: How many of the campaign's recent replies to show the model so it does
#: not walk back into one it has already used.
RECENT_TO_AVOID = 25

#: A rewrite this much longer than the original is not a rewrite.
LENGTH_CEILING = 2.2

PROMPT = """Rewrite this comment so it says the same thing in different words.

It is a reply to someone on TikTok, so it has to read like a person typed \
it — not a brand, not a slogan, not customer service.

Rules:
- Keep the meaning and the tone.
- Change the wording. Do not reuse the same phrasing.
- Keep it roughly the same length. Short is good.
- Match the original's register: if it is lower case, stay lower case; if \
it has an emoji, an emoji is fine; if it has none, do not add one.
- Keep any link, handle or code exactly as written.
- Reply with the rewritten comment and nothing else. No quotes, no \
preamble, no explanation, no options.

The comment:
{line}
{avoid}"""

AVOID_BLOCK = """
Already used under this video — do not write anything close to these:
{lines}"""


def _looks_like_a_refusal(text: str, original: str) -> bool:
    """Did the model answer the request, or talk about it?

    A refusal or a clarifying question is longer, and usually opens the
    way this list does. Posting one of those as a comment would be worse
    than posting a duplicate.
    """
    low = text.lower()
    openers = (
        "i can't", "i cannot", "i won't", "i'm not able", "i am not able",
        "sorry", "as an ai", "here are", "here's a", "here is a",
        "sure!", "certainly", "i'd be happy", "could you", "which ",
    )
    if any(low.startswith(o) for o in openers):
        return True
    # A rewrite of one line does not arrive as a list.
    if "\n" in text.strip() and len(text.strip().splitlines()) > 2:
        return True
    return len(text) > max(len(original) * LENGTH_CEILING, len(original) + 60)


async def _api_key(database, user_id: Optional[int] = None) -> Optional[str]:
    """The same key the rest of the app uses, looked up the same way."""
    if user_id:
        try:
            settings = await db.get_user_settings(database, user_id)
            key = settings.get("anthropic_api_key")
            if key:
                return key
        except Exception:  # noqa: BLE001 — a missing row is not a failure
            pass
    for name in ("anthropic_api_key", "claude_api_key"):
        try:
            value = await db.get_setting(database, name)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            return value
    return os.environ.get("ANTHROPIC_API_KEY") or None


async def _ask(prompt: str, api_key: str) -> Optional[str]:
    """One call, on a thread, so the worker's loop keeps running."""

    def _call() -> Optional[str]:
        body = json.dumps({
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "output_config": {"effort": EFFORT},
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        # A safety refusal comes back as a 200 with this stop reason, and
        # its text is an explanation, not a comment.
        if payload.get("stop_reason") == "refusal":
            return None
        for block in payload.get("content") or []:
            if block.get("type") == "text" and (block.get("text") or "").strip():
                return block["text"].strip()
        return None

    return await asyncio.to_thread(_call)


async def vary(
    database,
    line: str,
    *,
    avoid: Sequence[str] = (),
    user_id: Optional[int] = None,
) -> str:
    """The line to actually post — reworded, or the original if anything fails.

    `avoid` is what this campaign has already posted under the video.
    Showing it to the model is what stops the rewrites converging on one
    another, which is the same problem one step along.
    """
    original = (line or "").strip()
    if not original:
        return original

    key = await _api_key(database, user_id)
    if not key:
        return original

    recent = [a.strip() for a in avoid if a and a.strip()][-RECENT_TO_AVOID:]
    prompt = PROMPT.format(
        line=original,
        avoid=AVOID_BLOCK.format(lines="\n".join(f"- {r}" for r in recent))
        if recent else "",
    )

    try:
        answer = await _ask(prompt, key)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, OSError) as exc:
        print(f"[outreach] could not vary the reply ({type(exc).__name__}) — "
              f"posting it as written", flush=True)
        return original
    except Exception as exc:  # noqa: BLE001 — a rewrite must never lose a reply
        print(f"[outreach] varying the reply failed ({type(exc).__name__}: "
              f"{exc}) — posting it as written", flush=True)
        return original

    if not answer or _looks_like_a_refusal(answer, original):
        return original
    # Models like to wrap a rewrite in quotes even when told not to.
    return answer.strip().strip('"').strip("'").strip() or original
