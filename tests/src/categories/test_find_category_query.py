import json

from backend.domain.categories.index import store as category_store, find_category_by_query


def test_find_category_by_keywords(tmp_path, mock_settings):
    # Build custom index with two categories
    idx = {
        "categories": [
            {"id": "lease", "label": "Оренда житла", "keywords": ["оренда", "квартира"], "meta_filename": "lease.json"},
            {"id": "sale", "label": "Купівля", "keywords": ["купівля"], "meta_filename": "sale.json"},
        ]
    }
    (mock_settings.meta_categories_root / "categories_index.json").write_text(json.dumps(idx), encoding="utf-8")
    # Meta files (minimal)
    for cid in ["lease", "sale"]:
        (mock_settings.meta_categories_root / f"{cid}.json").write_text(json.dumps({"id": cid, "templates": [], "roles": {}, "party_modules": {}, "contract_fields": []}), encoding="utf-8")

    category_store._categories = {}
    category_store.load()

    best = find_category_by_query("хочу орендувати квартиру")
    assert best is not None
    assert best.id == "lease"


def test_find_category_returns_custom_when_present(mock_settings, monkeypatch):
    # Prepare store with only custom
    idx = {
        "categories": [
            {"id": "custom", "label": "Custom", "keywords": ["будь-що"], "meta_filename": "custom.json"},
        ]
    }
    (mock_settings.meta_categories_root / "categories_index.json").write_text(json.dumps(idx), encoding="utf-8")
    (mock_settings.meta_categories_root / "custom.json").write_text(json.dumps({"id": "custom", "templates": [], "roles": {}, "party_modules": {}, "contract_fields": []}), encoding="utf-8")

    from backend.domain.categories import index as idx_module
    category_store._categories = {}
    idx_module.store._categories = {}
    category_store.load()

    best = find_category_by_query("будь-що")
    assert best is not None
    assert best.id == "custom"
