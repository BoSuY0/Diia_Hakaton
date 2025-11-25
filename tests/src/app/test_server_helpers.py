"""Tests for server helper functions."""
import pytest

from backend.api.http import server


def test_detect_lang_uk_en():  # pylint: disable=protected-access
    """Test detect language for Ukrainian and English."""
    assert server._detect_lang("Привіт") == "uk"
    assert server._detect_lang("Hello") == "en"


def test_last_user_message_text_handles_structured():  # pylint: disable=protected-access
    """Test last user message text handles structured content."""
    msgs = [
        {"role": "user", "content": [{"text": "First"}, {"text": ""}]},
        {"role": "assistant", "content": "Reply"},
        {"role": "user", "content": [{"text": ""}, {"text": "Second"}]},
    ]
    assert server._last_user_message_text(msgs) == "Second"


def test_canonical_args_sorts_keys():  # pylint: disable=protected-access
    """Test canonical args sorts keys."""
    raw = '{"b":1,"a":2}'
    canon = server._canonical_args(raw)
    assert canon == '{"a":2,"b":1}'


def test_inject_session_id_adds_and_expands_alias():  # pylint: disable=protected-access
    """Test inject session id adds and expands alias."""
    args = '{"cid": "cat1", "f": "field1"}'
    injected = server._inject_session_id(args, "sess1", "upsert_field")
    data = server.json.loads(injected)
    assert data["session_id"] == "sess1"
    # alias cid -> category_id should be preserved as explicit field when not session-aware
    assert data["category_id"] == "cat1"
    assert data["field"] == "field1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_get_effective_state_uses_saved_when_has_category_tool(
    monkeypatch, mock_categories_data  # pylint: disable=unused-argument
):  # pylint: disable=protected-access
    """Test that _get_effective_state uses saved state correctly."""
    # pylint: disable-next=import-outside-toplevel
    from backend.infra.persistence.store import get_or_create_session, save_session
    s = get_or_create_session("eff_state")
    s.category_id = mock_categories_data
    s.state = server.SessionState.TEMPLATE_SELECTED
    save_session(s)
    state = await server._get_effective_state("eff_state", [], has_category_tool=False)
    assert state == "template_selected"


def test_prune_strips_orphan_tools():  # pylint: disable=protected-access
    """Test prune strips orphan tools."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "tool_calls": [{"id": "call1"}]},
        {"role": "tool", "tool_call_id": "call1", "content": "ok"},
        {"role": "tool", "tool_call_id": "orphan", "content": "drop me"},
    ]
    pruned = server._prune_messages(msgs)
    roles = [m["role"] for m in pruned]
    assert roles.count("tool") == 1


def test_format_reply_uses_tool_templates():  # pylint: disable=protected-access
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
    text = server._format_reply_from_messages(msgs)
    assert "Доступні шаблони" in text or "Available templates" in text


def test_format_reply_uses_tool_entities():  # pylint: disable=protected-access
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
    text = server._format_reply_from_messages(msgs)
    assert "field1" in text
