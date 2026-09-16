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
import re
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

#: A rewrite this much longer than the original is not a rewrite — but
#: a comment that reads naturally is worth a few more words, so this is
#: loose. It exists to catch an answer that stopped being a comment, not
#: to hold the wording to the original's length.
LENGTH_CEILING = 2.2

#: The obfuscated links these comments carry: t(dot)me/name, site(dot)club.
#: Written this way so the platform does not strip them, which means they
#: only work character for character — a rewrite that tidies "(dot)" into
#: "." or dresses the link up in words has thrown the comment away.
LINK = re.compile(r"\S*\(dot\)\S*", re.I)

#: The same link before anyone hid the dot: aceultra.club, t.me/name. A
#: campaign's own line usually carries one of these, and posting it as
#: written is how a comment gets stripped — so it goes out in the (dot)
#: form instead.
PLAIN_LINK = re.compile(
    r"\b([\w-]+(?:\.[\w-]+)*)\.(club|com|me|net|org|co|io|shop|store|link)"
    r"(/\S*)?",
    re.I,
)


def dotted(link: str) -> str:
    """A link written the way it has to be posted.

    The dot before the suffix is the one that gets a comment stripped, so
    that is the one that is hidden: aceultra.club -> Aceultra(dot)club,
    t.me/name -> t(dot)me/name.
    """
    match = PLAIN_LINK.search(link or "")
    if not match:
        return link
    host, suffix, path = match.group(1), match.group(2), match.group(3) or ""
    return f"{host}(dot){suffix}{path}"


def required_link(line: str) -> Optional[str]:
    """The link this comment has to carry, in the form it has to carry it.

    Taken as written when it is already hidden; converted when it is not.
    A comment that asks nobody to go anywhere has spent an account's
    attempt for nothing.
    """
    already = LINK.findall(line or "")
    if already:
        return already[0]
    match = PLAIN_LINK.search(line or "")
    return dotted(match.group(0)) if match else None

PROMPT = """Rewrite this TikTok comment so it says the same thing in \
different words.

It is a reply to someone, so it has to read like a person typed it — not \
a brand, not a slogan, not customer service. These are the shape to aim \
for:

    We do free samples! t(dot)me/wesellmuha
    visit our store Aceultra(dot)club
    join our tele channel t(dot)me/wesellmuha

Rules:
- Keep it short. One line, about as long as the original — these are \
comments, not adverts.
- Change the wording. Do not reuse the original's phrasing, or any \
phrasing listed below as already used.
- Include this link exactly as written, character for character: {link}
  Never turn "(dot)" into ".", never describe the link in words, never \
leave it out. It is the whole point of the comment.
- Match the original's register: if it is lower case, stay lower case; \
if it has an emoji, an emoji is fine; if it has none, do not add one.
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
    link = required_link(original)
    prompt = PROMPT.format(
        line=original,
        link=link or "(none — the comment carries no link)",
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

    # Every link in the original has to survive, exactly. A comment whose
    # link was tidied into a real dot, described in words, or dropped is
    # a comment that cost an account's attempt and asks nobody to go
    # anywhere — worse than posting the line unchanged.
    # The link is not negotiable. If the rewrite dropped it, put it back
    # rather than throwing a good comment away: a reply without it costs
    # the same attempt and asks nobody to go anywhere.
    answer = answer.strip().strip('"').strip("'").strip()
    if link and link.lower() not in answer.lower():
        print(f"[outreach] the rewrite dropped {link} — putting it back",
              flush=True)
        answer = f"{answer} {link}".strip()
    return answer or original
