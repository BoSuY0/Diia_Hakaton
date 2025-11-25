from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[3]

# Автоматично підтягуємо змінні з .env у корені проєкту.
# ENV змінні з оточення мають пріоритет (override=False за замовчуванням).
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.env: str = os.getenv("ENV", "dev").lower()
        self.is_prod: bool = self.env in {"prod", "production"}
        self.is_dev: bool = not self.is_prod

        # Усі артефакти (meta + документи) лежать під assets/
        self.documents_root: Path = BASE_DIR / "assets"
        # Аліас для сумісності з кодом динамічних шаблонів
        self.assets_dir: Path = self.documents_root
        # Структура всередині /assets:
        # /meta_data/
        #   /meta_data_categories_documents/
        #   /meta_data_users/           # user-related metadata (documents + sessions)
        # /documents_files/
        #   /filled_documents/          # згенеровані договори (output)
        #   /default_documents_files/   # DOCX-шаблони за замовчуванням
        #   /users_documents_files/     # користувацькі файли/завантажені шаблони
        self.meta_root: Path = self.documents_root / "meta_data"
        self.meta_categories_root: Path = self.meta_root / "meta_data_categories_documents"
        # Нова структура user-meta: meta_data_users/{documents,sessions}
        self.meta_users_root: Path = self.meta_root / "meta_data_users"
        self.meta_users_documents_root: Path = self.meta_users_root / "documents"

        self.documents_files_root: Path = self.documents_root / "documents_files"
        self.filled_documents_root: Path = self.documents_files_root / "filled_documents"
        self.default_documents_root: Path = self.documents_files_root / "default_documents_files"

        # Сесії користувачів (стан заповнення полів) у meta_data_users/sessions
        self.sessions_root: Path = self.meta_users_root / "sessions"

        # Зворотна сумісність зі старими атрибутами
        self.templates_root: Path = self.default_documents_root
        self.filled_root: Path = self.sessions_root
        self.output_root: Path = self.filled_documents_root

        # Сторедж сесій
        self.redis_url: str | None = os.getenv("REDIS_URL")
        _session_backend_env = os.getenv("SESSION_BACKEND")
        self.session_backend: str = (_session_backend_env or "redis").lower()
        try:
            self.session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))
        except ValueError:
            self.session_ttl_hours = 24
        # Детальна політика TTL
        try:
            self.draft_ttl_hours: int = int(os.getenv("DRAFT_TTL_HOURS", "24"))
        except ValueError:
            self.draft_ttl_hours = 24
        try:
            self.filled_ttl_hours: int = int(os.getenv("FILLED_TTL_HOURS", str(24 * 7)))
        except ValueError:
            self.filled_ttl_hours = 24 * 7
        try:
            self.signed_ttl_days: int = int(os.getenv("SIGNED_TTL_DAYS", "365"))
        except ValueError:
            self.signed_ttl_days = 365
        self.valkey_use_glide: bool = False
        self.valkey_addresses: list[tuple[str, int]] = []
        self.valkey_use_tls: bool = False

        # LLM (загальні змінні середовища, не прив'язані до провайдера)
        # Основні:
        #   LLM_API_KEY   — ключ до активної модельки (Anthropic / OpenAI / інші через LiteLLM)
        #   LLM_MODEL     — ідентифікатор моделі, наприклад: "anthropic/claude-4.5-haiku"
        #   LLM_BASE_URL  — опційний базовий URL до OpenAI-сумісного проксі / API
        self.llm_api_key: str | None = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.llm_model: str = (
            os.getenv("LLM_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4o-mini"
        )

        # Sanitize model name if it's a known hallucination/typo
        if self.llm_model == "gpt-5-mini-2025-08-7":
            self.llm_model = "gpt-5-mini-2025-08-07"

        self.llm_base_url: str | None = os.getenv("LLM_BASE_URL")
        self.chat_enabled: bool = os.getenv("CHAT_ENABLED", "false").lower() == "true"
        # Формат обміну між туллами та LLM усередині tool-loop:
        # "JSON" (за замовчуванням) або "VSC" (value-separated columns).
        self.llm_wire_format: str = os.getenv("LLM_WIRE_FORMAT", "JSON")

        # Зворотна сумісність з попередніми назвами (якщо десь ще використовуються):
        self.openai_api_key: str | None = self.llm_api_key
        self.openai_model: str = self.llm_model

        # Контракти (БД)
        self.contracts_db_url: str | None = os.getenv("CONTRACTS_DB_URL")
        # Опційний файловий fallback для контрактів (для міграції/бекупів). За замовчуванням вимкнено.
        self.contracts_fs_fallback: bool = os.getenv("CONTRACTS_FS_FALLBACK", "false").lower() == "true"

        # Auth
        self.auth_mode: str = os.getenv("AUTH_MODE", "auto").lower()
        self.auth_jwt_secret: str | None = os.getenv("AUTH_JWT_SECRET")
        self.auth_jwt_audience: str | None = os.getenv("AUTH_JWT_AUDIENCE")
        self.auth_jwt_algorithm: str = os.getenv("AUTH_JWT_ALGO", "HS256")
        self.auth_jwt_issuer: str | None = os.getenv("AUTH_JWT_ISSUER")
        # Префікс для внутрішнього user_id (наприклад, diia:<sub>)
        self.auth_user_prefix: str = os.getenv("AUTH_USER_PREFIX", "diia:")

        # CORS (origins для фронтенду)
        _cors_origins_env = os.getenv("CORS_ORIGINS")
        if _cors_origins_env:
            self.cors_origins: list[str] = [
                origin.strip()
                for origin in _cors_origins_env.split(",")
                if origin.strip()
            ]
        else:
            self.cors_origins: list[str] = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "*"
            ]

        # У прод-оточенні не використовуємо креденшли з wildcard.
        # Якщо дозволено "*", вимикаємо allow_credentials.
        self.cors_allow_credentials: bool = "*" not in self.cors_origins


settings = Settings()
