from backend.domain.sessions.models import Session, SessionState


def test_is_fully_signed_requires_party_types():
    s = Session(session_id="s1")
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.signatures = {"lessor": True}
    assert s.is_fully_signed is False
    s.signatures["lessee"] = True
    assert s.is_fully_signed is True


def test_filling_mode_default_and_state_change():
    s = Session(session_id="s2")
    assert s.filling_mode == "partial"
    s.state = SessionState.READY_TO_BUILD
    assert s.state == SessionState.READY_TO_BUILD
