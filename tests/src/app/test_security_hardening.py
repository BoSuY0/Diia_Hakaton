import json
import asyncio
import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app
from backend.agent.tools.session import UpsertFieldTool, SetPartyContextTool
from backend.infra.persistence.store import (
    get_or_create_session,
    load_session,
    save_session,
)
from backend.domain.sessions.models import SessionState, FieldState
from backend.domain.categories.index import store as category_store


client = TestClient(app)


def _add_category(settings, cat_id: str, allowed_types=None, templ_id="t_new"):
    """Helper to add a category meta into the temp workspace and reload store."""
    allowed_types = allowed_types or ["individual", "company"]
    meta = {
        "category_id": cat_id,
        "templates": [{"id": templ_id, "name": "New T", "file": f"{templ_id}.docx"}],
        "roles": {
            "lessor": {"label": "Lessor", "allowed_person_types": allowed_types},
            "lessee": {"label": "Lessee", "allowed_person_types": allowed_types},
        },
        "party_modules": {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            },
            "company": {
                "label": "Comp",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            },
        },
        "contract_fields": [{"field": "cf1", "label": "CF1", "required": True}],
    }
    cat_path = settings.meta_categories_root / f"{cat_id}.json"
    cat_path.write_text(json.dumps(meta), encoding="utf-8")

    index_path = settings.meta_categories_root / "categories_index.json"
    if index_path.exists():
        idx = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        idx = {"categories": []}
    cats = {c["id"] for c in idx.get("categories", [])}
    if cat_id not in cats:
        idx["categories"].append({"id": cat_id, "label": cat_id})
    index_path.write_text(json.dumps(idx), encoding="utf-8")

    # Point store to updated index and reload
    category_store._categories = {}
    category_store.load()


@pytest.mark.asyncio
async def test_upsert_unmasks_pii(mock_settings, mock_categories_data):
    session_id = "pii_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.role = "lessor"
    s.person_type = "individual"
    s.party_types = {"lessor": "individual"}
    s.role_owners = {"lessor": "user1"}
    save_session(s)

    tool = UpsertFieldTool()
    tags = {"[IBAN#1]": "UA123456789012345678901234567"}
    res = await tool.execute(
        {
            "session_id": session_id,
            "field": "name",
            "value": "My iban [IBAN#1]",
        },
        {"pii_tags": tags, "user_id": "user1"},
    )

    assert res["ok"] is True
    updated = load_session(session_id)
    assert updated.all_data["lessor.name"]["current"] == "My iban UA123456789012345678901234567"


@pytest.mark.asyncio
async def test_upsert_requires_client_when_role_claimed(mock_settings, mock_categories_data):
    session_id = "acl_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.role = "lessor"
    s.person_type = "individual"
    s.party_types = {"lessor": "individual"}
    s.party_users = {"lessor": "owner1"}
    save_session(s)

    tool = UpsertFieldTool()
    res = await tool.execute(
        {"session_id": session_id, "field": "name", "value": "Test"},
        {},  # no client_id
    )
    assert res["ok"] is False
    assert "необхідний" in res["error"].lower()


@pytest.mark.asyncio
async def test_upsert_blocks_foreign_role(mock_settings, mock_categories_data):
    session_id = "foreign_field_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.role = "lessor"
    s.person_type = "individual"
    s.party_types = {"lessor": "individual"}
    s.party_users = {"lessor": "owner1"}
    save_session(s)

    tool = UpsertFieldTool()
    res = await tool.execute(
        {"session_id": session_id, "field": "name", "value": "Test", "role": "lessor"},
        {"user_id": "other_user"},
    )
    assert res["ok"] is False
    assert "не маєте права" in res["error"]


def test_sign_requires_client_and_ready(mock_settings, mock_categories_data):
    session_id = "sign_ready_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.template_id = "t1"
    s.state = SessionState.COLLECTING_FIELDS
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    save_session(s)

    # No client id -> 401
    resp = client.post(f"/sessions/{session_id}/contract/sign")
    assert resp.status_code == 401

    # Not ready -> 400 even with client
    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-User-ID": "user1"},
    )
    assert resp.status_code == 400

    # Mark as built and owned -> success
    s = load_session(session_id)
    s.state = SessionState.BUILT
    s.party_users = {"lessor": "user1"}
    save_session(s)
    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-User-ID": "user1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["signatures"]["lessor"] is True


def test_sign_full_mode_respects_owners(mock_settings, mock_categories_data):
    session_id = "full_mode_conflict"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.template_id = "t1"
    s.state = SessionState.BUILT
    s.filling_mode = "full"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    s.party_users = {"lessor": "user_owner", "lessee": "other_owner"}
    save_session(s)

    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-User-ID": "intruder"},
    )
    assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_set_party_context_disallows_disallowed_type(mock_settings, mock_categories_data):
    tool = SetPartyContextTool()
    session_id = "ctx_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    save_session(s)

    res = await tool.execute(
        {"session_id": session_id, "role": "lessor", "person_type": "fop"},
        {"user_id": "ctx_user"},
    )
    assert res["ok"] is False


def test_sync_changes_category_and_clears_state(mock_settings, mock_categories_data):
    session_id = "sync_reset_session"

    # Ensure second category exists
    _add_category(mock_settings, "new_cat", templ_id="new_t")

    # Initial sync with test_cat
    payload1 = {
        "category_id": "test_cat",
        "template_id": "t1",
        "parties": {
            "lessor": {"person_type": "individual", "fields": {"name": "Old Name"}},
            "lessee": {"person_type": "individual", "fields": {"name": "Lessee Name"}},
        },
    }
    resp = client.post(
        f"/sessions/{session_id}/sync",
        json=payload1,
        headers={"X-User-ID": "sync_user"},
    )
    assert resp.status_code == 200

    # Add signature and data to ensure it is cleared
    s = load_session(session_id)
    s.signatures = {"lessor": True}
    s.all_data["lessor.name"] = {"current": "Old Name"}
    save_session(s)

    # Sync with a different category
    payload2 = {
        "category_id": "new_cat",
        "template_id": "new_t",
        "parties": {
            "lessor": {"person_type": "individual", "fields": {"name": "New Name"}},
        },
    }
    resp = client.post(
        f"/sessions/{session_id}/sync",
        json=payload2,
        headers={"X-User-ID": "sync_user"},
    )
    assert resp.status_code == 200
    s = load_session(session_id)
    assert s.category_id == "new_cat"
    assert s.signatures == {}  # cleared
    assert s.all_data.get("lessor.name", {}).get("current") == "New Name"


def test_sync_template_must_belong_to_category(mock_settings, mock_categories_data):
    session_id = "sync_template_guard"
    _add_category(mock_settings, "cat_a", templ_id="templ_a")

    bad_payload = {
        "category_id": "cat_a",
        "template_id": "foreign_template",
        "parties": {
            "lessor": {"person_type": "individual", "fields": {"name": "X"}},
        },
    }
    resp = client.post(
        f"/sessions/{session_id}/sync",
        json=bad_payload,
        headers={"X-User-ID": "sync_user"},
    )
    assert resp.status_code == 400


def test_schema_status_uses_field_state(mock_settings, mock_categories_data):
    session_id = "schema_status_session"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.contract_fields = {"cf1": FieldState(status="error", error="bad")}
    s.all_data = {"cf1": {"current": "Some text"}}
    save_session(s)

    resp = client.get(
        f"/sessions/{session_id}/schema",
        params={"data_mode": "status"},
        headers={"X-User-ID": "schema_user"},
    )
    assert resp.status_code == 200
    contract_fields = resp.json()["contract"]["fields"]
    assert contract_fields[0]["value"] is False  # error state should be false
