"""Unit tests for Caption service — word grouping, ASS generation, Whisper integration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.caption_service import (
    CaptionChunk,
    WordTimestamp,
    _format_ass_time,
    _generate_ass_file,
    _group_words,
    generate_captions,
)


# ── TestWordGrouping ─────────────────────────────────────────────


class TestWordGrouping:
    """Test _group_words chunking logic."""

    def test_groups_by_max_words(self):
        """Words are grouped into chunks of max_per_chunk."""
        words = [
            WordTimestamp("You", 0.0, 0.2),
            WordTimestamp("won't", 0.2, 0.5),
            WordTimestamp("believe", 0.5, 0.9),
            WordTimestamp("what", 1.0, 1.2),
            WordTimestamp("happened", 1.2, 1.6),
            WordTimestamp("next", 1.6, 1.9),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words(words, max_per_chunk=3)

        assert len(chunks) == 2
        assert chunks[0].text == "YOU WON'T BELIEVE"
        assert chunks[1].text == "WHAT HAPPENED NEXT"

    def test_splits_on_pause(self):
        """A pause > threshold forces a new chunk."""
        words = [
            WordTimestamp("Hello", 0.0, 0.3),
            WordTimestamp("world", 0.3, 0.6),
            # 0.5s pause here
            WordTimestamp("How", 1.1, 1.3),
            WordTimestamp("are", 1.3, 1.5),
            WordTimestamp("you", 1.5, 1.8),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words(words, max_per_chunk=3, pause_threshold=0.3)

        assert len(chunks) == 2
        assert chunks[0].text == "HELLO WORLD"
        assert chunks[1].text == "HOW ARE YOU"

    def test_splits_on_sentence_boundary(self):
        """Words ending with punctuation force a chunk break."""
        words = [
            WordTimestamp("Yes.", 0.0, 0.3),
            WordTimestamp("It", 0.4, 0.5),
            WordTimestamp("works!", 0.5, 0.8),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words(words, max_per_chunk=3)

        assert len(chunks) == 2
        assert chunks[0].text == "YES."
        assert chunks[1].text == "IT WORKS!"

    def test_empty_words(self):
        """Empty word list returns empty chunks."""
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words([], max_per_chunk=3)

        assert chunks == []

    def test_single_word(self):
        """Single word produces one chunk."""
        words = [WordTimestamp("Hello", 0.0, 0.5)]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words(words, max_per_chunk=3)

        assert len(chunks) == 1
        assert chunks[0].text == "HELLO"
        assert chunks[0].start == 0.0
        assert chunks[0].end == 0.5

    def test_uppercase_conversion(self):
        """Text is uppercased when captions_uppercase is True."""
        words = [
            WordTimestamp("hello", 0.0, 0.2),
            WordTimestamp("world", 0.2, 0.5),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = True
            chunks = _group_words(words, max_per_chunk=3)

        assert chunks[0].text == "HELLO WORLD"

    def test_no_uppercase_when_disabled(self):
        """Text is NOT uppercased when captions_uppercase is False."""
        words = [
            WordTimestamp("hello", 0.0, 0.2),
            WordTimestamp("World", 0.2, 0.5),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_uppercase = False
            chunks = _group_words(words, max_per_chunk=3)

        assert chunks[0].text == "hello World"


# ── TestFormatAssTime ────────────────────────────────────────────


class TestFormatAssTime:
    """Test _format_ass_time conversion."""

    def test_zero(self):
        assert _format_ass_time(0.0) == "0:00:00.00"

    def test_simple_seconds(self):
        assert _format_ass_time(5.25) == "0:00:05.25"

    def test_minutes_and_seconds(self):
        assert _format_ass_time(65.5) == "0:01:05.50"

    def test_centisecond_rounding(self):
        # 1.999 → rounds to 200 centiseconds = 2.00
        assert _format_ass_time(1.999) == "0:00:02.00"


# ── TestGenerateAssFile ──────────────────────────────────────────


class TestGenerateAssFile:
    """Test _generate_ass_file output."""

    def test_generates_valid_ass_file(self, tmp_path):
        """Generated ASS file has correct structure."""
        chunks = [
            CaptionChunk("HELLO WORLD", 0.0, 0.5),
            CaptionChunk("HOW ARE YOU", 0.6, 1.2),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_dir = tmp_path
            mock_settings.return_value.captions_font = "Arial"
            mock_settings.return_value.captions_font_size = 18
            ass_path = _generate_ass_file(chunks)

        assert ass_path.exists()
        content = ass_path.read_text(encoding="utf-8")

        # Check ASS structure
        assert "[Script Info]" in content
        assert "PlayResX: 1080" in content
        assert "PlayResY: 1920" in content
        assert "[V4+ Styles]" in content
        assert "Style: Default,Arial,18" in content
        assert "[Events]" in content

        # Check dialogue lines
        assert "Dialogue: 0,0:00:00.00,0:00:00.50,Default,,0,0,0,,HELLO WORLD" in content
        assert "Dialogue: 0,0:00:00.60,0:00:01.20,Default,,0,0,0,,HOW ARE YOU" in content

    def test_escapes_special_characters(self, tmp_path):
        """Special ASS characters are escaped in text."""
        chunks = [
            CaptionChunk("TEST {BRACES} HERE", 0.0, 0.5),
        ]
        with patch("app.services.caption_service.get_settings") as mock_settings:
            mock_settings.return_value.captions_dir = tmp_path
            mock_settings.return_value.captions_font = "Arial"
            mock_settings.return_value.captions_font_size = 18
            ass_path = _generate_ass_file(chunks)

        content = ass_path.read_text(encoding="utf-8")
        # Braces should be escaped
        assert "\\{BRACES\\}" in content


# ── TestGenerateCaptions ─────────────────────────────────────────


class TestGenerateCaptions:
    """Test the full generate_captions flow."""

    @pytest.mark.asyncio
    async def test_success(self, tmp_path):
        """Full flow: Whisper → group → ASS file."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake_audio")

        # Mock Whisper response
        mock_word_1 = MagicMock()
        mock_word_1.word = "Hello"
        mock_word_1.start = 0.0
        mock_word_1.end = 0.3

        mock_word_2 = MagicMock()
        mock_word_2.word = "world"
        mock_word_2.start = 0.3
        mock_word_2.end = 0.6

        mock_transcription = MagicMock()
        mock_transcription.words = [mock_word_1, mock_word_2]

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcription)

        with (
            patch("app.services.caption_service.get_settings") as mock_settings,
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            mock_settings.return_value.openai_api_key = "test-key"
            mock_settings.return_value.captions_max_words_per_chunk = 3
            mock_settings.return_value.captions_uppercase = True
            mock_settings.return_value.captions_dir = tmp_path
            mock_settings.return_value.captions_font = "Arial"
            mock_settings.return_value.captions_font_size = 18

            result = await generate_captions(audio_path)

        assert result.exists()
        assert result.suffix == ".ass"
        content = result.read_text(encoding="utf-8")
        assert "HELLO WORLD" in content

    @pytest.mark.asyncio
    async def test_whisper_failure_raises(self, tmp_path):
        """Whisper API failure raises exception (caller handles gracefully)."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"fake_audio")

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=RuntimeError("Whisper API error")
        )

        with (
            patch("app.services.caption_service.get_settings") as mock_settings,
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            mock_settings.return_value.openai_api_key = "test-key"

            with pytest.raises(RuntimeError, match="Whisper API error"):
                await generate_captions(audio_path)
