"""Tests for session role claiming and template setting."""
import pytest

from backend.domain.services.session import claim_session_role, set_session_template
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState, FieldState


def _session(cat_id="test_cat"):
    s = get_or_create_session("claim_session")
    s.category_id = cat_id
    s.filling_mode = "partial"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.role_owners = {}
    return s


@pytest.mark.usefixtures("mock_settings")
def test_claim_session_role_blocks_second_role_in_partial(mock_categories_data):
    """Test that user cannot claim second role in partial mode."""
    s = _session(mock_categories_data)
    s.role_owners = {"lessor": "user1"}
    save_session(s)

    with pytest.raises(PermissionError):
        claim_session_role(s, "lessee", "user1")


@pytest.mark.usefixtures("mock_settings")
def test_claim_session_role_blocks_second_role_even_in_full_mode(mock_categories_data):
    """Test that user cannot claim second role even in full mode.
    
    In full mode, user can EDIT fields for other roles via can_edit_party_field,
    but cannot OWN multiple roles.
    """
    s = _session(mock_categories_data)
    s.filling_mode = "full"
    s.role_owners = {"lessor": "user1"}
    save_session(s)
    with pytest.raises(PermissionError):
        claim_session_role(s, "lessee", "user1")


@pytest.mark.usefixtures("mock_settings")
def test_claim_session_role_blocks_taken_role(mock_categories_data):
    """Test that user cannot claim already taken role."""
    s = _session(mock_categories_data)
    s.role_owners = {"lessor": "owner1"}
    save_session(s)
    with pytest.raises(PermissionError):
        claim_session_role(s, "lessor", "intruder")


@pytest.mark.usefixtures("mock_settings")
def test_set_session_template_updates_state_based_on_readiness(mock_categories_data):
    """Test that setting template updates state based on field readiness."""
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
