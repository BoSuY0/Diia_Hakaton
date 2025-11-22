import sys
from pathlib import Path
import shutil

import pytest

# Додаємо корінь проєкту в sys.path, щоб імпорти src.* працювали без інсталяції пакету
PROJECT_ROOT = Path(__file__).resolve().parents[1]
root_str = str(PROJECT_ROOT)
# Щоб src.* бралося з кореня, а не з tests/src, ставимо корінь на початок sys.path
if root_str in sys.path:
    sys.path.remove(root_str)
sys.path.insert(0, root_str)

try:
    from src.common.config import Settings
except ModuleNotFoundError:
    # Додаткова спроба з явним шляхом до кореня
    if root_str in sys.path:
        sys.path.remove(root_str)
    sys.path.insert(0, root_str)
    from src.common.config import Settings

@pytest.fixture
def temp_workspace(tmp_path):
    """Creates a temporary workspace with necessary subdirectories."""
    # Create structure
    (tmp_path / "assets" / "meta_data" / "meta_data_categories_documents").mkdir(parents=True)
    (tmp_path / "assets" / "documents_files" / "default_documents_files").mkdir(parents=True)
    (tmp_path / "assets" / "user_documents").mkdir(parents=True)
    (tmp_path / "assets" / "session_answers").mkdir(parents=True)
    return tmp_path

@pytest.fixture
def mock_settings(temp_workspace):
    """Overrides settings to use the temporary workspace."""
    from src.common.config import settings
    
    # Store original values to restore after test
    original_values = {}
    keys_to_update = [
        "project_root", "assets_root", "documents_root", "meta_root",
        "meta_categories_root", "meta_users_root", "meta_users_documents_root",
        "sessions_root", "documents_files_root", "filled_documents_root",
        "default_documents_root", "users_documents_root"
    ]
    
    for key in keys_to_update:
        if hasattr(settings, key):
            original_values[key] = getattr(settings, key)
    
    # Manually overwrite paths
    # Manually overwrite paths
    settings.project_root = temp_workspace
    settings.assets_root = temp_workspace / "assets"
    
    # Re-construct derived paths based on the new assets_root
    settings.documents_root = settings.assets_root
    settings.meta_root = settings.documents_root / "meta_data"
    settings.meta_categories_root = settings.meta_root / "meta_data_categories_documents"
    settings.meta_users_root = settings.meta_root / "meta_data_users"
    settings.meta_users_documents_root = settings.meta_users_root / "documents"
    settings.sessions_root = settings.meta_users_root / "sessions"
    
    settings.documents_files_root = settings.documents_root / "documents_files"
    settings.filled_documents_root = settings.documents_files_root / "filled_documents"
    settings.default_documents_root = settings.documents_files_root / "default_documents_files"
    settings.users_documents_root = settings.documents_files_root / "users_documents_files"

    # Ensure directories exist
    settings.meta_categories_root.mkdir(parents=True, exist_ok=True)
    settings.meta_users_documents_root.mkdir(parents=True, exist_ok=True)
    settings.sessions_root.mkdir(parents=True, exist_ok=True)
    settings.default_documents_root.mkdir(parents=True, exist_ok=True)
    settings.users_documents_root.mkdir(parents=True, exist_ok=True)
    settings.filled_documents_root.mkdir(parents=True, exist_ok=True)
    
    yield settings
    
    # Restore original values
    for key, value in original_values.items():
        setattr(settings, key, value)

@pytest.fixture
def mock_categories_data(mock_settings, monkeypatch):
    import json
    from src.categories.index import store
    
    # Create a dummy category file
    cat_id = "test_cat"
    cat_file = mock_settings.meta_categories_root / f"{cat_id}.json"
    data = {
        "category_id": cat_id,
        "templates": [{"id": "t1", "name": "T1", "file": "f1.docx"}],
        "roles": {
            "lessor": {"label": "Lessor", "allowed_person_types": ["individual", "company"]},
            "lessee": {"label": "Lessee", "allowed_person_types": ["individual", "company"]}
        },
        "party_modules": {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}]
            },
            "company": {
                "label": "Comp",
                "fields": [{"field": "name", "label": "Name", "required": True}]
            }
        },
        "contract_fields": [
            {"field": "cf1", "label": "CF1", "required": True}
        ]
    }
    with cat_file.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    
    # Update index
    index_file = mock_settings.meta_categories_root / "categories_index.json"
    idx_data = {"categories": [{"id": cat_id, "label": "Test Cat"}]}
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(idx_data, f)

    # Patch the module-level variable _CATEGORIES_PATH because it's evaluated at import time
    monkeypatch.setattr("src.categories.index._CATEGORIES_PATH", index_file)
        
    # Force reload store
    store._categories = {} # Clear internal cache
    store.load() # Reload index
    
    return cat_id
