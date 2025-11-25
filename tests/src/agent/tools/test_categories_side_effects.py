"""Tests for category tool side effects."""
import pytest
from backend.agent.tools.categories import FindCategoryByQueryTool
from backend.infra.persistence.store import get_or_create_session, load_session
from backend.domain.categories.index import store


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_find_category_no_side_effect(mock_categories_data):
    """Test that FindCategoryByQueryTool does NOT automatically update session state."""
    # Setup: ensure category exists (provided by mock_categories_data fixture)
    # and create a fresh session
    session_id = "test_sess_side_effect"
    s = get_or_create_session(session_id)
    assert s.category_id is None

    store.load()

    # Execute the search tool
    tool = FindCategoryByQueryTool()
    # "Test Cat" corresponds to "test_cat" in mock_categories_data fixture
    args = {"query": "Test", "session_id": session_id}

    result = await tool.execute(args, {})

    # The tool should find the category
    assert result["category_id"] == "test_cat"

    # CRITICAL CHECK: The session state should NOT be updated automatically.
    # It should remain None until explicitly set by SetCategoryTool.
    s_after = load_session(session_id)

    # If this assertion fails (is not None), it means the bug is present.
    assert s_after.category_id is None, "FindCategoryByQueryTool should not automatically set session.category_id"
