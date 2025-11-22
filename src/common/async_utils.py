from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from fastapi.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Execute a blocking function in the threadpool and await the result.
    Use this to safely call legacy sync utilities from async endpoints.
    """
    return await run_in_threadpool(func, *args, **kwargs)


def ensure_awaitable(value: Any) -> asyncio.Future:
    """
    Wrap non-awaitable values into a completed future so call sites
    can uniformly await results from mixed sync/async helpers.
    """
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return asyncio.ensure_future(value)  # type: ignore[arg-type]
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    fut.set_result(value)
    return fut
