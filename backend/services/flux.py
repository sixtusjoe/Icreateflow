"""
AI face/image generation using Replicate's Flux model.
Used to generate replacement images for slide variations.
"""
import os
import httpx
from pathlib import Path


async def generate_image(prompt: str, output_path: str,
                         aspect_ratio: str = "3:4",
                         api_token: str = None) -> str:
    """
    Generate an image using Flux 1.1 Pro via Replicate API.

    Args:
        prompt: Description of the image to generate
        output_path: Where to save the generated image
        aspect_ratio: Image aspect ratio (default "3:4" for slides)
        api_token: Replicate API token (falls back to REPLICATE_API_TOKEN env var)

    Returns:
        Path to the saved image
    """
    try:
        import replicate
    except ImportError:
        raise RuntimeError("replicate package not installed. Run: pip install replicate")

    token = api_token or os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise ValueError("Replicate API token not configured. Set REPLICATE_API_TOKEN or pass api_token.")

    os.environ["REPLICATE_API_TOKEN"] = token

    output = replicate.run(
        "black-forest-labs/flux-1.1-pro",
        input={
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
            "safety_tolerance": 2,
        }
    )

    # Download the generated image
    image_url = output if isinstance(output, str) else str(output)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(resp.content)

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
