"""Unit tests for DynamicPromptBuilder."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

DB_FACTORY = "app.core.database.async_session_factory"

FAKE_VERSION_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
FAKE_PROJECT_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"


def _mock_session_ctx(mock_session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestBuildEnrichedPrompt:
    """Tests for prompt enrichment with trends and patterns."""

    @patch("app.services.pattern_service.PatternService.get_active_patterns")
    @patch("app.services.trend_service.TrendService.get_trend_for_video")
    @patch("app.services.prompt_builder_service.DynamicPromptBuilder._get_active_version")
    @pytest.mark.asyncio
    async def test_build_enriched_prompt_with_trends_and_patterns(
        self, mock_version, mock_trend, mock_patterns
    ):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_version.return_value = {
            "id": "version-1",
            "template": "Write about: {topic}",
            "version_label": "v1",
        }

        mock_trend.return_value = {
            "id": "trend-1",
            "topic": "AI breakthrough",
            "trend_score": 85.0,
            "source": "google_trends",
        }

        mock_patterns.return_value = [
            {"id": "p-1", "description": "Use questions as hooks", "confidence_score": 0.85},
        ]

        builder = DynamicPromptBuilder()
        prompt, metadata = await builder.build_enriched_prompt(
            base_topic="Mars exploration",
            niche="science",
        )

        assert "Mars exploration" in prompt
        assert "AI breakthrough" in prompt
        assert "TRENDING NOW" in prompt
        assert "PROVEN PATTERNS" in prompt
        assert metadata["prompt_version_id"] == "version-1"
        assert metadata["trend_topic_used"] == "AI breakthrough"
        assert len(metadata["patterns_applied"]) == 1

    @patch("app.services.pattern_service.PatternService.get_active_patterns")
    @patch("app.services.trend_service.TrendService.get_trend_for_video")
    @patch("app.services.prompt_builder_service.DynamicPromptBuilder._get_active_version")
    @pytest.mark.asyncio
    async def test_build_enriched_prompt_no_trends_available(
        self, mock_version, mock_trend, mock_patterns
    ):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_version.return_value = {
            "id": "version-1",
            "template": "Write about: {topic}",
            "version_label": "v1",
        }

        mock_trend.return_value = None
        mock_patterns.return_value = []

        builder = DynamicPromptBuilder()
        prompt, metadata = await builder.build_enriched_prompt(base_topic="Space facts")

        assert "Space facts" in prompt
        assert "TRENDING NOW" not in prompt
        assert "PROVEN PATTERNS" not in prompt
        assert metadata["trend_topic_used"] is None
        assert metadata["patterns_applied"] == []

    @patch("app.services.pattern_service.PatternService.get_active_patterns")
    @patch("app.services.trend_service.TrendService.get_trend_for_video")
    @patch("app.services.prompt_builder_service.DynamicPromptBuilder._get_active_version")
    @pytest.mark.asyncio
    async def test_build_enriched_prompt_no_patterns_available(
        self, mock_version, mock_trend, mock_patterns
    ):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_version.return_value = {
            "id": "v-1",
            "template": "Write about: {topic}",
            "version_label": "v1",
        }

        mock_trend.return_value = {
            "id": "t-1", "topic": "Trend X", "trend_score": 90, "source": "yt"
        }
        mock_patterns.return_value = []

        builder = DynamicPromptBuilder()
        prompt, metadata = await builder.build_enriched_prompt(base_topic="topic")

        assert "TRENDING NOW" in prompt
        assert "PROVEN PATTERNS" not in prompt

    @patch("app.services.pattern_service.PatternService.get_active_patterns")
    @patch("app.services.trend_service.TrendService.get_trend_for_video")
    @patch("app.services.prompt_builder_service.DynamicPromptBuilder._get_active_version")
    @pytest.mark.asyncio
    async def test_build_enriched_prompt_trend_failure_graceful(
        self, mock_version, mock_trend, mock_patterns
    ):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_version.return_value = {
            "id": "v-1", "template": "Write about: {topic}", "version_label": "v1"
        }

        mock_trend.side_effect = Exception("Trend API down")
        mock_patterns.return_value = []

        builder = DynamicPromptBuilder()
        prompt, metadata = await builder.build_enriched_prompt(base_topic="topic")

        assert "topic" in prompt
        assert metadata["trend_topic_used"] is None


class TestCreateDefaultBaseline:
    """Tests for baseline prompt version creation."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_create_default_baseline_version(self, mock_factory):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_session = AsyncMock()
        mock_factory.return_value = _mock_session_ctx(mock_session)

        builder = DynamicPromptBuilder()
        result = await builder._create_default_baseline()

        assert result["version_label"] == "v1-baseline"
        assert "{topic}" in result["template"]
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


class TestPromoteVersion:
    """Tests for prompt version promotion."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_promote_version_requires_min_usage(self, mock_factory):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_version = MagicMock()
        mock_version.usage_count = 2

        mock_session = AsyncMock()
        mock_session.get.return_value = mock_version

        mock_factory.return_value = _mock_session_ctx(mock_session)

        builder = DynamicPromptBuilder()
        promoted = await builder.promote_version(FAKE_VERSION_UUID)

        assert promoted is False


class TestRecordPromptUsage:
    """Tests for prompt usage recording."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_record_prompt_usage_increments_count(self, mock_factory):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_session = AsyncMock()
        mock_factory.return_value = _mock_session_ctx(mock_session)

        builder = DynamicPromptBuilder()
        await builder.record_prompt_usage(FAKE_VERSION_UUID, FAKE_PROJECT_UUID)

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestUpdatePromptPerformance:
    """Tests for prompt performance recalculation."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_update_prompt_performance_recalculates(self, mock_factory):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_session = AsyncMock()

        mock_row = MagicMock()
        mock_row.avg_views = 3500.0
        mock_row.avg_retention = 55.0
        mock_row.avg_ctr = 4.5

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row

        mock_session.execute.side_effect = [mock_result, AsyncMock()]

        mock_factory.return_value = _mock_session_ctx(mock_session)

        builder = DynamicPromptBuilder()
        await builder.update_prompt_performance(FAKE_VERSION_UUID)

        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()


class TestCreateNewVersion:
    """Tests for creating new prompt versions."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_create_new_version(self, mock_factory):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_session = AsyncMock()
        mock_factory.return_value = _mock_session_ctx(mock_session)

        builder = DynamicPromptBuilder()
        version_id = await builder.create_new_version(
            template="Test template {topic}", label="v2-test"
        )

        assert version_id is not None
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


class TestMaybeCreateImprovedVersion:
    """Tests for auto-generated improved prompt versions."""

    @patch("app.services.prompt_builder_service.DynamicPromptBuilder.create_new_version")
    @pytest.mark.asyncio
    async def test_maybe_create_with_enough_patterns(self, mock_create):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        mock_create.return_value = "new-version-id"

        builder = DynamicPromptBuilder()
        result = await builder.maybe_create_improved_version([
            {"description": "Pattern 1"},
            {"description": "Pattern 2"},
            {"description": "Pattern 3"},
        ])

        assert result == "new-version-id"
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_create_skips_with_few_patterns(self):
        from app.services.prompt_builder_service import DynamicPromptBuilder

        builder = DynamicPromptBuilder()
        result = await builder.maybe_create_improved_version([
            {"description": "Only one pattern"},
        ])

        assert result is None
