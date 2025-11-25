"""Tests for directory creation utilities."""
from backend.infra.config.settings import settings
from backend.infra.storage.fs import ensure_directories


def test_ensure_directories_creates_paths(mock_settings):
    """Test ensure_directories creates all required paths."""
    # Remove dirs to simulate fresh state
    for path in [
        mock_settings.meta_categories_root,
        mock_settings.meta_users_root,
        mock_settings.meta_users_documents_root,
        mock_settings.sessions_root,
        mock_settings.documents_files_root,
        mock_settings.default_documents_root,
        mock_settings.filled_documents_root,
    ]:
        if path.exists():
            # safety: only remove empty dirs in temp workspace
            try:
                path.rmdir()
            except OSError:
                pass

    ensure_directories()

    assert settings.meta_categories_root.exists()
    assert settings.meta_users_documents_root.exists()
    assert settings.sessions_root.exists()
    assert settings.default_documents_root.exists()
