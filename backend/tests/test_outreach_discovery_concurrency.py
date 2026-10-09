"""Several lead searches at once — never two on one account, never past the cap.

One search used to block every other search on the server, for everyone.
"""
import asyncio

import pytest

from services.outreach import discovery


@pytest.fixture
def held_runs(monkeypatch):
    """Searches that browse until released, so several can be in flight."""
    release = asyncio.Event()

    async def fake_run(search, account, settings, run):
        await release.wait()

    monkeypatch.setattr(discovery, "_run", fake_run)
    monkeypatch.setattr(discovery, "_RUNS", {})
    monkeypatch.setattr(discovery, "_TASKS", {})
    monkeypatch.setattr(discovery, "_ACCOUNT_OF", {})
    yield release
    release.set()


SETTINGS = {"outreach_discovery_max_concurrent": 2}
A = {"id": 1, "name": "Finder A"}
B = {"id": 2, "name": "Finder B"}
C = {"id": 3, "name": "Finder C"}


async def test_two_accounts_search_at_the_same_time(held_runs):
    discovery.start({"id": 10}, A, SETTINGS)
    discovery.start({"id": 11}, B, SETTINGS)
    await asyncio.sleep(0)
    assert discovery.running_count() == 2
    assert discovery.busy_account_ids() == {1, 2}


async def test_one_account_never_runs_two(held_runs):
    discovery.start({"id": 10}, A, SETTINGS)
    with pytest.raises(ValueError, match="Finder A is already running"):
        discovery.start({"id": 11}, A, SETTINGS)
    # Another account is still free to start.
    assert discovery.why_not_now([A, B], SETTINGS) is None
    # With only the busy one, there is nothing to start on.
    assert "Every discovery account" in discovery.why_not_now([A], SETTINGS)


async def test_the_server_cap_holds(held_runs):
    discovery.start({"id": 10}, A, SETTINGS)
    discovery.start({"id": 11}, B, SETTINGS)
    with pytest.raises(ValueError, match="2 searches are already running"):
        discovery.start({"id": 12}, C, SETTINGS)
    assert "already running" in discovery.why_not_now([C], SETTINGS)


async def test_a_finished_search_frees_its_account(held_runs):
    discovery.start({"id": 10}, A, SETTINGS)
    held_runs.set()
    await asyncio.sleep(0.01)
    assert discovery.busy_account_ids() == set()
    discovery.start({"id": 11}, A, SETTINGS)
