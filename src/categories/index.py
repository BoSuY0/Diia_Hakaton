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
    description: str
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
                description=raw.get("description", ""),
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




def _ngrams(text: str, n: int = 3) -> set:
    """Generate character n-grams from text."""
    text = text.lower()
    return {text[i:i+n] for i in range(len(text) - n + 1)}


def _similarity(text1: str, text2: str, n: int = 3) -> float:
    """Calculate Jaccard similarity between two texts using character n-grams."""
    ngrams1 = _ngrams(text1, n)
    ngrams2 = _ngrams(text2, n)
    
    if not ngrams1 or not ngrams2:
        return 0.0
    
    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)
    
    return intersection / union if union > 0 else 0.0


def find_category_by_query(query: str) -> Optional[Category]:
    """
    Пошук категорії по тексту з використанням n-gram схожості.
    Рахуємо схожість між запитом і label + description.
    """
    if not query.strip():
        return None
    
    best: Optional[Category] = None
    best_score = 0.0

    for category in store.categories.values():
        # Combine label and description for matching
        category_text = f"{category.label} {category.description}"
        
        # Calculate similarity
        score = _similarity(query, category_text, n=3)
        
        if score > best_score:
            best_score = score
            best = category

    # Only return if similarity is above threshold
    return best if best_score > 0.1 else None


def get_roles(category_id: str) -> List[str]:
    """
    Повертає список ролей для категорії (lessor, lessee, ...).
    Читає з метаданих категорії (roles).
    """
    category = store.get(category_id)
    if not category:
        return []
    meta = _load_meta(category)
    roles = meta.get("roles", {})
    return list(roles.keys())


def get_role_info(category_id: str, role: str) -> Dict[str, Any]:
    """
    Повертає інформацію про роль (label, allowed_person_types).
    Приклад: {"label": "Орендодавець", "allowed_person_types": ["individual", "fop", "company"]}
    """
    category = store.get(category_id)
    if not category:
        return {}
    meta = _load_meta(category)
    roles = meta.get("roles", {})
    return roles.get(role, {})




