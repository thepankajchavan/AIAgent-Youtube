"""
Pacing Service — computes per-scene speed multipliers for dynamic video pacing.

Slow-mo for dramatic moments, speed-up for energetic beats.
Uses FFmpeg setpts for video and atempo for audio speed changes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger

from app.core.config import get_settings

# Beat type → speed multiplier (1.0 = normal, <1.0 = slow-mo, >1.0 = speed-up)
BEAT_PACING: dict[str, float] = {
    "hook": 1.0,       # Normal pace — grab attention clearly
    "build": 1.05,     # Slightly faster — keep momentum
    "climax": 0.85,    # Slow down — dramatic emphasis
    "kicker": 1.10,    # Speed up — punchy ending
}

# Mood → base speed adjustment
MOOD_PACING: dict[str, dict[str, float]] = {
    "energetic": {"base": 1.08, "hook": 1.05, "build": 1.10, "climax": 0.90, "kicker": 1.15},
    "calm": {"base": 0.95, "hook": 0.95, "build": 0.95, "climax": 0.90, "kicker": 1.0},
    "dramatic": {"base": 0.95, "hook": 1.0, "build": 0.95, "climax": 0.80, "kicker": 1.05},
    "mysterious": {"base": 0.92, "hook": 0.95, "build": 0.90, "climax": 0.85, "kicker": 1.0},
    "uplifting": {"base": 1.0, "hook": 1.0, "build": 1.05, "climax": 0.90, "kicker": 1.10},
    "dark": {"base": 0.93, "hook": 0.95, "build": 0.90, "climax": 0.80, "kicker": 1.0},
    "happy": {"base": 1.05, "hook": 1.05, "build": 1.08, "climax": 0.92, "kicker": 1.12},
    "sad": {"base": 0.90, "hook": 0.92, "build": 0.90, "climax": 0.85, "kicker": 0.95},
    "epic": {"base": 0.95, "hook": 1.0, "build": 0.95, "climax": 0.80, "kicker": 1.08},
    "chill": {"base": 0.93, "hook": 0.95, "build": 0.93, "climax": 0.90, "kicker": 0.98},
}


def compute_scene_pacing(
    num_scenes: int,
    mood: str = "uplifting",
    pacing_style: str = "auto",
) -> list[float]:
    """
    Compute speed multiplier for each scene.

    Args:
        num_scenes: Number of video scenes.
        mood: Script mood tag.
        pacing_style: "auto" (beat-based), "uniform" (same speed), or mood name.

    Returns:
        List of speed multipliers, one per scene.
    """
    settings = get_settings()
    min_speed = settings.pacing_min_speed
    max_speed = settings.pacing_max_speed
    base_speed = settings.pacing_base_speed

    if pacing_style == "uniform" or num_scenes <= 1:
        return [base_speed] * num_scenes

    # Map scenes to beat types
    beat_types = _scenes_to_beats(num_scenes)

    # Get mood-specific pacing or use default
    mood_speeds = MOOD_PACING.get(mood, MOOD_PACING.get("uplifting", {}))

    speeds = []
    for beat in beat_types:
        if pacing_style == "auto":
            speed = mood_speeds.get(beat, BEAT_PACING.get(beat, 1.0))
        else:
            # Use specific mood pacing
            override = MOOD_PACING.get(pacing_style, {})
            speed = override.get(beat, BEAT_PACING.get(beat, 1.0))

        # Apply base speed multiplier and clamp
        speed *= base_speed
        speed = max(min_speed, min(max_speed, speed))
        speeds.append(round(speed, 3))

    return speeds


def _scenes_to_beats(num_scenes: int) -> list[str]:
    """Map scene positions to beat types."""
    if num_scenes == 1:
        return ["hook"]
    if num_scenes == 2:
        return ["hook", "kicker"]
    if num_scenes == 3:
        return ["hook", "climax", "kicker"]

    beats = ["hook"]
    for _ in range(num_scenes - 3):
        beats.append("build")
    beats.append("climax")
    beats.append("kicker")
    return beats


def apply_speed_effect(
    input_path: Path,
    output_path: Path,
    speed: float,
) -> Path:
    """
    Apply speed change to a video clip using FFmpeg.

    Uses setpts for video speed and atempo for audio speed.
    atempo only supports 0.5-2.0 range, so chains are needed for extreme values.
    """
    if abs(speed - 1.0) < 0.01:
        # No speed change needed — copy
        import shutil
        shutil.copy2(input_path, output_path)
        return output_path

    # Video: setpts=PTS/speed (faster = lower PTS)
    video_filter = f"setpts=PTS/{speed}"

    # Audio: atempo=speed (supports 0.5-2.0, chain for extremes)
    atempo_filters = _build_atempo_chain(speed)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter:v", video_filter,
        "-filter:a", atempo_filters,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        logger.debug("Speed effect applied: {}x → {}", speed, output_path)
        return output_path
    except subprocess.CalledProcessError:
        # Fallback: try without audio filter (video might not have audio)
        cmd_no_audio = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-filter:v", video_filter,
            "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            str(output_path),
        ]
        subprocess.run(cmd_no_audio, check=True, capture_output=True, timeout=120)
        return output_path


def _build_atempo_chain(speed: float) -> str:
    """Build atempo filter chain for FFmpeg (each atempo limited to 0.5-2.0)."""
    if 0.5 <= speed <= 2.0:
        return f"atempo={speed}"

    # Chain multiple atempo filters
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)
