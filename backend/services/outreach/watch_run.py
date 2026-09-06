"""Run one job in a browser window a person can watch — and intervene in.

The driver already knows how to wait: when a verification puzzle appears it
holds the page open for several minutes rather than failing, because only a
person can clear one. That is useless without a window to clear it in, and
until now the only way to get a window was an SSH session, a VNC tunnel and
a shell script.

This is the same run, started from the campaign page. One job, a visible
browser, and the operator watching it click through — which is also the
only way to find out what a selector is really doing on a live page.

It runs on whatever machine hosts the backend, so it is gated the same way
browser sign-in is; see `local_browser`.
"""
from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import database as db
from services.outreach import config as cfg
from services.outreach import local_browser
from services.outreach.browser import DriverUnavailable, get_driver

STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"


@dataclass
class Watch:
    """One watched run, as the campaign page needs to see it."""

    campaign_id: int
    platform: str
    status: str = STATUS_STARTING
    message: str = "Opening a browser window…"
    #: Whether a job was actually claimed. A watch that finds nothing queued
    #: is not a failure, but the operator has to be told, or they are left
    #: staring at a window that closed for no visible reason.
    did_work: bool = False
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = None

    @property
    def done(self) -> bool:
        return self.status in (STATUS_FINISHED, STATUS_FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "platform": self.platform,
            "status": self.status,
            "message": self.message,
            "did_work": self.did_work,
            "done": self.done,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


#: In flight and recently finished, by campaign. In memory on purpose: a
#: watched run cannot outlive the process whose window it opened.
_WATCHES: dict[int, Watch] = {}
_TASKS: dict[int, asyncio.Task] = {}


def unavailable_reason() -> Optional[str]:
    return local_browser.unavailable_reason("Watching a send")


def status_for(campaign_id: int) -> Optional[Watch]:
    return _WATCHES.get(int(campaign_id))


def is_running(campaign_id: int) -> bool:
    task = _TASKS.get(int(campaign_id))
    return task is not None and not task.done()


def any_running() -> bool:
    """Is a watched run open anywhere?

    Two visible browsers driving the same account would fight over its
    session, so only one runs at a time regardless of campaign.
    """
    return any(t is not None and not t.done() for t in _TASKS.values())


def start(campaign: dict[str, Any]) -> Watch:
    """Open a window and run one job. Returns immediately.

    Raises ValueError when something is already sending — see `any_running`
    and the local sender. Two claimants would race each other for jobs and
    for the same account's lease.
    """
    from services.outreach.runner import local_worker_running

    campaign_id = int(campaign["id"])
    platform = (campaign.get("platform") or "").strip().lower()
    if local_worker_running():
        raise ValueError(
            "Sending is already running on this machine, in a visible "
            "browser — watch that window rather than starting a second one."
        )
    if any_running():
        raise ValueError(
            "A watched run is already open. Finish or close that window first."
        )

    watch = Watch(campaign_id=campaign_id, platform=platform)
    _WATCHES[campaign_id] = watch
    _TASKS[campaign_id] = asyncio.create_task(_run(campaign, watch))
    return watch


async def _run(campaign: dict[str, Any], watch: Watch) -> None:
    from services.outreach.runner import PLATFORM_DRIVERS, OutreachWorker

    def finish(status: str, message: str, did_work: bool = False) -> None:
        watch.status = status
        watch.message = message
        watch.did_work = did_work
        watch.finished_at = datetime.now(timezone.utc).isoformat()

    driver_name = PLATFORM_DRIVERS.get(watch.platform)
    if not driver_name:
        finish(STATUS_FAILED, f"No driver for platform {watch.platform!r}.")
        return

    worker = None
    try:
        # Headful for this run only. Setting the environment variable would
        # follow every other worker in this process, which is not what
        # "watch this one" means.
        driver = get_driver(driver_name, headless=False)
        # Passing the driver pins it, which is right here: this run is for
        # one campaign, on one platform, in one window.
        worker = OutreachWorker(once=True, driver=driver)

        database = await db.get_db()
        try:
            settings = await cfg.get_all(database)
        finally:
            await database.close()

        watch.status = STATUS_RUNNING
        watch.message = (
            "A browser window is open. Watch it work — if a verification "
            "puzzle appears, solve it there and the send continues by itself."
        )

        did_work = await worker.process_one(settings)
    except DriverUnavailable as exc:
        finish(STATUS_FAILED, str(exc)[:300])
        return
    except asyncio.CancelledError:
        finish(STATUS_FAILED, "The watched run was cancelled.")
        raise
    except Exception as exc:  # noqa: BLE001 — the page has to hear about it
        traceback.print_exc()
        finish(STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:300])
        return
    finally:
        if worker is not None:
            try:
                await worker.shutdown()
            except Exception:  # noqa: BLE001 — shutdown must not raise
                traceback.print_exc()

    if did_work:
        finish(
            STATUS_FINISHED,
            "The job finished — its result is on this page. The window "
            "closing is the end of the run, not an error.",
            did_work=True,
        )
    else:
        finish(
            STATUS_FINISHED,
            "Nothing was queued to run. Check the campaign is running, has "
            "queued targets, and that its account is not paused.",
            did_work=False,
        )
