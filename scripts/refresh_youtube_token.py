"""Re-authenticate YouTube OAuth token.

Run this when the token is expired or revoked:
    python scripts/refresh_youtube_token.py

This will open a browser for Google OAuth consent,
then save a fresh token to youtube_token.json.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    settings = get_settings()
    secrets_path = Path(settings.youtube_client_secrets_file)
    token_path = Path(settings.youtube_token_file)

    if not secrets_path.exists():
        print(f"Client secrets file not found: {secrets_path}")
        print("Download it from Google Cloud Console -> APIs & Services -> Credentials.")
        sys.exit(1)

    # Remove old token
    if token_path.exists():
        token_path.unlink()
        print(f"Removed old token: {token_path}")

    encrypted_path = token_path.with_suffix(".json.encrypted")
    if encrypted_path.exists():
        encrypted_path.unlink()
        print(f"Removed old encrypted token: {encrypted_path}")

    # Run OAuth flow (port 8080 must match Authorized redirect URIs in Google Cloud Console)
    print("Opening browser for YouTube OAuth consent...")
    print("Make sure http://localhost:8080/ is in your Google Cloud Console redirect URIs.")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(port=8080)

    # Save token
    token_path.write_text(creds.to_json())
    print(f"Token saved to: {token_path}")
    print()
    print("Next steps:")
    print("1. Restart Celery workers so they pick up the new token")
    print("2. (Optional) Encrypt with: python scripts/encrypt_youtube_token.py")


if __name__ == "__main__":
    main()
