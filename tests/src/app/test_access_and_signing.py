import json
import pytest
from fastapi.testclient import TestClient

from src.app.server import app
from src.sessions.store import get_or_create_session, load_session, save_session
from src.sessions.models import SessionState, FieldState
from src.agent.tools.session import SetPartyContextTool
from src.common.enums import FillingMode

client = TestClient(app)


def _bootstrap_session(cat_id: str, template_id: str = "t1"):
    session_id = "sess_rest_fields"
    s = get_or_create_session(session_id)
    s.category_id = cat_id
    s.template_id = template_id
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.state = SessionState.TEMPLATE_SELECTED
    save_session(s)
    return session_id


def test_fields_endpoint_requires_header_when_participant(mock_settings, mock_categories_data):
    session_id = _bootstrap_session(mock_categories_data)
    # Claim a role to mark participants
    s = load_session(session_id)
    s.party_users = {"lessor": "owner1"}
    save_session(s)

    # Without header -> 401
    resp = client.post(
        f"/sessions/{session_id}/fields",
        json={"field": "name", "value": "A", "role": "lessor"},
    )
    assert resp.status_code == 401

    # With wrong user -> 400/403 (tool returns error -> 400)
    resp = client.post(
        f"/sessions/{session_id}/fields",
        headers={"X-Client-ID": "intruder"},
        json={"field": "name", "value": "A", "role": "lessor"},
    )
    assert resp.status_code in (400, 403)

    # With owner -> allowed
    resp = client.post(
        f"/sessions/{session_id}/fields",
        headers={"X-Client-ID": "owner1"},
        json={"field": "name", "value": "A", "role": "lessor"},
    )
    assert resp.status_code == 200


def test_fields_header_not_required_before_participants(mock_settings, mock_categories_data):
    session_id = _bootstrap_session(mock_categories_data)
    # No participants yet -> allowed without header
    resp = client.post(
        f"/sessions/{session_id}/fields",
        json={"field": "name", "value": "A", "role": "lessor"},
    )
    assert resp.status_code == 200


def test_sign_full_mode_with_empty_owners(mock_settings, mock_categories_data):
    session_id = _bootstrap_session(mock_categories_data)
    s = load_session(session_id)
    s.state = SessionState.BUILT
    s.filling_mode = FillingMode.FULL
    save_session(s)

    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-Client-ID": "user_full"},
    )
    assert resp.status_code == 200
    signed = load_session(session_id).signatures
    assert signed.get("lessor") is True
    assert signed.get("lessee") is True


def test_sign_full_mode_conflict_owner(mock_settings, mock_categories_data):
    session_id = _bootstrap_session(mock_categories_data)
    s = load_session(session_id)
    s.state = SessionState.BUILT
    s.filling_mode = FillingMode.FULL
    s.party_users = {"lessor": "owner1", "lessee": "owner2"}
    save_session(s)

    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-Client-ID": "other"},
    )
    assert resp.status_code == 403


def test_download_forbidden_until_signed(mock_settings, mock_categories_data, monkeypatch):
    session_id = _bootstrap_session(mock_categories_data)
    s = load_session(session_id)
    s.state = SessionState.BUILT
    s.template_id = "t1"
    save_session(s)

    # Mock builder to avoid file IO
    monkeypatch.setattr("src.app.server.tool_build_contract", lambda session_id, template_id: {"file_path": "tmp.docx"})

    resp = client.get(
        f"/sessions/{session_id}/contract/download",
        headers={"X-Client-ID": "owner1"},
    )
    assert resp.status_code == 403

    s = load_session(session_id)
    s.signatures = {"lessor": True, "lessee": True}
    s.state = SessionState.COMPLETED
    save_session(s)

    resp = client.get(
        f"/sessions/{session_id}/contract/download",
        headers={"X-Client-ID": "owner1"},
    )
    assert resp.status_code in (200, 404)  # 404 allowed if file missing


def test_set_party_context_requires_category_and_allowed_type(mock_settings, mock_categories_data):
    tool = SetPartyContextTool()
    session_id = "ctx_access_test"
    s = get_or_create_session(session_id)
    save_session(s)  # no category
    res = tool.execute({"session_id": session_id, "role": "lessor", "person_type": "individual"}, {})
    assert res["ok"] is False

    s = load_session(session_id)
    s.category_id = mock_categories_data
    save_session(s)
    # Disallowed type
    res = tool.execute({"session_id": session_id, "role": "lessor", "person_type": "fop"}, {})
    assert res["ok"] is False

    # Allowed type
    res = tool.execute({"session_id": session_id, "role": "lessor", "person_type": "individual"}, {"client_id": "user_ctx"})
    assert res["ok"] is True
    s = load_session(session_id)
    assert s.party_users["lessor"] == "user_ctx"
