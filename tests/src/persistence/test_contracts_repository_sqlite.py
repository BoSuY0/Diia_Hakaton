"""Tests for SQLite contracts repository."""
from pathlib import Path

from backend.infra.persistence.contracts_repository import SQLiteContractsRepository
from backend.domain.sessions.models import Session, SessionState


def _session(session_id: str = "s1") -> Session:
    """Create a test session."""
    return Session(session_id=session_id, creator_user_id="owner", state=SessionState.BUILT)


def test_sqlite_contracts_repo_roundtrip(tmp_path: Path):
    """Test SQLite contracts repository roundtrip."""
    db_path = tmp_path / "contracts.db"
    repo = SQLiteContractsRepository(db_path)

    sess = _session("sess_sqlite")
    payload = {"foo": "bar", "nested": {"a": 1}}
    repo.create_or_update(sess, payload)

    loaded = repo.get_by_session_id("sess_sqlite")
    assert loaded == payload

    # Update with new template/state
    sess.template_id = "t1"
    sess.state = SessionState.COMPLETED
    payload2 = {"foo": "baz"}
    repo.create_or_update(sess, payload2)
    loaded2 = repo.get_by_session_id("sess_sqlite")
    assert loaded2 == payload2

    # List for user
    items = repo.list_for_user("owner")
    assert any(i["session_id"] == "sess_sqlite" for i in items)
