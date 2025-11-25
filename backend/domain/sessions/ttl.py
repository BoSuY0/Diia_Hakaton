"""TTL (time-to-live) utilities for session expiration."""
from __future__ import annotations

from backend.domain.sessions.models import Session, SessionState
from backend.infra.config.settings import settings


STATE_TTL_HOURS: dict[SessionState, int] = {
    SessionState.IDLE: settings.draft_ttl_hours,
    SessionState.CATEGORY_SELECTED: settings.draft_ttl_hours,
    SessionState.TEMPLATE_SELECTED: settings.draft_ttl_hours,
    SessionState.COLLECTING_FIELDS: settings.draft_ttl_hours,
    SessionState.READY_TO_BUILD: settings.draft_ttl_hours,
    SessionState.BUILT: settings.filled_ttl_hours,
    SessionState.READY_TO_SIGN: settings.filled_ttl_hours,
    SessionState.COMPLETED: settings.signed_ttl_days * 24,
}


def ttl_hours_for_state(state: SessionState | str) -> int:
    """Get TTL hours for a given session state."""
    try:
        st_enum = state if isinstance(state, SessionState) else SessionState(str(state))
    except ValueError:
        return settings.draft_ttl_hours
    return STATE_TTL_HOURS.get(st_enum, settings.draft_ttl_hours)


def ttl_hours_for_session(session: Session) -> int:
    """Get TTL hours for a session based on its current state."""
    return ttl_hours_for_state(session.state)
