from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.common.config import BASE_DIR, settings
from src.common.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Category:
    id: str
    label: str
    meta_path: Path  # шлях до JSON-файлу категорії всередині meta_data_categories


@dataclass
class Entity:
    field: str
    type: str
    label: str
    required: bool


@dataclass
class TemplateInfo:
    id: str
    name: str
    file: str


@dataclass
class PartyField:
    field: str
    label: str
    required: bool


_CATEGORIES_PATH = settings.meta_categories_root / "categories_index.json"


class CategoryStore:
    def __init__(self) -> None:
        self._categories: Dict[str, Category] = {}

    def load(self) -> None:
        if not _CATEGORIES_PATH.exists():
            logger.warning("Categories index not found at %s", _CATEGORIES_PATH)
            self._categories = {}
            return
        with _CATEGORIES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._categories = {}
        for raw in data.get("categories", []):
            meta_filename = raw.get("meta_filename") or f"{raw['id']}.json"
            meta_path = settings.meta_categories_root / meta_filename
            self._categories[raw["id"]] = Category(
                id=raw["id"],
                label=raw["label"],
                meta_path=meta_path,
            )

    @property
    def categories(self) -> Dict[str, Category]:
        if not self._categories:
            self.load()
        return self._categories

    def get(self, category_id: str) -> Optional[Category]:
        return self.categories.get(category_id)


store = CategoryStore()


def _load_meta(category: Category) -> dict:
    with category.meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_entities(category_id: str) -> List[Entity]:
    category = store.get(category_id)
    if not category:
        raise ValueError(f"Unknown category_id: {category_id}")
    data = _load_meta(category)
    entities: List[Entity] = []

    # Новий формат: contract_fields як основні ентіті договору.
    contract_fields = data.get("contract_fields")
    if contract_fields:
        for raw in contract_fields:
            entities.append(
                Entity(
                    field=raw["field"],
                    type="text",
                    label=raw.get("label", raw["field"]),
                    required=bool(raw.get("required", True)),
                )
            )
        return entities

    # Зворотна сумісність зі старим форматом "entities".
    for raw in data.get("entities", []):
        entities.append(
            Entity(
                field=raw["field"],
                type=raw.get("type", "text"),
                label=raw.get("label", raw["field"]),
                required=bool(raw.get("required", True)),
            )
        )
    return entities


def list_templates(category_id: str) -> List[TemplateInfo]:
    category = store.get(category_id)
    if not category:
        raise ValueError(f"Unknown category_id: {category_id}")
    data = _load_meta(category)
    templates: List[TemplateInfo] = []
    for raw in data.get("templates", []):
        templates.append(
            TemplateInfo(
                id=raw["id"],
                name=raw.get("name", raw["id"]),
                file=raw.get("file", f"{raw['id']}.docx"),
            )
        )
    return templates


def list_party_fields(category_id: str, person_type: str) -> List[PartyField]:
    """
    Повертає перелік полів сторони договору (name, address, тощо)
    для вказаного типу особи (individual / fop / company) усередині категорії.
    """
    category = store.get(category_id)
    if not category:
        raise ValueError(f"Unknown category_id: {category_id}")
    data = _load_meta(category)
    modules = data.get("party_modules") or {}
    module = modules.get(person_type)
    if not module:
        return []
    fields: List[PartyField] = []
    for raw in module.get("fields", []):
        fields.append(
            PartyField(
                field=raw["field"],
                label=raw.get("label", raw["field"]),
                required=bool(raw.get("required", True)),
            )
        )
    return fields


def find_category_by_query(query: str) -> Optional[Category]:
    """
    Дуже проста евристика пошуку категорії по тексту:
    рахуємо кількість спільних слів між запитом і label.
    """
    query_terms = {t.lower() for t in query.split() if t.strip()}
    best: Optional[Category] = None
    best_score = 0

    for category in store.categories.values():
        label_terms = {t.lower() for t in category.label.split() if t.strip()}
        score = len(query_terms & label_terms)
        if score > best_score:
            best_score = score
            best = category

    return best
