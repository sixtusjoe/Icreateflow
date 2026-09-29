"""DOM-less readers: the platforms' own JSON endpoints, no page driving.

The same seam as `browser/`: a reader is resolved by name and nothing above
this package knows how it works. The rule that keeps it from becoming
`playwright_base.py` is structural — a platform folder may import from this
root and may **never** import from a sibling, and a test walks the AST of
every module here to enforce it rather than trusting convention.

Duplication is the correct answer inside. If TikTok's and Instagram's
cursor loops end up 80% identical, they stay two loops: the third time a
flag is added to a shared function to make one platform behave differently,
that function has become playwright_base.py again.
"""
from __future__ import annotations

import importlib
from typing import Any

#: platform -> "module:attribute", imported lazily so a host that only
#: sends never needs the reader's dependencies.
READERS: dict[str, str] = {
    "tiktok": "services.outreach.net.tiktok.sign:TikTokSigner",
}


class ReaderUnavailable(RuntimeError):
    """No reader for this platform, or its dependencies are missing."""


def get_signer(platform: str, *args: Any, **kwargs: Any):
    """The signer for one platform, instantiated."""
    path = READERS.get((platform or "").strip().lower())
    if not path:
        raise ReaderUnavailable(
            f"No DOM-less reader for {platform!r}. Available: "
            f"{', '.join(sorted(READERS))}"
        )
    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ReaderUnavailable(
            f"The {platform} reader is registered but its dependencies are "
            f"not installed: {exc}"
        ) from exc
    return getattr(module, attr)(*args, **kwargs)
