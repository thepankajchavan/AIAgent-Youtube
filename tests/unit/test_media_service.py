"""Unit tests for Media service with mocked FFmpeg operations."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.media_service import (
    _concat_with_audio,
    apply_ken_burns,
    assemble_video,
    burn_captions,
    concatenate_clips,
    concatenate_clips_with_crossfade,
    image_to_video_clip,
    normalize_audio,
    overlay_audio,
    probe_duration,
    scale_and_pad,
    select_ken_burns_effect,
    trim_or_loop_clip,
)


class TestProbeOperations:
    """Test FFmpeg probe operations."""

    def test_probe_duration_success(self, mocker):
        """Test successful duration probing."""
        # Mock ffprobe output
        mock_output = json.dumps({"format": {"duration": "12.5"}})

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output
        mock_result.stderr = ""

        mocker.patch("subprocess.run", return_value=mock_result)

        duration = probe_duration(Path("/fake/video.mp4"))

        assert duration == 12.5

    def test_probe_duration_failure(self, mocker):
        """Test that probe failures raise RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffprobe: error reading file"

        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            probe_duration(Path("/fake/video.mp4"))


class TestScaleAndPad:
    """Test video scaling and padding operations."""

    def test_scale_and_pad_success(self, mocker, tmp_path):
        """Test successful video scaling."""
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"

        # Create fake input
        input_path.write_bytes(b"fake_video")

        # Mock successful FFmpeg run
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        # Create fake output
        output_path.write_bytes(b"scaled_video")

        result = scale_and_pad(input_path, output_path, 1080, 1920)

        # Verify FFmpeg was called correctly
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-y" in args  # Overwrite flag
        assert str(input_path) in args
        assert str(output_path) in args
        assert any("scale=1080:1920" in arg for arg in args)
        assert any("pad=1080:1920" in arg for arg in args)

        assert result == output_path

    def test_scale_and_pad_ffmpeg_failure(self, mocker, tmp_path):
        """Test that FFmpeg errors are raised."""
        input_path = tmp_path / "input.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.write_bytes(b"fake_video")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Invalid input file"

        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            scale_and_pad(input_path, output_path, 1080, 1920)


class TestConcatenateClips:
    """Test video concatenation operations."""

    def test_concatenate_clips_success(self, mocker, tmp_path):
        """Test successful concatenation of multiple clips."""
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        output_path = tmp_path / "concat.mp4"

        # Create fake inputs
        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")

        # Mock successful FFmpeg run
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        # Create fake output
        output_path.write_bytes(b"concatenated_video")

        result = concatenate_clips([clip1, clip2], output_path)

        # Verify concat list file was created and deleted
        # (The function creates a temporary concat list)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-f" in args
        assert "concat" in args

        assert result == output_path

    def test_concatenate_clips_creates_concat_file(self, mocker, tmp_path):
        """Test that concat list file is created correctly."""
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        output_path = tmp_path / "concat.mp4"

        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")

        # Capture the concat file creation
        concat_file_content = None

        def mock_subprocess_run(args, **kwargs):
            # Find the concat list file argument
            concat_idx = args.index("-i") + 1
            concat_file = Path(args[concat_idx])
            nonlocal concat_file_content
            if concat_file.exists():
                concat_file_content = concat_file.read_text()

            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mocker.patch("subprocess.run", side_effect=mock_subprocess_run)
        output_path.write_bytes(b"output")

        concatenate_clips([clip1, clip2], output_path)

        # Verify concat file contains both clips
        assert concat_file_content is not None
        assert clip1.as_posix() in concat_file_content
        assert clip2.as_posix() in concat_file_content


class TestOverlayAudio:
    """Test audio overlay operations."""

    def test_overlay_audio_loops_when_audio_longer(self, mocker, tmp_path):
        """Test that video loops to fill audio duration when audio is longer."""
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "audio.mp3"
        output_path = tmp_path / "final.mp4"

        video_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

        # Mock probe_duration: audio (42s) longer than video (15s)
        mocker.patch(
            "app.services.media_service.probe_duration",
            side_effect=lambda p: 42.0 if p.suffix == ".mp3" else 15.0,
        )

        # Mock FFmpeg run
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        output_path.write_bytes(b"final_video")

        result = overlay_audio(video_path, audio_path, output_path)

        # Verify FFmpeg was called correctly
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert str(video_path) in args
        assert str(audio_path) in args
        assert str(output_path) in args

        # Should use -stream_loop to loop video, NOT -shortest
        assert "-stream_loop" in args
        assert "-1" in args
        assert "-shortest" not in args

        # Should set duration to audio length
        assert "-t" in args
        t_idx = args.index("-t")
        assert args[t_idx + 1] == "42.0"

        assert result == output_path

    def test_overlay_audio_pads_when_video_longer(self, mocker, tmp_path):
        """Test audio padding with apad when video is longer (outro case)."""
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "audio.mp3"
        output_path = tmp_path / "final.mp4"

        video_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

        # Mock probe_duration: video longer than audio (has outro) → uses apad
        mocker.patch(
            "app.services.media_service.probe_duration",
            side_effect=lambda p: 8.0 if p.suffix == ".mp3" else 15.0,
        )

        # Mock FFmpeg run
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        output_path.write_bytes(b"final_video")

        result = overlay_audio(video_path, audio_path, output_path)

        # Verify FFmpeg used apad instead of -shortest
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "-shortest" not in args
        assert "-af" in args
        af_idx = args.index("-af")
        assert "apad" in args[af_idx + 1]
        assert "-t" in args  # Duration flag to match video length

        assert result == output_path


class TestAssembleVideo:
    """Test full video assembly pipeline."""

    def test_assemble_video_success(self, mocker, tmp_path):
        """Test complete video assembly pipeline."""
        # Setup paths
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        # Create fake input clips
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        audio_path = tmp_path / "audio.mp3"

        clip1.write_bytes(b"clip1_data")
        clip2.write_bytes(b"clip2_data")
        audio_path.write_bytes(b"audio_data")

        # overlay_audio mock must create the output file (shutil.move needs it)
        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        # Mock all FFmpeg operations
        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips_with_crossfade", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)

        # Mock validate_file_path to return the path unchanged
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        result = assemble_video(
            clip_paths=[clip1, clip2],
            audio_path=audio_path,
            video_format="short",
            project_id="test123",
        )

        # Verify result
        assert result.name == "final_test123.mp4"
        assert result.parent == tmp_path / "output"

    def test_assemble_video_validates_paths(self, mocker, tmp_path):
        """Test that file paths are validated for security."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip1 = tmp_path / "clip1.mp4"
        audio_path = tmp_path / "audio.mp3"
        clip1.write_bytes(b"clip")
        audio_path.write_bytes(b"audio")

        # Mock validate_file_path to raise error
        mocker.patch(
            "app.services.media_service.validate_file_path",
            side_effect=ValueError("Path traversal detected"),
        )

        with pytest.raises(ValueError, match="Path traversal detected"):
            assemble_video(clip_paths=[clip1], audio_path=audio_path, video_format="short")

    def test_assemble_video_short_format_resolution(self, mocker, tmp_path):
        """Test that short format uses 9:16 resolution."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")

        # Capture scale_and_pad calls
        scale_calls = []

        def mock_scale_and_pad(input_path, output_path, width, height):
            scale_calls.append((width, height))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"scaled")
            return output_path

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(clip_paths=[clip], audio_path=audio, video_format="short")

        # Verify 9:16 resolution (1080x1920)
        assert scale_calls[0] == (1080, 1920)

    def test_assemble_video_long_format_resolution(self, mocker, tmp_path):
        """Test that long format uses 16:9 resolution."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")

        scale_calls = []

        def mock_scale_and_pad(input_path, output_path, width, height):
            scale_calls.append((width, height))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"scaled")
            return output_path

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(clip_paths=[clip], audio_path=audio, video_format="long")

        # Verify 16:9 resolution (1920x1080)
        assert scale_calls[0] == (1920, 1080)

    def test_assemble_video_no_clips_raises_error(self, mocker, tmp_path):
        """Test that empty clip list raises ValueError."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mocker.patch("app.services.media_service.settings", mock_settings)

        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"audio")

        with pytest.raises(ValueError, match="No video clips provided"):
            assemble_video(clip_paths=[], audio_path=audio_path)

    def test_assemble_video_missing_audio_raises_error(self, mocker, tmp_path):
        """Test that missing audio file raises FileNotFoundError."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"clip")
        audio_path = tmp_path / "nonexistent_audio.mp3"

        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            assemble_video(clip_paths=[clip], audio_path=audio_path)

    def test_assemble_video_cleans_up_intermediate_files(self, mocker, tmp_path):
        """Test that intermediate work files are cleaned up."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")

        # Track work directory creation
        work_dirs = []

        def mock_scale_and_pad(input_path, output_path, width, height):
            work_dir = output_path.parent
            work_dirs.append(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"scaled")
            return output_path

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(clip_paths=[clip], audio_path=audio)

        # Verify work directory was cleaned up
        for work_dir in work_dirs:
            if work_dir.name.startswith("_work_"):
                assert not work_dir.exists(), f"Work directory not cleaned up: {work_dir}"


class TestConcatWithAudio:
    """Test audio+video concatenation (narrated + outro)."""

    def test_uses_filter_complex_not_demuxer(self, mocker, tmp_path):
        """Verify _concat_with_audio uses -filter_complex concat filter."""
        clip1 = tmp_path / "narrated.mp4"
        clip2 = tmp_path / "outro.mp4"
        output = tmp_path / "final.mp4"

        clip1.write_bytes(b"narrated")
        clip2.write_bytes(b"outro")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        _concat_with_audio([clip1, clip2], output)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]

        # Should use -filter_complex, NOT -f concat
        assert "-filter_complex" in args
        assert "-f" not in args

        # Filter should reference both inputs
        fc_idx = args.index("-filter_complex")
        fc_value = args[fc_idx + 1]
        assert "[0:v]" in fc_value
        assert "[0:a]" in fc_value
        assert "[1:v]" in fc_value
        assert "[1:a]" in fc_value
        assert "concat=n=2:v=1:a=1" in fc_value

        # Should map outputs
        assert "[outv]" in args
        assert "[outa]" in args

    def test_handles_three_clips(self, mocker, tmp_path):
        """Verify filter_complex scales to 3+ clips."""
        clips = [tmp_path / f"clip{i}.mp4" for i in range(3)]
        for c in clips:
            c.write_bytes(b"data")
        output = tmp_path / "output.mp4"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        _concat_with_audio(clips, output)

        args = mock_run.call_args[0][0]
        fc_idx = args.index("-filter_complex")
        fc_value = args[fc_idx + 1]
        assert "concat=n=3:v=1:a=1" in fc_value
        assert "[2:v]" in fc_value
        assert "[2:a]" in fc_value


class TestNormalizeAudio:
    """Test audio loudness normalization."""

    def test_normalize_audio_success(self, mocker, tmp_path):
        """Test successful audio normalization replaces file in-place."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"original_audio")
        norm_path = tmp_path / "audio.norm.mp3"

        def mock_ffmpeg_run(args, **kwargs):
            # Simulate FFmpeg writing the normalized file
            norm_path.write_bytes(b"normalized_audio")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run = mocker.patch("subprocess.run", side_effect=mock_ffmpeg_run)

        result = normalize_audio(audio_path)

        assert result == audio_path
        assert audio_path.read_bytes() == b"normalized_audio"
        assert not norm_path.exists()  # temp file replaced original

        # Verify FFmpeg was called with loudnorm filter
        args = mock_run.call_args[0][0]
        assert "ffmpeg" in args[0]
        assert "-af" in args
        af_idx = args.index("-af")
        assert "loudnorm" in args[af_idx + 1]
        assert "-14" in args[af_idx + 1]

    def test_normalize_audio_ffmpeg_failure(self, mocker, tmp_path):
        """Test that FFmpeg failure raises RuntimeError."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"audio")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error normalizing audio"
        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            normalize_audio(audio_path)


class TestBurnCaptions:
    """Test caption burn-in via FFmpeg."""

    def test_burn_captions_success(self, mocker, tmp_path):
        """Test successful caption burn-in."""
        video_path = tmp_path / "narrated.mp4"
        ass_path = tmp_path / "captions.ass"
        output_path = tmp_path / "captioned.mp4"

        video_path.write_bytes(b"video")
        ass_path.write_text("[Script Info]\nTitle: Test", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        result = burn_captions(video_path, ass_path, output_path)

        assert result == output_path
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert str(video_path) in args
        assert str(output_path) in args
        # Verify ass filter is present in -vf argument
        vf_idx = args.index("-vf")
        assert "ass=" in args[vf_idx + 1]
        # Audio should be copied, not re-encoded
        assert "-c:a" in args
        ca_idx = args.index("-c:a")
        assert args[ca_idx + 1] == "copy"

    def test_burn_captions_ffmpeg_failure(self, mocker, tmp_path):
        """Test that FFmpeg failure raises RuntimeError."""
        video_path = tmp_path / "narrated.mp4"
        ass_path = tmp_path / "captions.ass"
        output_path = tmp_path / "captioned.mp4"

        video_path.write_bytes(b"video")
        ass_path.write_text("[Script Info]", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error burning captions"
        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            burn_captions(video_path, ass_path, output_path)


class TestAssembleVideoWithCaptions:
    """Test assemble_video with caption support."""

    def test_with_captions(self, mocker, tmp_path):
        """Test that captions are burned when caption_ass_path is provided."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        ass_file = tmp_path / "captions.ass"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")
        ass_file.write_text("[Script Info]", encoding="utf-8")

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        def mock_burn(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"captioned")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mock_burn_fn = mocker.patch(
            "app.services.media_service.burn_captions", side_effect=mock_burn
        )
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        result = assemble_video(
            clip_paths=[clip],
            audio_path=audio,
            video_format="short",
            project_id="test_cap",
            caption_ass_path=ass_file,
        )

        # burn_captions should have been called
        mock_burn_fn.assert_called_once()
        assert result.name == "final_test_cap.mp4"

    def test_without_captions_backward_compat(self, mocker, tmp_path):
        """Test that assembly works without captions (backward compatible)."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mock_burn_fn = mocker.patch("app.services.media_service.burn_captions")
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        result = assemble_video(
            clip_paths=[clip],
            audio_path=audio,
            video_format="short",
            project_id="test_nocp",
        )

        # burn_captions should NOT have been called
        mock_burn_fn.assert_not_called()
        assert result.name == "final_test_nocp.mp4"


class TestTrimOrLoopClip:
    """Test clip duration matching via trim/loop."""

    def test_trim_clip_when_longer_than_target(self, mocker, tmp_path):
        """Clip 8s, target 5s → should trim with -t 5.0."""
        input_path = tmp_path / "clip.mp4"
        output_path = tmp_path / "trimmed.mp4"
        input_path.write_bytes(b"video")

        mocker.patch("app.services.media_service.probe_duration", return_value=8.0)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        trim_or_loop_clip(input_path, output_path, 5.0)

        args = mock_run.call_args[0][0]
        assert "-t" in args
        t_idx = args.index("-t")
        assert args[t_idx + 1] == "5.0"
        # Trim uses stream copy (no re-encode)
        assert "-c:v" in args
        cv_idx = args.index("-c:v")
        assert args[cv_idx + 1] == "copy"

    def test_loop_clip_when_shorter_than_target(self, mocker, tmp_path):
        """Clip 3s, target 7s → should loop with -stream_loop."""
        input_path = tmp_path / "clip.mp4"
        output_path = tmp_path / "looped.mp4"
        input_path.write_bytes(b"video")

        mocker.patch("app.services.media_service.probe_duration", return_value=3.0)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        trim_or_loop_clip(input_path, output_path, 7.0)

        args = mock_run.call_args[0][0]
        assert "-stream_loop" in args
        assert "-1" in args
        assert "-t" in args
        t_idx = args.index("-t")
        assert args[t_idx + 1] == "7.0"

    def test_clip_near_target_copies_as_is(self, mocker, tmp_path):
        """Clip 5.2s, target 5.0s → within 0.5s, should copy without re-encode."""
        input_path = tmp_path / "clip.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.write_bytes(b"video")

        mocker.patch("app.services.media_service.probe_duration", return_value=5.2)
        mock_run = mocker.patch("subprocess.run")

        trim_or_loop_clip(input_path, output_path, 5.0)

        # Should NOT call FFmpeg — just copies
        mock_run.assert_not_called()
        assert output_path.exists()

    def test_zero_target_raises_error(self, tmp_path):
        """Target duration 0 should raise ValueError."""
        input_path = tmp_path / "clip.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.write_bytes(b"video")

        with pytest.raises(ValueError, match="positive"):
            trim_or_loop_clip(input_path, output_path, 0)

    def test_negative_target_raises_error(self, tmp_path):
        """Negative target duration should raise ValueError."""
        input_path = tmp_path / "clip.mp4"
        output_path = tmp_path / "output.mp4"
        input_path.write_bytes(b"video")

        with pytest.raises(ValueError, match="positive"):
            trim_or_loop_clip(input_path, output_path, -5.0)


class TestSelectKenBurnsEffect:
    """Test Ken Burns effect selection for scenes."""

    def test_scene_1_uses_zoom_in(self):
        assert select_ken_burns_effect(1, 5) == "zoom_in"

    def test_scene_2_uses_diagonal_pan_rd(self):
        assert select_ken_burns_effect(2, 5) == "diagonal_pan_rd"

    def test_scene_3_uses_zoom_out_pan_left(self):
        assert select_ken_burns_effect(3, 5) == "zoom_out_pan_left"

    def test_scene_4_uses_pan_right(self):
        assert select_ken_burns_effect(4, 6) == "pan_right"

    def test_scene_5_uses_zoom_in_pan_right(self):
        assert select_ken_burns_effect(5, 6) == "zoom_in_pan_right"

    def test_scene_6_uses_diagonal_pan_lu(self):
        assert select_ken_burns_effect(6, 6) == "diagonal_pan_lu"

    def test_cycles_for_more_than_9_scenes(self):
        """Scene 10 should cycle back to scene 1's effect."""
        assert select_ken_burns_effect(10, 12) == select_ken_burns_effect(1, 5)

    def test_no_consecutive_duplicates_for_6_scenes(self):
        effects = [select_ken_burns_effect(i, 6) for i in range(1, 7)]
        for i in range(len(effects) - 1):
            assert effects[i] != effects[i + 1]


class TestApplyKenBurns:
    """Test Ken Burns FFmpeg effect generation."""

    def test_zoom_in_effect_ffmpeg_args(self, mocker, tmp_path):
        """Verify zoompan filter args for zoom_in effect."""
        image_path = tmp_path / "scene.png"
        output_path = tmp_path / "clip.mp4"
        image_path.write_bytes(b"image")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        apply_ken_burns(image_path, output_path, duration=5.0, effect="zoom_in")

        args = mock_run.call_args[0][0]
        assert args[0] == "ffmpeg"
        assert "-loop" in args
        assert "1" in args
        assert "-vf" in args

        vf_idx = args.index("-vf")
        vf_value = args[vf_idx + 1]
        assert "zoompan" in vf_value
        assert "1080x1920" in vf_value
        assert "fade=t=in" in vf_value
        assert "fade=t=out" in vf_value

    def test_duration_matches_target(self, mocker, tmp_path):
        """Verify -t flag matches requested duration."""
        image_path = tmp_path / "scene.png"
        output_path = tmp_path / "clip.mp4"
        image_path.write_bytes(b"image")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        apply_ken_burns(image_path, output_path, duration=8.5, effect="pan_left")

        args = mock_run.call_args[0][0]
        t_idx = args.index("-t")
        assert args[t_idx + 1] == "8.5"

    def test_invalid_effect_raises(self, tmp_path):
        """Unknown effect name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown Ken Burns effect"):
            apply_ken_burns(
                tmp_path / "img.png", tmp_path / "out.mp4",
                duration=5.0, effect="spin_around",
            )

    def test_zero_duration_raises(self, tmp_path):
        with pytest.raises(ValueError, match="positive"):
            apply_ken_burns(
                tmp_path / "img.png", tmp_path / "out.mp4",
                duration=0, effect="zoom_in",
            )

    def test_ffmpeg_failure_raises(self, mocker, tmp_path):
        """FFmpeg failure should raise RuntimeError."""
        image_path = tmp_path / "scene.png"
        output_path = tmp_path / "clip.mp4"
        image_path.write_bytes(b"image")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error"
        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            apply_ken_burns(image_path, output_path, duration=5.0, effect="zoom_in")


class TestImageToVideoClip:
    """Test high-level image-to-video wrapper."""

    def test_generates_output_file(self, mocker, tmp_path):
        """Test that image_to_video_clip calls apply_ken_burns with correct params."""
        image_path = tmp_path / "scene.png"
        image_path.write_bytes(b"image")

        mock_kb = mocker.patch("app.services.media_service.apply_ken_burns")

        result = image_to_video_clip(
            image_path=image_path,
            duration=5.0,
            scene_number=1,
            total_scenes=3,
            output_dir=tmp_path,
        )

        mock_kb.assert_called_once()
        call_kwargs = mock_kb.call_args
        assert call_kwargs[1]["effect"] == "zoom_in"  # scene 1
        assert call_kwargs[1]["duration"] == 5.0

    def test_scene_2_uses_diagonal_pan_effect(self, mocker, tmp_path):
        image_path = tmp_path / "scene.png"
        image_path.write_bytes(b"image")

        mock_kb = mocker.patch("app.services.media_service.apply_ken_burns")

        image_to_video_clip(
            image_path=image_path,
            duration=8.0,
            scene_number=2,
            total_scenes=5,
            output_dir=tmp_path,
        )

        call_kwargs = mock_kb.call_args
        assert call_kwargs[1]["effect"] == "diagonal_pan_rd"


class TestAssembleVideoWithSceneDurations:
    """Test that assemble_video uses scene_durations for clip matching."""

    def test_trim_or_loop_called_when_durations_provided(self, mocker, tmp_path):
        """When scene_durations is provided, trim_or_loop_clip should be called."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        audio = tmp_path / "audio.mp3"
        clip1.write_bytes(b"clip1")
        clip2.write_bytes(b"clip2")
        audio.write_bytes(b"audio")

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips_with_crossfade", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        mock_trim = mocker.patch(
            "app.services.media_service.trim_or_loop_clip",
            side_effect=lambda i, o, d: o,
        )

        assemble_video(
            clip_paths=[clip1, clip2],
            audio_path=audio,
            video_format="short",
            project_id="test_dur",
            scene_durations=[5.0, 8.0],
        )

        assert mock_trim.call_count == 2
        # Verify durations passed
        calls = mock_trim.call_args_list
        assert calls[0][0][2] == 5.0  # first clip, 5s
        assert calls[1][0][2] == 8.0  # second clip, 8s

    def test_no_trim_when_durations_not_provided(self, mocker, tmp_path):
        """Without scene_durations, trim_or_loop_clip should NOT be called."""
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mocker.patch("app.services.media_service.settings", mock_settings)

        clip = tmp_path / "clip.mp4"
        audio = tmp_path / "audio.mp3"
        clip.write_bytes(b"clip")
        audio.write_bytes(b"audio")

        def mock_overlay(v, a, o):
            o.parent.mkdir(parents=True, exist_ok=True)
            o.write_bytes(b"narrated")
            return o

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o, **kw: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=mock_overlay)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        mock_trim = mocker.patch("app.services.media_service.trim_or_loop_clip")

        assemble_video(
            clip_paths=[clip],
            audio_path=audio,
            video_format="short",
            project_id="test_nodur",
        )

        mock_trim.assert_not_called()


class TestConcatenateClipsWithCrossfade:
    """Test crossfade concatenation logic."""

    def test_single_clip_falls_back_to_simple_concat(self, mocker, tmp_path):
        """Single clip should use concatenate_clips, not xfade."""
        clip = tmp_path / "clip.mp4"
        output = tmp_path / "output.mp4"
        clip.write_bytes(b"video")

        mock_concat = mocker.patch(
            "app.services.media_service.concatenate_clips",
            side_effect=lambda c, o, **kw: o,
        )

        concatenate_clips_with_crossfade([clip], output)

        mock_concat.assert_called_once_with([clip], output)

    def test_two_clips_uses_xfade_filter(self, mocker, tmp_path):
        """Two clips should use FFmpeg xfade filter."""
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        output = tmp_path / "output.mp4"
        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")

        mocker.patch("app.services.media_service.probe_duration", return_value=5.0)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        concatenate_clips_with_crossfade([clip1, clip2], output)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "-filter_complex" in args
        fc_idx = args.index("-filter_complex")
        fc_value = args[fc_idx + 1]
        assert "xfade" in fc_value
        assert "transition=fade" in fc_value
        assert "[vout]" in fc_value

    def test_three_clips_chains_xfade_filters(self, mocker, tmp_path):
        """Three clips should chain two xfade filters."""
        clips = [tmp_path / f"clip{i}.mp4" for i in range(3)]
        for c in clips:
            c.write_bytes(b"video")
        output = tmp_path / "output.mp4"

        mocker.patch("app.services.media_service.probe_duration", return_value=6.0)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run = mocker.patch("subprocess.run", return_value=mock_result)

        concatenate_clips_with_crossfade(clips, output)

        args = mock_run.call_args[0][0]
        fc_idx = args.index("-filter_complex")
        fc_value = args[fc_idx + 1]
        # Should have 2 xfade filters chained with ;
        assert fc_value.count("xfade") == 2
        assert ";" in fc_value

    def test_ffmpeg_failure_raises(self, mocker, tmp_path):
        """FFmpeg xfade failure should raise RuntimeError."""
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        output = tmp_path / "output.mp4"
        clip1.write_bytes(b"video1")
        clip2.write_bytes(b"video2")

        mocker.patch("app.services.media_service.probe_duration", return_value=5.0)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "xfade filter error"
        mocker.patch("subprocess.run", return_value=mock_result)

        with pytest.raises(RuntimeError, match="FFmpeg"):
            concatenate_clips_with_crossfade([clip1, clip2], output)
