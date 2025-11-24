import pytest
from backend.domain.sessions.models import Session, FieldState, SessionState

def test_field_state_default():
    fs = FieldState()
    assert fs.status == "empty"
    assert fs.error is None

def test_session_default():
    s = Session(session_id="123")
    assert s.session_id == "123"
    assert s.state == SessionState.IDLE
    assert s.party_fields == {}
    assert s.contract_fields == {}
    assert s.can_build_contract is False

def test_session_nested_party_fields():
    s = Session(session_id="123")
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    assert s.party_fields["lessor"]["name"].status == "ok"
