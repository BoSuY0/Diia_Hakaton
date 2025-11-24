import json
import sys
import types

# Provide lightweight stubs to satisfy imports without external deps (redis, glide).
if "redis" not in sys.modules:
    sys.modules["redis"] = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: None))
if "glide" not in sys.modules:
    glide_stub = types.SimpleNamespace(
        GlideClusterClient=type("GlideClusterClient", (), {"create": staticmethod(lambda config: None)}),
        GlideClusterClientConfiguration=type("GlideClusterClientConfiguration", (), {}),
        NodeAddress=type("NodeAddress", (), {}),
    )
    sys.modules["glide"] = glide_stub

from backend.domain.categories import index as categories_index
from backend.domain.sessions.models import Session, FieldState
from backend.domain.services.fields import get_required_fields, validate_session_readiness


def _write_custom_meta(tmp_root):
    meta_dir = tmp_root / "assets" / "meta_data" / "meta_data_categories_documents"
    meta_dir.mkdir(parents=True, exist_ok=True)

    index_path = meta_dir / "categories_index.json"
    index_path.write_text(
        json.dumps(
            {
                "categories": [
                    {"id": "custom", "label": "Custom", "meta_filename": "custom.json"}
                ]
            }
        ),
        encoding="utf-8",
    )

    (meta_dir / "custom.json").write_text(
        json.dumps(
            {
                "category_id": "custom",
                "templates": [{"id": "custom_template", "name": "Custom", "file": "custom_contract.docx"}],
                "roles": {
                    "party_a": {"label": "A", "allowed_person_types": ["individual"]},
                    "party_b": {"label": "B", "allowed_person_types": ["individual"]},
                },
                "party_modules": {
                    "individual": {
                        "label": "Ind",
                        "fields": [{"field": "name", "label": "Name", "required": True}],
                    }
                },
                "contract_fields": [
                    {"field": "contract_city", "label": "Місто", "required": False, "ai_required": True},
                    {"field": "contract_subject", "label": "Предмет", "required": False, "ai_required": True},
                ],
            }
        ),
        encoding="utf-8",
    )

    return index_path


def _reload_store(index_path):
    categories_index._CATEGORIES_PATH = index_path
    categories_index.store._categories = {}
    categories_index.store.load()


def test_ai_required_fields_are_exposed(mock_settings, tmp_path):
    index_path = _write_custom_meta(tmp_path)
    _reload_store(index_path)

    session = Session(session_id="s1", category_id="custom", template_id="custom_template")
    required = get_required_fields(session)

    ai_fields = {f.field_name: f for f in required if f.ai_required}
    assert set(ai_fields.keys()) == {"contract_city", "contract_subject"}
    assert all(f.required is False for f in ai_fields.values())


def test_ai_required_fields_block_readiness_until_filled(mock_settings, tmp_path):
    index_path = _write_custom_meta(tmp_path)
    _reload_store(index_path)

    session = Session(session_id="s2", category_id="custom", template_id="custom_template")
    session.party_types = {"party_a": "individual", "party_b": "individual"}
    session.party_fields = {
        "party_a": {"name": FieldState(status="ok")},
        "party_b": {"name": FieldState(status="ok")},
    }

    # Not filled -> not ready
    assert validate_session_readiness(session) is False

    # Fill AI-only fields -> becomes ready (no other required fields)
    session.contract_fields["contract_city"] = FieldState(status="ok")
    session.contract_fields["contract_subject"] = FieldState(status="ok")
    assert validate_session_readiness(session) is True
