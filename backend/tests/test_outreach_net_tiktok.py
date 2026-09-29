"""The DOM-less TikTok reader, driven by a stub that behaves like TikTok.

Nothing here contacts TikTok or opens a browser. The stub reproduces the
response shapes recorded from the real endpoint on 2026-09-22, including
the two that a reader gets wrong quietly: an HTTP 200 with an empty body,
and `has_more=0` at the root cap.
"""
from __future__ import annotations

import ast
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from services.outreach.constants import RESULT_EMPTY_RESPONSE, RESULT_SENT
from services.outreach.net.tiktok import comments as reader
from services.outreach.net.tiktok import endpoints

POST = "https://www.tiktok.com/@someone/video/7684154011863371021"

#: Set by each test to script the stub.
SCRIPT: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        cursor = int(query.get("cursor", 0))
        count = int(query.get("count", 20))
        is_reply = "reply" in parsed.path

        SCRIPT.setdefault("seen", []).append((parsed.path, cursor))

        # An empty 200 — the failure this reader exists to notice.
        empties = SCRIPT.get("empty_until", 0)
        if SCRIPT.get("empty_forever") or len(SCRIPT["seen"]) <= empties:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"")
            return

        if is_reply:
            body = {
                "status_code": 0, "total": 2, "has_more": 0,
                "cursor": cursor + count,
                "comments": [_user(f"replier{cursor}a"), _user(f"replier{cursor}b")],
            }
        else:
            cap = SCRIPT.get("root_cap", 60)
            more = 1 if cursor + count < cap else 0
            people = [_user(f"root{cursor + i}") for i in range(3)]
            if SCRIPT.get("with_threads") and cursor == 0:
                people[0]["reply_comment_total"] = 2
                people[0]["cid"] = "c-1"
            body = {
                "status_code": 0, "total": SCRIPT.get("claimed_total", 1637),
                "has_more": more, "cursor": cursor + count, "comments": people,
            }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_a):  # noqa: A003
        return


def _user(handle: str) -> dict:
    return {
        "cid": f"cid-{handle}", "text": "nice",
        "reply_comment_total": 0,
        "user": {"unique_id": handle, "nickname": handle.title(), "uid": f"u-{handle}"},
    }


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); server.server_close()


@pytest.fixture(autouse=True)
def _reset():
    SCRIPT.clear()
    SCRIPT["seen"] = []
    yield


def minter(site: str, count: list | None = None):
    """A `mint` that points the reader at the stub instead of TikTok."""
    async def _mint() -> reader.Minted:
        if count is not None:
            count.append(1)
        return reader.Minted(
            f"{site}/api/comment/list/?aweme_id=1&cursor=0&count=20&X-Gnarly=abc",
            {"user-agent": "test"}, {"sessionid": "x"},
        )
    return _mint


async def _noop(_seconds: float) -> None:
    """No waiting in tests; the pacing is exercised by its own argument."""


async def _run(site, **kw):
    return await reader.read_commenters(
        POST, mint=minter(site), sleep=_noop, **kw)


# --- the ordinary case -----------------------------------------------------

async def test_it_pages_to_the_end_and_says_so(site):
    result = await _run(site, include_replies=False)
    assert result.ok
    assert result.status == RESULT_SENT
    assert result.rows, "no leads collected"
    assert result.complete, "a finished read should report complete"
    assert result.detail["hit_root_cap"] is False
    assert all(r.profile_url.startswith("https://www.tiktok.com/@") for r in result.rows)


async def test_a_person_who_commented_twice_is_one_lead(site):
    result = await _run(site, include_replies=False)
    handles = [r.username for r in result.rows]
    assert len(handles) == len(set(handles))


# --- the empty 200, which is the whole point -------------------------------

async def test_an_empty_200_is_never_reported_as_the_end_of_the_list(site):
    """The measured failure mode: no status code, no error, no body.

    A reader that treats this as "no more comments" reports a partial read
    as a complete one — 619 handles offered as the whole of a
    1,637-comment post, and nothing downstream able to tell.
    """
    SCRIPT["empty_forever"] = True
    result = await _run(site, include_replies=False)
    assert result.ok is False
    assert result.status == RESULT_EMPTY_RESPONSE
    assert result.complete is False
    assert "empty" in (result.error or "").lower()


async def test_an_expired_signature_is_reminted_and_the_read_continues(site):
    """One signature lasts minutes, so a long read mints several."""
    SCRIPT["empty_until"] = 1          # the first request only
    mints: list = []
    result = await reader.read_commenters(
        POST, mint=minter(site, mints), include_replies=False, sleep=_noop)
    assert result.ok, result.error
    assert len(mints) >= 2, "the reader did not mint a fresh signature"
    assert result.rows


async def test_rows_already_read_survive_a_failure(site):
    """A read that dies part-way has still spent the account's budget.

    Throwing the rows away wastes that; throwing the failure away is how a
    partial read gets recorded as a complete one. Both are kept.
    """
    SCRIPT["root_cap"] = 200
    result = await _run(site, include_replies=False, request_budget=4)
    assert result.rows, "rows collected before the budget ran out were lost"
    assert result.complete is False


# --- the cap that looks like an ending --------------------------------------

async def test_the_root_cap_is_not_reported_as_a_complete_read(site):
    """`has_more=0` at cursor 1000 is the platform declining to page.

    It looks exactly like a clean finish. Measured on a post whose stated
    total was 1,637: the root list ended at 1000.
    """
    SCRIPT["root_cap"] = endpoints.COMMENT_ROOT_CAP
    result = await _run(site, include_replies=False, request_budget=500)
    assert result.ok
    assert result.detail["hit_root_cap"] is True
    assert result.complete is False, (
        "a read stopped by the platform cap called itself complete"
    )


# --- reply threads ----------------------------------------------------------

async def test_reply_threads_are_read_too(site):
    """Most of a big post's people are in replies, not the root list."""
    SCRIPT["with_threads"] = True
    without = await _run(site, include_replies=False)
    with_replies = await _run(site, include_replies=True)
    assert len(with_replies.rows) > len(without.rows)
    assert any(r.username.startswith("replier") for r in with_replies.rows)


# --- the budget, which protects the account ---------------------------------

async def test_a_read_cannot_spend_more_than_its_budget(site):
    """~700 requests on one account had it throttled for about a day."""
    SCRIPT["root_cap"] = 10_000
    result = await _run(site, include_replies=False, request_budget=5)
    assert result.detail["requests"] <= 5
    assert result.complete is False


async def test_should_stop_is_honoured(site):
    SCRIPT["root_cap"] = 10_000
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    result = await reader.read_commenters(
        POST, mint=minter(site), should_stop=stop, include_replies=False,
        sleep=_noop)
    assert result.detail["requests"] <= 3


async def test_leads_are_banked_as_they_are_found(site):
    banked: list = []
    await _run(site, include_replies=False, on_found=banked.append)
    assert banked, "on_found was never called"


async def test_excluded_handles_are_not_returned(site):
    first = await _run(site, include_replies=False)
    skip = {first.rows[0].username}
    again = await _run(site, include_replies=False, exclude=skip)
    assert skip.isdisjoint({r.username for r in again.rows})


async def test_a_url_that_is_not_a_post_is_refused(site):
    result = await reader.read_commenters(
        "https://www.tiktok.com/@someone", mint=minter(site), sleep=_noop)
    assert result.ok is False
    assert result.rows == []


# --- the structural rule ----------------------------------------------------

def test_no_platform_folder_imports_another():
    """The rule that keeps `net/` from becoming playwright_base.py.

    A platform folder may import from `net/` root. It may never import from
    a sibling. Enforced here rather than by convention, because convention
    is what produced a shared module with `FOLLOWERS_IN_DIALOG` in it.
    """
    root = Path(__file__).resolve().parents[1] / "services/outreach/net"
    platforms = [d.name for d in root.iterdir()
                 if d.is_dir() and not d.name.startswith("__")]
    offences: list[str] = []
    for platform in platforms:
        siblings = {p for p in platforms if p != platform}
        for module in (root / platform).rglob("*.py"):
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                for name in names:
                    for sibling in siblings:
                        if f"net.{sibling}" in name:
                            offences.append(f"{module.name} imports {name}")
    assert not offences, (
        f"a platform folder imported a sibling: {offences}. Duplication is "
        f"the correct answer here — two cursor loops that are 80% identical "
        f"stay two loops."
    )
