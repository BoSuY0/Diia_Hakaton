"""Tests for environment variable overrides in settings."""
from backend.infra.config.settings import Settings


def test_env_overrides_base_dir(monkeypatch, tmp_path):  # pylint: disable=unused-argument
    """Test environment overrides base dir."""
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    # Ensure OPENAI_API_KEY absent so we pick LLM_API_KEY
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    s = Settings()
    assert s.llm_model == "env-model"
    assert s.llm_api_key == "env-key"


def test_llm_model_sanitization(monkeypatch):
    """Test LLM model sanitization."""
    monkeypatch.setenv("LLM_MODEL", "pt-4.1-mini")
    s = Settings()
    assert s.llm_model == "pt-4.1-mini"


def test_cors_origins_default(monkeypatch):
    """Test CORS origins default."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    s = Settings()
    assert "http://localhost:5173" in s.cors_origins
    assert "http://localhost:3000" in s.cors_origins
    assert s.cors_allow_credentials is True
