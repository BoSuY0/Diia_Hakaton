"""Tests for transactional session store."""
import pytest

from backend.infra.persistence.store import (
    atransactional_session,
    aget_or_create_session,
    aload_session,
)
from backend.shared.errors import SessionNotFoundError


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_transactional_session_saves_changes():
    """Test transactional session saves changes."""
    sid = "txn_session"
    await aget_or_create_session(sid)
    async with atransactional_session(sid) as sess:
        sess.category_id = "cat1"
    loaded = await aload_session(sid)
    assert loaded.category_id == "cat1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_transactional_session_raises_on_missing():
    """Test transactional session raises on missing."""
    with pytest.raises(SessionNotFoundError):
        async with atransactional_session("missing_sess"):
            pass
