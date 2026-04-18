"""
Text overlay engine using Pillow.
Applies TikTok-style text overlays to slide images.
Uses TikTok Sans (official open-source font from Google Fonts)
with configurable weight (Light → Black) and two text styles:
  - "stroke": white fill + black stroke outline
  - "background": white text on semi-transparent dark rounded rect
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

FONTS_DIR = Path(__file__).parent.parent / "fonts"
TARGET_3x4 = (768, 1024)
TARGET_9x16 = (1080, 1920)

# Available font weights for TikTok Sans variable font
FONT_WEIGHTS = [
    "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"
]
DEFAULT_WEIGHT = "Bold"

# Text styles
TEXT_STYLES = ["stroke", "background"]


def _load_font(size: int, weight: str = DEFAULT_WEIGHT) -> ImageFont.FreeTypeFont:
    """Load TikTok Sans at the given size and weight."""
    font_path = FONTS_DIR / "TikTokSans-Variable.ttf"
    if font_path.exists():
        font = ImageFont.truetype(str(font_path), size)
        if weight in FONT_WEIGHTS:
            try:
                font.set_variation_by_name(weight)
            except Exception:
                pass  # Fallback to default weight
        return font
    # Fallback
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text_lines(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text into lines that fit within max_width pixels."""
    if not text:
        return []

    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def _get_line_height(font: ImageFont.FreeTypeFont) -> int:
    """Get consistent line height for a font."""
    bbox = font.getbbox("Ayg")
    return int((bbox[3] - bbox[1]) * 1.3)


def _draw_stroke_text(draw: ImageDraw.Draw, x_center: int, y_center: int,
                      text: str, font: ImageFont.FreeTypeFont,
                      stroke_width: int = 4):
    """Draw TikTok-style text with white fill + black stroke outline at given center point."""
    draw.text(
        (x_center, y_center),
        text,
        font=font,
        fill="white",
        stroke_width=stroke_width,
        stroke_fill="black",
        anchor="mm",
        align="center",
    )


def _draw_background_text(img: Image.Image, x_center: int, y_center: int,
                          text: str, font: ImageFont.FreeTypeFont,
                          line_height: int):
    """Draw white text on a semi-transparent dark rounded rect background."""
    # Measure text
    bbox = font.getbbox(text, anchor="mm")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_x, pad_y = 16, 8
    rect_w = text_w + pad_x * 2
    rect_h = line_height + pad_y * 2
    rx = int(rect_h * 0.35)  # Corner radius

    rect_x = int(x_center - rect_w / 2)
    rect_y = y_center - rect_h // 2

    # Create overlay for semi-transparent background
    overlay_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay_img)
    overlay_draw.rounded_rectangle(
        [rect_x, rect_y, rect_x + rect_w, rect_y + rect_h],
        radius=rx,
        fill=(0, 0, 0, 170),  # ~65% opacity
    )
    # Composite
    if img.mode != "RGBA":
        img_rgba = img.convert("RGBA")
    else:
        img_rgba = img
    composited = Image.alpha_composite(img_rgba, overlay_img)

    # Draw text on top
    draw = ImageDraw.Draw(composited)
    draw.text(
        (x_center, y_center),
        text,
        font=font,
        fill="white",
        anchor="mm",
        align="center",
    )

    return composited


def resize_to_3x4(img: Image.Image) -> Image.Image:
    """Resize and crop image to 3:4 (768x1024)."""
    target_w, target_h = TARGET_3x4
    target_ratio = target_w / target_h
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
    else:
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    return img


def convert_3x4_to_9x16(img_3x4: Image.Image, bg_color: str = "#000000") -> Image.Image:
    """Convert a 3:4 image to 9:16 canvas for video."""
    target_w, target_h = TARGET_9x16

    # Ensure RGB mode for the canvas
    if img_3x4.mode == "RGBA":
        img_3x4 = img_3x4.convert("RGB")

    scale = target_w / img_3x4.width
    new_w = target_w
    new_h = int(img_3x4.height * scale)
    scaled = img_3x4.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    y_offset = (target_h - new_h) // 2
    canvas.paste(scaled, (0, y_offset))

    return canvas


def _apply_text_block(img: Image.Image, texts: list[dict],
                      weight: str = DEFAULT_WEIGHT,
                      text_style: str = "stroke") -> Image.Image:
    """Apply multiple text blocks to an image.

    Each text dict:
      - text: str
      - font_size: int (exact pixel size — NOT touched by scale)
      - y_ratio: float 0.0 (top) → 1.0 (bottom) — where to center vertically
      - x_ratio: float 0.0 (far left) → 1.0 (far right) — where to center horizontally (default 0.5)
      - scale: float — visual zoom applied to the rendered layer via image resize
               (mirrors CSS `transform: scale()` — font_size stays the same)

    weight: Font weight name (Light, Regular, ..., Black)
    text_style: "stroke" (white text + black outline) or "background" (white text on dark rect)
    """
    img = img.copy()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    max_text_width = int(img.width * 0.88)

    for block in texts:
        text = block.get("text", "").strip()
        if not text:
            continue

        font_size = int(block.get("font_size", 52))          # exact, unmodified
        scale = float(block.get("scale", 1.0))
        y_ratio = block.get("y_ratio", 0.35)
        x_ratio = block.get("x_ratio", 0.5)
        stroke_width = max(3, font_size // 14)

        font = _load_font(font_size, weight)
        lines = _wrap_text_lines(text, font, max_text_width)
        line_height = _get_line_height(font)
        total_height = line_height * len(lines)

        # Render the text block onto its own transparent RGBA layer at exact font_size,
        # then resize the layer by `scale` and paste at the anchor point. This gives
        # true zoom-scale semantics (strokes and padding scale proportionally) and
        # keeps the font_size slider value untouched.

        # Compute a tight canvas size for the block. Width == max_text_width is a
        # safe upper bound because lines already fit within it.
        layer_w = max_text_width
        layer_h = total_height + stroke_width * 2 + 8
        layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)

        if text_style == "background":
            for i, line in enumerate(lines):
                y_center_local = i * line_height + line_height // 2 + stroke_width
                # Draw per-line background box + text on the layer
                bbox = font.getbbox(line, anchor="mm")
                text_w = bbox[2] - bbox[0]
                pad_x, pad_y = 16, 8
                rect_w = text_w + pad_x * 2
                rect_h = line_height + pad_y * 2
                rx = int(rect_h * 0.35)
                rect_x = (layer_w - rect_w) // 2
                rect_y = y_center_local - rect_h // 2
                layer_draw.rounded_rectangle(
                    [rect_x, rect_y, rect_x + rect_w, rect_y + rect_h],
                    radius=rx,
                    fill=(0, 0, 0, 170),
                )
                layer_draw.text(
                    (layer_w / 2, y_center_local),
                    line, font=font, fill="white",
                    anchor="mm", align="center",
                )
        else:
            for i, line in enumerate(lines):
                y_center_local = i * line_height + line_height // 2 + stroke_width
                layer_draw.text(
                    (layer_w / 2, y_center_local),
                    line, font=font, fill="white",
                    stroke_width=stroke_width, stroke_fill="black",
                    anchor="mm", align="center",
                )

        # Apply zoom by resizing the entire rendered layer (CSS transform:scale equivalent).
        if abs(scale - 1.0) > 0.001:
            new_w = max(1, int(round(layer_w * scale)))
            new_h = max(1, int(round(layer_h * scale)))
            layer = layer.resize((new_w, new_h), Image.LANCZOS)
        else:
            new_w, new_h = layer_w, layer_h

        # Paste layer centered at (x_ratio, y_ratio).
        anchor_x = int(img.width * x_ratio)
        anchor_y = int(img.height * y_ratio)
        paste_x = anchor_x - new_w // 2
        paste_y = anchor_y - new_h // 2
        img.alpha_composite(layer, dest=(paste_x, paste_y))

    return img.convert("RGB")


def apply_overlay(image_path: str, slide_type: str, output_path: str,
                  title_text: str = None, body_text: str = None, cta_text: str = None,
                  bg_color: str = "#000000", weight: str = DEFAULT_WEIGHT,
                  text_style: str = "stroke") -> dict:
    """
    Main entry point. Apply text overlay to a slide image.

    Layout varies by slide type:
    - hook: Single large text block, upper-center area
    - content: Title (larger) + body (smaller) if present
    - cta: Title + body + CTA text at bottom
    """
    img = Image.open(image_path).convert("RGB")
    img_3x4 = resize_to_3x4(img)

    texts = []

    if slide_type == "hook":
        text = title_text or body_text or ""
        if text:
            texts.append({"text": text, "font_size": 56, "y_ratio": 0.30})

    elif slide_type == "content":
        title = title_text or ""
        body = body_text or ""

        if title and body:
            texts.append({"text": title, "font_size": 52, "y_ratio": 0.28})
            texts.append({"text": body, "font_size": 38, "y_ratio": 0.48})
        elif title:
            texts.append({"text": title, "font_size": 52, "y_ratio": 0.35})
        elif body:
            texts.append({"text": body, "font_size": 44, "y_ratio": 0.35})

    elif slide_type == "cta":
        title = title_text or ""
        body = body_text or ""
        cta = cta_text or ""

        if title and cta:
            texts.append({"text": title, "font_size": 48, "y_ratio": 0.25})
            if body:
                texts.append({"text": body, "font_size": 34, "y_ratio": 0.45})
            texts.append({"text": cta, "font_size": 42, "y_ratio": 0.75})
        elif title:
            texts.append({"text": title, "font_size": 48, "y_ratio": 0.30})
            if body:
                texts.append({"text": body, "font_size": 36, "y_ratio": 0.50})
        elif cta:
            texts.append({"text": cta, "font_size": 44, "y_ratio": 0.70})

    if texts:
        img_3x4 = _apply_text_block(img_3x4, texts, weight=weight, text_style=text_style)

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
