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

    # Very subtle color jitter — values tightened so output is visually
    # indistinguishable from the source. The earlier (looser) values plus
    # the noise filter below produced visibly grainy / posterised output
    # on TikTok's player. Crop+scale+seeded metadata changes are plenty to
    # defeat content-id checks; the jitter only needs to nudge.
    brightness = rng.uniform(-0.01, 0.01)
    saturation = rng.uniform(0.99, 1.01)
    contrast = rng.uniform(0.995, 1.005)
    hue = rng.uniform(-0.5, 0.5)

    # NOTE: dropped the `noise=alls=N:allf=t` filter that used to live
    # here. It worked great for breaking pHash but at our CRF (22–26) it
    # made the output look unmistakably grainy on platform players —
    # especially TikTok, which post-encodes our upload at lower bit-rates
    # and amplified the artefacts.

    vf = (
        f"crop=trunc(iw*{crop_pct:.4f}/2)*2:trunc(ih*{crop_pct:.4f}/2)*2,"
        f"scale=trunc(iw/{crop_pct:.4f}/2)*2:trunc(ih/{crop_pct:.4f}/2)*2,"
        f"eq=brightness={brightness:.4f}:saturation={saturation:.4f}:contrast={contrast:.4f},"
        f"hue=h={hue:.2f}"
    )

    # Audio: NO modifications. Earlier we did asetrate * pitch + atempo to
    # nudge the audio fingerprint, but the combination of resampling and
    # tempo correction introduced subtle A/V drift that TikTok's player
    # rendered as 'pausing and playing' (the user's exact words). The
    # video filter alone produces a distinct enough fingerprint for
    # cross-account dedup; nudging audio buys us very little extra at
    # the cost of breaking playback. Pass audio through unchanged with
    # a no-op filter so the af pipeline stays valid.
    af = "anull"

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
        # Sanity check: cached file must look like a complete MP4. ffmpeg
        # finishes by writing the moov atom — `ffprobe -show_format` only
        # succeeds on a fully-finalised file. If the file exists but isn't
        # valid (e.g. left over from a crashed run), nuke it and re-render.
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_format", str(out),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await probe.communicate()
            if probe.returncode == 0:
                return out
        except Exception:
            pass
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass

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

    # Atomic write: ffmpeg streams output to a sibling .partial path, then we
    # rename onto `out` once finished. Without this, a parallel dispatcher tick
    # (different clip_post row, same cache key, e.g. catch-up + slot together)
    # could read `out` while ffmpeg is mid-write — partial MP4 makes TikTok
    # reject as corrupt and YouTube splice in stale atoms (the "image + clip"
    # mash-up the user reported). os.replace is atomic on POSIX.
    import os as _os
    partial = out.with_suffix(out.suffix + ".partial")
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
        # Force MP4 muxer — ffmpeg infers format from extension, but our
        # atomic-write path ends in `.partial` so it can't auto-pick one.
        "-f", "mp4",
        str(partial),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            try:
                partial.unlink(missing_ok=True)
            except Exception:
                pass
            tail = (stderr or b"").decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg diversify failed (rc={proc.returncode}): {tail}")
        _os.replace(partial, out)
    finally:
        if tmp_download is not None:
            try:
                tmp_download.unlink(missing_ok=True)
            except Exception:
                pass

    return out


# ---------------------------------------------------------------------------
# Passthrough mode (no diversification)
# ---------------------------------------------------------------------------
# When clip_diversification_enabled=0, TikTok still requires the source URL
# to be on a domain verified in TikTok's Developer Portal. Posting GDrive
# direct-download links straight to TikTok fails with `url_ownership_unverified`.
#
# Solution: download the clip to a stable local cache path under our verified
# domain (icreateflow.com), then return the public URL pointing at that file.
# No ffmpeg, no perceptual changes — just a domain wrapper. Same clip serves
# every variation/platform; cache is keyed by clip_id only.

PASSTHROUGH_ROOT = Path("uploads/passthrough_clips")


def passthrough_path(clip_id: int) -> Path:
    return PASSTHROUGH_ROOT / f"{clip_id}.mp4"


async def _probe_video_codec(path: Path) -> str:
    """Return the video codec_name (e.g. 'h264', 'hevc'). Empty string on error."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=nk=1:nw=1",
        str(path),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return (out or b"").decode().strip().lower()


async def _transcode_to_h264(src: Path, dst: Path) -> None:
    """Re-encode src → dst as H.264 / AAC, preserving dimensions and duration.
    Atomic via .partial + os.replace.
    """
    import os as _os
    partial = dst.with_suffix(dst.suffix + ".partial")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(partial),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        try:
            partial.unlink(missing_ok=True)
        except Exception:
            pass
        tail = (stderr or b"").decode(errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg passthrough transcode failed (rc={proc.returncode}): {tail}")
    _os.replace(partial, dst)


async def passthrough_download(source: str, clip_id: int) -> Path:
    """Download `source` (a remote URL) to a stable local cache path and
    return that Path. If the cache file already exists and is non-empty, skip
    the download. Local source paths are returned unchanged.

    Atomic via .partial + os.replace so concurrent ticks never see a half-
    downloaded file.

    If the downloaded source is HEVC (H.265) we transcode in place to H.264.
    TikTok accepts H.265 at the upload API but its player renders it glitchy
    — the diversifier always re-encodes to H.264 so this only matters in
    passthrough mode, but it's the kind of bug that's invisible until it
    isn't.
    """
    if not source.startswith(("http://", "https://")):
        # Already a local file
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Clip source not found: {source}")
        return p

    out = passthrough_path(clip_id)
    if out.exists() and out.stat().st_size > 0:
        # Cached — but verify it's H.264. If a previous version saved HEVC
        # (the bug we're fixing), nuke the cache and re-pull.
        codec = await _probe_video_codec(out)
        if codec == "h264":
            return out
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass

    out.parent.mkdir(parents=True, exist_ok=True)
    import os as _os
    partial = out.with_suffix(out.suffix + ".partial")
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        async with client.stream("GET", source) as r:
            r.raise_for_status()
            with partial.open("wb") as f:
                async for chunk in r.aiter_bytes(1024 * 256):
                    f.write(chunk)

    # Probe what we just downloaded. H.264 → keep as-is. Anything else
    # (HEVC, VP9, etc.) → transcode to H.264.
    codec = await _probe_video_codec(partial)
    if codec == "h264":
        _os.replace(partial, out)
    else:
        # Transcode partial → out, then unlink the original partial.
        await _transcode_to_h264(partial, out)
        try:
            partial.unlink(missing_ok=True)
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
