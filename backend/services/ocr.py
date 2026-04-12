"""
OCR text extraction from slide images using Google Cloud Vision API.
Filters for large overlay text (TikTok-style), ignoring small background text.
"""
from pathlib import Path
import re
import os
import base64
import json
import urllib.request


def _get_api_key() -> str | None:
    """Get Google Vision API key from settings DB or environment."""
    api_key = os.environ.get("GOOGLE_VISION_API_KEY")
    if api_key:
        return api_key
    try:
        import sqlite3
        db_path = Path(__file__).parent.parent / "zagged.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT value FROM settings WHERE key = 'google_vision_api_key'").fetchone()
            conn.close()
            if row and row["value"]:
                return row["value"]
    except Exception:
        pass
    return None


def extract_text_from_image(image_path: str) -> str:
    """Extract overlay text from a slide image using Google Cloud Vision API."""
    api_key = _get_api_key()
    if not api_key:
        print(f"[OCR] No Google Vision API key configured — skipping OCR for {image_path}")
        return ""

    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Use DOCUMENT_TEXT_DETECTION for structured output with bounding boxes
        body = json.dumps({
            "requests": [{
                "image": {"content": image_data},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}]
            }]
        }).encode("utf-8")

        req = urllib.request.Request(
            f"https://vision.googleapis.com/v1/images:annotate?key={api_key}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())

        response = result.get("responses", [{}])[0]
        full_annotation = response.get("fullTextAnnotation")
        if not full_annotation:
            return ""

        # Get image dimensions from the first page
        pages = full_annotation.get("pages", [])
        if not pages:
            return full_annotation.get("text", "").strip()

        page = pages[0]
        img_width = page.get("width", 1080)
        img_height = page.get("height", 1440)

        # Extract blocks with their bounding boxes and text
        overlay_lines = []

        for block in page.get("blocks", []):
            block_text = _extract_block_text(block)
            if not block_text.strip():
                continue

            # Get bounding box
            vertices = block.get("boundingBox", {}).get("vertices", [])
            if len(vertices) < 4:
                continue

            # Calculate block dimensions
            xs = [v.get("x", 0) for v in vertices]
            ys = [v.get("y", 0) for v in vertices]
            block_width = max(xs) - min(xs)
            block_height = max(ys) - min(ys)
            block_left = min(xs)
            block_right = max(xs)

            # Calculate what % of image width this block spans
            width_ratio = block_width / img_width if img_width else 0
            # Character height relative to image
            height_ratio = block_height / img_height if img_height else 0

            # Filter criteria for overlay text:
            # 1. Must span a reasonable width (overlay text is usually wide, centered)
            #    At least 20% of image width
            # 2. Must be reasonably sized text (not tiny product labels)
            #    Block height should be meaningful
            # 3. Should be somewhat centered (not edge product text)
            center_x = (min(xs) + max(xs)) / 2
            center_ratio = center_x / img_width if img_width else 0.5

            # Estimate font size from block height and line count
            line_count = max(1, block_text.count("\n") + 1)
            char_height = block_height / line_count

            # Large overlay text: wide blocks OR tall characters
            is_overlay = (
                (width_ratio > 0.25 and char_height > img_height * 0.02) or  # Wide + decent size
                (char_height > img_height * 0.04) or  # Very large characters
                (width_ratio > 0.5)  # Very wide block
            )

            # Filter out likely noise
            is_noise = (
                width_ratio < 0.1 or  # Very narrow
                _is_gibberish(block_text) or  # Non-latin garbage
                (block_height < img_height * 0.015 and width_ratio < 0.3)  # Tiny text
            )

            if is_overlay and not is_noise:
                # Score by size — larger text = more important
                score = width_ratio * char_height
                overlay_lines.append((score, min(ys), block_text.strip()))

        if not overlay_lines:
            # Fallback: return full text but cleaned
            return _clean_text(full_annotation.get("text", ""))

        # Sort by vertical position (top to bottom)
        overlay_lines.sort(key=lambda x: x[1])

        # Join the overlay text
        text = "\n".join(line[2] for line in overlay_lines)
        return _clean_text(text)

    except Exception as e:
        print(f"[OCR] Google Vision error for {image_path}: {e}")
        return ""


def _extract_block_text(block: dict) -> str:
    """Extract text from a Vision API block."""
    lines = []
    for paragraph in block.get("paragraphs", []):
        words = []
        for word in paragraph.get("words", []):
            chars = ""
            for symbol in word.get("symbols", []):
                chars += symbol.get("text", "")
            words.append(chars)
        lines.append(" ".join(words))
    return "\n".join(lines)


def _is_gibberish(text: str) -> bool:
    """Check if text is mostly non-English/gibberish."""
    if not text:
        return True
    # Count latin letters vs non-latin/special
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    non_latin = sum(1 for c in text if not c.isascii() and c.isalpha())
    total_alpha = latin + non_latin
    if total_alpha == 0:
        return True
    # If more than 30% non-latin, likely product label in another language
    if non_latin / total_alpha > 0.3:
        return True
    return False


def _clean_text(text: str) -> str:
    """Clean OCR text — remove noise lines."""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip very short lines that are likely noise
        if len(stripped) <= 2 and not stripped[0].isdigit():
            continue
        # Skip lines that are mostly special characters
        alpha = sum(1 for c in stripped if c.isalpha() or c.isspace())
        if len(stripped) > 0 and alpha / len(stripped) < 0.4:
            continue
        lines.append(stripped)
    return "\n".join(lines)


def extract_slide_texts(slide_paths: list[str]) -> list[dict]:
    """
    Extract and parse text from a list of slide images.
    Returns list of dicts with slide_number, raw_text, type, title_text, body_text, cta_text, has_face.
    """
    results = []

    for i, path in enumerate(slide_paths):
        raw_text = extract_text_from_image(path)
        slide_num = i + 1
        is_last = (i == len(slide_paths) - 1)

        parsed = _parse_slide_text(raw_text, slide_num, is_last)
        parsed["slide_number"] = slide_num
        parsed["raw_text"] = raw_text
        parsed["has_face"] = False

        results.append(parsed)

    return results


def _parse_slide_text(text: str, slide_number: int, is_last: bool) -> dict:
    """Parse extracted text into structured fields."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if not lines:
        slide_type = "cta" if is_last else ("hook" if slide_number == 1 else "content")
        return {
            "type": slide_type,
            "title_text": "",
            "body_text": "",
            "cta_text": "",
        }

    full_text = " ".join(lines).lower()

    cta_keywords = ["search", "grab yours", "link in bio", "shop now", "get yours",
                    "buy now", "order now", "check out", "available at", "use code",
                    "try ", "get it", "click", "tap ", "swipe"]
    has_cta = any(kw in full_text for kw in cta_keywords)

    has_number = bool(re.search(r'^\d+[#.]|^#\d+', lines[0] if lines else ""))

    if is_last or has_cta:
        slide_type = "cta"
    elif slide_number == 1 and not has_number:
        slide_type = "hook"
    else:
        slide_type = "content"

    if slide_type == "hook":
        return {
            "type": "hook",
            "title_text": " ".join(lines),
            "body_text": "",
            "cta_text": "",
        }
    elif slide_type == "content":
        title_lines = []
        body_lines = []
        found_body = False
        for line in lines:
            if not found_body and (re.match(r'^\d+[#.]|^#\d+', line) or not body_lines):
                title_lines.append(line)
                if re.match(r'^\d+[#.]|^#\d+', line):
                    found_body = True
            else:
                body_lines.append(line)

        if title_lines and not body_lines and len(title_lines) > 1:
            title = title_lines[0]
            body_lines = title_lines[1:]
            title_lines = [title]

        return {
            "type": "content",
            "title_text": " ".join(title_lines),
            "body_text": " ".join(body_lines),
            "cta_text": "",
        }
    else:
        cta_line = ""
        other_lines = []
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in cta_keywords):
                cta_line = line
            else:
                other_lines.append(line)

        title = other_lines[0] if other_lines else ""
        body = " ".join(other_lines[1:]) if len(other_lines) > 1 else ""

        return {
            "type": "cta",
            "title_text": title,
            "body_text": body,
            "cta_text": cta_line,
        }
