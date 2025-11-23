from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.config import BASE_DIR, settings
from src.common.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Category:
    id: str
    label: str
    meta_path: Path
    keywords: List[str] = None


@dataclass
class Entity:
    field: str
    type: str
    label: str
    required: bool
    ai_required: bool = False


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


_CATEGORIES_PATH: Path | None = None


def _categories_path() -> Path:
    """
    Return path to categories_index.json. Allows test overrides via
    monkeypatching _CATEGORIES_PATH or by mutating settings.meta_categories_root.
    """
    if _CATEGORIES_PATH:
        return _CATEGORIES_PATH
    return settings.meta_categories_root / "categories_index.json"


class CategoryStore:
    def __init__(self) -> None:
        self._categories: Dict[str, Category] = {}

    def load(self) -> None:
        path = _categories_path()
        if not path.exists():
            logger.warning("Categories index not found at %s", path)
            self._categories = {}
            return
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._categories = {}
        for raw in data.get("categories", []):
            meta_filename = raw.get("meta_filename") or f"{raw['id']}.json"
            meta_path = settings.meta_categories_root / meta_filename
            self._categories[raw["id"]] = Category(
                id=raw["id"],
                label=raw["label"],
                meta_path=meta_path,
                keywords=raw.get("keywords", [])
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
                    ai_required=bool(raw.get("ai_required", False)),
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


def get_party_schema(category_id: str) -> Dict[str, Any]:
    """
    Повертає опис ролей договору та поля для кожного типу особи
    у межах категорії. Використовується для побудови форм на фронтенді
    без жорсткого кодування сторін і полів.
    """
    category = store.get(category_id)
    if not category:
        raise ValueError(f"Unknown category_id: {category_id}")

    data = _load_meta(category)
    roles_raw = data.get("roles") or {}
    modules_raw = data.get("party_modules") or {}

    roles: List[Dict[str, Any]] = []
    main_role = data.get("main_role") or data.get("primary_role")
    allowed_fallback = list(modules_raw.keys())
    for role_id, info in roles_raw.items():
        allowed_types = info.get("allowed_person_types") or allowed_fallback
        roles.append(
            {
                "id": role_id,
                "label": info.get("label", role_id),
                "allowed_person_types": allowed_types,
            }
        )
        if not main_role:
            main_role = role_id  # default to first role

    person_types: List[Dict[str, Any]] = []
    for person_type, info in modules_raw.items():
        fields: List[Dict[str, Any]] = []
        for raw in info.get("fields", []):
            fields.append(
                {
                    "field": raw["field"],
                    "label": raw.get("label", raw["field"]),
                    "required": bool(raw.get("required", True)),
                    "type": raw.get("type", "text"),
                }
            )
        person_types.append(
            {
                "person_type": person_type,
                "label": info.get("label", person_type),
                "fields": fields,
            }
        )

    return {
        "category_id": category_id,
        "main_role": main_role,
        "roles": roles,
        "person_types": person_types,
    }


def find_category_by_query(query: str) -> Optional[Category]:
    """
    Search category by keywords overlap only (labels are ignored).
    """
    query_norm = query.lower()
    query_terms = {t for t in query_norm.split() if t.strip()}
    best: Optional[Category] = None
    best_score = 0

    for category in store.categories.values():
        if category.id == "custom":
            continue
        # Check keywords
        keywords = {k.lower() for k in (category.keywords or [])}
        kw_score = len(query_terms & keywords) * 2

        # Substring bonuses (simple stemming-like) for keywords only
        for kw in keywords:
            if kw and kw in query_norm:
                kw_score += 1

        # Додатковий бонус за часткові збіги (перші 5 літер), щоб ловити відмінки
        for term in query_terms:
            for kw in keywords:
                stem = kw[:5]
                if stem and stem in term:
                    kw_score += 1

        total_score = kw_score
        
        if total_score > best_score:
            best_score = total_score
            best = category

    if best:
        return best

    return None
