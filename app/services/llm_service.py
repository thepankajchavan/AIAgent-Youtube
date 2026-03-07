"""
LLM Service — generates video scripts via OpenAI or Anthropic.

4-layer architecture:
  Layer 1: _call_openai / _call_anthropic
           Single API call with network-level retry (tenacity).
  Layer 2: _parse_and_validate
           Extract JSON, validate required keys, ensure scenes exist.
  Layer 3: _generate_with_quality_retry
           Quality validation loop — retries with corrective LLM feedback.
  Layer 4: generate_script (public API)
           Content moderation, sanitization, provider fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

import httpx
import openai
from anthropic import AsyncAnthropic
from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import QueryCache
from app.core.circuit_breaker import with_anthropic_breaker, with_openai_breaker
from app.core.config import get_settings
from app.security.content_moderation import is_content_safe
from app.security.sanitizers import sanitize_topic

settings = get_settings()

# ── Constants ─────────────────────────────────────────────────
MAX_QUALITY_RETRIES = 2  # Corrective feedback retries (on top of network retries)

# ── Clients (lazy singletons) ────────────────────────────────
_openai_client: AsyncOpenAI | None = None
_anthropic_client: AsyncAnthropic | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ── Provider enum ────────────────────────────────────────────
class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# ── Prompt templates ─────────────────────────────────────────
SHORT_SYSTEM_PROMPT = """\
You are a viral YouTube Shorts scriptwriter for faceless channels. You write scroll-stopping narrations over stock footage.

CONTENT NICHES: fascinating facts, motivation, science, technology, space, history, mysteries, psychology.

SCRIPT RULES:
1. Length: STRICTLY 80-100 words. Count carefully. This produces ~30-40 seconds of TTS audio.
2. Structure (4-5 visual beats, each separated by a blank line):
   - HOOK (1 sentence): A shocking claim, wild question, or jaw-dropping fact that stops the scroll instantly.
   - BUILD 1 (1-2 sentences): Expand with a vivid, concrete detail that pulls the viewer deeper.
   - BUILD 2 (1-2 sentences): Add another layer — a contrast, escalation, or surprising angle.
   - CLIMAX (1 sentence): The biggest reveal, twist, or mind-blowing conclusion.
   - KICKER (optional, 1 sentence): A short punchy closer that leaves the viewer thinking.
3. Do NOT include any "like", "subscribe", "follow", or CTA text — a pre-made outro handles this.
4. Short, punchy sentences. Conversational and confident — as if telling a friend something incredible.
5. NEVER use markdown formatting (no **, *, #, __). Plain text only.
6. Open with "you" or a direct address to make it personal. Example: "You won't believe..." or "Right now, there's a..."
7. Each beat should correspond to a concrete, filmable scene found as stock footage:
   nature, cities, people, technology, space, underwater, animals, historical imagery, time-lapses, aerial shots, etc.

SEARCH KEYWORDS:
- For each scene/beat, provide 2-3 specific Pexels stock video search terms.
- Be specific and visual: "aerial city skyline night lights" beats "city". "close up human eye iris" beats "eye".
- Think: what would a viewer SEE on screen while hearing this narration?

TAGS & SEO:
- Provide 10-15 YouTube tags: mix broad viral tags (e.g. "facts", "didyouknow", "mindblown") with niche-specific tags for the topic.
- Provide 5-8 hashtags WITH # symbol for the video description (YouTube shows the last 3 hashtags above the title).
- Pick the best YouTube category for this content from: education, science, entertainment, howto, people, comedy, news.
- Write a 2-3 sentence SEO-optimized description with relevant keywords that hooks viewers from search results.

Return ONLY a JSON object — no markdown fences, no explanation:
{
  "title": "Catchy YouTube title (under 60 chars, curiosity-driven, no clickbait ALL CAPS)",
  "script": "Full narration text with blank lines between beats",
  "scenes": [
    {"narration": "Hook text...", "search_keywords": ["specific keyword 1", "specific keyword 2"]},
    {"narration": "Build 1 text...", "search_keywords": ["specific keyword 1", "specific keyword 2"]},
    ...
  ],
  "tags": ["tag1", "tag2", ...] (10-15 YouTube tags, no # symbol),
  "hashtags": ["#Shorts", "#Facts", "#Science", "#Viral", "#MindBlown"],
  "category": "education",
  "description": "2-3 sentence SEO-optimized YouTube description with keywords"
}\
"""

LONG_SYSTEM_PROMPT = (
    "You are an expert YouTube long-form scriptwriter. "
    "Write a script that is 5-10 minutes when spoken aloud. "
    "Structure it with a hook, intro, 3-5 key sections, and a strong outro. "
    "Return ONLY a JSON object with keys: "
    '"title", "script", '
    '"tags" (list of 12-18 viral + niche tags, no # symbol), '
    '"hashtags" (list of 5-8 hashtags WITH # for the description), '
    '"category" (one of: education, science, entertainment, howto, people, comedy, news), '
    '"description" (2-3 SEO-optimized sentences with keywords), '
    '"sections" (list of {"heading": str, "content": str}).'
)


def _system_prompt(video_format: str, target_duration: int | None = None) -> str:
    if video_format != "short":
        return LONG_SYSTEM_PROMPT
    if target_duration:
        # ~2.5 words/sec at ElevenLabs TTS speed
        target_words = int(target_duration * 2.5)
        word_min = max(30, target_words - 10)
        word_max = target_words + 10
        return SHORT_SYSTEM_PROMPT.replace(
            "STRICTLY 80-100 words. Count carefully. This produces ~30-40 seconds of TTS audio.",
            f"STRICTLY {word_min}-{word_max} words. Count carefully. "
            f"This produces ~{target_duration} seconds of TTS audio.",
        )
    return SHORT_SYSTEM_PROMPT


def _user_prompt(
    topic: str,
    video_format: str,
    search_context: str | None = None,
    target_duration: int | None = None,
) -> str:
    context_block = ""
    if search_context:
        context_block = (
            "\n\n--- REAL-TIME RESEARCH ---\n"
            "Use the following recent information to make the script accurate, "
            "timely, and factual. Reference specific details, names, dates, "
            "and statistics from this research:\n\n"
            f"{search_context}\n"
            "--- END RESEARCH ---\n\n"
        )

    if video_format == "short":
        if target_duration:
            target_words = int(target_duration * 2.5)
            word_min = max(30, target_words - 10)
            word_max = target_words + 10
            word_reminder = f"{word_min}-{word_max} words"
        else:
            word_reminder = "80-100 words"
        return (
            f"Write a viral YouTube Short script about: {topic}\n"
            f"{context_block}"
            "Make it fascinating, dramatic, and impossible to scroll past. "
            f"Remember: {word_reminder}, 4-5 visual beats, and specific "
            "stock footage search keywords for each scene."
        )
    return f"Write a detailed YouTube video script about: {topic}{context_block}"


# ═════════════════════════════════════════════════════════════
# LAYER 1 — Single API call with network-level retry
# ═════════════════════════════════════════════════════════════

# Retry on: network errors, rate limits, timeouts, server errors
_RETRYABLE_ERRORS = (
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.ConnectError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.InternalServerError,
)

_network_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=3, max=90),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    before_sleep=lambda rs: logger.warning(
        "LLM network retry — attempt {} failed ({}), retrying in {:.1f}s …",
        rs.attempt_number,
        type(rs.outcome.exception()).__name__ if rs.outcome else "unknown",
        rs.next_action.sleep,
    ),
)


@with_openai_breaker(fallback_to_anthropic=False)
@_network_retry
async def _call_openai(messages: list[dict]) -> str:
    """Single OpenAI API call. Returns raw response text."""
    client = _get_openai()
    logger.debug("OpenAI API call — model={} messages={}", settings.openai_model, len(messages))

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=messages,
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    logger.debug("OpenAI response — {} chars", len(raw))
    return raw


@with_anthropic_breaker()
@_network_retry
async def _call_anthropic(messages: list[dict], system: str) -> str:
    """Single Anthropic API call. Returns raw response text."""
    client = _get_anthropic()
    logger.debug(
        "Anthropic API call — model={} messages={}", settings.anthropic_model, len(messages)
    )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        temperature=0.7,
        system=system,
        messages=messages,
    )

    raw = response.content[0].text
    logger.debug("Anthropic response — {} chars", len(raw))
    return raw


# ═════════════════════════════════════════════════════════════
# LAYER 2 — JSON extraction and structural validation
# ═════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict:
    """
    Robustly extract JSON from LLM response.

    Handles: raw JSON, markdown-fenced JSON, JSON embedded in prose,
    trailing commas, and other common LLM quirks.
    """
    text = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl != -1 else text[3:]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    text = text.strip()

    # Attempt 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: find outermost { ... } in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Attempt 3: fix trailing commas (common LLM error)
            cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("No valid JSON found in LLM response", text[:200], 0)


def _validate_required_keys(result: dict) -> None:
    """Validate that all required keys exist with correct types."""
    for key in ("title", "script", "tags", "description"):
        if key not in result:
            raise ValueError(f"LLM response missing required key: '{key}'")

    if not isinstance(result["tags"], list):
        raise ValueError("LLM response 'tags' must be a list")
    if not isinstance(result["script"], str) or not result["script"].strip():
        raise ValueError("LLM response 'script' must be a non-empty string")


def _ensure_scenes(result: dict) -> None:
    """Ensure result has a valid scenes array, building from script if needed."""
    scenes_valid = False

    if "scenes" in result and isinstance(result["scenes"], list) and len(result["scenes"]) >= 2:
        # Validate each scene
        all_ok = True
        for i, scene in enumerate(result["scenes"]):
            if not isinstance(scene, dict):
                all_ok = False
                break
            if "narration" not in scene:
                scene["narration"] = ""
            if "search_keywords" not in scene or not isinstance(scene["search_keywords"], list):
                scene["search_keywords"] = []
        scenes_valid = all_ok

    if not scenes_valid:
        # Rebuild scenes from script paragraphs + tags
        paragraphs = [p.strip() for p in result["script"].split("\n\n") if p.strip()]
        tags = result.get("tags", [])
        result["scenes"] = [
            {
                "narration": para,
                "search_keywords": [tags[i]] if i < len(tags) else [],
            }
            for i, para in enumerate(paragraphs)
        ]
        logger.warning(
            "Rebuilt {} scenes from script paragraphs (LLM didn't return valid scenes)",
            len(result["scenes"]),
        )


def _strip_markdown(result: dict) -> None:
    """Remove any markdown formatting from the script text."""
    s = result["script"]
    s = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s)
    s = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    result["script"] = s


def _parse_and_validate(raw_text: str) -> dict:
    """Layer 2: extract JSON, validate keys, ensure scenes, clean markdown."""
    result = _extract_json(raw_text)
    _validate_required_keys(result)
    _ensure_scenes(result)
    _strip_markdown(result)
    return result


# ═════════════════════════════════════════════════════════════
# LAYER 3 — Quality validation with corrective feedback retry
# ═════════════════════════════════════════════════════════════

_CTA_PATTERN = re.compile(
    r"\b(subscribe|like this video|follow me|comment below|share this|"
    r"hit the bell|turn on notifications|smash that|let me know)\b",
    re.IGNORECASE,
)


def _validate_script_quality(result: dict, video_format: str) -> list[str]:
    """
    Validate script quality. Returns list of issues (empty = perfect).

    Checks: word count, scene count, search keywords, CTA text, markdown.
    """
    issues: list[str] = []
    script = result.get("script", "")
    word_count = len(script.split())

    if video_format == "short":
        if word_count < 60:
            issues.append(f"Script too short: {word_count} words (need 80-100)")
        elif word_count > 130:
            issues.append(f"Script too long: {word_count} words (need 80-100)")

        scenes = result.get("scenes", [])
        if len(scenes) < 3:
            issues.append(f"Only {len(scenes)} scenes (need 4-5)")
        elif len(scenes) > 7:
            issues.append(f"Too many scenes: {len(scenes)} (need 4-5)")

        # Check scenes have search keywords
        empty_kw = sum(1 for s in scenes if not s.get("search_keywords"))
        if empty_kw > 0:
            issues.append(f"{empty_kw} scene(s) missing search keywords")

    # CTA detection
    cta_match = _CTA_PATTERN.search(script)
    if cta_match:
        issues.append(f"Contains CTA text: '{cta_match.group()}'")

    # Markdown detection
    if re.search(r"\*\*[^*]+\*\*|__[^_]+__", script):
        issues.append("Contains markdown formatting")

    # Title length check
    title = result.get("title", "")
    if len(title) > 70:
        issues.append(f"Title too long: {len(title)} chars (max 60)")

    return issues


async def _generate_with_quality_retry(
    topic: str,
    video_format: str,
    provider: LLMProvider,
    search_context: str | None = None,
    target_duration: int | None = None,
) -> dict:
    """
    Layer 3: Generate script with quality validation and corrective feedback.

    On quality issues, sends the LLM's previous output back with specific
    corrections, giving it a chance to fix the problems (multi-turn).

    Up to MAX_QUALITY_RETRIES corrective retries.
    """
    system = _system_prompt(video_format, target_duration)
    user_msg = _user_prompt(topic, video_format, search_context, target_duration)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    best_result: dict | None = None
    best_issue_count = 999

    for attempt in range(MAX_QUALITY_RETRIES + 1):
        try:
            # Call the appropriate provider
            if provider == LLMProvider.OPENAI:
                raw = await _call_openai(
                    [{"role": "system", "content": system}] + messages
                )
            else:
                raw = await _call_anthropic(messages, system)

            # Parse and validate structure
            result = _parse_and_validate(raw)

            # Quality check
            issues = _validate_script_quality(result, video_format)
            issue_count = len(issues)

            # Track the best result we've seen
            if issue_count < best_issue_count:
                best_result = result
                best_issue_count = issue_count

            if not issues:
                word_count = len(result["script"].split())
                logger.info(
                    "Script quality PERFECT — {} words, {} scenes, attempt {}/{}",
                    word_count,
                    len(result.get("scenes", [])),
                    attempt + 1,
                    MAX_QUALITY_RETRIES + 1,
                )
                return result

            # Quality issues found — retry with corrective feedback
            if attempt < MAX_QUALITY_RETRIES:
                logger.warning(
                    "Script quality issues (attempt {}/{}): {}",
                    attempt + 1,
                    MAX_QUALITY_RETRIES + 1,
                    issues,
                )

                # Build corrective multi-turn conversation
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The script has these quality issues that MUST be fixed:\n"
                            + "\n".join(f"- {issue}" for issue in issues)
                            + "\n\nPlease regenerate the COMPLETE corrected JSON. "
                            "Fix every issue listed above. Return ONLY the JSON."
                        ),
                    }
                )
            else:
                logger.warning(
                    "Accepting script with remaining issues after {} attempts: {}",
                    MAX_QUALITY_RETRIES + 1,
                    issues,
                )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(
                "Script parse/validation error (attempt {}/{}): {}",
                attempt + 1,
                MAX_QUALITY_RETRIES + 1,
                str(e)[:150],
            )
            if attempt < MAX_QUALITY_RETRIES:
                # Reset conversation with corrective instructions
                messages = [
                    {
                        "role": "user",
                        "content": (
                            f"{user_msg}\n\n"
                            f"Your previous response had this error: {e}\n\n"
                            "CRITICAL: Return ONLY valid JSON with ALL required keys: "
                            "title, script, scenes, tags, description. "
                            "No markdown fences, no explanation — ONLY the JSON object."
                        ),
                    }
                ]
            elif best_result is not None:
                return best_result
            else:
                raise

    # Return the best result we got
    if best_result is not None:
        return best_result

    raise RuntimeError("Script generation failed: no valid result after all attempts")


# ═════════════════════════════════════════════════════════════
# LAYER 4 — Public API with provider fallback
# ═════════════════════════════════════════════════════════════

async def generate_script(
    topic: str,
    video_format: str = "short",
    provider: LLMProvider = LLMProvider.OPENAI,
    search_context: str | None = None,
    target_duration: int | None = None,
) -> dict:
    """
    Generate a video script for the given topic.

    Full pipeline:
      1. Content moderation check
      2. Input sanitization (prompt injection prevention)
      3. Script generation with quality retry loop
      4. Automatic provider fallback if primary fails

    Args:
        target_duration: Target video duration in seconds. Adjusts word count
            in the LLM prompt (~2.5 words/sec TTS rate).

    Returns a dict with: title, script, scenes, tags, description.

    Raises:
        ValueError: If topic is invalid or violates content policy.
    """
    logger.info(
        "Generating {} script — provider={} topic='{}'",
        video_format,
        provider.value,
        topic[:50] + "..." if len(topic) > 50 else topic,
    )

    # 0. Check cache (skip for web-search-augmented scripts — time-sensitive)
    cache_key = None
    if search_context is None:
        topic_hash = hashlib.md5(f"{topic}:{video_format}".encode()).hexdigest()
        cache_key = f"script:{topic_hash}"
        cached = await QueryCache.get(cache_key)
        if cached:
            logger.info("Script cache HIT — topic='{}'", topic[:50])
            return json.loads(cached)

    # 1. Content moderation check
    is_safe, violation_reason = await is_content_safe(topic)
    if not is_safe:
        logger.warning(f"Content moderation blocked topic: {violation_reason}")
        raise ValueError(
            f"Topic violates content policy ({violation_reason}). "
            "Please provide a different topic."
        )

    # 2. Sanitize topic to prevent prompt injection
    sanitized_topic = sanitize_topic(topic)

    # 3. Generate with primary provider + quality retry
    try:
        result = await _generate_with_quality_retry(
            sanitized_topic, video_format, provider, search_context, target_duration
        )
        logger.info(
            "Script generated — provider={} title='{}' words={} scenes={}",
            provider.value,
            result["title"],
            len(result["script"].split()),
            len(result.get("scenes", [])),
        )
        # Cache result for 7 days (only non-search-augmented)
        if cache_key:
            await QueryCache.set(cache_key, json.dumps(result), ttl=7 * 24 * 3600)
        return result

    except Exception as primary_err:
        # 4. Provider fallback — try the other provider
        fallback = (
            LLMProvider.ANTHROPIC if provider == LLMProvider.OPENAI else LLMProvider.OPENAI
        )
        logger.warning(
            "Primary provider {} failed ({}), falling back to {} …",
            provider.value,
            type(primary_err).__name__,
            fallback.value,
        )

        try:
            result = await _generate_with_quality_retry(
                sanitized_topic, video_format, fallback, search_context, target_duration
            )
            logger.info(
                "Script generated via FALLBACK — provider={} title='{}' words={} scenes={}",
                fallback.value,
                result["title"],
                len(result["script"].split()),
                len(result.get("scenes", [])),
            )
            if cache_key:
                await QueryCache.set(cache_key, json.dumps(result), ttl=7 * 24 * 3600)
            return result

        except Exception as fallback_err:
            logger.error(
                "Both providers failed — primary={} ({}) fallback={} ({})",
                provider.value,
                primary_err,
                fallback.value,
                fallback_err,
            )
            # Raise the original error as it's more relevant
            raise primary_err from fallback_err
