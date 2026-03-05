"""
TTS Service — converts script text to speech via ElevenLabs.

Streams audio bytes to disk and returns the file path.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

settings = get_settings()

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"


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
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
) -> Path:
    """
    Convert text to speech and save as MP3.

    Args:
        text: The script text to convert.
        voice_id: ElevenLabs voice ID (defaults to config value).
        output_filename: Name for the output file (auto-generated if None).
        model_id: ElevenLabs model ID.
        stability: Voice stability (0.0 - 1.0).
        similarity_boost: Voice similarity boost (0.0 - 1.0).
        style: Style exaggeration (0.0 - 1.0).

    Returns:
        Path to the saved audio file.
    """
    voice_id = voice_id or settings.elevenlabs_voice_id
    output_dir = settings.audio_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = f"tts_{uuid.uuid4().hex[:12]}.mp3"
    output_path = output_dir / output_filename

    url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}/stream"

    payload = {
        "text": text,
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
        "ElevenLabs TTS request — voice={} text_len={} model={}",
        voice_id,
        len(text),
        model_id,
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
