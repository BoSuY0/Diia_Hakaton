import pytest
from backend.agent.tools.session import (
    SetPartyContextTool,
    UpsertFieldTool,
    GetPartyFieldsForSessionTool,
    GetSessionSummaryTool
)
from backend.infra.persistence.store import get_or_create_session, load_session
from backend.domain.sessions.models import SessionState

@pytest.fixture
def session_with_category(mock_settings, mock_categories_data):
    # mock_categories_data creates "test_cat" with "individual" party module
    session_id = "tool_test_session"
    s = get_or_create_session(session_id)
    s.category_id = "test_cat"
    from backend.infra.persistence.store import save_session
    save_session(s)
    return session_id

def test_set_party_context(session_with_category):
    tool = SetPartyContextTool()
    res = tool.execute({
        "session_id": session_with_category,
        "role": "lessor",
        "person_type": "individual"
    }, {"user_id": "tool_user"})
    
    assert res["ok"] is True
    assert res["role"] == "lessor"
    
    s = load_session(session_with_category)
    assert s.role == "lessor"
    assert s.person_type == "individual"
    assert s.party_types["lessor"] == "individual"

def test_upsert_field_party(session_with_category):
    # First set context
    SetPartyContextTool().execute({
        "session_id": session_with_category,
        "role": "lessor",
        "person_type": "individual"
    }, {"user_id": "tool_user"})
    
    tool = UpsertFieldTool()
    res = tool.execute({
        "session_id": session_with_category,
        "field": "name",
        "value": "John Doe"
    }, {"user_id": "tool_user"})
    
    assert res["ok"] is True
    assert res["status"] == "ok"
    
    s = load_session(session_with_category)
    assert s.party_fields["lessor"]["name"].status == "ok"
    assert s.all_data["lessor.name"]["current"] == "John Doe"

def test_upsert_field_contract(session_with_category):
    # "cf1" is a contract field in mock_categories_data
    SetPartyContextTool().execute(
        {
            "session_id": session_with_category,
            "role": "lessor",
            "person_type": "individual",
        },
        {"user_id": "tool_user"},
    )
    tool = UpsertFieldTool()
    res = tool.execute({
        "session_id": session_with_category,
        "field": "cf1",
        "value": "Contract Value"
    }, {"user_id": "tool_user"})
    
    assert res["ok"] is True
    
    s = load_session(session_with_category)
    assert s.contract_fields["cf1"].status == "ok"
    assert s.all_data["cf1"]["current"] == "Contract Value"

def test_get_party_fields(session_with_category):
    SetPartyContextTool().execute({
        "session_id": session_with_category,
        "role": "lessor",
        "person_type": "individual"
    }, {"user_id": "tool_user"})
    
    tool = GetPartyFieldsForSessionTool()
    res = tool.execute({"session_id": session_with_category}, {})
    
    assert res["ok"] is True
    assert len(res["fields"]) == 1
    assert res["fields"][0]["field"] == "name"

def test_get_session_summary(session_with_category):
    tool = GetSessionSummaryTool()
    res = tool.execute({"session_id": session_with_category}, {})
    
    assert res["session_id"] == session_with_category
    assert "party_fields" in res
    assert "contract_fields" in res
