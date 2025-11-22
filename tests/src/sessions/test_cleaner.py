import json
from datetime import datetime, timedelta

from src.sessions.cleaner import clean_stale_sessions, clean_abandoned_sessions
from src.sessions.models import SessionState
from src.storage.fs import session_answers_path


def _write_session_file(path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_clean_stale_sessions_removes_old_drafts(mock_settings):
    sid = "old_session"
    path = session_answers_path(sid)
    old_time = (datetime.now() - timedelta(hours=2)).isoformat()
    data = {
        "session_id": sid,
        "state": SessionState.IDLE.value,
        "updated_at": old_time,
    }
    _write_session_file(path, data)

    clean_stale_sessions(max_age_hours=1)
    assert not path.exists()


def test_clean_stale_sessions_keeps_ready_to_sign(mock_settings):
    sid = "important_session"
    path = session_answers_path(sid)
    old_time = (datetime.now() - timedelta(hours=48)).isoformat()
    data = {
        "session_id": sid,
        "state": SessionState.READY_TO_SIGN.value,
        "updated_at": old_time,
    }
    _write_session_file(path, data)

    clean_stale_sessions(max_age_hours=1)
    assert path.exists()


def test_clean_abandoned_sessions_removes_empty_and_old(mock_settings):
    sid = "abandoned"
    path = session_answers_path(sid)
    old_time = (datetime.now() - timedelta(minutes=10)).isoformat()
    data = {
        "session_id": sid,
        "state": SessionState.IDLE.value,
        "updated_at": old_time,
        "all_data": {},
    }
    _write_session_file(path, data)

    clean_abandoned_sessions(active_session_ids=set(), grace_period_minutes=1)
    assert not path.exists()


def test_clean_abandoned_sessions_keep_with_data(mock_settings):
    sid = "active_data"
    path = session_answers_path(sid)
    old_time = (datetime.now() - timedelta(minutes=10)).isoformat()
    data = {
        "session_id": sid,
        "state": SessionState.IDLE.value,
        "updated_at": old_time,
        "all_data": {"x": {"current": "val"}},
    }
    _write_session_file(path, data)

    clean_abandoned_sessions(active_session_ids=set(), grace_period_minutes=1)
    assert path.exists()
