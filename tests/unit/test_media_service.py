"""Unit tests for Media service with mocked FFmpeg operations."""

import pytest
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.media_service import (
    probe_duration,
    scale_and_pad,
    concatenate_clips,
    overlay_audio,
    assemble_video,
)


class TestProbeOperations:
    """Test FFmpeg probe operations."""

    def test_probe_duration_success(self, mocker):
        """Test successful duration probing."""
        # Mock ffprobe output
        mock_output = json.dumps({
            "format": {
                "duration": "12.5"
            }
        })

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

    def test_overlay_audio_success(self, mocker, tmp_path):
        """Test successful audio overlay."""
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "audio.mp3"
        output_path = tmp_path / "final.mp4"

        video_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

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
        assert "-shortest" in args  # Uses -shortest to match streams
        assert "-map" in args  # Map both video and audio

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

        # Mock all FFmpeg operations
        mocker.patch("app.services.media_service.scale_and_pad", side_effect=lambda i, o, w, h: o)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=lambda v, a, o: o)

        # Mock validate_file_path to return the path unchanged
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        result = assemble_video(
            clip_paths=[clip1, clip2],
            audio_path=audio_path,
            video_format="short",
            project_id="test123"
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
            side_effect=ValueError("Path traversal detected")
        )

        with pytest.raises(ValueError, match="Path traversal detected"):
            assemble_video(
                clip_paths=[clip1],
                audio_path=audio_path,
                video_format="short"
            )

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

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=lambda v, a, o: o)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(
            clip_paths=[clip],
            audio_path=audio,
            video_format="short"
        )

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

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=lambda v, a, o: o)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(
            clip_paths=[clip],
            audio_path=audio,
            video_format="long"
        )

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

        mocker.patch("app.services.media_service.scale_and_pad", side_effect=mock_scale_and_pad)
        mocker.patch("app.services.media_service.concatenate_clips", side_effect=lambda c, o: o)
        mocker.patch("app.services.media_service.overlay_audio", side_effect=lambda v, a, o: o)
        mocker.patch("app.services.media_service.validate_file_path", side_effect=lambda p, r: p)

        assemble_video(clip_paths=[clip], audio_path=audio)

        # Verify work directory was cleaned up
        for work_dir in work_dirs:
            if work_dir.name.startswith("_work_"):
                assert not work_dir.exists(), f"Work directory not cleaned up: {work_dir}"
