"""Unit tests for TTS service with mocked ElevenLabs API."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.tts_service import generate_speech, get_available_voices


class TestSpeechGeneration:
    """Test text-to-speech generation with ElevenLabs (mocked)."""

    @pytest.mark.asyncio
    async def test_generate_speech_success(self, mocker, tmp_path):
        """Test successful speech generation with ElevenLabs."""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mock_settings.elevenlabs_voice_id = "test_voice_id"
        mock_settings.audio_dir = tmp_path / "audio"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Mock HTTP response with audio bytes
        mock_audio_data = b"fake_mp3_audio_data_here" * 100  # Simulate audio bytes

        async def mock_aiter_bytes(chunk_size):
            """Simulate streaming audio chunks."""
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

        # Patch AsyncClient
        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        # Generate speech
        result = await generate_speech(
            text="Hello, this is a test.",
            output_filename="test_audio.mp3"
        )

        # Verify result
        assert result.exists()
        assert result.name == "test_audio.mp3"
        assert result.parent == tmp_path / "audio"

        # Verify file contains audio data
        assert result.read_bytes() == mock_audio_data

        # Verify API was called correctly
        mock_client.stream.assert_called_once()
        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert "text-to-speech/test_voice_id/stream" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_generate_speech_auto_filename(self, mocker, tmp_path):
        """Test that filename is auto-generated when not provided."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mock_settings.elevenlabs_voice_id = "voice123"
        mock_settings.audio_dir = tmp_path / "audio"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Mock HTTP response
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

        # Generate without filename
        result = await generate_speech(text="Test")

        # Verify auto-generated filename
        assert result.name.startswith("tts_")
        assert result.name.endswith(".mp3")
        assert len(result.name) == 20  # tts_ (4) + 12 hex chars + .mp3 (4)

    @pytest.mark.asyncio
    async def test_generate_speech_custom_voice_settings(self, mocker, tmp_path):
        """Test speech generation with custom voice parameters."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mock_settings.elevenlabs_voice_id = "default_voice"
        mock_settings.audio_dir = tmp_path / "audio"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Capture the request payload
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

        # Generate with custom settings
        await generate_speech(
            text="Test",
            voice_id="custom_voice",
            model_id="eleven_turbo_v2",
            stability=0.8,
            similarity_boost=0.9,
            style=0.5
        )

        # Verify custom parameters in payload
        assert captured_payload["model_id"] == "eleven_turbo_v2"
        assert captured_payload["voice_settings"]["stability"] == 0.8
        assert captured_payload["voice_settings"]["similarity_boost"] == 0.9
        assert captured_payload["voice_settings"]["style"] == 0.5
        assert captured_payload["voice_settings"]["use_speaker_boost"] is True

    @pytest.mark.asyncio
    async def test_generate_speech_api_error(self, mocker, tmp_path):
        """Test that API errors are raised correctly."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mock_settings.elevenlabs_voice_id = "voice123"
        mock_settings.audio_dir = tmp_path / "audio"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Mock HTTP error
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401)
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

        # Should raise after retries exhausted (tenacity wraps in RetryError)
        from tenacity import RetryError
        with pytest.raises((httpx.HTTPStatusError, RetryError)):
            await generate_speech(text="Test")

    @pytest.mark.asyncio
    async def test_generate_speech_creates_audio_dir(self, mocker, tmp_path):
        """Test that audio directory is created if it doesn't exist."""
        audio_dir = tmp_path / "nonexistent" / "audio"

        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mock_settings.elevenlabs_voice_id = "voice123"
        mock_settings.audio_dir = audio_dir
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Mock successful response
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

        # Generate speech
        result = await generate_speech(text="Test")

        # Verify directory was created
        assert audio_dir.exists()
        assert result.parent == audio_dir


class TestVoiceRetrieval:
    """Test fetching available voices from ElevenLabs."""

    @pytest.mark.asyncio
    async def test_get_available_voices_success(self, mocker):
        """Test successful retrieval of available voices."""
        mock_settings = MagicMock()
        mock_settings.elevenlabs_api_key = "test_api_key"
        mocker.patch("app.services.tts_service.settings", mock_settings)

        # Mock API response
        mock_voices_data = {
            "voices": [
                {
                    "voice_id": "voice1",
                    "name": "Rachel",
                    "category": "premade"
                },
                {
                    "voice_id": "voice2",
                    "name": "Domi",
                    "category": "premade"
                },
                {
                    "voice_id": "voice3",
                    "name": "Bella",
                    # Missing category
                }
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

        # Get voices
        result = await get_available_voices()

        # Verify result
        assert len(result) == 3
        assert result[0]["voice_id"] == "voice1"
        assert result[0]["name"] == "Rachel"
        assert result[0]["category"] == "premade"
        assert result[2]["category"] == "unknown"  # Default for missing category

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
                "401 Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401)
            )
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        with pytest.raises(httpx.HTTPStatusError):
            await get_available_voices()
