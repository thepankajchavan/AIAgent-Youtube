"""Unit tests for Beat TTS Service — per-beat voice expressiveness."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.beat_tts_service import (
    BEAT_EXPRESSIVENESS,
    BeatTTSParams,
    _clamp,
    _concatenate_audio_segments,
    _split_sentences,
    apply_beat_expressiveness,
    classify_script_beats,
    generate_speech_per_beat,
)
from app.services.voice_profile_service import VoiceProfile


# ── Helpers ──────────────────────────────────────────────────────


def _make_voice_profile(**overrides) -> VoiceProfile:
    """Create a VoiceProfile with sensible defaults, overridable."""
    defaults = {
        "stability": 0.50,
        "similarity_boost": 0.80,
        "style": 0.55,
        "speed": 1.00,
        "description": "test profile",
    }
    defaults.update(overrides)
    return VoiceProfile(**defaults)


# ── TestClamp ────────────────────────────────────────────────────


class TestClamp:
    """Test the _clamp utility function."""

    def test_value_within_range(self):
        """Value inside range is returned unchanged."""
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_value_at_minimum(self):
        """Value at min boundary is returned unchanged."""
        assert _clamp(0.0, 0.0, 1.0) == 0.0

    def test_value_at_maximum(self):
        """Value at max boundary is returned unchanged."""
        assert _clamp(1.0, 0.0, 1.0) == 1.0

    def test_value_below_minimum(self):
        """Value below min is clamped to min."""
        assert _clamp(-0.5, 0.0, 1.0) == 0.0

    def test_value_above_maximum(self):
        """Value above max is clamped to max."""
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_custom_range(self):
        """Works with non-standard min/max bounds."""
        assert _clamp(0.05, 0.1, 1.0) == 0.1
        assert _clamp(1.5, 0.1, 1.0) == 1.0
        assert _clamp(0.5, 0.1, 1.0) == 0.5


# ── TestSplitSentences ──────────────────────────────────────────


class TestSplitSentences:
    """Test _split_sentences text splitting logic."""

    def test_paragraph_splits(self):
        """Text with 3+ blank-line-separated paragraphs splits by paragraph."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = _split_sentences(text)
        assert len(result) == 3
        assert result[0] == "First paragraph."
        assert result[1] == "Second paragraph."
        assert result[2] == "Third paragraph."

    def test_many_paragraphs(self):
        """Multiple paragraphs are all returned."""
        text = "A.\n\nB.\n\nC.\n\nD.\n\nE."
        result = _split_sentences(text)
        assert len(result) == 5

    def test_sentence_splits_when_few_paragraphs(self):
        """Falls back to sentence splitting when fewer than 3 paragraphs."""
        text = "First sentence. Second sentence. Third sentence."
        result = _split_sentences(text)
        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[1] == "Second sentence."
        assert result[2] == "Third sentence."

    def test_sentence_splits_with_exclamation(self):
        """Splits on exclamation marks."""
        text = "Wow! That is great! Amazing!"
        result = _split_sentences(text)
        assert len(result) == 3

    def test_sentence_splits_with_question(self):
        """Splits on question marks."""
        text = "What happened? Nobody knows. Strange?"
        result = _split_sentences(text)
        assert len(result) == 3

    def test_single_line_no_split(self):
        """Single sentence returns one element."""
        text = "Just a single sentence"
        result = _split_sentences(text)
        assert len(result) == 1
        assert result[0] == "Just a single sentence"

    def test_single_sentence_with_period(self):
        """Single sentence with period returns one element."""
        text = "Only one sentence here."
        result = _split_sentences(text)
        assert len(result) == 1
        assert result[0] == "Only one sentence here."

    def test_empty_paragraphs_filtered(self):
        """Blank paragraphs are filtered out."""
        text = "A.\n\n\n\nB.\n\n\n\nC."
        result = _split_sentences(text)
        assert len(result) == 3

    def test_two_paragraphs_fall_back_to_sentences(self):
        """Two paragraphs (< 3) trigger sentence fallback."""
        text = "First para sentence one. Sentence two.\n\nSecond para."
        result = _split_sentences(text)
        # Only 2 paragraphs, so falls back to sentence splitting on full text
        assert len(result) >= 2


# ── TestClassifyBeats ────────────────────────────────────────────


class TestClassifyBeats:
    """Test classify_script_beats beat-type assignment."""

    def test_six_segment_script(self):
        """6 segments map to hook(1) + build(3) + climax(1) + kicker(1)."""
        text = (
            "Segment one.\n\n"
            "Segment two.\n\n"
            "Segment three.\n\n"
            "Segment four.\n\n"
            "Segment five.\n\n"
            "Segment six."
        )
        beats = classify_script_beats(text)
        assert len(beats) == 6
        assert beats[0].beat_type == "hook"
        assert beats[1].beat_type == "build"
        assert beats[2].beat_type == "build"
        assert beats[3].beat_type == "build"
        assert beats[4].beat_type == "climax"
        assert beats[5].beat_type == "kicker"

    def test_six_segment_text_content(self):
        """Beat text matches the original segment text."""
        text = (
            "Opening hook.\n\n"
            "Build one.\n\n"
            "Build two.\n\n"
            "Build three.\n\n"
            "The climax.\n\n"
            "The kicker."
        )
        beats = classify_script_beats(text)
        assert beats[0].text == "Opening hook."
        assert beats[5].text == "The kicker."

    def test_two_segment_script(self):
        """2 segments map to hook + kicker (no build or climax)."""
        text = "First sentence. Second sentence."
        beats = classify_script_beats(text)
        assert len(beats) == 2
        assert beats[0].beat_type == "hook"
        assert beats[1].beat_type == "kicker"

    def test_single_segment(self):
        """Single segment maps to hook only."""
        text = "Just one sentence"
        beats = classify_script_beats(text)
        assert len(beats) == 1
        assert beats[0].beat_type == "hook"

    def test_three_segment_script(self):
        """3 segments map to hook + climax + kicker."""
        text = "First. Second. Third."
        beats = classify_script_beats(text)
        assert len(beats) == 3
        assert beats[0].beat_type == "hook"
        assert beats[1].beat_type == "climax"
        assert beats[2].beat_type == "kicker"

    def test_four_segment_script(self):
        """4 segments map to hook + build + climax + kicker."""
        text = "One.\n\nTwo.\n\nThree.\n\nFour."
        beats = classify_script_beats(text)
        assert len(beats) == 4
        assert beats[0].beat_type == "hook"
        assert beats[1].beat_type == "build"
        assert beats[2].beat_type == "climax"
        assert beats[3].beat_type == "kicker"

    def test_with_scenes_dict_input(self):
        """Scenes list with narration is used instead of sentence splitting."""
        scenes = [
            {"narration": "Hook narration."},
            {"narration": "Build narration one."},
            {"narration": "Build narration two."},
            {"narration": "Climax narration."},
            {"narration": "Kicker narration."},
        ]
        beats = classify_script_beats("unused script text", scenes=scenes)
        assert len(beats) == 5
        assert beats[0].beat_type == "hook"
        assert beats[0].text == "Hook narration."
        assert beats[1].beat_type == "build"
        assert beats[2].beat_type == "build"
        assert beats[3].beat_type == "climax"
        assert beats[4].beat_type == "kicker"

    def test_with_scenes_ignores_empty_narration(self):
        """Scenes with empty narration are filtered out."""
        scenes = [
            {"narration": "Hook."},
            {"narration": ""},
            {"narration": "Kicker."},
        ]
        beats = classify_script_beats("fallback", scenes=scenes)
        assert len(beats) == 2
        assert beats[0].beat_type == "hook"
        assert beats[1].beat_type == "kicker"

    def test_single_scene_falls_back_to_sentences(self):
        """With only 1 scene (< 2), falls back to sentence splitting."""
        scenes = [{"narration": "Only scene."}]
        text = "Sentence one. Sentence two. Sentence three."
        beats = classify_script_beats(text, scenes=scenes)
        # len(scenes) < 2, so sentence fallback is used
        assert len(beats) == 3

    def test_empty_text_returns_single_hook(self):
        """Empty segments list returns the full text as a single hook beat."""
        # _split_sentences on text with no punctuation and no paragraphs
        text = "  "
        beats = classify_script_beats(text)
        # segments will be empty -> fallback returns single BeatTTSParams
        assert len(beats) == 1
        assert beats[0].beat_type == "hook"

    def test_initial_params_are_zero(self):
        """Beat params (stability, similarity_boost, style) start at 0.0."""
        text = "First. Second. Third."
        beats = classify_script_beats(text)
        for beat in beats:
            assert beat.stability == 0.0
            assert beat.similarity_boost == 0.0
            assert beat.style == 0.0


# ── TestApplyBeatExpressiveness ──────────────────────────────────


class TestApplyBeatExpressiveness:
    """Test apply_beat_expressiveness multiplier logic."""

    def test_hook_has_lower_stability_than_build(self):
        """Hook reduces stability (more expressive), build increases it."""
        profile = _make_voice_profile(stability=0.50, style=0.55)
        hook_params = apply_beat_expressiveness(profile, "hook")
        build_params = apply_beat_expressiveness(profile, "build")
        assert hook_params["stability"] < build_params["stability"]

    def test_climax_has_highest_style(self):
        """Climax has the highest style multiplier (1.40)."""
        profile = _make_voice_profile(style=0.50)
        hook_params = apply_beat_expressiveness(profile, "hook")
        build_params = apply_beat_expressiveness(profile, "build")
        climax_params = apply_beat_expressiveness(profile, "climax")
        kicker_params = apply_beat_expressiveness(profile, "kicker")
        assert climax_params["style"] >= hook_params["style"]
        assert climax_params["style"] >= build_params["style"]
        assert climax_params["style"] >= kicker_params["style"]

    def test_similarity_boost_unchanged(self):
        """similarity_boost is passed through from base profile unchanged."""
        profile = _make_voice_profile(similarity_boost=0.85)
        for beat_type in ("hook", "build", "climax", "kicker"):
            params = apply_beat_expressiveness(profile, beat_type)
            assert params["similarity_boost"] == 0.85

    def test_stability_clamped_to_min(self):
        """Very low base stability * low multiplier is clamped to 0.1."""
        profile = _make_voice_profile(stability=0.10)
        # hook mult is 0.75 -> 0.10 * 0.75 = 0.075, clamped to 0.1
        params = apply_beat_expressiveness(profile, "hook")
        assert params["stability"] == 0.1

    def test_stability_clamped_to_max(self):
        """High base stability * high multiplier is clamped to 1.0."""
        profile = _make_voice_profile(stability=0.95)
        # build mult is 1.10 -> 0.95 * 1.10 = 1.045, clamped to 1.0
        params = apply_beat_expressiveness(profile, "build")
        assert params["stability"] == 1.0

    def test_style_clamped_to_min(self):
        """Style is clamped to minimum 0.0."""
        profile = _make_voice_profile(style=0.0)
        # Any multiplier * 0.0 = 0.0, which is the min
        params = apply_beat_expressiveness(profile, "hook")
        assert params["style"] == 0.0

    def test_style_clamped_to_max(self):
        """Very high base style * high multiplier is clamped to 1.0."""
        profile = _make_voice_profile(style=0.90)
        # climax mult is 1.40 -> 0.90 * 1.40 = 1.26, clamped to 1.0
        params = apply_beat_expressiveness(profile, "climax")
        assert params["style"] == 1.0

    def test_exact_hook_multipliers(self):
        """Hook applies correct multipliers: stability*0.75, style*1.30."""
        profile = _make_voice_profile(stability=0.60, style=0.50)
        params = apply_beat_expressiveness(profile, "hook")
        assert params["stability"] == pytest.approx(0.60 * 0.75, abs=1e-6)
        assert params["style"] == pytest.approx(0.50 * 1.30, abs=1e-6)

    def test_exact_build_multipliers(self):
        """Build applies correct multipliers: stability*1.10, style*0.85."""
        profile = _make_voice_profile(stability=0.50, style=0.50)
        params = apply_beat_expressiveness(profile, "build")
        assert params["stability"] == pytest.approx(0.50 * 1.10, abs=1e-6)
        assert params["style"] == pytest.approx(0.50 * 0.85, abs=1e-6)

    def test_exact_climax_multipliers(self):
        """Climax applies correct multipliers: stability*0.70, style*1.40."""
        profile = _make_voice_profile(stability=0.50, style=0.50)
        params = apply_beat_expressiveness(profile, "climax")
        assert params["stability"] == pytest.approx(0.50 * 0.70, abs=1e-6)
        assert params["style"] == pytest.approx(0.50 * 1.40, abs=1e-6)

    def test_exact_kicker_multipliers(self):
        """Kicker applies correct multipliers: stability*0.85, style*1.15."""
        profile = _make_voice_profile(stability=0.50, style=0.50)
        params = apply_beat_expressiveness(profile, "kicker")
        assert params["stability"] == pytest.approx(0.50 * 0.85, abs=1e-6)
        assert params["style"] == pytest.approx(0.50 * 1.15, abs=1e-6)

    def test_unknown_beat_type_defaults_to_build(self):
        """Unknown beat type falls back to build multipliers."""
        profile = _make_voice_profile(stability=0.50, style=0.50)
        params = apply_beat_expressiveness(profile, "unknown_type")
        build_params = apply_beat_expressiveness(profile, "build")
        assert params == build_params

    def test_return_dict_has_expected_keys(self):
        """Returned dict has exactly stability, similarity_boost, style."""
        profile = _make_voice_profile()
        params = apply_beat_expressiveness(profile, "hook")
        assert set(params.keys()) == {"stability", "similarity_boost", "style"}


# ── TestConcatenateAudio ─────────────────────────────────────────


class TestConcatenateAudio:
    """Test _concatenate_audio_segments with mocked subprocess."""

    @patch("app.services.beat_tts_service.subprocess.run")
    def test_ffmpeg_called_with_correct_args(self, mock_run, tmp_path):
        """FFmpeg is invoked with concat demuxer and correct flags."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        seg1 = tmp_path / "seg1.mp3"
        seg2 = tmp_path / "seg2.mp3"
        seg1.write_bytes(b"audio1")
        seg2.write_bytes(b"audio2")
        output = tmp_path / "output.mp3"

        _concatenate_audio_segments([seg1, seg2], output)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "-f" in cmd
        assert cmd[cmd.index("-f") + 1] == "concat"
        assert "-safe" in cmd
        assert cmd[cmd.index("-safe") + 1] == "0"
        assert "-c" in cmd
        assert cmd[cmd.index("-c") + 1] == "copy"
        assert str(output) == cmd[-1]

    @patch("app.services.beat_tts_service.subprocess.run")
    def test_concat_file_written_correctly(self, mock_run, tmp_path):
        """The concat list file contains proper file entries."""
        written_content = {}

        def capture_run(cmd, **kwargs):
            # Read the concat file before it gets cleaned up
            concat_path = cmd[cmd.index("-i") + 1]
            with open(concat_path, "r") as f:
                written_content["data"] = f.read()
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = capture_run

        seg1 = tmp_path / "seg1.mp3"
        seg2 = tmp_path / "seg2.mp3"
        seg1.write_bytes(b"a")
        seg2.write_bytes(b"b")
        output = tmp_path / "output.mp3"

        _concatenate_audio_segments([seg1, seg2], output)

        content = written_content["data"]
        assert "file '" in content
        # Both segments should be referenced (with forward slashes)
        assert "seg1.mp3" in content
        assert "seg2.mp3" in content

    @patch("app.services.beat_tts_service.subprocess.run")
    def test_concat_file_cleaned_up(self, mock_run, tmp_path):
        """The temporary concat list file is cleaned up after FFmpeg runs."""
        concat_path_holder = {}

        def capture_run(cmd, **kwargs):
            concat_path_holder["path"] = cmd[cmd.index("-i") + 1]
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = capture_run

        seg1 = tmp_path / "seg1.mp3"
        seg2 = tmp_path / "seg2.mp3"
        seg1.write_bytes(b"a")
        seg2.write_bytes(b"b")
        output = tmp_path / "output.mp3"

        _concatenate_audio_segments([seg1, seg2], output)

        # The temp concat file should have been deleted
        assert not Path(concat_path_holder["path"]).exists()

    @patch("app.services.beat_tts_service.subprocess.run")
    def test_ffmpeg_failure_raises_runtime_error(self, mock_run, tmp_path):
        """RuntimeError is raised when FFmpeg returns non-zero exit code."""
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Error: something went wrong"
        )

        seg1 = tmp_path / "seg1.mp3"
        seg2 = tmp_path / "seg2.mp3"
        seg1.write_bytes(b"a")
        seg2.write_bytes(b"b")
        output = tmp_path / "output.mp3"

        with pytest.raises(RuntimeError, match="Audio concatenation failed"):
            _concatenate_audio_segments([seg1, seg2], output)

    def test_single_segment_copies_instead_of_concat(self, tmp_path):
        """Single segment is copied directly, no FFmpeg call."""
        seg1 = tmp_path / "seg1.mp3"
        seg1.write_bytes(b"audio_data_here")
        output = tmp_path / "output.mp3"

        with patch("app.services.beat_tts_service.subprocess.run") as mock_run:
            result = _concatenate_audio_segments([seg1], output)

            mock_run.assert_not_called()
            assert result == output
            assert output.read_bytes() == b"audio_data_here"

    @patch("app.services.beat_tts_service.subprocess.run")
    def test_timeout_passed_to_subprocess(self, mock_run, tmp_path):
        """subprocess.run is called with timeout=60."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        seg1 = tmp_path / "seg1.mp3"
        seg2 = tmp_path / "seg2.mp3"
        seg1.write_bytes(b"a")
        seg2.write_bytes(b"b")
        output = tmp_path / "output.mp3"

        _concatenate_audio_segments([seg1, seg2], output)

        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 60


# ── TestGenerateSpeechPerBeat ────────────────────────────────────


class TestGenerateSpeechPerBeat:
    """Test generate_speech_per_beat full pipeline with mocked TTS."""

    @pytest.mark.asyncio
    async def test_calls_generate_speech_per_beat_count(self, tmp_path):
        """generate_speech is called once per beat."""
        script = "Hook line.\n\nBuild line.\n\nClimax line.\n\nKicker line."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        call_index = {"i": 0}
        async def mock_gen_speech(**kwargs):
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ) as mock_speech,
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(script, mood="uplifting", output_dir=tmp_path)

            assert mock_speech.call_count == 4

    @pytest.mark.asyncio
    async def test_different_params_per_beat(self, tmp_path):
        """Each beat type gets different stability/style params."""
        script = "Hook. Build. Climax. Kicker."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        captured_calls = []
        call_index = {"i": 0}

        async def mock_gen_speech(**kwargs):
            captured_calls.append(kwargs)
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(script, mood="uplifting", output_dir=tmp_path)

            assert len(captured_calls) == 4

            # hook (index 0) has lower stability than build (index 1)
            assert captured_calls[0]["stability"] < captured_calls[1]["stability"]

            # climax (index 2) has highest style
            climax_style = captured_calls[2]["style"]
            for i, c in enumerate(captured_calls):
                if i != 2:
                    assert climax_style >= c["style"]

    @pytest.mark.asyncio
    async def test_concatenation_called_with_segment_paths(self, tmp_path):
        """_concatenate_audio_segments receives all segment paths."""
        script = "First.\n\nSecond.\n\nThird."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        call_index = {"i": 0}
        segment_paths_created = []

        async def mock_gen_speech(**kwargs):
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            segment_paths_created.append(path)
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ) as mock_concat,
        ):
            await generate_speech_per_beat(script, mood="uplifting", output_dir=tmp_path)

            mock_concat.assert_called_once()
            passed_paths = mock_concat.call_args[0][0]
            assert len(passed_paths) == 3
            assert passed_paths == segment_paths_created

    @pytest.mark.asyncio
    async def test_uses_mood_for_voice_profile(self, tmp_path):
        """get_voice_profile_for_mood is called with the provided mood."""
        script = "One. Two. Three."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        call_index = {"i": 0}
        async def mock_gen_speech(**kwargs):
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ),
            patch(
                "app.services.beat_tts_service.get_voice_profile_for_mood",
                return_value=_make_voice_profile(),
            ) as mock_get_profile,
        ):
            await generate_speech_per_beat(
                script, mood="dramatic", output_dir=tmp_path
            )

            mock_get_profile.assert_called_once_with("dramatic")

    @pytest.mark.asyncio
    async def test_fallback_on_tts_failure(self, tmp_path):
        """Falls back to single TTS call when per-beat generation fails."""
        script = "First.\n\nSecond.\n\nThird."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        fallback_path = tmp_path / "fallback.mp3"
        fallback_path.write_bytes(b"fallback_audio")

        call_count = {"n": 0}

        async def mock_gen_speech(**kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise RuntimeError("TTS API failed")
            # Fallback call should succeed
            return fallback_path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ) as mock_speech,
        ):
            result = await generate_speech_per_beat(
                script, mood="uplifting", output_dir=tmp_path
            )

            assert result == fallback_path
            # Last call should be the fallback with base profile params
            last_call = mock_speech.call_args
            assert last_call.kwargs["text"] == script

    @pytest.mark.asyncio
    async def test_output_dir_created_if_missing(self, tmp_path):
        """output_dir is created if it does not exist."""
        output_dir = tmp_path / "nonexistent" / "audio"
        script = "Single sentence"

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "default_audio"

        async def mock_gen_speech(**kwargs):
            path = output_dir / "seg.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=output_dir / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(
                script, mood="uplifting", output_dir=output_dir
            )

            assert output_dir.exists()

    @pytest.mark.asyncio
    async def test_uses_settings_audio_dir_when_none(self, tmp_path):
        """When output_dir is None, settings.audio_dir is used."""
        settings_audio_dir = tmp_path / "settings_audio"
        script = "One sentence"

        mock_settings = MagicMock()
        mock_settings.audio_dir = settings_audio_dir

        async def mock_gen_speech(**kwargs):
            path = settings_audio_dir / "seg.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=settings_audio_dir / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(
                script, mood="uplifting", output_dir=None
            )

            assert settings_audio_dir.exists()

    @pytest.mark.asyncio
    async def test_with_scenes_input(self, tmp_path):
        """Scenes input is forwarded to classify_script_beats."""
        scenes = [
            {"narration": "Hook scene."},
            {"narration": "Build scene."},
            {"narration": "Kicker scene."},
        ]

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        call_index = {"i": 0}
        captured_texts = []

        async def mock_gen_speech(**kwargs):
            captured_texts.append(kwargs.get("text", ""))
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(
                "ignored text", mood="uplifting", scenes=scenes, output_dir=tmp_path
            )

            assert len(captured_texts) == 3
            assert captured_texts[0] == "Hook scene."
            assert captured_texts[1] == "Build scene."
            assert captured_texts[2] == "Kicker scene."

    @pytest.mark.asyncio
    async def test_each_segment_gets_unique_filename(self, tmp_path):
        """Each beat segment gets a unique output_filename."""
        script = "First.\n\nSecond.\n\nThird."

        mock_settings = MagicMock()
        mock_settings.audio_dir = tmp_path / "audio"

        captured_filenames = []
        call_index = {"i": 0}

        async def mock_gen_speech(**kwargs):
            captured_filenames.append(kwargs.get("output_filename", ""))
            idx = call_index["i"]
            call_index["i"] += 1
            path = tmp_path / f"seg_{idx}.mp3"
            path.write_bytes(b"audio")
            return path

        with (
            patch(
                "app.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "app.services.beat_tts_service.generate_speech",
                side_effect=mock_gen_speech,
            ),
            patch(
                "app.services.beat_tts_service._concatenate_audio_segments",
                return_value=tmp_path / "final.mp3",
            ),
        ):
            await generate_speech_per_beat(script, mood="uplifting", output_dir=tmp_path)

            assert len(captured_filenames) == 3
            # All filenames should be unique
            assert len(set(captured_filenames)) == 3
            # Filenames should contain beat type
            assert "hook" in captured_filenames[0]
            assert "climax" in captured_filenames[1]
            assert "kicker" in captured_filenames[2]
