"""CLI tool to manage API keys."""

import sys
import uuid
from app.workers.db import get_sync_db
from app.models.api_key import APIKey
from sqlalchemy import select


def create_key(name: str, rate_limit: int = 100):
    """Create a new API key."""
    with get_sync_db() as db:
        # Generate API key
        key_value = APIKey.generate_key()

        # Create database record
        api_key = APIKey(
            key=key_value,
            name=name,
            rate_limit=rate_limit,
            is_active=True,
        )

        db.add(api_key)
        db.commit()
        db.refresh(api_key)

        print(f"\n✅ API Key Created Successfully!")
        print("=" * 80)
        print(f"ID:          {api_key.id}")
        print(f"Name:        {api_key.name}")
        print(f"Rate Limit:  {api_key.rate_limit} requests/hour")
        print(f"API Key:     {key_value}")
        print("=" * 80)
        print("⚠️  SAVE THIS KEY - IT WON'T BE SHOWN AGAIN!")
        print()


def list_keys():
    """List all API keys."""
    with get_sync_db() as db:
        stmt = select(APIKey).order_by(APIKey.created_at.desc())
        keys = db.execute(stmt).scalars().all()

        if not keys:
            print("\nNo API keys found.")
            return

        print("\nAPI Keys:")
        print("=" * 120)
        print(f"{'ID':<38} {'Name':<25} {'Status':<12} {'Rate Limit':<15} {'Requests':<12} {'Total':<10}")
        print("-" * 120)

        for key in keys:
            status = "✅ ACTIVE" if key.is_active else "❌ INACTIVE"
            requests = f"{key.requests_this_hour}/{key.rate_limit}"
            print(
                f"{str(key.id):<38} "
                f"{key.name:<25} "
                f"{status:<12} "
                f"{key.rate_limit:<15} "
                f"{requests:<12} "
                f"{key.total_requests:<10}"
            )
        print()


def get_key_details(key_id: str):
    """Show detailed information about a specific API key."""
    with get_sync_db() as db:
        try:
            key_uuid = uuid.UUID(key_id)
            api_key = db.get(APIKey, key_uuid)

            if not api_key:
                print(f"❌ API key with ID {key_id} not found")
                return

            print(f"\nAPI Key Details:")
            print("=" * 80)
            print(f"ID:                {api_key.id}")
            print(f"Name:              {api_key.name}")
            print(f"Status:            {'✅ ACTIVE' if api_key.is_active else '❌ INACTIVE'}")
            print(f"Rate Limit:        {api_key.rate_limit} requests/hour")
            print(f"Requests This Hour: {api_key.requests_this_hour}/{api_key.rate_limit}")
            print(f"Total Requests:    {api_key.total_requests}")
            print(f"Last Used:         {api_key.last_used_at or 'Never'}")
            print(f"Created:           {api_key.created_at}")
            print(f"Updated:           {api_key.updated_at}")
            print()

        except ValueError:
            print(f"❌ Invalid UUID format: {key_id}")


def revoke_key(key_id: str):
    """Revoke (deactivate) an API key."""
    with get_sync_db() as db:
        try:
            key_uuid = uuid.UUID(key_id)
            api_key = db.get(APIKey, key_uuid)

            if not api_key:
                print(f"❌ API key with ID {key_id} not found")
                return

            if not api_key.is_active:
                print(f"⚠️  API key '{api_key.name}' is already inactive")
                return

            api_key.is_active = False
            db.commit()
            print(f"✅ API key '{api_key.name}' has been revoked")

        except ValueError:
            print(f"❌ Invalid UUID format: {key_id}")


def activate_key(key_id: str):
    """Activate a previously revoked API key."""
    with get_sync_db() as db:
        try:
            key_uuid = uuid.UUID(key_id)
            api_key = db.get(APIKey, key_uuid)

            if not api_key:
                print(f"❌ API key with ID {key_id} not found")
                return

            if api_key.is_active:
                print(f"⚠️  API key '{api_key.name}' is already active")
                return

            api_key.is_active = True
            db.commit()
            print(f"✅ API key '{api_key.name}' has been activated")

        except ValueError:
            print(f"❌ Invalid UUID format: {key_id}")


def delete_key(key_id: str):
    """Permanently delete an API key."""
    with get_sync_db() as db:
        try:
            key_uuid = uuid.UUID(key_id)
            api_key = db.get(APIKey, key_uuid)

            if not api_key:
                print(f"❌ API key with ID {key_id} not found")
                return

            # Confirm deletion
            confirm = input(f"⚠️  Are you sure you want to DELETE '{api_key.name}'? (yes/no): ")
            if confirm.lower() != "yes":
                print("Deletion cancelled")
                return

            db.delete(api_key)
            db.commit()
            print(f"✅ API key '{api_key.name}' has been permanently deleted")

        except ValueError:
            print(f"❌ Invalid UUID format: {key_id}")


def print_usage():
    """Print usage instructions."""
    print("Usage:")
    print("  python scripts/manage_api_keys.py create <name> [rate_limit]")
    print("  python scripts/manage_api_keys.py list")
    print("  python scripts/manage_api_keys.py get <id>")
    print("  python scripts/manage_api_keys.py revoke <id>")
    print("  python scripts/manage_api_keys.py activate <id>")
    print("  python scripts/manage_api_keys.py delete <id>")
    print()
    print("Examples:")
    print("  python scripts/manage_api_keys.py create \"Production API\" 1000")
    print("  python scripts/manage_api_keys.py create \"Dev Key\"")
    print("  python scripts/manage_api_keys.py list")
    print("  python scripts/manage_api_keys.py revoke 550e8400-e29b-41d4-a716-446655440000")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == "create":
        if len(sys.argv) < 3:
            print("❌ Missing required argument: name")
            print_usage()
            sys.exit(1)
        name = sys.argv[2]
        rate_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 100
        create_key(name, rate_limit)

    elif command == "list":
        list_keys()

    elif command == "get":
        if len(sys.argv) < 3:
            print("❌ Missing required argument: key_id")
            print_usage()
            sys.exit(1)
        get_key_details(sys.argv[2])

    elif command == "revoke":
        if len(sys.argv) < 3:
            print("❌ Missing required argument: key_id")
            print_usage()
            sys.exit(1)
        revoke_key(sys.argv[2])

    elif command == "activate":
        if len(sys.argv) < 3:
            print("❌ Missing required argument: key_id")
            print_usage()
            sys.exit(1)
        activate_key(sys.argv[2])

    elif command == "delete":
        if len(sys.argv) < 3:
            print("❌ Missing required argument: key_id")
            print_usage()
            sys.exit(1)
        delete_key(sys.argv[2])

    else:
        print(f"❌ Invalid command: {command}")
        print_usage()
        sys.exit(1)
