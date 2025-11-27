"""Category index and metadata management.

NEW ARCHITECTURE (v2):
- Categories are just groups (lease_real_estate, acts, nda)
- Each template has its own JSON file in templates/ folder
- Templates contain: template_id, category_id, name, file, roles, party_modules, contract_fields
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Category:
    """Category metadata (group of templates)."""

    id: str
    label: str


@dataclass
class Template:
    """Template metadata with all entities."""

    id: str
    category_id: str
    name: str
    file: str
    keywords: List[str] = field(default_factory=list)
    ai_only: bool = False
    meta_path: Optional[Path] = None


@dataclass
class Entity:
    """Contract field entity."""

    field: str
    type: str
    label: str
    required: bool
    ai_required: bool = False


@dataclass
class TemplateInfo:
    """Template metadata (lightweight, for listing)."""

    id: str
    name: str
    file: str


@dataclass
class PartyField:
    """Party field metadata."""

    field: str
    label: str
    required: bool


_CATEGORIES_PATH: Path | None = None
_TEMPLATES_DIR: Path | None = None


def _categories_path() -> Path:
    """Return path to index.json (main categories file)."""
    if _CATEGORIES_PATH:
        return _CATEGORIES_PATH
    return settings.meta_categories_root / "index.json"


def _templates_dir() -> Path:
    """Return path to contracts directory."""
    if _TEMPLATES_DIR:
        return _TEMPLATES_DIR
    return settings.meta_categories_root / "contracts"


class CategoryStore:
    """In-memory store for category metadata."""

    def __init__(self) -> None:
        self._categories: Dict[str, Category] = {}

    def load(self) -> None:
        """Load categories from index file."""
        path = _categories_path()
        if not path.exists():
            logger.warning("Categories index not found at %s", path)
            self._categories = {}
            return
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._categories = {}
        for raw in data.get("categories", []):
            self._categories[raw["id"]] = Category(
                id=raw["id"],
                label=raw["label"],
            )

    @property
    def categories(self) -> Dict[str, Category]:
        """Get all categories, loading if necessary."""
        if not self._categories:
            self.load()
        return self._categories

    def get(self, category_id: str) -> Optional[Category]:
        """Get category by ID."""
        return self.categories.get(category_id)

    def clear(self) -> None:
        """Clear internal cache. Useful for testing."""
        self._categories = {}


class TemplateStore:
    """In-memory store for template metadata."""

    def __init__(self) -> None:
        self._templates: Dict[str, Template] = {}
        self._templates_by_category: Dict[str, List[str]] = {}

    def load(self) -> None:
        """Load all templates from templates/ directory."""
        templates_path = _templates_dir()
        if not templates_path.exists():
            logger.warning("Templates directory not found at %s", templates_path)
            self._templates = {}
            self._templates_by_category = {}
            return

        self._templates = {}
        self._templates_by_category = {}

        for json_file in templates_path.glob("*.json"):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                
                template_id = data.get("template_id")
                category_id = data.get("category_id")
                
                if not template_id or not category_id:
                    logger.warning("Invalid template file %s: missing template_id or category_id", json_file)
                    continue

                template = Template(
                    id=template_id,
                    category_id=category_id,
                    name=data.get("name", template_id),
                    file=data.get("file", f"{template_id}.docx"),
                    keywords=data.get("keywords", []),
                    ai_only=data.get("ai_only", False),
                    meta_path=json_file,
                )
                self._templates[template_id] = template

                # Index by category
                if category_id not in self._templates_by_category:
                    self._templates_by_category[category_id] = []
                self._templates_by_category[category_id].append(template_id)

            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load template %s: %s", json_file, e)

        logger.info("Loaded %d templates from %s", len(self._templates), templates_path)

    @property
    def templates(self) -> Dict[str, Template]:
        """Get all templates, loading if necessary."""
        if not self._templates:
            self.load()
        return self._templates

    def get(self, template_id: str) -> Optional[Template]:
        """Get template by ID."""
        return self.templates.get(template_id)

    def get_by_category(self, category_id: str) -> List[Template]:
        """Get all templates for a category."""
        if not self._templates:
            self.load()
        template_ids = self._templates_by_category.get(category_id, [])
        return [self._templates[tid] for tid in template_ids if tid in self._templates]

    def clear(self) -> None:
        """Clear internal cache."""
        self._templates = {}
        self._templates_by_category = {}


store = CategoryStore()
template_store = TemplateStore()


# In-memory cache for template metadata (keyed by template_id)
_template_meta_cache: Dict[str, dict] = {}


def load_template_meta(template_id: str, use_cache: bool = True) -> dict:
    """
    Load template metadata JSON.
    
    Args:
        template_id: Template ID.
        use_cache: If True (default), use in-memory cache.
    
    Returns:
        Parsed JSON metadata dictionary.
    """
    if use_cache and template_id in _template_meta_cache:
        return _template_meta_cache[template_id]

    template = template_store.get(template_id)
    if not template or not template.meta_path:
        raise ValueError(f"Unknown template_id: {template_id}")

    with template.meta_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if use_cache:
        _template_meta_cache[template_id] = data

    return data


# BACKWARD COMPATIBILITY: load_meta still works with category
# but now it loads the first template of that category
_meta_cache: Dict[str, dict] = {}


def load_meta(category: Category, use_cache: bool = True) -> dict:
    """
    DEPRECATED: Use load_template_meta instead.
    For backward compatibility, loads the first template of the category.
    """
    if use_cache and category.id in _meta_cache:
        return _meta_cache[category.id]

    templates = template_store.get_by_category(category.id)
    if not templates:
        # Fallback to old behavior - try to load category JSON directly
        old_path = settings.meta_categories_root / f"{category.id}.json"
        if old_path.exists():
            with old_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if use_cache:
                _meta_cache[category.id] = data
            return data
        raise ValueError(f"No templates found for category: {category.id}")

    # Load first template's metadata
    data = load_template_meta(templates[0].id, use_cache=False)
    
    if use_cache:
        _meta_cache[category.id] = data

    return data


def clear_meta_cache(category_id: Optional[str] = None) -> None:
    """Clear metadata cache."""
    if category_id:
        _meta_cache.pop(category_id, None)
    else:
        _meta_cache.clear()
        _template_meta_cache.clear()


# Backward compatibility alias
_load_meta = load_meta


def list_entities(category_id: str, template_id: Optional[str] = None) -> List[Entity]:
    """
    List contract field entities.
    
    Args:
        category_id: Category ID (for backward compatibility)
        template_id: Template ID (preferred, if provided)
    
    Returns:
        List of Entity objects from contract_fields.
    """
    # If template_id provided, use it directly
    if template_id:
        data = load_template_meta(template_id)
    else:
        # Backward compatibility: use first template of category
        category = store.get(category_id)
        if not category:
            raise ValueError(f"Unknown category_id: {category_id}")
        data = load_meta(category)
    
    entities: List[Entity] = []

    # New format: contract_fields
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

    # Backward compatibility: entities array
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


def list_entities_for_template(template_id: str) -> List[Entity]:
    """List contract field entities for a specific template."""
    return list_entities(category_id="", template_id=template_id)


def list_templates(category_id: str) -> List[TemplateInfo]:
    """List available templates for a category."""
    templates = template_store.get_by_category(category_id)
    return [
        TemplateInfo(
            id=t.id,
            name=t.name,
            file=t.file,
        )
        for t in templates
        if not t.ai_only  # Hide AI-only templates from UI listing
    ]


def list_all_templates(include_ai_only: bool = False) -> List[Template]:
    """List all templates across all categories."""
    templates = list(template_store.templates.values())
    if not include_ai_only:
        templates = [t for t in templates if not t.ai_only]
    return templates


def list_party_fields(category_id: str, person_type: str, template_id: Optional[str] = None) -> List[PartyField]:
    """
    Повертає перелік полів сторони договору (name, address, тощо)
    для вказаного типу особи (individual / fop / company).
    
    Args:
        category_id: Category ID (for backward compatibility)
        person_type: Person type (individual/fop/company)
        template_id: Template ID (preferred, if provided)
    """
    if template_id:
        data = load_template_meta(template_id)
    else:
        category = store.get(category_id)
        if not category:
            raise ValueError(f"Unknown category_id: {category_id}")
        data = load_meta(category)
    
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


def get_party_schema(category_id: str, template_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Повертає опис ролей договору та поля для кожного типу особи.
    Використовується для побудови форм на фронтенді.
    
    Args:
        category_id: Category ID (for backward compatibility)
        template_id: Template ID (preferred, if provided)
    """
    if template_id:
        data = load_template_meta(template_id)
        effective_category_id = data.get("category_id", category_id)
    else:
        category = store.get(category_id)
        if not category:
            raise ValueError(f"Unknown category_id: {category_id}")
        data = load_meta(category)
        effective_category_id = category_id
    roles_raw = data.get("roles") or {}
    modules_raw = data.get("party_modules") or {}

    roles: List[Dict[str, Any]] = []
    main_role = None
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
        if main_role is None:
            main_role = role_id  # default to first role order

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
        "category_id": effective_category_id,
        "template_id": template_id,
        "main_role": main_role,
        "roles": roles,
        "person_types": person_types,
    }


def find_template_by_query(query: str) -> Optional[Template]:
    """
    Search for a template by keywords.
    Returns the best matching template.
    """
    query_norm = query.lower()
    query_terms = {t for t in query_norm.split() if t.strip()}
    best: Optional[Template] = None
    best_score = 0

    for template in template_store.templates.values():
        # Check keywords
        keywords = {k.lower() for k in (template.keywords or [])}
        kw_score = len(query_terms & keywords) * 2

        # Substring bonuses for keywords
        for kw in keywords:
            if kw and kw in query_norm:
                kw_score += 1

        # Bonus for partial matches (first 5 chars) to catch Ukrainian word forms
        for term in query_terms:
            for kw in keywords:
                stem = kw[:5]
                if stem and stem in term:
                    kw_score += 1

        # Also check template name
        name_lower = template.name.lower()
        for term in query_terms:
            if term in name_lower:
                kw_score += 1

        if kw_score > best_score:
            best_score = kw_score
            best = template

    return best


def find_category_by_query(query: str) -> Optional[Category]:
    """
    Search category by finding the best matching template's category.
    """
    template = find_template_by_query(query)
    if template:
        return store.get(template.category_id)
    
    # Fallback: return first category or custom
    return store.categories.get("custom")
