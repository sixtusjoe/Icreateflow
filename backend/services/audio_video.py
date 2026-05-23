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
        "bg_color":      (10, 10, 15),
        "card_color":    (28, 28, 36, 220),
        "accent_color":  (255, 255, 255),
        "highlight_rgb": (0, 255, 170),   # neon-green on dark
        "bar_color":     (255, 255, 255),
        "text_color":    (255, 255, 255),
    },
    "vivid": {
        "bg_color":      (18, 0, 40),
        "card_color":    (40, 10, 80, 210),
        "accent_color":  (200, 130, 255),
        "highlight_rgb": (255, 90, 200),   # hot-pink
        "bar_color":     (200, 130, 255),
        "text_color":    (255, 255, 255),
    },
    "neon": {
        "bg_color":      (0, 8, 20),
        "card_color":    (0, 20, 40, 200),
        "accent_color":  (0, 220, 255),
        "highlight_rgb": (0, 220, 255),    # cyan
        "bar_color":     (0, 220, 255),
        "text_color":    (220, 240, 255),
    },
}

W, H = 1080, 1920   # 9:16 canvas
FONTS_DIR = Path(__file__).parent.parent / "fonts"


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


def render_template_background(
    template_id: str,
    background_image_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Render a 1080×1920 PNG player card background.

    Returns path to the saved PNG.
    """
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    canvas = Image.new("RGBA", (W, H), t["bg_color"] + (255,))

    # Optional user background image — blurred + darkened
    if background_image_path and Path(background_image_path).exists():
        bg = Image.open(background_image_path).convert("RGBA")
        # Fill canvas proportionally
        bg_ratio = bg.width / bg.height
        if bg_ratio > W / H:
            new_h = H
            new_w = int(bg_ratio * H)
        else:
            new_w = W
            new_h = int(W / bg_ratio)
        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        xo = (new_w - W) // 2
        yo = (new_h - H) // 2
        bg = bg.crop((xo, yo, xo + W, yo + H))
        bg = bg.filter(ImageFilter.GaussianBlur(20))
        # Darken
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 160))
        canvas = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(canvas)

    # --- Player card ---
    card_x0, card_x1 = 80, W - 80
    card_y0, card_y1 = H // 2 - 380, H // 2 + 380
    card_fill = t["card_color"]
    _rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1), 32, card_fill)

    # Album art placeholder (square, top of card)
    art_size = 340
    art_x = (W - art_size) // 2
    art_y = card_y0 + 48
    _rounded_rect(draw, (art_x, art_y, art_x + art_size, art_y + art_size), 20,
                  tuple(max(0, c - 20) for c in t["bg_color"]) + (255,))

    # Music note icon placeholder
    note_font = _font(80)
    draw.text((art_x + art_size // 2, art_y + art_size // 2), "♪",
              font=note_font, fill=t["accent_color"] + (120,), anchor="mm")

    # Song title placeholder
    title_y = art_y + art_size + 36
    title_font = _font(38)
    draw.text((W // 2, title_y), "♫  Now Playing", font=title_font,
              fill=t["text_color"] + (200,), anchor="mm")

    # Progress bar track
    bar_x0 = card_x0 + 60
    bar_x1 = card_x1 - 60
    bar_y = title_y + 64
    bar_h = 6
    _rounded_rect(draw, (bar_x0, bar_y, bar_x1, bar_y + bar_h), 3,
                  (255, 255, 255, 40))

    # Time labels
    time_font = _font(26)
    draw.text((bar_x0, bar_y + 18), "0:00", font=time_font,
              fill=t["text_color"] + (140,), anchor="lm")
    draw.text((bar_x1, bar_y + 18), "--:--", font=time_font,
              fill=t["text_color"] + (140,), anchor="rm")

    # Waveform bars (decorative static)
    wv_y = bar_y + 60
    bar_count = 32
    bw = (bar_x1 - bar_x0) // (bar_count * 2)
    heights = [
        int(20 + 40 * abs(math.sin(i * 0.7 + 1))) for i in range(bar_count)
    ]
    for i, bh in enumerate(heights):
        bx = bar_x0 + i * bw * 2
        draw.rectangle(
            [bx, wv_y - bh // 2, bx + bw, wv_y + bh // 2],
            fill=t["accent_color"] + (60,),
        )

    # Lyrics area hint
    lyric_y = card_y1 + 48
    hint_font = _font(32)
    draw.text((W // 2, lyric_y), "♪", font=hint_font,
              fill=t["highlight_rgb"] + (80,), anchor="mm")

    # Convert to RGB for JPEG/FFmpeg compat
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
    """Generate an ASS subtitle file with per-word karaoke highlighting.

    Returns path to .ass file.
    """
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    r, g, b = t["highlight_rgb"]
    # ASS color is &HBBGGRR& (BGR order)
    highlight_ass = f"&H00{b:02X}{g:02X}{r:02X}&"
    white_ass = "&H00FFFFFF&"

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w", encoding="utf-8")
        output_path = tmp.name
        tmp.close()

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
        f"Style: Karaoke,TikTok Sans,62,{white_ass},{highlight_ass},&H00000000&,&H80000000&,"
        "1,0,0,0,100,100,2,0,1,3,2,2,80,80,140,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Group words into lines of ~5 words each
    group_size = 5
    groups = [words[i:i + group_size] for i in range(0, len(words), group_size)]

    for group in groups:
        if not group:
            continue
        start = group[0]["start_s"]
        end = group[-1]["end_s"]
        # Pad end slightly so last group lingers
        end = min(end + 0.8, clip_duration)

        # Build karaoke text: {\k<centiseconds>}word
        parts = []
        for w in group:
            dur_cs = max(1, int((w["end_s"] - w["start_s"]) * 100))
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
    """Assemble a 9:16 MP4 from an audio clip + karaoke lyrics.

    Returns output_path on success.
    """
    duration = clip_end_s - clip_start_s

    # Normalise word timestamps to be relative to clip start
    clip_words = [
        {
            "word": w["word"],
            "start_s": max(0.0, w["start_s"] - clip_start_s),
            "end_s": max(0.0, w["end_s"] - clip_start_s),
        }
        for w in words
        if w["start_s"] < clip_end_s and w["end_s"] > clip_start_s
    ]

    tmp_dir = Path(tempfile.mkdtemp())
    bg_png = str(tmp_dir / "bg.png")
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

        # bar geometry (must match render_template_background)
        bar_x0 = 80 + 60       # card_x0 + padding
        bar_x1 = W - 80 - 60
        bar_w = bar_x1 - bar_x0
        # bar_y is halfway down card
        card_y0 = H // 2 - 380
        art_y = card_y0 + 48
        art_size = 340
        title_y = art_y + art_size + 36
        bar_y = title_y + 64

        # FFmpeg filter chain
        # [0:v] = looped background PNG
        # drawbox animates progress bar fill
        # ass overlays karaoke subtitles
        bar_filter = (
            f"drawbox=x={bar_x0}:y={bar_y}:"
            f"w='({bar_w})*t/{duration:.3f}':h=6:"
            f"c=0x{bar_color_hex}:t=fill"
        )
        vf = f"{bar_filter},ass={ass_file.replace(chr(92), '/')}"

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
        # Clean up temp files
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
