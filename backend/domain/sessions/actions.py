"""Session state management actions."""
from __future__ import annotations

from typing import Optional

from backend.shared.logging import get_logger
from backend.domain.sessions.models import Session, SessionState
from backend.domain.categories.index import store as category_store, Category, load_meta, template_store

logger = get_logger(__name__)

def set_session_category(session: Session, category_id: str) -> bool:
    """
    Sets the category for a session, resetting relevant state.
    Returns True if successful, False if category not found.

    NOTE: This function modifies the session in-place.
    It does NOT save the session to disk anymore.
    The caller must ensure it's called within a transactional_session context or saved manually.
    
    If the category has exactly one template, it will be automatically selected.
    """
    category: Optional[Category] = category_store.get(category_id)

    if not category:
        return False

    session.category_id = category_id
    
    # Автоматичний вибір шаблону, якщо в категорії є тільки один
    # Використовуємо template_store.get_by_category, щоб включити ai_only шаблони
    templates = template_store.get_by_category(category_id)
    if len(templates) == 1:
        session.template_id = templates[0].id
        session.state = SessionState.TEMPLATE_SELECTED
        logger.info(
            "set_session_category: auto-selected single template_id=%s for category_id=%s",
            session.template_id, category_id
        )
    else:
        session.template_id = None
        session.state = SessionState.CATEGORY_SELECTED
    session.party_fields.clear()
    session.contract_fields.clear()
    session.can_build_contract = False
    session.party_types.clear()
    session.role_owners.clear()
    session.signatures.clear()
    session.progress = {}
    session.all_data.clear()  # Clear all_data to avoid stale data from previous category

    # Встановлюємо required_roles з метаданих категорії
    # Це критично для коректної перевірки is_fully_signed
    try:
        meta = load_meta(category)
        roles = meta.get("roles") or {}
        session.required_roles = list(roles.keys())
        logger.info(
            "set_session_category: required_roles=%s",
            session.required_roles,
        )
    except (FileNotFoundError, KeyError, ValueError) as e:
        logger.warning("Failed to load category metadata: %s", e)
        session.required_roles = []

    # session is yielded by context manager, so changes will be saved on exit.
    logger.info(
        "set_session_category: session_id=%s category_id=%s",
        session.session_id, category_id,
    )
    return True
