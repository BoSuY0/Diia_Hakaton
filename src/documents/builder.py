from __future__ import annotations

from typing import Dict

from src.categories.index import Category, list_entities, list_templates, store
from src.common.errors import MetaNotFoundError, SessionNotFoundError
from src.common.logging import get_logger
from src.documents.docx_filler import fill_docx_template
from src.sessions.models import FieldState
from src.sessions.store import load_session
from src.storage.fs import output_document_path


logger = get_logger(__name__)


def build_contract(session_id: str, template_id: str, partial: bool = False) -> Dict[str, str]:
    logger.info(
        "builder=build_contract session_id=%s template_id=%s partial=%s", 
        session_id, template_id, partial
    )
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        logger.error(
            "builder=build_contract session_not_found session_id=%s", session_id
        )
        raise SessionNotFoundError(str(exc))

    if session.template_id and session.template_id != template_id:
        logger.error(
            "builder=build_contract template_mismatch session_id=%s stored=%s incoming=%s",
            session_id,
            session.template_id,
            template_id,
        )
        raise MetaNotFoundError("Template in session does not match requested template")

    if not session.category_id:
        raise MetaNotFoundError("Session has no category_id")

    category: Category | None = store.get(session.category_id)
    if not category:
        raise MetaNotFoundError(f"Unknown category_id: {session.category_id}")

    templates = {t.id: t for t in list_templates(session.category_id)}
    if template_id not in templates:
        raise MetaNotFoundError(
            f"Template '{template_id}' not found in category '{session.category_id}'"
        )
    template = templates[template_id]

    entities = list_entities(session.category_id)
    missing_required = [
        e.field
        for e in entities
        if e.required
        and (e.field not in session.contract_fields
             or session.contract_fields[e.field].status != "ok")
    ]

    # Check required party fields
    if session.category_id:
        from src.categories.index import list_party_fields, store as cat_store, _load_meta
        
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
                    p_type = session.person_type
                
                if not p_type:
                    p_type = "individual"

                party_fields_list = list_party_fields(session.category_id, p_type)
                for pf in party_fields_list:
                    if pf.required:
                        role_fields = session.party_fields.get(role_key) or {}
                        field_state = role_fields.get(pf.field)
                        # Check if field is filled (status ok)
                        if not field_state or field_state.status != "ok":
                            missing_required.append(f"{role_key}.{pf.field}")

    if missing_required and not partial:
        logger.warning(
            "builder=build_contract missing_required_fields session_id=%s "
            "category_id=%s template_id=%s missing=%s",
            session_id,
            session.category_id,
            template_id,
            missing_required,
        )
        raise ValueError(f"Missing required fields: {', '.join(missing_required)}")

    field_values: Dict[str, str] = {}
    PLACEHOLDER = "(____________)"

    # 1) Поля договору (contract_fields)
    for entity in entities:
        # Значення беремо з агрегатора all_data (current), а не з FieldState
        entry = (session.all_data or {}).get(entity.field) or {}
        value = entry.get("current")
        
        if value is None or str(value).strip() == "":
            field_values[entity.field] = PLACEHOLDER if partial else ""
        else:
            field_values[entity.field] = str(value)

    # 2) Поля сторони договору (party_fields).
    if session.category_id:
        from src.categories.index import list_party_fields, store as cat_store, _load_meta
        
        category_def = cat_store.get(session.category_id)
        if category_def:
            meta = _load_meta(category_def)
            roles = meta.get("roles")
            if roles:
                for role_key in roles.keys():
                    # Determine person type for this role
                    p_type = None
                    if session.party_types and role_key in session.party_types:
                        p_type = session.party_types[role_key]
                    elif session.role == role_key and session.person_type:
                        # Fallback: if this is the current user's role, use their type
                        p_type = session.person_type
                    
                    if not p_type:
                        # Fallback to individual if not set, to ensure fields are processed
                        p_type = "individual"

                    # Get fields for this role+type
                    party_fields_list = list_party_fields(session.category_id, p_type)
                    
                    # Fill values
                    role_prefix = role_key.strip().lower()
                    for pf in party_fields_list:
                        # Key format: "role.field" (e.g. "lessor.name")
                        key = f"{role_prefix}.{pf.field}"
                        entry = (session.all_data or {}).get(key) or {}
                        value = entry.get("current")
                        
                        if value is None or str(value).strip() == "":
                            field_values[key] = PLACEHOLDER if partial else ""
                        else:
                            field_values[key] = str(value)

    output_path = output_document_path(template.id, session_id, ext="docx")
    # Основний шлях до шаблону:
    #   /assets/documents_files/default_documents_files/<category_id>/<file>
    # Якщо такого файлу немає, пробуємо без піддиректорії категорії:
    #   /assets/documents_files/default_documents_files/<file>
    from src.common.config import settings  # локальний імпорт, щоб уникнути циклів

    template_path = (
        settings.default_documents_root
        / category.id
        / template.file
    )
    if not template_path.exists():
        fallback = settings.default_documents_root / template.file
        if fallback.exists():
            template_path = fallback

    fill_docx_template(template_path, field_values, output_path)
    logger.info(
        "builder=build_contract success session_id=%s template_id=%s file_path=%s",
        session_id,
        template_id,
        output_path,
    )
    return {
        "file_path": str(output_path),
        "filename": output_path.name,
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
