from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from backend.infra.config.settings import settings
from backend.domain.sessions.models import Session

DB_PATH: Path = settings.meta_users_documents_root / "contracts.db"


def _ensure_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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


def create_or_update_contract(session: Session, payload: Dict[str, Any]) -> None:
    conn = _ensure_db()
    now = datetime.utcnow().isoformat() + "Z"
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
        INSERT INTO contracts (id, session_id, category_id, template_id, state, owner_user_id, json_payload, created_at, updated_at)
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


def get_contract_by_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = _ensure_db()
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
    except Exception:
        return None


def list_contracts_for_user(user_id: str) -> List[Dict[str, Any]]:
    conn = _ensure_db()
    cur = conn.execute(
        "SELECT session_id, category_id, template_id, state, json_payload, updated_at FROM contracts WHERE owner_user_id = ?",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    result: List[Dict[str, Any]] = []
    for session_id, category_id, template_id, state, payload, updated_at in rows:
        try:
            payload_json = json.loads(payload)
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
