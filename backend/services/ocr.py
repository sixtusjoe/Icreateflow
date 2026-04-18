"""
OCR text extraction from slide images using Claude Vision API.
Claude understands context — it can distinguish TikTok overlay text
from product labels, brand names, and background text.
"""
from pathlib import Path
import re
import os
import base64
import json
import urllib.request


def _get_api_key() -> str | None:
    """Get Claude/Anthropic API key from environment (caller should fetch from DB)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    return api_key or None


class OCRError(Exception):
    """Raised when the OCR service itself fails (bad key, API down, etc.)."""
    pass


def extract_text_from_image(image_path: str, api_key: str | None = None) -> str:
    """Extract overlay text from a slide image using Claude Vision."""
    api_key = api_key or _get_api_key()
    if not api_key:
        print(f"[OCR] No Anthropic API key configured — skipping OCR for {image_path}")
        return ""

    return _extract_with_claude(image_path, api_key)


def _extract_with_claude(image_path: str, api_key: str) -> str:
    """Use Claude Vision API to extract overlay text from a TikTok slide."""
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Detect media type
        ext = Path(image_path).suffix.lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        media_type = media_types.get(ext, "image/jpeg")

        prompt = """Look at this TikTok slideshow image. Extract ONLY the main overlay text that was added on top of the image by the content creator.

Rules:
- ONLY extract the large, prominent overlay text (the text the creator typed/added as captions)
- IGNORE all product labels, brand names printed on products, packaging text, small text on items
- IGNORE any watermarks or social media handles
- IGNORE text that is part of the background/scene (store signs, etc.)
- The overlay text is typically large, bold, centered, and has a shadow or outline

Return the text in this exact format:
TITLE: [the main overlay text, exactly as written]
BODY: [any secondary/smaller overlay text if present, otherwise leave empty]
CTA: [any call-to-action overlay text like "Search X on google" if present, otherwise leave empty]

If there is no overlay text, return:
TITLE:
BODY:
CTA:"""

        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ]
            }]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())

        # Extract text from response
        content = result.get("content", [])
        if not content:
            return ""

        response_text = content[0].get("text", "")
        return _parse_claude_response(response_text)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore") if e.fp else ""
        print(f"[OCR] Claude Vision HTTP {e.code} for {image_path}: {body[:200]}")
        if e.code in (401, 403):
            raise OCRError(f"Anthropic API key rejected ({e.code}) — check the key in Settings") from e
        if e.code == 429:
            raise OCRError("Anthropic API rate-limit hit — try again in a moment") from e
        raise OCRError(f"Claude Vision error {e.code}") from e
    except Exception as e:
        print(f"[OCR] Claude Vision error for {image_path}: {e}")
        raise OCRError(str(e)) from e


def _parse_claude_response(response: str) -> str:
    """Parse Claude's structured response into our marker format."""
    title = ""
    body = ""
    cta = ""

    for line in response.split("\n"):
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("BODY:"):
            body = line[5:].strip()
        elif line.upper().startswith("CTA:"):
            cta = line[4:].strip()

    parts = []
    if title:
        parts.append(f"|||TITLE|||{title}")
    if body:
        parts.append(f"|||BODY|||{body}")
    if cta:
        parts.append(f"|||CTA|||{cta}")

    return "\n".join(parts) if parts else ""




def extract_slide_texts(slide_paths: list[str], api_key: str | None = None) -> list[dict]:
    """
    Extract and parse text from a list of slide images.
    Returns list of dicts with slide_number, raw_text, type, title_text, body_text, cta_text, has_face.
    Raises OCRError if the API call itself fails (bad key, rate-limit, etc.).
    """
    results = []

    for i, path in enumerate(slide_paths):
        raw_text = extract_text_from_image(path, api_key=api_key)
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
    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]

    title_parts = []
    body_parts = []
    cta_parts = []
    plain_lines = []

    for line in raw_lines:
        if line.startswith("|||TITLE|||"):
            cleaned = line[len("|||TITLE|||"):].strip()
            if cleaned:
                title_parts.append(cleaned)
                plain_lines.append(cleaned)
        elif line.startswith("|||BODY|||"):
            cleaned = line[len("|||BODY|||"):].strip()
            if cleaned:
                body_parts.append(cleaned)
                plain_lines.append(cleaned)
        elif line.startswith("|||CTA|||"):
            cleaned = line[len("|||CTA|||"):].strip()
            if cleaned:
                cta_parts.append(cleaned)
                plain_lines.append(cleaned)
        else:
            plain_lines.append(line)

    if not plain_lines:
        slide_type = "cta" if is_last else ("hook" if slide_number == 1 else "content")
        return {"type": slide_type, "title_text": "", "body_text": "", "cta_text": ""}

    full_text = " ".join(plain_lines).lower()

    cta_keywords = ["search", "grab yours", "link in bio", "shop now", "get yours",
                    "buy now", "order now", "check out", "available at", "use code",
                    "try ", "get it", "click", "tap ", "swipe"]
    has_cta = any(kw in full_text for kw in cta_keywords) or bool(cta_parts)

    has_number = bool(re.search(r'^\d+[#.]|^#\d+', plain_lines[0] if plain_lines else ""))

    if is_last or has_cta:
        slide_type = "cta"
    elif slide_number == 1 and not has_number:
        slide_type = "hook"
    else:
        slide_type = "content"

    # If Claude gave us structured |||CTA||| markers, use them directly
    if cta_parts or title_parts or body_parts:
        title = " ".join(title_parts)
        body = " ".join(body_parts)
        cta = " ".join(cta_parts)

        # If CTA was detected in title/body but not in |||CTA|||, check keywords
        if not cta and slide_type == "cta":
            for part in (body_parts + title_parts):
                if any(kw in part.lower() for kw in cta_keywords):
                    cta = part
                    if part in title_parts:
                        title_parts = [p for p in title_parts if p != part]
                        title = " ".join(title_parts)
                    elif part in body_parts:
                        body_parts = [p for p in body_parts if p != part]
                        body = " ".join(body_parts)
                    break

        return {
            "type": slide_type,
            "title_text": title or " ".join(plain_lines),
            "body_text": body,
            "cta_text": cta,
        }

    # Fallback: no markers
    if slide_type == "hook":
        return {"type": "hook", "title_text": " ".join(plain_lines), "body_text": "", "cta_text": ""}
    elif slide_type == "content":
        title_lines = []
        body_lines = []
        found_body = False
        for line in plain_lines:
            if not found_body and (re.match(r'^\d+[#.]|^#\d+', line) or not body_lines):
                title_lines.append(line)
                if re.match(r'^\d+[#.]|^#\d+', line):
                    found_body = True
            else:
                body_lines.append(line)
        if title_lines and not body_lines and len(title_lines) > 1:
            body_lines = title_lines[1:]
            title_lines = [title_lines[0]]
        return {"type": "content", "title_text": " ".join(title_lines), "body_text": " ".join(body_lines), "cta_text": ""}
    else:
        cta_line = ""
        other_lines = []
        for line in plain_lines:
            if any(kw in line.lower() for kw in cta_keywords):
                cta_line = line
            else:
                other_lines.append(line)
        title = other_lines[0] if other_lines else ""
        body = " ".join(other_lines[1:]) if len(other_lines) > 1 else ""
        return {"type": "cta", "title_text": title, "body_text": body, "cta_text": cta_line}
