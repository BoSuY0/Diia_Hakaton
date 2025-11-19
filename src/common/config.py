from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]

# Автоматично підтягуємо змінні з .env у корені проєкту.
# ENV змінні з оточення мають пріоритет (override=False за замовчуванням).
load_dotenv(BASE_DIR / ".env")


class Settings:
    # Усі артефакти (meta + документи) лежать під assets/
    documents_root: Path = BASE_DIR / "assets"
    # Структура всередині /assets:
    # /meta_data/
    #   /meta_data_categories_documents/
    #   /meta_data_users/           # user-related metadata (documents + sessions)
    # /documents_files/
    #   /filled_documents/          # згенеровані договори (output)
    #   /default_documents_files/   # DOCX-шаблони за замовчуванням
    #   /users_documents_files/     # користувацькі файли/завантажені шаблони
    meta_root: Path = documents_root / "meta_data"
    meta_categories_root: Path = meta_root / "meta_data_categories_documents"
    # Нова структура user-meta: meta_data_users/{documents,sessions}
    meta_users_root: Path = meta_root / "meta_data_users"
    meta_users_documents_root: Path = meta_users_root / "documents"

    documents_files_root: Path = documents_root / "documents_files"
    filled_documents_root: Path = documents_files_root / "filled_documents"
    default_documents_root: Path = documents_files_root / "default_documents_files"
    users_documents_root: Path = documents_files_root / "users_documents_files"

    # Сесії користувачів (стан заповнення полів) у meta_data_users/sessions
    sessions_root: Path = meta_users_root / "sessions"

    # Зворотна сумісність зі старими атрибутами
    templates_root: Path = default_documents_root
    filled_root: Path = sessions_root
    output_root: Path = filled_documents_root

    # LLM (загальні змінні середовища, не прив'язані до провайдера)
    # Основні:
    #   LLM_API_KEY   — ключ до активної модельки (Anthropic / OpenAI / інші через LiteLLM)
    #   LLM_MODEL     — ідентифікатор моделі, наприклад: "anthropic/claude-4.5-haiku"
    #   LLM_BASE_URL  — опційний базовий URL до OpenAI-сумісного проксі / API
    llm_api_key: str | None = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_model: str = (
        os.getenv("LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "anthropic/claude-4.5-haiku"
    )
    llm_base_url: str | None = os.getenv("LLM_BASE_URL")
    chat_enabled: bool = os.getenv("CHAT_ENABLED", "false").lower() == "true"
    # Формат обміну між туллами та LLM усередині tool-loop:
    # "JSON" (за замовчуванням) або "VSC" (value-separated columns).
    llm_wire_format: str = os.getenv("LLM_WIRE_FORMAT", "JSON")

    # Зворотна сумісність з попередніми назвами (якщо десь ще використовуються):
    openai_api_key: str | None = llm_api_key
    openai_model: str = llm_model

    # CORS (origins для фронтенду)
    _cors_origins_env = os.getenv("CORS_ORIGINS")
    if _cors_origins_env:
        cors_origins: list[str] = [
            origin.strip()
            for origin in _cors_origins_env.split(",")
            if origin.strip()
        ]
    else:
        cors_origins: list[str] = ["*"]


settings = Settings()
