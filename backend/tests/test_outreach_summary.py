"""The dashboard summary: what each figure covers, and what moves with the window.

The endpoint mixes two scopes on one payload — `daily_sends` and `range`
follow the caller's window, everything else is all-time — and the dashboard
labels each card accordingly. A test that only checked "the numbers are
numbers" would not notice the two drifting apart, which is exactly the bug
this suite exists to catch: a windowed figure sitting under an all-time
label reads as a much larger drop than it is.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

import database as db
from routers import outreach as outreach_router

CURRENT_USER: dict = {}


async def _stub_current_user():
    if not CURRENT_USER:
        raise HTTPException(401, "Not authenticated")
    return dict(CURRENT_USER)


async def _stub_admin_required():
    user = await _stub_current_user()
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@pytest.fixture
async def client(database, user):
    app = FastAPI()
    app.include_router(
        outreach_router.build_router(_stub_current_user, _stub_admin_required)
    )
    CURRENT_USER.clear()
    CURRENT_USER.update(user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    CURRENT_USER.clear()


async def _send(database, campaign_id: int, username: str, *, days_ago: int | None,
                status: str = "sent") -> None:
    """One target in a terminal state, optionally stamped `days_ago` back.

    `days_ago=None` leaves `sent_at` NULL — a real state in the production
    data, where a bulk status change marked targets sent without ever
    recording when.
    """
    from services.outreach import importer

    await importer.import_targets(database, campaign_id, f"username\n{username}\n")
    when = "NULL" if days_ago is None else f"NOW() - INTERVAL '{days_ago} days'"
    await database.session.execute(
        text(f"UPDATE outreach_targets SET status = :s, sent_at = {when} "
             f" WHERE campaign_id = :cid AND username = :u"),
        {"s": status, "cid": campaign_id, "u": username})
    await database.session.commit()


# --- the window -----------------------------------------------------------

async def test_window_is_one_of_the_offered_ranges(client):
    """An unoffered window is refused, not quietly rounded to a nearby one."""
    for days in (7, 14, 30, 90):
        assert (await client.get(f"/api/outreach/summary?days={days}")).status_code == 200
    for days in (0, 1, 13, 60, 365, -7):
        r = await client.get(f"/api/outreach/summary?days={days}")
        assert r.status_code == 400, f"days={days} should be refused, got {r.status_code}"
        assert "7, 14, 30, 90" in r.json()["detail"]


async def test_default_window_is_a_fortnight(client, campaign_factory, database):
    campaign = await campaign_factory()
    await _send(database, campaign["id"], "recent", days_ago=3)
    await _send(database, campaign["id"], "older", days_ago=20)

    body = (await client.get("/api/outreach/summary")).json()
    assert body["range"]["days"] == 14
    assert body["range"]["sent"] == 1, "the 20-day-old send is outside a fortnight"
    assert len(body["daily_sends"]) == 14


async def test_daily_sends_covers_every_day_including_the_silent_ones(
        client, campaign_factory, database):
    """A day with no sends is a zero, not a missing row.

    Grouping alone drops empty days, and the chart plots points by index —
    so a gap in sending came out evenly spaced and read as a smooth
    stretch rather than the hole it was.
    """
    campaign = await campaign_factory()
    await _send(database, campaign["id"], "today_sender", days_ago=0)
    await _send(database, campaign["id"], "sixdays_sender", days_ago=6)

    body = (await client.get("/api/outreach/summary?days=7")).json()
    daily = body["daily_sends"]
    assert len(daily) == 7
    assert [d["date"] for d in daily] == sorted(d["date"] for d in daily)
    assert sum(d["count"] for d in daily) == 2
    assert sum(1 for d in daily if d["count"] == 0) == 5


async def test_the_series_and_the_range_total_always_agree(
        client, campaign_factory, database):
    """Two queries, one answer — the chart's own sum is the headline figure."""
    campaign = await campaign_factory()
    for i, ago in enumerate([0, 0, 2, 5, 9, 12, 25]):
        await _send(database, campaign["id"], f"u{i}", days_ago=ago)

    for days in (7, 14, 30, 90):
        body = (await client.get(f"/api/outreach/summary?days={days}")).json()
        assert sum(d["count"] for d in body["daily_sends"]) == body["range"]["sent"], (
            f"series and range total disagree at days={days}")


async def test_previous_window_matches_the_selected_length(
        client, campaign_factory, database):
    """The comparison is like-for-like: 30 days against the prior 30, not 7."""
    campaign = await campaign_factory()
    # Each cluster sits where only one window's *previous* period can reach
    # it, so a comparison that always looks back a fixed seven days — the
    # shape this replaced — cannot pass by coincidence.
    for i in range(3):
        await _send(database, campaign["id"], f"now{i}", days_ago=2)
    for i in range(5):
        await _send(database, campaign["id"], f"prev{i}", days_ago=10)
    for i in range(2):
        await _send(database, campaign["id"], f"old{i}", days_ago=25)
    for i in range(4):
        await _send(database, campaign["id"], f"ancient{i}", days_ago=45)

    week = (await client.get("/api/outreach/summary?days=7")).json()["range"]
    assert week == {"days": 7, "sent": 3, "prev_sent": 5}

    fortnight = (await client.get("/api/outreach/summary?days=14")).json()["range"]
    assert fortnight["sent"] == 8, "both recent clusters fall inside a fortnight"
    assert fortnight["prev_sent"] == 2, (
        "the prior fortnight is days 15-28 back, which is where the pair sits")

    month = (await client.get("/api/outreach/summary?days=30")).json()["range"]
    assert month["sent"] == 10, "everything but the 45-day-old cluster"
    assert month["prev_sent"] == 4, (
        "the prior 30 days reaches back to day 60 — a fixed 7-day lookback "
        "would stop at day 37 and miss it entirely")


# --- what the window must NOT touch ---------------------------------------

async def test_all_time_figures_ignore_the_window(
        client, campaign_factory, database):
    """The delivery rate, the target counts and the weekday split are all-time.

    Each is labelled as such on the dashboard, so moving the range control
    must not move them — otherwise the label lies at every window but one.
    """
    campaign = await campaign_factory()
    await _send(database, campaign["id"], "recent", days_ago=1)
    await _send(database, campaign["id"], "ancient", days_ago=200)
    await _send(database, campaign["id"], "flop", days_ago=200, status="failed")

    fixed = ("targets", "total_targets", "sent", "attempted",
             "delivery_rate", "weekday_sends")
    first = (await client.get("/api/outreach/summary?days=7")).json()
    for days in (14, 30, 90):
        body = (await client.get(f"/api/outreach/summary?days={days}")).json()
        for key in fixed:
            assert body[key] == first[key], f"{key} moved with the window"

    assert first["sent"] == 2
    assert first["attempted"] == 3
    assert first["delivery_rate"] == round(2 / 3, 4)


async def test_delivery_rate_counts_attempts_not_the_backlog(
        client, campaign_factory, database):
    """Queued and paused targets were never attempted and must not count.

    Dividing by every target would report a campaign that has barely
    started as failing, which is the opposite of what is happening.
    """
    campaign = await campaign_factory()
    await _send(database, campaign["id"], "ok", days_ago=1)
    await _send(database, campaign["id"], "bad", days_ago=1, status="failed")
    await _send(database, campaign["id"], "skip", days_ago=1, status="skipped")
    from services.outreach import importer

    await importer.import_targets(database, campaign["id"], "username\nwaiting\n")

    body = (await client.get("/api/outreach/summary")).json()
    assert body["total_targets"] == 4
    assert body["attempted"] == 3, "the queued target is not an attempt"
    assert body["delivery_rate"] == round(1 / 3, 4)


async def test_untimestamped_sends_count_as_delivered_but_not_on_a_weekday(
        client, campaign_factory, database):
    """A send with no `sent_at` is real but unplaceable in time.

    Production carries 248 of these from a bulk status change. They belong
    in the delivery rate — they were sent — and cannot appear in the
    weekday split or the series, which is why the dashboard states the
    weekday card's own coverage rather than claiming the full total.
    """
    campaign = await campaign_factory()
    await _send(database, campaign["id"], "stamped", days_ago=1)
    await _send(database, campaign["id"], "unstamped", days_ago=None)

    body = (await client.get("/api/outreach/summary")).json()
    assert body["sent"] == 2, "both were sent"
    assert sum(body["weekday_sends"].values()) == 1, "only one can be placed"
    assert body["range"]["sent"] == 1, "and only one can sit on the series"


# --- scoping --------------------------------------------------------------

async def test_the_window_stays_scoped_to_the_caller(
        client, campaign_factory, database, user):
    """Another user's sends never reach this payload, at any window."""
    from services.auth import hash_password

    mine = await campaign_factory()
    await _send(database, mine["id"], "mine", days_ago=1)

    # `users` outlives the per-test truncation, so reuse the outsider if an
    # earlier test in this session already created them.
    email = "summary-outsider@example.com"
    existing = await db.get_user_by_email(database, email)
    other_id = existing["id"] if existing else await db.create_user(
        database, email, hash_password("x" * 12), "Outsider")
    theirs_id = await db.create_outreach_campaign(
        database, user_id=other_id, name="Theirs",
        message_template="hi", platform="tiktok", status="draft")
    await _send(database, theirs_id, "theirs", days_ago=1)

    body = (await client.get("/api/outreach/summary?days=30")).json()
    assert body["range"]["sent"] == 1
    assert body["sent"] == 1
    assert body["total_targets"] == 1


# --- campaigns by state ---------------------------------------------------

async def test_campaign_states_are_counted_and_missing_means_none(
        client, campaign_factory):
    """The sidebar's Outreach badge is `campaigns.completed`, from here.

    The badge used to show the queue depth, which is a target count and
    moves every time a worker picks a job up. What it says now is how many
    campaigns have finished, so this endpoint has to carry the split — and
    a state nobody is in is simply absent, which the reader must treat as
    zero rather than as "unknown".
    """
    body = (await client.get("/api/outreach/summary")).json()
    assert body["campaigns"] == {}, "no campaigns yet is an empty split"

    await campaign_factory(name="Finished one", status="completed")
    await campaign_factory(name="Finished two", status="completed")
    await campaign_factory(name="Still going", status="running")
    await campaign_factory(name="Not started")  # draft

    body = (await client.get("/api/outreach/summary")).json()
    assert body["campaigns"] == {"completed": 2, "running": 1, "draft": 1}
    assert "stopped" not in body["campaigns"], "a state nobody is in is absent"


async def test_campaign_states_ignore_the_window(client, campaign_factory):
    """Completed is a state, not an event — no window can move the count."""
    await campaign_factory(name="Done", status="completed")
    first = (await client.get("/api/outreach/summary?days=7")).json()["campaigns"]
    for days in (14, 30, 90):
        body = (await client.get(f"/api/outreach/summary?days={days}")).json()
        assert body["campaigns"] == first, f"campaigns moved at days={days}"


async def test_campaign_states_stay_scoped_to_the_caller(
        client, campaign_factory, database):
    """Another user's finished campaigns never reach this badge."""
    from services.auth import hash_password

    await campaign_factory(name="Mine", status="completed")

    email = "campaign-states-outsider@example.com"
    existing = await db.get_user_by_email(database, email)
    other_id = existing["id"] if existing else await db.create_user(
        database, email, hash_password("x" * 12), "Outsider")
    await db.create_outreach_campaign(
        database, user_id=other_id, name="Theirs",
        message_template="hi", platform="tiktok", status="completed")

    body = (await client.get("/api/outreach/summary")).json()
    assert body["campaigns"] == {"completed": 1}, "only the caller's own"
