"""Unit tests for the Music Service — Pixabay Music API integration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.music_service import (
    MOOD_SEARCH_MAP,
    VALID_MOODS,
    download_track,
    fetch_bgm_for_mood,
    search_music,
)

# ── Fixtures ──────────────────────────────────────────────────────


def _make_settings(tmp_path, api_key="test-key"):
    """Create a mock Settings object with reasonable defaults."""
    settings = MagicMock()
    settings.pixabay_api_key = api_key
    settings.media_path = tmp_path
    settings.bgm_default_mood = "uplifting"
    return settings


SAMPLE_PIXABAY_RESPONSE = {
    "totalHits": 2,
    "hits": [
        {
            "id": 10001,
            "title": "Energetic Beat",
            "audio": "https://cdn.pixabay.com/audio/10001.mp3",
            "duration": 60,
        },
        {
            "id": 10002,
            "title": "Uplifting Piano",
            "audio": "https://cdn.pixabay.com/audio/10002.mp3",
            "duration": 90,
        },
    ],
}

EMPTY_PIXABAY_RESPONSE = {"totalHits": 0, "hits": []}


# ── TestSearchMusic ───────────────────────────────────────────────


class TestSearchMusic:
    """Tests for search_music() — Pixabay Music API search."""

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, tmp_path):
        """Verify returned dicts have id, title, audio_url, duration keys."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_PIXABAY_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            tracks = await search_music("energetic")

        assert len(tracks) == 2
        for track in tracks:
            assert "id" in track
            assert "title" in track
            assert "audio_url" in track
            assert "duration" in track

        # Check actual values from sample response
        assert tracks[0]["id"] == "10001"
        assert tracks[0]["title"] == "Energetic Beat"
        assert tracks[0]["audio_url"] == "https://cdn.pixabay.com/audio/10001.mp3"
        assert tracks[0]["duration"] == 60

        assert tracks[1]["id"] == "10002"
        assert tracks[1]["title"] == "Uplifting Piano"

    @pytest.mark.asyncio
    async def test_mood_query_mapping(self, tmp_path):
        """Verify the correct mood -> Pixabay query string is used in API call."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_PIXABAY_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            await search_music("dramatic")

        # Inspect the params passed to client.get
        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["q"] == MOOD_SEARCH_MAP["dramatic"]
        assert params["key"] == "test-key"
        assert params["order"] == "popular"

    @pytest.mark.asyncio
    async def test_unknown_mood_uses_uplifting_fallback(self, tmp_path):
        """An unknown mood should fall back to the 'uplifting' query string."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_PIXABAY_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            await search_music("nonexistent_mood")

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["q"] == MOOD_SEARCH_MAP["uplifting"]

    @pytest.mark.asyncio
    async def test_min_max_duration_params(self, tmp_path):
        """Custom min/max duration values are forwarded to the API."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_PIXABAY_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            await search_music("calm", min_duration=10, max_duration=60)

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["min_duration"] == 10
        assert params["max_duration"] == 60

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self, tmp_path):
        """API returning zero hits should produce an empty list, not an error."""
        mock_response = MagicMock()
        mock_response.json.return_value = EMPTY_PIXABAY_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            tracks = await search_music("calm")

        assert tracks == []

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_list(self, tmp_path):
        """HTTP error from Pixabay should be caught; returns empty list."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=MagicMock(status_code=503),
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            tracks = await search_music("energetic")

        assert tracks == []

    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty_list(self, tmp_path):
        """Missing pixabay_api_key should skip the API call and return empty."""
        with patch(
            "app.services.music_service.get_settings",
            return_value=_make_settings(tmp_path, api_key=""),
        ):
            tracks = await search_music("energetic")

        assert tracks == []

    @pytest.mark.asyncio
    async def test_no_api_key_attribute_returns_empty_list(self, tmp_path):
        """Settings with no pixabay_api_key attribute should return empty list."""
        settings = MagicMock(spec=[])  # empty spec — no attributes
        del settings.pixabay_api_key  # ensure getattr falls through

        with patch("app.services.music_service.get_settings", return_value=settings):
            tracks = await search_music("calm")

        assert tracks == []


# ── TestDownloadTrack ─────────────────────────────────────────────


class TestDownloadTrack:
    """Tests for download_track() — downloading an audio file to disk."""

    @pytest.mark.asyncio
    async def test_saves_file_with_mp3_extension(self, tmp_path):
        """Downloaded file should be in output_dir with .mp3 extension."""
        audio_bytes = b"fake-mp3-content-bytes"

        mock_response = MagicMock()
        mock_response.content = audio_bytes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client):
            result = await download_track(
                "https://cdn.pixabay.com/audio/10001.mp3",
                output_dir=tmp_path,
            )

        assert result.suffix == ".mp3"
        assert result.parent == tmp_path
        assert result.exists()

    @pytest.mark.asyncio
    async def test_file_contains_correct_content(self, tmp_path):
        """The saved file must contain the exact bytes from the HTTP response."""
        audio_bytes = b"\xff\xfb\x90\x00" * 100  # fake MP3 frame data

        mock_response = MagicMock()
        mock_response.content = audio_bytes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client):
            result = await download_track(
                "https://cdn.pixabay.com/audio/10001.mp3",
                output_dir=tmp_path,
            )

        assert result.read_bytes() == audio_bytes

    @pytest.mark.asyncio
    async def test_default_output_dir_from_settings(self, tmp_path):
        """When output_dir is None, uses settings.media_path / 'bgm'."""
        audio_bytes = b"audio-data"

        mock_response = MagicMock()
        mock_response.content = audio_bytes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.music_service.get_settings", return_value=_make_settings(tmp_path)),
            patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await download_track("https://cdn.pixabay.com/audio/10001.mp3")

        assert result.parent == tmp_path / "bgm"
        assert result.exists()

    @pytest.mark.asyncio
    async def test_download_failure_raises_runtime_error(self, tmp_path):
        """Network failure during download must raise RuntimeError."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Failed to download BGM track"):
                await download_track(
                    "https://cdn.pixabay.com/audio/10001.mp3",
                    output_dir=tmp_path,
                )

    @pytest.mark.asyncio
    async def test_http_error_raises_runtime_error(self, tmp_path):
        """HTTP 404 during download must raise RuntimeError."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.music_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Failed to download BGM track"):
                await download_track(
                    "https://cdn.pixabay.com/audio/missing.mp3",
                    output_dir=tmp_path,
                )


# ── TestFetchBgmForMood ──────────────────────────────────────────


class TestFetchBgmForMood:
    """Tests for fetch_bgm_for_mood() — high-level search + download."""

    @pytest.mark.asyncio
    async def test_successful_path_returns_path(self, tmp_path):
        """Happy path: search finds tracks, download succeeds, returns Path."""
        downloaded_path = tmp_path / "bgm_abc123.mp3"
        downloaded_path.write_bytes(b"audio")

        sample_tracks = [
            {"id": "10001", "title": "Great Track", "audio_url": "https://example.com/a.mp3", "duration": 60},
        ]

        with (
            patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=sample_tracks),
            patch("app.services.music_service.download_track", new_callable=AsyncMock, return_value=downloaded_path),
        ):
            result = await fetch_bgm_for_mood("energetic", target_duration=45.0)

        assert result == downloaded_path
        assert isinstance(result, Path)

    @pytest.mark.asyncio
    async def test_no_tracks_found_returns_none(self):
        """Empty search results should return None, not raise."""
        with patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=[]):
            result = await fetch_bgm_for_mood("calm", target_duration=30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_search_fails_returns_none(self):
        """If search_music raises an exception, fetch_bgm_for_mood returns None."""
        with patch(
            "app.services.music_service.search_music",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API exploded"),
        ):
            result = await fetch_bgm_for_mood("epic", target_duration=60.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_download_fails_returns_none(self, tmp_path):
        """If download_track raises, fetch_bgm_for_mood returns None (graceful)."""
        sample_tracks = [
            {"id": "10001", "title": "Some Track", "audio_url": "https://example.com/a.mp3", "duration": 45},
        ]

        with (
            patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=sample_tracks),
            patch(
                "app.services.music_service.download_track",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Download failed"),
            ),
        ):
            result = await fetch_bgm_for_mood("happy", target_duration=40.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_tracks_without_audio_url(self, tmp_path):
        """Tracks with empty audio_url should be skipped; falls through to None."""
        tracks_no_url = [
            {"id": "10001", "title": "No URL Track", "audio_url": "", "duration": 60},
            {"id": "10002", "title": "Also No URL", "audio_url": "", "duration": 90},
        ]

        with patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=tracks_no_url):
            result = await fetch_bgm_for_mood("dark", target_duration=30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_picks_first_track_with_valid_url(self, tmp_path):
        """Should pick the first track that has a non-empty audio_url."""
        downloaded_path = tmp_path / "bgm_picked.mp3"
        downloaded_path.write_bytes(b"audio")

        tracks = [
            {"id": "10001", "title": "No URL", "audio_url": "", "duration": 60},
            {"id": "10002", "title": "Has URL", "audio_url": "https://example.com/b.mp3", "duration": 90},
        ]

        with (
            patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=tracks),
            patch("app.services.music_service.download_track", new_callable=AsyncMock, return_value=downloaded_path) as mock_dl,
        ):
            result = await fetch_bgm_for_mood("sad", target_duration=50.0)

        assert result == downloaded_path
        mock_dl.assert_awaited_once_with("https://example.com/b.mp3")

    @pytest.mark.asyncio
    async def test_duration_bounds_calculation(self):
        """Verify min_dur/max_dur are computed from target_duration correctly."""
        with (
            patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=[]) as mock_search,
        ):
            await fetch_bgm_for_mood("chill", target_duration=60.0)

        # min_dur = max(15, int(60.0 * 0.5)) = 30
        # max_dur = max(120, int(60.0 * 3)) = 180
        mock_search.assert_awaited_once_with("chill", min_duration=30, max_duration=180)

    @pytest.mark.asyncio
    async def test_short_duration_clamps_min_to_15(self):
        """Very short target_duration should clamp min_dur to 15."""
        with (
            patch("app.services.music_service.search_music", new_callable=AsyncMock, return_value=[]) as mock_search,
        ):
            await fetch_bgm_for_mood("calm", target_duration=10.0)

        # min_dur = max(15, int(10.0 * 0.5)) = max(15, 5) = 15
        # max_dur = max(120, int(10.0 * 3)) = max(120, 30) = 120
        mock_search.assert_awaited_once_with("calm", min_duration=15, max_duration=120)


# ── TestModuleLevelConstants ──────────────────────────────────────


class TestModuleLevelConstants:
    """Verify module-level constants are properly defined."""

    def test_valid_moods_matches_map_keys(self):
        """VALID_MOODS must exactly equal the keys of MOOD_SEARCH_MAP."""
        assert VALID_MOODS == set(MOOD_SEARCH_MAP.keys())

    def test_all_expected_moods_present(self):
        """Check that the core set of moods is present."""
        expected = {"energetic", "calm", "dramatic", "mysterious", "uplifting",
                    "dark", "happy", "sad", "epic", "chill"}
        assert expected.issubset(VALID_MOODS)

    def test_mood_map_values_are_nonempty_strings(self):
        """Each mood must map to a non-empty search query string."""
        for mood, query in MOOD_SEARCH_MAP.items():
            assert isinstance(query, str), f"Mood '{mood}' query is not a string"
            assert len(query) > 0, f"Mood '{mood}' has empty query"
