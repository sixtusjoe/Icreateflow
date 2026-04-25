"""One-off: queue Vid5 (clip_id=16) for catch-up posting in 1 min and Vid6
(clip_id=15) for tonight 20:00 Lagos = 19:00 UTC across all 3 Lancastar Moon
variations × all 4 platforms. Bumps times_posted on each clip so the planner
treats them as posted and doesn't redundantly re-pick them on the next tick.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import database as dbmod


ARTIST_ID = 1
CAMPAIGN_ID = 1
PLATFORMS = ("tiktok", "youtube", "instagram", "facebook")


async def main() -> None:
    database = await dbmod.get_db()
    try:
        now = datetime.now(timezone.utc)
        # tonight 19:00 UTC (20:00 Lagos). If we're already past 19:00 today,
        # use tomorrow.
        tonight = now.replace(hour=19, minute=0, second=0, microsecond=0)
        if tonight <= now:
            tonight += timedelta(days=1)
        catchup = now + timedelta(minutes=1)

        slots = [
            (16, catchup),  # Vid5 — clip id 16
            (15, tonight),  # Vid6 — clip id 15
        ]

        variations = await dbmod.get_artist_accounts(database, ARTIST_ID)
        for clip_id, slot in slots:
            clip = await dbmod.get_clip(database, clip_id)
            if not clip:
                print(f"clip {clip_id} not found, skipping")
                continue
            print(f"queueing clip {clip_id} ({dict(clip).get('filename')}) at {slot.isoformat()}")
            for var in variations:
                vd = dict(var)
                for p in PLATFORMS:
                    if not vd.get(f"{p}_token"):
                        continue
                    rid = await dbmod.create_clip_post(
                        database,
                        clip_id=clip_id,
                        artist_account_id=vd["id"],
                        platform=p,
                        scheduled_for=slot.replace(tzinfo=None),
                        status="scheduled",
                        artist_id=ARTIST_ID,
                        campaign_id=CAMPAIGN_ID,
                        clip_filename=dict(clip).get("filename"),
                        caption_snapshot=dict(clip).get("caption"),
                    )
                    print(f"  var {vd['id']} {p}: clip_post id={rid}")
            await dbmod.update_clip(
                database, clip_id,
                times_posted=int(dict(clip).get("times_posted") or 0) + 1,
                last_posted_at=now,
            )
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
