"""Print diagnostic state for one or more artist variations.

Reports per variation:
  - the OAuth columns (handle / user_id / token-present / expires_at /
    refresh-token-present) for each of the 4 platforms,
  - paused_reason,
  - the last 48 h of clip_posts rows for the variation (status + truncated
    error column),
  - relevant error_logs entries (posting.* / oauth.* / scheduler.*) bounded
    by the artist that owns the listed variations.

Avoids hand-pasted SQL — many terminals / chat clients autolink `t.col`
patterns into Markdown links and corrupt the query.

Usage:
    cd /opt/icreateflow/backend  # or wherever main.py lives
    sudo -u icreateflow ICREATE_DB_DSN="$ICREATE_DB_DSN" \
        python -m scripts.diagnose_variation moonslyrics lancastarmoonnews
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import database as dbmod


PLATFORMS = ("tiktok", "youtube", "instagram", "facebook")


def _b(v) -> str:
    return "yes" if v else "—"


def _fmt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%m-%d %H:%M")
    return str(dt)[:16]


async def main(names: list[str]) -> None:
    if not names:
        print("usage: python -m scripts.diagnose_variation <name> [<name>...]")
        sys.exit(2)

    db = await dbmod.get_db()
    try:
        # Resolve variations by name (case-insensitive).
        placeholders = ",".join("?" for _ in names)
        cur = await db.execute(
            f"SELECT * FROM artist_accounts "
            f"WHERE LOWER(name) IN ({placeholders})",
            tuple(n.lower() for n in names),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            print(f"No variations found with name in {names}")
            return

        artist_ids = {r["artist_id"] for r in rows}
        var_ids = [r["id"] for r in rows]

        for r in rows:
            print("=" * 72)
            print(f"variation: {r['name']!r}  id={r['id']}  artist_id={r['artist_id']}")
            print(f"  paused_reason: {r.get('paused_reason') or '—'}")
            for p in PLATFORMS:
                handle = r.get(f"{p}_handle") or "—"
                uid = r.get(f"{p}_user_id") or "—"
                exp = _fmt(r.get(f"{p}_expires_at"))
                has_tok = bool(r.get(f"{p}_token"))
                has_ref = bool(r.get(f"{p}_refresh_token"))
                print(
                    f"  {p:9} handle={handle!s:24} user_id={uid!s:22} "
                    f"token={_b(has_tok)} refresh={_b(has_ref)} expires={exp}"
                )

        # Recent clip_posts for these variations.
        ph = ",".join("?" for _ in var_ids)
        cur = await db.execute(
            f"SELECT id, artist_account_id, platform, status, scheduled_for, "
            f"posted_at, error FROM clip_posts "
            f"WHERE artist_account_id IN ({ph}) "
            f"AND scheduled_for >= NOW() - INTERVAL '48 hours' "
            f"ORDER BY scheduled_for DESC",
            tuple(var_ids),
        )
        post_rows = [dict(x) for x in await cur.fetchall()]
        var_name = {r["id"]: r["name"] for r in rows}
        print("=" * 72)
        print(f"clip_posts (last 48h) — {len(post_rows)} rows")
        if post_rows:
            print(f"{'post_id':>7}  {'variation':18}  {'platform':10}  "
                  f"{'status':10}  {'sched':12}  {'posted':12}  error")
            for p in post_rows:
                err = (p.get("error") or "").replace("\n", " ")[:200]
                print(
                    f"{p['id']:>7}  {var_name.get(p['artist_account_id'], '?'):18}  "
                    f"{p['platform'] or '-':10}  {p['status'] or '-':10}  "
                    f"{_fmt(p['scheduled_for']):12}  {_fmt(p.get('posted_at')):12}  "
                    f"{err}"
                )

        # error_logs window — broad source filter, scoped to last 48 h. Not
        # filtered by artist id because the source/context fields don't
        # carry it consistently.
        cur = await db.execute(
            "SELECT created_at, source, message, context FROM error_logs "
            "WHERE created_at >= NOW() - INTERVAL '48 hours' "
            "AND (source LIKE 'posting.%' OR source LIKE 'oauth.%' "
            "OR source LIKE 'scheduler.%') "
            "ORDER BY created_at DESC LIMIT 80"
        )
        err_rows = [dict(x) for x in await cur.fetchall()]
        print("=" * 72)
        print(f"error_logs (last 48h, posting/oauth/scheduler) — {len(err_rows)} rows")
        for e in err_rows:
            msg = (e.get("message") or "").replace("\n", " ")[:240]
            ctx = (e.get("context") or "").replace("\n", " ")[:80]
            print(f"  {_fmt(e['created_at'])}  {e['source']:30}  {msg}")
            if ctx:
                print(f"            ctx: {ctx}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
