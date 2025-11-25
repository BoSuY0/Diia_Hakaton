import json
from datetime import datetime, timedelta, timezone

from backend.domain.sessions.cleaner import clean_stale_sessions
from backend.domain.sessions.models import SessionState


def _write_session(settings, session_id: str, state: SessionState, hours_ago: int):
    payload = {
        "session_id": session_id,
        "state": state.value,
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(),
    }
    path = settings.sessions_root / f"{session_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_clean_stale_sessions_respects_ttl(mock_settings):
    # Switch cleaner to filesystem backend for the test
    mock_settings.session_backend = "fs"

    # Draft older than draft_ttl_hours -> should be deleted
    draft_path = _write_session(mock_settings, "stale_draft", SessionState.IDLE, hours_ago=mock_settings.draft_ttl_hours + 1)

    # Completed older than signed_ttl_days -> should be deleted
    completed_hours = (mock_settings.signed_ttl_days * 24) + 10
    completed_path = _write_session(mock_settings, "stale_completed", SessionState.COMPLETED, hours_ago=completed_hours)

    # Recent filled session should stay
    fresh_path = _write_session(mock_settings, "fresh_filled", SessionState.READY_TO_SIGN, hours_ago=1)

    clean_stale_sessions()

    assert not draft_path.exists()
    assert not completed_path.exists()
    assert fresh_path.exists()
