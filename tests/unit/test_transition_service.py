"""Tests for app.services.transition_service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.transition_service import (
    AVAILABLE_TRANSITIONS,
    _AUTO_CYCLE,
    compute_transitions_for_clips,
    select_durations,
    select_transitions,
)


# ── TestSelectTransitions ─────────────────────────────────────────


class TestSelectTransitions:
    """Tests for select_transitions()."""

    @pytest.mark.parametrize("num_clips,expected_count", [(5, 4), (6, 5), (8, 7)])
    def test_auto_mode_returns_correct_count(self, num_clips, expected_count):
        result = select_transitions(num_clips, style="auto")
        assert len(result) == expected_count

    def test_auto_mode_follows_cycle_order(self):
        result = select_transitions(9, style="auto")  # 8 transitions
        assert result == list(_AUTO_CYCLE)

    def test_auto_mode_cycles_back_for_more_than_8_scenes(self):
        # 10 clips => 9 transitions; position 8 (0-indexed) wraps to _AUTO_CYCLE[0]
        result = select_transitions(10, style="auto")
        assert len(result) == 9
        assert result[8] == _AUTO_CYCLE[0]
        # First 8 should match the cycle exactly
        assert result[:8] == list(_AUTO_CYCLE)

    def test_single_clip_returns_empty_list(self):
        result = select_transitions(1, style="auto")
        assert result == []

    def test_zero_clips_returns_empty_list(self):
        result = select_transitions(0, style="auto")
        assert result == []

    def test_specific_type_dissolve_returns_all_dissolve(self):
        result = select_transitions(5, style="dissolve")
        assert len(result) == 4
        assert all(t == "dissolve" for t in result)

    def test_specific_type_wipeleft(self):
        result = select_transitions(4, style="wipeleft")
        assert result == ["wipeleft"] * 3

    def test_uniform_style_returns_all_fade(self):
        result = select_transitions(6, style="uniform")
        assert len(result) == 5
        assert all(t == "fade" for t in result)

    def test_unknown_style_falls_back_to_fade(self):
        result = select_transitions(4, style="nonexistent_style")
        assert len(result) == 3
        assert all(t == "fade" for t in result)

    def test_two_clips_returns_single_transition(self):
        result = select_transitions(2, style="auto")
        assert len(result) == 1
        assert result[0] == _AUTO_CYCLE[0]

    def test_all_auto_cycle_entries_are_available(self):
        for t in _AUTO_CYCLE:
            assert t in AVAILABLE_TRANSITIONS


# ── TestSelectDurations ───────────────────────────────────────────


class TestSelectDurations:
    """Tests for select_durations()."""

    def test_returns_correct_count(self):
        result = select_durations(5, base_duration=0.3)
        assert len(result) == 4

    def test_first_duration_is_shorter(self):
        base = 0.4
        result = select_durations(5, base_duration=base)
        assert result[0] == round(base * 0.7, 2)

    def test_last_duration_is_longer(self):
        base = 0.4
        result = select_durations(5, base_duration=base)
        assert result[-1] == round(base * 1.5, 2)

    def test_middle_durations_equal_base(self):
        base = 0.3
        result = select_durations(6, base_duration=base)
        # Middle entries are index 1 through -2 (exclusive of first and last)
        for dur in result[1:-1]:
            assert dur == base

    def test_respects_max_bound(self):
        # base * 1.5 = 0.75, but max is 0.5 => last should be clamped to 0.5
        result = select_durations(4, base_duration=0.5, duration_min=0.2, duration_max=0.5)
        assert result[-1] == 0.5

    def test_respects_min_bound(self):
        # base * 0.7 = 0.07, but min is 0.2 => first should be clamped to 0.2
        result = select_durations(4, base_duration=0.1, duration_min=0.2, duration_max=0.8)
        assert result[0] == 0.2

    def test_single_transition_returns_base_clamped(self):
        # 2 clips => 1 transition, which uses the simple clamp path
        result = select_durations(2, base_duration=0.3, duration_min=0.2, duration_max=0.8)
        assert len(result) == 1
        assert result[0] == 0.3

    def test_single_transition_clamps_to_min(self):
        result = select_durations(2, base_duration=0.1, duration_min=0.2, duration_max=0.8)
        assert result[0] == 0.2

    def test_single_transition_clamps_to_max(self):
        result = select_durations(2, base_duration=1.0, duration_min=0.2, duration_max=0.8)
        assert result[0] == 0.8

    def test_single_clip_returns_empty(self):
        result = select_durations(1)
        assert result == []

    def test_zero_clips_returns_empty(self):
        result = select_durations(0)
        assert result == []

    def test_all_durations_within_bounds(self):
        d_min, d_max = 0.2, 0.8
        result = select_durations(8, base_duration=0.4, duration_min=d_min, duration_max=d_max)
        for dur in result:
            assert d_min <= dur <= d_max

    def test_default_parameters(self):
        result = select_durations(4)
        # base=0.3 => first=0.3*0.7=0.21, middle=0.3, last=0.3*1.5=0.45
        assert len(result) == 3
        assert result[0] == 0.21
        assert result[1] == 0.3
        assert result[2] == 0.45


# ── TestComputeTransitionsForClips ────────────────────────────────


class TestComputeTransitionsForClips:
    """Tests for compute_transitions_for_clips()."""

    def _mock_settings(self, **overrides):
        """Create a mock settings object with transition attributes."""
        defaults = {
            "transitions_enabled": True,
            "transition_style": "auto",
            "transition_duration": 0.3,
            "transition_duration_min": 0.2,
            "transition_duration_max": 0.8,
        }
        defaults.update(overrides)
        mock = MagicMock()
        for key, value in defaults.items():
            setattr(mock, key, value)
        return mock

    @patch("app.services.transition_service.get_settings")
    def test_enabled_returns_transitions_and_durations(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(transitions_enabled=True)

        transitions, durations = compute_transitions_for_clips(5)

        assert transitions is not None
        assert durations is not None
        assert len(transitions) == 4
        assert len(durations) == 4

    @patch("app.services.transition_service.get_settings")
    def test_disabled_returns_none_none(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(transitions_enabled=False)

        transitions, durations = compute_transitions_for_clips(5)

        assert transitions is None
        assert durations is None

    @patch("app.services.transition_service.get_settings")
    def test_dissolve_style_returns_all_dissolve(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(transition_style="dissolve")

        transitions, durations = compute_transitions_for_clips(4)

        assert transitions is not None
        assert len(transitions) == 3
        assert all(t == "dissolve" for t in transitions)

    @patch("app.services.transition_service.get_settings")
    def test_auto_style_returns_cycle_order(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(transition_style="auto")

        transitions, durations = compute_transitions_for_clips(6)

        assert transitions == list(_AUTO_CYCLE[:5])

    @patch("app.services.transition_service.get_settings")
    def test_custom_duration_params(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(
            transition_duration=0.5,
            transition_duration_min=0.3,
            transition_duration_max=0.6,
        )

        transitions, durations = compute_transitions_for_clips(4)

        assert durations is not None
        assert len(durations) == 3
        # First: 0.5*0.7=0.35 (above min 0.3), last: 0.5*1.5=0.75 clamped to 0.6
        assert durations[0] == 0.35
        assert durations[1] == 0.5
        assert durations[-1] == 0.6

    @patch("app.services.transition_service.get_settings")
    def test_single_clip_returns_empty_lists(self, mock_get_settings):
        mock_get_settings.return_value = self._mock_settings(transitions_enabled=True)

        transitions, durations = compute_transitions_for_clips(1)

        assert transitions == []
        assert durations == []

    @patch("app.services.transition_service.get_settings")
    def test_settings_missing_attributes_uses_defaults(self, mock_get_settings):
        # Simulate settings object without transition attributes (getattr defaults)
        mock = MagicMock(spec=[])
        mock_get_settings.return_value = mock

        transitions, durations = compute_transitions_for_clips(4)

        # transitions_enabled defaults to True, style defaults to "auto"
        assert transitions is not None
        assert len(transitions) == 3
        assert transitions[0] == _AUTO_CYCLE[0]
