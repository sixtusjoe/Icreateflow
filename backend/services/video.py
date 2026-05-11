"""
FFmpeg video builder.
Creates 9:16 videos with left-slide transitions from slide images.
Optionally mixes in background music.
"""
import asyncio
import subprocess
import shutil
from pathlib import Path


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def build_video(slide_paths: list[str], output_path: str,
                      slide_duration: float = 3.0, transition_duration: float = 0.5,
                      fps: int = 30, music_path: str = None) -> str:
    """
    Build a 9:16 video with left-slide transitions from a list of slide images.

    Args:
        slide_paths: Ordered list of 9:16 slide image paths
        output_path: Where to save the output MP4
        slide_duration: How long each slide is shown (seconds)
        transition_duration: How long the slide-left transition takes (seconds)
        fps: Frames per second
        music_path: Optional path to background music file

    Returns:
        Path to the output video file
    """
    if not check_ffmpeg():
        raise RuntimeError("FFmpeg not found. Install with: brew install ffmpeg")

    if len(slide_paths) < 2:
        raise ValueError("Need at least 2 slides to create a video")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    n = len(slide_paths)

    # Build input arguments: each image is looped for slide_duration
    inputs = []
    for p in slide_paths:
        inputs.extend(["-loop", "1", "-t", str(slide_duration), "-i", str(p)])

    # Build xfade filter chain
    filter_parts = []
    offset = slide_duration - transition_duration

    for i in range(1, n):
        if i == 1:
            in_label = "[0:v]"
        else:
            in_label = f"[v{i - 1}]"

        if i == n - 1:
            out_label = "[outv]"
        else:
            out_label = f"[v{i}]"

        filter_parts.append(
            f"{in_label}[{i}:v]xfade=transition=slideleft"
            f":duration={transition_duration}:offset={offset}{out_label}"
        )
        offset += slide_duration - transition_duration

    filter_complex = ";".join(filter_parts)

    # Build command. ffmpeg argument order matters: ALL -i inputs first,
    # then -filter_complex, then -map directives, then output options, then
    # the output file. The previous version placed `-i music` after
    # `-map [outv]`, which made ffmpeg fail with "Option map ... cannot be
    # applied to input url" — and silently produced an audio-less video.
    has_music = bool(music_path) and Path(music_path).exists()

    cmd = ["ffmpeg", "-y", *inputs]
    if has_music:
        cmd.extend(["-i", str(music_path)])

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]",
    ])

    if has_music:
        total_duration = (n * slide_duration) - ((n - 1) * transition_duration)
        cmd.extend([
            "-map", f"{n}:a",
            "-shortest",
            "-af", f"afade=t=out:st={max(total_duration - 1, 0)}:d=1",
        ])

    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-movflags", "+faststart",
        str(output_path)
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {stderr.decode()[-500:]}")

    return output_path


def get_video_duration(slide_count: int, slide_duration: float = 3.0,
                       transition_duration: float = 0.5) -> float:
    """Calculate total video duration given slide count and timings."""
    return (slide_count * slide_duration) - ((slide_count - 1) * transition_duration)


# Per-platform render profiles. Each entry picks slide duration + max duration
# so we can produce Shorts-safe, Reels-safe, FB-safe renders from the same
# 9:16 slide set. max_duration is the hard cap we squeeze into by shortening
# per-slide dwell when needed.
PLATFORM_PROFILES = {
    "youtube":   {"slide_duration": 3.0, "max_duration": 60.0},   # Shorts cap
    "instagram": {"slide_duration": 3.0, "max_duration": 90.0},   # Reels cap
    "facebook":  {"slide_duration": 3.0, "max_duration": 90.0},   # Match Reels cap
}


async def build_platform_video(
    slide_paths: list[str],
    output_path: str,
    platform: str,
    music_path: str | None = None,
    transition_duration: float = 0.5,
    fps: int = 30,
) -> str:
    """Build a 9:16 video sized for the given platform's caps.

    Computes a per-slide dwell time that keeps total duration <= the
    platform's max_duration; falls back to the base 3.0s dwell otherwise.
    Delegates the actual ffmpeg invocation to build_video.
    """
    profile = PLATFORM_PROFILES.get(platform)
    if not profile:
        raise ValueError(f"Unknown platform profile: {platform}")

    n = len(slide_paths)
    if n < 2:
        raise ValueError("Need at least 2 slides to create a video")

    dwell = profile["slide_duration"]
    cap = profile["max_duration"]
    # Duration with the default dwell.
    total = get_video_duration(n, dwell, transition_duration)
    if total > cap:
        # Solve for dwell: (n*d) - (n-1)*t = cap  ->  d = (cap + (n-1)*t) / n
        dwell = max(1.0, (cap + (n - 1) * transition_duration) / n)

    return await build_video(
        slide_paths=slide_paths,
        output_path=output_path,
        slide_duration=dwell,
        transition_duration=transition_duration,
        fps=fps,
        music_path=music_path,
    )
