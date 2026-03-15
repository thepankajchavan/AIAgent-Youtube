"""Unit tests for Phase 1: Visual hints in script generation.

Tests:
  - _ensure_scenes() visual_hint fallback logic (llm_service.py)
  - split_script_to_scenes() visual_hints injection (ai_video_service.py)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── _ensure_scenes tests ─────────────────────────────────────────


class TestEnsureScenesVisualHints:
    """Test visual_hint handling inside _ensure_scenes()."""

    def test_scenes_with_visual_hint_preserved(self):
        """Scenes that already have a visual_hint should keep it unchanged."""
        from app.services.llm_service import _ensure_scenes

        result = {
            "title": "Test",
            "script": "Line one.\n\nLine two.\n\nLine three.",
            "tags": ["tag1"],
            "scenes": [
                {
                    "narration": "Line one.",
                    "search_keywords": ["kw1"],
                    "visual_hint": "Wide aerial shot, golden hour, warm tones",
                },
                {
                    "narration": "Line two.",
                    "search_keywords": ["kw2"],
                    "visual_hint": "Close-up of a clock, cold blue light",
                },
            ],
        }

        _ensure_scenes(result)

        assert result["scenes"][0]["visual_hint"] == "Wide aerial shot, golden hour, warm tones"
        assert result["scenes"][1]["visual_hint"] == "Close-up of a clock, cold blue light"

    def test_scenes_without_visual_hint_get_narration_fallback(self):
        """Scenes missing visual_hint should fall back to the narration text."""
        from app.services.llm_service import _ensure_scenes

        result = {
            "title": "Test",
            "script": "Hook text.\n\nBuild text.",
            "tags": ["tag1"],
            "scenes": [
                {
                    "narration": "Hook text about the ocean.",
                    "search_keywords": ["ocean"],
                    # visual_hint NOT provided
                },
                {
                    "narration": "Build text about the sky.",
                    "search_keywords": ["sky"],
                    # visual_hint NOT provided
                },
            ],
        }

        _ensure_scenes(result)

        # visual_hint should fall back to narration
        assert result["scenes"][0]["visual_hint"] == "Hook text about the ocean."
        assert result["scenes"][1]["visual_hint"] == "Build text about the sky."

    def test_empty_visual_hint_gets_narration_fallback(self):
        """Scenes with empty string visual_hint should fall back to narration."""
        from app.services.llm_service import _ensure_scenes

        result = {
            "title": "Test",
            "script": "Hook line.\n\nBuild line.",
            "tags": ["tag1"],
            "scenes": [
                {
                    "narration": "The hook narration.",
                    "search_keywords": ["hook"],
                    "visual_hint": "",  # empty string
                },
                {
                    "narration": "The build narration.",
                    "search_keywords": ["build"],
                    "visual_hint": "",
                },
            ],
        }

        _ensure_scenes(result)

        # Empty visual_hint triggers fallback to narration
        assert result["scenes"][0]["visual_hint"] == "The hook narration."
        assert result["scenes"][1]["visual_hint"] == "The build narration."

    def test_mixed_scenes_some_with_some_without_hints(self):
        """Mix of scenes with and without visual_hint."""
        from app.services.llm_service import _ensure_scenes

        result = {
            "title": "Test",
            "script": "A.\n\nB.\n\nC.",
            "tags": ["t"],
            "scenes": [
                {
                    "narration": "Scene one narration.",
                    "search_keywords": ["kw1"],
                    "visual_hint": "Cinematic drone shot, misty mountains",
                },
                {
                    "narration": "Scene two narration.",
                    "search_keywords": ["kw2"],
                    # No visual_hint
                },
                {
                    "narration": "Scene three narration.",
                    "search_keywords": ["kw3"],
                    "visual_hint": "",
                },
            ],
        }

        _ensure_scenes(result)

        assert result["scenes"][0]["visual_hint"] == "Cinematic drone shot, misty mountains"
        assert result["scenes"][1]["visual_hint"] == "Scene two narration."
        assert result["scenes"][2]["visual_hint"] == "Scene three narration."

    def test_scenes_without_narration_or_hint(self):
        """Scene with neither narration nor visual_hint gets empty string."""
        from app.services.llm_service import _ensure_scenes

        result = {
            "title": "Test",
            "script": "A.\n\nB.",
            "tags": ["t"],
            "scenes": [
                {
                    "search_keywords": ["kw1"],
                    # No narration, no visual_hint
                },
                {
                    "narration": "Some narration.",
                    "search_keywords": ["kw2"],
                    "visual_hint": "A good hint",
                },
            ],
        }

        _ensure_scenes(result)

        # Scene without narration: narration defaults to "", visual_hint -> ""
        assert result["scenes"][0]["narration"] == ""
        assert result["scenes"][0]["visual_hint"] == ""


# ── split_script_to_scenes tests ────────────────────────────────


class TestSplitScriptToScenesVisualHints:
    """Test visual_hints injection in split_script_to_scenes()."""

    @pytest.mark.asyncio
    async def test_visual_hints_injected_into_user_content(self):
        """When visual_hints are provided, they should appear in the LLM user content."""
        from app.services.ai_video_service import split_script_to_scenes

        mock_scenes_response = {
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Hook text.",
                    "visual_description": "A wide shot",
                    "visual_type": "stock_footage",
                    "stock_query": "ocean waves",
                    "ai_prompt": "cinematic ocean waves, golden hour",
                    "duration_seconds": 5.0,
                },
                {
                    "scene_number": 2,
                    "narration": "Build text.",
                    "visual_description": "A close-up",
                    "visual_type": "stock_footage",
                    "stock_query": "sunset sky",
                    "ai_prompt": "dramatic sunset, warm amber tones",
                    "duration_seconds": 5.0,
                },
            ]
        }

        captured_user_content = None

        async def mock_call_openai_for_scenes(system_prompt, user_content):
            nonlocal captured_user_content
            captured_user_content = user_content
            return mock_scenes_response

        with (
            patch(
                "app.services.ai_video_service._call_openai_for_scenes",
                side_effect=mock_call_openai_for_scenes,
            ),
            patch("app.services.ai_video_service.settings") as mock_settings,
        ):
            mock_settings.openai_model = "gpt-4"
            mock_settings.ai_video_primary_provider = "runway"

            hints = [
                "Wide aerial shot, overcast sky, muted blue-grey",
                "Close-up detail, warm amber light, shallow depth of field",
            ]

            await split_script_to_scenes(
                script="Hook text.\n\nBuild text.",
                video_format="short",
                provider="openai",
                visual_strategy="stock_only",
                visual_hints=hints,
            )

        # Verify hints were injected
        assert captured_user_content is not None
        assert "VISUAL DIRECTION HINTS" in captured_user_content
        assert "Beat 1: Wide aerial shot, overcast sky, muted blue-grey" in captured_user_content
        assert "Beat 2: Close-up detail, warm amber light" in captured_user_content

    @pytest.mark.asyncio
    async def test_no_visual_hints_backward_compat(self):
        """When visual_hints is None, no hints block should be in user content."""
        from app.services.ai_video_service import split_script_to_scenes

        mock_scenes_response = {
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Hook text.",
                    "visual_description": "A wide shot",
                    "visual_type": "stock_footage",
                    "stock_query": "ocean waves",
                    "ai_prompt": "cinematic ocean waves",
                    "duration_seconds": 6.0,
                },
                {
                    "scene_number": 2,
                    "narration": "Build text.",
                    "visual_description": "A close-up",
                    "visual_type": "stock_footage",
                    "stock_query": "sunset sky",
                    "ai_prompt": "dramatic sunset",
                    "duration_seconds": 6.0,
                },
            ]
        }

        captured_user_content = None

        async def mock_call_openai_for_scenes(system_prompt, user_content):
            nonlocal captured_user_content
            captured_user_content = user_content
            return mock_scenes_response

        with (
            patch(
                "app.services.ai_video_service._call_openai_for_scenes",
                side_effect=mock_call_openai_for_scenes,
            ),
            patch("app.services.ai_video_service.settings") as mock_settings,
        ):
            mock_settings.openai_model = "gpt-4"
            mock_settings.ai_video_primary_provider = "runway"

            await split_script_to_scenes(
                script="Hook text.\n\nBuild text.",
                video_format="short",
                provider="openai",
                visual_strategy="stock_only",
                visual_hints=None,
            )

        assert captured_user_content is not None
        assert "VISUAL DIRECTION HINTS" not in captured_user_content

    @pytest.mark.asyncio
    async def test_empty_visual_hints_list_no_injection(self):
        """When visual_hints is an empty list, no hints block is injected."""
        from app.services.ai_video_service import split_script_to_scenes

        mock_scenes_response = {
            "scenes": [
                {
                    "scene_number": 1,
                    "narration": "Text.",
                    "visual_description": "Shot",
                    "visual_type": "stock_footage",
                    "stock_query": "test",
                    "ai_prompt": "test prompt",
                    "duration_seconds": 10.0,
                },
                {
                    "scene_number": 2,
                    "narration": "More text.",
                    "visual_description": "More shot",
                    "visual_type": "stock_footage",
                    "stock_query": "test2",
                    "ai_prompt": "test2 prompt",
                    "duration_seconds": 10.0,
                },
            ]
        }

        captured_user_content = None

        async def mock_call_openai_for_scenes(system_prompt, user_content):
            nonlocal captured_user_content
            captured_user_content = user_content
            return mock_scenes_response

        with (
            patch(
                "app.services.ai_video_service._call_openai_for_scenes",
                side_effect=mock_call_openai_for_scenes,
            ),
            patch("app.services.ai_video_service.settings") as mock_settings,
        ):
            mock_settings.openai_model = "gpt-4"
            mock_settings.ai_video_primary_provider = "runway"

            await split_script_to_scenes(
                script="Text.\n\nMore text.",
                video_format="short",
                provider="openai",
                visual_strategy="stock_only",
                visual_hints=[],
            )

        assert captured_user_content is not None
        assert "VISUAL DIRECTION HINTS" not in captured_user_content
