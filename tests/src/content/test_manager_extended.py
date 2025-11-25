"""Extended tests for content manager."""
import json

from backend.domain.content.manager import ContentManager


def test_add_category_creates_index_and_meta(mock_settings, tmp_path):  # pylint: disable=unused-argument
    """Test add category creates index and meta."""
    mgr = ContentManager()
    mgr.add_category("cat_new", "Label")

    index_path = mock_settings.meta_categories_root / "categories_index.json"
    index = index_path.read_text(encoding="utf-8")
    data = json.loads(index)
    assert any(c["id"] == "cat_new" for c in data["categories"])

    meta_path = mock_settings.meta_categories_root / "cat_new.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["category_id"] == "cat_new"
    assert "party_modules" in meta


def test_add_template_appends_once(mock_settings):
    """Test add template appends once."""
    mgr = ContentManager()
    mgr.add_category("cat_templ", "Label")
    mgr.add_template("cat_templ", "t1", "Template 1")
    mgr.add_template("cat_templ", "t1", "Template 1 duplicate")  # should not duplicate

    meta_path = mock_settings.meta_categories_root / "cat_templ.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    templates = [t["id"] for t in meta["templates"]]
    assert templates.count("t1") == 1


def test_add_field_appends_once_and_backup(mock_settings):
    """Test add field appends once and backup."""
    mgr = ContentManager()
    mgr.add_category("cat_field", "Label")
    meta_path = mock_settings.meta_categories_root / "cat_field.json"

    # First add creates field
    mgr.add_field("cat_field", "f1", "Field 1", required=True)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert any(f["field"] == "f1" for f in meta["contract_fields"])

    # Add again should not duplicate but should create .bak before write
    mgr.add_field("cat_field", "f1", "Field 1", required=True)
    bak = meta_path.with_suffix(".json.bak")
    assert bak.exists()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert [f["field"] for f in meta["contract_fields"]].count("f1") == 1
