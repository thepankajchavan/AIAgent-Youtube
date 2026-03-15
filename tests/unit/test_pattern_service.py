"""Unit tests for PatternService."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

DB_FACTORY = "app.core.database.async_session_factory"


def _mock_session_ctx(mock_session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestAnalyzePatterns:
    """Tests for pattern analysis."""

    @patch("app.services.pattern_service.PatternService._store_patterns")
    @patch("app.services.pattern_service.PatternService._analyze_with_llm")
    @patch("app.services.pattern_service.PatternService._get_bottom_performing_videos")
    @patch("app.services.analytics_service.AnalyticsService")
    @pytest.mark.asyncio
    async def test_analyze_patterns_success(
        self, mock_analytics_cls, mock_bottom, mock_llm, mock_store
    ):
        from app.services.pattern_service import PatternService

        mock_analytics = AsyncMock()
        mock_analytics.get_top_performing_videos.return_value = [
            {"topic": f"Top {i}", "views": 5000 - i * 100, "script_excerpt": "text"}
            for i in range(10)
        ]
        mock_analytics_cls.return_value = mock_analytics

        mock_bottom.return_value = [
            {"topic": f"Bottom {i}", "views": 50 + i * 10, "script_excerpt": "text"}
            for i in range(10)
        ]

        mock_llm.return_value = [
            {
                "pattern_type": "hook_style",
                "description": "Questions get more views",
                "confidence": 0.85,
                "recommendation": "Use questions",
            }
        ]
        mock_store.return_value = [
            {
                "id": "pattern-1",
                "pattern_type": "hook_style",
                "description": "Questions get more views",
                "confidence_score": 0.85,
            }
        ]

        service = PatternService()
        results = await service.analyze_patterns()

        assert len(results) == 1
        assert results[0]["pattern_type"] == "hook_style"

    @patch("app.services.pattern_service.PatternService._get_bottom_performing_videos")
    @patch("app.services.analytics_service.AnalyticsService")
    @pytest.mark.asyncio
    async def test_analyze_patterns_insufficient_data(
        self, mock_analytics_cls, mock_bottom
    ):
        from app.services.pattern_service import PatternService

        mock_analytics = AsyncMock()
        mock_analytics.get_top_performing_videos.return_value = [
            {"topic": "Top 1", "views": 5000}
        ]
        mock_analytics_cls.return_value = mock_analytics

        mock_bottom.return_value = [{"topic": "Bottom 1", "views": 50}]

        service = PatternService()
        results = await service.analyze_patterns()

        assert results == []


class TestShouldRunAnalysis:
    """Tests for analysis eligibility check."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_should_run_analysis_true(self, mock_factory):
        from app.services.pattern_service import PatternService

        mock_session = AsyncMock()

        # Total count: 15 videos
        total_result = MagicMock()
        total_result.scalar.return_value = 15

        # Last analysis: None (never analyzed)
        last_result = MagicMock()
        last_result.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [total_result, last_result]
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = PatternService()
        result = await service.should_run_analysis()

        assert result is True

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_should_run_analysis_false_not_enough_videos(self, mock_factory):
        from app.services.pattern_service import PatternService

        mock_session = AsyncMock()

        total_result = MagicMock()
        total_result.scalar.return_value = 5

        mock_session.execute.return_value = total_result
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = PatternService()
        result = await service.should_run_analysis()

        assert result is False

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_should_run_analysis_false_not_enough_new(self, mock_factory):
        from app.services.pattern_service import PatternService

        mock_session = AsyncMock()

        total_result = MagicMock()
        total_result.scalar.return_value = 15

        last_analysis = datetime.now(timezone.utc) - timedelta(days=1)
        last_result = MagicMock()
        last_result.scalar_one_or_none.return_value = last_analysis

        new_result = MagicMock()
        new_result.scalar.return_value = 2

        mock_session.execute.side_effect = [total_result, last_result, new_result]
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = PatternService()
        result = await service.should_run_analysis()

        assert result is False


class TestGetActivePatterns:
    """Tests for querying active patterns."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_get_active_patterns_filters_by_confidence(self, mock_factory):
        from app.services.pattern_service import PatternService

        mock_pattern = MagicMock()
        mock_pattern.id = "p-1"
        mock_pattern.pattern_type = "hook_style"
        mock_pattern.description = "Questions work best"
        mock_pattern.confidence_score = 0.85
        mock_pattern.sample_size = 40
        mock_pattern.pattern_data = json.dumps({"recommendation": "Use questions"})

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_pattern]
        mock_session.execute.return_value = mock_result

        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = PatternService()
        patterns = await service.get_active_patterns(min_confidence=0.6)

        assert len(patterns) == 1
        assert patterns[0]["confidence_score"] == 0.85

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_get_active_patterns_empty(self, mock_factory):
        from app.services.pattern_service import PatternService

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = PatternService()
        patterns = await service.get_active_patterns(min_confidence=0.9)

        assert patterns == []


class TestBuildAnalysisPrompt:
    """Tests for the LLM analysis prompt builder."""

    def test_build_analysis_prompt_includes_data(self):
        from app.services.pattern_service import PatternService

        service = PatternService()
        top = [{"topic": "AI Facts", "views": 5000, "retention": 65.0, "script_excerpt": "Did you know..."}]
        bottom = [{"topic": "Boring Facts", "views": 50, "retention": 10.0, "script_excerpt": "Here are some..."}]

        prompt = service._build_analysis_prompt(top, bottom)

        assert "TOP PERFORMING VIDEOS" in prompt
        assert "LOW PERFORMING VIDEOS" in prompt
        assert "AI Facts" in prompt
        assert "Boring Facts" in prompt
        assert "hook_style" in prompt
