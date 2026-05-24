"""
Audio-to-Video generation service.

Four cinematic templates: minimal | neon | vivid | inferno

Pipeline per clip:
  1. Render 1080×1920 background PNG (Pillow):
       – full-screen blurred background image (or dark gradient)
       – heavy dark gradient overlay top+bottom, lighter in middle
       – template-specific colour tint
       – album art centred in upper 40 % of frame
         · minimal  → circular art + dashed orbit ring  (FFmpeg rotating overlay)
         · neon     → vinyl disc with album art centre   (FFmpeg rotating overlay)
         · vivid    → square art with rounded corners + pink glow
         · inferno  → large square art, slightly desaturated
  2. For minimal/neon: render rotating vinyl-disc as transparent RGBA PNG
  3. Build ASS karaoke subtitle file (Whisper word timestamps)
  4. FFmpeg assembly:
       – loop background PNG
       – (minimal/neon only) overlay rotating disc via `rotate` filter
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
# Template definitions  (match HTML OVERLAY_THEMES)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "minimal": {
        "bg_top":        (8, 10, 14),
        "bg_bot":        (18, 22, 32),
        "overlay_top":   (8, 10, 14),       # dark slate
        "accent_color":  (0, 255, 170),     # #00FFAA
        "highlight_rgb": (0, 255, 170),
        "text_color":    (255, 255, 255),
        "glow_color":    (0, 255, 170),
        "art_style":     "disc_dashed",
        "disc_dark":     (10, 10, 14),
    },
    "neon": {
        "bg_top":        (0, 0, 0),
        "bg_bot":        (0, 0, 0),
        "overlay_top":   (0, 0, 0),
        "accent_color":  (0, 220, 255),     # #00DCFF
        "highlight_rgb": (0, 220, 255),
        "text_color":    (210, 235, 255),
        "glow_color":    (0, 180, 220),
        "art_style":     "disc_vinyl",
        "disc_dark":     (8, 12, 22),
    },
    "vivid": {
        "bg_top":        (18, 0, 26),       # #12001a
        "bg_bot":        (18, 0, 26),
        "overlay_top":   (26, 0, 36),       # #1a0024
        "accent_color":  (255, 90, 200),    # #FF5AC8
        "highlight_rgb": (255, 90, 200),
        "text_color":    (255, 255, 255),
        "glow_color":    (210, 60, 200),
        "art_style":     "square",
        "disc_dark":     None,
    },
    "inferno": {
        "bg_top":        (10, 8, 8),
        "bg_bot":        (4, 3, 3),
        "overlay_top":   (10, 8, 8),
        "accent_color":  (240, 240, 240),
        "highlight_rgb": (255, 200, 100),
        "text_color":    (255, 255, 255),
        "glow_color":    (160, 140, 110),
        "art_style":     "square",
        "disc_dark":     None,
    },
}

ROTATING_TEMPLATES = {"minimal", "neon"}

W, H = 1080, 1920

# ── Layout ────────────────────────────────────────────────────────────────────
ART_CX      = W // 2               # 540 — horizontal centre
ART_CY      = int(H * 0.36)        # 691 — art centre at 36 % from top
ART_R       = 330                  # circular art radius
ART_SQ      = 680                  # square art side (vivid / inferno)

DISC_CANVAS = ART_R * 2 + 180      # 840 — PNG size with glow headroom
DISC_X      = ART_CX - DISC_CANVAS // 2   # 540 - 420 = 120
DISC_Y      = ART_CY - DISC_CANVAS // 2   # 691 - 420 = 271

FONTS_DIR       = Path(__file__).parent.parent / "fonts"
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


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def _square_crop(img: Image.Image, size: int) -> Image.Image:
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
               radius: int, color: tuple, layers: int = 8):
    for i in range(layers, 0, -1):
        rad   = radius + i * 14
        alpha = int(30 * (1 - i / (layers + 1)))
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=(*color[:3], alpha))


def _gradient_overlay(canvas: Image.Image, dark: tuple,
                      top_alpha: int, mid_alpha: int, bot_alpha: int,
                      mid_frac: float = 0.50) -> Image.Image:
    """
    Apply a vertical gradient overlay that darkens the top and bottom
    of the frame while leaving the middle lighter.
    """
    ov   = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)
    for y in range(H):
        frac = y / H
        if frac < mid_frac:
            ratio = frac / mid_frac
            alpha = int(top_alpha + (mid_alpha - top_alpha) * ratio)
        else:
            ratio = (frac - mid_frac) / (1.0 - mid_frac)
            alpha = int(mid_alpha + (bot_alpha - mid_alpha) * ratio)
        draw.line([(0, y), (W, y)], fill=(*dark[:3], alpha))
    return Image.alpha_composite(canvas.convert("RGBA"), ov)


# ---------------------------------------------------------------------------
# Disc renderer — minimal (dashed ring) & neon (vinyl)
# ---------------------------------------------------------------------------

def render_album_disc(
    template_id: str,
    album_cover_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Render the rotating disc as a transparent RGBA PNG."""
    t    = TEMPLATES.get(template_id, TEMPLATES["neon"])
    size = DISC_CANVAS
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(canvas)

    cx = cy = size // 2
    r  = ART_R

    art_style = t.get("art_style", "disc_vinyl")
    gc        = t.get("glow_color", t["accent_color"])

    # Outer glow
    for i in range(6, 0, -1):
        rad   = r + i * 12
        alpha = int(32 * (1 - i / 7))
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=(*gc[:3], alpha))

    if art_style == "disc_vinyl":
        disc_dark = t.get("disc_dark", (10, 10, 18))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     fill=(*disc_dark, 255))

        groove_radii  = [r - 8, r - 38, r - 68, r - 98, r - 128]
        groove_alphas = [160, 110, 75, 50, 30]
        for grad, alph in zip(groove_radii, groove_alphas):
            if grad < 20:
                break
            draw.ellipse([cx - grad, cy - grad, cx + grad, cy + grad],
                         outline=(80, 80, 100, alph), width=2)

        label_r = 130
        if album_cover_path and Path(album_cover_path).exists():
            cover = _circle_crop(Image.open(album_cover_path), label_r * 2)
            canvas.paste(cover, (cx - label_r, cy - label_r), cover)
        else:
            draw.ellipse([cx - label_r, cy - label_r,
                          cx + label_r, cy + label_r],
                         fill=(*t["accent_color"], 240))

        draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12],
                     fill=(0, 0, 0, 0))
        mk_r = r - 38
        draw.ellipse([cx + mk_r - 7, cy - 7, cx + mk_r + 7, cy + 7],
                     fill=(*t["accent_color"], 200))

    else:  # disc_dashed
        art_r = r - 16
        if album_cover_path and Path(album_cover_path).exists():
            cover = _circle_crop(Image.open(album_cover_path), art_r * 2)
            canvas.paste(cover, (cx - art_r, cy - art_r), cover)
        else:
            disc_dark = t.get("disc_dark", (10, 10, 14))
            draw.ellipse([cx - art_r, cy - art_r, cx + art_r, cy + art_r],
                         fill=(*disc_dark, 255))
            for rad, alph in [(art_r - 18, 130), (art_r - 55, 80), (art_r - 92, 50)]:
                if rad < 20:
                    break
                draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                             outline=(*t["accent_color"], alph), width=2)
            draw.ellipse([cx - 28, cy - 28, cx + 28, cy + 28],
                         fill=(*t["accent_color"], 220))
            draw.ellipse([cx - 11, cy - 11, cx + 11, cy + 11],
                         fill=(0, 0, 0, 0))

        dash_r   = r + 4
        dash_len = 18
        gap_len  = 12
        step_deg = math.degrees(math.atan2(dash_len + gap_len, dash_r))
        angle    = 0
        while angle < 360:
            x0 = cx + dash_r * math.cos(math.radians(angle))
            y0 = cy + dash_r * math.sin(math.radians(angle))
            a1 = angle + step_deg * (dash_len / (dash_len + gap_len))
            x1 = cx + dash_r * math.cos(math.radians(a1))
            y1 = cy + dash_r * math.sin(math.radians(a1))
            draw.line([(x0, y0), (x1, y1)],
                      fill=(*t["accent_color"], 160), width=3)
            angle += step_deg

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        output_path = tmp.name
        tmp.close()
    canvas.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Background renderer — full-screen immersive (matches HTML preview)
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

    Layout matches the HTML preview:
      – full-screen blurred background image (or solid dark gradient)
      – heavy dark gradient overlay: dark top, lighter middle, dark bottom
      – template colour tint (vivid: pink blobs; neon: cyan hint)
      – album art centred at ~36 % from top
        · minimal/neon: ambient glow only (disc handled by FFmpeg overlay)
        · vivid/inferno: rounded-square art with glow
    """
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])

    # ── Base solid colour ────────────────────────────────────────────────────
    canvas = Image.new("RGBA", (W, H), (*t["bg_top"], 255))

    # ── Full-screen background image ─────────────────────────────────────────
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
        bg  = bg.crop((xo, yo, xo + W, yo + H)).convert("RGBA")

        # Blur strength per template
        blur = 32 if template_id != "inferno" else 40
        bg   = bg.filter(ImageFilter.GaussianBlur(blur))

        # Inferno: push toward greyscale
        if template_id == "inferno":
            from PIL import ImageEnhance
            bg = ImageEnhance.Color(bg).enhance(0.25)

        canvas = bg

    # ── Gradient overlay (dark top + bottom, lighter middle) ─────────────────
    dark = t["overlay_top"]
    canvas = _gradient_overlay(canvas, dark,
                               top_alpha=210, mid_alpha=70, bot_alpha=220,
                               mid_frac=0.52)
    draw = ImageDraw.Draw(canvas)

    # ── Template-specific colour tints ────────────────────────────────────────
    if template_id == "vivid":
        tint = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td   = ImageDraw.Draw(tint)
        # Pink blob top-left
        td.ellipse([-260, -260, 560, 560], fill=(255, 90, 200, 55))
        # Purple blob bottom-right
        td.ellipse([640, 1480, 1380, 2220], fill=(130, 30, 255, 60))
        tint = tint.filter(ImageFilter.GaussianBlur(80))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), tint)
        draw   = ImageDraw.Draw(canvas)

    elif template_id == "neon":
        tint = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td   = ImageDraw.Draw(tint)
        td.ellipse([ART_CX - 420, ART_CY - 420,
                    ART_CX + 420, ART_CY + 420],
                   fill=(0, 220, 255, 14))
        tint = tint.filter(ImageFilter.GaussianBlur(60))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), tint)
        draw   = ImageDraw.Draw(canvas)

    # ── Album art ─────────────────────────────────────────────────────────────
    art_style = t.get("art_style", "disc_vinyl")

    if art_style in ("disc_dashed", "disc_vinyl"):
        # Rotating disc handled by FFmpeg — paint ambient glow only
        _soft_glow(draw, ART_CX, ART_CY, ART_R,
                   t.get("glow_color", t["accent_color"]), layers=8)

    else:
        # Square art (vivid / inferno)
        art_size = ART_SQ
        ax0 = ART_CX - art_size // 2
        ay0 = ART_CY - art_size // 2
        ax1 = ax0 + art_size
        ay1 = ay0 + art_size
        art_radius = 36

        gc = t.get("glow_color", t["accent_color"])
        for i in range(7, 0, -1):
            pad   = i * 18
            alpha = int(28 * (1 - i / 8))
            draw.rounded_rectangle(
                [ax0 - pad, ay0 - pad, ax1 + pad, ay1 + pad],
                radius=art_radius + pad // 2, fill=(*gc[:3], alpha),
            )

        if album_cover_path and Path(album_cover_path).exists():
            cover = _square_crop(Image.open(album_cover_path), art_size)
            mask  = Image.new("L", (art_size, art_size), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, art_size, art_size], radius=art_radius, fill=255
            )
            chunk = Image.new("RGBA", (art_size, art_size), (0, 0, 0, 0))
            chunk.paste(cover.convert("RGBA"), mask=mask)
            canvas = canvas.convert("RGBA")
            canvas.paste(chunk, (ax0, ay0), chunk)
            draw = ImageDraw.Draw(canvas)
        else:
            draw.rounded_rectangle(
                [ax0, ay0, ax1, ay1], radius=art_radius,
                fill=(*t["bg_top"], 255),
            )
            _soft_glow(draw, ART_CX, ART_CY, 140,
                       gc, layers=5)

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
    """ASS karaoke file — \kf sweep highlights each word in accent colour."""
    t = TEMPLATES.get(template_id, TEMPLATES["minimal"])
    r, g, b    = t["highlight_rgb"]
    accent_ass = f"&H00{b:02X}{g:02X}{r:02X}&"
    white_ass  = "&H00FFFFFF&"
    dim_ass    = "&H80808080&"

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
        # Alignment 2 = bottom-centre; MarginV 300 px from bottom
        # Fontsize 78; Bold; Outline 4 + Shadow 2 for readability
        f"Style: Karaoke,TikTok Sans,78,{white_ass},{dim_ass},"
        "&H00000000&,&HA0000000&,"
        "1,0,0,0,100,100,2,0,1,4,2,2,80,80,300,1",
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
            w_start  = w["start_s"] + KARAOKE_DELAY_S
            w_end    = w["end_s"]   + KARAOKE_DELAY_S
            dur_cs   = max(1, int((w_end - w_start) * 100))
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
        await asyncio.to_thread(
            render_template_background,
            template_id, background_image_path, bg_png,
            title, artist, album_cover_path,
        )
        await asyncio.to_thread(
            build_ass_lyrics, clip_words, duration, template_id, ass_file,
        )

        ass_escaped = ass_file.replace("\\", "/")
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
                f"[bgd]ass={ass_escaped}[v]"
            )
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "30", "-i", bg_png,
                "-loop", "1", "-framerate", "30", "-i", disc_png,
                "-i", audio_clip_path,
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "2:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                output_path,
            ]
        else:
            filter_str = f"[0:v]ass={ass_escaped}[v]"
            cmd = [
                "ffmpeg", "-loglevel", "error", "-y",
                "-loop", "1", "-framerate", "30", "-i", bg_png,
                "-i", audio_clip_path,
                "-filter_complex", filter_str,
                "-map", "[v]", "-map", "1:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
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
