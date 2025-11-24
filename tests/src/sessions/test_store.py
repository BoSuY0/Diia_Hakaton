import pytest
from backend.infra.persistence.store import get_or_create_session, load_session, save_session
from backend.domain.sessions.models import Session, FieldState

def test_get_or_create_new(mock_settings):
    
    s = get_or_create_session("new_session")
    assert s.session_id == "new_session"
    assert (mock_settings.sessions_root / "session_new_session.json").exists()

def test_save_and_load(mock_settings):
    s = Session(session_id="test_save")
    s.category_id = "cat1"
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    save_session(s)
    
    loaded = load_session("test_save")
    assert loaded.category_id == "cat1"
    assert loaded.party_fields["lessor"]["name"].status == "ok"

def test_load_not_found(mock_settings):
    from backend.shared.errors import SessionNotFoundError
    with pytest.raises(SessionNotFoundError):
        load_session("non_existent")
