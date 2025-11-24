from __future__ import annotations

from typing import Dict
import sys

from backend.domain.categories.index import Category, list_templates, store
from backend.shared.errors import MetaNotFoundError, SessionNotFoundError
from backend.shared.logging import get_logger
from backend.domain.documents.docx_filler import fill_docx_template_async
from backend.infra.persistence.store import aload_session
from backend.infra.storage.fs import output_document_path
from backend.domain.services.fields import get_required_fields
from backend.infra.config.settings import settings


logger = get_logger(__name__)
# Додаємо псевдомодуль для зручного monkeypatch у тестах
sys.modules["backend.domain.documents.builder.settings"] = settings


async def build_contract(session_id: str, template_id: str, partial: bool = False) -> Dict[str, str]:
    logger.info(
        "builder=build_contract session_id=%s template_id=%s partial_arg=%s",
        session_id,
        template_id,
        partial,
    )
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        logger.error("builder=build_contract session_not_found session_id=%s", session_id)
        raise MetaNotFoundError(str(exc))

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

    if template_id.startswith("dynamic_"):
        logger.error("builder=build_contract dynamic_templates_removed template_id=%s", template_id)
        raise MetaNotFoundError("Dynamic templates are no longer supported")

    if template_id not in templates:
        raise MetaNotFoundError(
            f"Template '{template_id}' not found in category '{session.category_id}'"
        )
    template = templates[template_id]

    required_fields = get_required_fields(session)
    missing_required = []

    for field in required_fields:
        is_ok = False
        if field.role:
            role_fields = session.party_fields.get(field.role) or {}
            fs = role_fields.get(field.field_name)
            if fs and fs.status == "ok":
                is_ok = True
        else:
            fs = session.contract_fields.get(field.field_name)
            if fs and fs.status == "ok":
                is_ok = True

        if not is_ok and (field.required or field.ai_required):
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

    field_values: Dict[str, str] = {}
    PLACEHOLDER = "(                 )"

    from backend.domain.categories.index import (
        list_entities,
        list_party_fields,
        _load_meta,
        store as cat_store,
        Entity,
        PartyField,
    )

    entities = list_entities(session.category_id)
    for entity in entities:
        entry = (session.all_data or {}).get(entity.field)
        value = None
        if isinstance(entry, dict):
            value = entry.get("current")
        else:
            value = entry

        if value is None or str(value).strip() == "":
            field_values[entity.field] = PLACEHOLDER if partial else ""
        else:
            field_values[entity.field] = str(value)

    category_def = cat_store.get(session.category_id)
    meta = _load_meta(category_def) if category_def else {}
    roles = meta.get("roles") or {}
    modules = meta.get("party_modules") or {}

    for role_key in roles.keys():
        p_type = None
        if session.party_types and role_key in session.party_types:
            p_type = session.party_types[role_key]
        elif session.role == role_key and session.person_type:
            p_type = session.person_type
        if not p_type:
            p_type = "individual"

        party_fields_list = []
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

        if not party_fields_list:
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
    template_path = (
        settings.default_documents_root
        / category.id
        / template.file
    )
    if not template_path.exists():
        fallback = settings.default_documents_root / template.file
        if fallback.exists():
            template_path = fallback

    await fill_docx_template_async(
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


# Backward-compatible alias for code paths expecting build_contract_async
build_contract_async = build_contract
