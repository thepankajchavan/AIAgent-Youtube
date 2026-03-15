"""
Beat TTS Service — per-beat voice expressiveness for dynamic narration.

Splits the script into narrative beats (hook/build/climax/kicker) and
generates TTS for each beat with different voice parameters, creating
a natural-sounding narration that varies energy across the script.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.services.tts_service import generate_speech
from app.services.voice_profile_service import VoiceProfile, get_voice_profile_for_mood


# ── Beat Types ────────────────────────────────────────────────────

@dataclass
class BeatTTSParams:
    """TTS parameters for a single script beat."""

    text: str
    beat_type: str          # "hook" | "build" | "climax" | "kicker"
    stability: float
    similarity_boost: float
    style: float


# Expressiveness multipliers relative to base voice profile
BEAT_EXPRESSIVENESS: dict[str, dict[str, float]] = {
    "hook": {"stability_mult": 0.75, "style_mult": 1.30},
    "build": {"stability_mult": 1.10, "style_mult": 0.85},
    "climax": {"stability_mult": 0.70, "style_mult": 1.40},
    "kicker": {"stability_mult": 0.85, "style_mult": 1.15},
}


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to a range."""
    return max(min_val, min(value, max_val))


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences by punctuation or blank lines."""
    # First split by blank lines (paragraph breaks)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) >= 3:
        return paragraphs

    # Fall back to sentence splitting
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def apply_beat_expressiveness(
    base_profile: VoiceProfile,
    beat_type: str,
) -> dict[str, float]:
    """Apply beat multipliers to base voice profile params.

    Returns dict with stability, similarity_boost, style.
    """
    mult = BEAT_EXPRESSIVENESS.get(beat_type, BEAT_EXPRESSIVENESS["build"])
    return {
        "stability": _clamp(base_profile.stability * mult["stability_mult"], 0.1, 1.0),
        "similarity_boost": base_profile.similarity_boost,
        "style": _clamp(base_profile.style * mult["style_mult"], 0.0, 1.0),
    }


def classify_script_beats(
    script_text: str,
    scenes: list[dict] | None = None,
) -> list[BeatTTSParams]:
    """Split script into beats using scene structure or sentence heuristics.

    If scenes exist: map scene positions to beat types.
      - Scene 1 → hook
      - Scenes 2..N-2 → build
      - Scene N-1 → climax
      - Scene N → kicker

    If no scenes: split by sentences/paragraphs with same mapping.

    Returns list of BeatTTSParams with beat_type assigned (params filled later).
    """
    # Determine text segments
    if scenes and len(scenes) >= 2:
        segments = [s.get("narration", "") for s in scenes if s.get("narration")]
    else:
        segments = _split_sentences(script_text)

    if not segments:
        return [BeatTTSParams(
            text=script_text, beat_type="hook",
            stability=0.0, similarity_boost=0.0, style=0.0,
        )]

    n = len(segments)
    beats: list[BeatTTSParams] = []

    for i, text in enumerate(segments):
        if i == 0:
            beat_type = "hook"
        elif i == n - 1:
            beat_type = "kicker"
        elif i == n - 2 and n >= 3:
            beat_type = "climax"
        else:
            beat_type = "build"

        beats.append(BeatTTSParams(
            text=text, beat_type=beat_type,
            stability=0.0, similarity_boost=0.0, style=0.0,
        ))

    return beats


def _concatenate_audio_segments(
    segment_paths: list[Path],
    output_path: Path,
) -> Path:
    """Concatenate audio segments using FFmpeg concat demuxer."""
    if len(segment_paths) == 1:
        # No concatenation needed
        import shutil
        shutil.copy2(segment_paths[0], output_path)
        return output_path

    # Create concat list file
    concat_file = Path(tempfile.mktemp(suffix=".txt"))
    try:
        with open(concat_file, "w") as f:
            for p in segment_paths:
                # FFmpeg concat requires forward slashes and single-quote escaping
                safe_path = str(p).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )

        if result.returncode != 0:
            logger.error("FFmpeg concat failed: {}", result.stderr[:500])
            raise RuntimeError(f"Audio concatenation failed: {result.stderr[:200]}")

        return output_path

    finally:
        concat_file.unlink(missing_ok=True)


async def generate_speech_per_beat(
    script_text: str,
    mood: str = "uplifting",
    scenes: list[dict] | None = None,
    output_dir: Path | None = None,
    voice_id: str | None = None,
) -> Path:
    """Generate TTS per beat with varying expressiveness.

    1. Classify script into beats (hook/build/climax/kicker)
    2. Get base voice profile from mood
    3. For each beat: apply expressiveness multipliers, generate TTS
    4. Concatenate all audio segments seamlessly
    5. Return path to final audio file

    Falls back to single TTS call on failure.
    """
    from app.core.config import get_settings
    _settings = get_settings()

    if output_dir is None:
        output_dir = _settings.audio_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Classify beats
    beats = classify_script_beats(script_text, scenes)
    if not beats:
        # Fallback to single TTS
        return await generate_speech(text=script_text)

    # Get base voice profile
    base_profile = get_voice_profile_for_mood(mood)

    logger.info(
        "Per-beat TTS — {} beats ({}), mood={}, base_stability={}, base_style={}",
        len(beats),
        ", ".join(b.beat_type for b in beats),
        mood,
        base_profile.stability,
        base_profile.style,
    )

    # Generate TTS for each beat
    segment_paths: list[Path] = []
    try:
        for i, beat in enumerate(beats):
            params = apply_beat_expressiveness(base_profile, beat.beat_type)

            segment_filename = f"beat_{uuid.uuid4().hex[:8]}_{beat.beat_type}.mp3"
            _speech_kwargs = {
                "text": beat.text,
                "output_filename": segment_filename,
                "stability": params["stability"],
                "similarity_boost": params["similarity_boost"],
                "style": params["style"],
            }
            if voice_id:
                _speech_kwargs["voice_id"] = voice_id
            segment_path = await generate_speech(**_speech_kwargs)
            segment_paths.append(segment_path)

            logger.debug(
                "Beat {}/{} '{}' generated — stability={:.2f} style={:.2f}",
                i + 1, len(beats), beat.beat_type,
                params["stability"], params["style"],
            )

        # Concatenate all segments
        final_filename = f"tts_perbeat_{uuid.uuid4().hex[:8]}.mp3"
        final_path = output_dir / final_filename

        _concatenate_audio_segments(segment_paths, final_path)

        logger.info(
            "Per-beat TTS complete — {} beats concatenated → {}",
            len(segment_paths), final_path,
        )
        return final_path

    except Exception as exc:
        logger.error("Per-beat TTS failed, falling back to single TTS: {}", exc)
        # Fallback: single TTS with base profile
        return await generate_speech(
            text=script_text,
            stability=base_profile.stability,
            similarity_boost=base_profile.similarity_boost,
            style=base_profile.style,
        )
