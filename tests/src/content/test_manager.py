"""Tests for content manager."""
import json

import pytest

from backend.domain.content.manager import ContentManager


@pytest.fixture
def content_manager(mock_settings):  # pylint: disable=unused-argument
    """Create content manager fixture."""
    return ContentManager()


def test_create_category(content_manager, mock_settings):  # pylint: disable=redefined-outer-name
    """Test creating a category."""
    cat_id = "new_cat"
    content_manager.add_category(cat_id, "New Category")

    cat_file = mock_settings.meta_categories_root / f"{cat_id}.json"
    assert cat_file.exists()

    # Verify index update
    index_file = mock_settings.meta_categories_root / "categories_index.json"
    with index_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    cats = {c["id"]: c for c in data["categories"]}
    assert cat_id in cats
    assert cats[cat_id]["label"] == "New Category"


def test_add_template(content_manager, mock_categories_data, mock_settings):  # noqa: ARG001
    """Test adding a template."""
    # mock_categories_data creates "test_cat"
    content_manager.add_template("test_cat", "t2", "Template 2", "t2.docx")
    cat_file = mock_settings.meta_categories_root / "test_cat.json"
    with cat_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    templates = {t["id"]: t for t in data["templates"]}
    assert "t2" in templates
    assert templates["t2"]["name"] == "Template 2"


def test_add_field(content_manager, mock_categories_data, mock_settings):  # noqa: ARG001
    """Test adding a field."""
    content_manager.add_field("test_cat", "cf2", "Contract Field 2", required=False)
    cat_file = mock_settings.meta_categories_root / "test_cat.json"
    with cat_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    fields = {fld["field"]: fld for fld in data["contract_fields"]}
    assert "cf2" in fields
    assert fields["cf2"]["label"] == "Contract Field 2"
    assert fields["cf2"]["required"] is False
