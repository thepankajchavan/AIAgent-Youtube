"""Test utilities and helper functions."""

from pathlib import Path
import subprocess


def create_mock_audio(path: Path, duration_seconds: float = 1.0):
    """
    Create a silent MP3 file for testing.

    Args:
        path: Output path for the MP3 file
        duration_seconds: Duration of silence (default: 1.0 second)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=duration={duration_seconds}",
        "-c:a", "libmp3lame", "-b:a", "128k", str(path)
    ], check=True, capture_output=True)


def create_mock_video(
    path: Path,
    duration_seconds: float = 1.0,
    width: int = 1080,
    height: int = 1920
):
    """
    Create a black video file for testing.

    Args:
        path: Output path for the MP4 file
        duration_seconds: Duration of video (default: 1.0 second)
        width: Video width (default: 1080 for Shorts)
        height: Video height (default: 1920 for Shorts)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=black:s={width}x{height}:d={duration_seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        str(path)
    ], check=True, capture_output=True)


def assert_video_file_valid(path: Path):
    """
    Assert video file exists and is valid.

    Args:
        path: Path to video file

    Raises:
        AssertionError: If file doesn't exist, is empty, or is invalid
    """
    assert path.exists(), f"Video file not found: {path}"
    assert path.stat().st_size > 0, f"Video file is empty: {path}"

    # Use ffprobe to validate
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path)
    ], capture_output=True, text=True)
    assert result.returncode == 0, f"Invalid video file: {path}"


def assert_audio_file_valid(path: Path):
    """
    Assert audio file exists and is valid.

    Args:
        path: Path to audio file

    Raises:
        AssertionError: If file doesn't exist, is empty, or is invalid
    """
    assert path.exists(), f"Audio file not found: {path}"
    assert path.stat().st_size > 0, f"Audio file is empty: {path}"

    # Use ffprobe to validate
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path)
    ], capture_output=True, text=True)
    assert result.returncode == 0, f"Invalid audio file: {path}"
