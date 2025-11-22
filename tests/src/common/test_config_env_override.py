import os
from pathlib import Path

from src.common.config import Settings


def test_env_overrides_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    # Ensure OPENAI_API_KEY absent so we pick LLM_API_KEY
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    s = Settings()
    assert s.llm_model == "env-model"
    assert s.llm_api_key == "env-key"


def test_llm_model_sanitization(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-5-mini-2025-08-7")
    s = Settings()
    assert s.llm_model == "gpt-5-mini-2025-08-07"


def test_cors_origins_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    s = Settings()
    assert "*" in s.cors_origins
