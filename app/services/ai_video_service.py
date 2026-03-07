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
from app.core.circuit_breaker import with_kling_breaker, with_runway_breaker, with_stability_breaker
from app.core.config import get_settings
from app.services.media_service import probe_duration
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

# Per-second costs in USD (credits × $0.01/credit)
# gen4.5=12cr/s=$0.12, veo3.1_fast=10cr/s=$0.10, veo3.1=20cr/s=$0.20
COST_PER_SECOND: dict[str, float] = {
    "runway": 0.12,
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

DURATION FORMULA:
- Target total duration: exactly {total_duration} seconds of AI-generated content.
- Split into exactly 3 scenes.
- The 3 scenes map to the script's 3 beats: Hook → Build → Payoff.
- Distribute duration proportionally to each scene's narration length.
- The sum of all scene durations MUST equal {total_duration} seconds.
- A pre-made outro clip is appended automatically — do NOT create a CTA scene.

STYLE CONSISTENCY:
- All 3 scenes MUST share a unified visual palette: same color grading, lighting mood,
  and overall aesthetic. Specify the shared look in EVERY ai_prompt.
- Example: if Scene 1 uses "warm golden-hour lighting with amber tones",
  Scenes 2 and 3 must reference the same lighting and color scheme.

For each scene, provide:
- scene_number: Sequential integer starting from 1
- narration: The exact portion of the script narrated during this scene
- visual_description: Detailed description of what should be shown visually
- visual_type: {visual_type_instruction}
- stock_query: A 2-4 word Pexels search query — specific and concrete
  (e.g. "molten lava ocean" not "nature"). Always provide as fallback.
- ai_prompt: A rich, cinematic prompt for AI video generation following the
  AI PROMPT GUIDELINES below. Keep under 120 words. Always provide.
- duration_seconds: 10 seconds per scene (fixed, exactly 3 scenes)

AI PROMPT GUIDELINES — use specific vocabulary from these categories:
  Camera: dolly in, trucking shot, crane shot, steadicam, FPV, orbital, push-in,
          pull-out, whip pan, rack focus, tracking shot
  Cinematic: shallow depth of field, 8K, anamorphic lens flare, film grain,
             volumetric lighting, motion blur, bokeh
  Lighting: golden hour, neon-lit night, overcast diffused, backlit silhouette,
            Rembrandt lighting, high-key, low-key
  Framing: extreme close-up, medium shot, wide establishing shot, over-the-shoulder,
           bird's-eye view, low-angle hero shot ({orientation})
  Transitions: end each scene's prompt with a transition hint for the next scene
               (e.g. "camera rises into clouds" → next scene starts from above)

COHERENCE: each scene's visual must directly illustrate its narration — no random B-roll.

Return ONLY a JSON object with key "scenes" containing a list of scene objects.
For a {format} video, use {orientation} framing in all visual descriptions.\
"""

# Strategy-specific instructions injected into the prompt
_VISUAL_TYPE_INSTRUCTIONS = {
    "ai_only": (
        '"ai_generated" for ALL scenes — every scene will be rendered by an AI video model.'
    ),
    "stock_only": (
        '"stock_footage" for ALL scenes — every scene will use Pexels stock footage.'
    ),
    "hybrid": (
        '"ai_generated" if the scene requires unique, creative, abstract, impossible, '
        "or highly specific visuals that stock footage cannot provide. "
        'Use "stock_footage" for generic real-world footage (nature, cities, people, labs).'
    ),
}


async def split_script_to_scenes(
    script: str,
    video_format: str = "short",
    provider: str = "openai",
    visual_strategy: str = "hybrid",
    audio_duration: float | None = None,
) -> list[Scene]:
    """
    Use LLM to split a script into visual scenes.

    Args:
        script: The full video script text.
        video_format: "short" or "long".
        provider: LLM provider ("openai" or "anthropic").
        visual_strategy: "hybrid" (LLM decides), "ai_only", or "stock_only".
        audio_duration: Exact TTS audio duration in seconds. When provided,
            scene durations are distributed to match audio precisely.

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

    visual_type_instruction = _VISUAL_TYPE_INSTRUCTIONS.get(
        visual_strategy,
        _VISUAL_TYPE_INSTRUCTIONS["hybrid"],
    )

    # Use real audio duration if available, otherwise estimate from word count
    if audio_duration and audio_duration > 0:
        total_duration = f"{audio_duration:.1f}"
    else:
        word_count_est = len(script.split())
        total_duration = f"{(word_count_est / 150) * 60:.1f}" if word_count_est > 0 else "30"

    system_prompt = SCENE_SPLIT_SYSTEM_PROMPT.format(
        total_duration=total_duration,
        format=format_name,
        orientation=orientation,
        visual_type_instruction=visual_type_instruction,
    )

    word_count = len(script.split())
    user_content = f"Script ({word_count} words):\n{script}"

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
            duration_seconds=float(raw.get("duration_seconds", 10.0)),
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

    # Duration distribution: use real audio duration or fallback to word-count estimate
    if audio_duration and audio_duration > 0:
        # Exact sync: distribute audio duration proportionally by narration word count
        total_words = sum(len(s.narration.split()) for s in scenes)
        if total_words > 0:
            for s in scenes:
                scene_words = len(s.narration.split())
                s.duration_seconds = round((scene_words / total_words) * audio_duration, 1)
        else:
            # Equal distribution if narration is empty
            per_scene = round(audio_duration / len(scenes), 1)
            for s in scenes:
                s.duration_seconds = per_scene

        # Fix rounding error — assign remainder to longest scene
        remainder = round(audio_duration - sum(s.duration_seconds for s in scenes), 1)
        if remainder != 0:
            longest = max(scenes, key=lambda s: s.duration_seconds)
            longest.duration_seconds = round(longest.duration_seconds + remainder, 1)

        logger.info(
            "Scene durations synced to audio — audio={:.1f}s scenes=[{}]",
            audio_duration,
            ", ".join(f"{s.duration_seconds:.1f}s" for s in scenes),
        )
    else:
        # Fallback: estimate from word count (no audio_duration available)
        total_scene_duration = sum(s.duration_seconds for s in scenes)
        word_count = len(script.split())
        estimated_reading_time = (word_count / 150) * 60  # seconds at 150 WPM

        if estimated_reading_time > 0:
            drift_pct = abs(total_scene_duration - estimated_reading_time) / estimated_reading_time
            if drift_pct > 0.30:
                logger.warning(
                    "Scene duration drift {:.0%}: scenes={:.1f}s vs reading={:.1f}s ({} words) "
                    "— adjusting proportionally",
                    drift_pct,
                    total_scene_duration,
                    estimated_reading_time,
                    word_count,
                )
                if total_scene_duration > 0:
                    scale = estimated_reading_time / total_scene_duration
                    for s in scenes:
                        s.duration_seconds = round(s.duration_seconds * scale, 1)
            else:
                logger.debug(
                    "Scene duration OK — scenes={:.1f}s vs reading={:.1f}s (drift={:.0%})",
                    total_scene_duration,
                    estimated_reading_time,
                    drift_pct,
                )

    logger.info(
        "Scene split complete — {} scenes ({} AI, {} stock, total={:.1f}s)",
        len(scenes),
        sum(1 for s in scenes if s.visual_type == "ai_generated"),
        sum(1 for s in scenes if s.visual_type == "stock_footage"),
        sum(s.duration_seconds for s in scenes),
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


# ── Prompt Enhancement ────────────────────────────────────────────

# Quality boosters appended if not already present in the prompt
_QUALITY_TOKENS = [
    "cinematic",
    "8K",
    "shallow depth of field",
    "film grain",
    "professional color grading",
]

# Framing hints by aspect ratio
_FRAMING_HINTS = {
    "9:16": "vertical composition, portrait framing, subject centered",
    "16:9": "wide cinematic composition, rule of thirds, horizontal framing",
}


def _enhance_runway_prompt(prompt: str, aspect_ratio: str = "9:16") -> str:
    """Enrich a scene prompt with cinematic quality tokens before sending to Runway.

    Similar to ``_preprocess_text_for_tts`` for ElevenLabs — the raw LLM scene
    prompt is good, but appending quality modifiers produces noticeably better
    AI-generated video from Runway Gen-3/Gen-4.

    Enhancements:
      1. Append quality tokens (8K, film grain, etc.) that aren't already present.
      2. Add aspect-ratio-specific framing hints.
      3. Ensure smooth motion keywords are present.
      4. Strip excessive whitespace.

    The enhanced prompt stays well within Runway's ~500-word limit.
    """
    prompt_lower = prompt.lower()

    # 1. Append missing quality boosters
    missing = [tok for tok in _QUALITY_TOKENS if tok.lower() not in prompt_lower]
    if missing:
        prompt = f"{prompt.rstrip('.')}. {', '.join(missing)}."

    # 2. Add framing hint for the target aspect ratio
    framing = _FRAMING_HINTS.get(aspect_ratio, "")
    if framing and framing.split(",")[0].strip().lower() not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. {framing}."

    # 3. Ensure smooth motion is mentioned (critical for AI video quality)
    if "smooth" not in prompt_lower and "fluid" not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. Smooth, fluid camera motion."

    # 4. Clean up whitespace
    prompt = " ".join(prompt.split())

    return prompt


def _enhance_stability_prompt(prompt: str, aspect_ratio: str = "9:16") -> str:
    """Enrich a scene prompt for Stability AI image-to-video pipeline.

    Stability works best with emphasis on composition, lighting, and
    subtle natural motion (since SVD animates a still image).
    """
    prompt_lower = prompt.lower()

    # Stability-specific tokens (image quality + subtle motion)
    stability_tokens = [
        "high detail",
        "professional photography",
        "natural lighting",
        "subtle natural motion",
    ]
    missing = [tok for tok in stability_tokens if tok.lower() not in prompt_lower]
    if missing:
        prompt = f"{prompt.rstrip('.')}. {', '.join(missing)}."

    # Shared quality tokens
    shared_missing = [tok for tok in _QUALITY_TOKENS if tok.lower() not in prompt_lower]
    if shared_missing:
        prompt = f"{prompt.rstrip('.')}. {', '.join(shared_missing)}."

    # Add framing hint for the target aspect ratio
    framing = _FRAMING_HINTS.get(aspect_ratio, "")
    if framing and framing.split(",")[0].strip().lower() not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. {framing}."

    # Clean up whitespace
    prompt = " ".join(prompt.split())
    return prompt


def _enhance_kling_prompt(prompt: str, aspect_ratio: str = "9:16") -> str:
    """Enrich a scene prompt for Kling AI text-to-video.

    Similar to Runway enhancement but with Kling-optimized language
    (emphasizes camera motion and dynamic composition).
    """
    prompt_lower = prompt.lower()

    # Append missing quality boosters (shared with Runway)
    missing = [tok for tok in _QUALITY_TOKENS if tok.lower() not in prompt_lower]
    if missing:
        prompt = f"{prompt.rstrip('.')}. {', '.join(missing)}."

    # Add framing hint for the target aspect ratio
    framing = _FRAMING_HINTS.get(aspect_ratio, "")
    if framing and framing.split(",")[0].strip().lower() not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. {framing}."

    # Ensure smooth motion is mentioned
    if "smooth" not in prompt_lower and "fluid" not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. Smooth, fluid camera motion."

    # Kling-specific: emphasize dynamic composition
    if "dynamic" not in prompt_lower:
        prompt = f"{prompt.rstrip('.')}. Dynamic composition."

    # Clean up whitespace
    prompt = " ".join(prompt.split())
    return prompt


# ── AI Video Provider Implementations ────────────────────────────


@with_runway_breaker()
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
    duration: int = 10,
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

    # Enhance prompt with cinematic quality tokens
    enhanced_prompt = _enhance_runway_prompt(prompt, aspect_ratio)
    logger.debug("Runway prompt enhanced — {} → {} chars", len(prompt), len(enhanced_prompt))

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.ai_video_timeout)) as client:
        # 1. Create generation task
        logger.info(
            "Runway Gen-3 — creating task (duration={}s, aspect={})", duration, aspect_ratio
        )
        # Map aspect ratio to pixel dimensions (API requires pixel format)
        ratio_map = {"9:16": "720:1280", "16:9": "1280:720"}
        pixel_ratio = ratio_map.get(aspect_ratio, "720:1280")

        create_response = await client.post(
            "https://api.dev.runwayml.com/v1/text_to_video",
            headers={
                "Authorization": f"Bearer {settings.runway_api_key}",
                "Content-Type": "application/json",
                "X-Runway-Version": "2024-11-06",
            },
            json={
                "model": settings.runway_model,
                "promptText": enhanced_prompt,
                "duration": duration,
                "ratio": pixel_ratio,
            },
        )
        if create_response.status_code != 200:
            logger.error(
                "Runway API error {}: {}",
                create_response.status_code,
                create_response.text[:500],
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

    # Validate downloaded clip
    clip_duration = probe_duration(output_file)
    if clip_duration < 1.0:
        output_file.unlink(missing_ok=True)
        raise ValueError(f"Runway clip too short ({clip_duration:.1f}s) — likely corrupted")

    logger.info("Runway video saved — {} ({:.1f}s)", output_file, clip_duration)
    return output_file


@with_stability_breaker()
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
    duration: int = 10,
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

    # Enhance prompt for Stability
    enhanced_prompt = _enhance_stability_prompt(prompt, aspect_ratio="9:16")
    logger.debug("Stability prompt enhanced — {} → {} chars", len(prompt), len(enhanced_prompt))

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
                "prompt": enhanced_prompt,
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

    # Validate downloaded clip
    clip_duration = probe_duration(output_file)
    if clip_duration < 1.0:
        output_file.unlink(missing_ok=True)
        raise ValueError(f"Stability clip too short ({clip_duration:.1f}s) — likely corrupted")

    logger.info("Stability video saved — {} ({:.1f}s)", output_file, clip_duration)
    return output_file


@with_kling_breaker()
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
    duration: int = 10,
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

    # Enhance prompt for Kling
    enhanced_prompt = _enhance_kling_prompt(prompt, aspect_ratio)
    logger.debug("Kling prompt enhanced — {} → {} chars", len(prompt), len(enhanced_prompt))

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
                "prompt": enhanced_prompt,
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

    # Validate downloaded clip
    clip_duration = probe_duration(output_file)
    if clip_duration < 1.0:
        output_file.unlink(missing_ok=True)
        raise ValueError(f"Kling clip too short ({clip_duration:.1f}s) — likely corrupted")

    logger.info("Kling video saved — {} ({:.1f}s)", output_file, clip_duration)
    return output_file


# ── Routing & Fallback Chain ─────────────────────────────────────


async def _generate_with_provider(
    provider: str,
    scene: Scene,
    aspect_ratio: str,
) -> Path:
    """Route generation to the correct provider."""
    duration = max(2, round(scene.duration_seconds))
    if provider == "runway":
        # Runway API max duration is 10s
        runway_dur = min(duration, 10)
        return await generate_ai_video_runway(scene.ai_prompt, runway_dur, aspect_ratio)
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
        scene.generation_cost = 0.0
        scene.provider_used = "pexels"
        return path

    if not await check_budget(estimated):
        logger.warning(
            "Daily budget exceeded, falling back to stock for scene {}", scene.scene_number
        )
        path = await _fetch_stock_for_scene(scene, orientation)
        scene.video_path = str(path)
        scene.generation_cost = 0.0
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
    scene.generation_cost = 0.0
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
