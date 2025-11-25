"""LLM client for chat completions with tool support via LiteLLM."""
from __future__ import annotations

import asyncio
import atexit
import importlib
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import litellm  # type: ignore

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger


logger = get_logger(__name__)


class _PromptCache:
    """Cache container for system prompt."""

    value: str | None = None

    def get(self) -> str | None:
        """Get cached value."""
        return self.value

    def set(self, val: str) -> None:
        """Set cached value."""
        self.value = val


_prompt_cache = _PromptCache()

# Disable LiteLLM telemetry/background logging workers to avoid un-awaited coroutine warnings
try:
    litellm.telemetry = False  # type: ignore[attr-defined]
    litellm.turn_off_message_logging = True  # type: ignore[attr-defined]
    litellm.disable_streaming_logging = True  # type: ignore[attr-defined]
except (AttributeError, TypeError, RuntimeError):
    pass


def _disable_litellm_logging_workers() -> None:
    """
    LiteLLM occasionally spawns async logging workers that raise
    'coroutine ... was never awaited' warnings. We replace all known
    GLOBAL_LOGGING_WORKER references with a no-op stub.
    Additionally, we patch async logging helpers to no-op to bypass
    background logging entirely.
    """
    try:
        class _NoopWorker:
            """No-op stub for LiteLLM logging workers."""

            def ensure_initialized_and_enqueue(
                self, *_args: Any, **_kwargs: Any
            ) -> None:
                """No-op method."""

            def __repr__(self) -> str:
                """Return string representation."""
                return "<NoopWorker>"

        _noop = _NoopWorker()

        targets = []
        try:
            _lw = importlib.import_module("litellm.litellm_core_utils.logging_worker")
            targets.append(_lw)
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass

        try:
            _lutils = importlib.import_module("litellm.utils")
            targets.append(_lutils)
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass

        for mod_name in ("litellm.logging_worker", "litellm.logging"):
            try:
                module = __import__(mod_name, fromlist=["GLOBAL_LOGGING_WORKER"])
                targets.append(module)
            except (ImportError, AttributeError, ModuleNotFoundError):
                pass

        for target in targets:
            try:
                if hasattr(target, "GLOBAL_LOGGING_WORKER"):
                    target.GLOBAL_LOGGING_WORKER = _noop  # type: ignore
                if hasattr(target, "GLOBAL_LOGGING_HANDLER"):
                    target.GLOBAL_LOGGING_HANDLER = _noop  # type: ignore
            except (AttributeError, TypeError):
                pass

        # Patch utils async logging helper to a no-op coroutine
        try:
            _u = importlib.import_module("litellm.utils")

            async def _no_async_log(*_args: Any, **_kwargs: Any) -> None:
                """No-op async logging helper."""

            setattr(_u, "_client_async_logging_helper", _no_async_log)
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass
    except (ImportError, AttributeError, TypeError):
        pass


_disable_litellm_logging_workers()

# Ensure async HTTP clients are closed on exit to avoid
# "coroutine ... close_litellm_async_clients was never awaited" warnings.
try:
    from litellm import close_litellm_async_clients  # type: ignore

    def _close_litellm_clients() -> None:
        """Cleanup LiteLLM async clients on exit."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    close_litellm_async_clients(), loop
                )
                try:
                    fut.result(timeout=2)
                except (TimeoutError, RuntimeError, OSError):
                    pass
            else:
                loop.run_until_complete(close_litellm_async_clients())
        except (RuntimeError, OSError):
            try:
                asyncio.run(close_litellm_async_clients())
            except (RuntimeError, OSError):
                pass

    atexit.register(_close_litellm_clients)
except (ImportError, AttributeError):
    pass


def load_system_prompt() -> str:
    """Load and cache the system prompt from file."""
    if _prompt_cache.value is None:
        path = Path(__file__).with_name("system_prompt.txt")
        _prompt_cache.value = path.read_text(encoding="utf-8")
    return _prompt_cache.value


def ensure_api_key() -> None:
    """
    LiteLLM читає ключі з env змінних (OPENAI_API_KEY, ANTHROPIC_API_KEY тощо).
    Використовуємо один загальний LLM_API_KEY (settings.llm_api_key)
    і підставляємо його в потрібну змінну в залежності від моделі.
    """
    api_key = settings.llm_api_key
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not set")

    model_name = settings.llm_model.lower()

    # Дуже проста евристика: якщо в назві моделі фігурує "anthropic" або "claude" —
    # вважаємо, що використовуємо Anthropic і виставляємо ANTHROPIC_API_KEY.
    if "anthropic" in model_name or "claude" in model_name:
        if not os.getenv("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = api_key
    else:
        # За замовчуванням підставляємо в OPENAI_API_KEY (для openai-сумісних моделей)
        if not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = api_key


def _filter_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Фільтрує orphaned tool відповіді, залишаючи тільки валідні пари tool_call ↔ tool.
    """
    valid_messages = []
    tool_call_ids = set()

    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    # tc might be a dict or an object depending on how it was stored
                    if isinstance(tc, dict):
                        t_id = tc.get("id")
                    else:
                        t_id = getattr(tc, "id", None)

                    if t_id:
                        tool_call_ids.add(t_id)
            valid_messages.append(msg)
        elif role == "tool":
            # Only include tool response if we saw the call
            t_id = msg.get("tool_call_id")
            if t_id and t_id in tool_call_ids:
                valid_messages.append(msg)
            else:
                logger.warning("Dropping orphaned tool response: %s", t_id)
        else:
            valid_messages.append(msg)
    return valid_messages


async def chat_with_tools_async(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    require_tools: bool = False,
    max_completion_tokens: int = 256,
) -> Any:
    """Asynchronous wrapper over LiteLLM chat with tools."""
    ensure_api_key()

    kwargs: Dict[str, Any] = {}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url

    logger.info(
        "Calling LLM model=%s messages=%d tools=%d require=%s max_tokens=%s",
        settings.llm_model,
        len(messages),
        len(tools),
        require_tools,
        max_completion_tokens,
    )

    started = time.perf_counter()
    valid_messages = _filter_messages(messages)

    response = await litellm.acompletion(
        model=settings.llm_model,
        messages=valid_messages,
        tools=tools,
        tool_choice="required" if require_tools else "auto",
        parallel_tool_calls=True,
        temperature=0,
        top_p=1,
        presence_penalty=0,
        frequency_penalty=0,
        timeout=120,
        num_retries=2,
        drop_params=True,
        **kwargs,
    )
    duration_ms = (time.perf_counter() - started) * 1000

    # Акуратно витягаємо usage, якщо провайдер його повертає
    prompt_tokens = completion_tokens = total_tokens = None
    try:
        usage = getattr(response, "usage", None)
        if not usage and isinstance(response, dict):
            usage = response.get("usage")
        if usage:
            if isinstance(usage, dict):
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                total_tokens = usage.get("total_tokens")
            else:
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                completion_tokens = getattr(usage, "completion_tokens", None)
                total_tokens = getattr(usage, "total_tokens", None)
    except (AttributeError, TypeError, KeyError):
        pass

    logger.info(
        "LLM done model=%s ms=%.1f in=%s out=%s total=%s",
        settings.llm_model,
        duration_ms,
        prompt_tokens,
        completion_tokens,
        total_tokens,
    )

    return response


def chat_with_tools(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    require_tools: bool = False,
    max_completion_tokens: int = 256,
) -> Any:
    """
    Backward-compatible synchronous entrypoint that runs the async version.
    Use chat_with_tools_async from async contexts.
    """
    return asyncio.run(
        chat_with_tools_async(
            messages,
            tools,
            require_tools=require_tools,
            max_completion_tokens=max_completion_tokens,
        )
    )
