"""
Caption Styles — animated caption presets for TikTok-style captions.

Provides 4 style presets:
  - classic: Static white text (current default behavior)
  - karaoke: Word-by-word color fill highlight (TikTok-style)
  - bounce: Pop-in with overshoot bounce animation
  - typewriter: Progressive word reveal with fade-in

Each style generates ASS (Advanced SubStation Alpha) dialogue lines
with appropriate override tags for the animation effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.caption_service import CaptionChunk


# ── Data Models ──────────────────────────────────────────────────


@dataclass
class CaptionTheme:
    """Color theme for captions (ASS BGR hex format)."""

    primary: str = "FFFFFF"      # Main text color (BGR)
    accent: str = "00FFFF"       # Highlight/karaoke fill color (BGR)
    outline: str = "000000"      # Outline color (BGR)
    shadow: str = "80000000"     # Shadow color (ABGR)


@dataclass
class CaptionConfig:
    """Full caption configuration built from settings."""

    style: str = "classic"
    position: str = "bottom"
    font_name: str = "Arial"
    font_size: int = 28
    theme: CaptionTheme = field(default_factory=CaptionTheme)
    uppercase: bool = True
    max_words_per_chunk: int = 3


# ── Position Map ─────────────────────────────────────────────────

# ASS alignment + MarginV for each position
# \an2 = bottom-center, \an5 = mid-center, \an8 = top-center
POSITION_MAP: dict[str, dict[str, object]] = {
    "bottom": {"alignment": 2, "margin_v": 200},
    "center": {"alignment": 5, "margin_v": 0},
    "top":    {"alignment": 8, "margin_v": 120},
}


def build_caption_config() -> CaptionConfig:
    """Build a CaptionConfig from application settings."""
    s = get_settings()
    theme = CaptionTheme(
        primary=getattr(s, "captions_primary_color", "FFFFFF"),
        accent=getattr(s, "captions_accent_color", "00FFFF"),
        outline=getattr(s, "captions_outline_color", "000000"),
        shadow=getattr(s, "captions_shadow_color", "80000000"),
    )
    return CaptionConfig(
        style=getattr(s, "captions_style", "classic"),
        position=getattr(s, "captions_position", "bottom"),
        font_name=s.captions_font,
        font_size=s.captions_font_size,
        theme=theme,
        uppercase=s.captions_uppercase,
        max_words_per_chunk=s.captions_max_words_per_chunk,
    )


# ── ASS Color Formatting ────────────────────────────────────────


def _ass_color(bgr_hex: str) -> str:
    """Convert BGR hex string to ASS color format: &H00BBGGRR."""
    bgr_hex = bgr_hex.lstrip("&H").lstrip("#")
    if len(bgr_hex) == 6:
        return f"&H00{bgr_hex}&"
    elif len(bgr_hex) == 8:
        # ABGR format
        return f"&H{bgr_hex}&"
    return f"&H00{bgr_hex}&"


# ── ASS Header Builder ──────────────────────────────────────────


def build_ass_header(config: CaptionConfig) -> str:
    """Generate ASS [Script Info] + [V4+ Styles] header sections."""
    pos = POSITION_MAP.get(config.position, POSITION_MAP["bottom"])
    alignment = pos["alignment"]
    margin_v = pos["margin_v"]

    primary_color = _ass_color(config.theme.primary)
    accent_color = _ass_color(config.theme.accent)
    outline_color = _ass_color(config.theme.outline)
    shadow_color = _ass_color(config.theme.shadow)

    header = f"""\
[Script Info]
Title: Auto-generated captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font_name},{config.font_size},{primary_color},{accent_color},{outline_color},{shadow_color},-1,0,0,0,100,100,0,0,1,4,0,{alignment},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header


# ── ASS Time Formatting ─────────────────────────────────────────


def _format_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS format: H:MM:SS.cc (centiseconds)."""
    total_cs = round(seconds * 100)
    h = total_cs // 360000
    remainder = total_cs % 360000
    m = remainder // 6000
    remainder = remainder % 6000
    s = remainder // 100
    cs = remainder % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass_text(text: str) -> str:
    """Escape special ASS characters in text."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


# ── Style Generators ─────────────────────────────────────────────


def generate_classic_lines(chunks: list[CaptionChunk]) -> list[str]:
    """Classic style: plain dialogue lines, no override tags.

    Matches the original caption behavior exactly.
    """
    lines: list[str] = []
    for chunk in chunks:
        start = _format_ass_time(chunk.start)
        end = _format_ass_time(chunk.end)
        text = _escape_ass_text(chunk.text)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return lines


def generate_karaoke_lines(
    chunks: list[CaptionChunk],
    config: CaptionConfig,
) -> list[str]:
    r"""Karaoke style: word-by-word color fill using \kf tags.

    Each word gets a \kf<centiseconds> tag that controls the fill
    animation duration from primary color to accent (secondary) color.
    """
    accent_color = _ass_color(config.theme.accent)
    lines: list[str] = []

    for chunk in chunks:
        start = _format_ass_time(chunk.start)
        end = _format_ass_time(chunk.end)

        # Use word timestamps if available for precise timing
        if chunk.words and len(chunk.words) > 0:
            parts: list[str] = []
            for word in chunk.words:
                # \kf duration in centiseconds
                dur_cs = max(1, round((word.end - word.start) * 100))
                escaped = _escape_ass_text(word.word)
                parts.append(f"{{\\kf{dur_cs}}}{escaped}")
            text = " ".join(parts)
        else:
            # Fallback: distribute chunk duration evenly across words
            words = chunk.text.split()
            if not words:
                continue
            chunk_dur_cs = max(1, round((chunk.end - chunk.start) * 100))
            per_word_cs = max(1, chunk_dur_cs // len(words))
            parts = []
            for w in words:
                escaped = _escape_ass_text(w)
                parts.append(f"{{\\kf{per_word_cs}}}{escaped}")
            text = " ".join(parts)

        # Apply accent color override for karaoke highlight
        line = (
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
            f"{{\\1c{accent_color}}}{text}"
        )
        lines.append(line)

    return lines


def generate_bounce_lines(chunks: list[CaptionChunk]) -> list[str]:
    r"""Bounce style: pop-in with overshoot bounce animation.

    Uses \fscx/\fscy (font scale) with \t (animation transform):
      - Start at 50% scale
      - Overshoot to 110% in 150ms
      - Settle to 100% in next 100ms
    """
    lines: list[str] = []
    for chunk in chunks:
        start = _format_ass_time(chunk.start)
        end = _format_ass_time(chunk.end)
        text = _escape_ass_text(chunk.text)

        # Bounce animation: scale 50% → 110% → 100%
        bounce_tags = (
            r"{\fscx50\fscy50"
            r"\t(0,150,\fscx110\fscy110)"
            r"\t(150,250,\fscx100\fscy100)}"
        )
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{bounce_tags}{text}"
        )
    return lines


def generate_typewriter_lines(chunks: list[CaptionChunk]) -> list[str]:
    r"""Typewriter style: progressive word reveal with fade-in.

    Each new word appears with an alpha fade from transparent to opaque.
    Words accumulate within a chunk to create a "typing" effect.
    """
    lines: list[str] = []

    for chunk in chunks:
        if chunk.words and len(chunk.words) > 0:
            words = chunk.words
        else:
            # Fallback: split text and distribute timing
            raw_words = chunk.text.split()
            if not raw_words:
                continue
            total_dur = chunk.end - chunk.start
            per_word_dur = total_dur / len(raw_words)

            from app.services.caption_service import WordTimestamp
            words = [
                WordTimestamp(
                    word=w,
                    start=chunk.start + i * per_word_dur,
                    end=chunk.start + (i + 1) * per_word_dur,
                )
                for i, w in enumerate(raw_words)
            ]

        chunk_start = _format_ass_time(chunk.start)
        chunk_end = _format_ass_time(chunk.end)

        # Build progressive reveal: each word fades in at its start time
        parts: list[str] = []
        for i, word in enumerate(words):
            escaped = _escape_ass_text(word.word)
            # Offset from chunk start in milliseconds
            word_offset_ms = max(0, round((word.start - chunk.start) * 1000))
            fade_dur_ms = 80  # 80ms fade-in

            # Word starts fully transparent, fades to opaque
            parts.append(
                f"{{\\alpha&HFF&\\t({word_offset_ms},{word_offset_ms + fade_dur_ms},"
                f"\\alpha&H00&)}}{escaped}"
            )

        text = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{chunk_start},{chunk_end},Default,,0,0,0,,{text}"
        )

    return lines


# ── Style Dispatcher ─────────────────────────────────────────────

STYLE_GENERATORS = {
    "classic": lambda chunks, config: generate_classic_lines(chunks),
    "karaoke": generate_karaoke_lines,
    "bounce": lambda chunks, config: generate_bounce_lines(chunks),
    "typewriter": lambda chunks, config: generate_typewriter_lines(chunks),
}


def generate_styled_lines(
    chunks: list[CaptionChunk],
    config: CaptionConfig,
) -> list[str]:
    """Dispatch to the appropriate style generator."""
    generator = STYLE_GENERATORS.get(config.style)
    if generator is None:
        # Fallback to classic for unknown styles
        return generate_classic_lines(chunks)
    return generator(chunks, config)
