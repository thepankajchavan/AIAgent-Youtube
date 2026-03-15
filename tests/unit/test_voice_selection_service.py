"""Unit tests for VoiceSelectionService — voice selection priority logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.voice_selection_service import (
    MOOD_VOICE_MAP,
    NICHE_VOICE_MAP,
    _get_config_voice_for_niche,
    get_voice_catalog,
    select_voice,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Create a mock Settings with sensible defaults for voice selection.

    Uses a custom side_effect on __getattr__ so that getattr(settings, attr, "")
    returns "" for any unknown voice_map_* attribute, matching real Settings behavior.
    """
    known_attrs = {
        "multi_voice_enabled": True,
        "voice_map_science": "",
        "voice_map_history": "",
        "voice_map_technology": "",
        "voice_map_motivation": "",
        "voice_map_entertainment": "",
        "voice_map_psychology": "",
        "voice_map_space": "",
        "voice_map_default": "",
        "elevenlabs_voice_id": "default-elevenlabs-id",
    }
    known_attrs.update(overrides)

    class FakeSettings:
        """Minimal settings fake that returns '' for unknown voice_map_ attrs."""
        pass

    settings = FakeSettings()
    for key, value in known_attrs.items():
        setattr(settings, key, value)
    return settings


SETTINGS_PATCH = "app.services.voice_selection_service.get_settings"


# ── TestSelectVoicePriority ──────────────────────────────────────


class TestSelectVoicePriority:
    """select_voice() follows priority: user > config > mood > niche > default."""

    @patch(SETTINGS_PATCH)
    def test_user_voice_id_takes_highest_priority(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="science", mood="energetic", user_voice_id="user-123")
        assert result == "user-123"

    @patch(SETTINGS_PATCH)
    def test_user_voice_id_overrides_config_map(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_science="config-sci-voice")
        result = select_voice(niche="science", mood="calm", user_voice_id="user-override")
        assert result == "user-override"

    @patch(SETTINGS_PATCH)
    def test_config_voice_map_takes_second_priority(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_science="config-sci-voice")
        result = select_voice(niche="science", mood="energetic")
        assert result == "config-sci-voice"

    @patch(SETTINGS_PATCH)
    def test_config_voice_map_overrides_mood_and_niche(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_history="config-hist-voice")
        result = select_voice(niche="history", mood="dramatic")
        assert result == "config-hist-voice"

    @patch(SETTINGS_PATCH)
    def test_mood_voice_map_takes_third_priority(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="science", mood="energetic")
        assert result == MOOD_VOICE_MAP["energetic"]

    @patch(SETTINGS_PATCH)
    def test_mood_overrides_niche_when_no_config(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="history", mood="calm")
        assert result == MOOD_VOICE_MAP["calm"]

    @patch(SETTINGS_PATCH)
    def test_niche_voice_map_takes_fourth_priority(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="science", mood=None)
        assert result == NICHE_VOICE_MAP["science"]

    @patch(SETTINGS_PATCH)
    def test_niche_only_without_mood(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="technology")
        assert result == NICHE_VOICE_MAP["technology"]

    @patch(SETTINGS_PATCH)
    def test_falls_back_to_config_default(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_default="config-default-voice")
        result = select_voice(niche=None, mood=None)
        assert result == "config-default-voice"

    @patch(SETTINGS_PATCH)
    def test_falls_back_to_elevenlabs_voice_id(self, mock_gs):
        mock_gs.return_value = _make_settings(
            voice_map_default="",
            elevenlabs_voice_id="elevenlabs-fallback",
        )
        result = select_voice(niche=None, mood=None)
        assert result == "elevenlabs-fallback"

    @patch(SETTINGS_PATCH)
    def test_unknown_mood_falls_through_to_niche(self, mock_gs):
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="motivation", mood="nonexistent_mood")
        assert result == NICHE_VOICE_MAP["motivation"]

    @patch(SETTINGS_PATCH)
    def test_unknown_niche_and_mood_falls_to_default(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_default="fallback-default")
        result = select_voice(niche="unknown_niche", mood="unknown_mood")
        assert result == "fallback-default"

    @patch(SETTINGS_PATCH)
    def test_unknown_niche_and_mood_falls_to_elevenlabs(self, mock_gs):
        mock_gs.return_value = _make_settings(
            voice_map_default="",
            elevenlabs_voice_id="final-fallback",
        )
        result = select_voice(niche="unknown_niche", mood="unknown_mood")
        assert result == "final-fallback"

    @patch(SETTINGS_PATCH)
    def test_all_none_uses_elevenlabs_voice_id(self, mock_gs):
        mock_gs.return_value = _make_settings(elevenlabs_voice_id="global-id")
        result = select_voice()
        assert result == "global-id"

    @patch(SETTINGS_PATCH)
    def test_empty_user_voice_id_is_not_used(self, mock_gs):
        """Empty string user_voice_id should be treated as falsy."""
        mock_gs.return_value = _make_settings()
        result = select_voice(niche="science", user_voice_id="")
        # Should fall through to mood/niche, not return ""
        assert result != ""


# ── TestNicheVoiceMap ────────────────────────────────────────────


class TestNicheVoiceMap:
    """All niches in NICHE_VOICE_MAP return valid non-empty IDs."""

    ALL_NICHES = ["science", "history", "technology", "motivation",
                  "entertainment", "psychology", "space"]

    def test_all_expected_niches_present(self):
        assert set(self.ALL_NICHES).issubset(set(NICHE_VOICE_MAP.keys()))

    @pytest.mark.parametrize("niche", ALL_NICHES)
    def test_niche_voice_id_is_nonempty_string(self, niche):
        voice_id = NICHE_VOICE_MAP[niche]
        assert isinstance(voice_id, str)
        assert len(voice_id) > 0

    def test_niche_voice_map_has_seven_entries(self):
        assert len(NICHE_VOICE_MAP) == 7


# ── TestMoodVoiceMap ─────────────────────────────────────────────


class TestMoodVoiceMap:
    """All moods in MOOD_VOICE_MAP return valid non-empty IDs."""

    ALL_MOODS = ["energetic", "calm", "dramatic", "mysterious", "dark", "epic"]

    def test_all_expected_moods_present(self):
        assert set(self.ALL_MOODS).issubset(set(MOOD_VOICE_MAP.keys()))

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_mood_voice_id_is_nonempty_string(self, mood):
        voice_id = MOOD_VOICE_MAP[mood]
        assert isinstance(voice_id, str)
        assert len(voice_id) > 0

    def test_mood_voice_map_has_six_entries(self):
        assert len(MOOD_VOICE_MAP) == 6


# ── TestGetConfigVoiceForNiche ───────────────────────────────────


class TestGetConfigVoiceForNiche:
    """_get_config_voice_for_niche checks settings.voice_map_{niche}."""

    @patch(SETTINGS_PATCH)
    def test_returns_voice_id_when_config_set(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_science="configured-voice")
        result = _get_config_voice_for_niche("science")
        assert result == "configured-voice"

    @patch(SETTINGS_PATCH)
    def test_returns_none_for_empty_config(self, mock_gs):
        mock_gs.return_value = _make_settings(voice_map_science="")
        result = _get_config_voice_for_niche("science")
        assert result is None

    @patch(SETTINGS_PATCH)
    def test_returns_none_for_unknown_niche(self, mock_gs):
        """getattr(settings, 'voice_map_unknown', '') returns '' for real Settings."""
        mock_gs.return_value = _make_settings()
        result = _get_config_voice_for_niche("unknown")
        assert result is None

    @patch(SETTINGS_PATCH)
    def test_checks_correct_attr_name(self, mock_gs):
        """Verifies the attr name is voice_map_{niche}."""
        mock_gs.return_value = _make_settings(voice_map_history="hist-voice")
        result = _get_config_voice_for_niche("history")
        assert result == "hist-voice"


# ── TestGetVoiceCatalog ──────────────────────────────────────────


class TestGetVoiceCatalog:
    """get_voice_catalog returns annotated voice list."""

    @patch("asyncio.run")
    def test_returns_list_of_dicts(self, mock_run):
        get_voice_catalog.cache_clear()

        mock_run.return_value = [
            {"voice_id": "v1", "name": "Alice"},
            {"voice_id": "v2", "name": "Bob"},
        ]
        result = get_voice_catalog()
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(v, dict) for v in result)

        get_voice_catalog.cache_clear()

    @patch("asyncio.run")
    def test_annotates_recommended_niches(self, mock_run):
        get_voice_catalog.cache_clear()

        adam_id = NICHE_VOICE_MAP["science"]
        mock_run.return_value = [
            {"voice_id": adam_id, "name": "Adam"},
            {"voice_id": "unknown-id", "name": "Unknown"},
        ]
        result = get_voice_catalog()

        adam_entry = next(v for v in result if v["voice_id"] == adam_id)
        assert "science" in adam_entry["recommended_niches"]

        unknown_entry = next(v for v in result if v["voice_id"] == "unknown-id")
        assert unknown_entry["recommended_niches"] == []

        get_voice_catalog.cache_clear()

    @patch("asyncio.run")
    def test_returns_empty_list_on_exception(self, mock_run):
        get_voice_catalog.cache_clear()

        mock_run.side_effect = RuntimeError("TTS unavailable")
        result = get_voice_catalog()
        assert result == []

        get_voice_catalog.cache_clear()

    @patch("asyncio.run")
    def test_result_is_cached(self, mock_run):
        get_voice_catalog.cache_clear()

        mock_run.return_value = [{"voice_id": "v1", "name": "Voice1"}]
        result1 = get_voice_catalog()
        result2 = get_voice_catalog()
        assert result1 is result2
        assert mock_run.call_count == 1

        get_voice_catalog.cache_clear()

    @patch("asyncio.run")
    def test_space_niche_in_recommended(self, mock_run):
        """space niche voice shows up in recommended_niches."""
        get_voice_catalog.cache_clear()

        space_id = NICHE_VOICE_MAP["space"]
        mock_run.return_value = [{"voice_id": space_id, "name": "SpaceVoice"}]
        result = get_voice_catalog()

        assert "space" in result[0]["recommended_niches"]

        get_voice_catalog.cache_clear()
