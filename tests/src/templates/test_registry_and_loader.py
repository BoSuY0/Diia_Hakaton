import json
from pathlib import Path

import pytest

from backend.domain.templates.registry import TemplateRegistry
from backend.domain.templates.meta_loader import get_template_fields
from backend.shared.errors import MetaNotFoundError


def _write_category_with_template(settings, cat_id="tmpl_cat", templ_id="t1", filename="file.docx"):
    meta = {
        "category_id": cat_id,
        "templates": [{"id": templ_id, "name": "Template 1", "file": filename}],
        "roles": {"lessor": {"label": "L", "allowed_person_types": ["individual"]}},
        "party_modules": {
            "individual": {"label": "Indiv", "fields": [{"field": "name", "label": "Name", "required": True}]}
        },
        "contract_fields": [{"field": "cf1", "label": "CF1", "required": True}],
    }
    cat_path = settings.meta_categories_root / f"{cat_id}.json"
    cat_path.write_text(json.dumps(meta), encoding="utf-8")
    idx_path = settings.meta_categories_root / "categories_index.json"
    idx_path.write_text(json.dumps({"categories": [{"id": cat_id, "label": "Label"}]}), encoding="utf-8")
    from backend.domain.categories.index import store as category_store
    category_store.clear()
    category_store.load()

    # Prepare docx path
    doc_path = settings.default_documents_root / cat_id / filename
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.touch()
    return templ_id


def test_template_registry_lists_and_loads(mock_settings):
    templ_id = _write_category_with_template(mock_settings, cat_id="tmpl_cat", templ_id="t1", filename="f1.docx")
    reg = TemplateRegistry()
    templates = reg.list_templates()
    assert templ_id in templates
    meta = reg.load(templ_id)
    assert meta.template_id == templ_id
    assert meta.fields  # at least the contract field
    assert meta.file_template_path.exists()


def test_template_registry_fallback_path(mock_settings):
    # File placed in root default_documents_root, not in category subdir
    doc = mock_settings.default_documents_root / "orphan.docx"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.touch()
    templ_id = _write_category_with_template(mock_settings, cat_id="fallback_cat", templ_id="t_fallback", filename="orphan.docx")
    reg = TemplateRegistry()
    meta = reg.load(templ_id)
    assert meta.file_template_path.name == "orphan.docx"
    assert meta.file_template_path.exists()


def test_template_registry_missing_raises(mock_settings):
    reg = TemplateRegistry()
    with pytest.raises(MetaNotFoundError):
        reg.load("unknown_template")


def test_get_template_fields_builds_defaults(mock_settings):
    templ_id = _write_category_with_template(mock_settings, cat_id="tmpl_fields", templ_id="t_fields", filename="f.docx")
    fields = get_template_fields(templ_id)
    ids = {f.id for f in fields}
    assert "cf1" in ids
    # Placeholder should be generated with {{id}}
    cf1 = next(f for f in fields if f.id == "cf1")
    assert "{{cf1}}" in cf1.placeholder or cf1.placeholder == "cf1"
