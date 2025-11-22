from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

import litellm  # type: ignore

from src.common.config import settings
from src.common.logging import get_logger


logger = get_logger(__name__)
_SYSTEM_PROMPT_CACHE: str | None = None

# Disable LiteLLM telemetry/background logging workers to avoid un-awaited coroutine warnings
try:
    litellm.telemetry = False  # type: ignore[attr-defined]
    litellm.turn_off_message_logging = True  # type: ignore[attr-defined]
    litellm.disable_streaming_logging = True  # type: ignore[attr-defined]
except Exception:
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
            def ensure_initialized_and_enqueue(self, *args, **kwargs):
                return None

        _noop = _NoopWorker()

        targets = []
        try:
            from litellm.litellm_core_utils import logging_worker as _lw  # type: ignore
            targets.append(_lw)
        except Exception:
            pass

        try:
            import litellm.utils as _lutils  # type: ignore
            targets.append(_lutils)
        except Exception:
            pass

        for mod_name in ("litellm.logging_worker", "litellm.logging"):
            try:
                module = __import__(mod_name, fromlist=["GLOBAL_LOGGING_WORKER"])
                targets.append(module)
            except Exception:
                pass

        for target in targets:
            try:
                if hasattr(target, "GLOBAL_LOGGING_WORKER"):
                    target.GLOBAL_LOGGING_WORKER = _noop  # type: ignore
                if hasattr(target, "GLOBAL_LOGGING_HANDLER"):
                    target.GLOBAL_LOGGING_HANDLER = _noop  # type: ignore
            except Exception:
                pass

        # Patch utils async logging helper to a no-op coroutine
        try:
            import litellm.utils as _u  # type: ignore

            async def _no_async_log(*args, **kwargs):
                return None

            _u._client_async_logging_helper = _no_async_log  # type: ignore
        except Exception:
            pass
    except Exception:
        pass


_disable_litellm_logging_workers()

# Ensure async HTTP clients are closed on exit to avoid
# "coroutine ... close_litellm_async_clients was never awaited" warnings.
try:
    import atexit
    from litellm import close_litellm_async_clients  # type: ignore

    def _close_litellm_clients() -> None:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Run from existing loop and wait briefly
                fut = asyncio.run_coroutine_threadsafe(
                    close_litellm_async_clients(), loop
                )
                try:
                    fut.result(timeout=2)
                except Exception:
                    pass
            else:
                loop.run_until_complete(close_litellm_async_clients())
        except Exception:
            # Fallback: new loop for cleanup
            try:
                asyncio.run(close_litellm_async_clients())
            except Exception:
                pass

    atexit.register(_close_litellm_clients)
except Exception:
    pass


def load_system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        path = Path(__file__).with_name("system_prompt.txt")
        _SYSTEM_PROMPT_CACHE = path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT_CACHE


def _ensure_api_key() -> None:
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
                logger.warning(f"Dropping orphaned tool response: {t_id}")
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
    """
    Asynchronous wrapper over LiteLLM chat with tools.
    API remains OpenAI-compatible.
    """
    import time

    _ensure_api_key()

    kwargs: Dict[str, Any] = {}
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url

    logger.info(
        "Calling LLM via LiteLLM with %d messages model=%s tools=%d require_tools=%s max_completion_tokens=%s",
        len(messages),
        settings.llm_model,
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
    except Exception:
        pass

    logger.info(
        "LLM call done model=%s duration_ms=%.1f prompt_tokens=%s completion_tokens=%s total_tokens=%s",
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
