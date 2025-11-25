"""Tests for server helper functions."""
import pytest

from backend.api.http import server
from backend.infra.persistence.store import get_or_create_session, save_session


def test_detect_lang_uk_en():
    """Test detect language for Ukrainian and English."""
    assert server.detect_lang("Привіт") == "uk"
    assert server.detect_lang("Hello") == "en"


def test_last_user_message_text_handles_structured():
    """Test last user message text handles structured content."""
    msgs = [
        {"role": "user", "content": [{"text": "First"}, {"text": ""}]},
        {"role": "assistant", "content": "Reply"},
        {"role": "user", "content": [{"text": ""}, {"text": "Second"}]},
    ]
    assert server.last_user_message_text(msgs) == "Second"


def test_canonical_args_sorts_keys():
    """Test canonical args sorts keys."""
    raw = '{"b":1,"a":2}'
    canon = server.canonical_args(raw)
    assert canon == '{"a":2,"b":1}'


def test_inject_session_id_adds_and_expands_alias():
    """Test inject session id adds and expands alias."""
    args = '{"cid": "cat1", "f": "field1"}'
    injected = server.inject_session_id(args, "sess1", "upsert_field")
    data = server.json.loads(injected)
    assert data["session_id"] == "sess1"
    # alias cid -> category_id should be preserved as explicit field when not session-aware
    assert data["category_id"] == "cat1"
    assert data["field"] == "field1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings", "mock_categories_data")
async def test_get_effective_state_uses_saved_when_has_category_tool():
    """Test that _get_effective_state uses saved state correctly."""
    s = get_or_create_session("eff_state")
    s.category_id = "test_cat"  # mock_categories_data creates "test_cat"
    s.state = server.SessionState.TEMPLATE_SELECTED
    save_session(s)
    get_effective_state = getattr(server, "_get_effective_state")
    state = await get_effective_state("eff_state", [], has_category_tool=False)
    assert state == "template_selected"


def test_prune_strips_orphan_tools():
    """Test prune strips orphan tools."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "tool_calls": [{"id": "call1"}]},
        {"role": "tool", "tool_call_id": "call1", "content": "ok"},
        {"role": "tool", "tool_call_id": "orphan", "content": "drop me"},
    ]
    pruned = server.prune_messages(msgs)
    roles = [m["role"] for m in pruned]
    assert roles.count("tool") == 1


def test_format_reply_uses_tool_templates():
    """Test format reply uses tool templates."""
    msgs = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c1"}],
            "content": None,
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "get_templates_for_category",
            "content": "TEMPLATES\nlease_flat|Flat",
        },
    ]
    text = server.format_reply_from_messages(msgs)
    assert "Доступні шаблони" in text or "Available templates" in text


def test_format_reply_uses_tool_entities():
    """Test format reply uses tool entities."""
    msgs = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c1"}],
            "content": None,
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "get_category_entities",
            "content": "ENTITIES\nfield1|Label|text|1",
        },
    ]
    text = server.format_reply_from_messages(msgs)
    assert "field1" in text
