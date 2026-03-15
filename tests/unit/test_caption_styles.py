"""Tests for app.services.caption_styles — animated caption presets."""

from unittest.mock import patch, MagicMock

from app.services.caption_service import CaptionChunk, WordTimestamp
from app.services.caption_styles import (
    CaptionConfig,
    CaptionTheme,
    POSITION_MAP,
    build_caption_config,
    build_ass_header,
    generate_classic_lines,
    generate_karaoke_lines,
    generate_bounce_lines,
    generate_typewriter_lines,
    generate_styled_lines,
    _ass_color,
)


# ── Helper ───────────────────────────────────────────────────────


def _make_chunks() -> list[CaptionChunk]:
    """Return two sample CaptionChunks with word-level timestamps."""
    return [
        CaptionChunk(
            text="HELLO WORLD",
            start=0.0,
            end=1.0,
            words=[
                WordTimestamp(word="HELLO", start=0.0, end=0.5),
                WordTimestamp(word="WORLD", start=0.5, end=1.0),
            ],
        ),
        CaptionChunk(
            text="TESTING CAPTIONS",
            start=1.2,
            end=2.5,
            words=[
                WordTimestamp(word="TESTING", start=1.2, end=1.8),
                WordTimestamp(word="CAPTIONS", start=1.8, end=2.5),
            ],
        ),
    ]


def _default_config(**overrides) -> CaptionConfig:
    """Return a CaptionConfig with sensible defaults, accepting overrides."""
    kwargs = {
        "style": "classic",
        "position": "bottom",
        "font_name": "Arial",
        "font_size": 28,
        "theme": CaptionTheme(),
        "uppercase": True,
        "max_words_per_chunk": 3,
    }
    kwargs.update(overrides)
    return CaptionConfig(**kwargs)


# ── TestAssColor ─────────────────────────────────────────────────


class TestAssColor:
    """Verify BGR hex to ASS &H00XXXXXX& conversion."""

    def test_six_char_white(self):
        assert _ass_color("FFFFFF") == "&H00FFFFFF&"

    def test_six_char_accent(self):
        assert _ass_color("00FFFF") == "&H0000FFFF&"

    def test_six_char_black(self):
        assert _ass_color("000000") == "&H00000000&"

    def test_eight_char_abgr(self):
        """8-char input is treated as ABGR and kept verbatim."""
        assert _ass_color("80000000") == "&H80000000&"

    def test_eight_char_full_alpha(self):
        assert _ass_color("FF003366") == "&HFF003366&"

    def test_strips_hash_prefix(self):
        assert _ass_color("#FFFFFF") == "&H00FFFFFF&"

    def test_strips_ass_prefix(self):
        assert _ass_color("&HFFFFFF") == "&H00FFFFFF&"


# ── TestBuildAssHeader ───────────────────────────────────────────


class TestBuildAssHeader:
    """Verify the ASS header structure for all positions."""

    def test_header_contains_required_sections(self):
        config = _default_config()
        header = build_ass_header(config)
        assert "[Script Info]" in header
        assert "[V4+ Styles]" in header
        assert "[Events]" in header

    def test_header_contains_font_and_size(self):
        config = _default_config(font_name="Montserrat", font_size=32)
        header = build_ass_header(config)
        assert "Montserrat" in header
        assert ",32," in header

    def test_bottom_position(self):
        config = _default_config(position="bottom")
        header = build_ass_header(config)
        # Alignment=2, MarginV=200
        # The style line ends with: ...,Alignment,MarginL,MarginR,MarginV,Encoding
        assert ",2,40,40,200,1" in header

    def test_center_position(self):
        config = _default_config(position="center")
        header = build_ass_header(config)
        assert ",5,40,40,0,1" in header

    def test_top_position(self):
        config = _default_config(position="top")
        header = build_ass_header(config)
        assert ",8,40,40,120,1" in header

    def test_unknown_position_falls_back_to_bottom(self):
        config = _default_config(position="unknown_pos")
        header = build_ass_header(config)
        assert ",2,40,40,200,1" in header

    def test_header_uses_theme_colors(self):
        theme = CaptionTheme(
            primary="AABBCC",
            accent="112233",
            outline="DDEEFF",
            shadow="80445566",
        )
        config = _default_config(theme=theme)
        header = build_ass_header(config)
        assert "&H00AABBCC&" in header
        assert "&H00112233&" in header
        assert "&H00DDEEFF&" in header
        assert "&H80445566&" in header

    def test_header_contains_resolution(self):
        config = _default_config()
        header = build_ass_header(config)
        assert "PlayResX: 1080" in header
        assert "PlayResY: 1920" in header


# ── TestClassicLines ─────────────────────────────────────────────


class TestClassicLines:
    """Classic style: plain Dialogue lines with no override tags."""

    def test_correct_number_of_lines(self):
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        assert len(lines) == 2

    def test_lines_start_with_dialogue(self):
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        for line in lines:
            assert line.startswith("Dialogue: 0,")

    def test_no_override_tags(self):
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        for line in lines:
            # No ASS override tags like {\tag}
            assert "\\kf" not in line
            assert "\\fscx" not in line
            assert "\\alpha" not in line
            assert "\\t(" not in line

    def test_chunk_text_appears_in_line(self):
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        assert "HELLO WORLD" in lines[0]
        assert "TESTING CAPTIONS" in lines[1]

    def test_timing_format(self):
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        # First chunk: 0.0 -> 1.0 => "0:00:00.00" and "0:00:01.00"
        assert "0:00:00.00" in lines[0]
        assert "0:00:01.00" in lines[0]

    def test_empty_chunks_returns_empty(self):
        lines = generate_classic_lines([])
        assert lines == []


# ── TestKaraokeLines ─────────────────────────────────────────────


class TestKaraokeLines:
    """Karaoke style: \\kf word-by-word highlight with accent color."""

    def test_kf_tags_present(self):
        chunks = _make_chunks()
        config = _default_config(style="karaoke")
        lines = generate_karaoke_lines(chunks, config)
        for line in lines:
            assert "\\kf" in line

    def test_kf_durations_in_centiseconds(self):
        chunks = _make_chunks()
        config = _default_config(style="karaoke")
        lines = generate_karaoke_lines(chunks, config)
        # First chunk: HELLO 0.0-0.5 = 50cs, WORLD 0.5-1.0 = 50cs
        assert "{\\kf50}HELLO" in lines[0]
        assert "{\\kf50}WORLD" in lines[0]

    def test_second_chunk_kf_durations(self):
        chunks = _make_chunks()
        config = _default_config(style="karaoke")
        lines = generate_karaoke_lines(chunks, config)
        # Second chunk: TESTING 1.2-1.8 = 60cs, CAPTIONS 1.8-2.5 = 70cs
        assert "{\\kf60}TESTING" in lines[1]
        assert "{\\kf70}CAPTIONS" in lines[1]

    def test_accent_color_override(self):
        theme = CaptionTheme(accent="00FFFF")
        config = _default_config(style="karaoke", theme=theme)
        chunks = _make_chunks()
        lines = generate_karaoke_lines(chunks, config)
        # Each line should start with the accent color override
        for line in lines:
            assert "\\1c&H0000FFFF&" in line

    def test_custom_accent_color(self):
        theme = CaptionTheme(accent="3399FF")
        config = _default_config(style="karaoke", theme=theme)
        chunks = _make_chunks()
        lines = generate_karaoke_lines(chunks, config)
        for line in lines:
            assert "\\1c&H003399FF&" in line

    def test_fallback_without_word_timestamps(self):
        """When chunks lack word-level timestamps, timing is distributed evenly."""
        chunks = [
            CaptionChunk(text="TWO WORDS", start=0.0, end=1.0, words=None),
        ]
        config = _default_config(style="karaoke")
        lines = generate_karaoke_lines(chunks, config)
        assert len(lines) == 1
        assert "\\kf" in lines[0]
        # 100cs / 2 words = 50cs each
        assert "{\\kf50}TWO" in lines[0]
        assert "{\\kf50}WORDS" in lines[0]


# ── TestBounceLines ──────────────────────────────────────────────


class TestBounceLines:
    """Bounce style: pop-in with overshoot bounce animation."""

    def test_fscx_fscy_tags(self):
        chunks = _make_chunks()
        lines = generate_bounce_lines(chunks)
        for line in lines:
            assert "\\fscx50" in line
            assert "\\fscy50" in line

    def test_overshoot_animation(self):
        chunks = _make_chunks()
        lines = generate_bounce_lines(chunks)
        for line in lines:
            assert "\\t(0,150,\\fscx110\\fscy110)" in line

    def test_settle_animation(self):
        chunks = _make_chunks()
        lines = generate_bounce_lines(chunks)
        for line in lines:
            assert "\\t(150,250,\\fscx100\\fscy100)" in line

    def test_text_appears_after_tags(self):
        chunks = _make_chunks()
        lines = generate_bounce_lines(chunks)
        assert lines[0].endswith("HELLO WORLD")
        assert lines[1].endswith("TESTING CAPTIONS")

    def test_correct_line_count(self):
        chunks = _make_chunks()
        lines = generate_bounce_lines(chunks)
        assert len(lines) == 2


# ── TestTypewriterLines ──────────────────────────────────────────


class TestTypewriterLines:
    """Typewriter style: progressive word reveal with alpha fade-in."""

    def test_alpha_tags_present(self):
        chunks = _make_chunks()
        lines = generate_typewriter_lines(chunks)
        for line in lines:
            assert "\\alpha&HFF&" in line
            assert "\\alpha&H00&" in line

    def test_fade_in_timing(self):
        chunks = _make_chunks()
        lines = generate_typewriter_lines(chunks)
        # First word of first chunk starts at offset 0ms, fade duration 80ms
        assert "\\t(0,80," in lines[0]

    def test_second_word_offset(self):
        chunks = _make_chunks()
        lines = generate_typewriter_lines(chunks)
        # Second word of first chunk: WORLD starts at 0.5, chunk starts at 0.0
        # offset = (0.5 - 0.0) * 1000 = 500ms
        assert "\\t(500,580," in lines[0]

    def test_second_chunk_offsets(self):
        chunks = _make_chunks()
        lines = generate_typewriter_lines(chunks)
        # Second chunk starts at 1.2
        # TESTING starts at 1.2 -> offset = 0ms
        assert "\\t(0,80," in lines[1]
        # CAPTIONS starts at 1.8 -> offset = (1.8-1.2)*1000 = 600ms
        assert "\\t(600,680," in lines[1]

    def test_word_text_in_output(self):
        chunks = _make_chunks()
        lines = generate_typewriter_lines(chunks)
        assert "HELLO" in lines[0]
        assert "WORLD" in lines[0]
        assert "TESTING" in lines[1]
        assert "CAPTIONS" in lines[1]

    def test_fallback_without_word_timestamps(self):
        """When word timestamps are missing, timing is distributed evenly."""
        chunks = [
            CaptionChunk(text="ONE TWO THREE", start=0.0, end=3.0, words=None),
        ]
        lines = generate_typewriter_lines(chunks)
        assert len(lines) == 1
        assert "\\alpha" in lines[0]
        assert "ONE" in lines[0]
        assert "TWO" in lines[0]
        assert "THREE" in lines[0]


# ── TestGenerateStyledLines ──────────────────────────────────────


class TestGenerateStyledLines:
    """Dispatcher routes to the correct generator by style name."""

    def test_classic_dispatch(self):
        chunks = _make_chunks()
        config = _default_config(style="classic")
        lines = generate_styled_lines(chunks, config)
        classic_lines = generate_classic_lines(chunks)
        assert lines == classic_lines

    def test_karaoke_dispatch(self):
        chunks = _make_chunks()
        config = _default_config(style="karaoke")
        lines = generate_styled_lines(chunks, config)
        karaoke_lines = generate_karaoke_lines(chunks, config)
        assert lines == karaoke_lines

    def test_bounce_dispatch(self):
        chunks = _make_chunks()
        config = _default_config(style="bounce")
        lines = generate_styled_lines(chunks, config)
        bounce_lines = generate_bounce_lines(chunks)
        assert lines == bounce_lines

    def test_typewriter_dispatch(self):
        chunks = _make_chunks()
        config = _default_config(style="typewriter")
        lines = generate_styled_lines(chunks, config)
        typewriter_lines = generate_typewriter_lines(chunks)
        assert lines == typewriter_lines

    def test_unknown_style_falls_back_to_classic(self):
        chunks = _make_chunks()
        config = _default_config(style="nonexistent_style")
        lines = generate_styled_lines(chunks, config)
        classic_lines = generate_classic_lines(chunks)
        assert lines == classic_lines

    def test_empty_string_style_falls_back_to_classic(self):
        chunks = _make_chunks()
        config = _default_config(style="")
        lines = generate_styled_lines(chunks, config)
        classic_lines = generate_classic_lines(chunks)
        assert lines == classic_lines


# ── TestBuildCaptionConfig ───────────────────────────────────────


class TestBuildCaptionConfig:
    """Verify build_caption_config reads from get_settings()."""

    def _mock_settings(self, **overrides):
        defaults = {
            "captions_style": "karaoke",
            "captions_position": "center",
            "captions_font": "Montserrat",
            "captions_font_size": 32,
            "captions_uppercase": False,
            "captions_max_words_per_chunk": 4,
            "captions_primary_color": "AABBCC",
            "captions_accent_color": "112233",
            "captions_outline_color": "DDEEFF",
            "captions_shadow_color": "80445566",
        }
        defaults.update(overrides)
        mock = MagicMock()
        for key, value in defaults.items():
            setattr(mock, key, value)
        return mock

    @patch("app.services.caption_styles.get_settings")
    def test_style_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.style == "karaoke"

    @patch("app.services.caption_styles.get_settings")
    def test_position_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.position == "center"

    @patch("app.services.caption_styles.get_settings")
    def test_font_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.font_name == "Montserrat"
        assert config.font_size == 32

    @patch("app.services.caption_styles.get_settings")
    def test_uppercase_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.uppercase is False

    @patch("app.services.caption_styles.get_settings")
    def test_max_words_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.max_words_per_chunk == 4

    @patch("app.services.caption_styles.get_settings")
    def test_theme_colors_from_settings(self, mock_get):
        mock_get.return_value = self._mock_settings()
        config = build_caption_config()
        assert config.theme.primary == "AABBCC"
        assert config.theme.accent == "112233"
        assert config.theme.outline == "DDEEFF"
        assert config.theme.shadow == "80445566"

    @patch("app.services.caption_styles.get_settings")
    def test_missing_style_attribute_uses_default(self, mock_get):
        """When settings lacks captions_style, getattr default kicks in."""
        mock = self._mock_settings()
        del mock.captions_style
        mock_get.return_value = mock
        config = build_caption_config()
        assert config.style == "classic"

    @patch("app.services.caption_styles.get_settings")
    def test_missing_position_attribute_uses_default(self, mock_get):
        mock = self._mock_settings()
        del mock.captions_position
        mock_get.return_value = mock
        config = build_caption_config()
        assert config.position == "bottom"


# ── TestBackwardCompatibility ────────────────────────────────────


class TestBackwardCompatibility:
    """Classic style output matches original behavior (plain Dialogue lines)."""

    def test_classic_same_content_as_manual_format(self):
        """Classic lines should produce Dialogue lines with plain text, no tags."""
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)

        # Manually construct expected output
        expected = [
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,HELLO WORLD",
            "Dialogue: 0,0:00:01.20,0:00:02.50,Default,,0,0,0,,TESTING CAPTIONS",
        ]
        assert lines == expected

    def test_classic_via_dispatcher_matches_direct(self):
        """Dispatcher with 'classic' should produce identical output."""
        chunks = _make_chunks()
        config = _default_config(style="classic")
        dispatched = generate_styled_lines(chunks, config)
        direct = generate_classic_lines(chunks)
        assert dispatched == direct

    def test_classic_no_braces_in_output(self):
        """Classic lines should not contain any ASS override brace blocks."""
        chunks = _make_chunks()
        lines = generate_classic_lines(chunks)
        for line in lines:
            # The text portion (after last comma) should have no { }
            text_part = line.split(",", 9)[-1]
            assert "{" not in text_part
            assert "}" not in text_part


# ── TestPositionMap ──────────────────────────────────────────────


class TestPositionMap:
    """Verify POSITION_MAP entries have correct alignment and margin values."""

    def test_bottom_entry(self):
        assert POSITION_MAP["bottom"]["alignment"] == 2
        assert POSITION_MAP["bottom"]["margin_v"] == 200

    def test_center_entry(self):
        assert POSITION_MAP["center"]["alignment"] == 5
        assert POSITION_MAP["center"]["margin_v"] == 0

    def test_top_entry(self):
        assert POSITION_MAP["top"]["alignment"] == 8
        assert POSITION_MAP["top"]["margin_v"] == 120

    def test_all_three_positions_present(self):
        assert set(POSITION_MAP.keys()) == {"bottom", "center", "top"}
