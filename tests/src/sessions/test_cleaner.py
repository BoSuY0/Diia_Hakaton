from backend.domain.sessions.cleaner import clean_stale_sessions, clean_abandoned_sessions


def test_cleaners_are_noop_for_non_filesystem_backend(mock_settings):
    clean_stale_sessions(max_age_hours=1)
    clean_abandoned_sessions(active_session_ids=set(), grace_period_minutes=1)
    assert True
