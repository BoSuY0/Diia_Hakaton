"""Regression coverage for recent backend plan items."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.api.http import server
from backend.api.http.state import conversation_store
from backend.domain.categories.index import clear_meta_cache, load_meta, store as category_store
from backend.domain.sessions.models import FieldState, SessionState
from backend.infra.persistence.store import get_or_create_session, load_session, save_session
from tests.conftest import create_category_meta


def _prepare_category(mock_settings, *, cat_id: str = "plan_cat") -> str:
    """Create a category with two roles and a single required contract field."""
    create_category_meta(
        mock_settings,
        cat_id=cat_id,
        roles={
            "lessor": {"label": "Lessor", "allowed_person_types": ["individual"]},
            "lessee": {"label": "Lessee", "allowed_person_types": ["individual"]},
        },
        party_modules={
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            }
        },
        contract_fields=[{"field": "cf1", "label": "CF1", "required": True}],
    )
    category_store.clear()
    category_store.load()
    return cat_id


@pytest.mark.usefixtures("mock_settings")
def test_status_effective_consistent_across_endpoints(mock_categories_data):
    """status_effective should align between list and contract details."""
    client = TestClient(server.app)
    session_id = "status_effective_case"

    session = get_or_create_session(session_id, creator_user_id="owner1")
    session.category_id = mock_categories_data
    session.template_id = "t1"
    session.party_types = {"lessor": "individual", "lessee": "individual"}
    session.role_owners = {"lessor": "user1", "lessee": "user2"}
    session.state = SessionState.READY_TO_SIGN
    session.signatures = {"lessor": False, "lessee": True}
    save_session(session)

    headers = {"X-User-ID": "user1"}

    list_resp = client.get("/my-sessions", headers=headers)
    assert list_resp.status_code == 200
    records = [item for item in list_resp.json() if item["session_id"] == session_id]
    assert records, "session should be returned in my-sessions"
    list_status = records[0]["status_effective"]
    assert records[0]["is_signed"] is False

    contract_resp = client.get(f"/sessions/{session_id}/contract", headers=headers)
    assert contract_resp.status_code == 200
    contract_data = contract_resp.json()
    assert contract_data["status_effective"] == list_status
    assert contract_data["is_signed"] is False

    # Mark fully signed and ensure canonical status switches to completed everywhere
    session = get_or_create_session(session_id, creator_user_id="owner1")
    session.signatures = {"lessor": True, "lessee": True}
    save_session(session)

    list_resp = client.get("/my-sessions", headers=headers)
    records = [item for item in list_resp.json() if item["session_id"] == session_id]
    assert records[0]["status_effective"] == "completed"

    contract_resp = client.get(f"/sessions/{session_id}/contract", headers=headers)
    assert contract_resp.status_code == 200
    assert contract_resp.json()["is_signed"] is True


@pytest.mark.usefixtures("mock_settings")
def test_chat_reset_clears_history(monkeypatch):
    """`reset=True` should drop previous conversation context."""
    client = TestClient(server.app)
    session_id = "chat_reset_case"
    conversation_store.reset(session_id)

    class _Msg:
        def __init__(self, content):
            self.role = "assistant"
            self.content = content
            self.tool_calls = None

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    def fake_chat(messages, tools, require_tools=False, max_completion_tokens=None):  # noqa: ARG001
        return _Resp("ok")

    monkeypatch.setattr(server, "chat_with_tools", fake_chat)
    monkeypatch.setattr(server, "chat_with_tools_async", fake_chat)

    first = client.post("/chat", json={"session_id": session_id, "message": "Hi"})
    assert first.status_code == 200
    conv_first = conversation_store.get(session_id)
    assert conv_first.messages, "Conversation should store messages after first call"

    second = client.post(
        "/chat", json={"session_id": session_id, "message": "New start", "reset": True}
    )
    assert second.status_code == 200
    conv_second = conversation_store.get(session_id)
    assert conv_second is not conv_first  # reset creates a fresh Conversation instance
    assert any(
        m.get("content") == "New start" for m in conv_second.messages if isinstance(m, dict)
    )


@pytest.mark.usefixtures("mock_settings")
def test_requirements_self_vs_all_and_order_block(mock_settings):
    """User-ready does not imply full readiness; order should reject when others are empty."""
    cat_id = _prepare_category(mock_settings, cat_id="req_plan_cat")
    client = TestClient(server.app)
    session_id = "req_scope_case"

    session = get_or_create_session(session_id, creator_user_id="owner1")
    session.category_id = cat_id
    session.template_id = "t1"
    session.filling_mode = "partial"
    session.role = "lessor"
    session.person_type = "individual"
    session.party_types = {"lessor": "individual", "lessee": "individual"}
    session.role_owners = {"lessor": "u1", "lessee": "u2"}
    session.contract_fields = {"cf1": FieldState(status="ok")}
    session.party_fields = {
        "lessor": {"name": FieldState(status="ok")},
        "lessee": {},
    }
    save_session(session)

    headers = {"X-User-ID": "u1"}
    req_resp = client.get(f"/sessions/{session_id}/requirements", headers=headers)
    assert req_resp.status_code == 200
    payload = req_resp.json()
    assert payload["is_ready_self"] is True
    assert payload["is_ready_all"] is False

    order_resp = client.post(f"/sessions/{session_id}/order", headers=headers)
    assert order_resp.status_code == 400
    detail = order_resp.json()["detail"]
    assert detail["is_ready_all"] is False
    assert detail["is_ready_self"] is True


@pytest.mark.usefixtures("mock_settings")
def test_category_meta_cache_and_clear(mock_settings):
    """load_meta should serve cached data until cache is cleared."""
    cat_id = "cache_plan_cat"
    meta_path, _ = create_category_meta(
        mock_settings,
        cat_id=cat_id,
        templates=[{"id": "t1", "name": "Old Name", "file": "f1.docx"}],
    )
    category_store.clear()
    category_store.load()
    cat = category_store.get(cat_id)
    meta_1 = load_meta(cat)
    assert meta_1["templates"][0]["name"] == "Old Name"

    # Mutate file on disk; cached read should stay the same
    meta_path.write_text(
        json.dumps(
            {
                "category_id": cat_id,
                "templates": [{"id": "t1", "name": "New Name", "file": "f1.docx"}],
                "roles": {},
                "party_modules": {},
                "contract_fields": [],
            }
        ),
        encoding="utf-8",
    )
    meta_2 = load_meta(cat)
    assert meta_2["templates"][0]["name"] == "Old Name"

    clear_meta_cache(cat_id)
    meta_3 = load_meta(cat)
    assert meta_3["templates"][0]["name"] == "New Name"


@pytest.mark.usefixtures("mock_settings")
def test_lightweight_upsert_skips_full_recalc(mock_settings):
    """lightweight=True updates field state but defers heavy readiness recalculation."""
    cat_id = _prepare_category(mock_settings, cat_id="light_plan_cat")
    client = TestClient(server.app)
    session_id = "lightweight_case"

    session = get_or_create_session(session_id, creator_user_id="owner1")
    session.category_id = cat_id
    session.template_id = "t1"
    session.role = "lessor"
    session.person_type = "individual"
    session.party_types = {"lessor": "individual", "lessee": "individual"}
    session.role_owners = {"lessor": "u1", "lessee": "u2"}
    session.party_fields = {
        "lessor": {"name": FieldState(status="ok")},
        "lessee": {"name": FieldState(status="ok")},
    }
    session.contract_fields = {}
    session.state = SessionState.COLLECTING_FIELDS
    session.can_build_contract = False
    save_session(session)

    headers = {"X-User-ID": "u1"}
    resp_light = client.post(
        f"/sessions/{session_id}/fields",
        headers=headers,
        json={"field": "cf1", "value": "value", "lightweight": True},
    )
    assert resp_light.status_code == 200
    after_light = load_session(session_id)
    assert after_light.contract_fields["cf1"].status == "ok"
    assert after_light.can_build_contract is False
    assert after_light.state == SessionState.COLLECTING_FIELDS

    resp_heavy = client.post(
        f"/sessions/{session_id}/fields",
        headers=headers,
        json={"field": "cf1", "value": "value", "lightweight": False},
    )
    assert resp_heavy.status_code == 200
    after_heavy = load_session(session_id)
    assert after_heavy.can_build_contract is True
    assert after_heavy.state == SessionState.READY_TO_BUILD
