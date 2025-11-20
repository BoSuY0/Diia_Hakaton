
import pytest
from src.agent.tools.categories import FindCategoryByQueryTool
from src.sessions.store import get_or_create_session, load_session
from src.categories.index import store, Category
from pathlib import Path

# This test verifies that FindCategoryByQueryTool does NOT automatically update the session state.
def test_find_category_no_side_effect(mock_settings, mock_categories_data):
    # Setup: ensure category exists (provided by mock_categories_data fixture)
    # and create a fresh session
    session_id = "test_sess_side_effect"
    s = get_or_create_session(session_id)
    assert s.category_id is None

    # Execute the search tool
    tool = FindCategoryByQueryTool()
    # "Test Cat" corresponds to "test_cat" in mock_categories_data fixture
    args = {"query": "Test", "session_id": session_id}

    result = tool.execute(args, {})

    # The tool should find the category
    assert result["category_id"] == "test_cat"

    # CRITICAL CHECK: The session state should NOT be updated automatically.
    # It should remain None until explicitly set by SetCategoryTool.
    s_after = load_session(session_id)

    # If this assertion fails (is not None), it means the bug is present.
    assert s_after.category_id is None, "FindCategoryByQueryTool should not automatically set session.category_id"
