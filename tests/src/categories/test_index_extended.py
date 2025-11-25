"""Extended tests for category index functions."""
import json
import pytest

from backend.domain.categories.index import (
    list_entities,
    list_templates,
    list_party_fields,
    find_category_by_query,
    store as category_store,
)


def _write_category(settings, cat_id="idx_cat"):
    meta = {
        "category_id": cat_id,
        "templates": [{"id": "t1", "name": "Name1", "file": "f1.docx"}],
        "roles": {"lessor": {"label": "Lessor", "allowed_person_types": ["individual"]}},
        "party_modules": {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            }
        },
        "contract_fields": [{"field": "cf1", "label": "CF1", "required": True}],
    }
    meta_path = settings.meta_categories_root / f"{cat_id}.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    idx_path = settings.meta_categories_root / "categories_index.json"
    idx_data = {"categories": [{"id": cat_id, "label": "Label", "keywords": ["label"]}]}
    idx_path.write_text(json.dumps(idx_data), encoding="utf-8")
    category_store.clear()
    category_store.load()


@pytest.mark.usefixtures("mock_settings")
def test_list_entities_raises_for_unknown():
    """Test that list_entities raises ValueError for unknown category."""
    with pytest.raises(ValueError):
        list_entities("unknown")


def test_list_entities_and_templates(mock_settings):
    """Test list_entities and list_templates return correct data."""
    _write_category(mock_settings, cat_id="idx_cat")
    ents = list_entities("idx_cat")
    assert ents[0].field == "cf1" and ents[0].required
    tmpls = list_templates("idx_cat")
    assert tmpls[0].id == "t1"


def test_list_party_fields(mock_settings):
    """Test list_party_fields returns fields for person type."""
    _write_category(mock_settings, cat_id="idx_cat_pf")
    fields = list_party_fields("idx_cat_pf", "individual")
    assert fields[0].field == "name"

    # Unknown person_type returns empty list
    assert not list_party_fields("idx_cat_pf", "company")


def test_find_category_by_query_scores_keywords(mock_settings):
    """Test that find_category_by_query scores by keywords."""
    _write_category(mock_settings, cat_id="search_cat")
    best = find_category_by_query("label")
    assert best is not None
    assert best.id == "search_cat"
