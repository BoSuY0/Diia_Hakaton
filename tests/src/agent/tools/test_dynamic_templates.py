import json
from pathlib import Path

from src.agent.tools.dynamic_templates import create_dynamic_contract_template
from src.common.config import settings


def test_create_dynamic_contract_template_creates_files(tmp_path, mock_settings):
    title = "Test Contract"
    contract_text = "1. Предмет договору\nПункт\n{{price}}"
    fields_metadata = [{"field": "price", "label": "Ціна", "required": True, "type": "number"}]
    roles = {"party_a": "A", "party_b": "B"}

    template_id = create_dynamic_contract_template(title, contract_text, fields_metadata, roles)

    docx_path = settings.assets_dir / "documents" / "templates" / "dynamic" / f"{template_id}.docx"
    meta_path = settings.assets_dir / "meta_data" / "dynamic" / f"{template_id}.json"
    assert docx_path.exists()
    assert meta_path.exists()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["template_id"] == template_id
    assert {"field": "price", "label": "Ціна", "required": True, "type": "number"} in meta["contract_fields"]
