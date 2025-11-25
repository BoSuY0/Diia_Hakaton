"""Tests for server endpoints."""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.http.server import app

client = TestClient(app)

@pytest.fixture(name="llm_mock")
def llm_response_mock():
    """Fixture to mock LLM response."""
    with patch("backend.api.http.server.chat_with_tools") as mock:
        yield mock

@pytest.fixture
def mock_system_prompt():
    """Fixture to mock system prompt."""
    with patch("backend.api.http.server.load_system_prompt", return_value="System Prompt"):
        yield

def test_healthz():
    """Test health check endpoint."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.usefixtures("mock_settings")
@pytest.mark.usefixtures("mock_system_prompt")
def test_chat_simple_response(llm_mock):
    """Test simple chat response without tool calls."""
    # Mock LLM returning a text message
    mock_choice = MagicMock()
    mock_choice.message.role = "assistant"
    mock_choice.message.content = "Hello from LLM"
    mock_choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    llm_mock.return_value = mock_response

    response = client.post("/chat", json={"session_id": "test_chat_1", "message": "Hi"})

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test_chat_1"
    assert data["reply"] == "Hello from LLM"

@pytest.mark.usefixtures("mock_settings")
@pytest.mark.usefixtures("mock_system_prompt", "mock_categories_data")
def test_chat_with_tool_call(llm_mock):
    """Test chat with tool call."""
    # Scenario: User asks for categories

    # 1. First call: LLM returns tool call
    mock_choice_tool = MagicMock()
    mock_choice_tool.message.role = "assistant"
    mock_choice_tool.message.content = None

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "fc" # Alias for find_category_by_query
    mock_tool_call.function.arguments = '{"q": "test"}'

    mock_choice_tool.message.tool_calls = [mock_tool_call]

    mock_response_tool = MagicMock()
    mock_response_tool.choices = [mock_choice_tool]

    # 2. Second call: LLM sees tool result and replies
    mock_choice_reply = MagicMock()
    mock_choice_reply.message.role = "assistant"
    mock_choice_reply.message.content = "Found category: Test Cat"
    mock_choice_reply.message.tool_calls = None

    mock_response_reply = MagicMock()
    mock_response_reply.choices = [mock_choice_reply]

    # Configure side_effect to return tool call first, then reply
    llm_mock.side_effect = [mock_response_tool, mock_response_reply]

    response = client.post(
        "/chat", json={"session_id": "test_chat_tool", "message": "Find test category"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "Found category: Test Cat" in data["reply"]

    # Verify tool was called (implicitly by the fact that loop continued)
    # We can also check if chat_with_tools was called twice
    assert llm_mock.call_count == 2

@pytest.mark.usefixtures("mock_categories_data")
def test_list_categories():
    """Test listing categories endpoint."""
    response = client.get("/categories")
    assert response.status_code == 200
    cats = response.json()
    assert len(cats) >= 1
    assert cats[0]["id"] == "test_cat"
