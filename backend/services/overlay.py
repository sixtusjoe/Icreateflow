"""
Text overlay engine using Pillow.
Applies TikTok-style text overlays to slide images.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import textwrap

FONTS_DIR = Path(__file__).parent.parent.parent / "fonts"
TARGET_3x4 = (768, 1024)
TARGET_9x16 = (1080, 1920)


def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if font_path and Path(font_path).exists():
        return ImageFont.truetype(str(font_path), size)
    # Try default font in fonts dir
    default = FONTS_DIR / "Inter-Bold.ttf"
    if default.exists():
        return ImageFont.truetype(str(default), size)
    # Fallback to default
    return ImageFont.load_default()


def _draw_text_with_shadow(draw: ImageDraw.Draw, position: tuple, text: str,
                            font: ImageFont.FreeTypeFont, fill: str = "#FFFFFF",
                            shadow_color: str = "#000000", shadow_offset: int = 2):
    x, y = position
    # Draw shadow
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color)
    # Draw main text
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        if bbox[2] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def resize_to_3x4(img: Image.Image) -> Image.Image:
    """Resize and crop image to 3:4 (768x1024)."""
    target_w, target_h = TARGET_3x4
    target_ratio = target_w / target_h
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        # Image is wider — scale by height, crop width
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
    else:
        # Image is taller — scale by width, crop height
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    return img


def convert_3x4_to_9x16(img_3x4: Image.Image, bg_color: str = "#000000") -> Image.Image:
    """Convert a 3:4 image to 9:16 canvas for video."""
    target_w, target_h = TARGET_9x16

    # Scale 3:4 image to fill width
    scale = target_w / img_3x4.width
    new_w = target_w
    new_h = int(img_3x4.height * scale)
    scaled = img_3x4.resize((new_w, new_h), Image.LANCZOS)

    # Create 9:16 canvas
    canvas = Image.new("RGB", (target_w, target_h), bg_color)

    # Center vertically
    y_offset = (target_h - new_h) // 2
    canvas.paste(scaled, (0, y_offset))

    return canvas


def apply_hook_overlay(img: Image.Image, text: str,
                       font_path: str = None, font_size: int = 52,
                       text_color: str = "#FFFFFF", shadow_color: str = "#000000",
                       shadow_offset: int = 2) -> Image.Image:
    """Apply hook text overlay (slide 1 style — large centered text)."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    font = _load_font(font_path, font_size)

    max_width = int(img.width * 0.9)
    lines = _wrap_text(text, font, max_width)

    # Calculate total text height
    line_height = font.getbbox("Ay")[3] + 8
    total_height = line_height * len(lines)

    # Position: center-bottom area
    y_start = img.height - total_height - int(img.height * 0.15)

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (img.width - line_width) // 2
        y = y_start + i * line_height
        _draw_text_with_shadow(draw, (x, y), line, font, text_color, shadow_color, shadow_offset)

    return img


def apply_content_overlay(img: Image.Image, title: str, body: str,
                          font_path: str = None,
                          title_font_size: int = 44, body_font_size: int = 36,
                          text_color: str = "#FFFFFF", shadow_color: str = "#000000",
                          shadow_offset: int = 2) -> Image.Image:
    """Apply content overlay (numbered title + description body)."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    title_font = _load_font(font_path, title_font_size)
    body_font = _load_font(font_path, body_font_size)

    max_width = int(img.width * 0.9)
    margin_x = int(img.width * 0.05)

    # Wrap title and body
    title_lines = _wrap_text(title, title_font, max_width)
    body_lines = _wrap_text(body, body_font, max_width)

    title_line_h = title_font.getbbox("Ay")[3] + 8
    body_line_h = body_font.getbbox("Ay")[3] + 6

    total_height = (title_line_h * len(title_lines)) + 16 + (body_line_h * len(body_lines))

    # Position: center of image
    y_start = (img.height - total_height) // 2

    # Draw title
    y = y_start
    for line in title_lines:
        bbox = title_font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (img.width - line_width) // 2
        _draw_text_with_shadow(draw, (x, y), line, title_font, text_color, shadow_color, shadow_offset)
        y += title_line_h

    y += 16  # gap between title and body

    # Draw body
    for line in body_lines:
        bbox = body_font.getbbox(line)
        line_width = bbox[2] - bbox[0]
        x = (img.width - line_width) // 2
        _draw_text_with_shadow(draw, (x, y), line, body_font, text_color, shadow_color, shadow_offset)
        y += body_line_h

    return img


def apply_cta_overlay(img: Image.Image, title: str, body: str, cta: str,
                      font_path: str = None,
                      title_font_size: int = 44, body_font_size: int = 36,
                      cta_font_size: int = 40,
                      text_color: str = "#FFFFFF", shadow_color: str = "#000000",
                      shadow_offset: int = 2) -> Image.Image:
    """Apply CTA overlay (title + body + call-to-action line)."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    title_font = _load_font(font_path, title_font_size)
    body_font = _load_font(font_path, body_font_size)
    cta_font = _load_font(font_path, cta_font_size)

    max_width = int(img.width * 0.9)

    title_lines = _wrap_text(title, title_font, max_width)
    body_lines = _wrap_text(body, body_font, max_width)
    cta_lines = _wrap_text(cta, cta_font, max_width)

    title_line_h = title_font.getbbox("Ay")[3] + 8
    body_line_h = body_font.getbbox("Ay")[3] + 6
    cta_line_h = cta_font.getbbox("Ay")[3] + 8

    total_height = (
        title_line_h * len(title_lines) + 16 +
        body_line_h * len(body_lines) + 24 +
        cta_line_h * len(cta_lines)
    )

    y_start = (img.height - total_height) // 2

    # Title
    y = y_start
    for line in title_lines:
        bbox = title_font.getbbox(line)
        x = (img.width - (bbox[2] - bbox[0])) // 2
        _draw_text_with_shadow(draw, (x, y), line, title_font, text_color, shadow_color, shadow_offset)
        y += title_line_h

    y += 16

    # Body
    for line in body_lines:
        bbox = body_font.getbbox(line)
        x = (img.width - (bbox[2] - bbox[0])) // 2
        _draw_text_with_shadow(draw, (x, y), line, body_font, text_color, shadow_color, shadow_offset)
        y += body_line_h

    y += 24

    # CTA
    for line in cta_lines:
        bbox = cta_font.getbbox(line)
        x = (img.width - (bbox[2] - bbox[0])) // 2
        _draw_text_with_shadow(draw, (x, y), line, cta_font, text_color, shadow_color, shadow_offset)
        y += cta_line_h

    return img


def apply_overlay(image_path: str, slide_type: str, output_path: str,
                  title_text: str = None, body_text: str = None, cta_text: str = None,
                  font_path: str = None, bg_color: str = "#000000") -> dict:
    """
    Main entry point. Apply text overlay to a slide image and save.
    Returns paths to both 3:4 and 9:16 versions.
    """
    img = Image.open(image_path).convert("RGB")
    img_3x4 = resize_to_3x4(img)

    # Apply overlay based on type
    if slide_type == "hook":
        text = title_text or body_text or ""
        img_3x4 = apply_hook_overlay(img_3x4, text, font_path=font_path)
    elif slide_type == "content":
        img_3x4 = apply_content_overlay(
            img_3x4,
            title=title_text or "",
            body=body_text or "",
            font_path=font_path
        )
    elif slide_type == "cta":
        img_3x4 = apply_cta_overlay(
            img_3x4,
            title=title_text or "",
            body=body_text or "",
            cta=cta_text or "",
            font_path=font_path
        )

    # Save 3:4 version
    output_3x4 = Path(output_path)
    output_3x4.parent.mkdir(parents=True, exist_ok=True)
    img_3x4.save(str(output_3x4), "PNG")

    # Create and save 9:16 version
    img_9x16 = convert_3x4_to_9x16(img_3x4, bg_color)
    output_9x16 = output_3x4.parent / f"{output_3x4.stem}_9x16{output_3x4.suffix}"
    img_9x16.save(str(output_9x16), "PNG")

    return {
        "slide_3x4": str(output_3x4),
        "slide_9x16": str(output_9x16),
    }
