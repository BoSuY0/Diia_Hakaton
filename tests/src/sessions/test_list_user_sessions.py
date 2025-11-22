import json

from src.sessions.store import list_user_sessions, session_answers_path


def _write_session(mock_settings, session_id, party_users, updated_at="2024-01-01T00:00:00"):
    path = session_answers_path(session_id)
    data = {
        "session_id": session_id,
        "party_users": party_users,
        "updated_at": updated_at,
        "state": "idle",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_list_user_sessions_returns_sorted(mock_settings):
    _write_session(mock_settings, "s1", {"lessor": "user1"}, updated_at="2024-01-01T00:00:00")
    _write_session(mock_settings, "s2", {"lessee": "user1"}, updated_at="2024-01-02T00:00:00")
    _write_session(mock_settings, "s3", {"lessor": "other"}, updated_at="2024-01-03T00:00:00")

    sessions = list_user_sessions("user1")
    ids = [s.session_id for s in sessions]
    # Should include only s1 and s2 sorted by updated_at desc -> s2 first
    assert ids == ["s2", "s1"]
