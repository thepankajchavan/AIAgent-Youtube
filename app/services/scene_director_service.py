"""
Scene Director Service — creative presets and scene-aware direction.

Connects caption animations, video transitions, and background music
via creative presets and per-scene direction from the LLM scene plan.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.ai_video_service import Scene


# ── Creative Presets ─────────────────────────────────────────────

CREATIVE_PRESETS: dict[str, dict[str, object]] = {
    "minimal": {
        "caption_style": "classic",
        "transition_style": "fade",
        "bgm_volume_db": -22.0,
    },
    "cinematic": {
        "caption_style": "karaoke",
        "transition_style": "auto",
        "bgm_volume_db": -16.0,
    },
    "energetic": {
        "caption_style": "bounce",
        "transition_style": "auto",
        "bgm_volume_db": -15.0,
    },
}


@dataclass
class CreativeDirections:
    """Computed creative directions for a video."""

    caption_style: str = "classic"
    transition_style: str = "auto"
    transitions: list[str] = field(default_factory=list)
    dominant_mood: str = "uplifting"
    bgm_volume_db: float = -18.0


def _dominant_mood(scenes: list[Scene]) -> str:
    """Find the most common mood across scenes.

    Falls back to default mood from settings if no scene moods are set.
    """
    moods = [
        s.mood for s in scenes
        if hasattr(s, "mood") and s.mood is not None
    ]

    if not moods:
        s = get_settings()
        return getattr(s, "bgm_default_mood", "uplifting")

    counter = Counter(moods)
    return counter.most_common(1)[0][0]


def compute_creative_directions(
    scenes: list[Scene],
    preset: str = "auto",
) -> CreativeDirections:
    """Compute creative directions from scenes and/or preset.

    Args:
        scenes: List of Scene objects (may have transition_type, mood fields).
        preset: Creative preset name or "auto" to extract from scenes.

    Returns:
        CreativeDirections with computed values.
    """
    directions = CreativeDirections()

    # Apply preset if specified
    if preset != "auto" and preset in CREATIVE_PRESETS:
        p = CREATIVE_PRESETS[preset]
        directions.caption_style = str(p.get("caption_style", "classic"))
        directions.transition_style = str(p.get("transition_style", "auto"))
        directions.bgm_volume_db = float(p.get("bgm_volume_db", -18.0))
        directions.dominant_mood = _dominant_mood(scenes)
        logger.info(
            "Creative preset '{}' applied — captions={} transitions={} mood={}",
            preset, directions.caption_style, directions.transition_style,
            directions.dominant_mood,
        )
        return directions

    # Auto mode: extract from scene data
    directions.dominant_mood = _dominant_mood(scenes)

    # Extract per-scene transitions (if LLM provided them)
    scene_transitions = []
    for s in scenes:
        if hasattr(s, "transition_type") and s.transition_type is not None:
            scene_transitions.append(s.transition_type)

    if scene_transitions:
        # First scene has no inbound transition, so transitions = n-1
        # The transition_type on a scene means "transition INTO this scene"
        directions.transitions = scene_transitions[1:] if len(scene_transitions) > 1 else []
        directions.transition_style = "scene_directed"

    # Check for caption emphasis patterns
    has_strong = any(
        hasattr(s, "caption_emphasis") and s.caption_emphasis == "strong"
        for s in scenes
    )
    if has_strong:
        directions.caption_style = "karaoke"

    # Read BGM volume from settings
    s = get_settings()
    directions.bgm_volume_db = getattr(s, "bgm_volume_db", -18.0)

    logger.info(
        "Creative directions computed — mood={} captions={} transitions={}",
        directions.dominant_mood, directions.caption_style,
        directions.transition_style,
    )
    return directions


# ── Mood → Creative Style Mapping ────────────────────────────────

MOOD_CAPTION_MAP: dict[str, str] = {
    "energetic": "bounce",
    "calm": "classic",
    "dramatic": "karaoke",
    "mysterious": "typewriter",
    "uplifting": "karaoke",
    "dark": "typewriter",
    "happy": "bounce",
    "sad": "classic",
    "epic": "karaoke",
    "chill": "classic",
}

MOOD_TRANSITION_MAP: dict[str, str] = {
    "energetic": "auto",
    "calm": "dissolve",
    "dramatic": "auto",
    "mysterious": "fade",
    "uplifting": "smoothright",
    "dark": "fade",
    "happy": "auto",
    "sad": "dissolve",
    "epic": "auto",
    "chill": "dissolve",
}


def mood_to_caption_style(mood: str) -> str:
    """Map a mood tag to an appropriate caption animation style."""
    return MOOD_CAPTION_MAP.get(mood, "classic")


def mood_to_transition_style(mood: str) -> str:
    """Map a mood tag to an appropriate transition style."""
    return MOOD_TRANSITION_MAP.get(mood, "auto")
