"""
Music Service — background music integration via Pixabay Music API.

Provides mood-based music search, track download, and graceful degradation.
All functions return None on failure to allow the pipeline to continue
without background music.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
from loguru import logger

from app.core.config import get_settings

# ── Mood → Pixabay Search Query Mapping ──────────────────────────

MOOD_SEARCH_MAP: dict[str, str] = {
    "energetic": "energetic upbeat electronic",
    "calm": "calm peaceful ambient",
    "dramatic": "dramatic cinematic orchestral",
    "mysterious": "mysterious dark suspense",
    "uplifting": "uplifting inspiring positive",
    "dark": "dark intense ominous",
    "happy": "happy cheerful bright",
    "sad": "sad emotional melancholy",
    "epic": "epic heroic powerful",
    "chill": "chill lofi relaxing",
}

# All valid mood values
VALID_MOODS: set[str] = set(MOOD_SEARCH_MAP.keys())

PIXABAY_MUSIC_API_URL = "https://pixabay.com/api/music/"


async def search_music(
    mood: str,
    min_duration: int = 30,
    max_duration: int = 120,
) -> list[dict]:
    """Search Pixabay Music API for tracks matching a mood.

    Args:
        mood: Emotional mood tag (e.g. "energetic", "calm").
        min_duration: Minimum track duration in seconds.
        max_duration: Maximum track duration in seconds.

    Returns:
        List of track dicts with keys: id, title, audio_url, duration.
        Empty list if no results or API error.
    """
    settings = get_settings()
    api_key = getattr(settings, "pixabay_api_key", "")

    if not api_key:
        logger.warning("PIXABAY_API_KEY not configured — cannot search music")
        return []

    query = MOOD_SEARCH_MAP.get(mood, MOOD_SEARCH_MAP.get("uplifting", "uplifting music"))

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                PIXABAY_MUSIC_API_URL,
                params={
                    "key": api_key,
                    "q": query,
                    "min_duration": min_duration,
                    "max_duration": max_duration,
                    "order": "popular",
                },
            )
            response.raise_for_status()
            data = response.json()

        hits = data.get("hits", [])
        tracks = []
        for hit in hits:
            tracks.append({
                "id": str(hit.get("id", "")),
                "title": hit.get("title", "Unknown"),
                "audio_url": hit.get("audio", ""),
                "duration": hit.get("duration", 0),
            })

        logger.info(
            "Pixabay music search — mood='{}' query='{}' results={}",
            mood, query, len(tracks),
        )
        return tracks

    except Exception as exc:
        logger.warning("Pixabay music search failed: {}", exc)
        return []


async def download_track(
    audio_url: str,
    output_dir: Path | None = None,
) -> Path:
    """Download a music track from Pixabay.

    Args:
        audio_url: Direct URL to the audio file.
        output_dir: Directory to save the track (defaults to media/bgm).

    Returns:
        Path to the downloaded audio file.

    Raises:
        RuntimeError: If download fails.
    """
    if output_dir is None:
        settings = get_settings()
        output_dir = settings.media_path / "bgm"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"bgm_{uuid.uuid4().hex[:12]}.mp3"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(audio_url)
            response.raise_for_status()
            output_path.write_bytes(response.content)

        logger.info("BGM track downloaded — {} ({} bytes)", output_path.name, output_path.stat().st_size)
        return output_path

    except Exception as exc:
        logger.error("BGM download failed: {}", exc)
        raise RuntimeError(f"Failed to download BGM track: {exc}") from exc


async def fetch_bgm_for_mood(
    mood: str,
    target_duration: float,
) -> Path | None:
    """Search for and download a background music track matching the mood.

    High-level convenience function that combines search + download.
    Returns None on any failure (graceful degradation).

    Args:
        mood: Emotional mood tag.
        target_duration: Target video duration to help filter track length.

    Returns:
        Path to downloaded BGM file, or None if unavailable.
    """
    try:
        # Search with some buffer around target duration
        min_dur = max(15, int(target_duration * 0.5))
        max_dur = max(120, int(target_duration * 3))

        tracks = await search_music(mood, min_duration=min_dur, max_duration=max_dur)

        if not tracks:
            logger.warning("No BGM tracks found for mood='{}' — proceeding without music", mood)
            return None

        # Pick the first (most popular) track with a valid audio URL
        for track in tracks:
            if track.get("audio_url"):
                logger.info(
                    "Selected BGM track — '{}' (id={}, {}s)",
                    track["title"], track["id"], track.get("duration", "?"),
                )
                return await download_track(track["audio_url"])

        logger.warning("No BGM tracks had valid audio URLs")
        return None

    except Exception as exc:
        logger.warning("BGM fetch failed for mood='{}': {} — proceeding without music", mood, exc)
        return None
