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
    image_path: str | None = None  # AI-generated source image (for ai_images strategy)
    generation_cost: float = 0.0
    provider_used: str | None = None
    # Creative direction fields (Phase 4)
    transition_type: str | None = None   # FFmpeg xfade type INTO this scene
    mood: str | None = None              # Emotional tone for this scene
    caption_emphasis: str | None = None  # "strong" | "normal" | "subtle"


# ── Provider Duration Limits ─────────────────────────────────────

_PROVIDER_MAX_DURATION: dict[str, float] = {
    "runway": 10.0,
    "stability": 10.0,
    "kling": 10.0,
}


def _enforce_provider_duration_limits(
    scenes: list[Scene],
    provider: str,
    total_duration: float,
) -> list[Scene]:
    """Split scenes that exceed a provider's max duration limit.

    If a scene's duration exceeds the provider's limit (e.g. Runway 10s),
    split it into sub-scenes with proportional durations and narration.
    Total duration is preserved exactly.
    """
    max_dur = _PROVIDER_MAX_DURATION.get(provider, 10.0)

    new_scenes: list[Scene] = []
    for scene in scenes:
        if scene.duration_seconds <= max_dur or scene.visual_type == "stock_footage":
            new_scenes.append(scene)
            continue

        # Split into sub-scenes
        num_splits = int(scene.duration_seconds / max_dur) + 1
        sub_duration = round(scene.duration_seconds / num_splits, 1)

        # Split narration roughly by word count
        words = scene.narration.split()
        words_per_split = max(1, len(words) // num_splits)

        for j in range(num_splits):
            start_idx = j * words_per_split
            end_idx = start_idx + words_per_split if j < num_splits - 1 else len(words)
            sub_narration = " ".join(words[start_idx:end_idx])

            sub_scene = Scene(
                scene_number=0,  # Will be renumbered
                narration=sub_narration,
                visual_description=scene.visual_description,
                visual_type=scene.visual_type,
                stock_query=scene.stock_query,
                ai_prompt=scene.ai_prompt + (
                    f" (continuation {j + 1}/{num_splits})" if num_splits > 1 else ""
                ),
                duration_seconds=sub_duration,
                transition_type=scene.transition_type if j == 0 else "dissolve",
                mood=scene.mood,
                caption_emphasis=scene.caption_emphasis,
            )
            new_scenes.append(sub_scene)

        logger.info(
            "Scene {} split into {} sub-scenes (was {:.1f}s, max={:.1f}s)",
            scene.scene_number, num_splits, scene.duration_seconds, max_dur,
        )

    # Renumber scenes
    for i, s in enumerate(new_scenes):
        s.scene_number = i + 1

    # Fix rounding: ensure total matches
    actual_total = sum(s.duration_seconds for s in new_scenes)
    if total_duration > 0:
        remainder = round(total_duration - actual_total, 1)
        if abs(remainder) > 0.05:
            longest = max(new_scenes, key=lambda s: s.duration_seconds)
            longest.duration_seconds = round(longest.duration_seconds + remainder, 1)

    return new_scenes


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
- Split into 5 or 6 scenes for fast-paced, dynamic visuals.
- The scenes map to the script's beats: Hook → Build 1 → Build 2 → Build 3 → Climax → Kicker (optional 6th).
- Distribute duration proportionally to each scene's narration length.
- The sum of all scene durations MUST equal {total_duration} seconds.
- Do NOT create a CTA/subscribe scene — the video ends with content only.

STYLE CONSISTENCY (CRITICAL):
- Scene 1's ai_prompt MUST establish the video's visual DNA: a specific color palette
  (e.g. "teal and amber color grading"), lighting style (e.g. "golden hour warm light"),
  and aesthetic (e.g. "cinematic film grain, shallow depth of field").
- All subsequent scenes MUST reference Scene 1's exact same palette and lighting in their ai_prompt.
- Example: Scene 1 says "warm amber tones, golden hour light, shallow depth of field"
  → Scene 3 MUST include "warm amber tones, golden hour light" even if the subject differs.
- The visual DNA carries across scenes even when locations or subjects change.

For each scene, provide:
- scene_number: Sequential integer starting from 1
- narration: The exact portion of the script narrated during this scene
- visual_description: Detailed description of what should be shown visually
- visual_type: {visual_type_instruction}
- stock_query: A 2-4 word Pexels search query — specific and concrete
  (e.g. "molten lava ocean" not "nature"). Always provide as fallback.
- ai_prompt: A rich, cinematic prompt for AI video generation following the
  AI PROMPT GUIDELINES below. Keep under 120 words. Always provide.
- duration_seconds: distribute proportionally across 5-6 scenes based on narration length

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

CREATIVE DIRECTION (per scene — optional, for enhanced production):
- transition_type: FFmpeg xfade transition INTO this scene. Options: fade, dissolve,
  wipeleft, wiperight, slideleft, slideright, circlecrop, radial, smoothleft, smoothright.
  Scene 1 should always be "fade".
- mood: scene emotional tone. Options: energetic, calm, dramatic, mysterious, uplifting, dark.
- caption_emphasis: "strong" for key reveals/twists, "normal" for standard narration,
  "subtle" for bridge/transition moments.

VISUAL HINTS: If the scriptwriter provided visual direction hints, use them as the FOUNDATION
for each scene's ai_prompt — they contain camera angles, lighting, and color palette guidance.
Expand them with cinematic vocabulary but preserve the intended visual direction.

COHERENCE: each scene's visual must directly illustrate its narration — no random B-roll.

Return ONLY a JSON object with key "scenes" containing a list of scene objects.
For a {format} video, use {orientation} framing in all visual descriptions.\
"""

# Strategy-specific instructions injected into the prompt
_VISUAL_TYPE_INSTRUCTIONS = {
    "ai_only": (
        '"ai_generated" for ALL scenes — every scene will be rendered by an AI video model.'
    ),
    "ai_images": (
        '"ai_generated" for ALL scenes — every scene will use an AI-generated image '
        "with Ken Burns pan/zoom animation."
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
    visual_hints: list[str] | None = None,
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
        visual_hints: Per-beat visual direction hints from the scriptwriter.
            When provided, these guide the scene planner's ai_prompt generation.

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

    # Inject visual direction hints from the scriptwriter
    if visual_hints:
        hints_block = "\n".join(
            f"Beat {i + 1}: {hint}" for i, hint in enumerate(visual_hints) if hint
        )
        if hints_block:
            user_content += (
                f"\n\nVISUAL DIRECTION HINTS FROM SCRIPTWRITER:\n{hints_block}\n"
                "Use these as the FOUNDATION for each scene's ai_prompt — they contain "
                "camera angles, lighting, and color palette guidance from the scriptwriter."
            )

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
            transition_type=raw.get("transition_type"),
            mood=raw.get("mood"),
            caption_emphasis=raw.get("caption_emphasis"),
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

    # Enforce provider duration limits (e.g. Runway 10s max)
    if visual_strategy in ("ai_only", "hybrid", "ai_images"):
        provider_name = settings.ai_video_primary_provider
        original_count = len(scenes)
        effective_total = (
            float(audio_duration)
            if audio_duration
            else sum(s.duration_seconds for s in scenes)
        )
        scenes = _enforce_provider_duration_limits(scenes, provider_name, effective_total)
        if len(scenes) != original_count:
            logger.info(
                "Duration limits applied — {} scenes → {} scenes (provider={}, max={}s)",
                original_count,
                len(scenes),
                provider_name,
                _PROVIDER_MAX_DURATION.get(provider_name, 10.0),
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
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as e:
        raw = response.choices[0].message.content
        logger.error("OpenAI returned invalid JSON for scene split: {}\nRaw: {}", e, raw[:500])
        raise ValueError(f"OpenAI returned invalid JSON for scene splitting: {e}") from e


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
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error("Anthropic returned invalid JSON for scene split: {}\nRaw: {}", e, raw[:500])
        raise ValueError(f"Anthropic returned invalid JSON for scene splitting: {e}") from e


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


# ── Intelligent Prompt Rewriting ─────────────────────────────────

_PROVIDER_REWRITE_INSTRUCTIONS: dict[str, str] = {
    "runway": (
        "Optimize this prompt for Runway Gen-4 text-to-video. "
        "Runway excels at: smooth camera motion, cinematic tracking shots, "
        "realistic lighting, and dynamic scenes with flowing movement. "
        "Emphasize: camera movement direction, motion of subjects, lighting transitions. "
        "Keep under 400 words. Do NOT add unrelated elements."
    ),
    "stability": (
        "Optimize this prompt for Stability AI image-to-video. "
        "The output will be a still image animated with subtle motion. "
        "Emphasize: strong composition, dramatic lighting, clear focal point, "
        "photographic detail, and elements that animate well (water, clouds, fabric). "
        "Keep under 300 words. Do NOT add unrelated elements."
    ),
    "kling": (
        "Optimize this prompt for Kling AI text-to-video. "
        "Kling excels at: fast-paced dynamic scenes, character animation, "
        "and dramatic compositions. "
        "Emphasize: action, movement direction, dramatic angles, dynamic energy. "
        "Keep under 400 words. Do NOT add unrelated elements."
    ),
}


async def _rewrite_prompt_for_provider(
    prompt: str,
    provider: str,
    aspect_ratio: str = "9:16",
    style_anchor: str = "",
) -> str:
    """Use LLM to rewrite a scene prompt optimized for a specific AI video provider.

    Falls back to token-append enhancement if LLM call fails.
    """
    instruction = _PROVIDER_REWRITE_INSTRUCTIONS.get(provider)
    if not instruction:
        return _enhance_runway_prompt(prompt, aspect_ratio)

    framing = "vertical 9:16 portrait" if aspect_ratio == "9:16" else "horizontal 16:9 landscape"

    system = (
        f"{instruction}\n"
        f"Framing: {framing}.\n"
    )
    if style_anchor:
        system += f"Style anchor (MUST preserve): {style_anchor}\n"
    system += "Return ONLY the rewritten prompt text. No explanations."

    try:
        from app.services.llm_service import _get_openai
        client = _get_openai()
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Original prompt:\n{prompt}"},
            ],
            temperature=0.4,
            max_tokens=600,
        )
        rewritten = response.choices[0].message.content.strip()
        if len(rewritten) < 20:
            raise ValueError("Rewritten prompt too short")
        logger.debug(
            "Prompt rewritten for {} — {} → {} chars",
            provider, len(prompt), len(rewritten),
        )
        return rewritten
    except Exception as exc:
        logger.warning(
            "Prompt rewrite failed for {} ({}), using token-append fallback",
            provider, exc,
        )
        enhancer = {
            "runway": _enhance_runway_prompt,
            "stability": _enhance_stability_prompt,
            "kling": _enhance_kling_prompt,
        }.get(provider, _enhance_runway_prompt)
        return enhancer(prompt, aspect_ratio)


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
            # Detect billing/credit issues — skip retries immediately
            if create_response.status_code == 400:
                error_text = create_response.text.lower()
                if any(kw in error_text for kw in ("credit", "billing", "quota", "plan")):
                    raise RuntimeError(
                        f"Runway billing/credit issue (not retryable): "
                        f"{create_response.text[:200]}"
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
        # Detect billing/credit issues — skip retries immediately
        if img_response.status_code in (400, 402, 403):
            error_text = img_response.text.lower()
            if any(kw in error_text for kw in ("credit", "billing", "quota", "plan", "insufficient")):
                raise RuntimeError(
                    f"Stability billing/credit issue (not retryable): "
                    f"{img_response.text[:200]}"
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
    style_anchor: str = "",
) -> Path:
    """Route generation to the correct provider with optional prompt rewriting."""
    duration = max(2, round(scene.duration_seconds))

    # LLM-based prompt rewriting (opt-in)
    if getattr(settings, "prompt_rewriting_enabled", False):
        scene.ai_prompt = await _rewrite_prompt_for_provider(
            scene.ai_prompt, provider, aspect_ratio, style_anchor
        )

    if provider == "runway":
        # Runway API max duration is 10s — should be handled at planning time
        if duration > 10:
            logger.warning(
                "Scene {} duration {}s exceeds Runway 10s max "
                "(should have been split at planning time)",
                scene.scene_number, duration,
            )
        runway_dur = min(duration, 10)
        return await generate_ai_video_runway(scene.ai_prompt, runway_dur, aspect_ratio)
    elif provider == "stability":
        return await generate_ai_video_stability(scene.ai_prompt, duration)
    elif provider == "kling":
        return await generate_ai_video_kling(scene.ai_prompt, duration, aspect_ratio)
    raise ValueError(f"Unknown AI video provider: {provider}")


async def _fetch_stock_for_scene(scene: Scene, orientation: str) -> Path:
    """Fetch a single stock clip for a scene via Pexels, with query expansion and placeholder fallback."""
    try:
        clips = await fetch_clips(
            queries=[scene.stock_query],
            orientation=orientation,
            clips_per_query=1,
            narrations=[scene.narration],
            expand_queries=True,
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
    total_scenes: int = 5,
) -> Path:
    """
    Generate a visual for a single scene with full fallback chain:
        0. AI image + Ken Burns  (if ai_images_enabled — cheapest)
        1. Primary AI provider   (if visual_type == "ai_generated")
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

    # ── AI Images path (DALL-E + Ken Burns) — much cheaper than video gen ──
    if settings.ai_images_enabled:
        try:
            from app.services.image_gen_service import (
                estimate_image_cost,
                generate_scene_image,
            )
            from app.services.media_service import image_to_video_clip

            img_cost = estimate_image_cost(
                settings.ai_images_model,
                settings.ai_images_size,
                settings.ai_images_quality,
            )

            if not await check_budget(img_cost):
                logger.warning(
                    "Daily budget exceeded, skipping AI image for scene {}",
                    scene.scene_number,
                )
            else:
                image_path = await generate_scene_image(
                    prompt=scene.ai_prompt,
                    size=settings.ai_images_size,
                    model=settings.ai_images_model,
                    quality=settings.ai_images_quality,
                )
                video_path = image_to_video_clip(
                    image_path=image_path,
                    duration=scene.duration_seconds,
                    scene_number=scene.scene_number,
                    total_scenes=total_scenes,
                )
                await record_spend(img_cost)
                scene.video_path = str(video_path)
                scene.image_path = str(image_path)
                scene.generation_cost = img_cost
                scene.provider_used = settings.ai_images_model
                logger.info(
                    "Scene {} generated via AI image + Ken Burns (${:.2f})",
                    scene.scene_number, img_cost,
                )
                return video_path
        except Exception as exc:
            logger.warning(
                "AI image generation failed for scene {}: {} — trying AI video providers",
                scene.scene_number, exc,
            )

    primary = settings.ai_video_primary_provider
    secondary = settings.ai_video_secondary_provider

    # Budget check before any AI call
    estimated = estimate_cost(scene.duration_seconds, primary)
    if estimated > settings.ai_video_max_cost_per_video:
        logger.warning(
            "Scene {} estimated cost ${:.2f} exceeds per-scene budget "
            "(cap=${:.2f}), using stock",
            scene.scene_number,
            estimated,
            settings.ai_video_max_cost_per_video,
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


# ── Visual Continuity (Style Anchor) ────────────────────────────

_STYLE_TOKENS: dict[str, list[str]] = {
    "lighting": [
        "golden hour", "neon-lit", "overcast", "backlit", "low-key",
        "high-key", "rembrandt", "warm lighting", "cold lighting",
        "volumetric lighting", "natural light", "dramatic lighting",
        "torch-lit", "candlelight", "moonlight",
    ],
    "color": [
        "warm tones", "cool tones", "muted", "saturated", "desaturated",
        "amber", "blue-grey", "cyan", "teal", "orange-teal", "monochrome",
        "pastel", "neon", "earthy", "golden", "sepia", "warm amber",
    ],
    "aesthetic": [
        "cinematic", "documentary", "film noir", "vintage", "futuristic",
        "minimalist", "gritty", "ethereal", "surreal", "photorealistic",
        "8k", "film grain", "shallow depth of field",
    ],
}


def _build_style_anchor(scenes: list[Scene]) -> str:
    """Extract visual DNA from Scene 1's ai_prompt for cross-scene consistency.

    Scans the first scene's prompt for lighting, color, and aesthetic tokens
    and returns a concise style anchor string.
    """
    if not scenes or not scenes[0].ai_prompt:
        return ""

    first_prompt = scenes[0].ai_prompt.lower()

    found_tokens: list[str] = []
    for tokens in _STYLE_TOKENS.values():
        for token in tokens:
            if token in first_prompt:
                found_tokens.append(token)

    if not found_tokens:
        return ""

    return "VISUAL CONSISTENCY: maintain " + ", ".join(found_tokens[:8]) + "."


def _apply_style_anchor(scene: Scene, anchor: str) -> None:
    """Prepend the visual style anchor to a scene's ai_prompt."""
    if not anchor or not scene.ai_prompt:
        return
    if anchor.lower() in scene.ai_prompt.lower():
        return  # Already contains the anchor
    scene.ai_prompt = f"{anchor} {scene.ai_prompt}"


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
    # Apply visual style anchor for cross-scene consistency
    if getattr(settings, "visual_continuity_enabled", True) and len(scenes) > 1:
        anchor = _build_style_anchor(scenes)
        if anchor:
            for scene in scenes[1:]:
                _apply_style_anchor(scene, anchor)
            logger.info("Visual style anchor applied — '{}'", anchor[:80])

    semaphore = asyncio.Semaphore(max_concurrent)

    total_scenes = len(scenes)

    async def _generate_with_limit(scene: Scene) -> Path:
        async with semaphore:
            return await generate_scene_visual(scene, video_format, project_id, total_scenes)

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
