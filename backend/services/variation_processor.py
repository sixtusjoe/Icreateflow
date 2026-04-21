"""Per-variation clip diversification for clipping only.

Each (clip, variation, platform) tuple gets its own deterministically-seeded
FFmpeg pass so platforms see a distinct perceptual hash, audio fingerprint,
bitrate, and metadata — while humans see/hear the same clip.

The brands/Post Now pipeline DOES NOT call this. Clipping only.

Output is cached at `uploads/variation_renders/{clip_id}/v{variation_id}_{platform}.mp4`.
Same seed → same file → re-running the dispatcher is a no-op.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx


CACHE_ROOT = Path("uploads/variation_renders")


def _seed(clip_id: int, variation_id: int, platform: str) -> int:
    h = hashlib.sha256(f"{clip_id}:{variation_id}:{platform}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def output_path(clip_id: int, variation_id: int, platform: str) -> Path:
    return CACHE_ROOT / str(clip_id) / f"v{variation_id}_{platform}.mp4"


def _check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def _probe_audio_sample_rate(path: Path) -> int:
    """Return the input audio sample rate (Hz). Defaults to 48000 if unknown."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "default=nk=1:nw=1",
        str(path),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        rate = int((out or b"").decode().strip() or 0)
        return rate if rate > 0 else 48000
    except Exception:
        return 48000


async def _download_to_temp(url: str) -> Path:
    """Fetch a remote clip (e.g. Google Drive direct-download) to a local temp file."""
    tmp = Path(tempfile.mkstemp(suffix=".mp4")[1])
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes(1024 * 256):
                    f.write(chunk)
    return tmp


def _build_filters(rng: random.Random, audio_rate: int) -> tuple[str, str, int]:
    """Return (video_filter, audio_filter, crf) for one variant.

    `audio_rate` is the input stream's sample rate; asetrate must be anchored
    to that rate or pitch drifts audibly.
    """
    # Video: symmetric crop 1–3% then scale back to original dims. Imperceptible
    # to a human, completely breaks frame-level pHash/dHash.
    crop_pct = rng.uniform(0.97, 0.99)

    # Subtle color jitter
    brightness = rng.uniform(-0.03, 0.03)
    saturation = rng.uniform(0.97, 1.03)
    contrast = rng.uniform(0.98, 1.02)
    hue = rng.uniform(-2.0, 2.0)

    # Very low-amplitude noise. noise=alls must be an integer.
    noise = rng.randint(3, 7)

    # Force even output dimensions — libx264/yuv420p requires mod-2 width/height.
    vf = (
        f"crop=trunc(iw*{crop_pct:.4f}/2)*2:trunc(ih*{crop_pct:.4f}/2)*2,"
        f"scale=trunc(iw/{crop_pct:.4f}/2)*2:trunc(ih/{crop_pct:.4f}/2)*2,"
        f"eq=brightness={brightness:.4f}:saturation={saturation:.4f}:contrast={contrast:.4f},"
        f"hue=h={hue:.2f},"
        f"noise=alls={noise}:allf=t"
    )

    # Audio: tiny pitch shift (±25 cents = ±0.25 semitones, inaudible) via
    # asetrate then atempo back to near-original speed. This moves the audio
    # fingerprint off the original without sounding chipmunk-ish.
    # Ratio per cent: 2 ** (cents / 1200)
    cents = rng.uniform(-25.0, 25.0)
    pitch_ratio = 2 ** (cents / 1200.0)
    # Extra tempo nudge ±1%
    tempo_nudge = rng.uniform(0.99, 1.01)
    # atempo expects 0.5–2.0. Combined atempo = tempo_nudge / pitch_ratio.
    atempo = tempo_nudge / pitch_ratio
    af = (
        f"asetrate={audio_rate}*{pitch_ratio:.6f},"
        f"aresample={audio_rate},"
        f"atempo={atempo:.6f}"
    )

    crf = rng.randint(22, 26)
    return vf, af, crf


async def diversify(
    source: str,
    clip_id: int,
    variation_id: int,
    platform: str,
) -> Path:
    """Produce (or return cached) a diversified render for (clip, variation, platform).

    `source` is either a local path or an http(s) URL. Returns the local path
    to the rendered MP4, under `uploads/variation_renders/...`.
    """
    if not _check_ffmpeg():
        raise RuntimeError("ffmpeg not installed")

    out = output_path(clip_id, variation_id, platform)
    if out.exists() and out.stat().st_size > 0:
        return out

    out.parent.mkdir(parents=True, exist_ok=True)

    # Resolve source to a local file
    tmp_download: Optional[Path] = None
    if source.startswith(("http://", "https://")):
        tmp_download = await _download_to_temp(source)
        src_path = tmp_download
    else:
        src_path = Path(source)
        if not src_path.exists():
            raise FileNotFoundError(f"Clip source not found: {source}")

    rng = random.Random(_seed(clip_id, variation_id, platform))
    audio_rate = await _probe_audio_sample_rate(src_path)
    vf, af, crf = _build_filters(rng, audio_rate)

    # Randomised creation_time so metadata differs too
    year = rng.randint(2023, 2025)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    hour = rng.randint(0, 23)
    mn = rng.randint(0, 59)
    creation_time = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{mn:02d}:00"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-map_metadata", "-1",
        "-metadata", f"creation_time={creation_time}",
        "-movflags", "+faststart",
        str(out),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Clean partial output so next run retries cleanly
            try:
                out.unlink(missing_ok=True)
            except Exception:
                pass
            tail = (stderr or b"").decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg diversify failed (rc={proc.returncode}): {tail}")
    finally:
        if tmp_download is not None:
            try:
                tmp_download.unlink(missing_ok=True)
            except Exception:
                pass

    return out


def public_url_for(local_path: Path, public_base: str) -> str:
    """Build an externally-reachable URL the platforms can pull from.

    Mirrors the Post Now convention: {public_base}/api/files/{url-encoded-rel-path}.
    """
    from urllib.parse import quote
    rel = str(local_path).lstrip("./")
    enc = "/".join(quote(seg, safe="") for seg in rel.split("/") if seg)
    return f"{public_base.rstrip('/')}/api/files/{enc}"
