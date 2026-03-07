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
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from loguru import logger

from app.core.config import get_settings
from app.security.sanitizers import validate_file_path

settings = get_settings()

# Target resolutions
RESOLUTION_SHORT = (1080, 1920)  # 9:16
RESOLUTION_LONG = (1920, 1080)  # 16:9


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


def normalize_audio(input_path: Path) -> Path:
    """Normalize audio loudness to -14 LUFS (YouTube's standard).

    Uses FFmpeg's loudnorm filter for EBU R128 loudness normalization.
    Replaces the file in-place via a temporary file.

    Args:
        input_path: Path to the MP3/audio file.

    Returns:
        The same input_path (file is replaced in-place).
    """
    temp_path = input_path.with_suffix(".norm.mp3")

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            "loudnorm=I=-14:TP=-1.0:LRA=11",
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(temp_path),
        ],
        description="normalize audio loudness",
    )

    # Replace original with normalized version
    temp_path.replace(input_path)
    logger.info("Audio normalized to -14 LUFS — {}", input_path.name)
    return input_path


def probe_duration(file_path: Path) -> float:
    """Get the duration of a media file in seconds."""
    result = _run_ffmpeg(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
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
    """Scale a clip to fit inside target dimensions with black padding.

    Uses near-lossless CRF to preserve quality for intermediate files
    that will be concatenated and re-encoded in the final pass.
    """
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "10",
            "-pix_fmt",
            "yuv420p",
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

    try:
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c:v",
                "copy",  # stream copy — no re-encode since clips are same codec/resolution
                "-an",
                str(output_path),
            ],
            description="concatenate clips",
        )
    finally:
        concat_list.unlink(missing_ok=True)
    logger.info("Concatenated {} clips → {}", len(clip_paths), output_path.name)
    return output_path


def _concat_with_audio(clip_paths: list[Path], output_path: Path) -> Path:
    """Concatenate clips that each have audio tracks (e.g. narrated + outro).

    Uses FFmpeg's filter_complex concat filter (not the concat demuxer)
    so inputs with different codecs/parameters are handled correctly.
    """
    n = len(clip_paths)

    # Build input args
    input_args: list[str] = []
    for p in clip_paths:
        input_args.extend(["-i", str(p)])

    # Build filter_complex: [0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]
    filter_parts = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_complex = f"{filter_parts}concat=n={n}:v=1:a=1[outv][outa]"

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        description="concatenate with audio (filter)",
    )
    logger.info("Concatenated {} clips (with audio) → {}", n, output_path.name)
    return output_path


def overlay_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Merge a video track with a TTS audio track.

    If video is shorter than audio, the video loops to fill the narration.
    If video is longer, audio is padded with silence to match video length.
    """
    video_dur = probe_duration(video_path)
    audio_dur = probe_duration(audio_path)

    if video_dur >= audio_dur:
        # Video is long enough — pad audio with silence to match
        audio_filter = f"apad=whole_dur={video_dur}"
        duration_flag = ["-t", str(video_dur)]
        loop_flag: list[str] = []
    else:
        # Audio is longer — loop video to fill entire narration
        audio_filter = None
        duration_flag = ["-t", str(audio_dur)]
        loop_flag = ["-stream_loop", "-1"]

    args = [
        "ffmpeg",
        "-y",
        *loop_flag,
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-level",
        "4.2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]

    if audio_filter:
        args.extend(["-af", audio_filter])

    args.extend(duration_flag)
    args.extend(["-movflags", "+faststart", str(output_path)])

    _run_ffmpeg(args, description="overlay audio")

    logger.info(
        "Audio overlaid — video={} audio={} → {}",
        video_path.name,
        audio_path.name,
        output_path.name,
    )
    return output_path


def burn_captions(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
) -> Path:
    """
    Burn ASS subtitles into a video using FFmpeg's ass filter.

    Args:
        video_path: Path to the input video (e.g. narrated.mp4).
        ass_path: Path to the ASS subtitle file.
        output_path: Path for the captioned output video.

    Returns:
        Path to the captioned video.
    """
    # FFmpeg's ass filter on Windows can't handle drive-letter colons (C:) in paths.
    # The \: escaping doesn't work on Windows FFmpeg builds.
    # Fix: copy ASS to temp dir, run FFmpeg with cwd=tmp_dir, use bare filename.
    tmp_dir = tempfile.mkdtemp(prefix="ff_ass_")
    try:
        tmp_ass = Path(tmp_dir) / "captions.ass"
        shutil.copy2(ass_path, tmp_ass)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path.resolve()),
            "-vf",
            "ass=captions.ass",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path.resolve()),
        ]
        logger.debug("FFmpeg [burn captions]: {}", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=tmp_dir,
        )
        if result.returncode != 0:
            logger.error("FFmpeg FAILED [burn captions]:\n{}", result.stderr[-2000:])
            raise RuntimeError(
                f"FFmpeg 'burn captions' failed: {result.stderr[-500:]}"
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info("Captions burned — {} → {}", video_path.name, output_path.name)
    return output_path


def assemble_video(
    clip_paths: list[Path],
    audio_path: Path,
    video_format: str = "short",
    project_id: str | None = None,
    caption_ass_path: Path | None = None,
) -> Path:
    """
    Full assembly pipeline:
      1. Scale/pad each clip to target resolution
      2. Concatenate all clips
      3. Overlay TTS audio
      4. Burn captions (if ASS file provided)
      5. Append outro
      6. Return path to final output MP4

    Args:
        clip_paths: Downloaded B-roll clip file paths.
        audio_path: TTS audio file path.
        video_format: "short" (9:16) or "long" (16:9).
        project_id: Optional UUID for naming the output.
        caption_ass_path: Optional ASS subtitle file for caption burn-in.

    Returns:
        Path to the assembled final video.

    Raises:
        ValueError: If paths are invalid or attempt path traversal
    """
    if not clip_paths:
        raise ValueError("No video clips provided for assembly")

    # Validate all input paths to prevent path traversal
    media_root = settings.media_path
    for clip_path in clip_paths:
        validate_file_path(clip_path, media_root)

    audio_path = validate_file_path(audio_path, media_root)

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

    # 1. Scale each AI clip (strips audio — TTS replaces it)
    scaled_paths: list[Path] = []
    for i, clip in enumerate(clip_paths):
        scaled = work_dir / f"scaled_{i:03d}.mp4"
        scale_and_pad(clip, scaled, w, h)
        scaled_paths.append(scaled)

    # 2. Concatenate AI clips only (no audio)
    concat_path = work_dir / "concat.mp4"
    concatenate_clips(scaled_paths, concat_path)

    # 3. Overlay TTS audio on AI content only
    narrated_path = work_dir / "narrated.mp4"
    overlay_audio(concat_path, audio_path, narrated_path)

    # 4. Burn captions if ASS subtitle file provided
    if caption_ass_path is not None:
        captioned_path = work_dir / "captioned.mp4"
        burn_captions(narrated_path, caption_ass_path, captioned_path)
        narrated_path = captioned_path  # downstream uses captioned version

    # 5. Append outro clip with its own audio (like/subscribe)
    outro_path = Path(settings.outro_video_path).resolve()
    final_name = f"final_{tag}.mp4"
    final_path = output_dir / final_name

    if video_format == "short" and outro_path.exists():
        scaled_outro = work_dir / "scaled_outro_av.mp4"
        # Scale outro but KEEP its original audio
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(outro_path),
                "-vf",
                (
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
                ),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "10",
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-pix_fmt",
                "yuv420p",
                str(scaled_outro),
            ],
            description="scale outro (with audio)",
        )
        logger.info("Outro clip scaled with audio — {}", outro_path.name)

        # Concatenate narrated content + outro (both have audio)
        _concat_with_audio([narrated_path, scaled_outro], final_path)
        logger.info("Narrated + outro joined → {}", final_path.name)
    else:
        # No outro — narrated video is the final output
        shutil.move(str(narrated_path), str(final_path))

    # Cleanup intermediate files
    for f in work_dir.iterdir():
        f.unlink(missing_ok=True)
    work_dir.rmdir()

    logger.info("Assembly complete → {}", final_path)
    return final_path


def generate_thumbnail(
    video_path: Path, output_path: Path | None = None, timestamp: float = 0.0
) -> Path:
    """Generate a thumbnail image from a video file.

    Args:
        video_path: Path to the video file
        output_path: Optional output path for thumbnail (defaults to video_path with .jpg extension)
        timestamp: Timestamp in seconds to extract frame from (default: 0.0 for first frame)
                  If negative, extracts from middle of video

    Returns:
        Path to the generated thumbnail JPEG

    Example:
        >>> thumbnail = generate_thumbnail(Path("video.mp4"))  # First frame
        >>> thumbnail = generate_thumbnail(Path("video.mp4"), timestamp=-1)  # Middle frame
        >>> thumbnail = generate_thumbnail(Path("video.mp4"), timestamp=5.0)  # At 5 seconds
    """
    # Validate input path
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Default output path: same directory, same name with .jpg extension
    if output_path is None:
        output_path = video_path.with_suffix(".jpg")

    # If timestamp is negative, extract from middle of video
    if timestamp < 0:
        duration = probe_duration(video_path)
        timestamp = duration / 2.0
        logger.debug(
            "Extracting thumbnail from middle of video ({}s / 2 = {}s)", duration, timestamp
        )

    # Sanitize output path
    validate_file_path(output_path, settings.media_path)

    # Extract frame using FFmpeg
    # -ss: seek to timestamp
    # -i: input file
    # -vframes 1: extract only 1 frame
    # -q:v 2: JPEG quality (2 is high quality)
    # -vf scale: resize to 1280x720 (good thumbnail size)
    args = [
        "ffmpeg",
        "-y",  # Overwrite output file
        "-ss",
        str(timestamp),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        str(output_path),
    ]

    _run_ffmpeg(args, f"generate thumbnail at {timestamp}s")

    logger.info("Thumbnail generated → {} (from {}s)", output_path, timestamp)
    return output_path
