"""Unit tests for TTS service with mocked ElevenLabs API."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.tts_service import (
    _check_character_budget,
    _preprocess_text_for_tts,
    generate_speech,
    get_available_voices,
)


def _make_mock_settings(**overrides):
    """Create a mock settings object with all ElevenLabs attributes."""
    defaults = {
        "elevenlabs_api_key": "test_api_key",
        "elevenlabs_voice_id": "test_voice_id",
        "elevenlabs_model": "eleven_turbo_v2_5",
        "elevenlabs_output_format": "mp3_44100_192",
        "elevenlabs_stability": 0.55,
        "elevenlabs_similarity_boost": 0.80,
        "elevenlabs_style": 0.35,
        "elevenlabs_monthly_char_limit": 100_000,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestTextPreprocessing:
    """Test _preprocess_text_for_tts text transformations."""

    def test_large_numbers(self):
        """Large numbers are converted to words."""
        result = _preprocess_text_for_tts("There are 6000000 stars.")
        assert "six million" in result
        assert "6000000" not in result

    def test_ordinals(self):
        """Ordinals like 1st, 2nd, 3rd are expanded."""
        result = _preprocess_text_for_tts("He finished 1st in the race.")
        assert "first" in result
        assert "1st" not in result

    def test_ordinal_3rd(self):
        """3rd ordinal is expanded."""
        result = _preprocess_text_for_tts("The 3rd option.")
        assert "third" in result

    def test_percentages(self):
        """Percentages are expanded to words."""
        result = _preprocess_text_for_tts("About 99.9% of cases.")
        assert "percent" in result
        assert "99.9%" not in result

    def test_currency_with_magnitude(self):
        """Currency with magnitude suffix is expanded."""
        result = _preprocess_text_for_tts("It costs $2.5M to build.")
        assert "million" in result
        assert "dollars" in result
        assert "$2.5M" not in result

    def test_currency_simple(self):
        """Simple currency is expanded without double spaces."""
        result = _preprocess_text_for_tts("He earned $500 today.")
        assert "five hundred dollars" in result
        assert "$500" not in result
        assert "  " not in result

    def test_units_mph(self):
        """Speed units are expanded."""
        result = _preprocess_text_for_tts("Going 60 mph on the highway.")
        assert "miles per hour" in result
        assert "60 mph" not in result

    def test_units_km(self):
        """Distance units are expanded."""
        result = _preprocess_text_for_tts("It was 5 km away.")
        assert "kilometers" in result

    def test_year_modern(self):
        """Modern years are expanded naturally."""
        result = _preprocess_text_for_tts("In 2024 something happened.")
        assert "twenty twenty-four" in result
        assert "2024" not in result

    def test_year_2000s(self):
        """Years in the 2000s decade are expanded."""
        result = _preprocess_text_for_tts("Back in 2005 we started.")
        assert "2005" not in result
        # num2words converts 2005 → "two thousand and five"
        assert "two thousand" in result

    def test_acronyms(self):
        """Uppercase acronyms get dotted."""
        result = _preprocess_text_for_tts("The US government.")
        assert "U.S." in result
        assert " US " not in result

    def test_acronym_nasa(self):
        """Multi-letter acronyms get dotted."""
        result = _preprocess_text_for_tts("NASA launched a rocket.")
        assert "N.A.S.A." in result

    def test_small_numbers(self):
        """Small standalone numbers are converted."""
        result = _preprocess_text_for_tts("There are 5 reasons.")
        assert "five" in result

    def test_plain_text_unchanged(self):
        """Text without numbers/acronyms passes through."""
        text = "The quick brown fox jumps over the lazy dog."
        result = _preprocess_text_for_tts(text)
        assert result == text


class TestCharacterBudget:
    """Test _check_character_budget warnings and rejections."""

    def test_within_budget_no_warning(self, mocker):
        """No warning when well within budget."""
        mock_settings = _make_mock_settings(elevenlabs_monthly_char_limit=100_000)
        mocker.patch("app.services.tts_service.settings", mock_settings)
        # Should not raise
        _check_character_budget(50_000)

    def test_warning_at_80_percent(self, mocker):
        """Warning logged when at 80% of budget."""
        mock_settings = _make_mock_settings(elevenlabs_monthly_char_limit=100_000)
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mock_logger = mocker.patch("app.services.tts_service.logger")
        _check_character_budget(85_000)
        mock_logger.warning.assert_called_once()

    def test_reject_over_limit(self, mocker):
        """ValueError raised when exceeding budget."""
        mock_settings = _make_mock_settings(elevenlabs_monthly_char_limit=100_000)
        mocker.patch("app.services.tts_service.settings", mock_settings)
        with pytest.raises(ValueError, match="exceeds monthly ElevenLabs limit"):
            _check_character_budget(150_000)


class TestSpeechGeneration:
    """Test text-to-speech generation with ElevenLabs (mocked)."""

    @pytest.mark.asyncio
    async def test_generate_speech_success(self, mocker, tmp_path):
        """Test successful speech generation with ElevenLabs."""
        mock_settings = _make_mock_settings(audio_dir=tmp_path / "audio")
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        mock_audio_data = b"fake_mp3_audio_data_here" * 100

        async def mock_aiter_bytes(chunk_size):
            yield mock_audio_data

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await generate_speech(
            text="Hello, this is a test.", output_filename="test_audio.mp3"
        )

        assert result.exists()
        assert result.name == "test_audio.mp3"
        assert result.parent == tmp_path / "audio"
        assert result.read_bytes() == mock_audio_data

        mock_client.stream.assert_called_once()
        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert "text-to-speech/test_voice_id/stream" in call_args[0][1]
        assert "output_format=mp3_44100_192" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_generate_speech_auto_filename(self, mocker, tmp_path):
        """Test that filename is auto-generated when not provided."""
        mock_settings = _make_mock_settings(
            elevenlabs_voice_id="voice123", audio_dir=tmp_path / "audio"
        )
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        async def mock_aiter_bytes(chunk_size):
            yield b"audio_data"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await generate_speech(text="Test")

        assert result.name.startswith("tts_")
        assert result.name.endswith(".mp3")
        assert len(result.name) == 20  # tts_ (4) + 12 hex chars + .mp3 (4)

    @pytest.mark.asyncio
    async def test_generate_speech_custom_voice_settings(self, mocker, tmp_path):
        """Test speech generation with custom voice parameters."""
        mock_settings = _make_mock_settings(
            elevenlabs_voice_id="default_voice", audio_dir=tmp_path / "audio"
        )
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        captured_payload = {}

        async def mock_aiter_bytes(chunk_size=8192):
            yield b"audio"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        def capture_stream(method, url, json=None, headers=None):
            captured_payload.update(json)
            return mock_stream

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = capture_stream
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        await generate_speech(
            text="Test",
            voice_id="custom_voice",
            model_id="eleven_turbo_v2",
            stability=0.8,
            similarity_boost=0.9,
            style=0.5,
        )

        assert captured_payload["model_id"] == "eleven_turbo_v2"
        assert captured_payload["voice_settings"]["stability"] == 0.8
        assert captured_payload["voice_settings"]["similarity_boost"] == 0.9
        assert captured_payload["voice_settings"]["style"] == 0.5
        assert captured_payload["voice_settings"]["use_speaker_boost"] is True

    @pytest.mark.asyncio
    async def test_generate_speech_uses_settings_defaults(self, mocker, tmp_path):
        """Test that generate_speech uses settings when params are None."""
        mock_settings = _make_mock_settings(
            elevenlabs_voice_id="adam_voice",
            elevenlabs_model="eleven_turbo_v2_5",
            elevenlabs_stability=0.55,
            elevenlabs_similarity_boost=0.80,
            elevenlabs_style=0.35,
            audio_dir=tmp_path / "audio",
        )
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        captured_payload = {}

        async def mock_aiter_bytes(chunk_size=8192):
            yield b"audio"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        def capture_stream(method, url, json=None, headers=None):
            captured_payload.update(json)
            return mock_stream

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = capture_stream
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        # Call with no explicit params — should use settings
        await generate_speech(text="Test defaults")

        assert captured_payload["model_id"] == "eleven_turbo_v2_5"
        assert captured_payload["voice_settings"]["stability"] == 0.55
        assert captured_payload["voice_settings"]["similarity_boost"] == 0.80
        assert captured_payload["voice_settings"]["style"] == 0.35

    @pytest.mark.asyncio
    async def test_generate_speech_api_error(self, mocker, tmp_path):
        """Test that API errors are raised correctly."""
        mock_settings = _make_mock_settings(
            elevenlabs_voice_id="voice123", audio_dir=tmp_path / "audio"
        )
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
            )
        )

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        from tenacity import RetryError

        with pytest.raises((httpx.HTTPStatusError, RetryError)):
            await generate_speech(text="Test")

    @pytest.mark.asyncio
    async def test_generate_speech_creates_audio_dir(self, mocker, tmp_path):
        """Test that audio directory is created if it doesn't exist."""
        audio_dir = tmp_path / "nonexistent" / "audio"

        mock_settings = _make_mock_settings(
            elevenlabs_voice_id="voice123", audio_dir=audio_dir
        )
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        async def mock_aiter_bytes(chunk_size):
            yield b"audio"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await generate_speech(text="Test")

        assert audio_dir.exists()
        assert result.parent == audio_dir

    @pytest.mark.asyncio
    async def test_generate_speech_calls_normalize(self, mocker, tmp_path):
        """Test that normalize_audio is called after saving."""
        mock_settings = _make_mock_settings(audio_dir=tmp_path / "audio")
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mock_normalize = mocker.patch(
            "app.services.tts_service.normalize_audio", side_effect=lambda p: p
        )

        async def mock_aiter_bytes(chunk_size):
            yield b"audio"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await generate_speech(text="Test", output_filename="test.mp3")

        mock_normalize.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_generate_speech_preprocesses_text(self, mocker, tmp_path):
        """Test that text is preprocessed before sending to API."""
        mock_settings = _make_mock_settings(audio_dir=tmp_path / "audio")
        mocker.patch("app.services.tts_service.settings", mock_settings)
        mocker.patch("app.services.tts_service.normalize_audio", side_effect=lambda p: p)

        captured_payload = {}

        async def mock_aiter_bytes(chunk_size=8192):
            yield b"audio"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        def capture_stream(method, url, json=None, headers=None):
            captured_payload.update(json)
            return mock_stream

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = capture_stream
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        await generate_speech(text="There are 5000000 people.")

        # The text should be preprocessed — raw number should not appear
        assert "5000000" not in captured_payload["text"]
        assert "million" in captured_payload["text"]


class TestVoiceRetrieval:
    """Test fetching available voices from ElevenLabs."""

    @pytest.mark.asyncio
    async def test_get_available_voices_success(self, mocker):
        """Test successful retrieval of available voices."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        mock_voices_data = {
            "voices": [
                {"voice_id": "voice1", "name": "Rachel", "category": "premade"},
                {"voice_id": "voice2", "name": "Domi", "category": "premade"},
                {
                    "voice_id": "voice3",
                    "name": "Bella",
                },
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_voices_data)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await get_available_voices()

        assert len(result) == 3
        assert result[0]["voice_id"] == "voice1"
        assert result[0]["name"] == "Rachel"
        assert result[0]["category"] == "premade"
        assert result[2]["category"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_available_voices_empty_response(self, mocker):
        """Test handling of empty voices list."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"voices": []})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await get_available_voices()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_available_voices_api_error(self, mocker):
        """Test that API errors are raised correctly."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "invalid_key"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
            )
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        with pytest.raises(httpx.HTTPStatusError):
            await get_available_voices()
