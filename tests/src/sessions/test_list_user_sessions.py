"""Tests for list user sessions."""
import time

from backend.infra.persistence.store import (
    list_user_sessions,
    get_or_create_session,
    save_session,
)


def test_list_user_sessions_returns_sorted(mock_settings):  # pylint: disable=unused-argument
    """Test list user sessions returns sorted."""
    s1 = get_or_create_session("s1")
    s1.role_owners = {"lessor": "user1"}
    save_session(s1)

    time.sleep(0.01)
    s2 = get_or_create_session("s2")
    s2.role_owners = {"lessee": "user1"}
    save_session(s2)

    s3 = get_or_create_session("s3")
    s3.role_owners = {"lessor": "other"}
    save_session(s3)

    sessions = list_user_sessions("user1")
    ids = [s.session_id for s in sessions]
    assert ids == ["s2", "s1"]


def test_list_user_sessions_includes_creator(mock_settings):  # pylint: disable=unused-argument
    """Test list user sessions includes creator."""
    session = get_or_create_session("creator_session")
    session.creator_user_id = "creator"
    session.role_owners = {}
    save_session(session)

    sessions = list_user_sessions("creator")
    assert sessions and sessions[0].session_id == "creator_session"
