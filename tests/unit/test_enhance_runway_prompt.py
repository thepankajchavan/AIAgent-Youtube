"""Unit tests for prompt enhancement — Runway, Stability, and Kling."""

from app.services.ai_video_service import (
    _enhance_kling_prompt,
    _enhance_runway_prompt,
    _enhance_stability_prompt,
)


class TestEnhanceRunwayPrompt:
    """Test prompt enhancement for Runway API."""

    def test_appends_missing_quality_tokens(self):
        """Quality tokens (8K, film grain, etc.) are added when absent."""
        prompt = "A cat sitting on a windowsill at sunset"
        result = _enhance_runway_prompt(prompt)

        assert "8K" in result
        assert "cinematic" in result
        assert "film grain" in result
        assert "shallow depth of field" in result
        assert "professional color grading" in result

    def test_does_not_duplicate_existing_tokens(self):
        """Tokens already in the prompt are not repeated."""
        prompt = "A cinematic dolly shot of a forest with film grain and 8K detail"
        result = _enhance_runway_prompt(prompt)

        # "cinematic", "film grain", "8K" already present — should not duplicate
        assert result.lower().count("cinematic") == 1
        assert result.lower().count("film grain") == 1
        assert result.lower().count("8k") == 1

    def test_adds_portrait_framing_for_9_16(self):
        """9:16 aspect ratio adds vertical/portrait framing hint."""
        prompt = "A person walking through a neon-lit city street"
        result = _enhance_runway_prompt(prompt, aspect_ratio="9:16")

        assert "vertical composition" in result

    def test_adds_landscape_framing_for_16_9(self):
        """16:9 aspect ratio adds wide/landscape framing hint."""
        prompt = "A sweeping mountain landscape at golden hour"
        result = _enhance_runway_prompt(prompt, aspect_ratio="16:9")

        assert "wide cinematic composition" in result

    def test_adds_smooth_motion_when_absent(self):
        """Smooth motion hint is added when not present."""
        prompt = "A drone flying over a tropical beach"
        result = _enhance_runway_prompt(prompt)

        assert "smooth" in result.lower()

    def test_no_smooth_motion_when_already_present(self):
        """Smooth motion is not added if 'smooth' already appears."""
        prompt = "A smooth dolly shot tracking a runner through a park"
        result = _enhance_runway_prompt(prompt)

        # Should not add "Smooth, fluid camera motion" since "smooth" exists
        assert "fluid camera motion" not in result

    def test_no_smooth_when_fluid_present(self):
        """Smooth motion is not added if 'fluid' already appears."""
        prompt = "Fluid tracking shot following a dancer"
        result = _enhance_runway_prompt(prompt)

        assert "Smooth, fluid camera motion" not in result

    def test_cleans_up_whitespace(self):
        """Extra whitespace is collapsed."""
        prompt = "A   wide   shot   of   the   ocean"
        result = _enhance_runway_prompt(prompt)

        assert "  " not in result

    def test_preserves_original_content(self):
        """Original prompt content is preserved in the output."""
        prompt = "Extreme close-up of a hummingbird feeding from a red flower"
        result = _enhance_runway_prompt(prompt)

        assert "hummingbird" in result
        assert "red flower" in result

    def test_handles_empty_prompt(self):
        """Empty prompt doesn't crash — tokens are still appended."""
        result = _enhance_runway_prompt("")

        assert "cinematic" in result
        assert "8K" in result


class TestEnhanceStabilityPrompt:
    """Test prompt enhancement for Stability AI."""

    def test_adds_stability_specific_tokens(self):
        """Stability-specific tokens (natural lighting, subtle motion) added."""
        prompt = "A flower blooming in a garden"
        result = _enhance_stability_prompt(prompt)

        assert "natural lighting" in result
        assert "subtle natural motion" in result
        assert "high detail" in result

    def test_adds_shared_quality_tokens(self):
        """Shared quality tokens (8K, cinematic) are also added."""
        prompt = "A bird perched on a branch"
        result = _enhance_stability_prompt(prompt)

        assert "8K" in result
        assert "cinematic" in result

    def test_does_not_duplicate_existing(self):
        """Tokens already present are not duplicated."""
        prompt = "A high detail photograph with natural lighting and 8K resolution"
        result = _enhance_stability_prompt(prompt)

        assert result.lower().count("natural lighting") == 1
        assert result.lower().count("8k") == 1

    def test_adds_framing_hint(self):
        """Aspect ratio framing hint is added."""
        prompt = "A sunset over the ocean"
        result = _enhance_stability_prompt(prompt, aspect_ratio="9:16")

        assert "vertical composition" in result

    def test_cleans_whitespace(self):
        """Extra whitespace is collapsed."""
        prompt = "A   wide   shot"
        result = _enhance_stability_prompt(prompt)

        assert "  " not in result


class TestEnhanceKlingPrompt:
    """Test prompt enhancement for Kling AI."""

    def test_adds_quality_tokens(self):
        """Quality tokens are added when absent."""
        prompt = "A car driving through a tunnel"
        result = _enhance_kling_prompt(prompt)

        assert "8K" in result
        assert "cinematic" in result

    def test_adds_smooth_motion(self):
        """Smooth motion is added when absent."""
        prompt = "A dancer spinning on stage"
        result = _enhance_kling_prompt(prompt)

        assert "smooth" in result.lower()

    def test_adds_dynamic_composition(self):
        """Kling-specific dynamic composition is added."""
        prompt = "A skateboarder doing tricks"
        result = _enhance_kling_prompt(prompt)

        assert "dynamic composition" in result.lower()

    def test_no_dynamic_when_present(self):
        """Dynamic composition not duplicated if already present."""
        prompt = "A dynamic tracking shot of a runner"
        result = _enhance_kling_prompt(prompt)

        assert result.lower().count("dynamic") == 1

    def test_adds_framing_for_16_9(self):
        """16:9 framing hint added."""
        prompt = "A panoramic mountain view"
        result = _enhance_kling_prompt(prompt, aspect_ratio="16:9")

        assert "wide cinematic composition" in result

    def test_handles_empty_prompt(self):
        """Empty prompt doesn't crash."""
        result = _enhance_kling_prompt("")

        assert "cinematic" in result
        assert "8K" in result
