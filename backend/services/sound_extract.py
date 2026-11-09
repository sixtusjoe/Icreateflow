"""Pull the sound out of a social post link and save it as an MP3.

TikTok: the post page names its sound and gives the sound's own audio file,
so we take that (it's the clean track, the same for every post using it,
and it works for slideshows, which have no video to rip). Everything else,
and TikTok when the page doesn't give the sound, goes through yt-dlp's
best audio stream. Either way ffmpeg turns the result into an MP3.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Only post links from these sites. yt-dlp fetches whatever it is given, so
# an open list would let anyone make the server request internal addresses.
ALLOWED_HOSTS = (
    "tiktok.com", "instagram.com", "youtube.com", "youtu.be",
    "facebook.com", "fb.watch", "x.com", "twitter.com",
)
MAX_SECONDS = 15 * 60
MAX_BYTES = 60 * 1024 * 1024

_BROWSER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class SoundError(Exception):
    """A reason the sound couldn't be taken, worded for the person."""


def check_link(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not any(
        host == h or host.endswith("." + h) for h in ALLOWED_HOSTS
    ):
        raise SoundError("Paste a TikTok, Instagram, YouTube, Facebook or X post link.")
    return url


def _is_tiktok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "tiktok.com" or host.endswith(".tiktok.com")


async def _tiktok_sound(url: str) -> dict | None:
    """The sound's title, author and audio address from the post page."""
    from services.tiktok_scraper import _extract_from_sigi_state, _extract_from_universal_data

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=20,
        headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
    ) as client:
        resp = await client.get(url)
        if not _is_tiktok(str(resp.url)):
            return None
        html = resp.text
    for script_id, parse in (
        ("__UNIVERSAL_DATA_FOR_REHYDRATION__", _extract_from_universal_data),
        ("SIGI_STATE", _extract_from_sigi_state),
    ):
        m = re.search(rf'<script\s+id="{script_id}"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            continue
        try:
            _, _, sound_id, title, author, play_url = parse(json.loads(m.group(1)))
        except (ValueError, KeyError, AttributeError):
            continue
        if play_url:
            return {"title": title, "author": author, "play_url": play_url, "sound_id": sound_id}
    return None


async def _download(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=60,
        headers={"User-Agent": _BROWSER_UA, "Referer": "https://www.tiktok.com/"},
    ) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise SoundError(f"TikTok wouldn't hand over the sound (status {resp.status_code}).")
            size = 0
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise SoundError("That sound is too large.")
                    f.write(chunk)


def _ytdlp_audio(url: str, workdir: Path) -> tuple[Path, dict]:
    import yt_dlp

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "src.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": MAX_BYTES,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
            if (info.get("duration") or 0) > MAX_SECONDS:
                raise SoundError("That post is longer than 15 minutes, too long for a backing track.")
            info = ydl.extract_info(url, download=True) or {}
    except SoundError:
        raise
    except Exception as e:  # yt-dlp raises many kinds; all mean "couldn't get it"
        msg = str(e)
        logger.warning("sound_extract: yt-dlp failed for %s: %s", url, msg)
        if "login" in msg.lower() or "cookies" in msg.lower() or "rate" in msg.lower():
            raise SoundError("That site wants a signed-in visitor for this post, so the sound couldn't be taken.")
        raise SoundError("Couldn't read a sound from that link. Check the post is public.")
    files = [p for p in workdir.glob("src.*") if p.is_file()]
    if not files:
        raise SoundError("That post has no sound to take, or it's too long.")
    return files[0], info


def _to_mp3(src: Path, dest: Path) -> float:
    run = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-t", str(MAX_SECONDS),
         "-c:a", "libmp3lame", "-b:a", "192k", str(dest)],
        capture_output=True, text=True, timeout=300,
    )
    if run.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        logger.warning("sound_extract: ffmpeg failed: %s", run.stderr[-500:])
        raise SoundError("The link had no usable sound.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return round(float(probe.stdout.strip()), 3)
    except ValueError:
        return 0.0


async def extract_sound(url: str, out_dir: Path, name: str | None = None) -> dict:
    """Save the post's sound into out_dir. Returns name, file_path, duration."""
    url = check_link(url)
    if shutil.which("ffmpeg") is None:
        raise SoundError("The server can't convert audio right now.")
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sound-") as tmp:
        work = Path(tmp)
        src: Path | None = None
        title = None
        if _is_tiktok(url):
            try:
                found = await _tiktok_sound(url)
            except httpx.HTTPError as e:
                logger.warning("sound_extract: TikTok page fetch failed: %s", e)
                found = None
            if found:
                src = work / "src.audio"
                await _download(found["play_url"], src)
                title = " - ".join(x for x in (found["title"], found["author"]) if x)
        if src is None:
            src, info = await asyncio.to_thread(_ytdlp_audio, url, work)
            title = info.get("track") or info.get("title") or ""
            artist = info.get("artist") or info.get("uploader")
            if artist and artist not in title:
                title = f"{title} - {artist}" if title else artist

        label = (name or "").strip() or (title or "").strip() or "Sound from link"
        label = label[:120]
        stem = "".join(c for c in label if c.isalnum() or c in "._- ").strip() or "sound"
        dest = out_dir / f"{stem}.mp3"
        n = 2
        while dest.exists():
            dest = out_dir / f"{stem} ({n}).mp3"
            n += 1
        mp3 = work / "out.mp3"
        duration = await asyncio.to_thread(_to_mp3, src, mp3)
        shutil.move(str(mp3), dest)

    return {"name": label, "file_path": str(dest), "duration": duration}
