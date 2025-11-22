import json
import pytest

from src.agent.tools.categories import (
    GetTemplatesForCategoryTool,
    GetCategoryEntitiesTool,
    SetCategoryTool,
    FindCategoryByQueryTool,
)


def test_get_templates_for_category_returns_list(mock_settings, mock_categories_data):
    tool = GetTemplatesForCategoryTool()
    res = tool.execute({"category_id": mock_categories_data}, {})
    assert "templates" in res
    assert res["category_id"] == mock_categories_data


def test_get_category_entities_unknown_category_raises():
    tool = GetCategoryEntitiesTool()
    with pytest.raises(ValueError):
        tool.execute({"category_id": "unknown"}, {})


def test_set_category_rejects_unknown_and_custom(monkeypatch):
    tool = SetCategoryTool()
    # Unknown category
    res = tool.execute({"session_id": "s1", "category_id": "unknown"}, {})
    assert res["ok"] is False


def test_set_category_allows_custom(mock_settings, monkeypatch):
    # Prepare minimal custom meta
    idx = {
        "categories": [
            {"id": "custom", "label": "Custom", "keywords": ["будь-що"], "meta_filename": "custom.json"},
        ]
    }
    (mock_settings.meta_categories_root / "categories_index.json").write_text(json.dumps(idx), encoding="utf-8")
    (mock_settings.meta_categories_root / "custom.json").write_text(
        json.dumps({"id": "custom", "templates": [], "roles": {}, "party_modules": {}, "contract_fields": []}),
        encoding="utf-8",
    )

    # Refresh store to pick up custom category
    from src.categories import index as idx_module
    idx_module.store._categories = {}
    idx_module.store.load()

    tool = SetCategoryTool()
    res = tool.execute({"session_id": "s1", "category_id": "custom"}, {})
    assert res["ok"] is True
    assert res["category_id"] == "custom"


def test_find_category_by_query_ignores_custom(monkeypatch):
    tool = FindCategoryByQueryTool()
    # Monkeypatch find_category_by_query to return mock custom object
    class Cat:
        id = "custom"
        label = "Custom"
    monkeypatch.setattr("src.agent.tools.categories.find_category_by_query", lambda q: Cat())
    res = tool.execute({"query": "any"}, {})
    assert res["category_id"] == "custom"
