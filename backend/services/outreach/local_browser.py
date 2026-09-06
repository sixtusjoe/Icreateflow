"""Whether this host may open a browser window someone can look at.

Two features need it: signing an account in by hand, and watching a send
happen. Both only make sense where a person is sitting in front of the
machine — a laptop running the backend locally. On a headless server there
is nothing to display, and an endpoint that opens browsers on a production
host is a capability worth withholding rather than merely documenting.

So both are off unless the flag is set, and the API says so plainly instead
of failing in some obscure way further down.
"""
from __future__ import annotations

import os
from typing import Optional

#: The canonical flag. `ICREATE_OUTREACH_BROWSER_LOGIN` is still honoured —
#: it was the name when sign-in was the only feature that needed this, and
#: an existing local setup should not stop working over a rename.
FLAG = "ICREATE_OUTREACH_LOCAL_BROWSER"
LEGACY_FLAG = "ICREATE_OUTREACH_BROWSER_LOGIN"

_OFF = ("", "0", "false", "no", "off")


def is_enabled() -> bool:
    for name in (FLAG, LEGACY_FLAG):
        if (os.environ.get(name) or "").strip().lower() not in _OFF:
            return True
    return False


def unavailable_reason(what: str) -> Optional[str]:
    """Why `what` cannot be offered here, or None if it can.

    `what` is a short phrase for the message — "Browser sign-in", "Watching
    a send" — so the operator is told which thing is unavailable.
    """
    if not is_enabled():
        return (
            f"{what} is switched off on this host. It opens a real browser "
            f"window, so it is only enabled where someone can see it — set "
            f"{FLAG}=1 when running the app locally."
        )
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return f"{what} needs Playwright, which is not installed on this host."
    return None
