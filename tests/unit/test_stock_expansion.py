"""Unit tests for Phase 4: Smart stock fallback (query expansion).

Tests:
  - _expand_stock_query() synonym expansion and narration context
  - fetch_clips() with expand_queries flag
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.visual_service import _expand_stock_query


# ── _expand_stock_query tests ────────────────────────────────────


class TestExpandStockQuery:
    """Test stock query expansion logic."""

    def test_query_with_known_synonym(self):
        """Query containing 'ocean' should produce a synonym variant with 'sea'."""
        queries = _expand_stock_query("ocean sunset")

        assert "ocean sunset" in queries  # original always first
        # Should have a synonym variant
        assert any("sea" in q for q in queries)
        assert len(queries) >= 2

    def test_query_with_no_synonyms(self):
        """Query with no matching synonyms returns only the original."""
        queries = _expand_stock_query("random xylophone jazz")

        assert queries == ["random xylophone jazz"]

    def test_query_with_narration_context(self):
        """When narration is provided, a context-derived query should be added."""
        queries = _expand_stock_query(
            "sunset beach",
            narration="The golden sand stretches endlessly along the beautiful coastline.",
        )

        assert "sunset beach" in queries
        # Should have a narration-derived query with content words
        assert len(queries) >= 2
        # At least one query should contain words from narration
        all_text = " ".join(queries).lower()
        # Content words like "golden", "sand", "stretches", "endlessly" should appear
        assert any(
            word in all_text
            for word in ["golden", "sand", "stretches", "endlessly"]
        )

    def test_empty_narration_no_context_query(self):
        """Empty narration should not produce a context query."""
        queries = _expand_stock_query("city skyline", narration="")

        # Original + possibly synonym, but no narration-derived query
        for q in queries:
            if q != "city skyline":
                # If there's a second query, it should be synonym-based, not narration
                # "city" -> "urban skyline"
                assert "urban" in q.lower() or "skyline" in q.lower()

    def test_short_narration_no_context_query(self):
        """Narration with 3 or fewer words should not add a context query."""
        queries = _expand_stock_query("mountain peak", narration="Very short.")

        # Should not exceed original + synonym
        for q in queries:
            if q != "mountain peak":
                # Should be synonym variant only
                assert "peak" in q.lower() or "summit" in q.lower()

    def test_returns_max_3_queries(self):
        """Should never return more than 3 queries."""
        queries = _expand_stock_query(
            "ocean waves",
            narration="The vast endless ocean waves crash upon the rocky volcanic shoreline of the ancient island.",
        )

        assert len(queries) <= 3

    def test_deduplication(self):
        """Duplicate queries should be removed."""
        # "ocean" has synonym "sea", but if narration also yields something
        # matching original, it should be deduped
        queries = _expand_stock_query("ocean sunset", narration="ocean sunset is beautiful and amazing.")

        unique_lower = set(q.lower().strip() for q in queries)
        assert len(unique_lower) == len(queries)

    def test_multiple_synonyms_only_first_replaced(self):
        """Only the first matching synonym should be replaced."""
        # "space" -> "cosmos galaxy", only first match gets synonym
        queries = _expand_stock_query("space night sky")

        assert "space night sky" in queries
        if len(queries) > 1:
            # Should have replaced "space" with "cosmos galaxy"
            synonym_query = queries[1]
            assert "cosmos galaxy" in synonym_query or "sky" in synonym_query

    def test_city_synonym_expansion(self):
        """'city' should expand to variant with 'urban skyline'."""
        queries = _expand_stock_query("city night lights")

        assert queries[0] == "city night lights"
        assert any("urban skyline" in q for q in queries)

    def test_forest_synonym_expansion(self):
        """'forest' should expand to variant with 'woods trees'."""
        queries = _expand_stock_query("forest morning mist")

        assert queries[0] == "forest morning mist"
        assert any("woods trees" in q for q in queries)


# ── fetch_clips with expand_queries tests ─────────────────────────


@pytest.fixture(autouse=True)
def mock_pexels_rate_limit():
    """Auto-mock rate limit check so search tests don't need Redis."""
    with patch(
        "app.services.visual_service._check_pexels_rate_limit",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


class TestFetchClipsWithExpansion:
    """Test fetch_clips with query expansion enabled/disabled."""

    @pytest.mark.asyncio
    async def test_expand_queries_true_calls_search_with_variants(self, mocker, tmp_path):
        """With expand_queries=True, search should be tried with expanded queries."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_key"
        mock_settings.video_dir = tmp_path / "videos"
        mock_settings.stock_query_expansion_enabled = True
        mocker.patch("app.services.visual_service.settings", mock_settings)

        search_queries_called = []

        async def mock_search_videos(query, orientation, per_page):
            search_queries_called.append(query)
            if "sea" in query:  # synonym variant succeeds
                return [{"id": 1, "download_url": "https://example.com/v1.mp4", "duration": 10}]
            return []

        async def mock_download(url):
            path = tmp_path / "videos" / "downloaded.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            return path

        mocker.patch("app.services.visual_service.search_videos", side_effect=mock_search_videos)
        mocker.patch("app.services.visual_service.download_video", side_effect=mock_download)

        from app.services.visual_service import fetch_clips

        result = await fetch_clips(
            queries=["ocean sunset"],
            orientation="portrait",
            clips_per_query=1,
            expand_queries=True,
        )

        # Should have tried multiple query variants
        assert len(search_queries_called) >= 1
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_expand_queries_false_single_query(self, mocker, tmp_path):
        """With expand_queries=False, only the original query is used."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_key"
        mock_settings.video_dir = tmp_path / "videos"
        mocker.patch("app.services.visual_service.settings", mock_settings)

        search_queries_called = []

        async def mock_search_videos(query, orientation, per_page):
            search_queries_called.append(query)
            return [{"id": 1, "download_url": "https://example.com/v1.mp4", "duration": 10}]

        async def mock_download(url):
            path = tmp_path / "videos" / "downloaded.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            return path

        mocker.patch("app.services.visual_service.search_videos", side_effect=mock_search_videos)
        mocker.patch("app.services.visual_service.download_video", side_effect=mock_download)

        from app.services.visual_service import fetch_clips

        await fetch_clips(
            queries=["ocean sunset"],
            orientation="portrait",
            clips_per_query=1,
            expand_queries=False,
        )

        # Should have only used the original query
        assert len(search_queries_called) == 1
        assert search_queries_called[0] == "ocean sunset"

    @pytest.mark.asyncio
    async def test_first_expansion_fails_second_succeeds(self, mocker, tmp_path):
        """When the first query variant fails, the next variant should be tried."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_key"
        mock_settings.video_dir = tmp_path / "videos"
        mock_settings.stock_query_expansion_enabled = True
        mocker.patch("app.services.visual_service.settings", mock_settings)

        call_count = [0]

        async def mock_search_videos(query, orientation, per_page):
            call_count[0] += 1
            if call_count[0] == 1:
                return []  # First expansion fails
            return [{"id": 1, "download_url": "https://example.com/v1.mp4", "duration": 10}]

        async def mock_download(url):
            path = tmp_path / "videos" / "downloaded.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            return path

        mocker.patch("app.services.visual_service.search_videos", side_effect=mock_search_videos)
        mocker.patch("app.services.visual_service.download_video", side_effect=mock_download)

        from app.services.visual_service import fetch_clips

        result = await fetch_clips(
            queries=["ocean waves"],
            orientation="portrait",
            clips_per_query=1,
            narrations=["The vast ocean stretches endlessly toward the distant horizon line."],
            expand_queries=True,
        )

        # First query failed, second succeeded
        assert call_count[0] >= 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_narration_passed_to_expansion(self, mocker, tmp_path):
        """Narration should be used by _expand_stock_query for context."""
        mock_settings = MagicMock()
        mock_settings.pexels_api_key = "test_key"
        mock_settings.video_dir = tmp_path / "videos"
        mock_settings.stock_query_expansion_enabled = True
        mocker.patch("app.services.visual_service.settings", mock_settings)

        search_queries_called = []

        async def mock_search_videos(query, orientation, per_page):
            search_queries_called.append(query)
            if len(search_queries_called) == 1:
                return [{"id": 1, "download_url": "https://example.com/v.mp4", "duration": 10}]
            return []

        async def mock_download(url):
            path = tmp_path / "videos" / "v.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            return path

        mocker.patch("app.services.visual_service.search_videos", side_effect=mock_search_videos)
        mocker.patch("app.services.visual_service.download_video", side_effect=mock_download)

        # We can also verify by patching _expand_stock_query
        mock_expand = mocker.patch(
            "app.services.visual_service._expand_stock_query",
            return_value=["test query"],
        )

        from app.services.visual_service import fetch_clips

        await fetch_clips(
            queries=["test query"],
            narrations=["The aurora borealis dances across the arctic night sky."],
            expand_queries=True,
        )

        # Verify _expand_stock_query was called with narration
        mock_expand.assert_called_once_with(
            "test query",
            "The aurora borealis dances across the arctic night sky.",
        )
