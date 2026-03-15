"""
AI Image Generation Service — generates scene-accurate images via DALL-E 3 / GPT-image-1.

Much cheaper than AI video generation ($0.08/image vs $1.20/video clip).
Images are animated with Ken Burns effects in media_service.py.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from pathlib import Path

from loguru import logger
from openai import APIError, AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

settings = get_settings()

# ── Cost Constants ───────────────────────────────────────────────

COST_PER_IMAGE: dict[str, dict[str, float]] = {
    "dall-e-3": {
        "1024x1024": 0.04,
        "1024x1792": 0.08,
        "1792x1024": 0.08,
        "1024x1024_hd": 0.08,
        "1024x1792_hd": 0.12,
        "1792x1024_hd": 0.12,
    },
    "gpt-image-1": {
        "1024x1024": 0.04,
        "1024x1792": 0.08,
        "1792x1024": 0.08,
    },
}


# ── Client (lazy singleton) ─────────────────────────────────────

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ── Cost Estimation ──────────────────────────────────────────────


def estimate_image_cost(
    model: str = "dall-e-3",
    size: str = "1024x1792",
    quality: str = "standard",
) -> float:
    """Return estimated cost in USD for a single image generation."""
    key = f"{size}_hd" if quality == "hd" else size
    model_costs = COST_PER_IMAGE.get(model, COST_PER_IMAGE["dall-e-3"])
    return model_costs.get(key, 0.08)


# ── Prompt Enhancement ───────────────────────────────────────────


def _enhance_image_prompt(prompt: str, aspect_ratio: str = "9:16") -> str:
    """Add quality tokens and framing hints to an image generation prompt."""
    quality_tokens = [
        "high detail",
        "professional photography",
        "dramatic lighting",
        "cinematic composition",
        "vibrant colors",
    ]

    # Add framing hint for portrait orientation
    if aspect_ratio == "9:16":
        framing = "vertical portrait composition, mobile-optimized framing"
    else:
        framing = "wide cinematic landscape composition"

    # Avoid duplicating tokens already present
    additions = []
    prompt_lower = prompt.lower()
    for token in quality_tokens:
        if token.lower() not in prompt_lower:
            additions.append(token)

    if framing.split(",")[0].lower() not in prompt_lower:
        additions.append(framing)

    enhanced = prompt.rstrip(". ") + ". " + ", ".join(additions) + "."

    # DALL-E 3 prompt limit is 4000 chars
    if len(enhanced) > 3900:
        enhanced = enhanced[:3900]

    return enhanced


# ── Image Generation ─────────────────────────────────────────────


@retry(
    retry=retry_if_exception_type(APIError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    before_sleep=lambda rs: logger.warning(
        "Image generation attempt {} failed, retrying ...", rs.attempt_number
    ),
)
async def generate_scene_image(
    prompt: str,
    size: str = "1024x1792",
    model: str = "dall-e-3",
    quality: str = "standard",
) -> Path:
    """Generate a single scene-accurate image via OpenAI's image API.

    Uses response_format="b64_json" to receive image data directly in the
    API response, avoiding Azure Blob Storage temporary URL 403 errors.

    Args:
        prompt: Scene description for image generation.
        size: Image dimensions (e.g. "1024x1792" for portrait).
        model: "dall-e-3" or "gpt-image-1".
        quality: "standard" or "hd".

    Returns:
        Path to the saved PNG image.
    """
    output_dir = settings.ai_images_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    enhanced_prompt = _enhance_image_prompt(
        prompt,
        aspect_ratio="9:16" if "1792" in size else "16:9",
    )

    logger.info(
        "Generating AI image — model={} size={} quality={} prompt_len={}",
        model, size, quality, len(enhanced_prompt),
    )

    client = _get_client()
    response = await client.images.generate(
        model=model,
        prompt=enhanced_prompt,
        size=size,
        quality=quality,
        n=1,
        response_format="b64_json",
    )

    b64_data = response.data[0].b64_json
    if not b64_data:
        raise ValueError("OpenAI returned empty image data")

    # Decode base64 and save directly — no URL download needed
    image_bytes = base64.b64decode(b64_data)
    output_path = output_dir / f"scene_{uuid.uuid4().hex[:12]}.png"
    output_path.write_bytes(image_bytes)

    file_size = output_path.stat().st_size
    if file_size < 1000:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"Image too small ({file_size} bytes) — likely invalid")

    logger.info(
        "AI image saved — {} ({:.1f}KB) model={}",
        output_path.name, file_size / 1024, model,
    )
    return output_path


# ── Parallel Scene Image Generation ──────────────────────────────


async def generate_all_scene_images(
    scenes: list,
    project_id: str,
    max_concurrent: int = 3,
) -> list[Path]:
    """Generate images for all scenes in parallel with concurrency control.

    Uses the same budget tracking as ai_video_service.

    Args:
        scenes: List of Scene dataclass objects with ai_prompt, duration_seconds.
        project_id: UUID of the video project.
        max_concurrent: Maximum concurrent API calls.

    Returns:
        List of image Paths in scene order.
    """
    from app.services.ai_video_service import check_budget, record_spend

    semaphore = asyncio.Semaphore(max_concurrent)
    model = settings.ai_images_model
    size = settings.ai_images_size
    quality = settings.ai_images_quality

    # Check total budget upfront
    per_image_cost = estimate_image_cost(model, size, quality)
    total_estimated = per_image_cost * len(scenes)
    if total_estimated > settings.ai_images_max_cost_per_video:
        logger.warning(
            "Total image cost ${:.2f} exceeds per-video cap ${:.2f} — project={}",
            total_estimated, settings.ai_images_max_cost_per_video, project_id,
        )

    async def _generate_one(scene) -> Path:
        async with semaphore:
            img_cost = estimate_image_cost(model, size, quality)

            if not await check_budget(img_cost):
                logger.warning(
                    "Daily budget exceeded, skipping AI image for scene {}",
                    scene.scene_number,
                )
                raise RuntimeError("Daily budget exceeded")

            image_path = await generate_scene_image(
                prompt=scene.ai_prompt,
                size=size,
                model=model,
                quality=quality,
            )

            await record_spend(img_cost)
            return image_path

    tasks = [_generate_one(scene) for scene in scenes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    paths: list[Path] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(
                "AI image generation failed for scene {} in project {}: {}",
                scenes[i].scene_number, project_id, result,
            )
            paths.append(result)  # type: ignore[arg-type]  # caller handles
        else:
            paths.append(result)

    return paths
