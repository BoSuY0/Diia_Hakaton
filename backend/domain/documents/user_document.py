"""User document building and persistence utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from backend.domain.categories.index import (
    list_entities,
    list_party_fields,
    load_meta,
    store as category_store,
)
from backend.domain.services.session import get_effective_person_type
from backend.infra.config.settings import settings
from backend.domain.sessions.models import Session, SessionState
from backend.infra.storage.fs import read_json, write_json, read_json_async, write_json_async
from backend.infra.persistence.contracts_repository import get_contracts_repo
from backend.shared.async_utils import run_sync
from backend.shared.logging import get_logger

logger = get_logger(__name__)


def build_user_document(session: Session) -> Dict[str, Any]:
    """
    Побудова user-document JSON у форматі example_user_document.json
    на основі поточної Session.
    """
    document_id = (
        f"{session.template_id}_{session.session_id}"
        if session.template_id
        else session.session_id
    )
    if session.state == SessionState.BUILT:
        status = "built"
    else:
        status = "draft"

    category_id = session.category_id
    template_id = session.template_id

    # Поля договору (contract_fields)
    contract_fields: Dict[str, Any] = {}
    if category_id:
        for e in list_entities(category_id):
            entry = (session.all_data or {}).get(e.field) or {}
            value = entry.get("current")
            contract_fields[e.field] = value

    # Поля сторін (parties)
    parties: Dict[str, Any] = {}

    # Determine roles dynamically from session or category metadata
    target_roles = set(session.party_types.keys()) if session.party_types else set()
    if not target_roles and category_id:
        # Get roles from category metadata
        category = category_store.get(category_id)
        if category:
            meta = load_meta(category)
            target_roles = set((meta.get("roles") or {}).keys())

    for role_key in target_roles:
        # Logic: If we have data for this role in session.all_data, use it.

        # Determine person_type for this role
        person_type = (session.party_types or {}).get(role_key)

        # Fallback for legacy single-user sessions
        if not person_type and session.role == role_key:
            person_type = session.person_type

        # If still unknown, use centralized fallback logic
        if not person_type:
            person_type = get_effective_person_type(
                session, role_key, apply_fallback=True
            )

        data: Dict[str, Any] = {}
        has_data = False

        if category_id and person_type:
            for f in list_party_fields(category_id, person_type):
                # Try prefixed key first (created by upsert_field)
                prefixed_key = f"{role_key}.{f.field}"
                val = (session.all_data or {}).get(prefixed_key)

                # If not found and this is the "active" role, check raw key
                if val is None and session.role == role_key:
                    val = (session.all_data or {}).get(f.field)

                # Extract "current" if it's a dict (legacy structure)
                if isinstance(val, dict) and "current" in val:
                    val = val["current"]

                if val is not None:
                    data[f.field] = val
                    has_data = True

        # If we found no data, create empty dict (fields come from metadata)
        if not has_data:
            # Get field names from party_fields metadata
            if category_id and person_type:
                data = {
                    f.field: None
                    for f in list_party_fields(category_id, person_type)
                }

        # Прив'язка користувача до ролі (для пошуку/фільтрації поза сесією)
        user_id = (session.role_owners or {}).get(role_key)

        parties[role_key] = {
            "person_type": person_type,
            "source": "manual",
            "user_id": user_id,
            "data": data,
        }

    # Signatures — динамічно з ролей
    signatures = {
        role: {"status": "pending", "signed_at": None}
        for role in target_roles
    }

    return {
        "document_id": document_id,
        "category_id": category_id,
        "template_id": template_id,
        "status": status,
        "parties": parties,
        "contract_fields": contract_fields,
        "signatures": signatures,
    }


def save_user_document(session: Session) -> Path | None:
    """
    Зберігає user-document JSON у директорії meta_data_users/documents
    з ім'ям <session_id>.json.
    """
    doc = build_user_document(session)
    repo = get_contracts_repo()
    try:
        repo.create_or_update(session, doc)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "contracts_repo_write_failed session_id=%s error=%s",
            session.session_id, exc,
        )
        if not settings.contracts_fs_fallback:
            raise

    if settings.contracts_fs_fallback:
        path = settings.meta_users_documents_root / f"{session.session_id}.json"
        write_json(path, doc)
        return path

    return None


async def save_user_document_async(session: Session) -> Path | None:
    """
    Асинхронне збереження user-document.
    """
    doc = build_user_document(session)
    repo = get_contracts_repo()
    try:
        await run_sync(repo.create_or_update, session, doc)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "contracts_repo_write_failed_async session_id=%s error=%s",
            session.session_id, exc,
        )
        if not settings.contracts_fs_fallback:
            raise

    if settings.contracts_fs_fallback:
        path = settings.meta_users_documents_root / f"{session.session_id}.json"
        await write_json_async(path, doc)
        return path

    return None


def load_user_document(session_id: str) -> Dict[str, Any]:
    """
    Завантажує user-document JSON за session_id.
    """
    try:
        repo = get_contracts_repo()
        doc = repo.get_by_session_id(session_id)
        if doc:
            return doc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "contracts_repo_read_failed session_id=%s error=%s",
            session_id, exc,
        )
        if not settings.contracts_fs_fallback:
            raise

    if not settings.contracts_fs_fallback:
        raise FileNotFoundError(f"User document for session '{session_id}' not found in repository")

    path = settings.meta_users_documents_root / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"User document for session '{session_id}' not found")
    return read_json(path)


async def load_user_document_async(session_id: str) -> Dict[str, Any]:
    """
    Асинхронне завантаження user-document.
    """
    try:
        repo = get_contracts_repo()
        doc = await run_sync(repo.get_by_session_id, session_id)
        if doc:
            return doc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "contracts_repo_read_failed_async session_id=%s error=%s",
            session_id, exc,
        )
        if not settings.contracts_fs_fallback:
            raise

    if not settings.contracts_fs_fallback:
        raise FileNotFoundError(f"User document for session '{session_id}' not found in repository")

    path = settings.meta_users_documents_root / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"User document for session '{session_id}' not found")
    return await read_json_async(path)
