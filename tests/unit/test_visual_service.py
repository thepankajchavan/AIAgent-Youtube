"""Unit tests for Visual service with mocked Pexels API."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.services.visual_service import search_videos, download_video, fetch_clips


class TestVideoSearch:
    """Test Pexels video search with mocked API."""

    @pytest.mark.asyncio
    async def test_search_videos_success(self, mocker):
        """Test successful video search with Pexels."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_pexels_api_key"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        # Mock cache (miss then store)
        mocker.patch("app.services.visual_service.get_cached_pexels_search", return_value=None)
        mocker.patch("app.services.visual_service.cache_pexels_search", return_value=True)

        # Mock Pexels API response
        mock_pexels_response = {
            "videos": [
                {
                    "id": 123,
                    "url": "https://pexels.com/video/123",
                    "duration": 10,
                    "video_files": [
                        {
                            "id": 1,
                            "file_type": "video/mp4",
                            "width": 1080,
                            "height": 1920,
                            "link": "https://example.com/video1.mp4"
                        }
                    ]
                },
                {
                    "id": 456,
                    "url": "https://pexels.com/video/456",
                    "duration": 15,
                    "video_files": [
                        {
                            "id": 2,
                            "file_type": "video/mp4",
                            "width": 720,
                            "height": 1280,
                            "link": "https://example.com/video2.mp4"
                        }
                    ]
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_pexels_response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        # Search videos
        result = await search_videos(
            query="ocean waves",
            orientation="portrait",
            per_page=5
        )

        # Verify result
        assert len(result) == 2
        assert result[0]["id"] == 123
        assert result[0]["duration"] == 10
        assert result[0]["width"] == 1080
        assert result[0]["height"] == 1920
        assert result[0]["download_url"] == "https://example.com/video1.mp4"

        # Verify API call
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "videos/search" in call_args[0][0]
        assert call_args[1]["params"]["query"] == "ocean waves"
        assert call_args[1]["params"]["orientation"] == "portrait"

    @pytest.mark.asyncio
    async def test_search_videos_filters_by_duration(self, mocker):
        """Test that videos outside duration range are filtered out."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_api_key"
        mocker.patch("app.services.visual_service.settings", mock_settings)
        mocker.patch("app.services.visual_service.get_cached_pexels_search", return_value=None)
        mocker.patch("app.services.visual_service.cache_pexels_search", return_value=True)

        mock_pexels_response = {
            "videos": [
                {
                    "id": 1,
                    "url": "https://pexels.com/video/1",
                    "duration": 3,  # Too short (min is 5)
                    "video_files": [{
                        "file_type": "video/mp4",
                        "width": 1080,
                        "height": 1920,
                        "link": "https://example.com/video1.mp4"
                    }]
                },
                {
                    "id": 2,
                    "url": "https://pexels.com/video/2",
                    "duration": 10,  # Valid
                    "video_files": [{
                        "file_type": "video/mp4",
                        "width": 1080,
                        "height": 1920,
                        "link": "https://example.com/video2.mp4"
                    }]
                },
                {
                    "id": 3,
                    "url": "https://pexels.com/video/3",
                    "duration": 35,  # Too long (max is 30)
                    "video_files": [{
                        "file_type": "video/mp4",
                        "width": 1080,
                        "height": 1920,
                        "link": "https://example.com/video3.mp4"
                    }]
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_pexels_response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await search_videos(query="test", min_duration=5, max_duration=30)

        # Only video with duration 10 should be included
        assert len(result) == 1
        assert result[0]["id"] == 2
        assert result[0]["duration"] == 10

    @pytest.mark.asyncio
    async def test_search_videos_prefers_portrait_orientation(self, mocker):
        """Test that portrait videos are preferred for portrait orientation."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_api_key"
        mocker.patch("app.services.visual_service.settings", mock_settings)
        mocker.patch("app.services.visual_service.get_cached_pexels_search", return_value=None)
        mocker.patch("app.services.visual_service.cache_pexels_search", return_value=True)

        mock_pexels_response = {
            "videos": [
                {
                    "id": 1,
                    "url": "https://pexels.com/video/1",
                    "duration": 10,
                    "video_files": [
                        # Landscape file (wrong orientation)
                        {
                            "file_type": "video/mp4",
                            "width": 1920,
                            "height": 1080,
                            "link": "https://example.com/landscape.mp4"
                        },
                        # Portrait file (correct orientation)
                        {
                            "file_type": "video/mp4",
                            "width": 1080,
                            "height": 1920,
                            "link": "https://example.com/portrait.mp4"
                        }
                    ]
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_pexels_response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await search_videos(query="test", orientation="portrait")

        # Should select portrait file
        assert len(result) == 1
        assert result[0]["width"] == 1080
        assert result[0]["height"] == 1920
        assert "portrait.mp4" in result[0]["download_url"]

    @pytest.mark.asyncio
    async def test_search_videos_no_results(self, mocker):
        """Test handling of empty search results."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_api_key"
        mocker.patch("app.services.visual_service.settings", mock_settings)
        mocker.patch("app.services.visual_service.get_cached_pexels_search", return_value=None)
        mocker.patch("app.services.visual_service.cache_pexels_search", return_value=True)

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"videos": []})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await search_videos(query="nonexistent_topic")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_videos_api_error(self, mocker):
        """Test that API errors are raised correctly."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "invalid_key"
        mocker.patch("app.services.visual_service.settings", mock_settings)
        mocker.patch("app.services.visual_service.get_cached_pexels_search", return_value=None)

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

        from tenacity import RetryError
        with pytest.raises((httpx.HTTPStatusError, RetryError)):
            await search_videos(query="test")


class TestVideoDownload:
    """Test video downloading from Pexels."""

    @pytest.mark.asyncio
    async def test_download_video_success(self, mocker, tmp_path):
        """Test successful video download."""
        mock_settings = MagicMock()
        mock_settings.video_dir = tmp_path / "videos"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        # Mock video data
        mock_video_data = b"fake_mp4_video_data" * 1000

        async def mock_aiter_bytes(chunk_size):
            yield mock_video_data

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        # Download video
        result = await download_video(
            download_url="https://example.com/video.mp4",
            output_filename="test_video.mp4"
        )

        # Verify result
        assert result.exists()
        assert result.name == "test_video.mp4"
        assert result.parent == tmp_path / "videos"
        assert result.read_bytes() == mock_video_data

    @pytest.mark.asyncio
    async def test_download_video_auto_filename(self, mocker, tmp_path):
        """Test that filename is auto-generated when not provided."""
        mock_settings = MagicMock()
        mock_settings.video_dir = tmp_path / "videos"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        async def mock_aiter_bytes(chunk_size):
            yield b"video_data"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await download_video("https://example.com/video.mp4")

        # Verify auto-generated filename
        assert result.name.startswith("pexels_")
        assert result.name.endswith(".mp4")
        assert len(result.name) == 23  # pexels_ (7) + 12 hex chars + .mp4 (4)

    @pytest.mark.asyncio
    async def test_download_video_creates_directory(self, mocker, tmp_path):
        """Test that video directory is created if it doesn't exist."""
        video_dir = tmp_path / "nonexistent" / "videos"

        mock_settings = MagicMock()
        mock_settings.video_dir = video_dir
        mocker.patch("app.services.visual_service.settings", mock_settings)

        async def mock_aiter_bytes(chunk_size):
            yield b"data"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("httpx.AsyncClient", return_value=mock_client)

        result = await download_video("https://example.com/video.mp4")

        # Verify directory was created
        assert video_dir.exists()
        assert result.parent == video_dir


class TestFetchClips:
    """Test high-level clip fetching (search + download)."""

    @pytest.mark.asyncio
    async def test_fetch_clips_success(self, mocker, tmp_path):
        """Test successful fetching of multiple clips."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_api_key"
        mock_settings.video_dir = tmp_path / "videos"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        # Mock search results
        mock_search_results = [
            {
                "id": 1,
                "download_url": "https://example.com/video1.mp4",
                "duration": 10
            },
            {
                "id": 2,
                "download_url": "https://example.com/video2.mp4",
                "duration": 15
            }
        ]

        # Mock search function
        async def mock_search_videos(query, orientation, per_page):
            return mock_search_results

        mocker.patch(
            "app.services.visual_service.search_videos",
            side_effect=mock_search_videos
        )

        # Mock download function
        download_counter = [0]

        async def mock_download_video(download_url):
            download_counter[0] += 1
            path = tmp_path / "videos" / f"video{download_counter[0]}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake_video_data")
            return path

        mocker.patch(
            "app.services.visual_service.download_video",
            side_effect=mock_download_video
        )

        # Fetch clips
        result = await fetch_clips(
            queries=["ocean", "sunset"],
            orientation="portrait",
            clips_per_query=2
        )

        # Verify results
        assert len(result) == 4  # 2 queries × 2 clips each
        assert all(p.exists() for p in result)
        assert all(p.name.endswith(".mp4") for p in result)

    @pytest.mark.asyncio
    async def test_fetch_clips_limits_clips_per_query(self, mocker, tmp_path):
        """Test that clips_per_query limit is respected."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_api_key"
        mock_settings.video_dir = tmp_path / "videos"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        # Mock 5 search results
        mock_search_results = [
            {"id": i, "download_url": f"https://example.com/video{i}.mp4"}
            for i in range(1, 6)
        ]

        async def mock_search_videos(query, orientation, per_page):
            return mock_search_results

        mocker.patch(
            "app.services.visual_service.search_videos",
            side_effect=mock_search_videos
        )

        download_calls = []

        async def mock_download_video(download_url):
            download_calls.append(download_url)
            path = tmp_path / "videos" / f"video{len(download_calls)}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"data")
            return path

        mocker.patch(
            "app.services.visual_service.download_video",
            side_effect=mock_download_video
        )

        # Fetch only 2 clips per query
        result = await fetch_clips(
            queries=["test"],
            clips_per_query=2
        )

        # Should only download 2 clips despite 5 being available
        assert len(result) == 2
        assert len(download_calls) == 2
