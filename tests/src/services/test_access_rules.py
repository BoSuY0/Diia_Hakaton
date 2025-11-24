import pytest

from backend.domain.services.session import can_edit_party_field, can_edit_contract_field
from backend.infra.persistence.store import get_or_create_session
from backend.domain.sessions.models import SessionState


def _session_with_category(session_id: str, category_id: str, creator: str = "creator"):
    s = get_or_create_session(session_id, creator)
    s.category_id = category_id
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.state = SessionState.TEMPLATE_SELECTED
    return s


def test_creator_full_can_prefill_free_roles(mock_settings, mock_categories_data):
    s = _session_with_category("acl_full_prefill", mock_categories_data, creator="user1")
    s.filling_mode = "full"
    # No owners yet -> creator can edit both roles
    assert can_edit_party_field(s, acting_user_id="user1", target_role="lessor") is True
    assert can_edit_party_field(s, acting_user_id="user1", target_role="lessee") is True


def test_creator_blocked_after_role_claim(mock_settings, mock_categories_data):
    s = _session_with_category("acl_role_claim", mock_categories_data, creator="user1")
    s.filling_mode = "full"
    s.role_owners = {"lessee": "user2"}
    # Creator cannot edit claimed role
    assert can_edit_party_field(s, acting_user_id="user1", target_role="lessee") is False
    # Owner can edit their own role
    assert can_edit_party_field(s, acting_user_id="user2", target_role="lessee") is True


def test_contract_fields_access(mock_settings, mock_categories_data):
    s = _session_with_category("acl_contract", mock_categories_data, creator="creator")
    # No owners -> only creator can edit contract
    assert can_edit_contract_field(s, acting_user_id="creator", field_name="cf1") is True
    assert can_edit_contract_field(s, acting_user_id="stranger", field_name="cf1") is False

    # After role claimed -> participant can edit
    s.role_owners = {"lessor": "user1"}
    assert can_edit_contract_field(s, acting_user_id="user1", field_name="cf1") is True
    assert can_edit_contract_field(s, acting_user_id="stranger", field_name="cf1") is False
