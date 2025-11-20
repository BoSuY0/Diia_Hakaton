import pytest
from fastapi.testclient import TestClient
from src.app.server import app
from src.sessions.store import load_session

client = TestClient(app)

@pytest.fixture
def mock_chat_with_tools(monkeypatch):
    """Mocks the LLM client to avoid real API calls."""
    def mock_chat(*args, **kwargs):
        class MockResponse:
            class Choice:
                class Message:
                    role = "assistant"
                    content = "Mock response"
                    tool_calls = []
                message = Message()
            choices = [Choice()]
        return MockResponse()
    
    monkeypatch.setattr("src.app.server.chat_with_tools", mock_chat)
    return mock_chat

@pytest.fixture
def mock_build_contract(monkeypatch):
    def mock_build(*args, **kwargs):
        return {"document_url": "http://mock/doc.docx", "ok": True}
    monkeypatch.setattr("src.app.server.tool_build_contract", mock_build)

def test_sync_session_full_flow(mock_settings, mock_categories_data, mock_build_contract, temp_workspace):
    """Test one-shot sync with full data."""
    # 1. Create session
    response = client.post("/sessions", json={})
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
    
    response = client.post(f"/sessions/{session_id}/sync", json=payload)
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()
    
    assert data["status"] == "ready"
    assert data["document_url"] == "http://mock/doc.docx"

def test_sync_session_partial_flow(mock_settings, mock_categories_data, temp_workspace):
    """Test partial sync (one party only)."""
    response = client.post("/sessions", json={})
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

    response = client.post(f"/sessions/{session_id}/sync", json=payload)
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()
    
    assert data["status"] == "partial"
    # mock_categories_data defines roles: lessor, lessee. We sent lessor. Missing: lessee.
    assert "lessee" in data["missing"]

def test_sync_session_incremental_flow(mock_settings, mock_categories_data, mock_build_contract, temp_workspace):
    """Test incremental sync (add second party later)."""
    # 1. Start with partial
    response = client.post("/sessions", json={})
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
    client.post(f"/sessions/{session_id}/sync", json=payload1)
    
    # 2. Add lessee
    payload2 = {
        "parties": {
            "lessee": {
                "person_type": "company",
                "fields": {"name": "TOW"}
            }
        }
    }
    response = client.post(f"/sessions/{session_id}/sync", json=payload2)
    assert response.status_code == 200, f"Response: {response.text}"
    data = response.json()
    
    assert data["status"] == "ready"
    assert data["document_url"] == "http://mock/doc.docx"
    
    # Verify user_document contains both parties' data
    from src.documents.user_document import load_user_document
    doc = load_user_document(session_id)
    
    # Check Lessor Data
    assert doc["parties"]["lessor"]["person_type"] == "individual"
    assert doc["parties"]["lessor"]["data"]["name"] == "Ivanov"
    
    # Check Lessee Data
    assert doc["parties"]["lessee"]["person_type"] == "company"
    assert doc["parties"]["lessee"]["data"]["name"] == "TOW"
