from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.categories.index import list_entities, list_party_fields
from src.common.config import settings
from src.sessions.models import Session, SessionState
from src.storage.fs import read_json, write_json, read_json_async, write_json_async


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
    
    # Determine roles dynamically from session or fallback to default
    target_roles = set(session.party_types.keys()) if session.party_types else set()
    if not target_roles:
        target_roles = {"lessor", "lessee"}
    
    for role_key in target_roles:
        # Logic: If we have data for this role in session.all_data (prefixed or not), use it.
        
        # Determine person_type for this role
        person_type = (session.party_types or {}).get(role_key)
        
        # Fallback for legacy single-user sessions
        if not person_type and session.role == role_key:
            person_type = session.person_type
            
        # If still unknown, skip or default? Let's skip to avoid errors
        if not person_type:
             # Try to guess or default to individual?
             # For user_document metadata it's better to be safe.
             if role_key in ["lessor", "lessee"]:
                 person_type = "individual"
             else:
                 continue

        data: Dict[str, Any] = {}
        has_data = False
        
        if category_id and person_type:
            for f in list_party_fields(category_id, person_type):
                # Try prefixed key first (created by upsert_field)
                # Key format is "role.field"
                prefixed_key = f"{role_key}.{f.field}"
                val = (session.all_data or {}).get(prefixed_key)
                
                # If not found, and this is the "active" role, maybe it's under the raw key?
                # (Legacy behavior)
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


async def save_user_document_async(session: Session) -> Path:
    """
    Асинхронне збереження user-document.
    """
    doc = build_user_document(session)
    path = settings.meta_users_documents_root / f"{session.session_id}.json"
    await write_json_async(path, doc)
    return path


def load_user_document(session_id: str) -> Dict[str, Any]:
    """
    Завантажує user-document JSON за session_id.
    """
    path = settings.meta_users_documents_root / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"User document for session '{session_id}' not found")
    return read_json(path)


async def load_user_document_async(session_id: str) -> Dict[str, Any]:
    """
    Асинхронне завантаження user-document.
    """
    path = settings.meta_users_documents_root / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"User document for session '{session_id}' not found")
    return await read_json_async(path)

