"""Searches the phone app runs inside the TikTok app.

The phone reads; the server keeps the books — the row, who is new, when to
stop. These drive the three endpoints the phone calls, the way it calls
them, and check the ordinary review endpoint sees the result.
"""
from __future__ import annotations

import pytest

from tests.test_outreach_api import client, _as  # noqa: F401 — the fixture

VIDEO = "https://www.tiktok.com/@someone/video/7684154011863371021"


async def _campaign(client, platform="tiktok"):
    res = await client.post("/api/outreach/campaigns", json={
        "name": "Phone finds", "platform": platform, "activity": "follow",
    })
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _start(client, cid, wanted=3):
    res = await client.post(f"/api/outreach/campaigns/{cid}/leads/phone-search",
                            json={"videos": f"{VIDEO}\nnot a link", "wanted": wanted})
    assert res.status_code == 200, res.text
    return res.json()


async def _report(client, sid, *names, message=None):
    res = await client.post(f"/api/outreach/leads/searches/{sid}/phone-leads", json={
        "leads": [{"username": n, "display_name": n.title(), "followers": 12, "source": VIDEO} for n in names],
        "message": message,
    })
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_phone_search_starts_running_with_only_the_video_links(client):
    started = await _start(client, await _campaign(client))
    assert started["status"] == "running" and started["done"] is False
    assert started["videos"] == [VIDEO]
    status = (await client.get(f"/api/outreach/leads/searches/{started['search_id']}")).json()
    assert status["search"]["status"] == "running"
    assert status["run"] is None  # nothing on the server is running it


async def test_it_needs_a_tiktok_link_and_a_tiktok_campaign(client):
    cid = await _campaign(client)
    res = await client.post(f"/api/outreach/campaigns/{cid}/leads/phone-search", json={"videos": "hello"})
    assert res.status_code == 400
    ig = await _campaign(client, platform="instagram")
    res = await client.post(f"/api/outreach/campaigns/{ig}/leads/phone-search", json={"videos": VIDEO})
    assert res.status_code == 400


async def test_leads_are_banked_and_only_new_people_count(client):
    sid = (await _start(client, await _campaign(client), wanted=3))["search_id"]
    first = await _report(client, sid, "amy", "ben", message="Reading comments")
    assert first == {"taken": ["amy", "ben"], "found": 2, "stop": False}
    # ben again (commented twice), and Amy in another case: not new.
    again = await _report(client, sid, "ben", "AMY", "cal")
    assert again["taken"] == ["cal"] and again["found"] == 3
    assert again["stop"] is True  # three wanted, three found

    leads = (await client.get(f"/api/outreach/leads/searches/{sid}/leads")).json()
    assert sorted(lead["username"] for lead in leads) == ["amy", "ben", "cal"]
    assert leads[0]["profile_url"].startswith("https://www.tiktok.com/@")
    assert leads[0]["followers"] == 12 and leads[0]["source"] == VIDEO
    status = (await client.get(f"/api/outreach/leads/searches/{sid}")).json()["search"]
    assert status["found"] == 3 and status["message"] == "Reading comments"


async def test_people_found_by_an_earlier_search_are_not_new(client):
    cid = await _campaign(client)
    old = (await _start(client, cid))["search_id"]
    await _report(client, old, "amy")
    new = (await _start(client, cid))["search_id"]
    assert (await _report(client, new, "amy", "dee"))["taken"] == ["dee"]


async def test_stop_tells_the_phone_and_takes_nothing_more(client):
    sid = (await _start(client, await _campaign(client), wanted=50))["search_id"]
    await _report(client, sid, "amy")
    assert (await client.post(f"/api/outreach/leads/searches/{sid}/cancel")).status_code == 200
    after = await _report(client, sid, "ben")
    assert after["stop"] is True and after["taken"] == []
    # The phone's finish doesn't overwrite the Stop.
    await client.post(f"/api/outreach/leads/searches/{sid}/phone-finish", json={"status": "done", "message": "x"})
    status = (await client.get(f"/api/outreach/leads/searches/{sid}")).json()["search"]
    assert status["status"] == "cancelled"


async def test_finish_closes_the_search_with_the_phones_words(client):
    sid = (await _start(client, await _campaign(client)))["search_id"]
    await _report(client, sid, "amy")
    res = await client.post(f"/api/outreach/leads/searches/{sid}/phone-finish",
                            json={"status": "done", "message": "Read every comment — 1 new profile"})
    assert res.status_code == 200
    status = (await client.get(f"/api/outreach/leads/searches/{sid}")).json()["search"]
    assert status["status"] == "done" and status["message"].startswith("Read every comment")
    assert status["finished_at"]


async def test_another_user_cannot_report_into_your_search(client, database):
    sid = (await _start(client, await _campaign(client)))["search_id"]
    from services.auth import hash_password
    import database as db
    other = await db.create_user(database, "someone-else@example.com", hash_password("y" * 12), "Other")
    _as(dict(await db.get_user(database, other)))
    res = await client.post(f"/api/outreach/leads/searches/{sid}/phone-leads",
                            json={"leads": [{"username": "amy"}]})
    assert res.status_code == 404
