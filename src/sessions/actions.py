from __future__ import annotations

from typing import Optional

from src.common.logging import get_logger
from src.sessions.models import Session, SessionState
from src.categories.index import store as category_store, Category

logger = get_logger(__name__)

def set_session_category(session: Session, category_id: str) -> bool:
    """
    Sets the category for a session, resetting relevant state.
    Returns True if successful, False if category not found.

    NOTE: This function modifies the session in-place.
    It does NOT save the session to disk anymore.
    The caller must ensure it's called within a transactional_session context or saved manually.
    """
    category: Optional[Category] = category_store.get(category_id)
    
    if not category:
        return False

    session.category_id = category_id
    session.template_id = None
    session.state = SessionState.CATEGORY_SELECTED
    session.party_fields.clear()
    session.contract_fields.clear()
    session.can_build_contract = False
    session.progress = {}
    
    # session is yielded by context manager, so changes will be saved on exit.
    logger.info("set_session_category: session_id=%s category_id=%s", session.session_id, category_id)
    return True
