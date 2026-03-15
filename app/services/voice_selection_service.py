"""
Voice Selection Service — maps niches and moods to different ElevenLabs voices.

Priority: user_override > mood > niche > config default.
"""

from __future__ import annotations

from functools import lru_cache

from loguru import logger

from app.core.config import get_settings

# Default ElevenLabs voice IDs for different niches
# These are well-known public voices; users should override with their own
NICHE_VOICE_MAP: dict[str, str] = {
    "science": "pNInz6obpgDQGcFmaJgB",      # Adam — deep, authoritative
    "history": "VR6AewLTigWG4xSOukaG",      # Arnold — narrative, measured
    "technology": "ErXwobaYiN019PkySvjV",    # Antoni — clear, modern
    "motivation": "EXAVITQu4vr4xnSDxMaL",   # Bella — warm, inspiring
    "entertainment": "MF3mGyEYCl7XYWbV9V6O", # Elli — bright, energetic
    "psychology": "TxGEqnHWrfWFTfGW9XjX",   # Josh — thoughtful, calm
    "space": "pNInz6obpgDQGcFmaJgB",        # Adam — awe-inspiring
}

MOOD_VOICE_MAP: dict[str, str] = {
    "energetic": "MF3mGyEYCl7XYWbV9V6O",   # Elli — bright, fast
    "calm": "TxGEqnHWrfWFTfGW9XjX",        # Josh — soothing
    "dramatic": "VR6AewLTigWG4xSOukaG",     # Arnold — theatrical
    "mysterious": "TxGEqnHWrfWFTfGW9XjX",   # Josh — low, intriguing
    "dark": "VR6AewLTigWG4xSOukaG",         # Arnold — ominous
    "epic": "pNInz6obpgDQGcFmaJgB",         # Adam — grand
}


def select_voice(
    niche: str | None = None,
    mood: str | None = None,
    user_voice_id: str | None = None,
) -> str:
    """
    Select the best voice_id based on priority:
    user_override > config voice_map > mood > niche > config default.
    """
    settings = get_settings()

    # 1. User explicit override
    if user_voice_id:
        return user_voice_id

    # 2. Config-based voice maps (user-configured per niche)
    if niche:
        config_voice = _get_config_voice_for_niche(niche)
        if config_voice:
            return config_voice

    # 3. Mood-based voice
    if mood and mood in MOOD_VOICE_MAP:
        return MOOD_VOICE_MAP[mood]

    # 4. Niche-based voice (built-in defaults)
    if niche and niche in NICHE_VOICE_MAP:
        return NICHE_VOICE_MAP[niche]

    # 5. Config default or global fallback
    config_default = getattr(settings, "voice_map_default", "")
    if config_default:
        return config_default

    return settings.elevenlabs_voice_id


def _get_config_voice_for_niche(niche: str) -> str | None:
    """Check config for user-configured voice_id for a niche."""
    settings = get_settings()
    attr_name = f"voice_map_{niche}"
    voice_id = getattr(settings, attr_name, "")
    return voice_id if voice_id else None


@lru_cache(maxsize=1)
def get_voice_catalog() -> list[dict]:
    """Get available voices with niche recommendations."""
    import asyncio
    from app.services.tts_service import get_available_voices

    try:
        voices = asyncio.run(get_available_voices())
    except Exception:
        voices = []

    # Annotate with niche recommendations
    niche_reverse = {}
    for niche, vid in NICHE_VOICE_MAP.items():
        if vid not in niche_reverse:
            niche_reverse[vid] = []
        niche_reverse[vid].append(niche)

    for voice in voices:
        voice["recommended_niches"] = niche_reverse.get(voice.get("voice_id"), [])

    return voices
