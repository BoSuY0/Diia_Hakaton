"""Tests for multi-party access control."""
import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState
from backend.shared.enums import FillingMode


client = TestClient(app)


def _bootstrap_session(session_id: str, cat_id: str, filling_mode: FillingMode = FillingMode.FULL) -> str:
    s = get_or_create_session(session_id)
    s.category_id = cat_id
    s.template_id = "t1"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.state = SessionState.TEMPLATE_SELECTED
    s.filling_mode = filling_mode
    save_session(s)
    return session_id


@pytest.mark.usefixtures("mock_settings")
def test_multi_user_cannot_edit_foreign_party(mock_categories_data):
    """Test that user cannot edit another party's fields."""
    session_id = _bootstrap_session("multi_acl", mock_categories_data)

    # User A claims lessor, user B claims lessee
    resp_a = client.post(
        f"/sessions/{session_id}/party-context",
        headers={"X-User-ID": "user_a"},
        json={"role": "lessor", "person_type": "individual"},
    )
    assert resp_a.status_code == 200
    resp_b = client.post(
        f"/sessions/{session_id}/party-context",
        headers={"X-User-ID": "user_b"},
        json={"role": "lessee", "person_type": "individual"},
    )
    assert resp_b.status_code == 200

    # User A cannot edit user B's party fields
    blocked = client.post(
        f"/sessions/{session_id}/fields",
        headers={"X-User-ID": "user_a"},
        json={"field": "name", "value": "Owner edits other", "role": "lessee"},
    )
    assert blocked.status_code == 403

    # User B can edit their own side
    ok = client.post(
        f"/sessions/{session_id}/fields",
        headers={"X-User-ID": "user_b"},
        json={"field": "name", "value": "Lessee Name", "role": "lessee"},
    )
    assert ok.status_code == 200
    assert ok.json().get("ok") is True


@pytest.mark.usefixtures("mock_settings")
def test_observer_sees_no_sessions_and_cannot_sync(mock_categories_data):
    """Test that observer cannot see or modify sessions."""
    session_id = _bootstrap_session("observer_acl", mock_categories_data)
    # Creator claims a role to finalize participants
    client.post(
        f"/sessions/{session_id}/party-context",
        headers={"X-User-ID": "creator"},
        json={"role": "lessor", "person_type": "individual"},
    )

    # Observer should not see session in listing
    listing = client.get("/my-sessions", headers={"X-User-ID": "observer"})
    assert listing.status_code == 200
    assert all(item.get("session_id") != session_id for item in listing.json())

    # Observer cannot sync or write
    sync_resp = client.post(
        f"/sessions/{session_id}/sync",
        headers={"X-User-ID": "observer"},
        json={"parties": {"lessor": {"person_type": "individual", "fields": {"name": "X"}}}},
    )
    assert sync_resp.status_code == 403

    write_resp = client.post(
        f"/sessions/{session_id}/fields",
        headers={"X-User-ID": "observer"},
        json={"field": "name", "value": "X", "role": "lessor"},
    )
    assert write_resp.status_code == 403
