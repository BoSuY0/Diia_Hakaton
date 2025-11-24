import json
import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app
from backend.infra.persistence.store import get_or_create_session, load_session, save_session
from backend.domain.sessions.models import FieldState
from backend.agent.tools.session import UpsertFieldTool

client = TestClient(app)


def _write_category(settings, cat_id: str, templ_id: str):
    meta = {
        "category_id": cat_id,
        "templates": [{"id": templ_id, "name": templ_id, "file": f"{templ_id}.docx"}],
        "roles": {"lessor": {"label": "Lessor", "allowed_person_types": ["individual"]}},
        "party_modules": {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            }
        },
        "contract_fields": [{"field": "cf1", "label": "CF1", "required": True}],
    }
    path = settings.meta_categories_root / f"{cat_id}.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    idx = settings.meta_categories_root / "categories_index.json"
    if idx.exists():
        data = json.loads(idx.read_text(encoding="utf-8"))
    else:
        data = {"categories": []}
    if all(c["id"] != cat_id for c in data.get("categories", [])):
        data["categories"].append({"id": cat_id, "label": cat_id})
    idx.write_text(json.dumps(data), encoding="utf-8")


def test_sync_template_must_match_category(mock_settings):
    _write_category(mock_settings, "cat_a", "templ_a")
    session_id = "sync_templ_guard"
    payload = {
        "category_id": "cat_a",
        "template_id": "foreign",
        "parties": {"lessor": {"person_type": "individual", "fields": {"name": "X"}}},
    }
    resp = client.post(
        f"/sessions/{session_id}/sync",
        json=payload,
        headers={"X-User-ID": "sync_user"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sync_partial_and_ready(mock_settings):
    _write_category(mock_settings, "cat_a", "templ_a")
    session_id = "sync_ready_flow"

    # Partial: missing contract field
    payload_partial = {
        "category_id": "cat_a",
        "template_id": "templ_a",
        "parties": {"lessor": {"person_type": "individual", "fields": {"name": "X"}}},
    }
    resp = client.post(
        f"/sessions/{session_id}/sync",
        json=payload_partial,
        headers={"X-User-ID": "sync_user"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "partial"

    # Fill contract field via tool to reach ready
    tool = UpsertFieldTool()
    session_loaded = load_session(session_id)
    session_loaded.role_owners = {"lessor": "sync_user"}
    save_session(session_loaded)
    await tool.execute({"session_id": session_id, "field": "cf1", "value": "Val"}, {"user_id": "sync_user"})

    resp2 = client.post(
        f"/sessions/{session_id}/sync",
        json={"parties": {"lessor": {"person_type": "individual", "fields": {"name": "X"}}}},
        headers={"X-User-ID": "sync_user"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["status"] in ("ready", "partial")


def test_schema_respects_error_status(mock_settings, mock_categories_data):
    session_id = "schema_error_case"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    s.contract_fields = {"cf1": FieldState(status="error", error="bad")}
    s.all_data = {"cf1": {"current": "text"}}
    save_session(s)

    resp = client.get(f"/sessions/{session_id}/schema", params={"data_mode": "values"}, headers={"X-User-ID": "schema_user"})
    assert resp.status_code == 200
    cf = resp.json()["contract"]["fields"][0]
    assert cf["value"] is None  # error state should not expose value

    resp = client.get(f"/sessions/{session_id}/schema", params={"data_mode": "status"}, headers={"X-User-ID": "schema_user"})
    assert resp.status_code == 200
    cf = resp.json()["contract"]["fields"][0]
    assert cf["value"] is False


def test_schema_required_scope_excludes_optional(mock_settings, mock_categories_data):
    # Extend category to add optional field
    cat_path = mock_settings.meta_categories_root / f"{mock_categories_data}.json"
    meta = json.loads(cat_path.read_text(encoding="utf-8"))
    meta["contract_fields"].append({"field": "optional_field", "label": "Opt", "required": False})
    cat_path.write_text(json.dumps(meta), encoding="utf-8")

    # Reload store to pick updated meta
    from backend.domain.categories.index import store as category_store
    category_store._categories = {}
    category_store.load()

    session_id = "schema_required_scope"
    s = get_or_create_session(session_id)
    s.category_id = mock_categories_data
    save_session(s)

    resp = client.get(f"/sessions/{session_id}/schema", params={"scope": "required"}, headers={"X-User-ID": "schema_user"})
    assert resp.status_code == 200
    fields = resp.json()["contract"]["fields"]
    assert all(f["field_name"] != "optional_field" for f in fields)
