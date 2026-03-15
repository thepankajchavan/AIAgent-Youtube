"""Unit tests for the AI Image Generation Service (DALL-E 3 / GPT-image-1)."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.image_gen_service import (
    _enhance_image_prompt,
    estimate_image_cost,
    generate_scene_image,
)


class TestEstimateImageCost:
    """Test image cost estimation."""

    def test_dalle3_standard_1024x1792(self):
        cost = estimate_image_cost("dall-e-3", "1024x1792", "standard")
        assert cost == 0.08

    def test_dalle3_hd_1024x1792(self):
        cost = estimate_image_cost("dall-e-3", "1024x1792", "hd")
        assert cost == 0.12

    def test_dalle3_standard_1024x1024(self):
        cost = estimate_image_cost("dall-e-3", "1024x1024", "standard")
        assert cost == 0.04

    def test_gpt_image_1_1024x1792(self):
        cost = estimate_image_cost("gpt-image-1", "1024x1792", "standard")
        assert cost == 0.08

    def test_unknown_model_uses_default(self):
        cost = estimate_image_cost("unknown-model", "1024x1792", "standard")
        # Falls back to dall-e-3 costs
        assert cost == 0.08


class TestEnhanceImagePrompt:
    """Test image prompt enhancement."""

    def test_adds_quality_tokens(self):
        prompt = "A map of India and Russia"
        enhanced = _enhance_image_prompt(prompt)
        assert "high detail" in enhanced
        assert "professional photography" in enhanced
        assert "dramatic lighting" in enhanced

    def test_preserves_existing_tokens(self):
        prompt = "A dramatic lighting scene with high detail"
        enhanced = _enhance_image_prompt(prompt)
        # Should not duplicate existing tokens
        assert enhanced.count("dramatic lighting") == 1
        assert enhanced.count("high detail") == 1

    def test_adds_portrait_framing_for_9_16(self):
        prompt = "An oil tanker"
        enhanced = _enhance_image_prompt(prompt, aspect_ratio="9:16")
        assert "vertical portrait" in enhanced

    def test_adds_landscape_framing_for_16_9(self):
        prompt = "An oil tanker"
        enhanced = _enhance_image_prompt(prompt, aspect_ratio="16:9")
        assert "landscape" in enhanced

    def test_truncates_long_prompts(self):
        prompt = "x" * 4000
        enhanced = _enhance_image_prompt(prompt)
        assert len(enhanced) <= 3900


class TestGenerateSceneImage:
    """Test AI image generation with mocked OpenAI client."""

    @pytest.mark.asyncio
    async def test_success_saves_image(self, mocker, tmp_path):
        """Test successful image generation via b64_json."""
        mock_settings = MagicMock()
        mock_settings.ai_images_dir = tmp_path
        mock_settings.openai_api_key = "test-key"
        mocker.patch("app.services.image_gen_service.settings", mock_settings)

        # Mock OpenAI response with b64_json
        fake_image_data = b"x" * 5000
        mock_image = MagicMock()
        mock_image.b64_json = base64.b64encode(fake_image_data).decode()

        mock_response = MagicMock()
        mock_response.data = [mock_image]

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        mocker.patch(
            "app.services.image_gen_service._get_client",
            return_value=mock_client,
        )

        result = await generate_scene_image(
            prompt="A map of India and Russia",
            size="1024x1792",
            model="dall-e-3",
        )

        assert result.exists()
        assert result.suffix == ".png"
        assert result.parent == tmp_path
        assert result.stat().st_size == 5000

    @pytest.mark.asyncio
    async def test_empty_b64_data_raises(self, mocker, tmp_path):
        """Test that empty b64_json data raises ValueError."""
        mock_settings = MagicMock()
        mock_settings.ai_images_dir = tmp_path
        mock_settings.openai_api_key = "test-key"
        mocker.patch("app.services.image_gen_service.settings", mock_settings)

        mock_image = MagicMock()
        mock_image.b64_json = None

        mock_response = MagicMock()
        mock_response.data = [mock_image]

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        mocker.patch(
            "app.services.image_gen_service._get_client",
            return_value=mock_client,
        )

        with pytest.raises(ValueError, match="empty image data"):
            await generate_scene_image(prompt="test")

    @pytest.mark.asyncio
    async def test_small_file_raises(self, mocker, tmp_path):
        """Test that image too small raises ValueError."""
        mock_settings = MagicMock()
        mock_settings.ai_images_dir = tmp_path
        mock_settings.openai_api_key = "test-key"
        mocker.patch("app.services.image_gen_service.settings", mock_settings)

        # Return tiny image data (< 1000 bytes)
        mock_image = MagicMock()
        mock_image.b64_json = base64.b64encode(b"tiny").decode()

        mock_response = MagicMock()
        mock_response.data = [mock_image]

        mock_client = AsyncMock()
        mock_client.images.generate = AsyncMock(return_value=mock_response)
        mocker.patch(
            "app.services.image_gen_service._get_client",
            return_value=mock_client,
        )

        with pytest.raises(ValueError, match="too small"):
            await generate_scene_image(prompt="test")
