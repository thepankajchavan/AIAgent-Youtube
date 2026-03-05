"""Encrypt YouTube OAuth token for secure storage."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.encryption import encrypt_file, get_encryption_key
from app.core.config import get_settings

settings = get_settings()


def main():
    """Encrypt the YouTube token file."""
    token_path = Path(settings.youtube_token_file)

    # Check if token file exists
    if not token_path.exists():
        print(f"❌ YouTube token file not found: {token_path}")
        print("   Run the YouTube OAuth flow first to generate the token.")
        sys.exit(1)

    # Check if encryption key is configured
    try:
        get_encryption_key()
    except ValueError as e:
        print(f"❌ {e}")
        print()
        print("Generate an encryption key with:")
        print("  python scripts/generate_secrets.py")
        print()
        print("Then add ENCRYPTION_KEY to your .env file.")
        sys.exit(1)

    # Check if already encrypted
    encrypted_path = token_path.with_suffix('.json.encrypted')
    if encrypted_path.exists():
        confirm = input(f"⚠️  Encrypted token already exists at {encrypted_path}. Overwrite? (yes/no): ")
        if confirm.lower() != "yes":
            print("Encryption cancelled.")
            sys.exit(0)

    # Encrypt the token file
    print(f"🔐 Encrypting {token_path} ...")

    try:
        result_path = encrypt_file(token_path, encrypted_path)
        print(f"✅ Encrypted token saved to: {result_path}")
        print()
        print("Next steps:")
        print(f"1. Backup the original token: cp {token_path} {token_path}.backup")
        print(f"2. Delete the plaintext token: rm {token_path}")
        print(f"3. The app will now read from {encrypted_path} automatically")
        print()
        print("⚠️  Keep a secure backup of your encryption key!")

    except Exception as e:
        print(f"❌ Encryption failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
