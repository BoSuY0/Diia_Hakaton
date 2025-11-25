"""Contracts repository abstraction with SQLite and MySQL backends."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sqlite3

from backend.domain.sessions.models import Session
from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

# Lazy import to avoid hard dependency on MySQL
try:
    from backend.infra.persistence.contracts_mysql import MySQLContractsRepository
except ImportError:
    MySQLContractsRepository = None  # type: ignore[misc,assignment]

logger = get_logger(__name__)


class _RepoState:
    """
    Module-level repository state container.

    Holds the singleton repository instance.
    """

    instance: Optional["ContractsRepository"] = None

    def reset(self) -> None:
        """Reset state for testing."""
        self.instance = None

    def is_initialized(self) -> bool:
        """Check if repository is initialized."""
        return self.instance is not None


_repo_state = _RepoState()


class ContractsRepository:
    """Abstract base class for contracts persistence."""

    def create_or_update(self, session: Session, payload: Dict[str, Any]) -> None:
        """Create or update a contract record."""
        raise NotImplementedError

    def get_by_session_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a contract by session ID."""
        raise NotImplementedError

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """List all contracts for a user."""
        raise NotImplementedError


class SQLiteContractsRepository(ContractsRepository):
    """SQLite-based contracts repository implementation."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.meta_users_documents_root / "contracts.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                session_id TEXT UNIQUE,
                category_id TEXT,
                template_id TEXT,
                state TEXT,
                owner_user_id TEXT,
                json_payload TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
        return conn

    def create_or_update(self, session: Session, payload: Dict[str, Any]) -> None:
        conn = self._conn()
        now = session.updated_at.isoformat()
        data = (
            f"{session.session_id}",
            session.session_id,
            session.category_id,
            session.template_id,
            session.state.value,
            session.creator_user_id,
            json.dumps(payload, ensure_ascii=False),
            now,
            now,
        )
        conn.execute(
            """
            INSERT INTO contracts
            (id, session_id, category_id, template_id, state,
             owner_user_id, json_payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                category_id=excluded.category_id,
                template_id=excluded.template_id,
                state=excluded.state,
                owner_user_id=excluded.owner_user_id,
                json_payload=excluded.json_payload,
                updated_at=excluded.updated_at
            """,
            data,
        )
        conn.commit()
        conn.close()

    def get_by_session_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT json_payload FROM contracts WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT session_id, category_id, template_id, state, json_payload, updated_at "
            "FROM contracts WHERE owner_user_id = ?",
            (user_id,),
        )
        rows = cur.fetchall()
        conn.close()
        result: List[Dict[str, Any]] = []
        for session_id, category_id, template_id, state, payload, updated_at in rows:
            try:
                payload_json = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload_json = {}
            result.append(
                {
                    "session_id": session_id,
                    "category_id": category_id,
                    "template_id": template_id,
                    "state": state,
                    "updated_at": updated_at,
                    "document": payload_json,
                }
            )
        return result


def get_contracts_repo() -> ContractsRepository:
    """Get or create the singleton contracts repository instance."""
    if _repo_state.instance is None:
        if (
            settings.contracts_db_url
            and settings.contracts_db_url.startswith("mysql")
            and MySQLContractsRepository is not None
        ):
            try:
                _repo_state.instance = MySQLContractsRepository(settings.contracts_db_url)
            except (OSError, ValueError, RuntimeError, ConnectionError) as exc:
                logger.error(
                    "Failed to init MySQLContractsRepository, fallback to SQLite: %s",
                    exc,
                )
                _repo_state.instance = SQLiteContractsRepository()
        else:
            _repo_state.instance = SQLiteContractsRepository()
    return _repo_state.instance
