"""CLI tool to manage Telegram user allowlist."""

import sys
from app.workers.db import get_sync_db
from app.models.telegram_user import TelegramUser


def add_user(user_id: int):
    """Add user to allowlist."""
    with get_sync_db() as db:
        user = db.get(TelegramUser, user_id)
        if user:
            user.is_allowed = True
            db.commit()
            print(f"✅ User {user_id} added to allowlist")
        else:
            print(f"❌ User {user_id} not found. They must use the bot first.")


def remove_user(user_id: int):
    """Remove user from allowlist."""
    with get_sync_db() as db:
        user = db.get(TelegramUser, user_id)
        if user:
            user.is_allowed = False
            db.commit()
            print(f"✅ User {user_id} removed from allowlist")
        else:
            print(f"❌ User {user_id} not found")


def list_users():
    """List all users."""
    from sqlalchemy import select
    with get_sync_db() as db:
        stmt = select(TelegramUser).order_by(TelegramUser.created_at.desc())
        users = db.execute(stmt).scalars().all()

        print("\nTelegram Users:")
        print("-" * 80)
        for u in users:
            status = "✅ ALLOWED" if u.is_allowed else "❌ BLOCKED"
            admin = " (ADMIN)" if u.is_admin else ""
            print(f"{u.user_id:<15} @{u.username:<20} {status}{admin} - {u.total_videos_requested} videos")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/manage_telegram_users.py add <user_id>")
        print("  python scripts/manage_telegram_users.py remove <user_id>")
        print("  python scripts/manage_telegram_users.py list")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        list_users()
    elif command == "add" and len(sys.argv) == 3:
        add_user(int(sys.argv[2]))
    elif command == "remove" and len(sys.argv) == 3:
        remove_user(int(sys.argv[2]))
    else:
        print("Invalid command")
        sys.exit(1)
