"""Unit tests for Media service with mocked FFmpeg operations."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.media_service import (
    _concat_with_audio,
    assemble_video,
    burn_captions,
    concatenate_clips,
    normalize_audio,
    overlay_audio,
    probe_duration,
    scale_and_pad,
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
        """Test complete video assembly pipeline (no outro)."""
        # Setup paths
        mock_settings = MagicMock()
        mock_settings.media_path = tmp_path
        mock_settings.output_dir = tmp_path / "output"
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
        mock_settings.outro_video_path = str(tmp_path / "nonexistent_outro.mp4")
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
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
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
