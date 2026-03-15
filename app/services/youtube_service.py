"""
YouTube Service — uploads videos via the YouTube Data API v3.

Handles OAuth2 token management and resumable uploads.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.circuit_breaker import with_youtube_breaker
from app.core.config import get_settings
from app.core.encryption import decrypt_string, encrypt_string

settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CATEGORY_IDS = {
    "entertainment": "24",
    "education": "27",
    "science": "28",
    "howto": "26",
    "people": "22",
    "comedy": "23",
    "news": "25",
    "gaming": "20",
}


def _read_token(token_path: Path) -> str | None:
    """
    Read YouTube OAuth token from file (supports encrypted and plaintext).

    Args:
        token_path: Path to token file (e.g., youtube_token.json)

    Returns:
        Token JSON string, or None if file doesn't exist
    """
    # Check for encrypted token first
    encrypted_path = token_path.with_suffix(".json.encrypted")

    if encrypted_path.exists():
        logger.debug(f"Reading encrypted token from {encrypted_path}")
        try:
            ciphertext = encrypted_path.read_text()
            token_json = decrypt_string(ciphertext)
            return token_json
        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}")
            raise ValueError(
                f"Failed to decrypt YouTube token at {encrypted_path}. "
                "Verify ENCRYPTION_KEY is correct."
            ) from e

    # Fall back to plaintext token
    if token_path.exists():
        logger.warning(
            f"Reading plaintext token from {token_path}. "
            "Consider encrypting with: python scripts/encrypt_youtube_token.py"
        )
        return token_path.read_text()

    return None


def _write_token(token_path: Path, token_json: str) -> None:
    """
    Write YouTube OAuth token to file (encrypted if encryption key is configured).

    Args:
        token_path: Path to token file (e.g., youtube_token.json)
        token_json: Token JSON string
    """
    encrypted_path = token_path.with_suffix(".json.encrypted")

    # Try to encrypt if encryption key is configured
    try:
        ciphertext = encrypt_string(token_json)
        encrypted_path.write_text(ciphertext)
        logger.info(f"Saved encrypted token to {encrypted_path}")

        # Remove plaintext token if it exists
        if token_path.exists():
            token_path.unlink()
            logger.info(f"Removed plaintext token {token_path}")

    except ValueError:
        # Encryption key not configured, fall back to plaintext
        logger.warning(
            "ENCRYPTION_KEY not configured. Saving token as plaintext. "
            "Generate key with: python scripts/generate_secrets.py"
        )
        token_path.write_text(token_json)


def _get_authenticated_service():
    """
    Build an authenticated YouTube API service.

    Reads cached credentials from youtube_token.json.
    If expired, refreshes automatically.
    If no token exists, runs the OAuth consent flow (first-time setup only).
    """
    creds: Credentials | None = None
    token_path = Path(settings.youtube_token_file)
    secrets_path = Path(settings.youtube_client_secrets_file)

    # Read token (supports encrypted and plaintext)
    token_json = _read_token(token_path)
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired YouTube OAuth token …")
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise RuntimeError(
                "YouTube OAuth token expired/revoked. Re-authenticate by running:\n"
                "  python scripts/refresh_youtube_token.py\n"
                f"Original error: {exc}"
            ) from exc
    elif not creds or not creds.valid:
        if not secrets_path.exists():
            raise FileNotFoundError(
                f"YouTube client secrets file not found: {secrets_path}. "
                "Download it from Google Cloud Console."
            )
        logger.info("Running YouTube OAuth consent flow …")
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        creds = flow.run_local_server(port=0)

    # Persist refreshed / new credentials (encrypted if possible)
    _write_token(token_path, creds.to_json())

    return build("youtube", "v3", credentials=creds)


@with_youtube_breaker()
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=5, min=10, max=120),
    retry=retry_if_exception_type((IOError, OSError, ConnectionError)),
    before_sleep=lambda rs: logger.warning(
        "YouTube upload attempt {} failed, retrying …",
        rs.attempt_number,
    ),
)
def upload_video(
    file_path: str | Path,
    title: str,
    description: str,
    tags: list[str],
    category: str = "education",
    privacy_status: str = "public",
    is_short: bool = True,
    hashtags: list[str] | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> dict:
    """
    Upload a video to YouTube.

    Args:
        file_path: Path to the MP4 file.
        title: Video title (max 100 chars).
        description: Video description.
        tags: List of tags.
        category: Category name (mapped to YouTube category ID).
        privacy_status: "private", "unlisted", or "public".
        is_short: If True, prepends #Shorts to title/tags for Shorts shelf.
        hashtags: List of hashtags (with #) to append to description.
        progress_callback: Optional callback called with progress fraction (0.0-1.0).

    Returns:
        Dict with keys: video_id, url.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    youtube = _get_authenticated_service()

    # Shorts optimisation
    if is_short and "#Shorts" not in title:
        title = f"{title} #Shorts"
    if is_short and "#Shorts" not in tags:
        tags = [*tags, "#Shorts"]

    # Truncate title to YouTube limit
    title = title[:100]

    # Reorder hashtags so trending/viral ones appear last (YouTube shows last 3 above title)
    if hashtags:
        from app.services.viral_service import ViralOptimizer
        ordered_hashtags = ViralOptimizer().reorder_hashtags_for_youtube(hashtags)
        description = description + "\n\n" + " ".join(ordered_hashtags[-8:])

    category_id = CATEGORY_IDS.get(category.lower(), "24")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    logger.info(
        "YouTube upload starting — title='{}' privacy={} file={}",
        title,
        privacy_status,
        file_path.name,
    )

    media = MediaFileUpload(
        str(file_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    # Execute resumable upload with progress logging
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = status.progress()
            logger.info("Upload progress: {:.0%}", progress)
            if progress_callback:
                progress_callback(progress)

    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    logger.info("Upload complete — video_id={} url={}", video_id, video_url)
    return {"video_id": video_id, "url": video_url}


def set_thumbnail(video_id: str, thumbnail_path: str | Path) -> bool:
    """
    Set a custom thumbnail for a YouTube video.

    Requires the channel to be verified for custom thumbnails.
    Fails gracefully if the channel is not verified.

    Args:
        video_id: YouTube video ID.
        thumbnail_path: Path to the thumbnail image (JPEG/PNG, <2MB).

    Returns:
        True if thumbnail was set, False on failure.
    """
    thumbnail_path = Path(thumbnail_path)
    if not thumbnail_path.exists():
        logger.warning("Thumbnail file not found: {}", thumbnail_path)
        return False

    try:
        youtube = _get_authenticated_service()
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
        ).execute()
        logger.info("Thumbnail set for video {}", video_id)
        return True
    except HttpError as exc:
        if exc.resp.status == 403:
            logger.warning(
                "Cannot set thumbnail for video {} — channel not verified for "
                "custom thumbnails. Verify at https://www.youtube.com/verify",
                video_id,
            )
        else:
            logger.warning(
                "YouTube API error setting thumbnail for {}: {}", video_id, exc
            )
        return False
    except Exception as exc:
        logger.warning(
            "Failed to set thumbnail for video {}: {}", video_id, exc
        )
        return False
