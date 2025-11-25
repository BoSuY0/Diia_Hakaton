"""
Міграція користувацьких документів із файлового сховища у contracts repository
(SQLite або MySQL залежно від CONTRACTS_DB_URL).

Usage:
  python tools/migrate_contracts_to_db.py [--root /path/to/meta_data_users/documents] [--dry-run]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from backend.domain.sessions.models import Session, SessionState
from backend.infra.config.settings import settings
from backend.infra.persistence.contracts_repository import get_contracts_repo
from backend.infra.storage.fs import read_json
from backend.shared.logging import get_logger

logger = get_logger(__name__)


def _load_session_stub(session_id: str, payload: dict) -> Session:
    """
    Повертає мінімальний Session для запису в репозиторій контрактів.
    Якщо реальна сесія недоступна, використовуємо дані з user-document.
    """
    state = SessionState.COMPLETED if payload.get("status") == "built" else SessionState.IDLE
    return Session(
        session_id=session_id,
        category_id=payload.get("category_id"),
        template_id=payload.get("template_id"),
        state=state,
    )


def migrate(root: Path, dry_run: bool = False) -> None:
    """Migrate user-documents from filesystem to contracts repository."""
    repo = get_contracts_repo()
    files = sorted(root.glob("*.json"))
    if not files:
        logger.info("No JSON user-documents found under %s", root)
        return

    migrated = 0
    for path in files:
        session_id = path.stem
        try:
            payload = read_json(path)
        except (OSError, ValueError, KeyError) as exc:
            logger.error("Failed to read %s: %s", path, exc)
            continue

        session = _load_session_stub(session_id, payload)
        if dry_run:
            logger.info("DRY-RUN would migrate session_id=%s", session_id)
            migrated += 1
            continue

        try:
            repo.create_or_update(session, payload)
            migrated += 1
            logger.info("Migrated session_id=%s", session_id)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.error("Failed to migrate %s: %s", session_id, exc)

    logger.info("Migration finished: %s document(s) processed", migrated)


def main(args: Optional[list[str]] = None) -> None:
    """Main entry point for contracts migration CLI."""
    parser = argparse.ArgumentParser(
        description="Migrate user-documents into contracts repository",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=settings.meta_users_documents_root,
        help="Root folder with user-document JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan files without writing to repository",
    )
    ns = parser.parse_args(args=args)
    migrate(ns.root, dry_run=ns.dry_run)


if __name__ == "__main__":  # pragma: no cover - manual utility
    main()
