import asyncio

import pytest
from src.app.server import lifespan


@pytest.mark.asyncio
async def test_lifespan_runs_cleanup(monkeypatch):
    called = {"clean_abandoned": False, "clean_stale": False, "shutdown": False}

    async def fake_clean_abandoned(active_ids, grace_period_minutes=5):
        called["clean_abandoned"] = True

    def fake_clean_stale():
        called["clean_stale"] = True

    async def fake_shutdown():
        called["shutdown"] = True

    monkeypatch.setattr("src.sessions.cleaner.clean_abandoned_sessions", fake_clean_abandoned)
    monkeypatch.setattr("src.sessions.cleaner.clean_stale_sessions", fake_clean_stale)
    monkeypatch.setattr("src.app.server.stream_manager.shutdown", fake_shutdown)

    async with lifespan(object()):
        # allow loop to tick once
        await asyncio.sleep(0.2)

    assert called["clean_abandoned"] or called["clean_stale"]  # at least one tick ran
    # shutdown should be invoked on exit (may be swallowed if exception)
    assert called["shutdown"] is True
