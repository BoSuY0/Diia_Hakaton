from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import litellm  # type: ignore

from src.common.config import settings
from src.common.logging import get_logger


logger = get_logger(__name__)


def load_system_prompt() -> str:
    path = Path(__file__).with_name("system_prompt.txt")
    return path.read_text(encoding="utf-8")


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


def chat_with_tools(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    require_tools: bool = False,
    max_completion_tokens: int = 256,
) -> Any:
    """
    Обгортка над LiteLLM, яка викликає чат-модель з підтримкою tools.

    API сумісний зі структурою OpenAI ChatCompletion, тому
    код у server.py може й надалі працювати з response.choices[0].message.
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
    # Не задаємо штучний ліміт max_completion_tokens — дозволяємо моделі
    # повністю сформувати відповідь у межах її власного ліміту.
    # Filter messages to ensure tool roles are valid
    # LiteLLM/OpenAI requires that a message with role 'tool' MUST follow a message with 'tool_calls'
    # and match the tool_call_id.
    # We also need to ensure that if we have a tool call, we provide the result.
    
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

    response = litellm.completion(
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
