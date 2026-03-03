"""
Media Service — video assembly pipeline using FFmpeg.

Handles:
  1. Probing clip durations
  2. Concatenating multiple video clips
  3. Overlaying TTS audio onto the video track
  4. Scaling/padding to exact target resolutions (9:16 or 16:9)
  5. Final render to output MP4
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# Target resolutions
RESOLUTION_SHORT = (1080, 1920)  # 9:16
RESOLUTION_LONG = (1920, 1080)   # 16:9


def _run_ffmpeg(args: list[str], description: str) -> subprocess.CompletedProcess:
    """Execute an ffmpeg/ffprobe command and handle errors."""
    logger.debug("FFmpeg [{}]: {}", description, " ".join(args))
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        logger.error("FFmpeg FAILED [{}]:\n{}", description, result.stderr[-2000:])
        raise RuntimeError(f"FFmpeg '{description}' failed: {result.stderr[-500:]}")
    return result


def probe_duration(file_path: Path) -> float:
    """Get the duration of a media file in seconds."""
    result = _run_ffmpeg(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(file_path),
        ],
        description=f"probe {file_path.name}",
    )
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    logger.debug("{} duration: {:.2f}s", file_path.name, duration)
    return duration


def scale_and_pad(
    input_path: Path,
    output_path: Path,
    width: int,
    height: int,
) -> Path:
    """Scale a clip to fit inside target dimensions with black padding."""
    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",  # strip audio from B-roll
            str(output_path),
        ],
        description=f"scale {input_path.name}",
    )
    return output_path


def concatenate_clips(clip_paths: list[Path], output_path: Path) -> Path:
    """
    Concatenate multiple video clips into one continuous video.
    All clips must have the same resolution (call scale_and_pad first).
    """
    concat_list = output_path.parent / f"_concat_{uuid.uuid4().hex[:8]}.txt"
    with open(concat_list, "w") as f:
        for p in clip_paths:
            # FFmpeg concat demuxer needs forward slashes and escaped quotes
            f.write(f"file '{p.as_posix()}'\n")

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",
            str(output_path),
        ],
        description="concatenate clips",
    )

    concat_list.unlink(missing_ok=True)
    logger.info("Concatenated {} clips → {}", len(clip_paths), output_path.name)
    return output_path


def overlay_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Merge a video track with a TTS audio track.
    Trims the video to match audio duration (whichever is shorter).
    """
    audio_dur = probe_duration(audio_path)

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-t", str(audio_dur),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ],
        description="overlay audio",
    )

    logger.info(
        "Audio overlaid — video={} audio={} → {}",
        video_path.name,
        audio_path.name,
        output_path.name,
    )
    return output_path


def assemble_video(
    clip_paths: list[Path],
    audio_path: Path,
    video_format: str = "short",
    project_id: str | None = None,
) -> Path:
    """
    Full assembly pipeline:
      1. Scale/pad each clip to target resolution
      2. Concatenate all clips
      3. Overlay TTS audio
      4. Return path to final output MP4

    Args:
        clip_paths: Downloaded B-roll clip file paths.
        audio_path: TTS audio file path.
        video_format: "short" (9:16) or "long" (16:9).
        project_id: Optional UUID for naming the output.

    Returns:
        Path to the assembled final video.
    """
    if not clip_paths:
        raise ValueError("No video clips provided for assembly")
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    tag = project_id or uuid.uuid4().hex[:12]
    work_dir = output_dir / f"_work_{tag}"
    work_dir.mkdir(parents=True, exist_ok=True)

    w, h = RESOLUTION_SHORT if video_format == "short" else RESOLUTION_LONG

    logger.info(
        "Assembly starting — {} clips, format={} ({}x{})",
        len(clip_paths),
        video_format,
        w,
        h,
    )

    # 1. Scale each clip
    scaled_paths: list[Path] = []
    for i, clip in enumerate(clip_paths):
        scaled = work_dir / f"scaled_{i:03d}.mp4"
        scale_and_pad(clip, scaled, w, h)
        scaled_paths.append(scaled)

    # 2. Concatenate
    concat_path = work_dir / "concat.mp4"
    concatenate_clips(scaled_paths, concat_path)

    # 3. Overlay audio
    final_name = f"final_{tag}.mp4"
    final_path = output_dir / final_name
    overlay_audio(concat_path, audio_path, final_path)

    # Cleanup intermediate files
    for f in work_dir.iterdir():
        f.unlink(missing_ok=True)
    work_dir.rmdir()

    logger.info("Assembly complete → {}", final_path)
    return final_path
