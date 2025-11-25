"""Tests for Redis session store."""
import json
import time

import pytest
import pytest_asyncio

from backend.shared.errors import SessionNotFoundError
from backend.domain.sessions.models import FieldState
from backend.infra.persistence.store import (
    aget_or_create_session,
    alist_user_sessions,
    aload_session,
    asave_session,
    atransactional_session,
)
from backend.infra.storage import redis_client as redis_client_module
from backend.infra.persistence import store as store_module
from backend.domain.sessions.ttl import ttl_hours_for_state

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    fakeredis = None  # type: ignore[assignment]
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture(name="redis_mock")
async def redis_backend_fixture(mock_settings, monkeypatch):
    """Create fake Redis backend for testing."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client_module, "_redis", fake)
    monkeypatch.setattr(mock_settings, "session_backend", "redis")
    monkeypatch.setattr(mock_settings, "session_ttl_hours", 24)
    monkeypatch.setattr(mock_settings, "redis_url", "redis://localhost:6379/0")
    mock_state = type("State", (), {"redis_disabled": False, "init_logged": False})()
    monkeypatch.setattr(store_module, "_state", mock_state)
    yield fake
    await fake.flushall()


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(redis_mock):
    """Test save and load roundtrip."""
    session = await aget_or_create_session("redis_roundtrip")
    session.role_owners = {"lessor": "user1"}
    session.party_fields["lessor"] = {"name": FieldState(status="ok")}
    await asave_session(session)

    loaded = await aload_session(session.session_id)
    assert loaded.role_owners == {"lessor": "user1"}
    assert loaded.party_fields["lessor"]["name"].status == "ok"

    ttl = await redis_mock.ttl(f"session:{session.session_id}")
    expected_ttl = ttl_hours_for_state(session.state) * 3600
    assert ttl is not None and 0 < ttl <= expected_ttl

    raw = json.loads(await redis_mock.get(f"session:{session.session_id}"))
    assert raw["party_fields"]["lessor"]["name"]["status"] is True


@pytest.mark.asyncio
async def test_transactional_session_saves_changes(redis_mock):
    """Test transactional session saves changes."""
    session = await aget_or_create_session("redis_tx")

    async with atransactional_session(session.session_id) as s:
        s.role_owners["lessor"] = "client1"
        s.contract_fields["cf1"] = FieldState(status="ok")

    loaded = await aload_session(session.session_id)
    assert loaded.role_owners["lessor"] == "client1"
    assert loaded.contract_fields["cf1"].status == "ok"
    assert await redis_mock.get(f"session_lock:{session.session_id}") is None


@pytest.mark.asyncio
async def test_list_user_sessions_returns_sorted(redis_mock):
    """Test list user sessions returns sorted."""
    s1 = await aget_or_create_session("redis_ls1")
    s1.role_owners = {"lessor": "user-list"}
    await asave_session(s1)

    time.sleep(0.01)

    s2 = await aget_or_create_session("redis_ls2")
    s2.role_owners = {"lessee": "user-list"}
    await asave_session(s2)

    s3 = await aget_or_create_session("redis_ls3")
    s3.role_owners = {"lessor": "other-user"}
    await asave_session(s3)

    # Add ghost id to index to ensure cleanup
    await redis_mock.zadd("user_sessions:user-list", {"ghost": time.time()})

    sessions = await alist_user_sessions("user-list")
    ids = [s.session_id for s in sessions]
    assert ids == [s2.session_id, s1.session_id]
    assert "ghost" not in await redis_mock.zrange("user_sessions:user-list", 0, -1)

    creator_only = await aget_or_create_session("redis_creator_only", user_id="creator")
    creator_only.role_owners = {}
    await asave_session(creator_only)

    creator_sessions = await alist_user_sessions("creator")
    assert any(s.session_id == "redis_creator_only" for s in creator_sessions)


@pytest.mark.asyncio
@pytest.mark.usefixtures("redis_mock")
async def test_load_missing_raises():
    """Test load missing raises error."""
    with pytest.raises(SessionNotFoundError):
        await aload_session("does-not-exist")
