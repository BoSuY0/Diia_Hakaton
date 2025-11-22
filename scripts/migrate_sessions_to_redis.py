from __future__ import annotations

import argparse
import asyncio
import sys

from src.common.config import settings
from src.sessions.store_utils import _from_dict
from src.sessions import store_redis
from src.storage.fs import read_json


async def migrate_async(delete_files: bool = False) -> None:
    sessions_dir = settings.sessions_root
    if settings.session_backend != "redis":
        print("SESSION_BACKEND is not set to 'redis'; aborting to avoid accidental writes.", file=sys.stderr)
        sys.exit(1)

    if not settings.redis_url:
        print("REDIS_URL is not configured.", file=sys.stderr)
        sys.exit(1)

    if not sessions_dir.exists():
        print(f"Sessions directory does not exist: {sessions_dir}")
        return

    migrated = 0
    for path in sessions_dir.glob("session_*.json"):
        try:
            data = read_json(path)
            session = _from_dict(data)
            await store_redis.save_session(session)
            migrated += 1
            if delete_files:
                path.unlink()
        except Exception as exc:
            print(f"Failed to migrate {path.name}: {exc}", file=sys.stderr)

    print(f"Migrated {migrated} sessions to Redis")


def migrate(delete_files: bool = False) -> None:
    asyncio.run(migrate_async(delete_files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate file-based sessions into Redis")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete JSON session files after successful migration.",
    )
    args = parser.parse_args()
    migrate(delete_files=args.delete)
