"""
Audio-to-Video generation service.

Four cinematic templates: minimal | neon | vivid | inferno

Pipeline per clip:
  1. Render 1080×1920 background PNG (Pillow):
       – gradient / tinted background
       – rounded-rect card (upper ~48 % of frame)
       – album art: square for vivid/inferno; disc left for FFmpeg on minimal/neon
       – "NOW PLAYING" label inside card
       – progress bar track below card
  2. For minimal/neon: render rotating vinyl-disc as transparent RGBA PNG
  3. Build ASS karaoke subtitle file (Whisper word timestamps)
  4. FFmpeg assembly:
       – loop background PNG
       – (minimal/neon only) overlay rotating disc via `rotate` filter
       – animate progress bar fill (drawbox)
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
        "bg_top":         (8, 10, 14),
        "bg_bot":         (18, 22, 32),
        "card_color":     (16, 18, 28, 225),
        "card_border":    (255, 255, 255, 18),
        "accent_color":   (0, 255, 136),
        "highlight_rgb":  (0, 255, 136),
        "bar_color":      (0, 255, 136),
        "text_color":     (255, 255, 255),
        "glow_color":     (0, 255, 136),
        "art_style":      "disc_dashed",   # circular art + dashed ring
        "disc_dark":      (10, 10, 14),
    },
    "neon": {
        "bg_top":         (5, 12, 30),
        "bg_bot":         (8, 20, 48),
        "card_color":     (10, 18, 44, 225),
        "card_border":    (0, 200, 255, 30),
        "accent_color":   (0, 210, 255),
        "highlight_rgb":  (0, 210, 255),
        "bar_color":      (0, 210, 255),
        "text_color":     (210, 235, 255),
        "glow_color":     (0, 180, 220),
        "art_style":      "disc_vinyl",    # vinyl disc + album art in centre
        "disc_dark":      (8, 12, 22),
    },
    "vivid": {
        "bg_top":         (55, 0, 90),
        "bg_bot":         (18, 0, 55),
        "card_color":     (75, 8, 120, 215),
        "card_border":    (200, 80, 255, 40),
        "accent_color":   (255, 55, 175),
        "highlight_rgb":  (255, 55, 175),
        "bar_color":      (255, 55, 175),
        "text_color":     (255, 255, 255),
        "glow_color":     (210, 60, 200),
        "art_style":      "square",        # square album art
        "disc_dark":      None,
    },
    "inferno": {
        "bg_top":         (10, 8, 8),
        "bg_bot":         (4, 3, 3),
        "card_color":     (20, 16, 16, 230),
        "card_border":    (255, 255, 255, 12),
        "accent_color":   (240, 240, 240),
        "highlight_rgb":  (255, 200, 100),
        "bar_color":      (230, 230, 230),
        "text_color":     (255, 255, 255),
        "glow_color":     (160, 140, 110),
        "art_style":      "square",        # large square album art
        "disc_dark":      None,
    },
}

# Templates where album art is a rotating disc overlay (rendered separately)
ROTATING_TEMPLATES = {"minimal", "neon"}

W, H = 1080, 1920

# ── Layout ───────────────────────────────────────────────────────────────────
CARD_X0      = 42
CARD_X1      = W - 42         # 1038
CARD_Y0      = 68
CARD_Y1      = 918
CARD_RADIUS  = 42
CARD_W       = CARD_X1 - CARD_X0   # 996

ART_CX       = W // 2          # 540
ART_CY       = 430             # centre of art zone
ART_R        = 318             # disc radius (diameter 636)
ART_SQ       = 600             # square art side length

# Disc PNG canvas (larger than disc for glow headroom)
DISC_CANVAS  = ART_R * 2 + 84  # 720
DISC_X       = ART_CX - DISC_CANVAS // 2   # 540 - 360 = 180
DISC_Y       = ART_CY - DISC_CANVAS // 2   # 430 - 360 = 70

NP_Y         = 862             # "NOW PLAYING" y (inside card)
BAR_X0       = 82
BAR_X1       = W - 82          # 998
BAR_Y        = 965
BAR_H        = 4

FONTS_DIR    = Path(__file__).parent.parent / "fonts"
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


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill=None, outline=None, outline_width=1):
    x0, y0, x1, y1 = xy
    if fill:
        draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
        draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
        draw.ellipse([x0, y0, x0 + 2 * radius, y0 + 2 * radius], fill=fill)
        draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill)
        draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill)
        draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill)
    if outline:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                                outline=outline, width=outline_width)


def _gradient_bg(draw: ImageDraw.ImageDraw, top: tuple, bot: tuple):
    for y in range(H):
        ratio = y / H
        r = int(top[0] + (bot[0] - top[0]) * ratio)
        g = int(top[1] + (bot[1] - top[1]) * ratio)
        b = int(top[2] + (bot[2] - top[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    """Crop+resize an image to a circular RGBA thumbnail."""
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def _square_crop(img: Image.Image, size: int) -> Image.Image:
    """Centre-crop and resize an image to size×size."""
    img = img.convert("RGBA")
    w, h = img.size
    ratio = w / h
    if ratio > 1:
        new_w, new_h = int(ratio * size), size
    else:
        new_w, new_h = size, int(size / ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    xo = (new_w - size) // 2
    yo = (new_h - size) // 2
    return img.crop((xo, yo, xo + size, yo + size))


def _soft_glow(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               radius: int, color: tuple, layers: int = 6):
    for i in range(layers, 0, -1):
        rad   = radius + i * 12
        alpha = int(22 * (1 - i / (layers + 1)))
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=(*color, alpha))


# ---------------------------------------------------------------------------
# Disc renderer — minimal (dashed ring) & neon (vinyl)
# ---------------------------------------------------------------------------

def render_album_disc(
    template_id: str,
    album_cover_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Render the rotating disc as a transparent RGBA PNG.
    – minimal  → circular album art + dashed orbit ring
    – neon     → vinyl record with album art composited in centre
    """
    t    = TEMPLATES.get(template_id, TEMPLATES["neon"])
    size = DISC_CANVAS      # 720
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    cx = cy = size // 2     # 360
    r  = ART_R              # 318

    art_style = t.get("art_style", "disc_vinyl")
    gc        = t.get("glow_color", t["accent_color"])

    # ── Outer glow ───────────────────────────────────────────────────────────
    for i in range(5, 0, -1):
        rad   = r + i * 11
        alpha = int(28 * (1 - i / 6))
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=(*gc, alpha))

    if art_style == "disc_vinyl":
        # ── Dark vinyl body ──────────────────────────────────────────────────
        disc_dark = t.get("disc_dark", (10, 10, 18))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=(*disc_dark, 255))

        # ── Groove rings ─────────────────────────────────────────────────────
        groove_radii  = [r - 8, r - 38, r - 68, r - 98, r - 128]
        groove_alphas = [160, 110, 75, 50, 30]
        for i, (grad, alph) in enumerate(zip(groove_radii, groove_alphas)):
            if grad < 20:
                break
            draw.ellipse([cx - grad, cy - grad, cx + grad, cy + grad],
                         outline=(80, 80, 100, alph), width=2)

        # ── Centre label area ─────────────────────────────────────────────────
        label_r = 140
        if album_cover_path and Path(album_cover_path).exists():
            cover = _circle_crop(Image.open(album_cover_path), label_r * 2)
            canvas.paste(cover, (cx - label_r, cy - label_r), cover)
        else:
            # accent-coloured label circle
            draw.ellipse([cx - label_r, cy - label_r,
                          cx + label_r, cy + label_r],
                         fill=(*t["accent_color"], 240))
            sub_r   = 48
            sub_col = tuple(max(0, c - 55) for c in t["accent_color"])
            draw.ellipse([cx - sub_r, cy - sub_r, cx + sub_r, cy + sub_r],
                         fill=(*sub_col, 255))

        # ── Spindle hole ──────────────────────────────────────────────────────
        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12],
                     fill=(0, 0, 0, 0))

        # ── Marker dot so spin is visible ─────────────────────────────────────
        mk_r = r - 38
        draw.ellipse([cx + mk_r - 7, cy - 7, cx + mk_r + 7, cy + 7],
                     fill=(*t["accent_color"], 200))

    else:  # disc_dashed — circular album art + dashed ring
        # ── Album art circle ─────────────────────────────────────────────────
        art_r = r - 20
        if album_cover_path and Path(album_cover_path).exists():
            cover = _circle_crop(Image.open(album_cover_path), art_r * 2)
            canvas.paste(cover, (cx - art_r, cy - art_r), cover)
        else:
            disc_dark = t.get("disc_dark", (10, 10, 14))
            draw.ellipse([cx - art_r, cy - art_r, cx + art_r, cy + art_r],
                         fill=(*disc_dark, 255))
            # Minimal inner ring details
            for i, (rad, alph) in enumerate([(art_r - 18, 130), (art_r - 55, 80), (art_r - 92, 50)]):
                if rad < 20:
                    break
                draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                             outline=(*t["accent_color"], alph), width=2)
            # Centre accent dot
            draw.ellipse([cx - 28, cy - 28, cx + 28, cy + 28],
                         fill=(*t["accent_color"], 220))
            draw.ellipse([cx - 11, cy - 11, cx + 11, cy + 11],
                         fill=(0, 0, 0, 0))

        # ── Dashed orbit ring ────────────────────────────────────────────────
        dash_r    = r + 2
        dash_len  = 18
        gap_len   = 12
        step_deg  = math.degrees(math.atan2(dash_len + gap_len, dash_r))
        angle     = 0
        while angle < 360:
            x0 = cx + dash_r * math.cos(math.radians(angle))
            y0 = cy + dash_r * math.sin(math.radians(angle))
            a1 = angle + step_deg * (dash_len / (dash_len + gap_len))
            x1 = cx + dash_r * math.cos(math.radians(a1))
            y1 = cy + dash_r * math.sin(math.radians(a1))
            draw.line([(x0, y0), (x1, y1)],
                      fill=(*t["accent_color"], 160), width=2)
            angle += step_deg

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        output_path = tmp.name
        tmp.close()
    canvas.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Background / card renderer
# ---------------------------------------------------------------------------

def render_template_background(
    template_id: str,
    background_image_path: Optional[str] = None,
    output_path: Optional[str] = None,
    title: str = "",
    artist: str = "",
    album_cover_path: Optional[str] = None,
) -> str:
    """
    Render the static 1080×1920 background PNG.
    For rotating-disc templates (minimal/neon) the album art is NOT drawn here;
    it is composited by FFmpeg from disc.png.
    For vivid/inferno the album art is drawn directly into the card.
    """
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    canvas = Image.new("RGBA", (W, H), (*t["bg_top"], 255))
    draw   = ImageDraw.Draw(canvas)

    # ── Gradient background ──────────────────────────────────────────────────
    _gradient_bg(draw, t["bg_top"], t["bg_bot"])

    # ── Optional user background (blurred + darkened) ────────────────────────
    if background_image_path and Path(background_image_path).exists():
        bg = Image.open(background_image_path).convert("RGBA")
        ratio = bg.width / bg.height
        if ratio > W / H:
            new_h, new_w = H, int(ratio * H)
        else:
            new_w, new_h = W, int(W / ratio)
        bg  = bg.resize((new_w, new_h), Image.LANCZOS)
        xo  = (new_w - W) // 2
        yo  = (new_h - H) // 2
        bg  = bg.crop((xo, yo, xo + W, yo + H))
        bg  = bg.filter(ImageFilter.GaussianBlur(26))
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 160))
        canvas = Image.alpha_composite(bg, ov)
        draw   = ImageDraw.Draw(canvas)

    # ── Card ─────────────────────────────────────────────────────────────────
    card_fill = (*t["card_color"][:3], t["card_color"][3])
    _rounded_rect(draw, (CARD_X0, CARD_Y0, CARD_X1, CARD_Y1),
                  CARD_RADIUS, fill=card_fill)
    # Subtle card border
    border = t.get("card_border")
    if border:
        _rounded_rect(draw, (CARD_X0, CARD_Y0, CARD_X1, CARD_Y1),
                      CARD_RADIUS, outline=border, outline_width=1)

    art_style = t.get("art_style", "disc_vinyl")

    if art_style in ("disc_dashed", "disc_vinyl"):
        # Album art handled by the rotating disc overlay — just draw ambient glow
        gc = t.get("glow_color", t["accent_color"])
        _soft_glow(draw, ART_CX, ART_CY, ART_R, gc, layers=6)

    else:
        # ── Square album art (vivid / inferno) ───────────────────────────────
        art_size = ART_SQ
        ax0 = ART_CX - art_size // 2
        ay0 = ART_CY - art_size // 2
        ax1 = ax0 + art_size
        ay1 = ay0 + art_size
        art_radius = 28 if template_id == "vivid" else 16

        # Glow behind art
        gc = t.get("glow_color", t["accent_color"])
        for i in range(5, 0, -1):
            pad   = i * 14
            alpha = int(30 * (1 - i / 6))
            draw.rounded_rectangle(
                [ax0 - pad, ay0 - pad, ax1 + pad, ay1 + pad],
                radius=art_radius + pad // 2,
                fill=(*gc, alpha),
            )

        if album_cover_path and Path(album_cover_path).exists():
            cover = _square_crop(Image.open(album_cover_path), art_size)
            # Apply rounded mask
            mask = Image.new("L", (art_size, art_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, art_size, art_size], radius=art_radius, fill=255
            )
            cover_rgba = cover.convert("RGBA")
            canvas_chunk = Image.new("RGBA", (art_size, art_size), (0, 0, 0, 0))
            canvas_chunk.paste(cover_rgba, mask=mask)
            canvas = canvas.convert("RGBA")
            canvas.paste(canvas_chunk, (ax0, ay0), canvas_chunk)
            draw = ImageDraw.Draw(canvas)
        else:
            # Placeholder dark square
            art_dark = tuple(max(0, c - 10) for c in t["bg_top"])
            draw.rounded_rectangle(
                [ax0, ay0, ax1, ay1], radius=art_radius,
                fill=(*art_dark, 255),
            )
            # Vinyl + cover mockup in placeholder
            vc = ART_CX
            vr = ART_CY
            draw.ellipse([vc - 90, vr - 90, vc + 90, vr + 90],
                         fill=(20, 20, 28, 255))
            for rad, alph in [(82, 100), (55, 65), (28, 40)]:
                draw.ellipse([vc - rad, vr - rad, vc + rad, vr + rad],
                             outline=(*t["accent_color"], alph), width=2)
            draw.ellipse([vc - 18, vr - 18, vc + 18, vr + 18],
                         fill=(*t["accent_color"], 180))
            draw.ellipse([vc - 7, vr - 7, vc + 7, vr + 7],
                         fill=(0, 0, 0, 0))

    # ── "NOW PLAYING" label inside card ──────────────────────────────────────
    draw.text((W // 2, NP_Y), "NOW PLAYING",
              font=_font(20), fill=(*t["text_color"], 72), anchor="mm")

    # ── Progress bar track ────────────────────────────────────────────────────
    bar_bg = (*t["text_color"], 22)
    draw.rounded_rectangle(
        [BAR_X0, BAR_Y, BAR_X1, BAR_Y + BAR_H],
        radius=2, fill=bar_bg,
    )

    result = canvas.convert("RGB")
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        output_path = tmp.name
        tmp.close()
    result.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# ASS subtitle (karaoke)
# ---------------------------------------------------------------------------

def _seconds_to_ass(t: float) -> str:
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
    """ASS karaoke file.
    PrimaryColour  = white  (spoken/current)
    SecondaryColour= dark grey (upcoming, pre-karaoke)
    """
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    r, g, b = t["highlight_rgb"]
    accent_ass     = f"&H00{b:02X}{g:02X}{r:02X}&"
    white_ass      = "&H00FFFFFF&"
    dim_grey_ass   = "&H80808080&"   # upcoming words

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".ass", delete=False, mode="w", encoding="utf-8")
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
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Alignment 2 = bottom-centre; MarginV 320 px from bottom
        # Bold=1; Outline=4 + Shadow=2 for readability on any background
        f"Style: Karaoke,TikTok Sans,72,{white_ass},{dim_grey_ass},"
        "&H00000000&,&H90000000&,"
        "1,0,0,0,100,100,1,0,1,4,2,2,80,80,320,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text",
    ]

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
            # \kf = fill sweep (grey → white) for current word
            parts.append(f"{{\\kf{dur_cs}}}{w['word']}")
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
    album_cover_path: Optional[str] = None,
    title: str = "",
    artist: str = "",
) -> str:
    """Assemble the 9:16 MP4."""
    duration   = clip_end_s - clip_start_s
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

    needs_disc = template_id in ROTATING_TEMPLATES

    try:
        # 1 — background
        await asyncio.to_thread(
            render_template_background,
            template_id, background_image_path, bg_png,
            title, artist, album_cover_path,
        )

        # 2 — ASS karaoke
        await asyncio.to_thread(
            build_ass_lyrics, clip_words, duration, template_id, ass_file,
        )

        # 3 — build FFmpeg command
        t   = TEMPLATES.get(template_id, TEMPLATES["minimal"])
        r, g, b = t["bar_color"]
        bar_color_hex = f"{r:02x}{g:02x}{b:02x}ff"
        bar_w = BAR_X1 - BAR_X0

        ass_escaped = ass_file.replace("\\", "/")
        bar_expr = (
            f"drawbox=x={BAR_X0}:y={BAR_Y}:"
            f"w='({bar_w})*t/{duration:.3f}':h={BAR_H}:"
            f"c=0x{bar_color_hex}:t=fill"
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if needs_disc:
            disc_png = str(tmp_dir / "disc.png")
            await asyncio.to_thread(
                render_album_disc, template_id, album_cover_path, disc_png,
            )
            filter_complex = (
                f"[1:v]format=rgba,"
                f"rotate=2*PI*t/8:c=none:ow={DISC_CANVAS}:oh={DISC_CANVAS}[rot];"
                f"[0:v][rot]overlay={DISC_X}:{DISC_Y}[bgd];"
                f"[bgd]{bar_expr},ass={ass_escaped}[v]"
            )
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "30", "-i", bg_png,
                "-loop", "1", "-framerate", "30", "-i", disc_png,
                "-i", audio_clip_path,
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "2:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                output_path,
            ]
        else:
            filter_str = f"[0:v]{bar_expr},ass={ass_escaped}[v]"
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "30", "-i", bg_png,
                "-i", audio_clip_path,
                "-filter_complex", filter_str,
                "-map", "[v]", "-map", "1:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
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
        files = [bg_png, ass_file]
        if needs_disc:
            files.append(str(tmp_dir / "disc.png"))
        for f in files:
            try:
                os.unlink(f)
            except Exception:
                pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass

    return output_path
