import pytest
from unittest.mock import patch

from backend.agent.tools.session import (
    UpsertFieldTool,
    BuildContractTool,
    SignContractTool,
)
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState, FieldState


def _session_with_category(cat_id: str):
    s = get_or_create_session(f"sess_{cat_id}")
    s.category_id = cat_id
    s.template_id = "t1"
    s.role = "lessor"
    s.person_type = "individual"
    s.party_types = {"lessor": "individual"}
    return s


def test_upsert_contract_field_validation_error(mock_settings, mock_categories_data):
    s = _session_with_category(mock_categories_data)
    s.role_owners = {"lessor": "user1"}
    save_session(s)
    tool = UpsertFieldTool()
    res = tool.execute(
        {"session_id": s.session_id, "field": "cf1", "value": ""},
        {"client_id": "user1"},
    )
    assert res["ok"] is False
    assert res["field_state"]["status"] == "error"


def test_upsert_requires_person_type_for_party_field(mock_settings, mock_categories_data):
    s = _session_with_category(mock_categories_data)
    s.person_type = None
    s.party_types = {}
    s.role_owners = {"lessor": "user1"}
    save_session(s)
    tool = UpsertFieldTool()
    res = tool.execute(
        {"session_id": s.session_id, "field": "name", "value": "X"},
        {"client_id": "user1"},
    )
    assert res["ok"] is False
    assert "тип" in res["error"].lower()


def test_build_contract_tool_sets_state(mock_settings, mock_categories_data, monkeypatch):
    s = _session_with_category(mock_categories_data)
    save_session(s)
    tool = BuildContractTool()

    # Patch builder to avoid heavy work
    monkeypatch.setattr(
        "backend.agent.tools.session.build_contract_document",
        lambda session_id, template_id: {"file_path": "x"},
    )
    res = tool.execute({"session_id": s.session_id, "template_id": "t1"}, {})
    assert res["file_path"] == "x"
    from backend.infra.persistence.store import load_session
    loaded = load_session(s.session_id)
    assert loaded.state == SessionState.BUILT


def test_sign_contract_tool_requires_state(mock_settings, mock_categories_data):
    s = _session_with_category(mock_categories_data)
    s.state = SessionState.CATEGORY_SELECTED
    save_session(s)
    tool = SignContractTool()
    res = tool.execute({"session_id": s.session_id}, {"user_id": "owner1"})
    assert res["ok"] is False
    assert "не можна підписати" in res["error"].lower()
