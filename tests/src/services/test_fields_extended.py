import json

from backend.domain.services.fields import get_required_fields
from backend.infra.persistence.store import get_or_create_session, save_session


def _setup_category(settings, roles=True):
    meta = {
        "category_id": "fields_cat",
        "templates": [{"id": "t1", "name": "T1", "file": "f1.docx"}],
        "roles": {
            "lessor": {"label": "Lessor", "allowed_person_types": ["individual"]},
            "lessee": {"label": "Lessee", "allowed_person_types": ["individual"]},
        } if roles else {},
        "party_modules": {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            }
        },
        "contract_fields": [{"field": "cf1", "label": "CF1", "required": True}],
    }
    path = settings.meta_categories_root / "fields_cat.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    idx = settings.meta_categories_root / "categories_index.json"
    idx.write_text(json.dumps({"categories": [{"id": "fields_cat", "label": "Fields"}]}), encoding="utf-8")
    from backend.domain.categories.index import store as category_store
    from backend.domain.categories import index as category_index
    category_index._CATEGORIES_PATH = idx
    category_store._categories = {}
    category_store.load()


def test_get_required_fields_full_mode(mock_settings):
    _setup_category(mock_settings)
    s = get_or_create_session("req_full")
    s.category_id = "fields_cat"
    s.filling_mode = "full"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    save_session(s)

    reqs = get_required_fields(s)
    keys = {r.key for r in reqs}
    # Both roles and contract field
    assert "lessor.name" in keys
    assert "lessee.name" in keys
    assert "cf1" in keys


def test_get_required_fields_partial_mode(mock_settings):
    _setup_category(mock_settings)
    s = get_or_create_session("req_partial")
    s.category_id = "fields_cat"
    s.role = "lessor"
    s.person_type = "individual"
    s.filling_mode = "partial"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    save_session(s)

    reqs = get_required_fields(s)
    keys = {r.key for r in reqs}
    # Only current role + contract field
    assert "lessor.name" in keys
    assert "lessee.name" not in keys
    assert "cf1" in keys
