"""Unit tests for Phase 3: Prompt rewriting for AI video providers.

Tests:
  - _rewrite_prompt_for_provider() LLM rewriting and fallback
  - _PROVIDER_REWRITE_INSTRUCTIONS completeness
  - _generate_with_provider() integration with prompt rewriting flag
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_video_service import (
    Scene,
    _PROVIDER_REWRITE_INSTRUCTIONS,
    _rewrite_prompt_for_provider,
)


def _make_scene(
    ai_prompt: str = "A wide establishing shot of a desert",
    duration: float = 5.0,
    scene_number: int = 1,
) -> Scene:
    """Helper to create a Scene with sensible defaults."""
    return Scene(
        scene_number=scene_number,
        narration="Narration text.",
        visual_description="Visual description.",
        visual_type="ai_generated",
        stock_query="desert landscape",
        ai_prompt=ai_prompt,
        duration_seconds=duration,
    )


# ── _rewrite_prompt_for_provider tests ────────────────────────────


class TestRewritePromptForProvider:
    """Test LLM-based prompt rewriting for different providers."""

    @pytest.mark.asyncio
    async def test_successful_rewrite_with_mocked_openai(self):
        """Successful LLM rewrite returns the rewritten prompt."""
        mock_openai = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            "Cinematic wide establishing shot sweeping across endless golden "
            "sand dunes at golden hour, smooth dolly movement, warm amber tones, "
            "volumetric sun rays, 8K detail, shallow depth of field"
        )
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="A wide shot of a desert at sunset",
                provider="runway",
                aspect_ratio="9:16",
            )

        assert "golden" in result.lower() or "cinematic" in result.lower()
        assert len(result) >= 20
        mock_openai.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_token_append_on_llm_failure(self):
        """When LLM call fails, should fall back to token-append enhancement."""
        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="A desert scene",
                provider="runway",
                aspect_ratio="9:16",
            )

        # Fallback should use _enhance_runway_prompt which adds quality tokens
        assert "cinematic" in result.lower() or "8K" in result

    @pytest.mark.asyncio
    async def test_falls_back_on_too_short_rewrite(self):
        """If LLM returns a too-short prompt (< 20 chars), fallback is used."""
        mock_openai = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Short."  # < 20 chars
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="A desert at sunset with warm tones",
                provider="runway",
                aspect_ratio="9:16",
            )

        # Should fall back to token-append
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_unknown_provider_falls_back_to_runway_enhancement(self):
        """Unknown provider should fall back to runway enhancement (token-append)."""
        result = await _rewrite_prompt_for_provider(
            prompt="A mountain landscape",
            provider="unknown_provider",
            aspect_ratio="9:16",
        )

        # Should use _enhance_runway_prompt as fallback
        assert "cinematic" in result.lower() or "8K" in result

    @pytest.mark.asyncio
    async def test_style_anchor_included_in_system_prompt(self):
        """Style anchor should be included in the system prompt when provided."""
        mock_openai = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            "A cinematic crane shot rising over golden sand dunes "
            "with warm amber tones and volumetric lighting"
        )
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            await _rewrite_prompt_for_provider(
                prompt="Desert landscape",
                provider="runway",
                aspect_ratio="9:16",
                style_anchor="VISUAL CONSISTENCY: maintain golden hour, warm tones.",
            )

        # Verify the system prompt contains the style anchor
        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        assert "VISUAL CONSISTENCY" in system_msg["content"]
        assert "golden hour" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_stability_provider_rewrite(self):
        """Stability provider should use stability-specific instructions."""
        mock_openai = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            "A dramatically lit still photograph of a desert oasis "
            "with crystal clear reflection, strong composition"
        )
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="Desert oasis",
                provider="stability",
                aspect_ratio="9:16",
            )

        # Should succeed with stability prompt
        assert len(result) >= 20

        # Verify stability-specific instruction was sent
        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        assert "Stability" in system_msg["content"]

    @pytest.mark.asyncio
    async def test_stability_fallback_uses_stability_enhancer(self):
        """Stability provider fallback should use _enhance_stability_prompt."""
        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="A forest scene",
                provider="stability",
                aspect_ratio="9:16",
            )

        # Stability enhancer adds specific tokens
        assert "natural lighting" in result.lower() or "high detail" in result.lower()

    @pytest.mark.asyncio
    async def test_kling_fallback_uses_kling_enhancer(self):
        """Kling provider fallback should use _enhance_kling_prompt."""
        mock_openai = AsyncMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            result = await _rewrite_prompt_for_provider(
                prompt="An explosion scene",
                provider="kling",
                aspect_ratio="9:16",
            )

        # Kling enhancer adds dynamic composition
        assert "dynamic" in result.lower()

    @pytest.mark.asyncio
    async def test_landscape_framing_in_system_prompt(self):
        """16:9 aspect ratio should use landscape framing in system prompt."""
        mock_openai = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            "A sweeping horizontal cinematic shot of mountains at dawn"
        )
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_completion)

        with patch(
            "app.services.llm_service._get_openai",
            return_value=mock_openai,
        ):
            await _rewrite_prompt_for_provider(
                prompt="Mountains at dawn",
                provider="runway",
                aspect_ratio="16:9",
            )

        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        system_msg = next(m for m in messages if m["role"] == "system")
        assert "horizontal" in system_msg["content"] or "16:9" in system_msg["content"]


# ── _PROVIDER_REWRITE_INSTRUCTIONS tests ─────────────────────────


class TestProviderRewriteInstructions:
    """Test that provider-specific rewrite instructions exist."""

    def test_has_entry_for_runway(self):
        assert "runway" in _PROVIDER_REWRITE_INSTRUCTIONS

    def test_has_entry_for_stability(self):
        assert "stability" in _PROVIDER_REWRITE_INSTRUCTIONS

    def test_has_entry_for_kling(self):
        assert "kling" in _PROVIDER_REWRITE_INSTRUCTIONS

    def test_runway_instruction_mentions_camera_motion(self):
        assert "camera" in _PROVIDER_REWRITE_INSTRUCTIONS["runway"].lower()

    def test_stability_instruction_mentions_still_image(self):
        assert "still" in _PROVIDER_REWRITE_INSTRUCTIONS["stability"].lower()

    def test_kling_instruction_mentions_dynamic(self):
        assert "dynamic" in _PROVIDER_REWRITE_INSTRUCTIONS["kling"].lower()

    def test_all_instructions_are_non_empty(self):
        for provider, instruction in _PROVIDER_REWRITE_INSTRUCTIONS.items():
            assert len(instruction) > 50, f"Instruction for {provider} is too short"


# ── _generate_with_provider integration tests ────────────────────


class TestGenerateWithProviderPromptRewriting:
    """Test that _generate_with_provider respects prompt_rewriting_enabled."""

    @pytest.mark.asyncio
    async def test_calls_rewriter_when_enabled(self):
        """When prompt_rewriting_enabled=True, prompt rewriting should be called."""
        from app.services.ai_video_service import _generate_with_provider

        scene = _make_scene(ai_prompt="A desert scene", duration=5.0)

        mock_settings = MagicMock()
        mock_settings.prompt_rewriting_enabled = True

        mock_rewriter = AsyncMock(return_value="Rewritten desert prompt with cinematic details")
        mock_runway = AsyncMock(return_value=Path("/fake/output.mp4"))

        with (
            patch("app.services.ai_video_service.settings", mock_settings),
            patch("app.services.ai_video_service._rewrite_prompt_for_provider", mock_rewriter),
            patch("app.services.ai_video_service.generate_ai_video_runway", mock_runway),
        ):
            await _generate_with_provider("runway", scene, "9:16", style_anchor="")

        mock_rewriter.assert_called_once()
        # The rewritten prompt should have been used for the scene
        assert scene.ai_prompt == "Rewritten desert prompt with cinematic details"

    @pytest.mark.asyncio
    async def test_skips_rewriter_when_disabled(self):
        """When prompt_rewriting_enabled=False, prompt rewriting should be skipped."""
        from app.services.ai_video_service import _generate_with_provider

        scene = _make_scene(ai_prompt="A desert scene", duration=5.0)
        original_prompt = scene.ai_prompt

        mock_settings = MagicMock()
        mock_settings.prompt_rewriting_enabled = False

        mock_rewriter = AsyncMock()
        mock_runway = AsyncMock(return_value=Path("/fake/output.mp4"))

        with (
            patch("app.services.ai_video_service.settings", mock_settings),
            patch("app.services.ai_video_service._rewrite_prompt_for_provider", mock_rewriter),
            patch("app.services.ai_video_service.generate_ai_video_runway", mock_runway),
        ):
            await _generate_with_provider("runway", scene, "9:16")

        mock_rewriter.assert_not_called()
        assert scene.ai_prompt == original_prompt

    @pytest.mark.asyncio
    async def test_style_anchor_passed_to_rewriter(self):
        """Style anchor should be forwarded to the rewriter."""
        from app.services.ai_video_service import _generate_with_provider

        scene = _make_scene(ai_prompt="Forest scene", duration=5.0)
        anchor = "VISUAL CONSISTENCY: maintain golden hour, warm tones."

        mock_settings = MagicMock()
        mock_settings.prompt_rewriting_enabled = True

        mock_rewriter = AsyncMock(return_value="Rewritten forest prompt")
        mock_runway = AsyncMock(return_value=Path("/fake/output.mp4"))

        with (
            patch("app.services.ai_video_service.settings", mock_settings),
            patch("app.services.ai_video_service._rewrite_prompt_for_provider", mock_rewriter),
            patch("app.services.ai_video_service.generate_ai_video_runway", mock_runway),
        ):
            await _generate_with_provider("runway", scene, "9:16", style_anchor=anchor)

        # Verify anchor was passed
        call_kwargs = mock_rewriter.call_args
        assert call_kwargs[0][3] == anchor  # 4th positional arg is style_anchor

    @pytest.mark.asyncio
    async def test_default_prompt_rewriting_disabled(self):
        """By default prompt_rewriting_enabled should be False (opt-in)."""
        from app.services.ai_video_service import _generate_with_provider

        scene = _make_scene(ai_prompt="A desert", duration=5.0)

        mock_settings = MagicMock(spec=[])  # No attributes defined

        mock_rewriter = AsyncMock()
        mock_runway = AsyncMock(return_value=Path("/fake/output.mp4"))

        with (
            patch("app.services.ai_video_service.settings", mock_settings),
            patch("app.services.ai_video_service._rewrite_prompt_for_provider", mock_rewriter),
            patch("app.services.ai_video_service.generate_ai_video_runway", mock_runway),
        ):
            await _generate_with_provider("runway", scene, "9:16")

        # getattr(settings, "prompt_rewriting_enabled", False) should return False
        mock_rewriter.assert_not_called()

    @pytest.mark.asyncio
    async def test_duration_clamped_for_runway(self):
        """Scene duration > 10s should be clamped to 10 for Runway."""
        from app.services.ai_video_service import _generate_with_provider

        scene = _make_scene(ai_prompt="A long scene", duration=15.0)

        mock_settings = MagicMock()
        mock_settings.prompt_rewriting_enabled = False

        mock_runway = AsyncMock(return_value=Path("/fake/output.mp4"))

        with (
            patch("app.services.ai_video_service.settings", mock_settings),
            patch("app.services.ai_video_service.generate_ai_video_runway", mock_runway),
        ):
            await _generate_with_provider("runway", scene, "9:16")

        # Runway should be called with duration=10 (clamped)
        call_args = mock_runway.call_args
        assert call_args[0][1] == 10  # second positional arg is duration
