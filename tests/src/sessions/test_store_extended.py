import time

from src.sessions.store import get_or_create_session, save_session, load_session
from src.sessions.models import FieldState


def test_get_or_create_returns_session(mock_settings):
    sid = "store_create"
    s = get_or_create_session(sid)
    loaded = load_session(sid)
    assert loaded.session_id == s.session_id


def test_save_session_preserves_field_status(mock_settings):
    sid = "store_fields"
    s = get_or_create_session(sid)
    s.category_id = "cat"
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    save_session(s)

    loaded = load_session(sid)
    assert loaded.party_fields["lessor"]["name"].status == "ok"


def test_save_session_updates_timestamp(mock_settings):
    sid = "store_timestamp"
    s = get_or_create_session(sid)
    first = load_session(sid).updated_at
    time.sleep(0.01)
    save_session(s)
    second = load_session(sid).updated_at
    assert second > first
