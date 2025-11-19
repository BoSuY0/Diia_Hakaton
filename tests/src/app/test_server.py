import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.app.server import app

client = TestClient(app)

@pytest.fixture
def mock_llm_response():
    with patch("src.app.server.chat_with_tools") as mock:
        yield mock

@pytest.fixture
def mock_system_prompt():
    with patch("src.app.server.load_system_prompt", return_value="System Prompt"):
        yield

def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_chat_simple_response(mock_llm_response, mock_system_prompt, mock_settings):
    # Mock LLM returning a text message
    mock_choice = MagicMock()
    mock_choice.message.role = "assistant"
    mock_choice.message.content = "Hello from LLM"
    mock_choice.message.tool_calls = None
    
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_llm_response.return_value = mock_response
    
    response = client.post("/chat", json={"session_id": "test_chat_1", "message": "Hi"})
    
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test_chat_1"
    assert data["reply"] == "Hello from LLM"

def test_chat_with_tool_call(mock_llm_response, mock_system_prompt, mock_settings, mock_categories_data):
    # Scenario: User asks for categories -> LLM calls find_category_by_query -> Tool returns -> LLM replies
    
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
    mock_llm_response.side_effect = [mock_response_tool, mock_response_reply]
    
    response = client.post("/chat", json={"session_id": "test_chat_tool", "message": "Find test category"})
    
    assert response.status_code == 200
    data = response.json()
    assert "Found category: Test Cat" in data["reply"]
    
    # Verify tool was called (implicitly by the fact that loop continued)
    # We can also check if chat_with_tools was called twice
    assert mock_llm_response.call_count == 2

def test_list_categories(mock_categories_data):
    response = client.get("/categories")
    assert response.status_code == 200
    cats = response.json()
    assert len(cats) >= 1
    assert cats[0]["id"] == "test_cat"
