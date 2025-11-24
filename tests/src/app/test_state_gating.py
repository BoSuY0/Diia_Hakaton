import json
import types
import pytest

from backend.api.http import server
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState


@pytest.mark.asyncio
async def test_filter_tools_respects_state_allowed(monkeypatch, mock_settings, mock_categories_data):
    # Prepare session with category and state so _get_effective_state returns category_selected
    s = get_or_create_session("state_gate")
    s.category_id = mock_categories_data
    s.state = SessionState.CATEGORY_SELECTED
    save_session(s)

    # Dummy tool definitions/registry
    tool_defs = [{"function": {"name": "fc"}}, {"function": {"name": "other"}}]

    class DummyTool:
        def __init__(self, name, alias):
            self.name = name
            self.alias = alias

    def fake_get_definitions(minified=True):
        return tool_defs

    def fake_get_by_alias(alias):
        if alias == "fc":
            return DummyTool("find_category_by_query", "fc")
        if alias == "other":
            return DummyTool("unknown", "other")
        return None

    monkeypatch.setattr("backend.api.http.server.tool_registry.get_definitions", fake_get_definitions)
    monkeypatch.setattr("backend.api.http.server.tool_registry.get_by_alias", fake_get_by_alias)

    filtered = await server._filter_tools_for_session("state_gate", [], has_category_tool=True)
    names = [t["function"]["name"] for t in filtered]
    assert "fc" in names
    assert "other" not in names
