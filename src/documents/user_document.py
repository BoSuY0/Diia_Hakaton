from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.categories.index import list_entities, list_party_fields
from src.common.config import settings
from src.sessions.models import Session, SessionState
from src.storage.fs import read_json, write_json
from src.categories.index import get_roles


def build_user_document(session: Session) -> Dict[str, Any]:
    """
    Побудова user-document JSON у форматі example_user_document.json
    на основі поточної Session.
    """
    document_id = f"{session.template_id}_{session.session_id}" if session.template_id else session.session_id
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
    # Динамічне визначення ролей з метаданих категорії
    if category_id:
        target_roles = get_roles(category_id)
    else:
        target_roles = []  # Порожній список, якщо категорія не обрана
    
    for role_key in target_roles:
        # Logic: If we have data for this role in session.all_data (prefixed or not), use it.
        # Previously we restricted by session.role. Now we want to show EVERYTHING we have.
        
        # Determine person_type for this role
        # It might be stored in session.party_types (new way) or session.person_type (legacy single-user)
        person_type = (session.party_types or {}).get(role_key)
        
        # Fallback for legacy single-user sessions
        if not person_type and session.role == role_key:
            person_type = session.person_type

        data: Dict[str, Any] = {}
        has_data = False
        
        if category_id and person_type:
            for f in list_party_fields(category_id, person_type):
                # Try specific key first (role_field), then generic (field) if it might be unique?
                # In sync_session we store as "{role}_{field}" AND "{field}" (fallback).
                # But here we need to be precise.
                
                # Try prefixed key first (created by sync_session)
                prefixed_key = f"{role_key}_{f.field}"
                val = (session.all_data or {}).get(prefixed_key)
                
                # If not found, and this is the "active" role, maybe it's under the raw key?
                if val is None and session.role == role_key:
                     val = (session.all_data or {}).get(f.field)
                
                # Extract "current" if it's a dict (legacy structure) or use raw value
                if isinstance(val, dict) and "current" in val:
                    val = val["current"]
                
                if val is not None:
                    data[f.field] = val
                    has_data = True
        
        # If we found no data, fill with Nones as before
        if not has_data:
             data = {
                "name": None,
                "address": None,
                "id_code": None,
                "id_doc": None,
                "iban": None,
                "phone": None,
                "email": None,
            }

        parties[role_key] = {
            "person_type": person_type,
            "source": "manual",
            "data": data,
        }

    # Signatures — поки що прості pending-плейсхолдери
    signatures = {
        "lessor": {"status": "pending", "signed_at": None},
        "lessee": {"status": "pending", "signed_at": None},
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


def save_user_document(session: Session) -> Path:
    """
    Зберігає user-document JSON у директорії meta_data_users/documents
    з ім'ям <session_id>.json.
    """
    doc = build_user_document(session)
    path = settings.meta_users_documents_root / f"{session.session_id}.json"
    write_json(path, doc)
    return path


def load_user_document(session_id: str) -> Dict[str, Any]:
    """
    Завантажує user-document JSON за session_id.
    """
    path = settings.meta_users_documents_root / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"User document for session '{session_id}' not found")
    return read_json(path)

