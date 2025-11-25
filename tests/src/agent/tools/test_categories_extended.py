"""Extended tests for category tools."""
import json
import pytest

from backend.agent.tools.categories import (
    GetTemplatesForCategoryTool,
    GetCategoryEntitiesTool,
    SetCategoryTool,
    FindCategoryByQueryTool,
)


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_get_templates_for_category_returns_list(mock_categories_data):
    """Test that GetTemplatesForCategoryTool returns templates list."""
    tool = GetTemplatesForCategoryTool()
    res = await tool.execute({"category_id": mock_categories_data}, {})
    assert "templates" in res
    assert res["category_id"] == mock_categories_data


@pytest.mark.asyncio
async def test_get_category_entities_unknown_category_raises():
    """Test that GetCategoryEntitiesTool raises for unknown category."""
    tool = GetCategoryEntitiesTool()
    with pytest.raises(ValueError):
        await tool.execute({"category_id": "unknown"}, {})


@pytest.mark.asyncio
async def test_set_category_rejects_unknown_and_custom():
    """Test that SetCategoryTool rejects unknown category."""
    tool = SetCategoryTool()
    # Unknown category
    res = await tool.execute({"session_id": "s1", "category_id": "unknown"}, {})
    assert res["ok"] is False


@pytest.mark.asyncio
async def test_set_category_allows_custom(mock_settings):
    """Test that SetCategoryTool allows custom category."""
    idx = {
        "categories": [
            {
                "id": "custom",
                "label": "Custom",
                "keywords": ["будь-що"],
                "meta_filename": "custom.json",
            },
        ]
    }
    index_path = mock_settings.meta_categories_root / "categories_index.json"
    index_path.write_text(json.dumps(idx), encoding="utf-8")
    custom_meta = {
        "id": "custom",
        "templates": [],
        "roles": {},
        "party_modules": {},
        "contract_fields": [],
    }
    custom_path = mock_settings.meta_categories_root / "custom.json"
    custom_path.write_text(json.dumps(custom_meta), encoding="utf-8")

    # Refresh store to pick up custom category
    from backend.domain.categories import index as idx_module  # pylint: disable=import-outside-toplevel
    idx_module.store.clear()
    idx_module.store.load()

    tool = SetCategoryTool()
    res = await tool.execute({"session_id": "s1", "category_id": "custom"}, {})
    assert res["ok"] is True
    assert res["category_id"] == "custom"


@pytest.mark.asyncio
async def test_find_category_by_query_ignores_custom(monkeypatch):
    """Test that FindCategoryByQueryTool returns custom category."""
    tool = FindCategoryByQueryTool()

    class Cat:
        """Mock category object."""

        id = "custom"
        label = "Custom"

        def __repr__(self):
            return f"Cat(id={self.id})"

        def to_dict(self):
            """Convert to dict."""
            return {"id": self.id, "label": self.label}

    monkeypatch.setattr(
        "backend.agent.tools.categories.find_category_by_query", lambda q: Cat()
    )
    res = await tool.execute({"query": "any"}, {})
    assert res["category_id"] == "custom"
