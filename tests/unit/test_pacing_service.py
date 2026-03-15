"""Unit tests for PacingService — scene pacing and FFmpeg speed effects."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.pacing_service import (
    BEAT_PACING,
    MOOD_PACING,
    _build_atempo_chain,
    _scenes_to_beats,
    apply_speed_effect,
    compute_scene_pacing,
)


SETTINGS_PATCH = "app.services.pacing_service.get_settings"


# ── Helpers ──────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Create a mock Settings with pacing-related defaults."""
    defaults = {
        "pacing_min_speed": 0.75,
        "pacing_max_speed": 1.25,
        "pacing_base_speed": 1.0,
    }
    defaults.update(overrides)
    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)
    return settings


# ── TestScenesToBeats ────────────────────────────────────────────


class TestScenesToBeats:
    """_scenes_to_beats maps scene positions to beat types."""

    def test_one_scene_returns_hook(self):
        assert _scenes_to_beats(1) == ["hook"]

    def test_two_scenes_returns_hook_kicker(self):
        assert _scenes_to_beats(2) == ["hook", "kicker"]

    def test_three_scenes_returns_hook_climax_kicker(self):
        assert _scenes_to_beats(3) == ["hook", "climax", "kicker"]

    def test_four_scenes_returns_hook_build_climax_kicker(self):
        assert _scenes_to_beats(4) == ["hook", "build", "climax", "kicker"]

    def test_five_scenes_returns_hook_build_build_climax_kicker(self):
        assert _scenes_to_beats(5) == ["hook", "build", "build", "climax", "kicker"]

    def test_six_scenes_has_three_builds(self):
        result = _scenes_to_beats(6)
        assert result == ["hook", "build", "build", "build", "climax", "kicker"]
        assert len(result) == 6

    def test_ten_scenes_has_seven_builds(self):
        result = _scenes_to_beats(10)
        assert result[0] == "hook"
        assert result[-1] == "kicker"
        assert result[-2] == "climax"
        assert result.count("build") == 7
        assert len(result) == 10

    def test_first_is_always_hook(self):
        for n in range(1, 12):
            assert _scenes_to_beats(n)[0] == "hook"

    def test_last_is_kicker_for_multi_scene(self):
        for n in range(2, 12):
            assert _scenes_to_beats(n)[-1] == "kicker"

    def test_length_matches_input(self):
        for n in range(1, 15):
            assert len(_scenes_to_beats(n)) == n


# ── TestComputeScenePacing ───────────────────────────────────────


class TestComputeScenePacing:
    """compute_scene_pacing returns speed multipliers per scene."""

    @patch(SETTINGS_PATCH)
    def test_returns_list_of_correct_length(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(5, mood="uplifting")
        assert isinstance(result, list)
        assert len(result) == 5

    @patch(SETTINGS_PATCH)
    def test_uniform_style_returns_all_same_values(self, mock_gs):
        mock_gs.return_value = _make_settings(pacing_base_speed=1.0)
        result = compute_scene_pacing(5, mood="energetic", pacing_style="uniform")
        assert all(s == 1.0 for s in result)

    @patch(SETTINGS_PATCH)
    def test_uniform_style_uses_base_speed(self, mock_gs):
        mock_gs.return_value = _make_settings(pacing_base_speed=1.1)
        result = compute_scene_pacing(3, pacing_style="uniform")
        assert all(s == 1.1 for s in result)

    @patch(SETTINGS_PATCH)
    def test_single_scene_returns_base_speed(self, mock_gs):
        mock_gs.return_value = _make_settings(pacing_base_speed=1.05)
        result = compute_scene_pacing(1, mood="dramatic")
        assert result == [1.05]

    @patch(SETTINGS_PATCH)
    def test_dramatic_mood_gives_slow_climax(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(3, mood="dramatic", pacing_style="auto")
        # Scene 2 is climax for 3-scene; dramatic climax = 0.80 * base_speed 1.0 = 0.80
        climax_speed = result[1]  # index 1 = climax for 3 scenes
        assert climax_speed < 1.0, f"Dramatic climax should be slow, got {climax_speed}"

    @patch(SETTINGS_PATCH)
    def test_energetic_mood_gives_fast_hook(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(3, mood="energetic", pacing_style="auto")
        hook_speed = result[0]
        assert hook_speed >= 1.0, f"Energetic hook should be fast, got {hook_speed}"

    @patch(SETTINGS_PATCH)
    def test_clamps_to_min_speed(self, mock_gs):
        mock_gs.return_value = _make_settings(pacing_min_speed=0.9, pacing_max_speed=1.25)
        result = compute_scene_pacing(3, mood="dramatic", pacing_style="auto")
        for speed in result:
            assert speed >= 0.9, f"Speed {speed} below min 0.9"

    @patch(SETTINGS_PATCH)
    def test_clamps_to_max_speed(self, mock_gs):
        mock_gs.return_value = _make_settings(pacing_min_speed=0.75, pacing_max_speed=1.1)
        result = compute_scene_pacing(5, mood="energetic", pacing_style="auto")
        for speed in result:
            assert speed <= 1.1, f"Speed {speed} above max 1.1"

    @patch(SETTINGS_PATCH)
    def test_all_values_are_floats(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(4, mood="uplifting")
        assert all(isinstance(s, float) for s in result)

    @patch(SETTINGS_PATCH)
    def test_auto_style_uses_mood_speeds(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(3, mood="calm", pacing_style="auto")
        # calm mood has all speeds <= 1.0
        for speed in result:
            assert speed <= 1.05, f"Calm should not have high speeds, got {speed}"

    @patch(SETTINGS_PATCH)
    def test_unknown_mood_falls_back_to_uplifting(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result_unknown = compute_scene_pacing(3, mood="nonexistent_mood", pacing_style="auto")
        result_uplifting = compute_scene_pacing(3, mood="uplifting", pacing_style="auto")
        assert result_unknown == result_uplifting

    @patch(SETTINGS_PATCH)
    def test_specific_mood_pacing_style(self, mock_gs):
        """pacing_style can be a mood name to use that mood's pacing."""
        mock_gs.return_value = _make_settings()
        result = compute_scene_pacing(3, mood="uplifting", pacing_style="dramatic")
        # Should use dramatic mood's pacing, not uplifting
        climax_speed = result[1]
        dramatic_climax_speed = MOOD_PACING["dramatic"]["climax"]
        # With base_speed=1.0, should approximate dramatic climax
        assert climax_speed == pytest.approx(dramatic_climax_speed, abs=0.01)

    @patch(SETTINGS_PATCH)
    def test_base_speed_multiplier_applied(self, mock_gs):
        """base_speed multiplies the mood/beat speed."""
        mock_gs.return_value = _make_settings(pacing_base_speed=1.1, pacing_max_speed=2.0)
        result = compute_scene_pacing(1, mood="uplifting", pacing_style="uniform")
        assert result == [1.1]


# ── TestBeatPacingConstants ──────────────────────────────────────


class TestBeatPacingConstants:
    """BEAT_PACING and MOOD_PACING constants validation."""

    def test_beat_pacing_has_four_beats(self):
        assert set(BEAT_PACING.keys()) == {"hook", "build", "climax", "kicker"}

    def test_beat_pacing_values_are_floats(self):
        for beat, speed in BEAT_PACING.items():
            assert isinstance(speed, float), f"{beat} speed is not float"

    def test_climax_is_slowest_beat(self):
        assert BEAT_PACING["climax"] < BEAT_PACING["hook"]
        assert BEAT_PACING["climax"] < BEAT_PACING["build"]
        assert BEAT_PACING["climax"] < BEAT_PACING["kicker"]

    def test_kicker_is_fastest_beat(self):
        assert BEAT_PACING["kicker"] >= max(BEAT_PACING[b] for b in ["hook", "build"])

    ALL_MOODS = list(MOOD_PACING.keys())

    def test_mood_pacing_has_10_moods(self):
        assert len(MOOD_PACING) == 10

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_mood_has_required_keys(self, mood):
        required = {"base", "hook", "build", "climax", "kicker"}
        assert required.issubset(set(MOOD_PACING[mood].keys())), (
            f"Mood '{mood}' missing keys: {required - set(MOOD_PACING[mood].keys())}"
        )

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_mood_values_are_floats(self, mood):
        for key, val in MOOD_PACING[mood].items():
            assert isinstance(val, (int, float)), f"{mood}.{key} is not numeric"

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_mood_values_are_reasonable(self, mood):
        for key, val in MOOD_PACING[mood].items():
            assert 0.5 <= val <= 2.0, f"{mood}.{key}={val} out of reasonable range"


# ── TestBuildAtempoChain ─────────────────────────────────────────


class TestBuildAtempoChain:
    """_build_atempo_chain handles FFmpeg atempo 0.5-2.0 range limit."""

    def test_normal_speed_single_filter(self):
        assert _build_atempo_chain(1.5) == "atempo=1.5"

    def test_exact_0_5_single_filter(self):
        assert _build_atempo_chain(0.5) == "atempo=0.5"

    def test_exact_2_0_single_filter(self):
        assert _build_atempo_chain(2.0) == "atempo=2.0"

    def test_speed_1_0_single_filter(self):
        assert _build_atempo_chain(1.0) == "atempo=1.0"

    def test_speed_3_0_chains_two_filters(self):
        result = _build_atempo_chain(3.0)
        # 3.0 > 2.0, so: atempo=2.0, then atempo=1.5 (3.0/2.0)
        assert result.startswith("atempo=2.0,atempo=")
        parts = result.split(",")
        assert len(parts) == 2

    def test_speed_4_0_chains_filters(self):
        result = _build_atempo_chain(4.0)
        # 4.0 / 2.0 = 2.0 — so two atempo=2.0 filters
        assert "atempo=2.0" in result
        parts = result.split(",")
        assert len(parts) >= 2

    def test_speed_0_3_chains_slow_filters(self):
        result = _build_atempo_chain(0.3)
        # 0.3 < 0.5, so: atempo=0.5, then atempo=0.6 (0.3/0.5)
        assert "atempo=0.5" in result
        parts = result.split(",")
        assert len(parts) >= 2

    def test_speed_0_25_chains_multiple_slow_filters(self):
        result = _build_atempo_chain(0.25)
        # 0.25 < 0.5: atempo=0.5, remaining=0.5 → atempo=0.5
        parts = result.split(",")
        assert len(parts) >= 2

    def test_all_parts_start_with_atempo(self):
        for speed in [0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
            result = _build_atempo_chain(speed)
            for part in result.split(","):
                assert part.startswith("atempo="), f"Bad part '{part}' for speed={speed}"


# ── TestApplySpeedEffect ─────────────────────────────────────────


class TestApplySpeedEffect:
    """apply_speed_effect applies FFmpeg speed changes or copies file."""

    @patch("shutil.copy2")
    def test_speed_1_0_copies_file(self, mock_copy, tmp_path):
        """Speed of exactly 1.0 should copy instead of FFmpeg."""
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        result = apply_speed_effect(input_path, output_path, 1.0)
        mock_copy.assert_called_once_with(input_path, output_path)
        assert result == output_path

    @patch("shutil.copy2")
    def test_speed_near_1_0_copies_file(self, mock_copy, tmp_path):
        """Speed within 0.01 of 1.0 should also copy."""
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        apply_speed_effect(input_path, output_path, 1.005)
        mock_copy.assert_called_once()

    @patch("app.services.pacing_service.subprocess.run")
    def test_speed_1_5_calls_ffmpeg(self, mock_run, tmp_path):
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        mock_run.return_value = MagicMock(returncode=0)
        result = apply_speed_effect(input_path, output_path, 1.5)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-filter:v" in cmd
        assert "setpts=PTS/1.5" in cmd
        assert "-filter:a" in cmd
        assert "atempo=1.5" in cmd
        assert result == output_path

    @patch("app.services.pacing_service.subprocess.run")
    def test_speed_0_8_calls_ffmpeg_with_slowmo(self, mock_run, tmp_path):
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        mock_run.return_value = MagicMock(returncode=0)
        apply_speed_effect(input_path, output_path, 0.8)

        cmd = mock_run.call_args[0][0]
        assert "setpts=PTS/0.8" in cmd
        assert "atempo=0.8" in cmd

    @patch("app.services.pacing_service.subprocess.run")
    def test_ffmpeg_called_with_check_true(self, mock_run, tmp_path):
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        mock_run.return_value = MagicMock(returncode=0)
        apply_speed_effect(input_path, output_path, 1.5)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["check"] is True
        assert call_kwargs["capture_output"] is True
        assert call_kwargs["timeout"] == 120

    @patch("app.services.pacing_service.subprocess.run")
    def test_ffmpeg_failure_retries_without_audio(self, mock_run, tmp_path):
        """If first FFmpeg call fails, retry without audio filter."""
        import subprocess

        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        # First call raises CalledProcessError, second succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "ffmpeg"),
            MagicMock(returncode=0),
        ]
        result = apply_speed_effect(input_path, output_path, 1.5)

        assert mock_run.call_count == 2
        # Second call should have -an flag (no audio)
        second_cmd = mock_run.call_args_list[1][0][0]
        assert "-an" in second_cmd
        assert "-filter:a" not in second_cmd
        assert result == output_path

    @patch("app.services.pacing_service.subprocess.run")
    def test_output_uses_libx264_codec(self, mock_run, tmp_path):
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        mock_run.return_value = MagicMock(returncode=0)
        apply_speed_effect(input_path, output_path, 1.3)

        cmd = mock_run.call_args[0][0]
        assert "-c:v" in cmd
        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "libx264"

    @patch("app.services.pacing_service.subprocess.run")
    def test_returns_output_path(self, mock_run, tmp_path):
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.touch()

        mock_run.return_value = MagicMock(returncode=0)
        result = apply_speed_effect(input_path, output_path, 1.2)
        assert result == output_path
