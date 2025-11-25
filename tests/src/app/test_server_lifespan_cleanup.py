"""Tests for server lifespan cleanup."""
import asyncio

import pytest

from backend.api.http.server import lifespan


@pytest.mark.asyncio
async def test_lifespan_skips_cleanup_for_non_fs(monkeypatch, mock_settings):
    """Test lifespan skips cleanup for non-filesystem backend."""
    called = {"clean_abandoned": False, "clean_stale": False, "shutdown": False}

    async def fake_clean_abandoned(
        active_ids, grace_period_minutes=5  # pylint: disable=unused-argument
    ):
        called["clean_abandoned"] = True

    def fake_clean_stale():
        called["clean_stale"] = True

    async def fake_shutdown():
        called["shutdown"] = True

    monkeypatch.setattr("backend.domain.sessions.cleaner.clean_abandoned_sessions", fake_clean_abandoned)
    monkeypatch.setattr("backend.domain.sessions.cleaner.clean_stale_sessions", fake_clean_stale)
    monkeypatch.setattr("backend.api.http.server.stream_manager.shutdown", fake_shutdown)
    monkeypatch.setattr(mock_settings, "session_backend", "memory")

    async with lifespan(object()):
        # allow loop to tick once
        await asyncio.sleep(0.2)

    assert called["clean_abandoned"] is False and called["clean_stale"] is False
    assert called["shutdown"] is True
