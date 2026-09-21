"""How a list read decides to keep going, and when it banks what it found.

These are the three things last night's discovery work changed and left
uncovered: budgeting by leads *taken* rather than handles *read*, treating
a scroll that yields nobody as a stall worth re-nudging, and writing each
lead the moment it is found instead of at the end of the run.

The reader tests drive `_profile_links` against a scripted page rather
than a browser. That is the honest boundary: the loop is the thing that
was wrong, and a real Chromium would only prove that Playwright scrolls.
`_renudge` is the exception — it is *about* scrolling, so it gets a real
page, and skips when Playwright is not installed.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from services.outreach import discovery
from services.outreach.browser import playwright_base as base
from services.outreach.browser.playwright_instagram import (
    PlaywrightInstagramMessenger,
)

SELECTORS = ("a[href^='/']",)


class _Page:
    """The handful of calls `_profile_links` makes on a page.

    Every wait is a no-op, so a test that spends 160 rounds proving a
    stall is eventually given up on costs nothing to run.
    """

    async def goto(self, *_a, **_k) -> None: ...

    async def wait_for_timeout(self, _ms: int) -> None: ...


class _ScriptedReader(PlaywrightInstagramMessenger):
    """A driver whose page is a script: `(moved, names revealed)` per round.

    Index 0 is what is on screen before any scrolling; each `_load_more`
    advances one step. Past the end of the script the page keeps moving
    but reveals nobody — a list that scrolls for ever and is finished.
    """

    def __init__(self, script, tail_moves: bool = True,
                 renudge_moves: bool = True):
        super().__init__(headless=True)
        self._script = list(script)
        self._tail_moves = tail_moves
        self._at = 0
        self._revealed: list[str] = list(self._script[0][1])
        self.renudges = 0
        self.renudge_moves = renudge_moves

    # The browser preamble, removed.
    async def _dismiss_overlays(self, _page) -> None: ...

    async def _first_visible(self, _page, _selectors, timeout_ms: int = 0):
        return None

    async def _load_more(self, _page) -> bool:
        self._at += 1
        if self._at < len(self._script):
            moved, names = self._script[self._at]
            self._revealed.extend(names)
            return moved
        return self._tail_moves

    async def _collect_profile_links(self, _page, _selectors) -> list[str]:
        return list(self._revealed)

    async def _renudge(self, _page) -> bool:
        self.renudges += 1
        return self.renudge_moves


def _known(*names):
    """An `on_person` that rejects the handles a search already holds."""
    taken: list[str] = []

    async def on_person(username: str):
        if username in names:
            return False
        taken.append(username)

    on_person.taken = taken  # type: ignore[attr-defined]
    return on_person


# --- budgeting by what is taken -------------------------------------------


async def test_a_read_is_budgeted_by_leads_taken_not_handles_read():
    """A post whose audience is already known must not spend the budget.

    The count that ended the read used to be `len(seen)` — everybody whose
    handle was read, including the ones the search already had and threw
    away. On a post harvested before, nearly every handle is one of those,
    so a request for 654 more people read 654 and delivered none of them.
    """
    old = [f"known{i}" for i in range(20)]
    script = [(True, old[:5])]
    script += [(True, [name]) for name in old[5:]]
    script += [(True, [f"fresh{i}"]) for i in range(3)]
    reader = _ScriptedReader(script)
    on_person = _known(*old)

    names = await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS,
        scroll_rounds=2, want=3, on_person=on_person,
    )

    assert on_person.taken == ["fresh0", "fresh1", "fresh2"]
    # And it got there by reading far more than three handles.
    assert len(names) > 3, names


async def test_running_out_of_rounds_cannot_end_a_read_that_is_still_short():
    """The round budget is a guess; being short of leads is a fact.

    `scroll_rounds` is how much scrolling a target was guessed to be
    worth, and it was wrong in the only direction that matters: a request
    for 654 ended at 39 because the wheel ran out of turns, not because
    the post ran out of comments.
    """
    script = [(True, [])]
    script += [(True, []) for _ in range(30)]
    script += [(True, [f"late{i}"]) for i in range(4)]
    reader = _ScriptedReader(script)
    on_person = _known()

    await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS,
        scroll_rounds=3, want=4, on_person=on_person,
    )

    assert on_person.taken == ["late0", "late1", "late2", "late3"]


async def test_the_round_budget_still_ends_a_read_that_is_not_short():
    """It is only the *hungry* case that overrides the budget.

    A read with no target, or one already satisfied, must still stop when
    its rounds are spent rather than scrolling to the silence backstop.
    """
    reader = _ScriptedReader([(True, ["a"])], tail_moves=True)

    await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS, scroll_rounds=5,
    )

    assert reader._at == 5, f"stopped after {reader._at} rounds, not 5"


# --- a scroll that yields nobody ------------------------------------------


async def test_endless_scrolling_that_yields_nobody_counts_as_a_stall():
    """Movement was made to excuse a quiet round; it cannot excuse forever.

    A comment list is 3,000px deep and the trip down it is silent, so a
    round that scrolled without producing a name is not evidence the list
    has ended. But a page that scrolls for ever and yields nobody *is*
    finished, and before this the read spun all the way to the silence
    backstop: 75 rounds after the 129th handle, all moving, none new.
    """
    reader = _ScriptedReader([(True, ["a", "b"])], tail_moves=True)
    on_person = _known()

    await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS,
        scroll_rounds=5, want=500, on_person=on_person,
    )

    # It gave up, rather than running until the clock stopped it...
    assert reader.renudges == base.LIST_RENUDGES
    # ...and it asked the page again before each time it considered doing so.
    assert reader._at < base.LIST_DRY_ROUNDS * (base.LIST_RENUDGES + 2)


async def test_a_list_that_will_not_move_is_the_one_reason_to_stop_short():
    """A re-nudge that cannot shift the page means the list is truly static.

    That is the honest end of a read that is still short of what it was
    asked for — and it must be reached at once, not after three tries that
    each cost a second or two.
    """
    reader = _ScriptedReader([(True, ["a"])], tail_moves=False,
                             renudge_moves=False)
    on_person = _known()

    await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS,
        scroll_rounds=5, want=500, on_person=on_person,
    )

    assert reader.renudges == 1


async def test_a_read_says_what_it_is_doing_when_none_of_it_counts(capsys):
    """Zero leads and no output is indistinguishable from a hung browser.

    On a post whose audience is already known the first new name can be
    hundreds of handles down, so the heartbeat reports handles read as
    well as leads taken.
    """
    reader = _ScriptedReader([(True, ["a"])], tail_moves=True)
    on_person = _known("a")

    await reader._profile_links(
        _Page(), "https://example.test/p/1", SELECTORS,
        scroll_rounds=base.LIST_HEARTBEAT_ROUNDS + 1,
        want=None, on_person=on_person,
    )

    beats = [ln for ln in capsys.readouterr().out.splitlines()
             if "handle(s) read" in ln]
    assert beats, "a long read produced no heartbeat at all"
    assert f"round {base.LIST_HEARTBEAT_ROUNDS}" in beats[0], beats[0]


# --- re-nudging a real page -----------------------------------------------


async def test_renudge_moves_a_scrollable_page_and_reports_a_static_one():
    """The one part of this that is genuinely about a browser.

    These lists fetch when a sentinel near the bottom enters view; parked
    at the bottom it is already visible, so nothing fires again and the
    list looks finished when it is only waiting to be asked. Moving away
    and back asks again — but only if the page can move at all, and
    `_renudge` swallows every exception, so a method that was quietly
    failing would look exactly like a static page.
    """
    pytest.importorskip("playwright.async_api",
                        reason="playwright is not installed")
    tall = "<body style='margin:0'>" + "".join(
        f"<p style='height:40px'>row {i}</p>" for i in range(400)) + "</body>"
    flat = "<body style='margin:0'><p>one short line</p></body>"

    driver = PlaywrightInstagramMessenger(headless=True)
    await driver.startup()
    try:
        page = await (await driver._browser.new_context()).new_page()
        await page.set_content(tall)
        await page.mouse.move(200, 200)
        await page.mouse.wheel(0, 4000)
        await page.wait_for_timeout(300)
        assert await driver._scroll_position(page) > 0, "nothing scrolled"
        assert await driver._renudge(page) is True

        await page.set_content(flat)
        await page.wait_for_timeout(300)
        assert await driver._renudge(page) is False
    finally:
        try:
            await driver.shutdown()
        except Exception:  # noqa: BLE001 — teardown, not the assertion
            pass


# --- banking a lead the moment it is found --------------------------------


async def _search(database, user) -> int:
    search_id = (await database.session.execute(text(
        "INSERT INTO outreach_lead_searches "
        "  (user_id, campaign_id, platform, niche, wanted, status) "
        "VALUES (:uid, NULL, 'instagram', 'reader tests', 5, 'running') "
        "RETURNING id"), {"uid": user["id"]})).scalar_one()
    await database.session.commit()
    return int(search_id)


BARE = {"username": "probe", "profile_url": "https://example.test/probe",
        "source": "post:probe"}
SCORED = dict(BARE, display_name="Probe", bio="skater, NYC",
              followers=1234, score=87, reason="matches the niche")


async def _row(database, search_id: int):
    return (await database.session.execute(text(
        "SELECT display_name, bio, followers, score, reason "
        "  FROM outreach_leads WHERE search_id=:s AND username='probe'"),
        {"s": search_id})).first()


async def test_a_lead_is_banked_the_moment_it_is_found(database, user):
    """A run killed part-way must keep its work.

    The driver hands people over as it reads them precisely so a long run
    could survive being stopped — and then every one of them sat in a list
    until the read finished, so a run killed at ninety minutes stored
    nothing at all. A read of one post takes hours; it cannot be
    all-or-nothing.

    `_store_lead_now` opens its own connection, so this also proves the
    write is committed and visible from another one.
    """
    search_id = await _search(database, user)

    await discovery._store_lead_now(search_id, user["id"], "instagram", BARE)

    row = await _row(database, search_id)
    assert row is not None, "the lead was not written when it was found"


async def test_the_end_of_run_sweep_fills_in_what_the_live_write_could_not(
        database, user):
    """The second write has to be an update, not a no-op.

    The live write banks a bare row — a username and a URL are all the
    reader knows. Bio, follower count, score and reason arrive later, from
    the profile read and the scorer. `DO NOTHING` kept the bare row and
    silently threw all of that away.
    """
    search_id = await _search(database, user)

    await discovery._store_lead_now(search_id, user["id"], "instagram", BARE)
    await discovery._store_leads(database, search_id, user["id"],
                                 "instagram", [SCORED])

    name, bio, followers, score, reason = await _row(database, search_id)
    assert (bio, followers, score, reason) == (
        "skater, NYC", 1234, 87, "matches the niche")
    assert name == "Probe"


async def test_a_later_write_that_knows_less_never_blanks_what_is_there(
        database, user):
    """It fills rather than replaces.

    Otherwise a sweep over a lead whose profile could not be read would
    wipe the score and bio that an earlier pass had already earned.
    """
    search_id = await _search(database, user)
    await discovery._store_leads(database, search_id, user["id"],
                                 "instagram", [SCORED])

    await discovery._store_leads(database, search_id, user["id"],
                                 "instagram", [BARE])

    name, bio, followers, score, reason = await _row(database, search_id)
    assert (name, bio, followers, score, reason) == (
        "Probe", "skater, NYC", 1234, 87, "matches the niche")


async def test_storing_the_same_lead_twice_keeps_one_row(database, user):
    """Banking live and sweeping at the end must not double up."""
    search_id = await _search(database, user)

    await discovery._store_lead_now(search_id, user["id"], "instagram", BARE)
    await discovery._store_leads(database, search_id, user["id"],
                                 "instagram", [SCORED])

    count = (await database.session.execute(text(
        "SELECT count(*) FROM outreach_leads WHERE search_id=:s"),
        {"s": search_id})).scalar_one()
    assert count == 1


async def test_a_row_that_will_not_save_does_not_take_the_run_down(
        database, user):
    """Storing is reporting, not the work.

    `_store_lead_now` runs inside the reader's callback, so an exception
    there would kill a discovery run that was otherwise going fine.
    """
    search_id = await _search(database, user)

    await discovery._store_lead_now(
        search_id, user["id"], "instagram",
        {"username": "x" * 5000, "profile_url": None},
    )

    assert await _row(database, search_id) is None
