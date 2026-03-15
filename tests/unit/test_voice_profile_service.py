"""Unit tests for VoiceProfileService — mood-to-voice mapping."""

from __future__ import annotations

import dataclasses

import pytest

from app.services.voice_profile_service import (
    DEFAULT_MOOD,
    MOOD_VOICE_PROFILES,
    VoiceProfile,
    get_voice_profile_for_mood,
)

ALL_MOODS = [
    "energetic", "calm", "dramatic", "mysterious", "uplifting",
    "dark", "happy", "sad", "epic", "chill",
]


class TestVoiceProfiles:
    """All 10 moods must exist and have valid parameter ranges."""

    def test_all_10_moods_present(self):
        assert set(MOOD_VOICE_PROFILES.keys()) == set(ALL_MOODS)
        assert len(MOOD_VOICE_PROFILES) == 10

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_profile_is_voice_profile_instance(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert isinstance(profile, VoiceProfile)

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_stability_in_range(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert 0.0 <= profile.stability <= 1.0, (
            f"{mood}: stability={profile.stability} out of [0.0, 1.0]"
        )

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_similarity_boost_in_range(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert 0.0 <= profile.similarity_boost <= 1.0, (
            f"{mood}: similarity_boost={profile.similarity_boost} out of [0.0, 1.0]"
        )

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_style_in_range(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert 0.0 <= profile.style <= 1.0, (
            f"{mood}: style={profile.style} out of [0.0, 1.0]"
        )

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_speed_in_range(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert 0.8 <= profile.speed <= 1.2, (
            f"{mood}: speed={profile.speed} out of [0.8, 1.2]"
        )

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_description_is_nonempty_string(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert isinstance(profile.description, str)
        assert len(profile.description) > 0


class TestGetVoiceProfile:
    """get_voice_profile_for_mood returns correct profile or falls back."""

    @pytest.mark.parametrize("mood", ALL_MOODS)
    def test_known_mood_returns_correct_profile(self, mood):
        result = get_voice_profile_for_mood(mood)
        expected = MOOD_VOICE_PROFILES[mood]
        assert result is expected

    def test_unknown_mood_falls_back_to_uplifting(self):
        result = get_voice_profile_for_mood("nonexistent_mood")
        expected = MOOD_VOICE_PROFILES[DEFAULT_MOOD]
        assert result is expected

    def test_empty_string_falls_back_to_uplifting(self):
        result = get_voice_profile_for_mood("")
        assert result is MOOD_VOICE_PROFILES[DEFAULT_MOOD]

    def test_case_sensitive_unknown_falls_back(self):
        # "Energetic" (capitalized) is not a key — should fall back
        result = get_voice_profile_for_mood("Energetic")
        assert result is MOOD_VOICE_PROFILES[DEFAULT_MOOD]

    def test_default_mood_is_uplifting(self):
        assert DEFAULT_MOOD == "uplifting"
        assert DEFAULT_MOOD in MOOD_VOICE_PROFILES

    def test_fallback_profile_has_valid_values(self):
        profile = get_voice_profile_for_mood("totally_unknown")
        assert 0.0 <= profile.stability <= 1.0
        assert 0.0 <= profile.similarity_boost <= 1.0
        assert 0.0 <= profile.style <= 1.0
        assert 0.8 <= profile.speed <= 1.2


class TestExpressiveMoods:
    """Expressive moods use lower stability; subdued moods use higher."""

    @pytest.mark.parametrize("mood", ["energetic", "dramatic", "epic"])
    def test_expressive_moods_have_low_stability(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert profile.stability < 0.5, (
            f"{mood}: stability={profile.stability} should be < 0.5 for expressive mood"
        )

    @pytest.mark.parametrize("mood", ["calm", "chill", "sad"])
    def test_subdued_moods_have_high_stability(self, mood):
        profile = MOOD_VOICE_PROFILES[mood]
        assert profile.stability > 0.5, (
            f"{mood}: stability={profile.stability} should be > 0.5 for subdued mood"
        )

    def test_energetic_has_fast_speed(self):
        profile = MOOD_VOICE_PROFILES["energetic"]
        assert profile.speed >= 1.0, "energetic mood should speak fast"

    def test_calm_has_slow_speed(self):
        profile = MOOD_VOICE_PROFILES["calm"]
        assert profile.speed < 1.0, "calm mood should speak slowly"

    def test_epic_has_high_style(self):
        profile = MOOD_VOICE_PROFILES["epic"]
        assert profile.style >= 0.7, "epic mood should have high style exaggeration"

    def test_chill_has_low_style(self):
        profile = MOOD_VOICE_PROFILES["chill"]
        assert profile.style <= 0.35, "chill mood should have low style exaggeration"


class TestProfileImmutability:
    """VoiceProfile is a frozen dataclass — fields cannot be modified."""

    def test_cannot_modify_stability(self):
        profile = MOOD_VOICE_PROFILES["energetic"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.stability = 0.99

    def test_cannot_modify_similarity_boost(self):
        profile = MOOD_VOICE_PROFILES["calm"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.similarity_boost = 0.99

    def test_cannot_modify_style(self):
        profile = MOOD_VOICE_PROFILES["dramatic"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.style = 0.99

    def test_cannot_modify_speed(self):
        profile = MOOD_VOICE_PROFILES["happy"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.speed = 0.99

    def test_cannot_modify_description(self):
        profile = MOOD_VOICE_PROFILES["epic"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.description = "tampered"

    def test_frozen_flag_is_set(self):
        assert dataclasses.fields(VoiceProfile) is not None
        # Confirm the class itself is frozen
        assert VoiceProfile.__dataclass_params__.frozen is True
