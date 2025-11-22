from fastapi.testclient import TestClient

from src.app.server import app
from src.sessions.store import load_session


client = TestClient(app)


def test_healthz_endpoint():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "docx_ok" in data


def test_create_and_get_session(mock_settings, mock_categories_data):
    resp = client.post("/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # Set category
    resp2 = client.post(f"/sessions/{session_id}/category", json={"category_id": mock_categories_data})
    assert resp2.status_code == 200

    # Get summary
    resp3 = client.get(f"/sessions/{session_id}")
    assert resp3.status_code == 200
    data = resp3.json()
    assert data["category_id"] == mock_categories_data


def test_categories_endpoints(mock_settings, mock_categories_data):
    # list categories
    resp = client.get("/categories")
    assert resp.status_code == 200
    cats = resp.json()
    assert any(c["id"] == mock_categories_data for c in cats)

    # find by query
    resp2 = client.post("/categories/find", json={"query": "оренда"})
    assert resp2.status_code == 200

    # get templates/entities
    resp3 = client.get(f"/categories/{mock_categories_data}/templates")
    assert resp3.status_code == 200
    resp4 = client.get(f"/categories/{mock_categories_data}/entities")
    assert resp4.status_code == 200
    resp5 = client.get(f"/categories/{mock_categories_data}/parties")
    assert resp5.status_code == 200
    data = resp5.json()
    assert data["roles"]
    assert data["person_types"]


def test_chat_endpoint_with_mock_llm(monkeypatch, mock_settings):
    called = {}

    class Msg:
        role = "assistant"
        content = "Mock reply"
        tool_calls = None

    class Choice:
        message = Msg()

    class Resp:
        choices = [Choice()]

    monkeypatch.setattr("src.app.server.chat_with_tools", lambda *a, **k: Resp())

    # Need session
    sid = "chat_sess"
    client.post("/sessions", json={"session_id": sid})
    resp = client.post("/chat", json={"session_id": sid, "message": "Hello"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Mock reply"


def test_session_schema_endpoint(mock_settings, mock_categories_data):
    resp = client.post("/sessions", json={})
    sid = resp.json()["session_id"]
    client.post(f"/sessions/{sid}/category", json={"category_id": mock_categories_data})
    # Set party context to avoid missing person_type in schema fields/value mode
    client.post(
        f"/sessions/{sid}/party-context",
        json={"role": "lessor", "person_type": "individual"},
        headers={"X-Client-ID": "u1"},
    )
    schema = client.get(f"/sessions/{sid}/schema", headers={"X-Client-ID": "u1"})
    assert schema.status_code == 200
    data = schema.json()
    assert data["category_id"] == mock_categories_data
    assert data["parties"]


def test_set_template_endpoint(mock_settings, mock_categories_data):
    resp = client.post("/sessions", json={})
    sid = resp.json()["session_id"]
    client.post(f"/sessions/{sid}/category", json={"category_id": mock_categories_data})
    r = client.post(f"/sessions/{sid}/template", json={"template_id": "t1"})
    assert r.status_code == 200
    s = load_session(sid)
    assert s.template_id == "t1"
