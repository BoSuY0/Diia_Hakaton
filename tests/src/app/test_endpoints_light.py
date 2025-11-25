"""Light tests for basic API endpoints."""
import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app
from backend.infra.persistence.store import load_session


client = TestClient(app)
AUTH_HEADERS = {"X-User-ID": "u1"}


def test_healthz_endpoint():
    """Test healthz endpoint."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "docx_ok" in data


@pytest.mark.usefixtures("mock_settings")
def test_create_and_get_session(mock_categories_data):
    """Test creating and getting a session."""
    resp = client.post("/sessions", json={}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # Set category
    resp2 = client.post(f"/sessions/{session_id}/category", json={"category_id": mock_categories_data}, headers=AUTH_HEADERS)
    assert resp2.status_code == 200

    # Get summary
    resp3 = client.get(f"/sessions/{session_id}", headers=AUTH_HEADERS)
    assert resp3.status_code == 200
    data = resp3.json()
    assert data["category_id"] == mock_categories_data


@pytest.mark.usefixtures("mock_settings")
def test_categories_endpoints(mock_categories_data):
    """Test category listing and lookup endpoints."""
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


@pytest.mark.usefixtures("mock_settings")
def test_chat_endpoint_with_mock_llm(monkeypatch):
    """Test chat endpoint with mocked LLM."""
    called = {}

    class Msg:  # pylint: disable=too-few-public-methods
        """Mock message."""

        role = "assistant"
        content = "Mock reply"
        tool_calls = None

    class Choice:  # pylint: disable=too-few-public-methods
        """Mock choice."""

        message = Msg()

    class Resp:  # pylint: disable=too-few-public-methods
        """Mock response."""

        choices = [Choice()]

    monkeypatch.setattr("backend.api.http.server.chat_with_tools", lambda *a, **k: Resp())

    # Need session
    sid = "chat_sess"
    client.post("/sessions", json={"session_id": sid}, headers=AUTH_HEADERS)
    resp = client.post("/chat", json={"session_id": sid, "message": "Hello"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Mock reply"


@pytest.mark.usefixtures("mock_settings")
def test_session_schema_endpoint(mock_categories_data):
    """Test session schema endpoint."""
    resp = client.post("/sessions", json={}, headers=AUTH_HEADERS)
    sid = resp.json()["session_id"]
    client.post(f"/sessions/{sid}/category", json={"category_id": mock_categories_data}, headers=AUTH_HEADERS)
    # Set party context to avoid missing person_type in schema fields/value mode
    client.post(
        f"/sessions/{sid}/party-context",
        json={"role": "lessor", "person_type": "individual"},
        headers={"X-User-ID": "u1"},
    )
    schema = client.get(f"/sessions/{sid}/schema", headers={"X-User-ID": "u1"})
    assert schema.status_code == 200
    data = schema.json()
    assert data["category_id"] == mock_categories_data
    assert data["parties"]


@pytest.mark.usefixtures("mock_settings")
def test_set_template_endpoint(mock_categories_data):
    """Test setting template for a session."""
    resp = client.post("/sessions", json={}, headers=AUTH_HEADERS)
    sid = resp.json()["session_id"]
    client.post(f"/sessions/{sid}/category", json={"category_id": mock_categories_data}, headers=AUTH_HEADERS)
    r = client.post(f"/sessions/{sid}/template", json={"template_id": "t1"}, headers=AUTH_HEADERS)
    assert r.status_code == 200
    s = load_session(sid)
    assert s.template_id == "t1"
