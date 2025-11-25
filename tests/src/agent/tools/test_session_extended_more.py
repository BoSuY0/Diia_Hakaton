"""Extended tests for session tools."""
import pytest
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_upsert_contract_field_validation_error(mock_categories_data):
    """Test that upserting empty contract field returns validation error."""
    s = _session_with_category(mock_categories_data)
    s.role_owners = {"lessor": "user1"}
    save_session(s)
    tool = UpsertFieldTool()
    res = await tool.execute(
        {"session_id": s.session_id, "field": "cf1", "value": ""},
        {"user_id": "user1"},
    )
    assert res["ok"] is False
    assert res["field_state"]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_upsert_requires_person_type_for_party_field(mock_categories_data):
    """Test upsert behavior when person_type is not set."""
    s = _session_with_category(mock_categories_data)
    s.person_type = None
    s.party_types = {}
    s.role_owners = {"lessor": "user1"}
    save_session(s)
    tool = UpsertFieldTool()
    res = await tool.execute(
        {"session_id": s.session_id, "field": "name", "value": "X"},
        {"user_id": "user1"},
    )
    assert res["ok"] is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_build_contract_tool_sets_state(mock_categories_data, monkeypatch):
    """Test that build contract tool sets session state to BUILT."""
    s = _session_with_category(mock_categories_data)
    save_session(s)
    tool = BuildContractTool()

    # Patch builder to avoid heavy work
    async def fake_build(session_id, template_id):
        return {"file_path": "x"}

    monkeypatch.setattr(
        "backend.agent.tools.session.build_contract_document",
        fake_build,
    )
    res = await tool.execute({"session_id": s.session_id, "template_id": "t1"}, {})
    assert res["file_path"] == "x"
    from backend.infra.persistence.store import load_session
    loaded = load_session(s.session_id)
    assert loaded.state == SessionState.BUILT


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_sign_contract_tool_requires_state(mock_categories_data):
    """Test that sign contract tool requires proper session state."""
    s = _session_with_category(mock_categories_data)
    s.state = SessionState.CATEGORY_SELECTED
    save_session(s)
    tool = SignContractTool()
    res = await tool.execute({"session_id": s.session_id}, {"user_id": "owner1"})
    assert res["ok"] is False
    assert "не можна підписати" in res["error"].lower()
