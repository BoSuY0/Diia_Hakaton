from src.sessions.store import transactional_session, get_or_create_session, load_session, save_session


def test_transactional_session_saves_changes(mock_settings):
    sid = "txn_session"
    s = get_or_create_session(sid)
    with transactional_session(sid) as sess:
        sess.category_id = "cat1"
    loaded = load_session(sid)
    assert loaded.category_id == "cat1"


def test_transactional_session_raises_on_missing(mock_settings):
    try:
        with transactional_session("missing_sess") as _:
            pass
        assert False, "expected SessionNotFoundError"
    except Exception as e:
        from src.common.errors import SessionNotFoundError
        assert isinstance(e, SessionNotFoundError)
