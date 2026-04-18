"""
TikTok slide downloader.
Downloads individual slide images from a TikTok photo carousel post URL.
"""
import re
import json
import logging
import subprocess
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)


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
                "Accept-Language": "en-US,en;q=0.9",
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
                    logger.info("tiktok_scraper: UNIVERSAL_DATA yielded %d urls", len(image_urls))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("tiktok_scraper: UNIVERSAL_DATA parse failed: %s", e)

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
                        logger.info("tiktok_scraper: SIGI_STATE yielded %d urls", len(image_urls))
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("tiktok_scraper: SIGI_STATE parse failed: %s", e)

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
                logger.info("tiktok_scraper: CDN regex yielded %d urls", len(image_urls))

            # Fallback: yt-dlp for TikTok photo posts (if installed)
            if not image_urls:
                image_urls = _ytdlp_fallback(resolved_url)
                logger.info("tiktok_scraper: yt-dlp fallback yielded %d urls", len(image_urls))

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
                    else:
                        logger.warning(
                            "tiktok_scraper: skipped %s (status=%s, size=%d)",
                            url, img_resp.status_code, len(img_resp.content),
                        )
                except Exception as e:
                    logger.warning("tiktok_scraper: download failed for %s: %s", url, e)
                    continue

    except Exception as e:
        logger.exception("TikTok scraper error: %s", e)

    return {
        "slides": slides,
        "sound_id": sound_id,
        "caption": caption,
    }


def _ytdlp_fallback(url: str) -> list[str]:
    """Use yt-dlp to extract photo-post image URLs when HTML scraping fails."""
    try:
        proc = subprocess.run(
            ["yt-dlp", "--skip-download", "--dump-single-json", "--no-warnings", url],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        data = json.loads(proc.stdout)
        urls: list[str] = []
        # Photo posts expose images under 'entries' or directly under 'thumbnails'
        entries = data.get("entries") or [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Preferred: explicit 'images' array (new yt-dlp versions)
            for img in entry.get("images") or []:
                u = img.get("url") if isinstance(img, dict) else None
                if u:
                    urls.append(u)
            # Fallback: use largest thumbnail per entry
            thumbs = entry.get("thumbnails") or []
            if thumbs and not urls:
                thumbs_sorted = sorted(
                    (t for t in thumbs if isinstance(t, dict) and t.get("url")),
                    key=lambda t: (t.get("height") or 0) * (t.get("width") or 0),
                    reverse=True,
                )
                if thumbs_sorted:
                    urls.append(thumbs_sorted[0]["url"])
        # dedupe
        seen, out = set(), []
        for u in urls:
            base = u.split("?")[0]
            if base not in seen:
                seen.add(base)
                out.append(u)
        return out
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning("yt-dlp fallback unavailable: %s", e)
        return []


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
