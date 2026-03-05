"""
Media Pipeline Optimization - Parallel processing and GPU acceleration.

Optimizations:
- Parallel FFmpeg operations for multiple clips
- GPU-accelerated encoding (NVENC) detection
- Concurrent video clip processing
- Optimized encoding parameters
"""

import asyncio
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# Thread pool for parallel FFmpeg operations
ffmpeg_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ffmpeg")


class GPUAcceleration:
    """Detect and configure GPU acceleration for video encoding."""

    _nvenc_available: bool | None = None
    _vaapi_available: bool | None = None

    @classmethod
    def detect_nvenc(cls) -> bool:
        """
        Detect NVIDIA NVENC GPU encoder availability.

        Returns:
            True if NVENC is available, False otherwise
        """
        if cls._nvenc_available is not None:
            return cls._nvenc_available

        try:
            # Check if ffmpeg has nvenc encoder
            result = subprocess.run(
                ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=5
            )

            cls._nvenc_available = "h264_nvenc" in result.stdout

            if cls._nvenc_available:
                logger.info("✅ NVIDIA NVENC GPU encoder detected")
            else:
                logger.info("❌ NVIDIA NVENC not available, using CPU encoding")

            return cls._nvenc_available

        except Exception as e:
            logger.warning(f"Failed to detect NVENC: {e}")
            cls._nvenc_available = False
            return False

    @classmethod
    def detect_vaapi(cls) -> bool:
        """
        Detect VA-API hardware acceleration (Intel/AMD).

        Returns:
            True if VA-API is available, False otherwise
        """
        if cls._vaapi_available is not None:
            return cls._vaapi_available

        try:
            # Check if ffmpeg has vaapi encoder
            result = subprocess.run(
                ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=5
            )

            cls._vaapi_available = "h264_vaapi" in result.stdout

            if cls._vaapi_available:
                logger.info("✅ VA-API hardware encoder detected")
            else:
                logger.info("❌ VA-API not available")

            return cls._vaapi_available

        except Exception as e:
            logger.warning(f"Failed to detect VA-API: {e}")
            cls._vaapi_available = False
            return False

    @classmethod
    def get_encoder_params(cls) -> tuple[str, list[str]]:
        """
        Get optimal encoder and parameters based on available hardware.

        Returns:
            Tuple of (encoder_name, encoder_params)
        """
        # Try NVENC first (fastest)
        if cls.detect_nvenc():
            return "h264_nvenc", [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "fast",
                "-rc",
                "vbr",
                "-cq",
                "23",
                "-b:v",
                "5M",
                "-maxrate",
                "10M",
                "-bufsize",
                "10M",
            ]

        # Try VA-API (Intel/AMD)
        if cls.detect_vaapi():
            return "h264_vaapi", ["-c:v", "h264_vaapi", "-qp", "23"]

        # Fallback to CPU encoding (libx264)
        return "libx264", [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-profile:v",
            "high",
            "-level",
            "4.0",
        ]


async def parallel_scale_clips(
    input_clips: list[Path], width: int, height: int, output_dir: Path
) -> list[Path]:
    """
    Scale multiple video clips in parallel using concurrent FFmpeg processes.

    Args:
        input_clips: List of input video file paths
        width: Target width
        height: Target height
        output_dir: Output directory for scaled clips

    Returns:
        List of scaled clip paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Scaling {len(input_clips)} clips in parallel to {width}x{height}")

    async def scale_clip(clip_path: Path, index: int) -> Path:
        """Scale a single clip asynchronously."""
        output_path = output_dir / f"scaled_{index}_{clip_path.name}"

        # Get encoder params
        encoder, encoder_params = GPUAcceleration.get_encoder_params()

        command = [
            "ffmpeg",
            "-i",
            str(clip_path),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
            *encoder_params,
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(output_path),
        ]

        # Run FFmpeg in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            ffmpeg_executor,
            subprocess.run,
            command,
            {"check": True, "capture_output": True, "text": True},
        )

        logger.debug(f"Scaled clip {index + 1}/{len(input_clips)}: {output_path.name}")
        return output_path

    # Process all clips concurrently
    tasks = [scale_clip(clip, i) for i, clip in enumerate(input_clips)]
    scaled_clips = await asyncio.gather(*tasks)

    logger.info(f"Successfully scaled {len(scaled_clips)} clips in parallel")
    return scaled_clips


async def optimized_concatenate(
    input_clips: list[Path], output_path: Path, use_gpu: bool = True
) -> Path:
    """
    Concatenate video clips with optimized encoding.

    Args:
        input_clips: List of video clip paths
        output_path: Output file path
        use_gpu: Whether to use GPU acceleration if available

    Returns:
        Path to concatenated video
    """
    if not input_clips:
        raise ValueError("No input clips provided for concatenation")

    logger.info(f"Concatenating {len(input_clips)} clips with optimization")

    # Create concat file list
    concat_file = output_path.parent / f"concat_{output_path.stem}.txt"

    with open(concat_file, "w") as f:
        for clip in input_clips:
            # Escape single quotes in file paths
            escaped_path = str(clip).replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")

    # Get optimal encoder
    encoder, encoder_params = (
        GPUAcceleration.get_encoder_params()
        if use_gpu
        else ("libx264", ["-c:v", "libx264", "-preset", "medium", "-crf", "23"])
    )

    command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        *encoder_params,
        "-c:a",
        "copy",  # Copy audio without re-encoding
        "-movflags",
        "+faststart",  # Enable streaming
        "-y",
        str(output_path),
    ]

    # Run concatenation
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        ffmpeg_executor,
        subprocess.run,
        command,
        {"check": True, "capture_output": True, "text": True},
    )

    # Clean up concat file
    concat_file.unlink()

    logger.info(f"Concatenation complete: {output_path.name} (encoder: {encoder})")
    return output_path


async def optimized_audio_overlay(
    video_path: Path, audio_path: Path, output_path: Path, use_gpu: bool = True
) -> Path:
    """
    Overlay audio on video with optimized encoding.

    Args:
        video_path: Input video file path
        audio_path: Input audio file path
        output_path: Output file path
        use_gpu: Whether to use GPU acceleration if available

    Returns:
        Path to output video with audio
    """
    logger.info("Adding audio overlay with optimization")

    # Get optimal encoder
    encoder, encoder_params = (
        GPUAcceleration.get_encoder_params()
        if use_gpu
        else ("libx264", ["-c:v", "libx264", "-preset", "medium", "-crf", "23"])
    )

    command = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        *encoder_params,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",  # Match shortest input duration
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]

    # Run audio overlay
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        ffmpeg_executor,
        subprocess.run,
        command,
        {"check": True, "capture_output": True, "text": True},
    )

    logger.info(f"Audio overlay complete: {output_path.name} (encoder: {encoder})")
    return output_path


def get_optimization_stats() -> dict[str, Any]:
    """
    Get media optimization statistics and capabilities.

    Returns:
        Dictionary with optimization stats
    """
    return {
        "gpu_acceleration": {
            "nvenc_available": GPUAcceleration.detect_nvenc(),
            "vaapi_available": GPUAcceleration.detect_vaapi(),
            "encoder": GPUAcceleration.get_encoder_params()[0],
        },
        "parallel_processing": {
            "max_workers": ffmpeg_executor._max_workers,
            "thread_name_prefix": ffmpeg_executor._thread_name_prefix,
        },
        "encoding_settings": {
            "preset": "fast" if GPUAcceleration.detect_nvenc() else "medium",
            "format": "h264",
            "pixel_format": "yuv420p",
        },
    }
