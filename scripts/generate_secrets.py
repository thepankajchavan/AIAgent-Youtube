"""Generate secure random secrets for production deployment."""

import secrets
import string
from cryptography.fernet import Fernet


def generate_password(length: int = 32) -> str:
    """
    Generate a strong random password.

    Args:
        length: Password length (default: 32)

    Returns:
        Random password with uppercase, lowercase, digits, and symbols
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


def generate_token(length: int = 32) -> str:
    """
    Generate a URL-safe random token.

    Args:
        length: Token length in bytes (default: 32, produces ~43 chars)

    Returns:
        Base64-encoded random token
    """
    return secrets.token_urlsafe(length)


def main():
    """Generate all required secrets and print them."""
    print("# ==================================================================")
    print("# Generated Secrets for Production Deployment")
    print("# ==================================================================")
    print("# IMPORTANT: Save these secrets securely!")
    print("# Add them to your .env file or environment variables")
    print("# ==================================================================")
    print()

    print("# -- Database Password --")
    db_password = generate_password(32)
    print(f"DB_PASSWORD={db_password}")
    print()

    print("# -- Redis Password --")
    redis_password = generate_password(32)
    print(f"REDIS_PASSWORD={redis_password}")
    print()

    print("# -- Encryption Key (Fernet) --")
    encryption_key = Fernet.generate_key().decode()
    print(f"ENCRYPTION_KEY={encryption_key}")
    print()

    print("# -- Telegram Webhook Secret --")
    webhook_secret = generate_token(32)
    print(f"TELEGRAM_WEBHOOK_SECRET={webhook_secret}")
    print()

    print("# -- Update Database URLs --")
    print("# Replace the passwords in your DATABASE_URL and REDIS_URL:")
    print(f'DATABASE_URL=postgresql+asyncpg://postgres:{db_password}@postgres:5432/content_engine')
    print(f'DATABASE_URL_SYNC=postgresql+psycopg2://postgres:{db_password}@postgres:5432/content_engine')
    print(f'REDIS_URL=redis://:{redis_password}@redis:6379/0')
    print(f'CELERY_BROKER_URL=redis://:{redis_password}@redis:6379/0')
    print(f'CELERY_RESULT_BACKEND=redis://:{redis_password}@redis:6379/1')
    print()

    print("# ==================================================================")
    print("# Next Steps:")
    print("# 1. Add these secrets to your .env file")
    print("# 2. Update docker-compose.yml and docker-compose.prod.yml to use these passwords")
    print("# 3. Encrypt sensitive files with: python scripts/encrypt_youtube_token.py")
    print("# 4. Restart all services: docker compose down && docker compose up -d")
    print("# ==================================================================")


if __name__ == "__main__":
    main()
