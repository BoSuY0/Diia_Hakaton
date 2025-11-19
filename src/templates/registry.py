from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from src.categories.index import list_entities, list_templates, store as category_store
from src.common.config import settings
from src.common.errors import MetaNotFoundError


@dataclass
class TemplateMeta:
    """
    Уніфікований опис шаблону договору.

    Побудований поверх нової структури meta-файлів у assets/meta_data/meta_data_categories_documents.
    """

    template_id: str
    name: str
    description: str
    fields: List[dict]
    file_template_path: Path
    file_output_format: str


class TemplateRegistry:
    """
    Реєстр шаблонів, який тепер збирає мета-інформацію з категорій у assets/...,
    а не з legacy meta_root/default_docs.

    Для кожного template_id шукається категорія, якій він належить, та
    використовується перелік entities цієї категорії.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, TemplateMeta] = {}

    def _ensure_index(self) -> None:
        if self._cache:
            return

        for category in category_store.categories.values():
            entities = list_entities(category.id)
            templates = list_templates(category.id)

            fields: List[dict] = []
            for e in entities:
                fields.append(
                    {
                        "id": e.field,
                        "label": e.label,
                        "type": e.type,
                        "required": e.required,
                    }
                )

            for t in templates:
                # Основний шлях: default_documents_files/<category_id>/<file>
                file_template_path = (
                    settings.default_documents_root
                    / category.id
                    / t.file
                )
                # Фолбек: default_documents_files/<file>, якщо піддиректорії немає
                if not file_template_path.exists():
                    fallback = settings.default_documents_root / t.file
                    if fallback.exists():
                        file_template_path = fallback
                meta = TemplateMeta(
                    template_id=t.id,
                    name=t.name,
                    description=category.label,
                    fields=fields,
                    file_template_path=file_template_path,
                    file_output_format="docx",
                )
                self._cache[t.id] = meta

    def list_templates(self) -> List[str]:
        """
        Повертає список відомих template_id з актуальної структури assets/... .
        """
        self._ensure_index()
        return sorted(self._cache.keys())

    def load(self, template_id: str) -> TemplateMeta:
        self._ensure_index()
        if template_id not in self._cache:
            raise MetaNotFoundError(f"Meta for template '{template_id}' not found")
        return self._cache[template_id]


registry = TemplateRegistry()
