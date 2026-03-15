"""
Voice Profile Service — maps mood tags to ElevenLabs voice parameters.

Each mood (returned by the LLM in script generation) maps to a tuned
VoiceProfile with stability, similarity_boost, and style values that
make the narration match the emotional tone of the script.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass(frozen=True)
class VoiceProfile:
    """Tuned ElevenLabs voice parameters for a specific mood."""

    stability: float        # 0.0-1.0 — lower = more expressive/varied
    similarity_boost: float  # 0.0-1.0 — voice consistency
    style: float            # 0.0-1.0 — style exaggeration
    speed: float            # 0.8-1.2 — speaking rate multiplier
    description: str        # Human-readable label


# ── Mood → Voice Profile Mapping ─────────────────────────────────

MOOD_VOICE_PROFILES: dict[str, VoiceProfile] = {
    "energetic": VoiceProfile(
        stability=0.30, similarity_boost=0.80, style=0.70,
        speed=1.10, description="Fast, punchy, high energy",
    ),
    "calm": VoiceProfile(
        stability=0.70, similarity_boost=0.85, style=0.25,
        speed=0.92, description="Smooth, steady, relaxed",
    ),
    "dramatic": VoiceProfile(
        stability=0.35, similarity_boost=0.80, style=0.65,
        speed=0.95, description="Intense, theatrical",
    ),
    "mysterious": VoiceProfile(
        stability=0.50, similarity_boost=0.75, style=0.55,
        speed=0.90, description="Low-key, intriguing",
    ),
    "uplifting": VoiceProfile(
        stability=0.45, similarity_boost=0.80, style=0.55,
        speed=1.00, description="Warm, inspiring",
    ),
    "dark": VoiceProfile(
        stability=0.40, similarity_boost=0.80, style=0.60,
        speed=0.88, description="Ominous, heavy",
    ),
    "happy": VoiceProfile(
        stability=0.35, similarity_boost=0.85, style=0.65,
        speed=1.08, description="Bright, cheerful",
    ),
    "sad": VoiceProfile(
        stability=0.60, similarity_boost=0.85, style=0.40,
        speed=0.88, description="Somber, reflective",
    ),
    "epic": VoiceProfile(
        stability=0.30, similarity_boost=0.75, style=0.75,
        speed=0.95, description="Grand, powerful",
    ),
    "chill": VoiceProfile(
        stability=0.65, similarity_boost=0.85, style=0.30,
        speed=0.93, description="Laid-back, conversational",
    ),
}

DEFAULT_MOOD = "uplifting"


def get_voice_profile_for_mood(mood: str) -> VoiceProfile:
    """Return a tuned VoiceProfile for the given mood.

    Falls back to the 'uplifting' profile for unknown moods.
    """
    profile = MOOD_VOICE_PROFILES.get(mood)
    if profile is None:
        logger.warning(
            "Unknown mood '{}' — falling back to '{}' voice profile",
            mood, DEFAULT_MOOD,
        )
        profile = MOOD_VOICE_PROFILES[DEFAULT_MOOD]
    else:
        logger.debug(
            "Voice profile for mood='{}': stability={} style={} speed={}",
            mood, profile.stability, profile.style, profile.speed,
        )
    return profile
