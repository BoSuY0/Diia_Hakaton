from src.sessions.actions import set_session_category
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import SessionState, FieldState


def test_set_session_category_resets_state_and_data(mock_settings, mock_categories_data):
    s = get_or_create_session("action_reset")
    s.category_id = mock_categories_data
    s.template_id = "old_t"
    s.state = SessionState.BUILT
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    s.contract_fields["cf1"] = FieldState(status="ok")
    s.party_types["lessor"] = "individual"
    s.party_users["lessor"] = "user1"
    s.signatures["lessor"] = True
    s.progress = {"required_total": 5}
    save_session(s)

    set_session_category(s, mock_categories_data)  # same id, but should still reset internals

    assert s.template_id is None
    assert s.state == SessionState.CATEGORY_SELECTED
    assert s.party_fields == {}
    assert s.contract_fields == {}
    assert s.party_types == {}
    assert s.party_users == {}
    assert s.signatures == {}
    assert s.can_build_contract is False
    assert s.progress == {}
