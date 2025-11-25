"""Tests for stream manager."""
import asyncio
import json

import pytest

from backend.api.http.server import stream_manager


@pytest.mark.asyncio
async def test_stream_manager_connect_broadcast_disconnect():
    """Test stream manager connect, broadcast, and disconnect."""
    q = await stream_manager.connect("s1", "user1")
    assert any(c["queue"] is q for c in stream_manager.connections["s1"])

    await stream_manager.broadcast("s1", {"hello": "world"})
    msg = await asyncio.wait_for(q.get(), timeout=1)
    assert msg.startswith("data:")
    payload = json.loads(msg.split("data:")[1])
    assert payload["hello"] == "world"

    # Exclude sender should skip enqueueing
    await stream_manager.broadcast("s1", {"skip": True}, exclude_user_id="user1")
    assert q.empty()

    stream_manager.disconnect("s1", q)
    assert "s1" not in stream_manager.connections or all(
        c["queue"] is not q for c in stream_manager.connections.get("s1", [])
    )
