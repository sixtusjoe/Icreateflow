#!/usr/bin/env python3
"""Run an outreach browser worker.

    cd backend
    python3 scripts/outreach_worker.py                  # driver from site_config
    python3 scripts/outreach_worker.py --driver mock    # dry run, sends nothing
    python3 scripts/outreach_worker.py --concurrency 3
    python3 scripts/outreach_worker.py --once           # one job, then exit

Run as many processes as you like — job claims and account leases are
taken in Postgres, so workers never collide. Ctrl-C (or SIGTERM from
systemd) stops the loop cleanly; any job still in flight keeps its lease
and is requeued by the reaper.

Needs the same environment as the API: `ICREATE_DB_DSN`, plus
`ICREATE_OUTREACH_SECRET` (or `ICREATE_JWT_SECRET`) to decrypt stored
sending-account sessions.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

# Allow `python3 scripts/outreach_worker.py` from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.outreach.runner import OutreachWorker, default_worker_id  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ICREATEFLOW outreach worker")
    parser.add_argument(
        "--driver",
        help="Automation driver to use (mock, playwright_tiktok). "
             "Defaults to the outreach_driver site_config value.",
    )
    parser.add_argument(
        "--concurrency", type=int,
        help="Jobs processed in parallel. Defaults to outreach_worker_concurrency.",
    )
    parser.add_argument("--worker-id", help="Identifier stamped on claimed jobs.")
    parser.add_argument(
        "--once", action="store_true", help="Process one job and exit (smoke test)."
    )
    return parser.parse_args(argv)


async def main_async(args) -> int:
    worker = OutreachWorker(
        worker_id=args.worker_id or default_worker_id(),
        driver_name=args.driver,
        concurrency=args.concurrency,
        once=args.once,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:  # pragma: no cover — non-POSIX
            pass

    print(f"[outreach] worker {worker.worker_id} starting", flush=True)
    try:
        await worker.run()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        await worker.shutdown()
    print(f"[outreach] worker {worker.worker_id} stopped", flush=True)
    return 0


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
