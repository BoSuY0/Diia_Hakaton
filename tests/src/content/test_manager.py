import pytest
from backend.domain.content.manager import ContentManager

@pytest.fixture
def content_manager(mock_settings):
    return ContentManager()

def test_create_category(content_manager, mock_settings):
    cat_id = "new_cat"
    content_manager.add_category(cat_id, "New Category")
    
    cat_file = mock_settings.meta_categories_root / f"{cat_id}.json"
    assert cat_file.exists()
    
    # Verify index update
    index_file = mock_settings.meta_categories_root / "categories_index.json"
    import json
    with index_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    cats = {c["id"]: c for c in data["categories"]}
    assert cat_id in cats
    assert cats[cat_id]["label"] == "New Category"

def test_add_template(content_manager, mock_categories_data, mock_settings):
    # mock_categories_data creates "test_cat"
    content_manager.add_template("test_cat", "t2", "Template 2", "t2.docx")
    
    import json
    cat_file = mock_settings.meta_categories_root / "test_cat.json"
    with cat_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    templates = {t["id"]: t for t in data["templates"]}
    assert "t2" in templates
    assert templates["t2"]["name"] == "Template 2"

def test_add_field(content_manager, mock_categories_data, mock_settings):
    content_manager.add_field("test_cat", "cf2", "Contract Field 2", required=False)
    
    import json
    cat_file = mock_settings.meta_categories_root / "test_cat.json"
    with cat_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    fields = {f["field"]: f for f in data["contract_fields"]}
    assert "cf2" in fields
    assert fields["cf2"]["label"] == "Contract Field 2"
    assert fields["cf2"]["required"] is False
