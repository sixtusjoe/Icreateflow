"""The image a campaign sends alongside its message.

One image per campaign, stored on disk with only its path in the row. The
file is a few hundred kilobytes and the campaign row is read on every job
claim; keeping bytes out of it costs nothing and saves reading them
thousands of times.

Not every platform can send one. Instagram's composer takes an image;
TikTok's web DMs are text only. That is expressed as a selector each driver
either has or does not, so a platform without one fails with a clear
message instead of quietly sending the text and calling it done — which
would be the same class of lie as reporting a send that never happened.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

#: Where campaign attachments live, relative to the backend working dir.
ATTACHMENT_DIR = Path(os.environ.get("ICREATE_OUTREACH_ATTACHMENT_DIR", "uploads/outreach"))

#: What a DM composer will actually accept.
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

#: Instagram rejects very large images from the web composer, and a big file
#: makes every send slower for no benefit.
MAX_BYTES = 8 * 1024 * 1024


class AttachmentError(ValueError):
    """The upload cannot be used — wrong type, too big, unreadable."""


def extension_for(content_type: Optional[str], filename: Optional[str]) -> str:
    """The extension to store under, or raise if this is not a usable image."""
    suffix = ALLOWED_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if suffix:
        return suffix
    # Some browsers send application/octet-stream for a drag-and-drop; fall
    # back to the name before rejecting something perfectly valid.
    name_suffix = Path(filename or "").suffix.lower()
    if name_suffix in set(ALLOWED_TYPES.values()) or name_suffix == ".jpeg":
        return ".jpg" if name_suffix == ".jpeg" else name_suffix
    raise AttachmentError(
        f"Unsupported image type {content_type or filename or 'unknown'!r}. "
        f"Use JPEG, PNG, GIF or WebP."
    )


def save(owner_id: int, data: bytes, content_type: Optional[str],
         filename: Optional[str], kind: str = "campaign") -> tuple[str, str]:
    """Write the image and return `(path, original name)`.

    The stored name is random: an operator's filename is not something to
    put on disk verbatim, and two campaigns uploading `photo.jpg` must not
    collide.
    """
    if not data:
        raise AttachmentError("The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(
            f"Image is {len(data) // (1024 * 1024)}MB — the limit is "
            f"{MAX_BYTES // (1024 * 1024)}MB."
        )
    suffix = extension_for(content_type, filename)
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    path = ATTACHMENT_DIR / f"{kind}-{int(owner_id)}-{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    return str(path), (filename or path.name)


def remove(path: Optional[str]) -> None:
    """Delete a stored attachment. Missing is not an error."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        # A file we cannot delete is not worth failing a request over; it
        # is orphaned, not dangerous.
        pass


def exists(path: Optional[str]) -> bool:
    return bool(path) and Path(path).is_file()


def copy_for_campaign(source_path: Optional[str], campaign_id: int,
                      name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Give a campaign its own copy of a template's image.

    Copied rather than shared on purpose. If they pointed at one file,
    editing a template — or deleting it — would change or break what a
    campaign already running is sending, without anyone touching that
    campaign.
    """
    if not exists(source_path):
        return None, None
    src = Path(str(source_path))
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    dest = ATTACHMENT_DIR / f"campaign-{int(campaign_id)}-{uuid.uuid4().hex}{src.suffix}"
    dest.write_bytes(src.read_bytes())
    return str(dest), (name or dest.name)
