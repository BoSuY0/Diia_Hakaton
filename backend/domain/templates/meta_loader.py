from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.domain.templates.registry import TemplateMeta, registry


@dataclass
class TemplateField:
    id: str
    label: str
    type: str
    required: bool
    placeholder: str


def get_template_fields(template_id: str) -> List[TemplateField]:
    meta: TemplateMeta = registry.load(template_id)
    fields: List[TemplateField] = []
    for raw in meta.fields:
        fields.append(
            TemplateField(
                id=raw["id"],
                label=raw.get("label", raw["id"]),
                type=raw.get("type", "text"),
                required=bool(raw.get("required", True)),
                placeholder=raw.get("placeholder", f"{{{{{raw['id']}}}}}"),
            )
        )
    return fields

