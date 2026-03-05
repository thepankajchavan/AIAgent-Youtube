"""
YouTube OAuth Setup Script

Run this script ONCE to authenticate with YouTube and generate the OAuth token.
This will open a browser window for you to authorize the app.

After successful authentication, a youtube_token.json file will be created.
This token will be used for all future YouTube uploads.

Usage:
    python setup_youtube_oauth.py
"""

import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from loguru import logger

# Same scopes as the main service
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# File paths
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "youtube_token.json"


def setup_youtube_oauth():
    """Run the OAuth consent flow and save the token."""

    # Check if client_secrets.json exists
    if not Path(CLIENT_SECRETS_FILE).exists():
        logger.error(f"❌ {CLIENT_SECRETS_FILE} not found!")
        logger.error("Please download it from Google Cloud Console:")
        logger.error("  1. Go to: https://console.cloud.google.com/apis/credentials")
        logger.error("  2. Select your project: curious-signal-489207-d7")
        logger.error("  3. Download OAuth 2.0 Client credentials")
        logger.error("  4. Save as 'client_secrets.json' in this directory")
        return

    logger.info("🔐 Starting YouTube OAuth setup...")
    logger.info("")
    logger.info("This will open a browser window for you to:")
    logger.info("  1. Select your Google account")
    logger.info("  2. Grant permission to upload videos to YouTube")
    logger.info("  3. Authorize the app")
    logger.info("")
    logger.info("⚠️  You may see a warning: 'Google hasn't verified this app'")
    logger.info("   → Click 'Advanced' → 'Go to [your app name] (unsafe)'")
    logger.info("   → This is safe because it's YOUR app!")
    logger.info("")

    try:
        # Run the OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            SCOPES
        )

        # This will open a browser window
        logger.info("🌐 Opening browser for authentication...")
        credentials = flow.run_local_server(
            port=8080,
            prompt='consent',
            success_message='Authentication successful! You can close this window now.'
        )

        # Save the credentials
        token_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes,
        }

        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f, indent=2)

        logger.info("")
        logger.info("✅ SUCCESS! YouTube OAuth token saved to: youtube_token.json")
        logger.info("")
        logger.info("📝 Token Details:")
        logger.info(f"   Client ID: {credentials.client_id[:30]}...")
        logger.info(f"   Scopes: {', '.join(credentials.scopes)}")
        logger.info(f"   Expires: {credentials.expiry}")
        logger.info("")
        logger.info("🎬 Your system is now ready to upload videos to YouTube!")
        logger.info("")
        logger.info("🔒 Security Recommendations:")
        logger.info("   1. Keep youtube_token.json secure (it's in .gitignore)")
        logger.info("   2. Consider encrypting it: python scripts/encrypt_youtube_token.py")
        logger.info("   3. Never share your client_secrets.json or token file")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Start your services: start_all.bat")
        logger.info("  2. Start Telegram bot: python telegram_bot.py")
        logger.info("  3. Send: /video 3 facts about space")
        logger.info("  4. Watch it upload to YouTube! 🚀")

    except Exception as e:
        logger.error(f"❌ OAuth setup failed: {e}")
        logger.error("")
        logger.error("Common issues:")
        logger.error("  1. Browser didn't open? Check firewall settings")
        logger.error("  2. Authorization failed? Check Google Cloud Console settings:")
        logger.error("     - OAuth consent screen configured")
        logger.error("     - Your email added as test user")
        logger.error("     - YouTube Data API v3 enabled")
        logger.error("  3. Port 8080 already in use? Close other apps using that port")


if __name__ == "__main__":
    setup_youtube_oauth()
