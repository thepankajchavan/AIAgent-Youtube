"""
AI Video Service — generates video clips using AI providers.

Supports:
  - Runway Gen-3 Alpha (text-to-video)
  - Stability AI (text-to-image → image-to-video)
  - Kling AI (text-to-video)

Also handles LLM-based scene splitting and a multi-provider
fallback chain with per-day budget tracking via Redis.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import QueryCache
from app.core.config import get_settings
from app.services.visual_service import create_placeholder_video, fetch_clips

settings = get_settings()


# ── Data Models ──────────────────────────────────────────────────


@dataclass
class Scene:
    """A single visual scene from the LLM scene plan."""

    scene_number: int
    narration: str
    visual_description: str
    visual_type: str  # "ai_generated" or "stock_footage"
    stock_query: str  # always provided (used as fallback)
    ai_prompt: str  # always provided
    duration_seconds: float
    video_path: str | None = None
    generation_cost: float = 0.0
    provider_used: str | None = None


# ── Cost Constants ───────────────────────────────────────────────

# Approximate per-second costs (USD)
COST_PER_SECOND: dict[str, float] = {
    "runway": 0.05,
    "stability": 0.03,
    "kling": 0.02,
}

_DAILY_SPEND_KEY = "ai_video:daily_spend:{date}"


# ── Cost Tracking (Redis-backed) ────────────────────────────────


def estimate_cost(duration: float, provider: str) -> float:
    """Estimate AI generation cost in USD."""
    return duration * COST_PER_SECOND.get(provider, 0.05)


async def get_daily_spend() -> float:
    """Get total AI video spend for today from Redis."""
    key = _DAILY_SPEND_KEY.format(date=date.today().isoformat())
    value = await QueryCache.get(key)
    return float(value) if value else 0.0


async def record_spend(amount: float) -> None:
    """Record spend to Redis with a 48-hour TTL."""
    key = _DAILY_SPEND_KEY.format(date=date.today().isoformat())
    current = await get_daily_spend()
    await QueryCache.set(key, current + amount, ttl=60 * 60 * 48)


async def check_budget(estimated_cost: float) -> bool:
    """Return True if estimated cost fits within daily budget."""
    daily = await get_daily_spend()
    if daily + estimated_cost > settings.ai_video_max_daily_spend:
        logger.warning(
            "Daily AI video budget would be exceeded: ${:.2f} + ${:.2f} > ${:.2f}",
            daily,
            estimated_cost,
            settings.ai_video_max_daily_spend,
        )
        return False
    return True


# ── Scene Splitting (LLM) ───────────────────────────────────────

SCENE_SPLIT_SYSTEM_PROMPT = """\
You are an expert video scene planner for YouTube content.
Given a video script, split it into distinct visual scenes for video production.

For each scene, provide:
- scene_number: Sequential integer starting from 1
- narration: The exact portion of the script narrated during this scene
- visual_description: Detailed description of what should be shown visually
- visual_type: "ai_generated" if the scene requires unique, creative, abstract, \
impossible, or highly specific visuals that stock footage cannot provide. \
Use "stock_footage" for generic real-world footage (nature, cities, people, labs).
- stock_query: A Pexels search query (always provide — used as fallback)
- ai_prompt: A detailed, cinematic prompt for AI video generation (always provide)
- duration_seconds: How long this scene lasts (2-8 seconds each, based on narration pace)

Return ONLY a JSON object with key "scenes" containing a list of scene objects.
Total scene durations should approximately match the script reading time.
For a {format} video, use {orientation} framing in all visual descriptions.\
"""


async def split_script_to_scenes(
    script: str,
    video_format: str = "short",
    provider: str = "openai",
    visual_strategy: str = "hybrid",
) -> list[Scene]:
    """
    Use LLM to split a script into visual scenes.

    Args:
        script: The full video script text.
        video_format: "short" or "long".
        provider: LLM provider ("openai" or "anthropic").
        visual_strategy: "hybrid" (LLM decides), "ai_only", or "stock_only".

    Returns:
        List of Scene objects with visual_type assignments.
    """
    from app.services.llm_service import LLMProvider

    orientation = (
        "vertical 9:16 portrait" if video_format == "short" else "horizontal 16:9 landscape"
    )
    format_name = (
        "YouTube Short (30-60 seconds)"
        if video_format == "short"
        else "YouTube long-form (5-10 minutes)"
    )

    system_prompt = SCENE_SPLIT_SYSTEM_PROMPT.format(
        format=format_name,
        orientation=orientation,
    )

    user_content = f"Script:\n{script}"

    # Call LLM using existing infrastructure
    if provider == LLMProvider.ANTHROPIC.value or provider == "anthropic":
        result = await _call_anthropic_for_scenes(system_prompt, user_content)
    else:
        result = await _call_openai_for_scenes(system_prompt, user_content)

    # Parse scenes from LLM response
    raw_scenes = result.get("scenes", [])
    if not raw_scenes:
        raise ValueError("LLM returned no scenes from scene splitting")

    scenes: list[Scene] = []
    for raw in raw_scenes:
        scene = Scene(
            scene_number=raw.get("scene_number", len(scenes) + 1),
            narration=raw.get("narration", ""),
            visual_description=raw.get("visual_description", ""),
            visual_type=raw.get("visual_type", "stock_footage"),
            stock_query=raw.get("stock_query", "nature"),
            ai_prompt=raw.get("ai_prompt", raw.get("visual_description", "")),
            duration_seconds=float(raw.get("duration_seconds", 4.0)),
        )
        scenes.append(scene)

    # Override visual_type based on strategy
    if visual_strategy == "ai_only":
        for s in scenes:
            s.visual_type = "ai_generated"
    elif visual_strategy == "stock_only":
        for s in scenes:
            s.visual_type = "stock_footage"
    # "hybrid" keeps the LLM's decisions

    logger.info(
        "Scene split complete — {} scenes ({} AI, {} stock)",
        len(scenes),
        sum(1 for s in scenes if s.visual_type == "ai_generated"),
        sum(1 for s in scenes if s.visual_type == "stock_footage"),
    )
    return scenes


async def _call_openai_for_scenes(system_prompt: str, user_content: str) -> dict:
    """Call OpenAI with scene splitting prompt."""
    from app.services.llm_service import _get_openai

    client = _get_openai()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    return json.loads(response.choices[0].message.content)


async def _call_anthropic_for_scenes(system_prompt: str, user_content: str) -> dict:
    """Call Anthropic with scene splitting prompt."""
    from app.services.llm_service import _get_anthropic

    client = _get_anthropic()
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        first_newline = raw.find("\n")
        raw = raw[first_newline + 1 :] if first_newline != -1 else raw[3:]
    if raw.rstrip().endswith("```"):
        raw = raw.rstrip()[:-3]
    return json.loads(raw.strip())


# ── AI Video Provider Implementations ────────────────────────────


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=5, min=10, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "Runway attempt {} failed, retrying …",
        rs.attempt_number,
    ),
)
async def generate_ai_video_runway(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
) -> Path:
    """
    Generate video using Runway Gen-3 Alpha API.

    Flow:
        1. POST to create a generation task
        2. Poll task status until complete
        3. Download the result video
        4. Return local file path
    """
    output_dir = settings.ai_video_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"runway_{uuid.uuid4().hex[:12]}.mp4"

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_video_timeout)) as client:
        # 1. Create generation task
        logger.info(
            "Runway Gen-3 — creating task (duration={}s, aspect={})", duration, aspect_ratio
        )
        create_response = await client.post(
            "https://api.dev.runwayml.com/v1/text_to_video",
            headers={
                "Authorization": f"Bearer {settings.runway_api_key}",
                "Content-Type": "application/json",
                "X-Runway-Version": "2024-11-06",
            },
            json={
                "model": settings.runway_model,
                "prompt": prompt,
                "duration": duration,
                "ratio": aspect_ratio,
            },
        )
        create_response.raise_for_status()
        task_id = create_response.json().get("id")
        logger.info("Runway task created — id={}", task_id)

        # 2. Poll for completion
        poll_url = f"https://api.dev.runwayml.com/v1/tasks/{task_id}"
        for _attempt in range(120):  # max ~10 minutes polling
            await asyncio.sleep(5)
            poll_response = await client.get(
                poll_url,
                headers={"Authorization": f"Bearer {settings.runway_api_key}"},
            )
            poll_response.raise_for_status()
            poll_data = poll_response.json()
            status = poll_data.get("status", "")

            if status == "SUCCEEDED":
                video_url = poll_data.get("output", [None])[0]
                if not video_url:
                    raise ValueError("Runway task succeeded but no output URL")
                break
            elif status in ("FAILED", "CANCELLED"):
                error = poll_data.get("failure", "Unknown error")
                raise RuntimeError(f"Runway generation failed: {error}")
            # else PENDING / RUNNING — continue polling
        else:
            raise TimeoutError(f"Runway task {task_id} did not complete within timeout")

        # 3. Download result
        logger.info("Runway downloading result video …")
        video_response = await client.get(video_url)
        video_response.raise_for_status()
        output_file.write_bytes(video_response.content)

    logger.info("Runway video saved — {}", output_file)
    return output_file


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=5, min=10, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "Stability attempt {} failed, retrying …",
        rs.attempt_number,
    ),
)
async def generate_ai_video_stability(
    prompt: str,
    duration: int = 4,
) -> Path:
    """
    Generate video using Stability AI (image-to-video pipeline).

    Flow:
        1. Generate a still image via SDXL text-to-image
        2. Animate the image via Stable Video Diffusion
        3. Poll for completion and download
    """
    output_dir = settings.ai_video_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"stability_{uuid.uuid4().hex[:12]}.mp4"

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_video_timeout)) as client:
        headers = {
            "Authorization": f"Bearer {settings.stability_api_key}",
            "Accept": "application/json",
        }

        # Step 1: Generate still image via SDXL
        logger.info("Stability — generating base image via SDXL")
        img_response = await client.post(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            headers={**headers, "Accept": "image/*"},
            data={
                "prompt": prompt,
                "output_format": "png",
                "aspect_ratio": "9:16",
            },
        )
        img_response.raise_for_status()

        image_path = output_dir / f"stability_img_{uuid.uuid4().hex[:8]}.png"
        image_path.write_bytes(img_response.content)
        logger.info("Stability base image saved — {}", image_path)

        # Step 2: Image-to-Video via SVD
        logger.info("Stability — animating image via SVD")
        with open(image_path, "rb") as img_file:
            vid_response = await client.post(
                "https://api.stability.ai/v2beta/image-to-video",
                headers={"Authorization": f"Bearer {settings.stability_api_key}"},
                data={"seed": 0, "cfg_scale": 2.5, "motion_bucket_id": 40},
                files={"image": ("image.png", img_file, "image/png")},
            )
        vid_response.raise_for_status()
        generation_id = vid_response.json().get("id")
        logger.info("Stability video generation started — id={}", generation_id)

        # Step 3: Poll for result
        poll_url = f"https://api.stability.ai/v2beta/image-to-video/result/{generation_id}"
        for _attempt in range(90):  # max ~7.5 minutes
            await asyncio.sleep(5)
            result_response = await client.get(
                poll_url,
                headers={
                    "Authorization": f"Bearer {settings.stability_api_key}",
                    "Accept": "video/*",
                },
            )
            if result_response.status_code == 202:
                continue  # Still processing
            result_response.raise_for_status()
            output_file.write_bytes(result_response.content)
            break
        else:
            raise TimeoutError(f"Stability video {generation_id} did not complete within timeout")

        # Clean up temporary image
        with contextlib.suppress(OSError):
            image_path.unlink()

    logger.info("Stability video saved — {}", output_file)
    return output_file


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=5, min=10, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "Kling attempt {} failed, retrying …",
        rs.attempt_number,
    ),
)
async def generate_ai_video_kling(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
) -> Path:
    """
    Generate video using Kling AI API.

    Flow:
        1. POST to create a generation task
        2. Poll for completion
        3. Download result video
    """
    output_dir = settings.ai_video_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"kling_{uuid.uuid4().hex[:12]}.mp4"

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_video_timeout)) as client:
        # 1. Create generation task
        logger.info("Kling AI — creating task (duration={}s, aspect={})", duration, aspect_ratio)
        create_response = await client.post(
            "https://api.klingai.com/v1/videos/text2video",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.kling_access_key}",
            },
            json={
                "prompt": prompt,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
                "model": "kling-v1",
                "mode": "std",
            },
        )
        create_response.raise_for_status()
        task_data = create_response.json().get("data", {})
        task_id = task_data.get("task_id")
        logger.info("Kling task created — id={}", task_id)

        # 2. Poll for completion
        poll_url = f"https://api.klingai.com/v1/videos/text2video/{task_id}"
        for _attempt in range(120):
            await asyncio.sleep(5)
            poll_response = await client.get(
                poll_url,
                headers={"Authorization": f"Bearer {settings.kling_access_key}"},
            )
            poll_response.raise_for_status()
            poll_data = poll_response.json().get("data", {})
            status = poll_data.get("task_status", "")

            if status == "succeed":
                videos = poll_data.get("task_result", {}).get("videos", [])
                if not videos:
                    raise ValueError("Kling task succeeded but no video in result")
                video_url = videos[0].get("url")
                break
            elif status == "failed":
                error = poll_data.get("task_status_msg", "Unknown error")
                raise RuntimeError(f"Kling generation failed: {error}")
        else:
            raise TimeoutError(f"Kling task {task_id} did not complete within timeout")

        # 3. Download result
        logger.info("Kling downloading result video …")
        video_response = await client.get(video_url)
        video_response.raise_for_status()
        output_file.write_bytes(video_response.content)

    logger.info("Kling video saved — {}", output_file)
    return output_file


# ── Routing & Fallback Chain ─────────────────────────────────────


async def _generate_with_provider(
    provider: str,
    scene: Scene,
    aspect_ratio: str,
) -> Path:
    """Route generation to the correct provider."""
    duration = max(2, int(scene.duration_seconds))
    if provider == "runway":
        return await generate_ai_video_runway(scene.ai_prompt, duration, aspect_ratio)
    elif provider == "stability":
        return await generate_ai_video_stability(scene.ai_prompt, duration)
    elif provider == "kling":
        return await generate_ai_video_kling(scene.ai_prompt, duration, aspect_ratio)
    raise ValueError(f"Unknown AI video provider: {provider}")


async def _fetch_stock_for_scene(scene: Scene, orientation: str) -> Path:
    """Fetch a single stock clip for a scene via Pexels, with placeholder fallback."""
    try:
        clips = await fetch_clips(
            queries=[scene.stock_query],
            orientation=orientation,
            clips_per_query=1,
        )
        if clips:
            return clips[0]
    except Exception as exc:
        logger.warning(
            "Stock footage fetch failed for scene {}: {}",
            scene.scene_number,
            exc,
        )
    # Ultimate fallback: solid-colour placeholder
    placeholders = await create_placeholder_video(scene.stock_query, int(scene.duration_seconds))
    return placeholders[0]


async def generate_scene_visual(
    scene: Scene,
    video_format: str,
    project_id: str,
) -> Path:
    """
    Generate a visual for a single scene with full fallback chain:
        1. Primary AI provider  (if visual_type == "ai_generated")
        2. Secondary AI provider (if primary fails)
        3. Stock footage         (Pexels)
        4. Placeholder video     (solid colour)

    For stock_footage scenes, skip straight to step 3.
    """
    orientation = "portrait" if video_format == "short" else "landscape"
    aspect = "9:16" if video_format == "short" else "16:9"

    # Stock footage scenes bypass AI entirely
    if scene.visual_type == "stock_footage":
        path = await _fetch_stock_for_scene(scene, orientation)
        scene.video_path = str(path)
        scene.provider_used = "pexels"
        return path

    primary = settings.ai_video_primary_provider
    secondary = settings.ai_video_secondary_provider

    # Budget check before any AI call
    estimated = estimate_cost(scene.duration_seconds, primary)
    if estimated > settings.ai_video_max_cost_per_video:
        logger.warning(
            "Scene {} estimated cost ${:.2f} exceeds per-video cap, using stock",
            scene.scene_number,
            estimated,
        )
        path = await _fetch_stock_for_scene(scene, orientation)
        scene.video_path = str(path)
        scene.provider_used = "pexels"
        return path

    if not await check_budget(estimated):
        logger.warning(
            "Daily budget exceeded, falling back to stock for scene {}", scene.scene_number
        )
        path = await _fetch_stock_for_scene(scene, orientation)
        scene.video_path = str(path)
        scene.provider_used = "pexels"
        return path

    # Try primary provider
    try:
        path = await _generate_with_provider(primary, scene, aspect)
        cost = estimate_cost(scene.duration_seconds, primary)
        await record_spend(cost)
        scene.generation_cost = cost
        scene.provider_used = primary
        scene.video_path = str(path)
        logger.info("Scene {} generated via {} (${:.2f})", scene.scene_number, primary, cost)
        return path
    except Exception as exc:
        logger.warning(
            "Primary AI provider ({}) failed for scene {}: {}",
            primary,
            scene.scene_number,
            exc,
        )

    # Try secondary provider
    if secondary and secondary != primary:
        try:
            path = await _generate_with_provider(secondary, scene, aspect)
            cost = estimate_cost(scene.duration_seconds, secondary)
            await record_spend(cost)
            scene.generation_cost = cost
            scene.provider_used = secondary
            scene.video_path = str(path)
            logger.info(
                "Scene {} generated via {} fallback (${:.2f})", scene.scene_number, secondary, cost
            )
            return path
        except Exception as exc:
            logger.warning(
                "Secondary AI provider ({}) failed for scene {}: {}",
                secondary,
                scene.scene_number,
                exc,
            )

    # Fall back to stock footage
    logger.info("All AI providers failed, using stock footage for scene {}", scene.scene_number)
    path = await _fetch_stock_for_scene(scene, orientation)
    scene.video_path = str(path)
    scene.provider_used = "pexels"
    return path


# ── Parallel Scene Generation ────────────────────────────────────


async def generate_all_visuals(
    scenes: list[Scene],
    video_format: str,
    project_id: str,
    max_concurrent: int = 3,
) -> list[Path]:
    """
    Generate visuals for all scenes with concurrency control.

    Uses asyncio.Semaphore to limit concurrent AI API calls
    and prevent rate-limiting. Returns paths in scene order.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _generate_with_limit(scene: Scene) -> Path:
        async with semaphore:
            return await generate_scene_visual(scene, video_format, project_id)

    tasks = [_generate_with_limit(scene) for scene in scenes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    paths: list[Path] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Scene {} generation failed completely: {}", i + 1, result)
            # Last-resort placeholder
            placeholder = await create_placeholder_video(
                scenes[i].stock_query,
                int(scenes[i].duration_seconds),
            )
            paths.append(placeholder[0])
            scenes[i].video_path = str(placeholder[0])
            scenes[i].provider_used = "placeholder"
        else:
            paths.append(result)

    logger.info(
        "All visuals generated for project {} — {} clips",
        project_id,
        len(paths),
    )
    return paths
