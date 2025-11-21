from __future__ import annotations

from typing import Dict

from src.categories.index import Category, list_templates, store
from src.common.errors import MetaNotFoundError, SessionNotFoundError
from src.common.logging import get_logger
from src.documents.docx_filler import fill_docx_template
from src.sessions.store import load_session
from src.storage.fs import output_document_path
from src.services.fields import get_required_fields


logger = get_logger(__name__)


def build_contract(session_id: str, template_id: str, partial: bool = False) -> Dict[str, str]:
    logger.info(
        "builder=build_contract session_id=%s template_id=%s partial_arg=%s", 
        session_id, template_id, partial
    )
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        logger.error(
            "builder=build_contract session_not_found session_id=%s", session_id
        )
        raise SessionNotFoundError(str(exc))

    # Infer partial mode from session if not explicitly set
    # REMOVED: We want strict validation if partial=False is passed (default), 
    # regardless of filling_mode. order_contract relies on this.
    # if not partial and session.filling_mode == "partial":
    #    partial = True
    #    logger.info("builder=build_contract inferred_partial=True from session.filling_mode")

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

    # 1. Validate missing fields using shared service
    # We get ALL required fields.
    required_fields = get_required_fields(session)
    missing_required = []

    for field in required_fields:
        is_ok = False
        if field.role:
            # Check party fields
            role_fields = session.party_fields.get(field.role) or {}
            fs = role_fields.get(field.field_name)
            if fs and fs.status == "ok":
                is_ok = True
        else:
            # Check contract fields
            fs = session.contract_fields.get(field.field_name)
            if fs and fs.status == "ok":
                is_ok = True
        
        if not is_ok:
            missing_required.append(field.key)

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

    # 2. Collect values for template
    field_values: Dict[str, str] = {}
    PLACEHOLDER = "(____________)"

    # We iterate over ALL fields that might be in the session, not just required ones.
    # But wait, the template might use fields that are NOT required but optional.
    # So we should probably iterate over all DEFINED fields in the category, including optional.

    # Let's get ALL potential fields (required + optional)
    # Re-using logic from get_required_fields but without filtering by 'required=True'
    # Ideally get_required_fields should be get_all_fields(session, required_only=False)
    # But for now let's replicate logic or update service.

    # Since we need to fill the template, we can just iterate over session.all_data!
    # The session.all_data contains flattened keys like "lessor.name" or "contract_date".
    # This is exactly what the template expects (plus simple transformation if needed).

    # However, session.all_data might contain stale data or data not relevant to current category roles?
    # Unlikely.

    # Let's safely iterate over known entities + known party fields to pull form all_data
    # This ensures we don't dump garbage into the template context, but also ensures we catch optional fields.

    # Actually, iterating over session.all_data is safer if we trust the keys.
    # But let's try to be structured to handle default values (PLACEHOLDER) for missing optional fields if partial=True?
    # No, if partial=True, we only care about REQUIRED fields being filled if we were in strict mode.
    # But here we want to fill what we have.

    # Let's use session.all_data directly as base, and fill missing keys with placeholders?
    # The issue is we don't know "missing keys" unless we list them.

    # So we DO need to list all fields.
    from src.categories.index import list_entities, list_party_fields, _load_meta, store as cat_store

    # Contract fields
    entities = list_entities(session.category_id)
    for entity in entities:
        entry = (session.all_data or {}).get(entity.field)
        value = None
        if isinstance(entry, dict):
            value = entry.get("current")
        else:
            value = entry
        
        if value is None or str(value).strip() == "":
            # Only use placeholder if it's partial build (preview)
            field_values[entity.field] = PLACEHOLDER if partial else ""
        else:
            field_values[entity.field] = str(value)

    # Party fields
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

            if not p_type:
                p_type = "individual"

            party_fields_list = list_party_fields(session.category_id, p_type)
            for pf in party_fields_list:
                key = f"{role_key}.{pf.field}"
                entry = (session.all_data or {}).get(key)
                value = None
                if isinstance(entry, dict):
                    value = entry.get("current")
                else:
                    value = entry

                if value is None or str(value).strip() == "":
                    field_values[key] = PLACEHOLDER if partial else ""
                else:
                    field_values[key] = str(value)

    output_path = output_document_path(template.id, session_id, ext="docx")

    from src.common.config import settings

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
