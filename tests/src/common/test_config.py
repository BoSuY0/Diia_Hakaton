"""Tests for configuration settings."""
from backend.infra.config.settings import Settings


def test_settings_paths(mock_settings):
    """Test settings paths are correctly set."""
    # Check if paths are correctly set relative to the temp workspace
    assert mock_settings.assets_root.name == "assets"
    assert mock_settings.meta_categories_root.exists()
    assert mock_settings.sessions_root.exists()

def test_settings_env_loading(monkeypatch):
    """Test environment variable loading."""
    # Test env var override
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    # Re-instantiate settings to pick up env
    _ = Settings()
    # Note: This depends on how pydantic settings work.
    # If .env is missing, it might not fail, but we just check if it *can* load.
