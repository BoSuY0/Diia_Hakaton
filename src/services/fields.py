from __future__ import annotations

from typing import List, Dict, Optional, Set
from dataclasses import dataclass

from src.sessions.models import Session
from src.categories.index import list_entities, list_party_fields, store as cat_store, _load_meta

@dataclass
class FieldSchema:
    key: str  # e.g. "lessor.name" or "contract_date"
    field_name: str # e.g. "name" or "contract_date"
    role: Optional[str] # e.g. "lessor" or None
    label: str
    required: bool
    type: str = "text"

def get_required_fields(session: Session) -> List[FieldSchema]:
    """
    Returns a list of all required fields for the current session state,
    considering category, roles, and person types.
    """
    if not session.category_id:
        return []

    result: List[FieldSchema] = []

    # 1. Contract Fields
    entities = list_entities(session.category_id)
    for e in entities:
        if e.required:
            result.append(FieldSchema(
                key=e.field,
                field_name=e.field,
                role=None,
                label=e.label,
                required=True,
                type=e.type
            ))

    # 2. Party Fields
    category_def = cat_store.get(session.category_id)
    if category_def:
        meta = _load_meta(category_def)
        roles = meta.get("roles") or {}

        for role_key in roles.keys():
            # Determine person type
            p_type = None
            if session.party_types and role_key in session.party_types:
                p_type = session.party_types[role_key]
            elif session.role == role_key and session.person_type:
                 # Fallback for backward compatibility
                p_type = session.person_type

            # Default to individual if unknown, to ensure we list something
            if not p_type:
                p_type = "individual"

            party_fields_list = list_party_fields(session.category_id, p_type)
            for pf in party_fields_list:
                if pf.required:
                    key = f"{role_key}.{pf.field}"
                    result.append(FieldSchema(
                        key=key,
                        field_name=pf.field,
                        role=role_key,
                        label=pf.label,
                        required=True,
                        type="text" # Party fields usually don't have type in metadata yet, handled by validator heuristic
                    ))

    return result

def validate_session_readiness(session: Session) -> bool:
    """
    Checks if all required fields in the session are filled and valid.
    """
    required = get_required_fields(session)
    for r in required:
        if r.role:
            # Check party fields
            role_fields = session.party_fields.get(r.role) or {}
            fs = role_fields.get(r.field_name)
            if not fs or fs.status != "ok":
                return False
        else:
            # Check contract fields
            fs = session.contract_fields.get(r.field_name)
            if not fs or fs.status != "ok":
                return False
    return True
