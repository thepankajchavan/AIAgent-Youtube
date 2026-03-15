"""Unit tests for Phase 6: Duration-aware scene planning.

Tests _enforce_provider_duration_limits() from ai_video_service.py:
  - Scenes under limit remain unchanged
  - Scenes over limit are split into sub-scenes
  - stock_footage scenes are never split
  - Total duration is preserved after split
  - Scene numbers are renumbered correctly
  - Narration words are split proportionally
"""

import pytest

from app.services.ai_video_service import Scene, _enforce_provider_duration_limits


def _make_scene(
    scene_number: int = 1,
    narration: str = "Test narration text.",
    duration: float = 5.0,
    visual_type: str = "ai_generated",
    ai_prompt: str = "cinematic shot",
    stock_query: str = "test query",
    transition_type: str | None = None,
    mood: str | None = None,
    caption_emphasis: str | None = None,
) -> Scene:
    """Helper to create a Scene with sensible defaults."""
    return Scene(
        scene_number=scene_number,
        narration=narration,
        visual_description="A visual description",
        visual_type=visual_type,
        stock_query=stock_query,
        ai_prompt=ai_prompt,
        duration_seconds=duration,
        transition_type=transition_type,
        mood=mood,
        caption_emphasis=caption_emphasis,
    )


class TestEnforceProviderDurationLimitsNoSplit:
    """Test cases where no splitting should occur."""

    def test_all_scenes_under_limit_no_changes(self):
        """When all scenes are under the provider limit, nothing changes."""
        scenes = [
            _make_scene(scene_number=1, duration=5.0),
            _make_scene(scene_number=2, duration=8.0),
            _make_scene(scene_number=3, duration=7.0),
        ]
        total = sum(s.duration_seconds for s in scenes)

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 3
        assert result[0].duration_seconds == 5.0
        assert result[1].duration_seconds == 8.0
        assert result[2].duration_seconds == 7.0

    def test_scenes_exactly_at_limit(self):
        """Scenes at exactly 10s should NOT be split (limit is <=)."""
        scenes = [
            _make_scene(scene_number=1, duration=10.0),
            _make_scene(scene_number=2, duration=10.0),
        ]
        total = 20.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 2
        assert result[0].duration_seconds == 10.0
        assert result[1].duration_seconds == 10.0


class TestEnforceProviderDurationLimitsSplit:
    """Test scene splitting when duration exceeds limit."""

    def test_15s_scene_split_into_2(self):
        """A 15s scene with runway (max 10s) should split into 2 sub-scenes."""
        narration = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
        scenes = [
            _make_scene(scene_number=1, duration=15.0, narration=narration),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 2
        # Each sub-scene should be ~7.5s
        for s in result:
            assert s.duration_seconds <= 10.0
        # Narration should be split
        all_words = " ".join(s.narration for s in result).split()
        assert len(all_words) == 10

    def test_25s_scene_split_into_3(self):
        """A 25s scene should split into 3 sub-scenes (25/10 + 1 = 3)."""
        # 12 words for even splitting across 3 parts
        narration = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        scenes = [
            _make_scene(scene_number=1, duration=25.0, narration=narration),
        ]
        total = 25.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 3
        # Each sub-scene should be ~8.3s
        for s in result:
            assert s.duration_seconds <= 10.0

    def test_stock_footage_never_split(self):
        """stock_footage scenes should never be split even if > 10s."""
        scenes = [
            _make_scene(scene_number=1, duration=15.0, visual_type="stock_footage"),
            _make_scene(scene_number=2, duration=20.0, visual_type="stock_footage"),
        ]
        total = 35.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 2
        assert result[0].duration_seconds == 15.0
        assert result[1].duration_seconds == 20.0

    def test_total_duration_preserved(self):
        """Total duration must be preserved after splitting."""
        scenes = [
            _make_scene(scene_number=1, duration=5.0),
            _make_scene(scene_number=2, duration=15.0, narration="one two three four five six"),
            _make_scene(scene_number=3, duration=8.0),
        ]
        total = 28.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        actual_total = sum(s.duration_seconds for s in result)
        assert abs(actual_total - total) < 0.2  # Allow small rounding

    def test_scene_numbers_renumbered(self):
        """After splitting, scene numbers should be sequential starting from 1."""
        scenes = [
            _make_scene(scene_number=1, duration=5.0),
            _make_scene(scene_number=2, duration=15.0, narration="a b c d e f"),
            _make_scene(scene_number=3, duration=5.0),
        ]
        total = 25.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        expected_numbers = list(range(1, len(result) + 1))
        actual_numbers = [s.scene_number for s in result]
        assert actual_numbers == expected_numbers

    def test_narration_words_split_proportionally(self):
        """Words should be divided roughly equally across sub-scenes."""
        narration = "word1 word2 word3 word4 word5 word6 word7 word8"
        scenes = [
            _make_scene(scene_number=1, duration=15.0, narration=narration),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 2
        # 8 words / 2 splits = 4 words each
        words_per_scene = [len(s.narration.split()) for s in result]
        assert words_per_scene[0] == 4
        assert words_per_scene[1] == 4

    def test_ai_prompt_has_continuation_label(self):
        """Split sub-scenes should have continuation labels in ai_prompt."""
        scenes = [
            _make_scene(
                scene_number=1,
                duration=15.0,
                narration="one two three four five six",
                ai_prompt="cinematic ocean shot",
            ),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert len(result) == 2
        assert "(continuation 1/2)" in result[0].ai_prompt
        assert "(continuation 2/2)" in result[1].ai_prompt

    def test_mixed_scenes_only_over_limit_split(self):
        """Only scenes exceeding the limit should be split; others are untouched."""
        scenes = [
            _make_scene(scene_number=1, duration=5.0, narration="short one"),
            _make_scene(scene_number=2, duration=15.0, narration="long narration with many words here"),
            _make_scene(scene_number=3, duration=8.0, narration="medium scene"),
        ]
        total = 28.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        # Scene 1 (5s) + Scene 2 split into 2 (7.5s each) + Scene 3 (8s) = 4 scenes
        assert len(result) == 4
        assert result[0].narration == "short one"
        assert result[3].narration == "medium scene"

    def test_transition_type_preserved_for_first_sub_scene(self):
        """First sub-scene should keep the original transition_type."""
        scenes = [
            _make_scene(
                scene_number=1,
                duration=15.0,
                narration="one two three four five six",
                transition_type="wipeleft",
            ),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        assert result[0].transition_type == "wipeleft"
        assert result[1].transition_type == "dissolve"  # subsequent sub-scenes get dissolve

    def test_mood_and_caption_emphasis_carried_to_sub_scenes(self):
        """Mood and caption_emphasis should propagate to all sub-scenes."""
        scenes = [
            _make_scene(
                scene_number=1,
                duration=15.0,
                narration="one two three four five six",
                mood="dramatic",
                caption_emphasis="strong",
            ),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "runway", total)

        for s in result:
            assert s.mood == "dramatic"
            assert s.caption_emphasis == "strong"

    def test_unknown_provider_uses_default_10s_limit(self):
        """Unknown provider should default to 10s max."""
        scenes = [
            _make_scene(scene_number=1, duration=15.0, narration="one two three four five six"),
        ]
        total = 15.0

        result = _enforce_provider_duration_limits(scenes, "unknown_provider", total)

        assert len(result) == 2
        for s in result:
            assert s.duration_seconds <= 10.0

    def test_empty_scenes_list(self):
        """Empty scenes list should return empty list."""
        result = _enforce_provider_duration_limits([], "runway", 0.0)
        assert result == []
