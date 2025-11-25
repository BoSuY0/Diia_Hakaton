"""Pytest configuration and fixtures for test suite."""
# pylint: disable=redefined-outer-name,protected-access
import asyncio
import inspect
import json
import sys
from pathlib import Path

import pytest

# Додаємо корінь проєкту в sys.path, щоб імпорти backend.* працювали без інсталяцїї пакету
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(PROJECT_ROOT)
# Щоб backend.* бралося з кореня, а не з tests/src, ставимо корінь на початок sys.path
if ROOT_STR in sys.path:
    sys.path.remove(ROOT_STR)
sys.path.insert(0, ROOT_STR)

try:
    from backend.infra.config.settings import Settings  # noqa: F401  # pylint: disable=unused-import
except ModuleNotFoundError:
    # Додаткова спроба з явним шляхом до кореня
    if ROOT_STR in sys.path:
        sys.path.remove(ROOT_STR)
    sys.path.insert(0, ROOT_STR)
    from backend.infra.config.settings import Settings  # pylint: disable=unused-import

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
    # pylint: disable=import-outside-toplevel
    from backend.infra.config.settings import settings
    from backend.infra.persistence import store_memory, store
    from backend.infra.persistence import contracts_repository
    from backend.domain.categories import index as category_index

    # Store original values to restore after test
    original_values = {}
    keys_to_update = [
        "project_root", "assets_root", "documents_root", "meta_root",
        "meta_categories_root", "meta_users_root", "meta_users_documents_root",
        "sessions_root", "documents_files_root", "filled_documents_root",
        "default_documents_root", "users_documents_root",
        "session_backend", "session_ttl_hours", "redis_url",
        "draft_ttl_hours", "filled_ttl_hours", "signed_ttl_days",
        "contracts_db_url",
        "auth_mode", "auth_jwt_secret", "auth_jwt_audience", "auth_jwt_algorithm",
        "env", "is_dev", "is_prod",
    ]

    for key in keys_to_update:
        if hasattr(settings, key):
            original_values[key] = getattr(settings, key)

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
    settings.session_backend = "memory"
    settings.session_ttl_hours = 24
    settings.draft_ttl_hours = 24
    settings.filled_ttl_hours = 24 * 7
    settings.signed_ttl_days = 365
    settings.redis_url = None
    settings.auth_mode = "auto"
    settings.auth_jwt_secret = None
    settings.auth_jwt_audience = None
    settings.auth_jwt_algorithm = "HS256"
    settings.env = "test"
    settings.is_dev = True
    settings.is_prod = False
    store._redis_disabled = False
    store_memory._reset_for_tests()
    contracts_repository._contracts_repo = None
    orig_categories_path = category_index._CATEGORIES_PATH
    category_index._CATEGORIES_PATH = None
    category_index.store.clear()

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
    category_index._CATEGORIES_PATH = orig_categories_path
    category_index.store.clear()

@pytest.fixture
def mock_categories_data(mock_settings, monkeypatch):  # noqa: ARG001
    """Create mock category data for testing."""
    from backend.domain.categories.index import store  # pylint: disable=import-outside-toplevel

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
    idx_data = {"categories": [{"id": cat_id, "label": "Test Cat", "keywords": ["test"]}]}
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(idx_data, f)

    # Patch the module-level variable _CATEGORIES_PATH because it's evaluated at import time
    monkeypatch.setattr("backend.domain.categories.index._CATEGORIES_PATH", index_file)

    # Force reload store
    store.clear()
    store.load()

    return cat_id


def create_category_meta(
    settings,
    cat_id: str,
    *,
    templates=None,
    roles=None,
    party_modules=None,
    contract_fields=None,
    keywords=None,
):
    """Create category metadata files for testing.

    This is a shared helper to reduce code duplication in tests.

    Args:
        settings: The settings object with paths.
        cat_id: Category ID.
        templates: List of template dicts, defaults to single template.
        roles: Roles dict, defaults to lessor/lessee with individual type.
        party_modules: Party modules dict, defaults to individual with name field.
        contract_fields: Contract fields list, defaults to single cf1 field.
        keywords: Keywords for index, defaults to [cat_id].
    """
    if templates is None:
        templates = [{"id": "t1", "name": "T1", "file": "f1.docx"}]
    if roles is None:
        roles = {"lessor": {"label": "Lessor", "allowed_person_types": ["individual"]}}
    if party_modules is None:
        party_modules = {
            "individual": {
                "label": "Indiv",
                "fields": [{"field": "name", "label": "Name", "required": True}],
            }
        }
    if contract_fields is None:
        contract_fields = [{"field": "cf1", "label": "CF1", "required": True}]
    if keywords is None:
        keywords = [cat_id]

    meta = {
        "category_id": cat_id,
        "templates": templates,
        "roles": roles,
        "party_modules": party_modules,
        "contract_fields": contract_fields,
    }
    meta_path = settings.meta_categories_root / f"{cat_id}.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    # Update or create index
    index_path = settings.meta_categories_root / "categories_index.json"
    if index_path.exists():
        idx_data = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        idx_data = {"categories": []}

    # Add category if not exists
    if all(c["id"] != cat_id for c in idx_data.get("categories", [])):
        idx_data["categories"].append({
            "id": cat_id,
            "label": cat_id.replace("_", " ").title(),
            "keywords": keywords,
        })
    index_path.write_text(json.dumps(idx_data), encoding="utf-8")

    return meta_path, index_path


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """
    Run all sync tests inside an asyncio event loop so they execute in async mode
    without manual rewrite of each test. Coroutine tests are left to pytest-asyncio.
    """
    # Let pytest-asyncio/anyio handle native async tests or tests marked with asyncio
    if inspect.iscoroutinefunction(pyfuncitem.obj) or "asyncio" in pyfuncitem.keywords:
        return None  # let pytest-asyncio handle native async tests

    testargs = {
        arg: pyfuncitem.funcargs[arg]
        for arg in pyfuncitem._fixtureinfo.argnames
    }

    async def _run():
        pyfuncitem.obj(**testargs)

    asyncio.run(_run())
    return True
