"""
LLM Service — generates video scripts via OpenAI or Anthropic.

Each provider is isolated behind a common interface so the caller
never deals with SDK specifics.
"""

from __future__ import annotations

import json
from enum import StrEnum

import httpx
from anthropic import AsyncAnthropic
from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.security.content_moderation import is_content_safe
from app.security.sanitizers import sanitize_topic

settings = get_settings()

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
SHORT_SYSTEM_PROMPT = (
    "You are a viral YouTube Shorts scriptwriter. "
    "Write a script that is 30-60 seconds when spoken aloud. "
    "Use a punchy hook in the first line, maintain high energy, "
    "and end with a call to action. "
    "Return ONLY a JSON object with keys: "
    '"title", "script", "tags" (list of 5-8 tags), "description" (1-2 sentences).'
)

LONG_SYSTEM_PROMPT = (
    "You are an expert YouTube long-form scriptwriter. "
    "Write a script that is 5-10 minutes when spoken aloud. "
    "Structure it with a hook, intro, 3-5 key sections, and a strong outro. "
    "Return ONLY a JSON object with keys: "
    '"title", "script", "tags" (list of 8-12 tags), "description" (2-3 sentences), '
    '"sections" (list of {"heading": str, "content": str}).'
)


def _system_prompt(video_format: str) -> str:
    return SHORT_SYSTEM_PROMPT if video_format == "short" else LONG_SYSTEM_PROMPT


# ── Retry decorator (shared) ────────────────────────────────
_llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "LLM call attempt {} failed, retrying in {:.1f}s …",
        rs.attempt_number,
        rs.next_action.sleep,
    ),
)


# ── OpenAI implementation ────────────────────────────────────
@_llm_retry
async def _generate_openai(topic: str, video_format: str) -> dict:
    client = _get_openai()
    logger.info("OpenAI request — model={} topic='{}'", settings.openai_model, topic)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _system_prompt(video_format)},
            {"role": "user", "content": f"Topic: {topic}"},
        ],
        temperature=0.9,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    logger.debug("OpenAI raw response length: {} chars", len(raw))
    return json.loads(raw)


# ── Anthropic implementation ─────────────────────────────────
@_llm_retry
async def _generate_anthropic(topic: str, video_format: str) -> dict:
    client = _get_anthropic()
    logger.info("Anthropic request — model={} topic='{}'", settings.anthropic_model, topic)

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=_system_prompt(video_format),
        messages=[
            {"role": "user", "content": f"Topic: {topic}"},
        ],
    )

    raw = response.content[0].text
    logger.debug("Anthropic raw response length: {} chars", len(raw))

    # Anthropic may wrap JSON in markdown fences — strip them
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # Handle ```json, ```python, or plain ``` openers
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1 :] if first_newline != -1 else cleaned[3:]
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]

    return json.loads(cleaned.strip())


# ── Public interface ─────────────────────────────────────────
async def generate_script(
    topic: str,
    video_format: str = "short",
    provider: LLMProvider = LLMProvider.OPENAI,
) -> dict:
    """
    Generate a video script for the given topic.

    Security:
        - Sanitizes input to prevent prompt injection
        - Moderates content for policy violations
        - Wraps user input in XML tags for LLM clarity

    Returns a dict with at minimum: title, script, tags, description.

    Raises:
        ValueError: If topic is invalid or violates content policy
    """
    logger.info(
        "Generating {} script — provider={} topic='{}'",
        video_format,
        provider.value,
        topic[:50] + "..." if len(topic) > 50 else topic,
    )

    # 1. Content moderation check
    is_safe, violation_reason = await is_content_safe(topic)
    if not is_safe:
        logger.warning(f"Content moderation blocked topic: {violation_reason}")
        raise ValueError(
            f"Topic violates content policy ({violation_reason}). "
            "Please provide a different topic."
        )

    # 2. Sanitize topic to prevent prompt injection
    # This wraps the topic in <user_input> tags and validates characters
    sanitized_topic = sanitize_topic(topic)

    # 3. Generate script with sanitized topic
    if provider == LLMProvider.OPENAI:
        result = await _generate_openai(sanitized_topic, video_format)
    else:
        result = await _generate_anthropic(sanitized_topic, video_format)

    # Validate required keys and types
    for key in ("title", "script", "tags", "description"):
        if key not in result:
            raise ValueError(f"LLM response missing required key: '{key}'")

    if not isinstance(result["tags"], list):
        raise ValueError("LLM response 'tags' must be a list")
    if not isinstance(result["script"], str) or not result["script"].strip():
        raise ValueError("LLM response 'script' must be a non-empty string")

    logger.info("Script generated — title='{}'", result["title"])
    return result
