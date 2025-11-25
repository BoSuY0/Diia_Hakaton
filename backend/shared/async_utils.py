"""Async utility functions."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar, Union, cast

from fastapi.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Execute a blocking function in the threadpool and await the result.
    Use this to safely call legacy sync utilities from async endpoints.
    """
    return await run_in_threadpool(func, *args, **kwargs)


def ensure_awaitable(value: Union[Any, Awaitable[Any]]) -> asyncio.Future[Any]:
    """
    Wrap non-awaitable values into a completed future so call sites
    can uniformly await results from mixed sync/async helpers.
    """
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return asyncio.ensure_future(cast(Awaitable[Any], value))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    fut: asyncio.Future[Any] = loop.create_future()
    fut.set_result(value)
    return fut
