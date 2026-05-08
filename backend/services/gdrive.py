"""Google Drive folder mirror via server-side API key.

We don't need per-user OAuth for v1 — the folders the user pastes must be
publicly shared ("Anyone with the link"), and we list/download via a single
admin-owned API key stored in the `settings` table as `google_api_key`.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

import httpx


class GDriveError(Exception):
    """Raised when the Drive service fails (bad key, folder not public, etc.)."""


def parse_folder_id(url: str) -> str | None:
    """Extract a Drive folder id from common URL shapes."""
    if not url:
        return None
    url = url.strip()
    # /drive/folders/{id}
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    # ?id=...
    try:
        q = parse_qs(urlparse(url).query)
        if "id" in q and q["id"]:
            return q["id"][0]
    except Exception:
        pass
    # Bare id (looks like a Drive id)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", url):
        return url
    return None


def direct_download_url(file_id: str) -> str:
    """Public direct-download URL for a GDrive file.

    Uses drive.usercontent.google.com with confirm=t to bypass Google's
    large-file virus-scan warning page (which returns ~2,420 bytes of HTML
    instead of the video when using the legacy /uc?export=download URL).
    """
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


async def list_video_files(folder_id: str, api_key: str) -> list[dict]:
    """List video/* files in a public Drive folder. Returns [{id, name, mimeType, size}]."""
    if not folder_id:
        raise GDriveError("Missing folder id")
    if not api_key:
        raise GDriveError("Google API key not configured — set it in Settings")

    params = {
        "q": f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false",
        "key": api_key,
        "fields": "files(id,name,mimeType,size)",
        "pageSize": "1000",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://www.googleapis.com/drive/v3/files", params=params)
        if r.status_code == 403:
            raise GDriveError("Drive API denied the request — check the key or folder sharing")
        if r.status_code == 404:
            raise GDriveError("Drive folder not found — make sure the link is public")
        if r.status_code >= 400:
            raise GDriveError(f"Drive API error {r.status_code}: {r.text[:200]}")
        data = r.json()
    return data.get("files", [])
