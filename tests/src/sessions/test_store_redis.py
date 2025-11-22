import json
import time

import fakeredis
import pytest

from src.common.config import settings
from src.common.errors import SessionNotFoundError
from src.sessions.models import FieldState
from src.sessions.store import (
    get_or_create_session,
    list_user_sessions,
    load_session,
    save_session,
    transactional_session,
)
from src.storage import redis_client as redis_client_module


@pytest.fixture
def redis_backend(mock_settings, monkeypatch):
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client_module, "_redis", fake)
    monkeypatch.setattr(mock_settings, "session_backend", "redis")
    monkeypatch.setattr(mock_settings, "session_ttl_hours", 24)
    monkeypatch.setattr(mock_settings, "redis_url", "redis://localhost:6379/0")
    from src.sessions import store as store_module
    store_module._redis_disabled = False
    yield fake
    fake.flushall()


def test_save_and_load_roundtrip(redis_backend):
    session = get_or_create_session("redis_roundtrip")
    session.party_users = {"lessor": "user1"}
    session.party_fields["lessor"] = {"name": FieldState(status="ok")}
    save_session(session)

    loaded = load_session(session.session_id)
    assert loaded.party_users == {"lessor": "user1"}
    assert loaded.party_fields["lessor"]["name"].status == "ok"

    ttl = redis_backend.ttl(f"session:{session.session_id}")
    assert ttl is not None and ttl > 0 and ttl <= settings.session_ttl_hours * 3600

    raw = json.loads(redis_backend.get(f"session:{session.session_id}"))
    assert raw["party_fields"]["lessor"]["name"]["status"] is True


def test_transactional_session_saves_changes(redis_backend):
    session = get_or_create_session("redis_tx")

    with transactional_session(session.session_id) as s:
        s.party_users["lessor"] = "client1"
        s.contract_fields["cf1"] = FieldState(status="ok")

    loaded = load_session(session.session_id)
    assert loaded.party_users["lessor"] == "client1"
    assert loaded.contract_fields["cf1"].status == "ok"
    assert redis_backend.get(f"session_lock:{session.session_id}") is None


def test_list_user_sessions_returns_sorted(redis_backend):
    s1 = get_or_create_session("redis_ls1")
    s1.party_users = {"lessor": "user-list"}
    save_session(s1)

    time.sleep(0.01)

    s2 = get_or_create_session("redis_ls2")
    s2.party_users = {"lessee": "user-list"}
    save_session(s2)

    s3 = get_or_create_session("redis_ls3")
    s3.party_users = {"lessor": "other-user"}
    save_session(s3)

    # Add ghost id to index to ensure cleanup
    redis_backend.zadd("user_sessions:user-list", {"ghost": time.time()})

    sessions = list_user_sessions("user-list")
    ids = [s.session_id for s in sessions]
    assert ids == [s2.session_id, s1.session_id]
    assert "ghost" not in redis_backend.zrange("user_sessions:user-list", 0, -1)


def test_load_missing_raises(redis_backend):
    with pytest.raises(SessionNotFoundError):
        load_session("does-not-exist")
