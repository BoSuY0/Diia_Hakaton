from __future__ import annotations

from typing import Any, List, Dict, Optional, Set
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
    ai_required: bool = False
    type: str = "text"

def get_required_fields(session: Session) -> List[FieldSchema]:
    """
    Returns a list of all required fields for the current session state,
    considering category, roles, and person types.
    """
    if not session.category_id:
        return []

    result: List[FieldSchema] = []

    if session.template_id and session.template_id.startswith("dynamic_"):
        raise ValueError("Dynamic templates are no longer supported")

    # 1. Contract Fields
    entities = list_entities(session.category_id)

    for e in entities:
        if e.required or getattr(e, "ai_required", False):
            result.append(FieldSchema(
                key=e.field,
                field_name=e.field,
                role=None,
                label=e.label,
                required=bool(e.required),
                ai_required=getattr(e, "ai_required", False),
                type=e.type
            ))

    # 2. Party Fields
    category_def = cat_store.get(session.category_id)
    if category_def:
        meta = _load_meta(category_def)
        roles = meta.get("roles") or {}
        modules = meta.get("party_modules") or {}
    else:
        roles = {}
        modules = {}

    # Filter roles if filling_mode is partial
    target_roles = list(roles.keys())
    if session.filling_mode == "partial" and session.role:
        # In partial mode, we only require fields for the CURRENT role.
        # Unless the role is not in the category (which shouldn't happen if validated).
        if session.role in roles:
            target_roles = [session.role]

    for role_key in target_roles:
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

        party_fields_list = []
        module = modules.get(p_type)
        if module:
            from src.categories.index import PartyField
            for raw in module.get("fields", []):
                party_fields_list.append(PartyField(field=raw["field"], label=raw.get("label", raw["field"]), required=raw.get("required", True)))
        
        if not party_fields_list:
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
                    ai_required=False,
                    type="text" # Party fields usually don't have type in metadata yet, handled by validator heuristic
                ))

    return result

def validate_session_readiness(session: Session) -> bool:
    """
    Checks if all required fields in the session are filled and valid.
    """
    required = get_required_fields(session)
    for r in required:
        needs = r.required or r.ai_required
        if not needs:
            continue
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


def collect_missing_fields(session: Session) -> Dict[str, Any]:
    """
    Returns a structured list of missing required fields grouped by contract/roles.
    Used for surfacing precise validation errors to the UI.
    """
    missing_contract: List[Dict[str, Any]] = []
    missing_roles: Dict[str, Dict[str, Any]] = {}

    role_labels: Dict[str, str] = {}
    if session.category_id:
        category_def = cat_store.get(session.category_id)
        if category_def:
            meta = _load_meta(category_def)
            role_labels = {
                k: v.get("label", k) for k, v in (meta.get("roles") or {}).items()
            }

    required = get_required_fields(session)
    for r in required:
        needs = r.required or r.ai_required
        if not needs:
            continue

        is_ok = False
        if r.role:
            role_fields = session.party_fields.get(r.role) or {}
            fs = role_fields.get(r.field_name)
            is_ok = bool(fs and fs.status == "ok")
        else:
            fs = session.contract_fields.get(r.field_name)
            is_ok = bool(fs and fs.status == "ok")

        if is_ok:
            continue

        entry = {"field": r.field_name, "key": r.key, "label": r.label}
        if r.role:
            role_entry = missing_roles.get(r.role) or {
                "role": r.role,
                "role_label": role_labels.get(r.role, r.role),
                "missing_fields": [],
            }
            role_entry["missing_fields"].append(entry)
            missing_roles[r.role] = role_entry
        else:
            missing_contract.append(entry)

    is_ready = not missing_contract and not any(
        v["missing_fields"] for v in missing_roles.values()
    )

    return {
        "is_ready": is_ready,
        "contract": missing_contract,
        "roles": missing_roles,
    }
