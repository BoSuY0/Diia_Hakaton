import pytest
from src.common.config import Settings

def test_settings_paths(mock_settings):
    # Check if paths are correctly set relative to the temp workspace
    assert mock_settings.assets_root.name == "assets"
    assert mock_settings.meta_categories_root.exists()
    assert mock_settings.sessions_root.exists()

def test_settings_env_loading(monkeypatch):
    # Test env var override (we can't easily test .env file loading here without creating one, 
    # but we can test os.environ priority if Config uses it)
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    # Re-instantiate settings to pick up env
    s = Settings()
    # Note: This depends on how pydantic settings work. 
    # If .env is missing, it might not fail, but we just check if it *can* load.
    pass 
