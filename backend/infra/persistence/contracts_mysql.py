from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pymysql
from urllib.parse import urlparse

from backend.domain.sessions.models import Session
from backend.shared.logging import get_logger

logger = get_logger(__name__)


class MySQLContractsRepository:
    def __init__(self, dsn: str) -> None:
        self.params = self._parse_dsn(dsn)
        self._ensure_table()

    def _parse_dsn(self, dsn: str) -> dict:
        parsed = urlparse(dsn)
        if parsed.scheme not in ("mysql", "mysql+pymysql"):
            raise ValueError("Unsupported DSN scheme for MySQL")
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": (parsed.path or "/").lstrip("/"),
            "autocommit": True,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.Cursor,
        }

    def _conn(self):
        return pymysql.connect(**self.params)

    def _ensure_table(self) -> None:
        try:
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contracts (
                        session_id VARCHAR(255) PRIMARY KEY,
                        owner_user_id VARCHAR(255) NOT NULL,
                        category_id VARCHAR(255),
                        template_id VARCHAR(255),
                        state VARCHAR(64),
                        json_body JSON NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    ) CHARACTER SET utf8mb4;
                    """
                )
            conn.close()
        except Exception as exc:
            logger.error("Failed to ensure contracts table: %s", exc)
            raise

    def create_or_update(self, session: Session, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contracts (session_id, owner_user_id, category_id, template_id, state, json_body, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        owner_user_id=VALUES(owner_user_id),
                        category_id=VALUES(category_id),
                        template_id=VALUES(template_id),
                        state=VALUES(state),
                        json_body=VALUES(json_body),
                        updated_at=VALUES(updated_at)
                    """,
                    (
                        session.session_id,
                        session.creator_user_id,
                        session.category_id,
                        session.template_id,
                        session.state.value,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        finally:
            conn.close()

    def get_by_session_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT json_body FROM contracts WHERE session_id=%s",
                    (session_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return json.loads(row[0])
        finally:
            conn.close()

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT session_id, category_id, template_id, state, json_body, updated_at FROM contracts WHERE owner_user_id=%s ORDER BY updated_at DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
                result: List[Dict[str, Any]] = []
                for session_id, category_id, template_id, state, body, updated_at in rows:
                    try:
                        payload_json = json.loads(body)
                    except Exception:
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
        finally:
            conn.close()
