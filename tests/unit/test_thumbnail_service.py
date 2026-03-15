"""Unit tests for thumbnail_service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SETTINGS_PATH = "app.services.thumbnail_service.get_settings"
IMAGE_GEN_PATH = "app.services.image_gen_service.generate_scene_image"


# ===========================================================================
# generate_thumbnail_prompt
# ===========================================================================


class TestGenerateThumbnailPrompt:
    """Tests for generate_thumbnail_prompt()."""

    def test_includes_topic_in_prompt(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Amazing Facts", topic="black holes", mood="uplifting"
        )

        assert "black holes" in prompt

    def test_includes_mood_style_keywords(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Energy!", topic="fitness", mood="energetic"
        )

        assert "vibrant neon colors" in prompt

    def test_calm_mood_uses_calm_style(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Relax", topic="meditation", mood="calm"
        )

        assert "soft pastel tones" in prompt

    def test_dramatic_mood_uses_dramatic_style(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Dark Times", topic="history", mood="dramatic"
        )

        assert "dark moody lighting" in prompt

    def test_mysterious_mood(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Secrets", topic="ancient ruins", mood="mysterious"
        )

        assert "deep blues and purples" in prompt

    def test_dark_mood(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Noir", topic="crime stories", mood="dark"
        )

        assert "noir-style" in prompt

    def test_happy_mood(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Joy", topic="puppies", mood="happy"
        )

        assert "bright saturated colors" in prompt

    def test_epic_mood(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Grand", topic="mountains", mood="epic"
        )

        assert "sweeping wide angle" in prompt

    def test_unknown_mood_defaults_to_uplifting(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Default", topic="general", mood="nonexistent_mood"
        )

        assert "warm golden light" in prompt

    def test_default_mood_is_uplifting(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(title="Test", topic="science")

        assert "warm golden light" in prompt

    def test_prompt_capped_at_3900_chars(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        # Very long topic to push prompt past 3900 chars
        long_topic = "A" * 5000
        prompt = generate_thumbnail_prompt(
            title="Long", topic=long_topic, mood="uplifting"
        )

        assert len(prompt) <= 3900

    def test_prompt_contains_no_text_instruction(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        prompt = generate_thumbnail_prompt(
            title="Test", topic="AI", mood="uplifting"
        )

        assert "no text or letters" in prompt

    def test_different_moods_produce_different_prompts(self):
        from app.services.thumbnail_service import generate_thumbnail_prompt

        energetic = generate_thumbnail_prompt("T", "topic", "energetic")
        calm = generate_thumbnail_prompt("T", "topic", "calm")
        dark = generate_thumbnail_prompt("T", "topic", "dark")

        # All three should be distinct
        assert energetic != calm
        assert calm != dark
        assert energetic != dark


# ===========================================================================
# generate_ai_thumbnail
# ===========================================================================


class TestGenerateAiThumbnail:
    """Tests for generate_ai_thumbnail()."""

    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_calls_generate_scene_image_with_correct_size(
        self, mock_settings, mock_gen
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "standard"
        settings.ai_thumbnail_text_overlay = False
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")

        result = await generate_ai_thumbnail(
            title="Test", topic="AI", mood="uplifting", project_id="proj-1"
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["size"] == "1792x1024"
        assert call_kwargs["model"] == "dall-e-3"
        assert call_kwargs["quality"] == "standard"
        assert result == Path("/tmp/thumb.png")

    @patch("app.services.thumbnail_service.add_text_overlay")
    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_calls_text_overlay_when_enabled(
        self, mock_settings, mock_gen, mock_overlay
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "standard"
        settings.ai_thumbnail_text_overlay = True
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")
        mock_overlay.return_value = Path("/tmp/thumb_overlay.png")

        result = await generate_ai_thumbnail(
            title="My Video Title", topic="AI", project_id="proj-2"
        )

        mock_overlay.assert_called_once_with(Path("/tmp/thumb.png"), "My Video Title")
        assert result == Path("/tmp/thumb_overlay.png")

    @patch("app.services.thumbnail_service.add_text_overlay")
    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_skips_text_overlay_when_disabled(
        self, mock_settings, mock_gen, mock_overlay
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "standard"
        settings.ai_thumbnail_text_overlay = False
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")

        result = await generate_ai_thumbnail(
            title="My Video Title", topic="AI", project_id="proj-3"
        )

        mock_overlay.assert_not_called()
        assert result == Path("/tmp/thumb.png")

    @patch("app.services.thumbnail_service.add_text_overlay")
    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_skips_text_overlay_when_title_empty(
        self, mock_settings, mock_gen, mock_overlay
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "standard"
        settings.ai_thumbnail_text_overlay = True
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")

        result = await generate_ai_thumbnail(
            title="", topic="AI", project_id="proj-4"
        )

        # Empty title is falsy, so overlay is skipped
        mock_overlay.assert_not_called()
        assert result == Path("/tmp/thumb.png")

    @patch("app.services.thumbnail_service.add_text_overlay")
    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_text_overlay_failure_returns_plain_thumbnail(
        self, mock_settings, mock_gen, mock_overlay
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "standard"
        settings.ai_thumbnail_text_overlay = True
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")
        mock_overlay.side_effect = OSError("Font not found")

        result = await generate_ai_thumbnail(
            title="Fallback Test", topic="AI", project_id="proj-5"
        )

        # Should fall back to the original thumbnail
        assert result == Path("/tmp/thumb.png")

    @patch(IMAGE_GEN_PATH, new_callable=AsyncMock)
    @patch(SETTINGS_PATH)
    @pytest.mark.asyncio
    async def test_passes_prompt_to_generate_scene_image(
        self, mock_settings, mock_gen
    ):
        from app.services.thumbnail_service import generate_ai_thumbnail

        settings = MagicMock()
        settings.ai_images_model = "dall-e-3"
        settings.ai_images_quality = "hd"
        settings.ai_thumbnail_text_overlay = False
        mock_settings.return_value = settings

        mock_gen.return_value = Path("/tmp/thumb.png")

        await generate_ai_thumbnail(
            title="Black Holes", topic="astrophysics", mood="epic"
        )

        call_kwargs = mock_gen.call_args.kwargs
        # The prompt should contain the topic
        assert "astrophysics" in call_kwargs["prompt"]


# ===========================================================================
# add_text_overlay
# ===========================================================================


class TestAddTextOverlay:
    """Tests for add_text_overlay()."""

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_creates_output_with_overlay_suffix(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        input_path = Path("/tmp/thumb.png")
        result = add_text_overlay(input_path, "Test Title")

        expected = Path("/tmp/thumb_overlay.png")
        assert result == expected
        mock_img.save.assert_called_once_with(expected, quality=95)

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_text_is_uppercased(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        add_text_overlay(Path("/tmp/thumb.png"), "lowercase title")

        # The second draw.text call (main text) should use uppercased text
        draw_calls = mock_draw.text.call_args_list
        assert len(draw_calls) == 2  # shadow + main
        # Main text (second call)
        main_text_arg = draw_calls[1][0][1]
        assert main_text_arg == "LOWERCASE TITLE"

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_title_truncated_at_50_chars(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        long_title = "A" * 100
        add_text_overlay(Path("/tmp/thumb.png"), long_title)

        # Check the main text call uses truncated + uppercased text
        main_text = mock_draw.text.call_args_list[1][0][1]
        assert len(main_text) <= 50

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_draws_shadow_and_main_text(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        add_text_overlay(Path("/tmp/thumb.png"), "Test")

        # Two draw.text calls: shadow (black) + main (white)
        assert mock_draw.text.call_count == 2
        shadow_fill = mock_draw.text.call_args_list[0][1]["fill"]
        main_fill = mock_draw.text.call_args_list[1][1]["fill"]
        assert shadow_fill == (0, 0, 0, 200)
        assert main_fill == (255, 255, 255, 255)

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_font_fallback_to_default(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        # Both truetype calls fail, should fall back to load_default
        mock_truetype.side_effect = OSError("Font not found")
        mock_default_font = MagicMock()
        mock_load_default.return_value = mock_default_font

        add_text_overlay(Path("/tmp/thumb.png"), "Fallback Font")

        mock_load_default.assert_called_once()

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_font_size_scales_with_image_width(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 2000
        mock_img.height = 1200
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        add_text_overlay(Path("/tmp/thumb.png"), "Scale Test")

        # font_size = max(40, 2000 // 20) = max(40, 100) = 100
        call_args = mock_truetype.call_args
        assert call_args[0][1] == 100  # font size

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_font_size_minimum_is_40(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 400  # 400 // 20 = 20, but min is 40
        mock_img.height = 300
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 200, 30)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        add_text_overlay(Path("/tmp/thumb.png"), "Small Image")

        call_args = mock_truetype.call_args
        assert call_args[0][1] == 40  # min font size

    @patch("PIL.ImageFont.load_default")
    @patch("PIL.ImageFont.truetype")
    @patch("PIL.ImageDraw.Draw")
    @patch("PIL.Image.open")
    def test_output_path_preserves_extension(
        self, mock_open, mock_draw_cls, mock_truetype, mock_load_default
    ):
        from app.services.thumbnail_service import add_text_overlay

        mock_img = MagicMock()
        mock_img.width = 1792
        mock_img.height = 1024
        mock_open.return_value = mock_img

        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 400, 50)
        mock_draw_cls.return_value = mock_draw

        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        result = add_text_overlay(Path("/tmp/image.jpg"), "Title")

        assert result.suffix == ".jpg"
        assert result.stem == "image_overlay"
