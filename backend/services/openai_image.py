"""OpenAI image generation service for variation slide images.

Uses gpt-image-1 model:
- With reference image → /v1/images/edits  (image-guided generation)
- Without reference    → /v1/images/generations (text-to-image)
"""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from typing import Optional


async def generate_image(
    prompt: str,
    output_path: str,
    reference_image_path: Optional[str] = None,
    api_key: Optional[str] = None,
    size: str = "1024x1536",
) -> str:
    """Generate an image via OpenAI and save it to output_path.

    Args:
        prompt: Text description of the desired image.
        output_path: Local filesystem path to write the PNG result.
        reference_image_path: Optional path to a reference image. When
            provided the model uses it as visual context.
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
        size: Image dimensions. Defaults to portrait 1024x1536.

    Returns:
        output_path on success.

    Raises:
        ValueError: API key not configured.
        RuntimeError: OpenAI API returned an error.
    """
    token = api_key or os.environ.get("OPENAI_API_KEY")
    if not token:
        raise ValueError("OpenAI API key not configured — add one in Settings")

    import httpx

    headers = {"Authorization": f"Bearer {token}"}

    if reference_image_path and Path(reference_image_path).exists():
        # OpenAI edits endpoint requires PNG. Convert if needed.
        import io
        from PIL import Image as _PILImage, ImageFile as _PILImageFile

        _PILImageFile.LOAD_TRUNCATED_IMAGES = True  # handle partially-written files

        def _to_png_bytes(path: str) -> bytes:
            img = _PILImage.open(path)
            img.load()  # force full load before converting
            img = img.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        image_bytes = await asyncio.to_thread(_to_png_bytes, reference_image_path)

        files = {
            "image": ("reference.png", image_bytes, "image/png"),
        }
        data = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": "medium",
            "n": "1",
        }

        def _do_request():
            with httpx.Client(timeout=300) as client:
                resp = client.post(
                    "https://api.openai.com/v1/images/edits",
                    headers=headers,
                    data=data,
                    files=files,
                )
                if not resp.is_success:
                    raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
                return resp.json()

        result = await asyncio.to_thread(_do_request)
    else:
        # Pure text-to-image via /v1/images/generations
        payload = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": "medium",
            "n": 1,
        }

        def _do_request():
            with httpx.Client(timeout=300) as client:
                resp = client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )
                if not resp.is_success:
                    raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
                return resp.json()

        result = await asyncio.to_thread(_do_request)

    # Extract base64 image data
    image_data = result.get("data", [{}])[0]
    b64 = image_data.get("b64_json") or image_data.get("b64")
    if not b64:
        # Some responses return a URL instead
        url = image_data.get("url")
        if url:
            def _download():
                with httpx.Client(timeout=60) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    return r.content
            img_bytes = await asyncio.to_thread(_download)
        else:
            raise RuntimeError(f"OpenAI returned no image data: {result}")
    else:
        img_bytes = base64.b64decode(b64)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(img_bytes)
    return output_path
