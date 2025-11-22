import os
from pathlib import Path

from src.common.config import settings, Settings


def test_settings_paths_default(tmp_path, monkeypatch):
    # Override BASE_DIR indirectly
    monkeypatch.setattr("src.common.config.BASE_DIR", tmp_path)
    # Reload settings class
    s = Settings()
    assert s.documents_root == tmp_path / "assets"
    assert s.meta_categories_root == s.documents_root / "meta_data" / "meta_data_categories_documents"
    assert s.output_root == s.filled_documents_root


def test_settings_llm_defaults(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "k1")
    s = Settings()
    assert s.llm_api_key == "k1"
    assert s.llm_model  # has some default or env


def test_settings_cors_origins_parse(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://example.com, http://foo")
    s = Settings()
    assert "http://example.com" in s.cors_origins
    assert "http://foo" in s.cors_origins
    assert s.cors_allow_credentials is True
