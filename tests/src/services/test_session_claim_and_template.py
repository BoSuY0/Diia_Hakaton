import pytest

from src.services.session import claim_session_role, set_session_template
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import SessionState, FieldState


def _session(cat_id="test_cat"):
    s = get_or_create_session("claim_session")
    s.category_id = cat_id
    s.filling_mode = "partial"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    return s


def test_claim_session_role_blocks_second_role_in_partial(mock_settings, mock_categories_data):
    s = _session(mock_categories_data)
    s.party_users = {"lessor": "user1"}
    save_session(s)

    ok = claim_session_role(s, "lessee", "user1")
    assert ok is False


def test_claim_session_role_allows_second_role_in_full_mode(mock_settings, mock_categories_data):
    s = _session(mock_categories_data)
    s.filling_mode = "full"
    s.party_users = {"lessor": "user1"}
    save_session(s)
    ok = claim_session_role(s, "lessee", "user1")
    assert ok is True


def test_claim_session_role_blocks_taken_role(mock_settings, mock_categories_data):
    s = _session(mock_categories_data)
    s.party_users = {"lessor": "owner1"}
    save_session(s)
    ok = claim_session_role(s, "lessor", "intruder")
    assert ok is False


def test_set_session_template_updates_state_based_on_readiness(mock_settings, mock_categories_data):
    s = _session(mock_categories_data)
    s.template_id = None
    # Fill all required fields to be ready
    s.contract_fields["cf1"] = FieldState(status="ok")
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    s.role = "lessor"
    save_session(s)

    set_session_template(s, "t1")
    # Because required fields filled, state should be READY_TO_BUILD
    assert s.template_id == "t1"
    assert s.state in {SessionState.TEMPLATE_SELECTED, SessionState.READY_TO_BUILD}
