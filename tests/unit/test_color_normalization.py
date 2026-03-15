"""Unit tests for Phase 5: Color normalization.

Tests:
  - normalize_color_grading() FFmpeg command construction per profile
  - Unknown profile falls back to neutral
  - FFmpeg failure raises RuntimeError
  - _MOOD_COLOR_MAP coverage and correctness
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.media_service import _COLOR_PROFILES, _MOOD_COLOR_MAP, normalize_color_grading


class TestNormalizeColorGrading:
    """Test FFmpeg-based color normalization for each profile."""

    def test_neutral_profile_ffmpeg_command(self, mocker, tmp_path):
        """Verify correct FFmpeg filter chain for 'neutral' profile."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="neutral")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]

        # Verify FFmpeg base structure
        assert args[0] == "ffmpeg"
        assert "-y" in args
        assert "-i" in args
        assert str(video_path) in args
        assert str(output_path) in args

        # Verify -vf contains neutral profile filter
        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]
        assert "eq=contrast=1.05" in vf_value
        assert "brightness=0.02" in vf_value
        assert "saturation=1.1" in vf_value
        assert "unsharp" in vf_value
        # Neutral should NOT have colorbalance
        assert "colorbalance" not in vf_value

    def test_cinematic_profile_ffmpeg_command(self, mocker, tmp_path):
        """Verify correct FFmpeg filter chain for 'cinematic' profile."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="cinematic")

        args = mock_run.call_args[0][0]
        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]

        assert "eq=contrast=1.1" in vf_value
        assert "brightness=-0.02" in vf_value
        assert "saturation=0.95" in vf_value
        assert "colorbalance" in vf_value
        assert "bs=0.05" in vf_value  # blue shadows push

    def test_warm_profile_ffmpeg_command(self, mocker, tmp_path):
        """Verify correct FFmpeg filter chain for 'warm' profile."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="warm")

        args = mock_run.call_args[0][0]
        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]

        assert "eq=contrast=1.05" in vf_value
        assert "saturation=1.05" in vf_value
        assert "colorbalance" in vf_value
        assert "rs=0.06" in vf_value  # red shadows push for warmth
        assert "bs=-0.04" in vf_value  # blue reduction for warmth

    def test_cool_profile_ffmpeg_command(self, mocker, tmp_path):
        """Verify correct FFmpeg filter chain for 'cool' profile."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="cool")

        args = mock_run.call_args[0][0]
        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]

        assert "eq=contrast=1.05" in vf_value
        assert "saturation=1.0" in vf_value
        assert "colorbalance" in vf_value
        assert "rs=-0.04" in vf_value  # red reduction for coolness
        assert "bs=0.06" in vf_value  # blue push for coolness

    def test_unknown_profile_falls_back_to_neutral(self, mocker, tmp_path):
        """Unknown profile name should use neutral profile filters."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="nonexistent_profile")

        args = mock_run.call_args[0][0]
        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]

        # Should use neutral profile filter string
        assert vf_value == _COLOR_PROFILES["neutral"]

    def test_ffmpeg_failure_raises_runtime_error(self, mocker, tmp_path):
        """FFmpeg failure should raise RuntimeError."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: invalid filter"
        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="color normalization failed"):
            normalize_color_grading(video_path, output_path, profile="neutral")

    def test_output_encoding_settings(self, mocker, tmp_path):
        """Verify output uses libx264 with correct settings."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="neutral")

        args = mock_run.call_args[0][0]
        assert "-c:v" in args
        cv_idx = args.index("-c:v")
        assert args[cv_idx + 1] == "libx264"
        assert "-crf" in args
        assert "-pix_fmt" in args
        assert "yuv420p" in args

    def test_audio_is_copied_not_reencoded(self, mocker, tmp_path):
        """Audio stream should be copied as-is during color normalization."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        normalize_color_grading(video_path, output_path, profile="warm")

        args = mock_run.call_args[0][0]
        assert "-c:a" in args
        ca_idx = args.index("-c:a")
        assert args[ca_idx + 1] == "copy"

    def test_returns_output_path(self, mocker, tmp_path):
        """Function should return the output path."""
        video_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        video_path.write_bytes(b"video")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mocker.patch("subprocess.run", return_value=mock_result)

        result = normalize_color_grading(video_path, output_path, profile="neutral")

        assert result == output_path


class TestColorProfiles:
    """Test that color profile definitions are correct."""

    def test_all_four_profiles_exist(self):
        """All four profiles should be defined."""
        assert "neutral" in _COLOR_PROFILES
        assert "cinematic" in _COLOR_PROFILES
        assert "warm" in _COLOR_PROFILES
        assert "cool" in _COLOR_PROFILES

    def test_all_profiles_contain_eq_filter(self):
        """Every profile should include eq filter for contrast/brightness/saturation."""
        for name, vf in _COLOR_PROFILES.items():
            assert "eq=" in vf, f"Profile '{name}' missing eq filter"

    def test_all_profiles_contain_unsharp(self):
        """Every profile should include unsharp filter for subtle sharpening."""
        for name, vf in _COLOR_PROFILES.items():
            assert "unsharp" in vf, f"Profile '{name}' missing unsharp filter"

    def test_cinematic_has_colorbalance(self):
        """Cinematic profile should include colorbalance for teal/orange grading."""
        assert "colorbalance" in _COLOR_PROFILES["cinematic"]

    def test_warm_has_colorbalance(self):
        """Warm profile should include colorbalance for warm tones."""
        assert "colorbalance" in _COLOR_PROFILES["warm"]

    def test_cool_has_colorbalance(self):
        """Cool profile should include colorbalance for cool tones."""
        assert "colorbalance" in _COLOR_PROFILES["cool"]


class TestMoodColorMap:
    """Test mood-to-color-profile mapping."""

    def test_all_10_moods_have_entries(self):
        """All 10 standard moods should map to a color profile."""
        expected_moods = [
            "energetic", "calm", "dramatic", "mysterious", "uplifting",
            "dark", "happy", "sad", "epic", "chill",
        ]
        for mood in expected_moods:
            assert mood in _MOOD_COLOR_MAP, f"Mood '{mood}' missing from _MOOD_COLOR_MAP"

    def test_dramatic_maps_to_cinematic(self):
        assert _MOOD_COLOR_MAP["dramatic"] == "cinematic"

    def test_calm_maps_to_cool(self):
        assert _MOOD_COLOR_MAP["calm"] == "cool"

    def test_mysterious_maps_to_cinematic(self):
        assert _MOOD_COLOR_MAP["mysterious"] == "cinematic"

    def test_energetic_maps_to_warm(self):
        assert _MOOD_COLOR_MAP["energetic"] == "warm"

    def test_uplifting_maps_to_warm(self):
        assert _MOOD_COLOR_MAP["uplifting"] == "warm"

    def test_dark_maps_to_cinematic(self):
        assert _MOOD_COLOR_MAP["dark"] == "cinematic"

    def test_happy_maps_to_warm(self):
        assert _MOOD_COLOR_MAP["happy"] == "warm"

    def test_sad_maps_to_cool(self):
        assert _MOOD_COLOR_MAP["sad"] == "cool"

    def test_epic_maps_to_cinematic(self):
        assert _MOOD_COLOR_MAP["epic"] == "cinematic"

    def test_chill_maps_to_neutral(self):
        assert _MOOD_COLOR_MAP["chill"] == "neutral"

    def test_all_values_are_valid_profiles(self):
        """Every mood should map to a valid color profile key."""
        for mood, profile in _MOOD_COLOR_MAP.items():
            assert profile in _COLOR_PROFILES, (
                f"Mood '{mood}' maps to '{profile}' which is not a valid profile"
            )
