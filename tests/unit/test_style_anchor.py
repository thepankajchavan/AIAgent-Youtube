"""Unit tests for Phase 2: Visual style anchor.

Tests:
  - _build_style_anchor() token extraction from Scene 1's ai_prompt
  - _apply_style_anchor() prepending anchor to scene ai_prompts
"""

import pytest

from app.services.ai_video_service import Scene, _apply_style_anchor, _build_style_anchor


def _make_scene(
    scene_number: int = 1,
    ai_prompt: str = "",
    narration: str = "Narration.",
) -> Scene:
    """Helper to create a Scene with defaults."""
    return Scene(
        scene_number=scene_number,
        narration=narration,
        visual_description="desc",
        visual_type="ai_generated",
        stock_query="test",
        ai_prompt=ai_prompt,
        duration_seconds=5.0,
    )


# ── _build_style_anchor tests ────────────────────────────────────


class TestBuildStyleAnchor:
    """Test extraction of visual DNA from Scene 1's ai_prompt."""

    def test_prompt_with_lighting_tokens(self):
        """Prompt containing lighting tokens should be extracted."""
        scenes = [
            _make_scene(ai_prompt="Wide shot of a desert at golden hour with dramatic lighting, volumetric lighting rays"),
        ]

        anchor = _build_style_anchor(scenes)

        assert "VISUAL CONSISTENCY" in anchor
        assert "golden hour" in anchor
        assert "dramatic lighting" in anchor
        assert "volumetric lighting" in anchor

    def test_prompt_with_color_tokens(self):
        """Prompt containing color tokens should be extracted."""
        scenes = [
            _make_scene(ai_prompt="City skyline with warm tones, orange-teal color grading, amber highlights"),
        ]

        anchor = _build_style_anchor(scenes)

        assert "VISUAL CONSISTENCY" in anchor
        assert "warm tones" in anchor
        assert "amber" in anchor

    def test_prompt_with_no_style_tokens(self):
        """Prompt with no matching style tokens returns empty string."""
        scenes = [
            _make_scene(ai_prompt="A person walking down a street talking on their phone"),
        ]

        anchor = _build_style_anchor(scenes)

        assert anchor == ""

    def test_empty_scenes_list(self):
        """Empty scenes list returns empty string."""
        anchor = _build_style_anchor([])

        assert anchor == ""

    def test_caps_at_8_tokens(self):
        """Should cap extracted tokens at 8 to keep the anchor concise."""
        # Prompt with many style tokens (> 8)
        scenes = [
            _make_scene(
                ai_prompt=(
                    "cinematic golden hour warm tones amber neon-lit "
                    "volumetric lighting dramatic lighting film grain "
                    "8k shallow depth of field saturated muted"
                )
            ),
        ]

        anchor = _build_style_anchor(scenes)

        # Count tokens in the anchor (between "maintain " and ".")
        if anchor:
            token_part = anchor.split("maintain ")[1].rstrip(".")
            tokens = [t.strip() for t in token_part.split(",")]
            assert len(tokens) <= 8

    def test_uses_only_first_scene(self):
        """Only Scene 1's ai_prompt should be scanned, not subsequent scenes."""
        scenes = [
            _make_scene(scene_number=1, ai_prompt="A simple shot of a tree"),
            _make_scene(
                scene_number=2,
                ai_prompt="cinematic golden hour warm tones neon-lit volumetric lighting",
            ),
        ]

        anchor = _build_style_anchor(scenes)

        # Scene 1 has no style tokens, so anchor should be empty
        assert anchor == ""

    def test_first_scene_with_empty_ai_prompt(self):
        """Scene 1 with empty ai_prompt returns empty anchor."""
        scenes = [
            _make_scene(scene_number=1, ai_prompt=""),
            _make_scene(scene_number=2, ai_prompt="golden hour cinematic"),
        ]

        anchor = _build_style_anchor(scenes)

        assert anchor == ""

    def test_aesthetic_tokens_extracted(self):
        """Aesthetic tokens like 'cinematic', 'film grain', '8k' should be extracted."""
        scenes = [
            _make_scene(ai_prompt="A cinematic establishing shot with film grain and 8k detail"),
        ]

        anchor = _build_style_anchor(scenes)

        assert "cinematic" in anchor
        assert "film grain" in anchor
        assert "8k" in anchor

    def test_case_insensitive_matching(self):
        """Token matching should be case-insensitive."""
        scenes = [
            _make_scene(ai_prompt="GOLDEN HOUR sunrise with WARM TONES across the landscape"),
        ]

        anchor = _build_style_anchor(scenes)

        assert "golden hour" in anchor
        assert "warm tones" in anchor


# ── _apply_style_anchor tests ────────────────────────────────────


class TestApplyStyleAnchor:
    """Test prepending the style anchor to scene ai_prompts."""

    def test_prepends_anchor_to_ai_prompt(self):
        """Anchor should be prepended to the scene's ai_prompt."""
        scene = _make_scene(ai_prompt="A wide shot of the ocean at dusk")
        anchor = "VISUAL CONSISTENCY: maintain golden hour, warm tones."

        _apply_style_anchor(scene, anchor)

        assert scene.ai_prompt.startswith("VISUAL CONSISTENCY: maintain golden hour, warm tones.")
        assert "A wide shot of the ocean at dusk" in scene.ai_prompt

    def test_skips_if_anchor_already_present(self):
        """Should not double-apply the anchor if it's already in the prompt."""
        anchor = "VISUAL CONSISTENCY: maintain golden hour, warm tones."
        scene = _make_scene(
            ai_prompt=f"{anchor} A close-up of flowers in bloom"
        )
        original_prompt = scene.ai_prompt

        _apply_style_anchor(scene, anchor)

        # Should be unchanged — no double application
        assert scene.ai_prompt == original_prompt

    def test_skips_if_anchor_empty(self):
        """Should not modify prompt if anchor is empty string."""
        scene = _make_scene(ai_prompt="A tracking shot through the forest")
        original_prompt = scene.ai_prompt

        _apply_style_anchor(scene, "")

        assert scene.ai_prompt == original_prompt

    def test_skips_if_scene_has_no_ai_prompt(self):
        """Should not crash if scene has empty ai_prompt."""
        scene = _make_scene(ai_prompt="")
        anchor = "VISUAL CONSISTENCY: maintain golden hour."

        _apply_style_anchor(scene, anchor)

        assert scene.ai_prompt == ""

    def test_case_insensitive_duplicate_detection(self):
        """Duplicate detection should be case-insensitive."""
        anchor = "VISUAL CONSISTENCY: maintain golden hour."
        scene = _make_scene(
            ai_prompt="visual consistency: maintain golden hour. A wide shot of mountains"
        )
        original_prompt = scene.ai_prompt

        _apply_style_anchor(scene, anchor)

        # Should be unchanged since anchor is already present (case-insensitive)
        assert scene.ai_prompt == original_prompt

    def test_anchor_separated_by_space(self):
        """Anchor and original prompt should be separated by a space."""
        scene = _make_scene(ai_prompt="Close-up of lava flowing")
        anchor = "VISUAL CONSISTENCY: maintain cinematic, warm tones."

        _apply_style_anchor(scene, anchor)

        assert scene.ai_prompt == (
            "VISUAL CONSISTENCY: maintain cinematic, warm tones. Close-up of lava flowing"
        )
