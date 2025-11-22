from __future__ import annotations

from typing import Dict

from src.categories.index import Category, list_templates, store
from src.common.errors import MetaNotFoundError, SessionNotFoundError
from src.common.logging import get_logger
from src.documents.docx_filler import fill_docx_template
from src.sessions.store import load_session
from src.storage.fs import output_document_path
from src.services.fields import get_required_fields
from src.common.config import settings
import sys


logger = get_logger(__name__)
# Додаємо псевдомодуль для зручного monkeypatch у тестах
sys.modules["src.documents.builder.settings"] = settings


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
        raise MetaNotFoundError(str(exc))

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

    # Dynamic Template Handling
    is_dynamic = template_id.startswith("dynamic_")
    dynamic_meta = {}
    
    if is_dynamic:
        from src.categories.index import get_dynamic_template_meta
        dynamic_meta = get_dynamic_template_meta(template_id)
        if not dynamic_meta:
             raise MetaNotFoundError(f"Dynamic template meta not found: {template_id}")
        
        # Override template object locally
        from src.categories.index import TemplateInfo
        template = TemplateInfo(id=template_id, name=dynamic_meta.get("label", "Dynamic Contract"), file=f"{template_id}.docx")

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
    # Видимий плейсхолдер для превʼю (не видаляється в docx_filler з keep_placeholders=True)
    PLACEHOLDER = "(                 )"

    from src.categories.index import list_entities, list_party_fields, _load_meta, store as cat_store, Entity, PartyField

    # Contract fields
    if is_dynamic:
        # Use fields from dynamic meta
        entities = []
        for raw in dynamic_meta.get("contract_fields", []):
             entities.append(Entity(field=raw["field"], type="text", label=raw["label"], required=raw.get("required", True)))
    else:
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
    if is_dynamic:
        roles = dynamic_meta.get("roles") or {}
        # For dynamic templates, we might have custom party fields defined in meta
        # But usually we stick to standard modules.
        # Let's check if dynamic meta overrides party modules
        modules = dynamic_meta.get("party_modules") or {}
    else:
        category_def = cat_store.get(session.category_id)
        meta = _load_meta(category_def) if category_def else {}
        roles = meta.get("roles") or {}
        modules = meta.get("party_modules") or {}

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

        # Get fields for this type
        party_fields_list = []
        module = modules.get(p_type)
        if module:
             for raw in module.get("fields", []):
                party_fields_list.append(PartyField(field=raw["field"], label=raw.get("label", raw["field"]), required=raw.get("required", True)))
        
        # Add standard fields if not dynamic (or if dynamic uses standard modules logic)
        if not is_dynamic and not party_fields_list:
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
    if is_dynamic:
        template_path = settings.assets_dir / "documents" / "templates" / "dynamic" / template.file
    else:
        template_path = (
            settings.default_documents_root
            / category.id
            / template.file
        )
        if not template_path.exists():
            fallback = settings.default_documents_root / template.file
            if fallback.exists():
                template_path = fallback

    fill_docx_template(
        template_path,
        field_values,
        output_path,
        keep_placeholders=partial,
    )
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
