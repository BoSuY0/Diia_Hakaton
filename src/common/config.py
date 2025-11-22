from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]

# Автоматично підтягуємо змінні з .env у корені проєкту.
# ENV змінні з оточення мають пріоритет (override=False за замовчуванням).
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
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
        self.session_backend: str = os.getenv("SESSION_BACKEND", "redis").lower()
        try:
            self.session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))
        except ValueError:
            self.session_ttl_hours = 24
        self.valkey_use_glide: bool = os.getenv("USE_VALKEY_GLIDE", "false").lower() == "true"
        self.valkey_addresses: list[tuple[str, int]] = []
        addresses_env = os.getenv("VALKEY_ADDRESSES")
        if addresses_env:
            parts = [p.strip() for p in addresses_env.split(",") if p.strip()]
            for part in parts:
                if ":" in part:
                    host, port = part.split(":", 1)
                    try:
                        self.valkey_addresses.append((host, int(port)))
                    except ValueError:
                        continue
                else:
                    self.valkey_addresses.append((part, 6379))
        self.valkey_use_tls: bool = os.getenv("VALKEY_USE_TLS", "true").lower() == "true"

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

# Backward-compat: класові атрибути для старого коду, що звертався як Settings.documents_root тощо.
Settings.documents_root = BASE_DIR / "assets"
Settings.assets_dir = Settings.documents_root
Settings.meta_root = Settings.documents_root / "meta_data"
Settings.meta_categories_root = Settings.meta_root / "meta_data_categories_documents"
Settings.meta_users_root = Settings.meta_root / "meta_data_users"
Settings.meta_users_documents_root = Settings.meta_users_root / "documents"
Settings.sessions_root = Settings.meta_users_root / "sessions"
Settings.documents_files_root = Settings.documents_root / "documents_files"
Settings.filled_documents_root = Settings.documents_files_root / "filled_documents"
Settings.default_documents_root = Settings.documents_files_root / "default_documents_files"
Settings.users_documents_root = Settings.documents_files_root / "users_documents_files"
Settings.templates_root = Settings.default_documents_root
Settings.filled_root = Settings.sessions_root
Settings.output_root = Settings.filled_documents_root
Settings.llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
Settings.llm_model = (
    os.getenv("LLM_MODEL")
    or os.getenv("OPENAI_MODEL")
    or "gpt-4o-mini"
)
if Settings.llm_model == "gpt-5-mini-2025-08-7":
    Settings.llm_model = "gpt-5-mini-2025-08-07"
Settings.llm_base_url = os.getenv("LLM_BASE_URL")
Settings.chat_enabled = os.getenv("CHAT_ENABLED", "false").lower() == "true"
Settings.llm_wire_format = os.getenv("LLM_WIRE_FORMAT", "JSON")
Settings.openai_api_key = Settings.llm_api_key
Settings.openai_model = Settings.llm_model
_cors_origins_env = os.getenv("CORS_ORIGINS")
if _cors_origins_env:
    Settings.cors_origins = [
        origin.strip()
        for origin in _cors_origins_env.split(",")
        if origin.strip()
    ]
else:
    Settings.cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"
    ]
Settings.cors_allow_credentials = "*" not in Settings.cors_origins
Settings.redis_url = os.getenv("REDIS_URL")
Settings.session_backend = os.getenv("SESSION_BACKEND", "redis").lower()
try:
    Settings.session_ttl_hours = int(os.getenv("SESSION_TTL_HOURS", "24"))
except ValueError:
    Settings.session_ttl_hours = 24
Settings.valkey_use_glide = os.getenv("USE_VALKEY_GLIDE", "false").lower() == "true"
Settings.valkey_addresses = []
_addresses_env = os.getenv("VALKEY_ADDRESSES")
if _addresses_env:
    _parts = [p.strip() for p in _addresses_env.split(",") if p.strip()]
    for _part in _parts:
        if ":" in _part:
            _host, _port = _part.split(":", 1)
            try:
                Settings.valkey_addresses.append((_host, int(_port)))
            except ValueError:
                continue
        else:
            Settings.valkey_addresses.append((_part, 6379))
Settings.valkey_use_tls = os.getenv("VALKEY_USE_TLS", "true").lower() == "true"
