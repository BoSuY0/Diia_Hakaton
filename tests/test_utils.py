"""Shared test utilities and fixtures."""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from backend.api.http.server import app


def create_mock_chat_response():
    """Create a mock response for chat_with_tools."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.role = "assistant"
    mock_response.choices[0].message.content = "Mock response"
    mock_response.choices[0].message.tool_calls = []
    return mock_response


def setup_mock_chat():
    """Setup mock for chat_with_tools to avoid real LLM calls.

    Returns:
        Tuple of (patcher, mock_chat, client)
    """
    patcher = patch("backend.api.http.server.chat_with_tools")
    mock_chat = patcher.start()
    mock_chat.return_value = create_mock_chat_response()
    client = TestClient(app)
    return patcher, mock_chat, client


# Common contract field values for testing
COMMON_CONTRACT_FIELDS = {
    "object_address": "Kyiv, Main St, 1",
    "rent_price_month": "10000",
    "start_date": "01.01.2025",
}
