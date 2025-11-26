"""Field schema and session readiness validation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from typing import TYPE_CHECKING

from backend.domain.categories.index import (
    PartyField,
    list_entities,
    list_party_fields,
    load_meta,
    store as cat_store,
)
from backend.domain.sessions.models import Session

if TYPE_CHECKING:
    pass


def get_party_fields_for_role(
    session: Session,
    role: str,
    roles_meta: Dict[str, Any],
    modules: Dict[str, Any],
) -> List[PartyField]:
    """Get party fields for a specific role.

    Centralizes the logic for determining party fields based on person type
    and category metadata.

    Args:
        session: The session object.
        role: The role to get fields for.
        roles_meta: The roles metadata from category.
        modules: The party_modules metadata from category.

    Returns:
        List of PartyField objects for the role.
    """
    p_type = None
    if session.party_types and role in session.party_types:
        p_type = session.party_types[role]
    elif session.role == role and session.person_type:
        p_type = session.person_type

    if not p_type:
        role_meta = roles_meta.get(role, {})
        p_type = role_meta.get("default_person_type")
        if not p_type:
            allowed = role_meta.get("allowed_person_types", [])
            if allowed:
                p_type = allowed[0]
            elif modules:
                p_type = next(iter(modules.keys()), "individual")

    party_fields_list: List[PartyField] = []
    module = modules.get(p_type)
    if module:
        for raw in module.get("fields", []):
            party_fields_list.append(
                PartyField(
                    field=raw["field"],
                    label=raw.get("label", raw["field"]),
                    required=raw.get("required", True),
                )
            )

    if not party_fields_list and session.category_id:
        party_fields_list = list_party_fields(session.category_id, p_type)

    return party_fields_list


@dataclass
class FieldSchema:
    """Schema for a field in a session (contract or party field)."""

    key: str  # e.g. "lessor.name" or "contract_date"
    field_name: str  # e.g. "name" or "contract_date"
    role: Optional[str]  # e.g. "lessor" or None
    label: str
    required: bool
    ai_required: bool = False
    type: str = "text"

def get_required_fields(
    session: Session,
    scope: Literal["self", "all"] = "self"
) -> List[FieldSchema]:
    """
    Returns a list of all required fields for the current session state,
    considering category, roles, and person types.
    
    Args:
        session: The session object.
        scope: "self" - only current user's role fields (respects filling_mode).
               "all" - all roles' fields (ignores filling_mode, for order validation).
    
    Returns:
        List of required FieldSchema objects.
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
        meta = load_meta(category_def)
        roles = meta.get("roles") or {}
        modules = meta.get("party_modules") or {}
    else:
        roles = {}
        modules = {}

    # Determine target roles based on scope
    target_roles = list(roles.keys())
    if scope == "self" and session.filling_mode == "partial" and session.role:
        # In partial mode with scope="self", only require fields for the CURRENT role.
        if session.role in roles:
            target_roles = [session.role]
    # For scope="all", always include ALL roles regardless of filling_mode

    for role_key in target_roles:
        party_fields_list = get_party_fields_for_role(session, role_key, roles, modules)

        for pf in party_fields_list:
            if pf.required:
                key = f"{role_key}.{pf.field}"
                # Party fields use validator heuristic for type inference
                result.append(FieldSchema(
                    key=key,
                    field_name=pf.field,
                    role=role_key,
                    label=pf.label,
                    required=True,
                    ai_required=False,
                    type="text",
                ))

    return result

def validate_session_readiness(session: Session) -> bool:
    """
    Checks if all required fields in the session are filled and valid.
    """
    # Template is a hard prerequisite: без нього договір не може вважатися готовим
    if not session.template_id:
        return False

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


def _check_fields_ready(
    session: Session,
    required_fields: List[FieldSchema]
) -> tuple[bool, List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, str]]:
    """
    Helper to check which required fields are missing.
    Returns (is_ready, missing_contract, missing_roles, role_labels).
    """
    missing_contract: List[Dict[str, Any]] = []
    missing_roles: Dict[str, Dict[str, Any]] = {}

    role_labels: Dict[str, str] = {}
    if session.category_id:
        category_def = cat_store.get(session.category_id)
        if category_def:
            meta = load_meta(category_def)
            role_labels = {
                k: v.get("label", k) for k, v in (meta.get("roles") or {}).items()
            }

    for r in required_fields:
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

    return is_ready, missing_contract, missing_roles, role_labels


def collect_missing_fields(
    session: Session,
    scope: Literal["self", "all"] = "self"
) -> Dict[str, Any]:
    """
    Returns a structured list of missing required fields grouped by contract/roles.
    Used for surfacing precise validation errors to the UI.
    
    Args:
        session: The session object.
        scope: "self" - check only current user's role (for UI display).
               "all" - check all roles (for order validation).
    
    Returns:
        Dict with is_ready, is_ready_self, is_ready_all, contract, roles.
    """
    # Get missing fields for the requested scope
    required = get_required_fields(session, scope=scope)
    is_ready, missing_contract, missing_roles, _ = _check_fields_ready(
        session, required
    )

    # Always compute both is_ready_self and is_ready_all for client convenience
    required_self = get_required_fields(session, scope="self")
    is_ready_self, _, _, _ = _check_fields_ready(session, required_self)

    required_all = get_required_fields(session, scope="all")
    is_ready_all, missing_contract_all, missing_roles_all, _ = _check_fields_ready(
        session, required_all
    )

    # Якщо немає template_id — вважаємо, що нічого не готово, і додаємо в missing
    template_missing_entry = None
    if not session.template_id:
        template_missing_entry = {
            "field": "template_id",
            "key": "template_id",
            "label": "Шаблон договору",
        }

    if template_missing_entry:
        missing_contract = [template_missing_entry] + missing_contract
        missing_contract_all = [template_missing_entry] + missing_contract_all
        is_ready = False
        is_ready_self = False
        is_ready_all = False

    # Detailed per-role structure (role -> {role, role_label, missing_fields:[...]})
    roles_detailed = missing_roles
    roles_all_detailed = missing_roles_all

    # Backward-compatible simple structure: role -> [missing_fields]
    roles_simple = {
        role: entry.get("missing_fields", [])
        for role, entry in roles_detailed.items()
    }
    roles_all_simple = {
        role: entry.get("missing_fields", [])
        for role, entry in roles_all_detailed.items()
    }

    return {
        "is_ready": is_ready,  # Backward compatible - based on requested scope
        "is_ready_self": is_ready_self,  # Current user's fields ready
        "is_ready_all": is_ready_all,  # All parties' fields ready
        "contract": missing_contract,
        # Simple format used by legacy clients: roles[role] -> [fields]
        "roles": roles_simple,
        # New detailed format for richer UI: roles_detailed[role] -> {role, role_label, missing_fields}
        "roles_detailed": roles_detailed,
        # Include all missing for order validation context
        "missing_all": {
            "contract": missing_contract_all,
            "roles": roles_all_simple,
            "roles_detailed": roles_all_detailed,
        } if scope == "all" else None,
    }
