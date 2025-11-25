"""Template metadata loading utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.domain.templates.registry import TemplateMeta, registry


@dataclass
class TemplateField:
    """Represents a field definition in a template."""
    id: str
    label: str
    type: str
    required: bool
    placeholder: str


def get_template_fields(template_id: str) -> List[TemplateField]:
    """Load and return fields for a given template."""
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
