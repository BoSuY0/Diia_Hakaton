import time

from backend.infra.persistence.store import list_user_sessions, get_or_create_session, save_session


def test_list_user_sessions_returns_sorted(mock_settings):
    s1 = get_or_create_session("s1")
    s1.party_users = {"lessor": "user1"}
    save_session(s1)

    time.sleep(0.01)
    s2 = get_or_create_session("s2")
    s2.party_users = {"lessee": "user1"}
    save_session(s2)

    s3 = get_or_create_session("s3")
    s3.party_users = {"lessor": "other"}
    save_session(s3)

    sessions = list_user_sessions("user1")
    ids = [s.session_id for s in sessions]
    assert ids == ["s2", "s1"]
