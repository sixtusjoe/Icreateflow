"""
AI face/image generation using Replicate's Flux model.
Used to generate replacement images for slide variations.
"""
import os
import httpx
from pathlib import Path


REPLICATE_MODEL = "black-forest-labs/flux-1.1-pro"
_REPLICATE_API = "https://api.replicate.com/v1"


async def generate_image(prompt: str, output_path: str,
                         aspect_ratio: str = "3:4",
                         api_token: str = None) -> str:
    """
    Generate an image using Flux 1.1 Pro via the Replicate REST API.

    Calls Replicate directly over HTTP (no SDK dependency) so we stay
    compatible with any Python version.

    Args:
        prompt: Description of the image to generate
        output_path: Where to save the generated image
        aspect_ratio: Image aspect ratio (default "3:4" for slides)
        api_token: Replicate API token (falls back to REPLICATE_API_TOKEN env var)

    Returns:
        Path to the saved image
    """
    token = api_token or os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise ValueError(
            "Replicate API token not configured. Set REPLICATE_API_TOKEN or pass api_token."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait",  # block up to 60s server-side, avoids some polling
    }
    payload = {
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
            "safety_tolerance": 2,
        }
    }

    async with httpx.AsyncClient(timeout=120) as client:
        # Create prediction
        resp = await client.post(
            f"{_REPLICATE_API}/models/{REPLICATE_MODEL}/predictions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        pred = resp.json()

        # Poll until terminal status
        import asyncio as _asyncio
        while pred.get("status") not in ("succeeded", "failed", "canceled"):
            get_url = pred.get("urls", {}).get("get")
            if not get_url:
                break
            await _asyncio.sleep(1.5)
            r = await client.get(get_url, headers=headers)
            r.raise_for_status()
            pred = r.json()

        if pred.get("status") != "succeeded":
            err = pred.get("error") or pred.get("status")
            raise RuntimeError(f"Replicate prediction failed: {err}")

        # `output` can be a URL string, a list of URLs, or a dict — normalize.
        output = pred.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if not output or not isinstance(output, str):
            raise RuntimeError(f"Unexpected Replicate output: {output!r}")

        # Download the generated image
        img = await client.get(output)
        img.raise_for_status()

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(img.content)

    return str(out)


def build_face_prompt(description: str = "", style: str = "") -> str:
    """
    Build a prompt for generating a face/person image that looks natural.

    Args:
        description: What the person should look like or be doing
        style: Brand style hints (e.g. "warm tones, lifestyle photography")

    Returns:
        A detailed prompt string
    """
    base = "photorealistic photograph, natural lighting, candid shot"
    if style:
        base = f"{base}, {style}"
    if description:
        base = f"{base}, {description}"
    base += ", shot on iPhone, social media style, high quality"
    return base


def build_scene_prompt(description: str = "", style: str = "") -> str:
    """
    Build a prompt for generating a scene/product/environment image.

    Args:
        description: What the scene should contain
        style: Brand style hints

    Returns:
        A detailed prompt string
    """
    base = "photorealistic photograph, professional photography"
    if style:
        base = f"{base}, {style}"
    if description:
        base = f"{base}, {description}"
    base += ", high quality, detailed, natural lighting"
    return base
