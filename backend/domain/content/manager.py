import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

logger = get_logger(__name__)


class ContentManager:
    """
    Менеджер для програмного управління контентом (категорії, шаблони, поля).
    Дозволяє безпечно додавати нові записи в JSON-файли конфігурації.
    """

    def __init__(self) -> None:
        self.categories_index_path = settings.meta_categories_root / "categories_index.json"
        self._ensure_root_exists()

    def _ensure_root_exists(self) -> None:
        if not settings.meta_categories_root.exists():
            logger.info("Creating categories root: %s", settings.meta_categories_root)
            settings.meta_categories_root.mkdir(parents=True, exist_ok=True)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_json(self, path: Path, data: Dict[str, Any]) -> None:
        # Створюємо резервну копію перед записом
        if path.exists():
            backup_path = path.with_suffix(".json.bak")
            shutil.copy2(path, backup_path)
        
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_category(self, category_id: str, label: str) -> None:
        """
        Створює нову категорію:
        1. Додає запис в categories_index.json
        2. Створює базовий файл метаданих категорії {category_id}.json
        """
        # 1. Оновлюємо індекс
        index_data = self._load_json(self.categories_index_path)
        categories = index_data.get("categories", [])

        # Перевірка на дублікати
        for cat in categories:
            if cat["id"] == category_id:
                logger.warning("Category '%s' already exists in index.", category_id)
                return

        new_entry = {
            "id": category_id,
            "label": label,
            "meta_filename": f"{category_id}.json"
        }
        categories.append(new_entry)
        index_data["categories"] = categories
        self._save_json(self.categories_index_path, index_data)
        logger.info("Added category '%s' to index.", category_id)

        # 2. Створюємо файл метаданих
        meta_path = settings.meta_categories_root / f"{category_id}.json"
        if not meta_path.exists():
            initial_meta = {
                "category_id": category_id,
                "templates": [],
                "roles": {
                    "lessor": {
                        "label": "Сторона 1 (напр. Виконавець)",
                        "allowed_person_types": ["individual", "fop", "company"]
                    },
                    "lessee": {
                        "label": "Сторона 2 (напр. Замовник)",
                        "allowed_person_types": ["individual", "fop", "company"]
                    }
                },
                "party_modules": {
                    "individual": {
                        "label": "Фізична особа",
                        "fields": [
                            {"field": "name", "label": "ПІБ", "required": True},
                            {"field": "address", "label": "Адреса", "required": True}
                        ]
                    },
                    "fop": {
                        "label": "ФОП",
                        "fields": [
                            {"field": "name", "label": "ПІБ ФОП", "required": True},
                            {"field": "id_code", "label": "РНОКПП", "required": True}
                        ]
                    },
                    "company": {
                        "label": "Юридична особа",
                        "fields": [
                            {"field": "name", "label": "Назва", "required": True},
                            {"field": "id_code", "label": "ЄДРПОУ", "required": True}
                        ]
                    }
                },
                "contract_fields": []
            }
            self._save_json(meta_path, initial_meta)
            logger.info("Created metadata file for category '%s'.", category_id)

    def add_template(
        self, 
        category_id: str, 
        template_id: str, 
        name: str, 
        filename: Optional[str] = None
    ) -> None:
        """Додає шаблон до існуючої категорії."""
        meta_path = settings.meta_categories_root / f"{category_id}.json"
        if not meta_path.exists():
            raise ValueError(f"Category file not found: {meta_path}")

        data = self._load_json(meta_path)
        templates = data.get("templates", [])

        # Перевірка на дублікати
        for tmpl in templates:
            if tmpl["id"] == template_id:
                logger.warning("Template '%s' already exists in category '%s'.", template_id, category_id)
                return

        new_template = {
            "id": template_id,
            "name": name,
            "file": filename or f"{template_id}.docx"
        }
        templates.append(new_template)
        data["templates"] = templates
        self._save_json(meta_path, data)
        logger.info("Added template '%s' to category '%s'.", template_id, category_id)

    def add_field(
        self, 
        category_id: str, 
        field_name: str, 
        label: str, 
        required: bool = False
    ) -> None:
        """Додає поле договору (contract_fields) до категорії."""
        meta_path = settings.meta_categories_root / f"{category_id}.json"
        if not meta_path.exists():
            raise ValueError(f"Category file not found: {meta_path}")

        data = self._load_json(meta_path)
        fields = data.get("contract_fields", [])

        # Перевірка на дублікати
        for f in fields:
            if f["field"] == field_name:
                logger.warning("Field '%s' already exists in category '%s'.", field_name, category_id)
                return

        new_field = {
            "field": field_name,
            "label": label,
            "required": required
        }
        fields.append(new_field)
        data["contract_fields"] = fields
        self._save_json(meta_path, data)
        logger.info("Added field '%s' to category '%s'.", field_name, category_id)
