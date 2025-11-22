import pytest
from fastapi.testclient import TestClient

from src.app.server import app
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import SessionState
from src.documents.user_document import save_user_document


client = TestClient(app)


def _prepare_full_session(session_id: str, category_id: str) -> str:
    """Create a session with both roles claimed to test access control."""
    s = get_or_create_session(session_id)
    s.category_id = category_id
    s.template_id = "t1"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.party_users = {"lessor": "owner1", "lessee": "owner2"}
    s.state = SessionState.COMPLETED
    s.signatures = {"lessor": True, "lessee": True}
    s.can_build_contract = True
    save_session(s)
    save_user_document(s)
    return session_id


def test_contract_endpoints_reject_foreign_client(mock_settings, mock_categories_data):
    session_id = _prepare_full_session("acl_contract", mock_categories_data)
    headers = {"X-Client-ID": "intruder"}

    resp_info = client.get(f"/sessions/{session_id}/contract", headers=headers)
    assert resp_info.status_code == 403

    resp_preview = client.get(f"/sessions/{session_id}/contract/preview", headers=headers)
    assert resp_preview.status_code == 403

    resp_download = client.get(f"/sessions/{session_id}/contract/download", headers=headers)
    assert resp_download.status_code == 403


def test_user_document_protected_from_third_party(mock_settings, mock_categories_data):
    session_id = _prepare_full_session("acl_user_doc", mock_categories_data)
    headers = {"X-Client-ID": "intruder"}

    resp = client.get(f"/user-documents/{session_id}", headers=headers)
    assert resp.status_code == 403


def test_stream_and_order_require_participant(mock_settings, mock_categories_data):
    session_id = _prepare_full_session("acl_stream_order", mock_categories_data)
    headers = {"X-Client-ID": "intruder"}

    resp_stream = client.get(f"/sessions/{session_id}/stream", headers=headers)
    assert resp_stream.status_code == 403

    resp_order = client.post(f"/sessions/{session_id}/order", headers=headers)
    assert resp_order.status_code == 403


def test_sync_requires_participant(mock_settings, mock_categories_data):
    session_id = _prepare_full_session("acl_sync", mock_categories_data)
    headers = {"X-Client-ID": "intruder"}

    resp = client.post(
        f"/sessions/{session_id}/sync",
        json={"parties": {"lessor": {"person_type": "individual", "fields": {"name": "X"}}}},
        headers=headers,
    )
    assert resp.status_code == 403
