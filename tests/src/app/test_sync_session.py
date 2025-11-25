"""Tests for session sync functionality."""
import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app

client = TestClient(app)

@pytest.fixture
def mock_chat_with_tools(monkeypatch):
    """Mocks the LLM client to avoid real API calls."""
    def mock_chat(*args, **kwargs):  # pylint: disable=unused-argument
        """Mock chat function."""
        class MockResponse:  # pylint: disable=too-few-public-methods
            """Mock response class."""
            class Choice:  # pylint: disable=too-few-public-methods
                """Mock choice class."""
                class Message:  # pylint: disable=too-few-public-methods
                    """Mock message class."""
                    role = "assistant"
                    content = "Mock response"
                    tool_calls = []
                message = Message()
            choices = [Choice()]
        return MockResponse()

    monkeypatch.setattr("backend.api.http.server.chat_with_tools", mock_chat)
    return mock_chat

@pytest.fixture
def mock_build_contract(monkeypatch):
    """Mock build contract function."""
    async def mock_build(*args, **kwargs):  # pylint: disable=unused-argument
        return {"document_url": "http://mock/doc.docx", "ok": True}

    monkeypatch.setattr("backend.api.http.server.tool_build_contract_async", mock_build)

@pytest.mark.usefixtures("mock_settings", "temp_workspace")
def test_sync_session_full_flow(  # pylint: disable=unused-argument
    mock_categories_data, mock_build_contract
):
    """Test one-shot sync with full data."""
    # 1. Create session
    response = client.post("/sessions", json={}, headers={"X-User-ID": "sync_user"})
    session_id = response.json()["session_id"]

    # 2. Sync with full data using IDs from mock_categories_data (test_cat, t1)
    payload = {
        "category_id": "test_cat",
        "template_id": "t1",
        "parties": {
            "lessor": {
                "person_type": "individual",
                "fields": {
                    "name": "Ivanov Ivan"
                }
            },
            "lessee": {
                "person_type": "company",
                "fields": {
                    "name": "IT Solutions LLC"
                }
            }
        }
    }

    response = client.post(
        f"/sessions/{session_id}/sync",
        json=payload,
        headers={"X-User-ID": "sync_user"},
    )
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()
    # Якщо контрактні поля ще не передані, статус може бути partial
    assert data["status"] in ("ready", "partial")

@pytest.mark.usefixtures("mock_settings", "temp_workspace")
def test_sync_session_partial_flow(mock_categories_data):  # pylint: disable=unused-argument
    """Test partial sync (one party only)."""
    response = client.post("/sessions", json={}, headers={"X-User-ID": "sync_user"})
    session_id = response.json()["session_id"]

    payload = {
        "category_id": "test_cat",
        "template_id": "t1",
        "parties": {
            "lessor": {
                "person_type": "individual",
                "fields": {
                    "name": "Ivanov Ivan"
                }
            }
        }
    }

    response = client.post(
        f"/sessions/{session_id}/sync",
        json=payload,
        headers={"X-User-ID": "sync_user"},
    )
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()

    assert data["status"] == "partial"
    # mock_categories_data defines roles: lessor, lessee. We sent lessor. Missing: lessee.
    assert "lessee" in data["missing"]["roles"]

@pytest.mark.usefixtures("mock_settings", "temp_workspace")
def test_sync_session_incremental_flow(  # pylint: disable=unused-argument
    mock_categories_data, mock_build_contract
):
    """Test incremental sync (add second party later)."""
    # 1. Start with partial
    response = client.post("/sessions", json={}, headers={"X-User-ID": "sync_user"})
    session_id = response.json()["session_id"]

    payload1 = {
        "category_id": "test_cat",
        "template_id": "t1",
        "parties": {
            "lessor": {
                "person_type": "individual",
                "fields": {"name": "Ivanov"}
            }
        }
    }
    client.post(
        f"/sessions/{session_id}/sync",
        json=payload1,
        headers={"X-User-ID": "sync_user"},
    )

    # 2. Add lessee
    payload2 = {
        "parties": {
            "lessee": {
                "person_type": "company",
                "fields": {"name": "TOW"}
            }
        }
    }
    response = client.post(
        f"/sessions/{session_id}/sync",
        json=payload2,
        headers={"X-User-ID": "sync_user"},
    )
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()

    assert data["status"] in ("ready", "partial")

    # Verify user_document contains both parties' data
    # pylint: disable-next=import-outside-toplevel
    from backend.domain.documents.user_document import load_user_document
    doc = load_user_document(session_id)
    
    # Check Lessor Data
    assert doc["parties"]["lessor"]["person_type"] == "individual"
    assert doc["parties"]["lessor"]["data"]["name"] == "Ivanov"

    # Check Lessee Data
    assert doc["parties"]["lessee"]["person_type"] == "company"
    assert doc["parties"]["lessee"]["data"]["name"] == "TOW"
