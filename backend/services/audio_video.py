"""
Audio-to-Video generation service.

Pipeline per clip:
  1. Render a 1080×1920 player template PNG using Pillow (background + card, no disc)
  2. Render the rotating vinyl disc as a separate transparent RGBA PNG
  3. Generate an ASS subtitle file with Whisper word-level karaoke timing
  4. Assemble via FFmpeg:
       – loop background PNG as base video
       – overlay rotating disc (rotate filter, transparent fill)
       – animate progress bar (drawbox)
       – burn karaoke subtitles (ass filter)
       – mux audio
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
        "bg_top":        (6, 6, 10),
        "bg_bot":        (18, 18, 30),
        "card_color":    (22, 22, 36, 210),
        "accent_color":  (0, 255, 170),
        "highlight_rgb": (0, 255, 170),
        "bar_color":     (0, 255, 170),
        "text_color":    (255, 255, 255),
        "ring_colors":   [(0, 255, 170), (0, 200, 130), (0, 140, 90)],
        "glow_color":    (0, 255, 170),
    },
    "vivid": {
        "bg_top":        (12, 0, 28),
        "bg_bot":        (32, 5, 62),
        "card_color":    (42, 10, 78, 210),
        "accent_color":  (200, 130, 255),
        "highlight_rgb": (255, 90, 200),
        "bar_color":     (200, 130, 255),
        "text_color":    (255, 255, 255),
        "ring_colors":   [(255, 90, 200), (200, 60, 160), (160, 40, 120)],
        "glow_color":    (200, 130, 255),
    },
    "neon": {
        "bg_top":        (0, 6, 18),
        "bg_bot":        (0, 14, 36),
        "card_color":    (0, 20, 46, 210),
        "accent_color":  (0, 220, 255),
        "highlight_rgb": (0, 220, 255),
        "bar_color":     (0, 220, 255),
        "text_color":    (220, 240, 255),
        "ring_colors":   [(0, 220, 255), (0, 160, 200), (0, 100, 150)],
        "glow_color":    (0, 220, 255),
    },
}

W, H = 1080, 1920   # 9:16 canvas

# ---------------------------------------------------------------------------
# Layout constants  (all units: pixels on the 1080×1920 canvas)
# ---------------------------------------------------------------------------

DISC_R      = 188           # vinyl disc radius
DISC_CX     = W // 2        # 540 — horizontal centre of disc
DISC_CY     = 660           # vertical  centre of disc
ART_SIZE    = DISC_R * 2    # 376 — bounding-box diameter
DISC_CANVAS = ART_SIZE + 80 # 456 — disc PNG canvas (room for glow rings)

# Where the disc PNG's top-left lands on the background canvas
DISC_X = DISC_CX - DISC_CANVAS // 2   # 540 - 228 = 312
DISC_Y = DISC_CY - DISC_CANVAS // 2   # 660 - 228 = 432

# Frosted card sits behind the lower half of the disc and the info section
CARD_X0 = 60
CARD_X1 = W - 60
CARD_Y0 = DISC_CY - DISC_R - 80     # 392  (slightly above disc top)
CARD_Y1 = 1270

# Info text y-positions
NP_Y      = CARD_Y0 + 34             # "NOW PLAYING" label
TITLE_Y   = DISC_CY + DISC_R + 64   # track title            = 912
ARTIST_Y  = TITLE_Y + 70            # artist / subtitle      = 982

# Progress bar
BAR_X0 = CARD_X0 + 60               # 120
BAR_X1 = CARD_X1 - 60               # 960
BAR_Y  = ARTIST_Y + 82              # 1064
BAR_H  = 5

# Waveform decorative bars
WV_Y = BAR_Y + 66                    # 1130

FONTS_DIR = Path(__file__).parent.parent / "fonts"

# Slight positive offset added to karaoke word timestamps so the highlight
# lands just after the word starts (Whisper tags onsets ~150 ms early on music).
KARAOKE_DELAY_S = 0.15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Vertical gradient across the full canvas."""
    for y in range(H):
        ratio = y / H
        r = int(top[0] + (bot[0] - top[0]) * ratio)
        g = int(top[1] + (bot[1] - top[1]) * ratio)
        b = int(top[2] + (bot[2] - top[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))


def _soft_glow(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               radius: int, color: tuple, layers: int = 7):
    """Radial soft glow centred at (cx, cy)."""
    for i in range(layers, 0, -1):
        rad   = radius + i * 14
        alpha = int(28 * (1 - i / (layers + 1)))
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=(*color, alpha))


# ---------------------------------------------------------------------------
# Disc renderer  (separate transparent PNG, rotated by FFmpeg)
# ---------------------------------------------------------------------------

def render_album_disc(
    template_id: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Render the vinyl-style album disc as a transparent RGBA PNG.
    FFmpeg will rotate this overlay to create the spinning effect.
    """
    t    = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    size = DISC_CANVAS                       # 456
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    cx = cy = size // 2                      # 228
    r  = DISC_R                              # 188
    gc = t.get("glow_color", t["accent_color"])
    ring_colors = t.get("ring_colors", [t["accent_color"]] * 3)

    # ── Outer glow (feathered rings) ────────────────────────────────────────
    for i in range(6, 0, -1):
        rad   = r + i * 10
        alpha = int(32 * (1 - i / 7))
        if cx - rad >= 0:                    # stay in canvas
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                         fill=(*gc, alpha))

    # ── Main disc body (dark circle) ────────────────────────────────────────
    disc_dark = tuple(max(0, c - 8) for c in t["bg_top"])
    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                 fill=(*disc_dark, 255))

    # ── Groove rings ─────────────────────────────────────────────────────────
    groove_radii  = [r - 10, r - 44, r - 78, r - 112]
    groove_alphas = [170, 115, 72, 45]
    groove_widths = [3, 2, 2, 1]
    for i, (rad, alph, wid) in enumerate(
            zip(groove_radii, groove_alphas, groove_widths)):
        if rad < 20:
            break
        rc = ring_colors[i % len(ring_colors)]
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     outline=(*rc, alph), width=wid)

    # ── Asymmetric marker dot so rotation is visible ─────────────────────────
    # Offset along one groove ring so it orbits the center as the disc spins
    mk_rad   = r - 44          # same radius as inner groove
    mk_angle = 0               # at the "3 o'clock" position (right side)
    mk_x     = cx + int(mk_rad * math.cos(mk_angle))
    mk_y     = cy + int(mk_rad * math.sin(mk_angle))
    draw.ellipse([mk_x - 7, mk_y - 7, mk_x + 7, mk_y + 7],
                 fill=(*t["accent_color"], 220))

    # ── Centre label circle ──────────────────────────────────────────────────
    label_r = 68
    draw.ellipse([cx - label_r, cy - label_r, cx + label_r, cy + label_r],
                 fill=(*t["accent_color"], 245))

    # ── Darker sub-circle inside label ───────────────────────────────────────
    sub_r   = 30
    sub_col = tuple(max(0, c - 50) for c in t["accent_color"])
    draw.ellipse([cx - sub_r, cy - sub_r, cx + sub_r, cy + sub_r],
                 fill=(*sub_col, 255))

    # ── Centre spindle hole ───────────────────────────────────────────────────
    hole_r = 11
    draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r],
                 fill=(0, 0, 0, 0))

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        output_path = tmp.name
        tmp.close()
    canvas.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Background / card renderer  (static PNG, disc NOT drawn here)
# ---------------------------------------------------------------------------

def render_template_background(
    template_id: str,
    background_image_path: Optional[str] = None,
    output_path: Optional[str] = None,
    title: str = "",
    artist: str = "",
) -> str:
    """Render the 1080×1920 static background PNG.  The rotating disc is
    composited on top by FFmpeg, so it is intentionally omitted here."""
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    canvas = Image.new("RGBA", (W, H), (*t["bg_top"], 255))
    draw   = ImageDraw.Draw(canvas)

    # ── Gradient background ──────────────────────────────────────────────────
    _gradient_bg(draw, t["bg_top"], t["bg_bot"])

    # ── Optional user background — blurred + darkened ────────────────────────
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
        bg = bg.filter(ImageFilter.GaussianBlur(26))
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 165))
        canvas  = Image.alpha_composite(bg, overlay)
        draw    = ImageDraw.Draw(canvas)

    # ── Soft ambient glow where the disc will sit ────────────────────────────
    gc = t.get("glow_color", t["accent_color"])
    _soft_glow(draw, DISC_CX, DISC_CY, DISC_R, gc, layers=7)

    # ── Frosted-glass card (spans disc area + info section below) ────────────
    _rounded_rect(draw, (CARD_X0, CARD_Y0, CARD_X1, CARD_Y1), 36,
                  (*t["card_color"][:3], t["card_color"][3]))

    # ── "NOW PLAYING" label at top of card ───────────────────────────────────
    draw.text((W // 2, NP_Y), "NOW PLAYING",
              font=_font(22), fill=(*t["text_color"], 80), anchor="mm")

    # ── Track title ──────────────────────────────────────────────────────────
    title_text = title.strip() if title.strip() else "♪  ♪  ♪"
    # Truncate long titles so they fit
    title_font = _font(52)
    while len(title_text) > 3:
        bbox = title_font.getbbox(title_text)
        if (bbox[2] - bbox[0]) <= (CARD_X1 - CARD_X0 - 80):
            break
        title_text = title_text[:-1]
    draw.text((W // 2, TITLE_Y), title_text,
              font=title_font, fill=(*t["text_color"], 240), anchor="mm")

    # ── Artist / subtitle line ────────────────────────────────────────────────
    if artist.strip():
        artist_text = artist.strip()
        if len(artist_text) > 32:
            artist_text = artist_text[:32] + "…"
        draw.text((W // 2, ARTIST_Y), artist_text,
                  font=_font(32), fill=(*t["text_color"], 140), anchor="mm")

    # ── Thin divider under artist name ───────────────────────────────────────
    div_y = ARTIST_Y + 46
    draw.rectangle([CARD_X0 + 100, div_y, CARD_X1 - 100, div_y + 1],
                   fill=(*t["text_color"], 22))

    # ── Progress bar track ────────────────────────────────────────────────────
    _rounded_rect(draw, (BAR_X0, BAR_Y, BAR_X1, BAR_Y + BAR_H), 2,
                  (*t["text_color"], 26))

    # Time labels
    tf = _font(26)
    draw.text((BAR_X0, BAR_Y + 22), "0:00",
              font=tf, fill=(*t["text_color"], 80), anchor="lm")
    draw.text((BAR_X1, BAR_Y + 22), "--:--",
              font=tf, fill=(*t["text_color"], 80), anchor="rm")

    # ── Decorative waveform bars ──────────────────────────────────────────────
    bar_count = 40
    total_w   = BAR_X1 - BAR_X0
    bw        = max(3, total_w // (bar_count * 2 + 1))
    gap       = max(2, bw)

    for i in range(bar_count):
        bh   = int(8 + 42 * abs(math.sin(i * 0.72 + 0.9)))
        bx   = BAR_X0 + i * (bw + gap)
        edge = abs(i - bar_count / 2) / (bar_count / 2)
        alph = max(18, int(78 * (1 - edge * 0.65)))
        draw.rectangle([bx, WV_Y - bh // 2, bx + bw, WV_Y + bh // 2],
                       fill=(*t["accent_color"], alph))

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
    """Convert seconds → ASS H:MM:SS.cc timestamp."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_lyrics(
    words: list[dict],
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
        tmp = tempfile.NamedTemporaryFile(
            suffix=".ass", delete=False, mode="w", encoding="utf-8")
        output_path = tmp.name
        tmp.close()

    # Alignment 2 = bottom-centre.  MarginV 360 px from bottom → lyrics sit
    # in the lower third of the frame, well below the player card (CARD_Y1≈1270).
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Karaoke,TikTok Sans,68,{white_ass},{highlight_ass},"
        "&H00000000&,&H90000000&,"
        "1,0,0,0,100,100,1,0,1,4,2,2,80,80,360,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Group into lines of ~5 words
    group_size = 5
    groups = [words[i:i + group_size] for i in range(0, len(words), group_size)]

    for group in groups:
        if not group:
            continue
        start = max(0.0, group[0]["start_s"])
        end   = min(group[-1]["end_s"] + 0.6, clip_duration)
        parts = []
        for w in group:
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
    words: list[dict],
    template_id: str,
    output_path: str,
    background_image_path: Optional[str] = None,
    title: str = "",
    artist: str = "",
) -> str:
    """
    Assemble a 9:16 MP4:
      [0] background PNG  (looped static image)
      [1] disc PNG        (looped, rotated via FFmpeg rotate filter)
      [2] audio clip

    filter_complex:
      - rotate disc at 1 RPM (one revolution per 8 s)
      - overlay disc on background
      - animate progress bar (drawbox)
      - burn karaoke subtitles (ass)
    """
    duration = clip_end_s - clip_start_s

    # Normalise word timestamps to clip-relative seconds
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
    disc_png = str(tmp_dir / "disc.png")
    ass_file = str(tmp_dir / "lyrics.ass")

    try:
        # 1 — render static background (no disc)
        await asyncio.to_thread(
            render_template_background,
            template_id, background_image_path, bg_png, title, artist,
        )

        # 2 — render rotating disc
        await asyncio.to_thread(render_album_disc, template_id, disc_png)

        # 3 — ASS karaoke subtitles
        await asyncio.to_thread(
            build_ass_lyrics, clip_words, duration, template_id, ass_file,
        )

        # 4 — build FFmpeg filter_complex
        t   = TEMPLATES.get(template_id, TEMPLATES["minimal"])
        r, g, b = t["bar_color"]
        bar_color_hex = f"{r:02x}{g:02x}{b:02x}ff"
        bar_w = BAR_X1 - BAR_X0

        ass_escaped = ass_file.replace("\\", "/")

        # Rotate disc: one full revolution every 8 seconds, transparent fill
        filter_complex = (
            # Step 1: rotate disc (RGBA transparent fill)
            f"[1:v]format=rgba,"
            f"rotate=2*PI*t/8:c=none:ow={DISC_CANVAS}:oh={DISC_CANVAS}[rot];"
            # Step 2: overlay disc on background
            f"[0:v][rot]overlay={DISC_X}:{DISC_Y}[bgd];"
            # Step 3: animated progress bar
            f"[bgd]drawbox="
            f"x={BAR_X0}:y={BAR_Y}:"
            f"w='({bar_w})*t/{duration:.3f}':h={BAR_H}:"
            f"c=0x{bar_color_hex}:t=fill,"
            # Step 4: karaoke lyrics
            f"ass={ass_escaped}[v]"
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "30", "-i", bg_png,    # [0] background
            "-loop", "1", "-framerate", "30", "-i", disc_png,  # [1] disc
            "-i", audio_clip_path,                              # [2] audio
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "2:a",
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
            raise RuntimeError(f"FFmpeg failed: {stderr.decode()[:600]}")

    finally:
        for f in [bg_png, disc_png, ass_file]:
            try:
                os.unlink(f)
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass

    return output_path
