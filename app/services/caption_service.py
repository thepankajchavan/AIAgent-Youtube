"""
Caption Service — generates word-by-word animated captions for videos.

Flow:
  1. TTS audio → OpenAI Whisper API (word-level timestamps)
  2. Group words into 2-3 word display chunks
  3. Generate ASS (Advanced SubStation Alpha) subtitle file
  4. Burn captions into video via FFmpeg in media_service

Graceful degradation: if Whisper fails, returns None and video
is produced without captions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.circuit_breaker import with_whisper_breaker
from app.core.config import get_settings


@dataclass
class WordTimestamp:
    """A single word with its start/end time from Whisper."""

    word: str
    start: float
    end: float


@dataclass
class CaptionChunk:
    """A group of 2-3 words displayed together as one caption."""

    text: str
    start: float
    end: float
    words: list[WordTimestamp] | None = None  # Preserved for karaoke \kf timing


async def generate_captions(
    audio_path: Path,
    script_text: str | None = None,
    style: str | None = None,
) -> Path:
    """
    Main entry point — transcribe audio and generate ASS subtitle file.

    Args:
        audio_path: Path to the TTS audio file (MP3).
        script_text: Optional script text (unused for now, reserved for
                     future alignment improvements).
        style: Caption animation style override. If None, uses config default.

    Returns:
        Path to the generated .ass subtitle file.

    Raises:
        Exception: If Whisper API call fails (caller should catch
                   and proceed without captions).
    """
    settings = get_settings()

    logger.info("Generating captions for {}", audio_path.name)

    # Step 1: Get word-level timestamps from Whisper
    words = await _transcribe_with_timestamps(audio_path)

    if not words:
        raise ValueError("Whisper returned no word timestamps")

    # Step 2: Group words into display chunks
    chunks = _group_words(
        words,
        max_per_chunk=settings.captions_max_words_per_chunk,
    )

    # Step 3: Generate ASS subtitle file with style
    effective_style = style or getattr(settings, "captions_style", "classic")
    ass_path = _generate_ass_file(chunks, style=effective_style)

    logger.info(
        "Captions generated — {} words → {} chunks → {} (style={})",
        len(words),
        len(chunks),
        ass_path.name,
        effective_style,
    )
    return ass_path


@with_whisper_breaker()
async def _transcribe_with_timestamps(audio_path: Path) -> list[WordTimestamp]:
    """
    Call OpenAI Whisper API to get word-level timestamps.

    Cost: ~$0.006/minute — a 35-second video costs ~$0.004.
    """
    from openai import AsyncOpenAI

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)

    logger.debug("Calling Whisper API for word timestamps — {}", audio_path.name)

    with open(audio_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    raw_words = transcription.words or []

    words = [
        WordTimestamp(
            word=w.word.strip(),
            start=w.start,
            end=w.end,
        )
        for w in raw_words
        if w.word.strip()
    ]

    logger.debug("Whisper returned {} words", len(words))
    return words


def _group_words(
    words: list[WordTimestamp],
    max_per_chunk: int = 3,
    pause_threshold: float = 0.3,
) -> list[CaptionChunk]:
    """
    Group words into display chunks of 2-3 words each.

    Breaks on:
      - max_per_chunk words reached
      - pause > pause_threshold seconds between words
      - sentence boundary (word ends with . ! ?)
    """
    settings = get_settings()
    uppercase = settings.captions_uppercase

    if not words:
        return []

    chunks: list[CaptionChunk] = []
    current_words: list[WordTimestamp] = []

    for i, word in enumerate(words):
        current_words.append(word)

        is_last = i == len(words) - 1
        at_max = len(current_words) >= max_per_chunk
        ends_sentence = word.word.rstrip().endswith((".", "!", "?"))

        # Check for pause before next word
        has_pause = False
        if not is_last:
            gap = words[i + 1].start - word.end
            has_pause = gap >= pause_threshold

        if is_last or at_max or ends_sentence or has_pause:
            text = " ".join(w.word for w in current_words)
            if uppercase:
                text = text.upper()
            # Preserve word-level timestamps for karaoke/typewriter styles
            chunk_words = [
                WordTimestamp(
                    word=w.word.upper() if uppercase else w.word,
                    start=w.start,
                    end=w.end,
                )
                for w in current_words
            ]
            chunks.append(
                CaptionChunk(
                    text=text,
                    start=current_words[0].start,
                    end=current_words[-1].end,
                    words=chunk_words,
                )
            )
            current_words = []

    return chunks


def _format_ass_time(seconds: float) -> str:
    """
    Convert float seconds to ASS subtitle format: H:MM:SS.cc

    ASS uses centiseconds (hundredths), not milliseconds.
    Example: 65.372 → "0:01:05.37"
    """
    total_cs = round(seconds * 100)
    h = total_cs // 360000
    remainder = total_cs % 360000
    m = remainder // 6000
    remainder = remainder % 6000
    s = remainder // 100
    cs = remainder % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _generate_ass_file(
    chunks: list[CaptionChunk],
    style: str = "classic",
) -> Path:
    """
    Generate an ASS (Advanced SubStation Alpha) subtitle file.

    Dispatches to style-specific generators from caption_styles module.
    Falls back to classic style for unknown styles.
    """
    from app.services.caption_styles import (
        CaptionConfig,
        build_ass_header,
        build_caption_config,
        generate_styled_lines,
    )

    settings = get_settings()

    captions_dir = settings.captions_dir
    captions_dir.mkdir(parents=True, exist_ok=True)
    ass_path = captions_dir / f"captions_{uuid.uuid4().hex[:12]}.ass"

    # Build config with the specified style
    config = build_caption_config()
    config.style = style

    # Build header and styled dialogue lines
    header = build_ass_header(config)
    lines = generate_styled_lines(chunks, config)

    content = header + "\n".join(lines) + "\n"
    ass_path.write_text(content, encoding="utf-8")

    logger.debug("ASS subtitle file written — {} lines, style={} → {}", len(lines), style, ass_path)
    return ass_path
