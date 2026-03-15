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
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.error("Failed to parse duration from ffprobe output for {}: {}", file_path.name, e)
        raise ValueError(f"Invalid ffprobe output for {file_path.name}: {e}") from e
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


def trim_or_loop_clip(
    input_path: Path,
    output_path: Path,
    target_duration: float,
) -> Path:
    """Adjust a clip to exactly match *target_duration* seconds.

    - Clip longer than target → trim with ``-t``
    - Clip shorter than target → loop with ``-stream_loop``
    - Within 0.5 s of target → copy as-is (skip re-encode)

    Returns *output_path*.
    """
    if target_duration <= 0:
        raise ValueError(f"target_duration must be positive, got {target_duration}")

    actual = probe_duration(input_path)
    diff = abs(actual - target_duration)

    if diff <= 0.5:
        # Close enough — just copy
        shutil.copy2(str(input_path), str(output_path))
        logger.debug(
            "Clip {} within 0.5s of target ({:.1f}s vs {:.1f}s) — copied as-is",
            input_path.name, actual, target_duration,
        )
        return output_path

    if actual > target_duration:
        # Trim to target
        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-t", str(target_duration),
                "-c:v", "copy",
                "-an",
                str(output_path),
            ],
            description=f"trim {input_path.name} to {target_duration:.1f}s",
        )
    else:
        # Loop to fill target
        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(input_path),
                "-t", str(target_duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-an",
                str(output_path),
            ],
            description=f"loop {input_path.name} to {target_duration:.1f}s",
        )

    logger.info(
        "Clip adjusted — {} {:.1f}s → {:.1f}s ({})",
        input_path.name, actual, target_duration,
        "trimmed" if actual > target_duration else "looped",
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


def concatenate_clips_with_crossfade(
    clip_paths: list[Path],
    output_path: Path,
    crossfade_duration: float = 0.3,
    transitions: list[str] | None = None,
    transition_durations: list[float] | None = None,
) -> Path:
    """Concatenate video clips with crossfade/xfade transitions.

    Uses FFmpeg's xfade filter to create smooth transitions between clips.
    Falls back to simple concatenation for a single clip.

    Args:
        clip_paths: List of video clip paths (must have same resolution/codec).
        output_path: Path for the concatenated output.
        crossfade_duration: Default duration of each crossfade in seconds.
        transitions: Per-boundary transition types (len = num_clips - 1).
                     If None, uses "fade" for all.
        transition_durations: Per-boundary durations (len = num_clips - 1).
                              If None, uses crossfade_duration for all.

    Returns:
        Path to the concatenated video with transitions.
    """
    if len(clip_paths) < 2:
        # Single clip — just copy
        return concatenate_clips(clip_paths, output_path)

    n = len(clip_paths)

    # Build input args
    input_args: list[str] = []
    for p in clip_paths:
        input_args.extend(["-i", str(p)])

    # Get durations for offset calculation
    durations = [probe_duration(p) for p in clip_paths]

    # Build xfade filter chain with per-transition types and durations
    filter_parts: list[str] = []
    cumulative_duration = durations[0]

    for i in range(1, n):
        # Per-transition type and duration
        transition_type = transitions[i - 1] if transitions and i - 1 < len(transitions) else "fade"
        duration = transition_durations[i - 1] if transition_durations and i - 1 < len(transition_durations) else crossfade_duration

        # Offset = cumulative duration minus crossfade overlap
        offset = cumulative_duration - duration
        offset = max(0, offset)  # Safety clamp

        if i == 1:
            src_label = "[0:v][1:v]"
        else:
            src_label = f"[v{i-1}][{i}:v]"

        if i == n - 1:
            out_label = "[vout]"
        else:
            out_label = f"[v{i}]"

        filter_parts.append(
            f"{src_label}xfade=transition={transition_type}:duration={duration}:offset={offset:.3f}{out_label}"
        )

        # Add this clip's duration minus the crossfade overlap
        cumulative_duration = offset + durations[i]

    filter_complex = ";".join(filter_parts)

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output_path),
        ],
        description=f"crossfade concatenate {n} clips",
    )

    transition_desc = "mixed" if transitions else "fade"
    logger.info(
        "Crossfade concatenated {} clips (transitions={}) → {}",
        n, transition_desc, output_path.name,
    )
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


# ── Color Normalization ────────────────────────────────────────

_COLOR_PROFILES: dict[str, str] = {
    "neutral": (
        "eq=contrast=1.05:brightness=0.02:saturation=1.1,"
        "unsharp=5:5:0.5:5:5:0"
    ),
    "cinematic": (
        "eq=contrast=1.1:brightness=-0.02:saturation=0.95,"
        "colorbalance=rs=-0.05:gs=-0.02:bs=0.05:rm=-0.03:gm=0:bm=0.03,"
        "unsharp=5:5:0.5:5:5:0"
    ),
    "warm": (
        "eq=contrast=1.05:brightness=0.02:saturation=1.05,"
        "colorbalance=rs=0.06:gs=0.02:bs=-0.04:rm=0.04:gm=0.01:bm=-0.02,"
        "unsharp=5:5:0.5:5:5:0"
    ),
    "cool": (
        "eq=contrast=1.05:brightness=0.01:saturation=1.0,"
        "colorbalance=rs=-0.04:gs=0:bs=0.06:rm=-0.02:gm=0.01:bm=0.04,"
        "unsharp=5:5:0.5:5:5:0"
    ),
}

_MOOD_COLOR_MAP: dict[str, str] = {
    "energetic": "warm",
    "calm": "cool",
    "dramatic": "cinematic",
    "mysterious": "cinematic",
    "uplifting": "warm",
    "dark": "cinematic",
    "happy": "warm",
    "sad": "cool",
    "epic": "cinematic",
    "chill": "neutral",
}


def normalize_color_grading(
    video_path: Path,
    output_path: Path,
    profile: str = "neutral",
) -> Path:
    """Apply a color normalization pass to unify visual style across clips.

    Uses FFmpeg eq (contrast/brightness/saturation) and colorbalance filters.
    """
    vf = _COLOR_PROFILES.get(profile, _COLOR_PROFILES["neutral"])

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg color normalization failed: {result.stderr[-500:]}"
        )

    logger.info(
        "Color normalization applied — profile={} {} → {}",
        profile, video_path.name, output_path.name,
    )
    return output_path


def mix_audio_with_bgm(
    tts_path: Path,
    bgm_path: Path,
    output_path: Path,
    tts_volume_db: float = -3.0,
    bgm_volume_db: float = -18.0,
    fade_in: float = 1.0,
    fade_out: float = 2.0,
    ducking_enabled: bool = True,
) -> Path:
    """Mix TTS narration with background music.

    Applies volume leveling, fade in/out on BGM, and optional sidechain
    ducking to reduce BGM during speech.

    Args:
        tts_path: Path to TTS narration audio.
        bgm_path: Path to background music audio.
        output_path: Path for mixed output.
        tts_volume_db: TTS volume adjustment in dB.
        bgm_volume_db: BGM volume adjustment in dB.
        fade_in: BGM fade-in duration at start (seconds).
        fade_out: BGM fade-out duration at end (seconds).
        ducking_enabled: Apply sidechain compression to duck BGM.

    Returns:
        Path to the mixed audio file.
    """
    # Get TTS duration for BGM trimming and fade-out timing
    tts_duration = probe_duration(tts_path)
    fade_out_start = max(0, tts_duration - fade_out)

    if ducking_enabled:
        # Sidechain ducking: BGM ducks under speech
        filter_complex = (
            f"[0:a]volume={tts_volume_db}dB,asplit=2[tts][sc];"
            f"[1:a]atrim=0:{tts_duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={bgm_volume_db}dB,"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out}[bgm_raw];"
            f"[bgm_raw][sc]sidechaincompress=threshold=0.02:ratio=6:attack=200:release=1000[bgm];"
            f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )
    else:
        # Simple mix without ducking
        filter_complex = (
            f"[0:a]volume={tts_volume_db}dB[tts];"
            f"[1:a]atrim=0:{tts_duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={bgm_volume_db}dB,"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out}[bgm];"
            f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(tts_path),
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            "-ar", "44100",
            str(output_path),
        ],
        description="mix TTS with BGM",
    )

    logger.info(
        "Audio mixed — TTS={} BGM={} ducking={} → {}",
        tts_path.name, bgm_path.name, ducking_enabled, output_path.name,
    )
    return output_path


def assemble_video(
    clip_paths: list[Path],
    audio_path: Path,
    video_format: str = "short",
    project_id: str | None = None,
    caption_ass_path: Path | None = None,
    scene_durations: list[float] | None = None,
    transitions: list[str] | None = None,
    transition_durations: list[float] | None = None,
    bgm_path: Path | None = None,
    bgm_volume_db: float = -18.0,
    tts_volume_db: float = -3.0,
    bgm_fade_in: float = 1.0,
    bgm_fade_out: float = 2.0,
    bgm_ducking_enabled: bool = True,
    mood: str | None = None,
) -> Path:
    """
    Full assembly pipeline:
      1. Scale/pad each clip to target resolution
      2. Trim/loop each clip to match its scene duration (if provided)
      3. Concatenate all clips with transitions
      4. Mix BGM with TTS audio (if provided)
      5. Overlay audio onto video
      6. Burn captions (if ASS file provided)
      7. Return path to final output MP4

    Args:
        clip_paths: Downloaded B-roll clip file paths.
        audio_path: TTS audio file path.
        video_format: "short" (9:16) or "long" (16:9).
        project_id: Optional UUID for naming the output.
        caption_ass_path: Optional ASS subtitle file for caption burn-in.
        scene_durations: Per-clip target durations in seconds.
        transitions: Per-boundary xfade transition types.
        transition_durations: Per-boundary transition durations.
        bgm_path: Optional background music file path.
        bgm_volume_db: BGM volume in dB.
        tts_volume_db: TTS narration volume in dB.
        bgm_fade_in: BGM fade-in duration in seconds.
        bgm_fade_out: BGM fade-out duration in seconds.
        bgm_ducking_enabled: Apply sidechain ducking on BGM.

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

    # 1. Scale each clip (strips audio — TTS replaces it)
    scaled_paths: list[Path] = []
    for i, clip in enumerate(clip_paths):
        scaled = work_dir / f"scaled_{i:03d}.mp4"
        scale_and_pad(clip, scaled, w, h)
        scaled_paths.append(scaled)

    # 2. Trim/loop each clip to its scene duration (if provided)
    if scene_durations and len(scene_durations) == len(scaled_paths):
        duration_matched: list[Path] = []
        for i, (scaled, dur) in enumerate(zip(scaled_paths, scene_durations)):
            matched = work_dir / f"matched_{i:03d}.mp4"
            trim_or_loop_clip(scaled, matched, dur)
            duration_matched.append(matched)
        scaled_paths = duration_matched
        logger.info(
            "Clips duration-matched to scenes — total={:.1f}s",
            sum(scene_durations),
        )

    # 3. Concatenate clips with transitions (or simple concat for single clip)
    concat_path = work_dir / "concat.mp4"
    if len(scaled_paths) > 1:
        concatenate_clips_with_crossfade(
            scaled_paths, concat_path,
            transitions=transitions,
            transition_durations=transition_durations,
        )
    else:
        concatenate_clips(scaled_paths, concat_path)

    # 3b. Mix BGM with TTS audio if background music is provided
    effective_audio = audio_path
    if bgm_path is not None and bgm_path.exists():
        mixed_audio = work_dir / "mixed_audio.mp3"
        mix_audio_with_bgm(
            tts_path=audio_path,
            bgm_path=bgm_path,
            output_path=mixed_audio,
            tts_volume_db=tts_volume_db,
            bgm_volume_db=bgm_volume_db,
            fade_in=bgm_fade_in,
            fade_out=bgm_fade_out,
            ducking_enabled=bgm_ducking_enabled,
        )
        effective_audio = mixed_audio
        logger.info("Using BGM-mixed audio for overlay")

    # 4. Overlay audio onto video
    narrated_path = work_dir / "narrated.mp4"
    overlay_audio(concat_path, effective_audio, narrated_path)

    # 4. Burn captions if ASS subtitle file provided
    if caption_ass_path is not None:
        captioned_path = work_dir / "captioned.mp4"
        burn_captions(narrated_path, caption_ass_path, captioned_path)
        narrated_path = captioned_path  # downstream uses captioned version

    # 4b. Color normalization (optional — unifies visual style across clips)
    if getattr(settings, "color_normalization_enabled", False):
        color_profile = getattr(settings, "color_normalization_profile", "auto")
        if color_profile == "auto":
            color_profile = _MOOD_COLOR_MAP.get(mood or "uplifting", "neutral")
        try:
            color_path = work_dir / "color_normalized.mp4"
            normalize_color_grading(narrated_path, color_path, profile=color_profile)
            narrated_path = color_path
        except Exception as exc:
            logger.warning("Color normalization failed, skipping: {}", exc)

    # 5. Move narrated video to final output
    final_name = f"final_{tag}.mp4"
    final_path = output_dir / final_name
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


# ── Ken Burns Effect (Image → Video) ────────────────────────────


_KB_EFFECTS: dict[str, dict[str, str]] = {
    "zoom_in": {
        "z": "'min(zoom+0.0015,1.5)'",
        "x": "'iw/2-(iw/zoom/2)'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
    "zoom_out": {
        "z": "'if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))'",
        "x": "'iw/2-(iw/zoom/2)'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
    "pan_left": {
        "z": "1.2",
        "x": "'(iw/2-(iw/zoom/2))+on*(iw/zoom-ow)/{frames}'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
    "pan_right": {
        "z": "1.2",
        "x": "'(iw/2-(iw/zoom/2))-on*(iw/zoom-ow)/{frames}'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
    "pan_up": {
        "z": "1.2",
        "x": "'iw/2-(iw/zoom/2)'",
        "y": "'(ih/2-(ih/zoom/2))-on*(ih/zoom-oh)/{frames}'",
    },
    "diagonal_pan_rd": {
        "z": "1.2",
        "x": "'(iw/2-(iw/zoom/2))-on*(iw/zoom-ow)/{frames}'",
        "y": "'(ih/2-(ih/zoom/2))+on*(ih/zoom-oh)/{frames}'",
    },
    "diagonal_pan_lu": {
        "z": "1.2",
        "x": "'(iw/2-(iw/zoom/2))+on*(iw/zoom-ow)/{frames}'",
        "y": "'(ih/2-(ih/zoom/2))-on*(ih/zoom-oh)/{frames}'",
    },
    "zoom_in_pan_right": {
        "z": "'min(zoom+0.0012,1.4)'",
        "x": "'iw/2-(iw/zoom/2)-on*(iw/zoom-ow)*0.3/{frames}'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
    "zoom_out_pan_left": {
        "z": "'if(lte(zoom,1.0),1.4,max(1.001,zoom-0.0012))'",
        "x": "'iw/2-(iw/zoom/2)+on*(iw/zoom-ow)*0.3/{frames}'",
        "y": "'ih/2-(ih/zoom/2)'",
    },
}


def select_ken_burns_effect(scene_number: int, total_scenes: int) -> str:
    """Pick a Ken Burns effect for a scene to ensure visual variety.

    Optimized sequence for 5-6 scenes with maximum visual diversity:
      Scene 1: zoom_in — dramatic pull-in (hook)
      Scene 2: diagonal_pan_rd — dynamic diagonal movement
      Scene 3: zoom_out_pan_left — revealing pull-back
      Scene 4: pan_right — lateral sweep
      Scene 5: zoom_in_pan_right — intense combined motion
      Scene 6: diagonal_pan_lu — upward exit
    Cycles for >6 scenes.
    """
    effects = [
        "zoom_in",
        "diagonal_pan_rd",
        "zoom_out_pan_left",
        "pan_right",
        "zoom_in_pan_right",
        "diagonal_pan_lu",
        "zoom_out",
        "pan_left",
        "pan_up",
    ]
    idx = (scene_number - 1) % len(effects)
    return effects[idx]


def apply_ken_burns(
    image_path: Path,
    output_path: Path,
    duration: float,
    effect: str = "zoom_in",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> Path:
    """Convert a static image into a video clip with pan/zoom animation.

    Uses FFmpeg's zoompan filter. Adds fade-in/out for smooth transitions.

    Args:
        image_path: Path to the source image (PNG/JPG).
        output_path: Path for the output MP4 clip.
        duration: Target clip duration in seconds.
        effect: One of zoom_in, zoom_out, pan_left, pan_right, pan_up.
        width: Output video width.
        height: Output video height.
        fps: Output frame rate.

    Returns:
        Path to the generated video clip.
    """
    if duration <= 0:
        raise ValueError(f"Duration must be positive, got {duration}")

    if effect not in _KB_EFFECTS:
        raise ValueError(f"Unknown Ken Burns effect: {effect}. Use: {list(_KB_EFFECTS.keys())}")

    total_frames = int(duration * fps)
    params = _KB_EFFECTS[effect]

    # Substitute {frames} placeholder in pan effects
    z = params["z"]
    x = params["x"].replace("{frames}", str(total_frames))
    y = params["y"].replace("{frames}", str(total_frames))

    zoompan_filter = (
        f"zoompan=z={z}:x={x}:y={y}"
        f":d={total_frames}:s={width}x{height}:fps={fps}"
    )

    # Build video filter chain: zoompan + fade in/out
    fade_in = "fade=t=in:st=0:d=0.5"
    fade_out_start = max(0, duration - 0.5)
    fade_out = f"fade=t=out:st={fade_out_start:.2f}:d=0.5"

    vf = f"{zoompan_filter},{fade_in},{fade_out}"

    args = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-an",
        str(output_path),
    ]

    _run_ffmpeg(args, f"ken_burns {effect} ({duration:.1f}s)")

    logger.info(
        "Ken Burns clip generated — {} effect={} duration={:.1f}s",
        output_path.name, effect, duration,
    )
    return output_path


def image_to_video_clip(
    image_path: Path,
    duration: float,
    scene_number: int,
    total_scenes: int,
    output_dir: Path | None = None,
) -> Path:
    """High-level wrapper: generate a Ken Burns video clip from an image.

    Selects the appropriate effect based on scene position and generates
    the video clip with exact duration matching.

    Args:
        image_path: Path to the AI-generated scene image.
        duration: Exact clip duration in seconds.
        scene_number: 1-based scene number (for effect selection).
        total_scenes: Total number of scenes in the video.
        output_dir: Output directory (defaults to ai_images_dir).

    Returns:
        Path to the generated video clip.
    """
    if output_dir is None:
        output_dir = settings.ai_images_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    effect = select_ken_burns_effect(scene_number, total_scenes)
    output_path = output_dir / f"kb_{scene_number}_{uuid.uuid4().hex[:8]}.mp4"

    apply_ken_burns(
        image_path=image_path,
        output_path=output_path,
        duration=duration,
        effect=effect,
    )

    return output_path
