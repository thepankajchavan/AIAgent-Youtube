"""
TTS Service — converts script text to speech via ElevenLabs.

Streams audio bytes to disk and returns the file path.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx
from loguru import logger
from num2words import num2words
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.circuit_breaker import with_elevenlabs_breaker
from app.core.config import get_settings
from app.services.media_service import normalize_audio

settings = get_settings()

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

# Common unit expansions for TTS pronunciation
_UNIT_MAP = {
    "km": "kilometers",
    "mph": "miles per hour",
    "kph": "kilometers per hour",
    "kg": "kilograms",
    "lb": "pounds",
    "lbs": "pounds",
    "ft": "feet",
    "mi": "miles",
    "cm": "centimeters",
    "mm": "millimeters",
    "m": "meters",
    "oz": "ounces",
    "°C": "degrees Celsius",
    "°F": "degrees Fahrenheit",
}


def _preprocess_text_for_tts(text: str) -> str:
    """Clean up text so the TTS engine pronounces numbers, units, and
    acronyms naturally instead of reading them as raw characters.
    """

    # Currency with magnitude suffix: $2.5M → two point five million dollars
    def _expand_currency(m: re.Match) -> str:
        symbol = m.group(1)
        number = m.group(2)
        suffix = (m.group(3) or "").upper()
        magnitude = {"K": "thousand", "M": "million", "B": "billion", "T": "trillion"}.get(
            suffix, ""
        )
        currency = "dollars" if symbol == "$" else "euros" if symbol == "€" else "pounds"
        parts = number.split(".")
        if len(parts) == 2 and parts[1]:
            word_num = f"{num2words(int(parts[0]))} point {num2words(int(parts[1]))}"
        else:
            word_num = num2words(int(parts[0]))
        return " ".join(filter(None, [word_num, magnitude, currency]))

    text = re.sub(r"([$€£])(\d+(?:\.\d+)?)\s*([KkMmBbTt])?(?=\s|[.,;!?]|$)", _expand_currency, text)

    # Percentages: 99.9% → ninety-nine point nine percent
    def _expand_pct(m: re.Match) -> str:
        num_str = m.group(1)
        parts = num_str.split(".")
        if len(parts) == 2 and parts[1]:
            return f"{num2words(int(parts[0]))} point {num2words(int(parts[1]))} percent"
        return f"{num2words(int(parts[0]))} percent"

    text = re.sub(r"(\d+(?:\.\d+)?)%", _expand_pct, text)

    # Ordinals: 1st, 2nd, 3rd, 4th → first, second, third, fourth
    def _expand_ordinal(m: re.Match) -> str:
        return num2words(int(m.group(1)), to="ordinal")

    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", _expand_ordinal, text)

    # Numbers with units: "60 mph" → "sixty miles per hour"
    unit_pattern = r"\b(\d+(?:\.\d+)?)\s*(" + "|".join(re.escape(u) for u in _UNIT_MAP) + r")\b"

    def _expand_unit(m: re.Match) -> str:
        num_str = m.group(1)
        unit = m.group(2)
        parts = num_str.split(".")
        if len(parts) == 2 and parts[1]:
            word_num = f"{num2words(int(parts[0]))} point {num2words(int(parts[1]))}"
        else:
            word_num = num2words(int(parts[0]))
        return f"{word_num} {_UNIT_MAP[unit]}"

    text = re.sub(unit_pattern, _expand_unit, text)

    # Decimal numbers: 3.14 → three point one four (must run before year/integer patterns)
    def _expand_decimal(m: re.Match) -> str:
        whole = m.group(1)
        frac = m.group(2)
        return f"{num2words(int(whole))} point {' '.join(num2words(int(d)) for d in frac)}"

    text = re.sub(r"\b(\d+)\.(\d+)\b", _expand_decimal, text)

    # Years (4-digit numbers 1000-2099 appearing alone): 2024 → twenty twenty-four
    def _expand_year(m: re.Match) -> str:
        year = int(m.group(1))
        if 2000 <= year <= 2009:
            return num2words(year)
        if 2010 <= year <= 2099:
            century = year // 100
            remainder = year % 100
            return f"{num2words(century)} {num2words(remainder)}"
        if 1000 <= year <= 1999:
            high = year // 100
            low = year % 100
            if low == 0:
                return f"{num2words(high)} hundred"
            return f"{num2words(high)} {num2words(low)}"
        return m.group(0)

    text = re.sub(r"\b(1\d{3}|20\d{2})\b", _expand_year, text)

    # Large plain numbers: 6000000 → six million
    def _expand_number(m: re.Match) -> str:
        return num2words(int(m.group(0)))

    text = re.sub(r"\b\d{4,}\b", _expand_number, text)

    # Remaining small integers (1-999) that weren't already converted
    def _expand_small_number(m: re.Match) -> str:
        return num2words(int(m.group(0)))

    text = re.sub(r"\b\d{1,3}\b", _expand_small_number, text)

    # Acronyms: 2-4 consecutive uppercase letters → dotted (US → U.S., NASA → N.A.S.A.)
    def _expand_acronym(m: re.Match) -> str:
        return ".".join(m.group(0)) + "."

    text = re.sub(r"\b([A-Z]{2,4})\b", _expand_acronym, text)

    return text


def _check_character_budget(char_count: int) -> None:
    """Warn or reject based on monthly character budget."""
    limit = settings.elevenlabs_monthly_char_limit
    if char_count > limit:
        raise ValueError(
            f"Text ({char_count} chars) exceeds monthly ElevenLabs limit ({limit} chars). "
            "Reduce script length or wait for quota reset."
        )
    usage_pct = (char_count / limit) * 100
    if usage_pct >= 80:
        logger.warning(
            "ElevenLabs character budget warning: {} chars = {:.0f}% of {} monthly limit",
            char_count,
            usage_pct,
            limit,
        )


@with_elevenlabs_breaker()
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "ElevenLabs TTS attempt {} failed, retrying in {:.1f}s …",
        rs.attempt_number,
        rs.next_action.sleep,
    ),
)
async def generate_speech(
    text: str,
    voice_id: str | None = None,
    output_filename: str | None = None,
    model_id: str | None = None,
    stability: float | None = None,
    similarity_boost: float | None = None,
    style: float | None = None,
) -> Path:
    """
    Convert text to speech and save as MP3.

    Args:
        text: The script text to convert.
        voice_id: ElevenLabs voice ID (defaults to config value).
        output_filename: Name for the output file (auto-generated if None).
        model_id: ElevenLabs model ID (defaults to config value).
        stability: Voice stability 0.0-1.0 (defaults to config value).
        similarity_boost: Voice similarity boost 0.0-1.0 (defaults to config value).
        style: Style exaggeration 0.0-1.0 (defaults to config value).

    Returns:
        Path to the saved audio file.
    """
    # Resolve defaults from settings
    voice_id = voice_id or settings.elevenlabs_voice_id
    model_id = model_id or settings.elevenlabs_model
    stability = stability if stability is not None else settings.elevenlabs_stability
    similarity_boost = (
        similarity_boost
        if similarity_boost is not None
        else settings.elevenlabs_similarity_boost
    )
    style = style if style is not None else settings.elevenlabs_style
    output_format = settings.elevenlabs_output_format

    output_dir = settings.audio_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = f"tts_{uuid.uuid4().hex[:12]}.mp3"
    output_path = output_dir / output_filename

    # Preprocess text for better pronunciation
    processed_text = _preprocess_text_for_tts(text)

    # Check character budget
    char_count = len(processed_text)
    _check_character_budget(char_count)

    url = (
        f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}/stream"
        f"?output_format={output_format}"
    )

    payload = {
        "text": processed_text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }

    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    logger.info(
        "ElevenLabs TTS request — voice={} chars={} model={} format={} "
        "style={} stability={} (budget: {}/{})",
        voice_id,
        char_count,
        model_id,
        output_format,
        style,
        stability,
        char_count,
        settings.elevenlabs_monthly_char_limit,
    )

    bytes_written = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()

            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    bytes_written += len(chunk)

    logger.info(
        "TTS audio saved — path={} size={:.1f}KB",
        output_path,
        bytes_written / 1024,
    )

    # Normalize loudness for consistent volume across videos
    normalize_audio(output_path)

    return output_path


async def get_available_voices() -> list[dict]:
    """Fetch the list of available voices from ElevenLabs."""
    url = f"{ELEVENLABS_BASE_URL}/voices"
    headers = {"xi-api-key": settings.elevenlabs_api_key}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    voices = [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "category": v.get("category", "unknown"),
        }
        for v in data.get("voices", [])
    ]
    logger.info("Fetched {} available voices from ElevenLabs", len(voices))
    return voices
