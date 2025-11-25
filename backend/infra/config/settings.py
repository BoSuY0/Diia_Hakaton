"""Application settings loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[3]

# Автоматично підтягуємо змінні з .env у корені проєкту.
# ENV змінні з оточення мають пріоритет (override=False за замовчуванням).
load_dotenv(BASE_DIR / ".env")


class Settings:
    """
    Application configuration container with environment-based settings.

    Loads configuration from environment variables with sensible defaults.
    """

    def __init__(self) -> None:
        self._init_env()
        self._init_paths()
        self._init_session_config()
        self._init_llm_config()
        self._init_auth_config()
        self._init_cors_config()

    def _init_env(self) -> None:
        """Initialize environment settings."""
        self.env: str = os.getenv("ENV", "dev").lower()
        self.is_prod: bool = self.env in {"prod", "production"}
        self.is_dev: bool = not self.is_prod

    def _init_paths(self) -> None:
        """Initialize file system paths."""
        self.documents_root: Path = BASE_DIR / "assets"
        self.assets_dir: Path = self.documents_root
        self.meta_root: Path = self.documents_root / "meta_data"
        self.meta_categories_root: Path = self.meta_root / "meta_data_categories_documents"
        self.meta_users_root: Path = self.meta_root / "meta_data_users"
        self.meta_users_documents_root: Path = self.meta_users_root / "documents"
        self.documents_files_root: Path = self.documents_root / "documents_files"
        self.filled_documents_root: Path = self.documents_files_root / "filled_documents"
        self.default_documents_root: Path = (
            self.documents_files_root / "default_documents_files"
        )
        self.sessions_root: Path = self.meta_users_root / "sessions"
        self.templates_root: Path = self.default_documents_root
        self.filled_root: Path = self.sessions_root
        self.output_root: Path = self.filled_documents_root

    def _init_session_config(self) -> None:
        """Initialize session storage configuration."""
        self.redis_url: str | None = os.getenv("REDIS_URL")
        self.session_backend: str = (os.getenv("SESSION_BACKEND") or "redis").lower()
        self.session_ttl_hours: int = self._get_int_env("SESSION_TTL_HOURS", 24)
        self.draft_ttl_hours: int = self._get_int_env("DRAFT_TTL_HOURS", 24)
        self.filled_ttl_hours: int = self._get_int_env("FILLED_TTL_HOURS", 24 * 7)
        self.signed_ttl_days: int = self._get_int_env("SIGNED_TTL_DAYS", 365)
        self.valkey_use_glide: bool = False
        self.valkey_addresses: list[tuple[str, int]] = []
        self.valkey_use_tls: bool = False

    def _init_llm_config(self) -> None:
        """Initialize LLM configuration."""
        self.llm_api_key: str | None = (
            os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        )
        self.llm_model: str = (
            os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        )
        self.llm_base_url: str | None = os.getenv("LLM_BASE_URL")
        self.chat_enabled: bool = os.getenv("CHAT_ENABLED", "false").lower() == "true"
        self.llm_wire_format: str = os.getenv("LLM_WIRE_FORMAT", "JSON")
        self.openai_api_key: str | None = self.llm_api_key
        self.openai_model: str = self.llm_model
        self.contracts_db_url: str | None = os.getenv("CONTRACTS_DB_URL")
        self.contracts_fs_fallback: bool = (
            os.getenv("CONTRACTS_FS_FALLBACK", "false").lower() == "true"
        )

    def _init_auth_config(self) -> None:
        """Initialize authentication configuration."""
        self.auth_mode: str = os.getenv("AUTH_MODE", "auto").lower()
        self.auth_jwt_secret: str | None = os.getenv("AUTH_JWT_SECRET")
        self.auth_jwt_audience: str | None = os.getenv("AUTH_JWT_AUDIENCE")
        self.auth_jwt_algorithm: str = os.getenv("AUTH_JWT_ALGO", "HS256")
        self.auth_jwt_issuer: str | None = os.getenv("AUTH_JWT_ISSUER")
        self.auth_user_prefix: str = os.getenv("AUTH_USER_PREFIX", "diia:")

    def _init_cors_config(self) -> None:
        """Initialize CORS configuration."""
        cors_env = os.getenv("CORS_ORIGINS")
        if cors_env:
            self.cors_origins: list[str] = [
                o.strip() for o in cors_env.split(",") if o.strip()
            ]
        else:
            # Security: No wildcard "*" in defaults - only localhost for dev
            self.cors_origins = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
        # Warn if wildcard is used with credentials (security risk)
        if "*" in self.cors_origins:
            import warnings
            warnings.warn(
                "CORS wildcard '*' is insecure. Set specific CORS_ORIGINS in production.",
                stacklevel=2,
            )
        self.cors_allow_credentials: bool = "*" not in self.cors_origins

    @staticmethod
    def _get_int_env(key: str, default: int) -> int:
        """Get integer from environment variable with default."""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.is_prod

    def uses_redis(self) -> bool:
        """Check if Redis is configured as session backend."""
        return self.session_backend == "redis" and bool(self.redis_url)


settings = Settings()
