"""Tests for LLM client."""
import os

import pytest

from backend.agent import llm_client
from backend.infra.config.settings import settings


def test_ensure_api_key_sets_openai(monkeypatch):  # pylint: disable=protected-access
    """Test ensure API key sets OpenAI."""
    monkeypatch.setattr(settings, "llm_api_key", "test_key")
    monkeypatch.setattr(settings, "llm_model", "gpt-4")
    # Clear env first
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm_client._ensure_api_key()
    assert os.getenv("OPENAI_API_KEY") == "test_key"


def test_ensure_api_key_sets_anthropic(monkeypatch):  # pylint: disable=protected-access
    """Test ensure API key sets Anthropic."""
    monkeypatch.setattr(settings, "llm_api_key", "anthro_key")
    monkeypatch.setattr(settings, "llm_model", "claude-3")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm_client._ensure_api_key()
    assert os.getenv("ANTHROPIC_API_KEY") == "anthro_key"


@pytest.mark.asyncio
async def test_chat_with_tools_filters_orphan_tool(monkeypatch):
    """Test chat with tools filters orphan tool."""
    monkeypatch.setattr(settings, "llm_api_key", "test_key")
    monkeypatch.setattr(settings, "llm_model", "gpt-4")

    captured = {}

    def fake_completion(**kwargs):
        captured["messages"] = kwargs["messages"]
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    async def fake_acompletion(**kwargs):
        return fake_completion(**kwargs)

    monkeypatch.setattr(
        llm_client,
        "litellm",
        type(
            "obj", (),
            {
                "completion": staticmethod(fake_completion),
                "acompletion": staticmethod(fake_acompletion)
            }
        ),
    )

    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [{"id": "call1"}]},
        {"role": "tool", "tool_call_id": "orphan", "content": "drop"},
        {"role": "tool", "tool_call_id": "call1", "content": "ok"},
    ]
    await llm_client.chat_with_tools_async(msgs, tools=[])
    sent_roles = [m["role"] for m in captured["messages"]]
    # Only one tool response should remain
    assert sent_roles.count("tool") == 1
