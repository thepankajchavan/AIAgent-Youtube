"""
Visual Service — fetches stock video clips from Pexels.

Searches for relevant B-roll, downloads clips to disk, and returns
file paths. Handles orientation filtering for shorts (portrait) vs
long-form (landscape).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import cache_pexels_search, get_cached_pexels_search
from app.core.circuit_breaker import with_pexels_breaker
from app.core.config import get_settings
from app.services.media_service import probe_duration

settings = get_settings()

PEXELS_BASE_URL = "https://api.pexels.com"
_PEXELS_RATE_LIMIT_KEY = "pexels:api_calls:{hour}"
_PEXELS_RATE_LIMIT_THRESHOLD = 180  # 90% of 200/hour Pexels limit


async def _check_pexels_rate_limit() -> bool:
    """Check if Pexels API rate limit threshold is approaching.

    Returns True if safe to proceed, False if rate limit exceeded.
    Uses Redis INCR with 1-hour TTL for tracking.
    """
    from datetime import datetime, UTC
    from app.core.redis_client import get_redis_client

    try:
        redis = await get_redis_client()
        hour_key = _PEXELS_RATE_LIMIT_KEY.format(
            hour=datetime.now(UTC).strftime("%Y%m%d%H")
        )
        count = await redis.incr(hour_key)
        if count == 1:
            await redis.expire(hour_key, 3600)

        if count > _PEXELS_RATE_LIMIT_THRESHOLD:
            logger.warning(
                "Pexels rate limit approaching: {}/{} calls this hour",
                count,
                _PEXELS_RATE_LIMIT_THRESHOLD,
            )
            return False
        return True
    except Exception as exc:
        logger.debug("Rate limit check failed (proceeding): {}", exc)
        return True  # Don't block on Redis failures


def _headers() -> dict[str, str]:
    return {"Authorization": settings.pexels_api_key}


@with_pexels_breaker(fallback_to_placeholder=False)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=lambda rs: logger.warning(
        "Pexels search attempt {} failed, retrying …",
        rs.attempt_number,
    ),
)
async def search_videos(
    query: str,
    orientation: str = "portrait",
    per_page: int = 5,
    min_duration: int = 5,
    max_duration: int = 30,
) -> list[dict]:
    """
    Search Pexels for stock video clips (with caching).

    Args:
        query: Search keywords.
        orientation: "portrait" (9:16) or "landscape" (16:9).
        per_page: Number of results to return.
        min_duration: Minimum clip duration in seconds.
        max_duration: Maximum clip duration in seconds.

    Returns:
        List of video metadata dicts with keys: id, url, duration, width, height, download_url.
    """
    # Check cache first (cache key includes query + orientation)
    cache_key = f"{query}:{orientation}:{per_page}"
    cached_results = await get_cached_pexels_search(cache_key)

    if cached_results is not None:
        logger.info(f"Cache HIT for Pexels search: '{query}'")
        return cached_results

    # Rate limit check (only for non-cached requests)
    if not await _check_pexels_rate_limit():
        logger.warning("Pexels rate limit exceeded — returning empty for '{}'", query)
        return []

    logger.info(
        "Cache MISS - Pexels search — query='{}' orientation={} count={}",
        query,
        orientation,
        per_page,
    )

    params = {
        "query": query,
        "orientation": orientation,
        "per_page": per_page,
        "size": "medium",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{PEXELS_BASE_URL}/videos/search",
            headers=_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for video in data.get("videos", []):
        duration = video.get("duration", 0)
        if not (min_duration <= duration <= max_duration):
            continue

        # Pick the best quality file that isn't huge
        best_file = _pick_best_file(video.get("video_files", []), orientation)
        if best_file is None:
            continue

        results.append(
            {
                "id": video["id"],
                "url": video["url"],
                "duration": duration,
                "width": best_file["width"],
                "height": best_file["height"],
                "download_url": best_file["link"],
            }
        )

    logger.info("Pexels returned {} usable clips for '{}'", len(results), query)

    # Cache results for 24 hours
    await cache_pexels_search(cache_key, results, ttl=60 * 60 * 24)

    return results


def _pick_best_file(files: list[dict], orientation: str) -> dict | None:
    """
    Select the best video file from Pexels file variants.
    Prefers HD resolution, correct aspect ratio, mp4 format.
    """
    scored: list[tuple[int, dict]] = []

    for f in files:
        if f.get("file_type") != "video/mp4":
            continue

        w = f.get("width", 0)
        h = f.get("height", 0)
        if w == 0 or h == 0:
            continue

        score = 0

        # Orientation match
        if orientation == "portrait" and h > w or orientation == "landscape" and w > h:
            score += 100

        # Resolution preference (720p–1080p sweet spot)
        shorter = min(w, h)
        if 720 <= shorter <= 1080:
            score += 50
        elif shorter > 1080:
            score += 20  # usable but large

        scored.append((score, f))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


@with_pexels_breaker(fallback_to_placeholder=False)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
)
async def download_video(
    download_url: str,
    output_filename: str | None = None,
) -> Path:
    """
    Download a single video file from Pexels to the video directory.

    Returns:
        Path to the downloaded file.
    """
    output_dir = settings.video_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = f"pexels_{uuid.uuid4().hex[:12]}.mp4"
    output_path = output_dir / output_filename

    logger.info("Downloading clip → {}", output_path.name)

    max_size = 500 * 1024 * 1024  # 500MB limit

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            bytes_written = 0
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        raise ValueError(
                            f"Download exceeds {max_size // (1024*1024)}MB limit "
                            f"({bytes_written // (1024*1024)}MB downloaded)"
                        )
                    f.write(chunk)

    logger.info("Clip saved — {} ({:.1f}MB)", output_path.name, bytes_written / 1_048_576)

    # Validate downloaded clip
    clip_duration = probe_duration(output_path)
    if clip_duration < 1.0:
        output_path.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded clip too short ({clip_duration:.1f}s) — likely corrupted"
        )

    return output_path


async def fetch_clips(
    queries: list[str],
    orientation: str = "portrait",
    clips_per_query: int = 2,
) -> list[Path]:
    """
    High-level helper: search multiple queries, download top clips, return paths.

    This is the main entry point called by Celery workers.
    """
    downloaded: list[Path] = []

    for query in queries:
        results = await search_videos(
            query=query,
            orientation=orientation,
            per_page=clips_per_query,
        )
        for clip in results[:clips_per_query]:
            path = await download_video(clip["download_url"])
            downloaded.append(path)

    logger.info("Total clips downloaded: {}", len(downloaded))
    return downloaded


async def create_placeholder_video(
    query: str,
    duration: int = 30,
    orientation: str = "portrait",
) -> list[Path]:
    """
    Create placeholder video files when Pexels API is unavailable.

    Creates simple black videos with text overlay using FFmpeg.

    Args:
        query: The search query (used for filename/logging)
        duration: Duration in seconds
        orientation: "portrait" (1080x1920) or "landscape" (1920x1080)

    Returns:
        List of placeholder video file paths
    """
    import subprocess

    output_dir = settings.video_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"placeholder_{uuid.uuid4().hex[:12]}.mp4"
    output_path = output_dir / filename

    logger.warning(f"Creating placeholder video for query: {query}")

    # Adapt resolution to format
    resolution = "1080x1920" if orientation == "portrait" else "1920x1080"

    command = [
        "ffmpeg",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={resolution}:d={duration}",
        "-vf",
        "drawtext=text='Stock footage unavailable':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(output_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info(f"Created placeholder video: {output_path.name}")
        return [output_path]
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create placeholder video: {e.stderr}")
        raise RuntimeError(f"Failed to create placeholder video: {e}")
