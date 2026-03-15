"""Unit tests for Scene Director Service — creative presets and direction logic."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.ai_video_service import Scene
from app.services.scene_director_service import (
    CREATIVE_PRESETS,
    CreativeDirections,
    _dominant_mood,
    compute_creative_directions,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_scene(num, mood=None, transition_type=None, caption_emphasis=None):
    return Scene(
        scene_number=num,
        narration=f"Scene {num}",
        visual_description="desc",
        visual_type="stock_footage",
        stock_query="nature",
        ai_prompt="prompt",
        duration_seconds=5.0,
        mood=mood,
        transition_type=transition_type,
        caption_emphasis=caption_emphasis,
    )


def _mock_settings():
    s = MagicMock()
    s.bgm_default_mood = "uplifting"
    s.bgm_volume_db = -18.0
    return s


# ── TestDominantMood ─────────────────────────────────────────────


class TestDominantMood:
    """Tests for the _dominant_mood helper."""

    @patch("app.services.scene_director_service.get_settings")
    def test_multiple_moods_returns_most_common(self, mock_gs):
        """When scenes have mixed moods, the most frequent one wins."""
        mock_gs.return_value = _mock_settings()
        scenes = [
            _make_scene(1, mood="tense"),
            _make_scene(2, mood="uplifting"),
            _make_scene(3, mood="tense"),
            _make_scene(4, mood="calm"),
            _make_scene(5, mood="tense"),
        ]
        result = _dominant_mood(scenes)
        assert result == "tense"

    @patch("app.services.scene_director_service.get_settings")
    def test_all_same_mood(self, mock_gs):
        """When every scene shares the same mood, that mood is returned."""
        mock_gs.return_value = _mock_settings()
        scenes = [
            _make_scene(1, mood="calm"),
            _make_scene(2, mood="calm"),
            _make_scene(3, mood="calm"),
        ]
        result = _dominant_mood(scenes)
        assert result == "calm"

    @patch("app.services.scene_director_service.get_settings")
    def test_no_moods_returns_settings_default(self, mock_gs):
        """Scenes with mood=None fall back to bgm_default_mood from settings."""
        mock_gs.return_value = _mock_settings()
        scenes = [
            _make_scene(1),
            _make_scene(2),
        ]
        result = _dominant_mood(scenes)
        assert result == "uplifting"
        mock_gs.assert_called_once()

    @patch("app.services.scene_director_service.get_settings")
    def test_empty_scenes_returns_default(self, mock_gs):
        """An empty scene list falls back to settings default mood."""
        mock_gs.return_value = _mock_settings()
        result = _dominant_mood([])
        assert result == "uplifting"
        mock_gs.assert_called_once()


# ── TestComputeCreativeDirections ────────────────────────────────


class TestComputeCreativeDirections:
    """Tests for compute_creative_directions with presets and auto mode."""

    @patch("app.services.scene_director_service.get_settings")
    def test_preset_minimal(self, mock_gs):
        """preset='minimal' applies classic captions, fade transitions, -22 dB."""
        mock_gs.return_value = _mock_settings()
        scenes = [_make_scene(1, mood="calm")]

        dirs = compute_creative_directions(scenes, preset="minimal")

        assert dirs.caption_style == "classic"
        assert dirs.transition_style == "fade"
        assert dirs.bgm_volume_db == -22.0
        assert dirs.dominant_mood == "calm"

    @patch("app.services.scene_director_service.get_settings")
    def test_preset_cinematic(self, mock_gs):
        """preset='cinematic' applies karaoke captions, auto transitions, -16 dB."""
        mock_gs.return_value = _mock_settings()
        scenes = [_make_scene(1, mood="dramatic")]

        dirs = compute_creative_directions(scenes, preset="cinematic")

        assert dirs.caption_style == "karaoke"
        assert dirs.transition_style == "auto"
        assert dirs.bgm_volume_db == -16.0
        assert dirs.dominant_mood == "dramatic"

    @patch("app.services.scene_director_service.get_settings")
    def test_preset_energetic(self, mock_gs):
        """preset='energetic' applies bounce captions, auto transitions, -15 dB."""
        mock_gs.return_value = _mock_settings()
        scenes = [_make_scene(1, mood="hype")]

        dirs = compute_creative_directions(scenes, preset="energetic")

        assert dirs.caption_style == "bounce"
        assert dirs.transition_style == "auto"
        assert dirs.bgm_volume_db == -15.0
        assert dirs.dominant_mood == "hype"

    @patch("app.services.scene_director_service.get_settings")
    def test_auto_extracts_transitions_from_scenes(self, mock_gs):
        """Auto mode extracts per-scene transition_type into directions.transitions."""
        mock_gs.return_value = _mock_settings()
        scenes = [
            _make_scene(1, transition_type="fade"),
            _make_scene(2, transition_type="wipeleft"),
            _make_scene(3, transition_type="dissolve"),
        ]

        dirs = compute_creative_directions(scenes, preset="auto")

        # First scene transition is skipped (no inbound); remaining are kept
        assert dirs.transitions == ["wipeleft", "dissolve"]
        assert dirs.transition_style == "scene_directed"

    @patch("app.services.scene_director_service.get_settings")
    def test_auto_strong_emphasis_sets_karaoke(self, mock_gs):
        """Auto mode with any scene having caption_emphasis='strong' sets karaoke."""
        mock_gs.return_value = _mock_settings()
        scenes = [
            _make_scene(1, caption_emphasis="normal"),
            _make_scene(2, caption_emphasis="strong"),
            _make_scene(3, caption_emphasis="subtle"),
        ]

        dirs = compute_creative_directions(scenes, preset="auto")

        assert dirs.caption_style == "karaoke"

    @patch("app.services.scene_director_service.get_settings")
    def test_auto_no_scene_data_returns_defaults(self, mock_gs):
        """Auto mode with plain scenes returns all defaults."""
        mock_gs.return_value = _mock_settings()
        scenes = [_make_scene(1), _make_scene(2)]

        dirs = compute_creative_directions(scenes, preset="auto")

        assert dirs.caption_style == "classic"
        assert dirs.transition_style == "auto"
        assert dirs.bgm_volume_db == -18.0
        assert dirs.dominant_mood == "uplifting"
        assert dirs.transitions == []

    @patch("app.services.scene_director_service.get_settings")
    def test_unknown_preset_treated_as_auto(self, mock_gs):
        """An unrecognized preset name falls through to auto logic."""
        mock_gs.return_value = _mock_settings()
        scenes = [_make_scene(1, mood="chill")]

        dirs = compute_creative_directions(scenes, preset="nonexistent_preset")

        # Should behave like auto — mood extracted, defaults used
        assert dirs.dominant_mood == "chill"
        assert dirs.caption_style == "classic"
        assert dirs.bgm_volume_db == -18.0


# ── TestCreativePresets ──────────────────────────────────────────


class TestCreativePresets:
    """Tests for the CREATIVE_PRESETS dictionary structure."""

    def test_all_presets_produce_valid_directions(self):
        """Each preset name creates a valid CreativeDirections object."""
        for name, preset_dict in CREATIVE_PRESETS.items():
            dirs = CreativeDirections(
                caption_style=str(preset_dict["caption_style"]),
                transition_style=str(preset_dict["transition_style"]),
                bgm_volume_db=float(preset_dict["bgm_volume_db"]),
            )
            assert isinstance(dirs.caption_style, str), f"preset {name}"
            assert isinstance(dirs.transition_style, str), f"preset {name}"
            assert isinstance(dirs.bgm_volume_db, float), f"preset {name}"

    @pytest.mark.parametrize("preset_name", list(CREATIVE_PRESETS.keys()))
    def test_preset_has_required_keys(self, preset_name):
        """Every preset must have caption_style, transition_style, bgm_volume_db."""
        preset = CREATIVE_PRESETS[preset_name]
        assert "caption_style" in preset
        assert "transition_style" in preset
        assert "bgm_volume_db" in preset


# ── TestSceneBackwardCompat ──────────────────────────────────────


class TestSceneBackwardCompat:
    """Backward compatibility: scenes without creative direction fields."""

    def test_scene_defaults_none_for_creative_fields(self):
        """A bare Scene has transition_type, mood, caption_emphasis all None."""
        scene = Scene(
            scene_number=1,
            narration="Narration",
            visual_description="desc",
            visual_type="stock_footage",
            stock_query="nature",
            ai_prompt="prompt",
            duration_seconds=5.0,
        )
        assert scene.transition_type is None
        assert scene.mood is None
        assert scene.caption_emphasis is None

    @patch("app.services.scene_director_service.get_settings")
    def test_compute_directions_with_old_style_scenes(self, mock_gs):
        """compute_creative_directions handles scenes that lack creative fields."""
        mock_gs.return_value = _mock_settings()
        old_scenes = [
            Scene(
                scene_number=i,
                narration=f"Scene {i}",
                visual_description="desc",
                visual_type="stock_footage",
                stock_query="nature",
                ai_prompt="prompt",
                duration_seconds=5.0,
            )
            for i in range(1, 4)
        ]

        dirs = compute_creative_directions(old_scenes, preset="auto")

        assert isinstance(dirs, CreativeDirections)
        assert dirs.caption_style == "classic"
        assert dirs.transition_style == "auto"
        assert dirs.dominant_mood == "uplifting"
        assert dirs.transitions == []
        assert dirs.bgm_volume_db == -18.0

    @patch("app.services.scene_director_service.get_settings")
    def test_preset_works_with_old_style_scenes(self, mock_gs):
        """Named presets work even when scenes lack creative direction fields."""
        mock_gs.return_value = _mock_settings()
        old_scenes = [
            Scene(
                scene_number=1,
                narration="Scene 1",
                visual_description="desc",
                visual_type="stock_footage",
                stock_query="nature",
                ai_prompt="prompt",
                duration_seconds=5.0,
            ),
        ]

        dirs = compute_creative_directions(old_scenes, preset="cinematic")

        assert dirs.caption_style == "karaoke"
        assert dirs.transition_style == "auto"
        assert dirs.bgm_volume_db == -16.0
        # Mood falls back to settings default since scenes have no mood
        assert dirs.dominant_mood == "uplifting"
