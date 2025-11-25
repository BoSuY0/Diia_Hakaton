"""Tests for category query search."""
import json

from backend.domain.categories import index as idx_module
from backend.domain.categories.index import (
    store as category_store,
    find_category_by_query,
)


def test_find_category_by_keywords(mock_settings):
    """Test that find_category_by_query matches keywords."""
    idx = {
        "categories": [
            {
                "id": "lease",
                "label": "Оренда житла",
                "keywords": ["оренда", "квартира"],
                "meta_filename": "lease.json",
            },
            {
                "id": "sale",
                "label": "Купівля",
                "keywords": ["купівля"],
                "meta_filename": "sale.json",
            },
        ]
    }
    index_path = mock_settings.meta_categories_root / "categories_index.json"
    index_path.write_text(json.dumps(idx), encoding="utf-8")
    for cid in ["lease", "sale"]:
        meta = {
            "id": cid,
            "templates": [],
            "roles": {},
            "party_modules": {},
            "contract_fields": [],
        }
        meta_path = mock_settings.meta_categories_root / f"{cid}.json"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    category_store.clear()
    category_store.load()

    best = find_category_by_query("хочу орендувати квартиру")
    assert best is not None
    assert best.id == "lease"


def test_find_category_returns_custom_when_present(mock_settings):
    """Test that find_category_by_query returns custom category as fallback."""
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

    category_store.clear()
    idx_module.store.clear()
    category_store.load()

    best = find_category_by_query("будь-що")
    assert best is not None
    assert best.id == "custom"
