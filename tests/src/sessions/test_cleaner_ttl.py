"""Tests for session TTL-based cleanup."""
import json
from datetime import datetime, timedelta, timezone

from backend.domain.sessions.cleaner import clean_stale_sessions
from backend.domain.sessions.models import SessionState


def _write_session(settings, session_id: str, state: SessionState, hours_ago: int):
    """Helper to write test session file."""
    payload = {
        "session_id": session_id,
        "state": state.value,
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(),
    }
    path = settings.sessions_root / f"{session_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_clean_stale_sessions_respects_ttl(mock_settings):
    """Test clean_stale_sessions respects TTL settings."""
    mock_settings.session_backend = "fs"

    draft_hours = mock_settings.draft_ttl_hours + 1
    draft_path = _write_session(
        mock_settings, "stale_draft", SessionState.IDLE, hours_ago=draft_hours
    )

    completed_hours = (mock_settings.signed_ttl_days * 24) + 10
    completed_path = _write_session(
        mock_settings, "stale_completed", SessionState.COMPLETED,
        hours_ago=completed_hours
    )

    fresh_path = _write_session(
        mock_settings, "fresh_filled", SessionState.READY_TO_SIGN, hours_ago=1
    )

    clean_stale_sessions()

    assert not draft_path.exists()
    assert not completed_path.exists()
    assert fresh_path.exists()
