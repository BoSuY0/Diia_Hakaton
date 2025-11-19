"""
Невеликий тестовий скрипт для перевірки доступу до LLM Proxy Service CodeMie.

Використовує Azure OpenAI‑сумісний клієнт (`openai.AzureOpenAI`)
та дані з `.env`:
  - LLM_API_KEY  – api_key команди
  - LLM_MODEL    – назва моделі (наприклад, gpt-4.1)
  - LLM_BASE_URL – базовий URL проксі (опційно, за замовчуванням https://codemie.lab.epam.com/llms)
  - LLM_API_VERSION – версія API (опційно, за замовчуванням 2024-02-01)

Приклад:
    python test.py "Hello, CodeMie!"
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

try:
    import openai  # type: ignore[import]
except ImportError as exc:  # noqa: F401
    raise SystemExit(
        "Не знайдено бібліотеку 'openai'. "
        "Встановіть її командою: pip install openai"
    ) from exc

# Підтягуємо змінні з .env у os.environ
load_dotenv()

api_key = os.environ.get("LLM_API_KEY")
if not api_key:
    raise RuntimeError("LLM_API_KEY не задано в оточенні (.env)")

raw_model = os.environ.get("LLM_MODEL", "gpt-4.1")

# Офіційно доступні моделі для вашої команди (з повідомлення 401):
ALLOWED_MODELS = {
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-5-mini-2025-08-07",
    "claude-4-5-haiku",
    "codemie-text-embedding-ada-002",
    "gemini-2.5-flash",
}

# Прості алиаси, щоб підтримати назви з документації / інших SDK
MODEL_ALIASES = {
    "anthropic/claude-4.5-haiku": "claude-4-5-haiku",
    "claude-4.5-haiku": "claude-4-5-haiku",
    "gpt-5-nano-2025-08-07": "gpt-5-mini-2025-08-07",
}

model = MODEL_ALIASES.get(raw_model, raw_model)

if model not in ALLOWED_MODELS:
    allowed_str = ", ".join(sorted(ALLOWED_MODELS))
    raise SystemExit(
        f"Модель '{raw_model}' недоступна для вашої команди.\n"
        f"Використайте одну з доступних: {allowed_str}\n"
        "Підкоригуйте змінну LLM_MODEL у файлі .env."
    )

base_url = os.environ.get("LLM_BASE_URL", "https://codemie.lab.epam.com/llms")
api_version = os.environ.get("LLM_API_VERSION", "2024-02-01")

client = openai.AzureOpenAI(
    api_key=api_key,
    azure_endpoint=base_url,
    api_version=api_version,
)

prompt = " ".join(sys.argv[1:]).strip() or "Hello, CodeMie!"

print(f"Using model: {model}")
print(f"Prompt: {prompt!r}")

try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt},
        ],
    )
except openai.AuthenticationError as err:  # type: ignore[attr-defined]
    raise SystemExit(
        "Помилка автентифікації (401) при зверненні до LLM Proxy Service.\n"
        "Перевірте, що LLM_API_KEY коректний і що ви використовуєте "
        "доступну для вашої команди модель."
    ) from err

print("\nResponse:")
print(response.choices[0].message.content)
