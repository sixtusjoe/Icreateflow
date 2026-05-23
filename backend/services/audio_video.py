"""
Audio-to-Video generation service.

Pipeline per clip:
  1. Render a 1080×1920 player template PNG using Pillow
  2. Generate an ASS subtitle file with Whisper word-level karaoke timing
  3. Assemble: loop background + mux audio + overlay ASS → H.264 MP4
"""
from __future__ import annotations

import asyncio
import math
import os
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFile, ImageFilter
ImageFile.LOAD_TRUNCATED_IMAGES = True

# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

TEMPLATES = {
    "minimal": {
        "bg_top":        (8, 8, 12),
        "bg_bot":        (18, 18, 28),
        "card_color":    (30, 30, 42, 210),
        "accent_color":  (0, 255, 170),    # neon-green
        "highlight_rgb": (0, 255, 170),
        "bar_color":     (0, 255, 170),
        "text_color":    (255, 255, 255),
        "ring_colors":   [(0, 255, 170), (0, 200, 130), (0, 140, 90)],
    },
    "vivid": {
        "bg_top":        (14, 0, 32),
        "bg_bot":        (35, 5, 70),
        "card_color":    (50, 15, 90, 200),
        "accent_color":  (200, 130, 255),
        "highlight_rgb": (255, 90, 200),   # hot-pink
        "bar_color":     (200, 130, 255),
        "text_color":    (255, 255, 255),
        "ring_colors":   [(255, 90, 200), (200, 60, 160), (160, 40, 120)],
    },
    "neon": {
        "bg_top":        (0, 6, 18),
        "bg_bot":        (0, 14, 35),
        "card_color":    (0, 22, 48, 200),
        "accent_color":  (0, 220, 255),    # cyan
        "highlight_rgb": (0, 220, 255),
        "bar_color":     (0, 220, 255),
        "text_color":    (220, 240, 255),
        "ring_colors":   [(0, 220, 255), (0, 160, 200), (0, 100, 150)],
    },
}

W, H = 1080, 1920   # 9:16 canvas
FONTS_DIR = Path(__file__).parent.parent / "fonts"

# Small positive offset (seconds) added to every word timestamp so the
# karaoke highlight lands a touch after the word starts — Whisper tends
# to tag word-onset slightly early on music tracks.
KARAOKE_DELAY_S = 0.15


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / "TikTokSans-Variable.ttf"
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill):
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.ellipse([x0, y0, x0 + 2 * radius, y0 + 2 * radius], fill=fill)
    draw.ellipse([x1 - 2 * radius, y0, x1, y0 + 2 * radius], fill=fill)
    draw.ellipse([x0, y1 - 2 * radius, x0 + 2 * radius, y1], fill=fill)
    draw.ellipse([x1 - 2 * radius, y1 - 2 * radius, x1, y1], fill=fill)


def _gradient_bg(draw: ImageDraw.ImageDraw, top: tuple, bot: tuple):
    """Draw a vertical gradient on the full canvas."""
    for y in range(H):
        ratio = y / H
        r = int(top[0] + (bot[0] - top[0]) * ratio)
        g = int(top[1] + (bot[1] - top[1]) * ratio)
        b = int(top[2] + (bot[2] - top[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))


def render_template_background(
    template_id: str,
    background_image_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Render a 1080×1920 PNG player card background."""
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    canvas = Image.new("RGBA", (W, H), (*t["bg_top"], 255))
    draw = ImageDraw.Draw(canvas)

    # ── Gradient background ──────────────────────────────────────────────────
    _gradient_bg(draw, t["bg_top"], t["bg_bot"])

    # ── Optional user background image — blurred + darkened ─────────────────
    if background_image_path and Path(background_image_path).exists():
        bg = Image.open(background_image_path).convert("RGBA")
        bg_ratio = bg.width / bg.height
        if bg_ratio > W / H:
            new_h, new_w = H, int(bg_ratio * H)
        else:
            new_w, new_h = W, int(W / bg_ratio)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        xo, yo = (new_w - W) // 2, (new_h - H) // 2
        bg = bg.crop((xo, yo, xo + W, yo + H))
        bg = bg.filter(ImageFilter.GaussianBlur(24))
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 170))
        canvas = Image.alpha_composite(bg, overlay)
        draw = ImageDraw.Draw(canvas)

    # ── Card ─────────────────────────────────────────────────────────────────
    card_x0, card_x1 = 60, W - 60
    card_y0 = H // 2 - 420
    card_y1 = H // 2 + 360
    _rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1), 36,
                  (*t["card_color"][:3], t["card_color"][3]))

    # ── Album art area ────────────────────────────────────────────────────────
    art_size = 360
    art_x = (W - art_size) // 2
    art_y = card_y0 + 52

    # Dark square background
    art_bg = tuple(max(0, c - 18) for c in t["bg_top"])
    _rounded_rect(draw, (art_x, art_y, art_x + art_size, art_y + art_size), 24,
                  (*art_bg, 255))

    # Concentric glowing rings — no special Unicode chars needed
    cx, cy = art_x + art_size // 2, art_y + art_size // 2
    ring_colors = t.get("ring_colors", [t["accent_color"]] * 3)
    radii   = [art_size // 2 - 10, art_size // 2 - 48, art_size // 2 - 86]
    alphas  = [180, 110, 60]
    widths  = [4, 3, 2]
    for rc, rad, alph, wid in zip(ring_colors, radii, alphas, widths):
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     outline=(*rc, alph), width=wid)

    # Centre filled dot
    dot_r = 22
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                 fill=(*t["accent_color"], 230))
    # Smaller white core
    core_r = 9
    draw.ellipse([cx - core_r, cy - core_r, cx + core_r, cy + core_r],
                 fill=(255, 255, 255, 200))

    # ── "NOW PLAYING" label ──────────────────────────────────────────────────
    label_y = art_y + art_size + 38
    label_font = _font(26)
    draw.text((W // 2, label_y), "NOW PLAYING",
              font=label_font, fill=(*t["text_color"], 100), anchor="mm")

    # ── Thin divider ─────────────────────────────────────────────────────────
    div_y = label_y + 42
    draw.rectangle(
        [card_x0 + 80, div_y, card_x1 - 80, div_y + 1],
        fill=(*t["text_color"], 25),
    )

    # ── Progress bar track ───────────────────────────────────────────────────
    bar_x0 = card_x0 + 60
    bar_x1 = card_x1 - 60
    bar_y  = div_y + 52
    bar_h  = 5

    _rounded_rect(draw, (bar_x0, bar_y, bar_x1, bar_y + bar_h), 2,
                  (*t["text_color"], 28))

    # Time labels
    time_font = _font(24)
    draw.text((bar_x0, bar_y + 20), "0:00", font=time_font,
              fill=(*t["text_color"], 90), anchor="lm")
    draw.text((bar_x1, bar_y + 20), "--:--", font=time_font,
              fill=(*t["text_color"], 90), anchor="rm")

    # ── Waveform bars (decorative static) ────────────────────────────────────
    wv_y      = bar_y + 58
    bar_count = 38
    total_w   = bar_x1 - bar_x0
    bw        = max(3, total_w // (bar_count * 2 + 1))
    gap       = max(2, bw)

    for i in range(bar_count):
        bh   = int(10 + 44 * abs(math.sin(i * 0.68 + 0.5)))
        bx   = bar_x0 + i * (bw + gap)
        # Fade alpha toward edges
        edge_ratio = abs(i - bar_count / 2) / (bar_count / 2)
        alph = max(25, int(85 * (1 - edge_ratio * 0.6)))
        draw.rectangle(
            [bx, wv_y - bh // 2, bx + bw, wv_y + bh // 2],
            fill=(*t["accent_color"], alph),
        )

    # ── Subtle glow dot below card (visual flair) ─────────────────────────────
    glow_y = card_y1 + 40
    glow_r = 4
    draw.ellipse([W // 2 - glow_r, glow_y - glow_r,
                  W // 2 + glow_r, glow_y + glow_r],
                 fill=(*t["accent_color"], 60))

    result = canvas.convert("RGB")
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        output_path = tmp.name
        tmp.close()
    result.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# ASS subtitle (karaoke) generation
# ---------------------------------------------------------------------------

def _seconds_to_ass(t: float) -> str:
    """Convert seconds to ASS H:MM:SS.cc timestamp."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_lyrics(
    words: list[dict],          # [{word, start_s, end_s}], relative to clip start
    clip_duration: float,
    template_id: str = "minimal",
    output_path: Optional[str] = None,
) -> str:
    """Generate an ASS subtitle file with per-word karaoke highlighting."""
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    r, g, b = t["highlight_rgb"]
    highlight_ass = f"&H00{b:02X}{g:02X}{r:02X}&"
    white_ass     = "&H00FFFFFF&"

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
        output_path = tmp.name
        tmp.close()

    # ── Style ────────────────────────────────────────────────────────────────
    # Alignment 2  = bottom-center
    # MarginV 360  = 360 px from the bottom edge → sits centred in the lower
    #                third of the frame (below the player card)
    # Fontsize 68  = large, readable on phone screens
    # Outline 4 + Shadow 2 = crisp glow on any background
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, "
        "Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Karaoke,TikTok Sans,68,{white_ass},{highlight_ass},&H00000000&,&H90000000&,"
        "1,0,0,0,100,100,1,0,1,4,2,2,80,80,360,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Group words into lines of ~5 words
    group_size = 5
    groups = [words[i:i + group_size] for i in range(0, len(words), group_size)]

    for group in groups:
        if not group:
            continue
        start = max(0.0, group[0]["start_s"])
        end   = min(group[-1]["end_s"] + 0.6, clip_duration)

        parts = []
        for w in group:
            # Apply karaoke delay so highlight tracks the word, not the onset
            w_start = w["start_s"] + KARAOKE_DELAY_S
            w_end   = w["end_s"]   + KARAOKE_DELAY_S
            dur_cs  = max(1, int((w_end - w_start) * 100))
            parts.append(f"{{\\k{dur_cs}}}{w['word']}")
        text = " ".join(parts)

        lines.append(
            f"Dialogue: 0,{_seconds_to_ass(start)},{_seconds_to_ass(end)},"
            f"Karaoke,,0,0,0,,{text}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_path


# ---------------------------------------------------------------------------
# Full video assembly
# ---------------------------------------------------------------------------

async def generate_audio_video_clip(
    audio_clip_path: str,
    clip_start_s: float,
    clip_end_s: float,
    words: list[dict],           # [{word, start_s, end_s}] relative to full track
    template_id: str,
    output_path: str,
    background_image_path: Optional[str] = None,
) -> str:
    """Assemble a 9:16 MP4 from an audio clip + karaoke lyrics."""
    duration = clip_end_s - clip_start_s

    # Normalise word timestamps to be relative to clip start
    clip_words = [
        {
            "word":    w["word"],
            "start_s": max(0.0, w["start_s"] - clip_start_s),
            "end_s":   max(0.0, w["end_s"]   - clip_start_s),
        }
        for w in words
        if w["start_s"] < clip_end_s and w["end_s"] > clip_start_s
    ]

    tmp_dir  = Path(tempfile.mkdtemp())
    bg_png   = str(tmp_dir / "bg.png")
    ass_file = str(tmp_dir / "lyrics.ass")

    try:
        # 1 — render background in thread
        await asyncio.to_thread(
            render_template_background, template_id, background_image_path, bg_png
        )

        # 2 — generate ASS subtitles in thread
        await asyncio.to_thread(
            build_ass_lyrics, clip_words, duration, template_id, ass_file
        )

        # 3 — animated progress bar via FFmpeg drawbox
        t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
        r, g, b = t["bar_color"]
        bar_color_hex = f"{r:02x}{g:02x}{b:02x}ff"

        # bar geometry — must mirror render_template_background
        card_x0 = 60
        card_x1 = W - 60
        card_y0 = H // 2 - 420
        art_size = 360
        art_y   = card_y0 + 52
        label_y = art_y + art_size + 38
        div_y   = label_y + 42
        bar_x0  = card_x0 + 60
        bar_x1  = card_x1 - 60
        bar_w   = bar_x1 - bar_x0
        bar_y   = div_y + 52

        bar_filter = (
            f"drawbox=x={bar_x0}:y={bar_y}:"
            f"w='({bar_w})*t/{duration:.3f}':h=5:"
            f"c=0x{bar_color_hex}:t=fill"
        )
        # Escape Windows backslash in ass path (no-op on Linux)
        ass_escaped = ass_file.replace("\\", "/")
        vf = f"{bar_filter},ass={ass_escaped}"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "30", "-i", bg_png,
            "-i", audio_clip_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {stderr.decode()[:400]}")

    finally:
        for f in [bg_png, ass_file]:
            try:
                os.unlink(f)
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass

    return output_path
