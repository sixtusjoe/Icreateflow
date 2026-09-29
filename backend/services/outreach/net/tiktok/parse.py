"""TikTok JSON -> LeadRow. Knows the response shape and nothing else."""
from __future__ import annotations

from typing import Any, Iterable

from services.outreach.net.result import LeadRow
from services.outreach.net.tiktok import endpoints


def leads_from_comments(
    payload: dict[str, Any], source: str | None = None
) -> list[LeadRow]:
    """Everyone who wrote one of these comments, de-duplicated in order.

    A person who commented five times is one lead. Keeping the first
    occurrence rather than the last means the order a caller sees is the
    order the platform returned, which is what makes a partial read
    reproducible.
    """
    seen: set[str] = set()
    rows: list[LeadRow] = []
    for comment in payload.get("comments") or []:
        user = comment.get("user") or {}
        handle = (user.get("unique_id") or "").strip()
        if not handle or handle in seen:
            continue
        seen.add(handle)
        rows.append(LeadRow(
            username=handle,
            profile_url=endpoints.profile_url(handle),
            display_name=(user.get("nickname") or None),
            platform_id=(str(user.get("uid")) if user.get("uid") else None),
            source=source,
        ))
    return rows


def threads_with_replies(payload: dict[str, Any]) -> list[tuple[str, int]]:
    """(comment id, reply count) for comments that advertise replies.

    The root list will never return these people, so a read that stops at
    the root list has found a fraction of the post and cannot tell.
    """
    out: list[tuple[str, int]] = []
    for comment in payload.get("comments") or []:
        count = int(comment.get("reply_comment_total") or 0)
        cid = comment.get("cid")
        if count > 0 and cid:
            out.append((str(cid), count))
    return out


def page_state(payload: dict[str, Any]) -> dict[str, Any]:
    """The paging fields, normalised.

    `has_more` arrives as 0/1 rather than a boolean, and `total` counts
    replies and deleted comments the root list will never return — so it is
    carried through as the platform's claim, never as a target to reach.
    """
    return {
        "cursor": payload.get("cursor"),
        "has_more": bool(payload.get("has_more")),
        "claimed_total": payload.get("total"),
        "status_code": payload.get("status_code"),
        "status_msg": payload.get("status_msg"),
    }


def dedupe(rows: Iterable[LeadRow]) -> list[LeadRow]:
    """First occurrence wins, order preserved."""
    seen: set[str] = set()
    out: list[LeadRow] = []
    for row in rows:
        if row.username in seen:
            continue
        seen.add(row.username)
        out.append(row)
    return out
