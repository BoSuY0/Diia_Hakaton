import json
import time

from src.sessions.store import (
    get_or_create_session,
    save_session,
    load_session,
    session_answers_path,
)
from src.sessions.models import FieldState


def test_get_or_create_creates_file(mock_settings):
    sid = "store_create"
    s = get_or_create_session(sid)
    path = session_answers_path(sid)
    assert path.exists()
    loaded = load_session(sid)
    assert loaded.session_id == s.session_id


def test_save_session_serializes_field_status_bool(mock_settings):
    sid = "store_fields"
    s = get_or_create_session(sid)
    s.category_id = "cat"
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    save_session(s)

    raw = json.loads(session_answers_path(sid).read_text(encoding="utf-8"))
    assert raw["party_fields"]["lessor"]["name"]["status"] is True


def test_save_session_updates_timestamp(mock_settings):
    sid = "store_timestamp"
    s = get_or_create_session(sid)
    save_session(s)
    path = session_answers_path(sid)
    first = json.loads(path.read_text(encoding="utf-8"))["updated_at"]
    time.sleep(0.01)
    save_session(load_session(sid))
    second = json.loads(path.read_text(encoding="utf-8"))["updated_at"]
    assert second > first
