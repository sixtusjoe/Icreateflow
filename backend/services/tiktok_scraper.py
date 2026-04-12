"""
TikTok slide downloader.
Downloads individual slide images from a TikTok photo carousel post URL.
"""
import re
import json
import httpx
from pathlib import Path


async def download_tiktok_slides(tiktok_url: str, output_dir: str) -> dict:
    """
    Download slides from a TikTok photo carousel post.

    Returns dict with: slides (list of paths), sound_id, caption
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    slides = []
    sound_id = None
    caption = ""

    try:
        # Resolve short URLs and fetch the page
        resolved_url = await _resolve_url(tiktok_url)

        # Extract post ID from URL
        post_id_match = re.search(r'/(?:photo|video)/(\d+)', resolved_url)
        if not post_id_match:
            post_id_match = re.search(r'/(\d+)', resolved_url)

        # Fetch the page with mobile user agent to get JSON data
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        ) as client:
            resp = await client.get(resolved_url)
            html = resp.text

            # Extract JSON data from various script patterns TikTok uses
            image_urls = []

            # Pattern 1: __UNIVERSAL_DATA_FOR_REHYDRATION__
            match = re.search(
                r'<script\s+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    image_urls, caption, sound_id = _extract_from_universal_data(data)
                except (json.JSONDecodeError, KeyError):
                    pass

            # Pattern 2: SIGI_STATE
            if not image_urls:
                match = re.search(
                    r'<script\s+id="SIGI_STATE"[^>]*>(.*?)</script>',
                    html, re.DOTALL
                )
                if match:
                    try:
                        data = json.loads(match.group(1))
                        image_urls, caption, sound_id = _extract_from_sigi_state(data)
                    except (json.JSONDecodeError, KeyError):
                        pass

            # Pattern 3: Brute force find image URLs from TikTok CDN
            if not image_urls:
                # Look for high-quality image URLs from TikTok's CDN
                cdn_patterns = [
                    r'(https?://p\d+-sign[^"\'\\\s]+\.(?:jpeg|jpg|png|webp)[^"\'\\\s]*)',
                    r'(https?://[^"\'\\\s]*tiktokcdn[^"\'\\\s]*\.(?:jpeg|jpg|png|webp)[^"\'\\\s]*)',
                    r'(https?://[^"\'\\\s]*muscdn[^"\'\\\s]*\.(?:jpeg|jpg|png|webp)[^"\'\\\s]*)',
                ]
                for pattern in cdn_patterns:
                    found = re.findall(pattern, html)
                    for url in found:
                        # Clean up escaped characters
                        clean_url = url.replace('\\u002F', '/').replace('\\/', '/')
                        # Filter out thumbnails and small images
                        if 'thumbnail' not in clean_url.lower() and 'avatar' not in clean_url.lower():
                            image_urls.append(clean_url)

                # Deduplicate
                seen = set()
                unique = []
                for u in image_urls:
                    # Normalize URL for dedup (strip query params)
                    base = u.split('?')[0]
                    if base not in seen:
                        seen.add(base)
                        unique.append(u)
                image_urls = unique

            # Download the images
            for i, url in enumerate(image_urls):
                try:
                    img_resp = await client.get(url)
                    if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                        content_type = img_resp.headers.get("content-type", "")
                        if "png" in content_type:
                            ext = "png"
                        elif "webp" in content_type:
                            ext = "webp"
                        else:
                            ext = "jpg"
                        path = out / f"slide_{i + 1:02d}.{ext}"
                        path.write_bytes(img_resp.content)
                        slides.append(str(path))
                except Exception:
                    continue

    except Exception as e:
        print(f"TikTok scraper error: {e}")

    return {
        "slides": slides,
        "sound_id": sound_id,
        "caption": caption,
    }


def _extract_from_universal_data(data: dict) -> tuple[list[str], str, str | None]:
    """Extract image URLs from __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON."""
    image_urls = []
    caption = ""
    sound_id = None

    # Navigate the nested structure
    default_scope = data.get("__DEFAULT_SCOPE__", {})
    webapp_detail = default_scope.get("webapp.video-detail", {})
    item_info = webapp_detail.get("itemInfo", {}).get("itemStruct", {})

    if not item_info:
        # Try alternative path
        for key in default_scope:
            val = default_scope[key]
            if isinstance(val, dict) and "itemInfo" in val:
                item_info = val["itemInfo"].get("itemStruct", {})
                break

    if item_info:
        caption = item_info.get("desc", "")

        # Get sound ID
        music = item_info.get("music", {})
        if music:
            sound_id = str(music.get("id", ""))

        # Get carousel images
        image_post = item_info.get("imagePost", {})
        images = image_post.get("images", [])
        for img in images:
            url_list = img.get("imageURL", {}).get("urlList", [])
            if url_list:
                # Prefer the last URL (usually highest quality)
                image_urls.append(url_list[-1])

    return image_urls, caption, sound_id


def _extract_from_sigi_state(data: dict) -> tuple[list[str], str, str | None]:
    """Extract image URLs from SIGI_STATE JSON."""
    image_urls = []
    caption = ""
    sound_id = None

    item_module = data.get("ItemModule", {})
    for item_id, item in item_module.items():
        caption = item.get("desc", "")
        music = item.get("music", {})
        if music:
            sound_id = str(music.get("id", ""))

        image_post = item.get("imagePost", {})
        images = image_post.get("images", [])
        for img in images:
            url_list = img.get("imageURL", {}).get("urlList", [])
            if url_list:
                image_urls.append(url_list[-1])
        break  # Only need the first item

    return image_urls, caption, sound_id


async def _resolve_url(url: str) -> str:
    """Resolve short/redirect URLs to final URL."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.head(url)
            return str(resp.url)
    except Exception:
        return url
