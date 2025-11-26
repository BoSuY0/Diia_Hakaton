"""FastAPI HTTP server for the Contract Builder ChatBot."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.agent.llm_client import chat_with_tools_async, load_system_prompt
from backend.api.http.state import Conversation, conversation_store
from backend.api.tool_adapter.tool_router import (
    dispatch_tool_async,
    tool_build_contract_async,
    tool_find_category_by_query_async,
    tool_get_category_entities_async,
    tool_get_category_parties_async,
    tool_get_party_fields_for_session_async,
    tool_get_session_summary_async,
    tool_get_templates_for_category_async,
    tool_set_category_async,
    tool_set_template_async,
    tool_upsert_field_async,
    tool_set_party_context_async,
    tool_registry as adapter_tool_registry,
)

from backend.shared.errors import SessionNotFoundError
from backend.shared.logging import get_logger, setup_logging
from backend.infra.config.settings import settings
from backend.domain.documents.user_document import load_user_document_async
from backend.domain.documents.builder import build_contract_async
from backend.infra.persistence.store import (
    aget_or_create_session,
    aload_session,
    atransactional_session,
    alist_user_sessions,
    ainit_store,
    generate_readable_id,
)
from backend.domain.sessions.models import Session, SessionState
from backend.domain.sessions.cleaner import clean_stale_sessions, clean_abandoned_sessions
from backend.domain.services.fields import collect_missing_fields
from backend.domain.categories.index import (
    list_party_fields, list_entities, store as cat_store, load_meta, list_templates,
    get_party_schema,
)
from backend.infra.storage.fs import ensure_directories
from backend.domain.validation.pii_tagger import sanitize_typed
from backend.shared.async_utils import run_sync, ensure_awaitable
from backend.shared.auth import resolve_user_id, diia_profile_from_token
from backend.shared import metrics
from backend.agent.tools.registry import tool_registry

# Backwards-compatible alias for sync monkeypatches in tests
tool_build_contract = tool_build_contract_async


setup_logging()
logger = get_logger(__name__)
security_logger = get_logger("security")
chat_with_tools = chat_with_tools_async  # backward compatibility for existing patches/tests

@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ARG001
    """Application lifespan context manager."""
    ensure_directories()
    await ainit_store()

    stop_event = asyncio.Event()

    async def cleanup_loop():
        try:
            # Невелика затримка, щоб не блокувати старт
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=0.1)
                return
            except asyncio.TimeoutError:
                pass

            while not stop_event.is_set():
                try:
                    # Access stream_manager from globals (defined later in this file)
                    _stream_mgr = globals().get('stream_manager')
                    active_ids = set(_stream_mgr.connections.keys()) if _stream_mgr else set()

                    # Run cleanup in background threads with таймаутами
                    try:
                        if inspect.iscoroutinefunction(clean_abandoned_sessions):
                            await asyncio.wait_for(
                                clean_abandoned_sessions(active_ids, grace_period_minutes=5),
                                timeout=2.0,
                            )
                        else:
                            await asyncio.wait_for(
                                asyncio.to_thread(clean_abandoned_sessions, active_ids, 5),
                                timeout=2.0,
                            )
                    except (asyncio.TimeoutError, OSError) as e:
                        logger.error("Abandoned cleanup error/timeout: %s", e)

                    try:
                        if inspect.iscoroutinefunction(clean_stale_sessions):
                            await asyncio.wait_for(clean_stale_sessions(), timeout=2.0)
                        else:
                            await asyncio.wait_for(
                                asyncio.to_thread(clean_stale_sessions),
                                timeout=2.0,
                            )
                    except (asyncio.TimeoutError, OSError) as e:
                        logger.error("Stale cleanup error/timeout: %s", e)

                except (OSError, RuntimeError) as e:
                    logger.error("Background cleanup error: %s", e)

                # Wait for 60 seconds or until stop signal
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    # Graceful exit on cancellation
                    logger.info("Cleanup loop cancelled; exiting quietly")
                    return
        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled (outer); exiting")
        except (OSError, RuntimeError) as e:
            logger.error("Cleanup loop stopped with error: %s", e)

    cleanup_task = None
    if settings.session_backend == "fs":
        cleanup_task = asyncio.create_task(cleanup_loop())
    else:
        logger.info("Filesystem cleanup loop skipped (backend=%s)", settings.session_backend)

    logger.info("Server started")
    yield

    # Shutdown logic
    logger.info("Shutting down server...")
    stop_event.set()

    if cleanup_task:
        try:
            # Give cleanup task a moment to exit gracefully
            await asyncio.wait_for(cleanup_task, timeout=2.0)
        except asyncio.TimeoutError:
            # Force cancel if it hangs (e.g., during initial sleep)
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            logger.info("Cleanup task cancelled during shutdown; exiting quietly")
        except (OSError, RuntimeError) as e:
            logger.error("Error waiting for cleanup task: %s", e)

    try:
        # Force close all SSE streams
        if 'stream_manager' in globals():
            await asyncio.wait_for(stream_manager.shutdown(), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    logger.info("Server shutdown complete")

app = FastAPI(title="Contract Builder ChatBot", lifespan=lifespan)


# CORS для фронтенду / зовнішніх клієнтів
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log HTTP requests with timing and user context."""
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    session_id = request.path_params.get("session_id") if hasattr(request, "path_params") else None
    user_id = request.headers.get("X-User-ID")
    auth_header = request.headers.get("Authorization")
    role = None

    try:
        resolved_for_logging = resolve_user_id(user_id, auth_header, allow_anonymous=True)
        if resolved_for_logging:
            user_id = resolved_for_logging
    except HTTPException:
        # For logging we keep raw headers to avoid masking auth issues
        pass

    # Peek into body for additional context
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            body_bytes = await request.body()
            # Re-attach body for downstream handlers
            request._body = body_bytes  # noqa: SLF001  # pylint: disable=protected-access
            if body_bytes:
                try:
                    payload = json.loads(body_bytes.decode("utf-8"))
                    role = payload.get("role")
                    session_id = session_id or payload.get("session_id") or payload.get("sessionId")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
        except (RuntimeError, ConnectionError):
            pass

    try:
        response = await call_next(request)
    except Exception:  # pylint: disable=broad-exception-caught
        error_id = str(uuid4())
        logger.exception(
            "request_error error_id=%s method=%s path=%s session_id=%s user_id=%s role=%s",
            error_id,
            request.method,
            request.url.path,
            session_id,
            user_id,
            role,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_id": error_id},
        )

    status = response.status_code
    log_fn = logger.info if status < 400 else logger.warning
    log_fn(
        "request id=%s method=%s path=%s status=%s session_id=%s user_id=%s role=%s",
        request_id,
        request.method,
        request.url.path,
        status,
        session_id,
        user_id,
        role,
    )
    try:
        metrics.record_request(request.method, request.url.path, status)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    try:
        response.headers["X-Request-ID"] = request_id
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return response


def _require_user_id(x_user_id: Optional[str], authorization: Optional[str] = None) -> str:
    return resolve_user_id(x_user_id, authorization)


# Session ID validation: alphanumeric, hyphens, underscores, 3-64 chars
_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")


def _validate_session_id(session_id: str) -> None:
    """Validate session_id format to prevent injection attacks."""
    if not session_id or not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid session_id format. Must be 3-64 alphanumeric characters, "
                "hyphens, or underscores."
            ),
        )


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    session_id: str
    message: str
    reset: bool = False  # If True, clears conversation history before processing


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    session_id: str
    reply: str


class FindCategoryRequest(BaseModel):
    """Request model for category search."""

    query: str


class CreateSessionRequest(BaseModel):
    """Request model for session creation.
    
    Supports two modes:
    1. Simple: just create empty session (session_id, user_id only)
    2. Full init: create session with all parameters at once
       (category_id, template_id, filling_mode, role, person_type)
    """

    session_id: Optional[str] = None
    user_id: Optional[str] = None
    # Optional parameters for full initialization
    category_id: Optional[str] = None
    template_id: Optional[str] = None
    filling_mode: Optional[str] = None  # "full" or "partial"
    role: Optional[str] = None
    person_type: Optional[str] = None


class JoinSessionRequest(BaseModel):
    """Request model for joining an existing session via deep-link."""

    session_id: str
    role: Optional[str] = None  # Optional role to claim
    person_type: Optional[str] = None  # Person type for the role


class JoinSessionResponse(BaseModel):
    """Response model for join session endpoint."""

    session_id: str
    category_id: Optional[str] = None
    template_id: Optional[str] = None
    state: str
    status_effective: str
    is_signed: bool
    role_claimed: Optional[str] = None
    required_roles: List[str] = []
    available_roles: List[str] = []  # Roles not yet claimed


@app.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """
    Прості метрики по запитах (in-memory лічильники).
    """
    return {
        "requests": metrics.snapshot(),
    }


@app.get("/me/profile")
async def me_profile(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
):
    """Get current user profile from JWT token."""
    user_id = resolve_user_id(x_user_id, authorization)
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    profile = diia_profile_from_token(token) if token else {}
    return {
        "user_id": user_id,
        "profile": profile,
    }


class CreateSessionResponse(BaseModel):
    """Response model for session creation."""

    session_id: str


class SetCategoryRequest(BaseModel):
    """Request model for setting session category."""

    category_id: str


class UpsertFieldRequest(BaseModel):
    """Request model for upserting a field value."""

    field: str
    value: Any
    role: Optional[str] = None
    lightweight: bool = False  # If True, skip full readiness validation for faster response


class SetTemplateRequest(BaseModel):
    """Request model for setting session template."""

    template_id: str


class BuildContractRequest(BaseModel):
    """Request model for building a contract."""

    template_id: Optional[str] = None


class SetPartyContextRequest(BaseModel):
    """Request model for setting party context."""

    role: str
    person_type: str
    filling_mode: Optional[str] = None


SESSION_AWARE_TOOLS = {
    "find_category_by_query",
    "get_templates_for_category",
    "get_party_fields_for_session",
    "set_category",
    "set_template",
    "set_party_context",
    "upsert_field",
    "get_session_summary",
    "build_contract",
    "route_message",
    "set_filling_mode",
    "sign_contract",
}


# Скорочені alias-імена тулів для LLM (для економії токенів).
TOOL_ALIAS_BY_CANON: Dict[str, str] = {
    "find_category_by_query": "fc",
    "get_templates_for_category": "gt",
    "get_category_entities": "ge",
    "set_category": "sc",
    "set_template": "st",
    "set_party_context": "pc",
    "get_party_fields_for_session": "pf",
    "upsert_field": "uf",
    "get_session_summary": "gs",
    "build_contract": "bc",
    "route_message": "rt",
    "sign_contract": "sn",
}
TOOL_CANON_BY_ALIAS: Dict[str, str] = {
    alias: name for name, alias in TOOL_ALIAS_BY_CANON.items()
}

# Скорочені alias-імена аргументів тулів (ключі JSON для LLM).
PARAM_ALIAS_BY_CANON: Dict[str, str] = {
    "query": "q",
    "category_id": "cid",
    "template_id": "tid",
    "role": "r",
    "person_type": "pt",
    "field": "f",
    "value": "v",
    # session_id LLM не задає, він інʼєктується бекендом
}
PARAM_CANON_BY_ALIAS: Dict[str, str] = {
    alias: name for name, alias in PARAM_ALIAS_BY_CANON.items()
}


# Які тулли дозволені моделі на кожному етапі життєвого циклу сесії
# Note: Consider moving this to a configuration or tool metadata in the future
ALLOWED_TOOLS_BY_STATE: Dict[str, List[str]] = {
    "idle": [
        "route_message",
        "find_category_by_query",
        "set_category",
    ],
    "category_selected": [
        "route_message",
        "find_category_by_query",
        "get_templates_for_category",
        "get_category_entities",
        "set_template",
    ],
    "template_selected": [
        "route_message",
        "find_category_by_query",
        "get_templates_for_category",
        "get_category_entities",
        "get_party_fields_for_session",
        "set_party_context",
        "upsert_field",
        "get_session_summary",
        "set_template",
        "set_filling_mode",
    ],
    "collecting_fields": [
        "route_message",
        "find_category_by_query",
        "get_templates_for_category",
        "set_party_context",
        "upsert_field",
        "get_session_summary",
        "set_filling_mode",
    ],
    "ready_to_build": [
        "route_message",
        "get_session_summary",
        # Allow editing (will invalidate signatures if any)
        "set_party_context",
        "upsert_field",
        "set_filling_mode",
    ],
    "built": [
        "route_message",
        "get_session_summary",
        # Allow editing (will invalidate signatures if any and reset state to ready/collecting)
        "set_party_context",
        "upsert_field",
        "set_filling_mode",
        "sign_contract",
    ],
    "ready_to_sign": [
        "route_message",
        "get_session_summary",
        "sign_contract",
    ],
    "completed": [
        "route_message",
        "get_session_summary",
    ],
}





def inject_session_id(args_json: str, conv_session_id: str, tool_name: str) -> str:
    """
    Гарантує, що всі session-aware тулли працюють з поточною сесією,
    незалежно від того, який session_id повернула модель.
    """
    try:
        raw_args = json.loads(args_json or "{}")
    except (json.JSONDecodeError, TypeError):
        raw_args = {}

    # Перекладаємо alias-ключі у канонічні імена параметрів.
    args: Dict[str, Any] = {}
    for key, value in raw_args.items():
        canon_key = PARAM_CANON_BY_ALIAS.get(key, key)
        args[canon_key] = value

    if tool_name in SESSION_AWARE_TOOLS:
        args["session_id"] = conv_session_id

    return json.dumps(args, ensure_ascii=False)


def canonical_args(args_json: str) -> str:
    """
    Канонікалізація JSON-аргументів тулла для дедуплікації викликів.
    """
    try:
        parsed = json.loads(args_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return args_json or "{}"
    try:
        return json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return args_json or "{}"


def _build_initial_messages(
    user_message: str, _session_id: str,  # noqa: ARG001
) -> List[Dict[str, Any]]:
    system_prompt = load_system_prompt()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    return messages


def last_user_message_text(messages: List[Dict[str, Any]]) -> str:
    """
    Повертає текст останнього user-повідомлення з непорожнім контентом.
    """
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            ).strip()
        else:
            continue
        if text:
            return text
    return ""


def detect_lang(text: str) -> str:
    """
    Дуже проста евристика: якщо є кириличні символи — вважаємо, що це українська.
    Інакше — англійська.
    """
    for ch in text.lower():
        if "а" <= ch <= "я" or ch in "іїєґ":
            return "uk"
    return "en"


I18N: Dict[str, Dict[str, str]] = {
    "category_locked": {
        "uk": "Категорію зафіксовано.",
        "en": "Category is set.",
    },
    "auto_template": {
        "uk": "Єдиний шаблон обрано автоматично.",
        "en": "The only template was selected automatically.",
    },
    "send_values": {
        "uk": (
            "Надішліть значення полів по одному у форматі: field=value. "
            "PII можна тегами [TYPE#N]."
        ),
        "en": (
            "Send field values one by one as: field=value. "
            "PII may be tags like [TYPE#N]."
        ),
    },
    "field_updated_built": {
        "uk": "Поле оновлено. Усі обов'язкові поля заповнені, договір зібрано.",
        "en": "Field updated. All required fields are filled, the contract is built.",
    },
    "field_updated_ready_no_template": {
        "uk": (
            "Поле оновлено. Всі обов'язкові поля заповнені, "
            "але шаблон договору ще не обрано."
        ),
        "en": (
            "Field updated. All required fields are filled, "
            "but the contract template is not selected yet."
        ),
    },
    "field_updated_summary": {
        "uk": "Поле оновлено. Нижче — поточний статус полів.",
        "en": "Field updated. Below is the current field status.",
    },
    "download_docx": {
        "uk": "Завантажити DOCX",
        "en": "Download DOCX",
    },
    "fallback_next_step": {
        "uk": (
            "Категорію зафіксовано. Оберіть шаблон договору або "
            "надішліть дані для заповнення наступного поля."
        ),
        "en": (
            "Category is set. Choose a contract template or "
            "send data to fill the next field."
        ),
    },
}


def _t(key: str, lang: str) -> str:
    data = I18N.get(key) or {}
    if lang in data:
        return data[lang]
    if "uk" in data:
        return data["uk"]
    return next(iter(data.values()), "")



async def _get_effective_state(
    session_id: str,
    _messages: List[Dict[str, Any]],  # noqa: ARG001 - used indirectly via has_category_tool
    *,
    has_category_tool: bool = False,
) -> str:
    """
    Визначає поточний стан сесії для state-gating.

    До першого set_category в поточній розмові вважаємо станом "idle",
    навіть якщо у збереженій сесії він був інший.
    """
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError:
        # Якщо сесію ще не створено — вважаємо стан "idle".
        return "idle"

    # Якщо в історії поточної розмови ще не було set_category, але сесія вже має категорію/шаблон,
    # використовуємо фактичний стан сесії, щоб не зависати в idle після рестарту чи REST-створення.
    if not has_category_tool and session.category_id:
        return session.state.value

    if not has_category_tool:
        return "idle"

    return session.state.value


async def filter_tools_for_session(
    session_id: str,
    messages: List[Dict[str, Any]],
    *,
    has_category_tool: bool = False,
) -> List[Dict[str, Any]]:
    """
    Формує підмножину TOOL_DEFINITIONS, дозволену на поточному етапі сесії.
    Використовує ToolRegistry для отримання визначень.
    """
    state = await _get_effective_state(
        session_id,
        messages,
        has_category_tool=has_category_tool,
    )
    allowed = set(ALLOWED_TOOLS_BY_STATE.get(state, []))

    # Get all definitions from registry (minified by default)
    all_tools = tool_registry.get_definitions(minified=True)

    if not allowed:
        return []

    # Filter based on allowed names (checking both name and alias)
    filtered_tools = []
    for tool_def in all_tools:
        func_name = tool_def["function"]["name"]
        # We need to check if this alias corresponds to an allowed tool
        # This is a bit tricky because 'allowed' list uses canonical names
        # but tool_def uses aliases.
        # Let's reverse lookup the canonical name for the alias
        tool = tool_registry.get_by_alias(func_name)
        if tool and tool.name in allowed:
            filtered_tools.append(tool_def)

    return filtered_tools



async def _tool_loop(messages: List[Dict[str, Any]], conv: Conversation) -> List[Dict[str, Any]]:
    """
    Tool-loop: виклик LLM, виконання тулів, захист від петель та мінімізація контексту.
    """
    max_iterations = 5
    last_tool_signature: Optional[str] = None

    for _ in range(max_iterations):
        tools = await filter_tools_for_session(
            conv.session_id,
            messages,
            has_category_tool=conv.has_category_tool,
        )
        try:
            tool_names = [
                t.get("function", {}).get("name", "<unknown>") for t in tools
            ]
            logger.info("toolset_for_state session_id=%s tools=%s", conv.session_id, tool_names)
        except (AttributeError, TypeError):
            logger.info(
                "toolset_for_state session_id=%s tools_count=%d",
                conv.session_id,
                len(tools),
            )

        state = await _get_effective_state(
            conv.session_id,
            messages,
            has_category_tool=conv.has_category_tool,
        )
        # Не форсимо tools навіть на idle — модель сама вирішує,
        # чи відповідати текстом (OTHER), чи викликати тулли.
        require_tools = False
        # Дозволяємо моделі достатньо токенів, щоб повністю
        # перелічити шаблони/поля та дати пояснення.
        # Idle: коротка відповідь-вступ, інші стани — детальні пояснення.
        max_tokens = 96 if state == "idle" else 256

        response = await ensure_awaitable(
            chat_with_tools(
                messages,
                tools,
                require_tools=require_tools,
                max_completion_tokens=max_tokens,
            )
        )
        choice = response.choices[0]
        message = choice.message

        # Дедуплікація tool_calls у межах одного повідомлення (по канонічному імені тулла)
        dedup_calls: Dict[str, Any] = {}
        if message.tool_calls:
            for tc in message.tool_calls:
                canon_name = TOOL_CANON_BY_ALIAS.get(tc.function.name, tc.function.name)
                key = f"{canon_name}:{canonical_args(tc.function.arguments)}"
                if key not in dedup_calls:
                    dedup_calls[key] = tc
        tool_calls = list(dedup_calls.values()) if dedup_calls else []

        assistant_msg: Dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if tool_calls:
            assistant_msg["tool_calls"] = [
                tc.model_dump() for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if tool_calls:
            # Захист від бескінечних повторів: якщо модель двічі поспіль
            # викликає той самий тул з тим самим payload — зупиняємо цикл.
            signature_parts = []
            for tc in tool_calls:
                canon_name = TOOL_CANON_BY_ALIAS.get(tc.function.name, tc.function.name)
                signature_parts.append(f"{canon_name}:{tc.function.arguments}")
            signature = "|".join(signature_parts)
            if signature and signature == last_tool_signature:
                messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            "Я декілька разів викликав один і той самий інструмент "
                            "без помітного прогресу. Спробуйте переформулювати запит "
                            "або змінити вхідні дані."
                        ),
                    }
                )
                break

            last_tool_signature = signature

            for tool_call in tool_calls:
                tool_name_alias = tool_call.function.name
                tool_name = TOOL_CANON_BY_ALIAS.get(tool_name_alias, tool_name_alias)
                raw_args = tool_call.function.arguments or "{}"

                tool_args = inject_session_id(
                    raw_args,
                    conv.session_id,
                    tool_name,
                )
                logger.info("Executing tool %s", tool_name)
                tool_result = await dispatch_tool_async(
                    tool_name,
                    tool_args,
                    tags=getattr(conv, "tags", None),
                    user_id=getattr(conv, "user_id", None),
                )

                if tool_name == "set_category":
                    # Після явного set_category вважаємо, що категорія зафіксована
                    # в межах цієї розмови (для state-gating).
                    try:
                        conv.has_category_tool = True
                    except AttributeError:
                        pass

                # tool_result is now already a string (VSC or JSON)
                compact_content = tool_result
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": compact_content,
                    }
                )

                # Жодних AUTO-BUILD / PREFETCH — бекенд виконує лише явні виклики тулів.

            # Обрізаємо історію перед наступною ітерацією tool-loop
            pruned = prune_messages(messages)
            messages = pruned
            conv.messages = pruned
            continue

        # No more tool calls, return messages
        break
    return messages


def prune_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Обрізає історію діалогу для LLM, залишаючи лише необхідний контекст.
    Важливо: зберігаємо лише узгоджені пари assistant tool_calls ↔ tool responses,
    щоб уникнути orphaned tool messages після обрізки.
    """
    # Нове правило: не обрізати контекст локально, лише прибирати "сироти".
    return _strip_orphan_tools(messages)


def _strip_orphan_tools(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Видаляє tool-повідомлення, якщо для них немає відповідного assistant.tool_call у вікні.
    Це запобігає втраті контексту в chat_with_tools, який відкидає orphaned tool responses.
    """
    # Збираємо всі tool_call_id з assistant-повідомлень у вікні
    allowed_ids = set()
    for m in msgs:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    allowed_ids.add(tc.get("id"))
                except (AttributeError, TypeError):
                    pass

    # Фільтруємо tool-повідомлення без відповідних id
    filtered: List[Dict[str, Any]] = []
    for m in msgs:
        if m.get("role") == "tool":
            tc_id = m.get("tool_call_id")
            if tc_id and tc_id in allowed_ids:
                filtered.append(m)
            # orphan is dropped
        else:
            filtered.append(m)
    return filtered


def format_reply_from_messages(messages: List[Dict[str, Any]]) -> str:
    """Return the last non-empty assistant text message from the conversation."""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            ).strip()
            if text:
                return text

    # Якщо жодного контенту асистента немає (наприклад, лише tool_calls),
    # пробуємо зібрати корисну інформацію з VSC-відповідей тулів
    # (TEMPLATES / ENTITIES) і показати її користувачу.
    templates: List[tuple[str, str]] = []
    entities: List[tuple[str, str, bool]] = []

    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content")
        if not isinstance(content, str):
            continue
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            continue
        header = lines[0]
        rows = lines[1:]
        if header == "TEMPLATES":
            for row in rows:
                parts = row.split("|")
                if not parts:
                    continue
                tid = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else tid
                if tid:
                    templates.append((tid, name))
        elif header == "ENTITIES":
            for row in rows:
                parts = row.split("|")
                if len(parts) < 4:
                    continue
                field = parts[0].strip()
                label = parts[1].strip()
                required_flag = parts[3].strip()
                required = required_flag == "1"
                if field:
                    entities.append((field, label, required))

    last_user = last_user_message_text(messages)
    lang = detect_lang(last_user) if last_user else "uk"

    if templates or entities:
        lines: List[str] = []
        if lang == "en":
            if templates:
                lines.append("Available templates:")
                for tid, name in templates:
                    lines.append(f"- {tid} — {name}")
            if entities:
                lines.append("Fields to fill:")
                for field, label, required in entities:
                    flag = "(required)" if required else "(optional)"
                    lines.append(f"- {field}: {label} {flag}")
            lines.append(
                "Reply with the template id you choose, "
                "or send the first field as field=value."
            )
        else:
            if templates:
                lines.append("Доступні шаблони:")
                for tid, name in templates:
                    lines.append(f"- {tid} — {name}")
            if entities:
                lines.append("Потрібно заповнити такі поля:")
                for field, label, required in entities:
                    flag = "(обов'язкове)" if required else "(необов'язкове)"
                    lines.append(f"- {field}: {label} {flag}")
            lines.append(
                "Напишіть, який шаблон обираєте (id), "
                "або надішліть перше поле у форматі field=value."
            )
        return "\n".join(lines)

    # Якщо навіть VSC-відповідей немає — повертаємо коротку підказку.
    return _t("fallback_next_step", lang)


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    """
    Basic health-check endpoint (public).
    Returns minimal info to avoid exposing infrastructure details.
    """
    return {"status": "ok"}


@app.get("/healthz/detailed")
async def healthz_detailed(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Detailed health-check (requires authentication).
    Returns infrastructure status for debugging.
    """
    # Require authentication for detailed health info
    _require_user_id(x_user_id, authorization)

    try:
        from docx import Document  # type: ignore  # pylint: disable=import-outside-toplevel
        Document()
        docx_ok = True
    except (ImportError, OSError):
        docx_ok = False

    redis_ok = False
    if settings.redis_url:
        try:
            from backend.infra.storage.redis_client import get_redis  # pylint: disable=import-outside-toplevel
            client = await get_redis()
            await client.ping()
            redis_ok = True
        except (ImportError, OSError, ConnectionError):
            redis_ok = False

    db_ok = False
    if settings.contracts_db_url:
        try:
            if settings.contracts_db_url.startswith("mysql"):
                import pymysql  # pylint: disable=import-outside-toplevel
                parsed = urlparse(settings.contracts_db_url)
                conn = pymysql.connect(host=parsed.hostname or "localhost", connect_timeout=2)
                conn.close()
            db_ok = True
        except (pymysql.Error, OSError):
            db_ok = False
    else:
        db_ok = True  # SQLite local by default

    return {
        "status": "ok",
        "docx_ok": docx_ok,
        "redis_ok": redis_ok,
        "contracts_db_ok": db_ok,
    }


@app.get("/categories")
async def list_categories() -> List[Dict[str, str]]:
    """List all available contract categories."""
    categories = []
    for category in cat_store.categories.values():
        if category.id == "custom":
            continue
        categories.append({"id": category.id, "label": category.label})
    return categories


@app.post("/categories/find")
async def find_category(req: FindCategoryRequest) -> Dict[str, Any]:
    """Find category by natural language query."""
    return await tool_find_category_by_query_async(req.query)


@app.get("/categories/{category_id}/templates")
async def get_category_templates(category_id: str) -> Dict[str, Any]:
    """Get available templates for a category."""
    try:
        return await tool_get_templates_for_category_async(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/categories/{category_id}/entities")
async def get_category_entities(category_id: str) -> Dict[str, Any]:
    """Get contract field entities for a category."""
    try:
        return await tool_get_category_entities_async(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/categories/{category_id}/parties")
async def get_category_parties(category_id: str) -> Dict[str, Any]:
    """Get party roles for a category."""
    try:
        return await tool_get_category_parties_async(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/categories/{category_id}/schema")
async def get_category_schema(category_id: str) -> Dict[str, Any]:
    """
    Отримати схему ролей та полів для категорії БЕЗ створення сесії.
    Використовується для показу форми вибору ролі до створення сесії.
    
    Returns:
        - category_id: ID категорії
        - main_role: роль за замовчуванням
        - roles: список ролей з allowed_person_types
        - person_types: типи осіб з полями для кожного
    """
    try:
        return get_party_schema(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/sessions/{session_id}/party-fields")
async def get_session_party_fields(session_id: str) -> Dict[str, Any]:
    """
    Повертає перелік полів сторони договору (name, address, тощо)
    для поточної сесії, виходячи з role + person_type.
    """
    _validate_session_id(session_id)
    result = await tool_get_party_fields_for_session_async(session_id=session_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions/{session_id}/party-context")
async def set_session_party_context(
    session_id: str,
    req: SetPartyContextRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Set party context (role, person type) for a session."""
    _validate_session_id(session_id)
    user_id = _require_user_id(x_user_id, authorization)

    result = await tool_set_party_context_async(
        session_id=session_id,
        role=req.role,
        person_type=req.person_type,
        filling_mode=req.filling_mode,
        _context={"user_id": user_id},
    )
    if result.get("ok", False):
        await stream_manager.broadcast(session_id, {
            "type": "schema_update",
            "reason": "party_context_changed"
        })

    if not result.get("ok", False):
        status_code = int(result.get("status_code") or 400)
        logger.warning(
            "set_party_context_failed status=%s session_id=%s user_id=%s role=%s error=%s",
            status_code,
            session_id,
            user_id,
            req.role,
            result.get("error"),
        )
        raise HTTPException(status_code=status_code, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    req: CreateSessionRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> CreateSessionResponse:
    """Create a new contract session.
    
    Supports full initialization with all parameters:
    - category_id: set category
    - template_id: set template (requires category_id)
    - filling_mode: "full" or "partial"
    - role: claim role for user
    - person_type: set person type for the role
    """
    # Якщо ID не передано, генеруємо читабельний.
    session_id = req.session_id or generate_readable_id("new")
    _validate_session_id(session_id)
    creator_user_id = req.user_id or resolve_user_id(x_user_id, authorization)
    session = await aget_or_create_session(session_id, user_id=creator_user_id)
    
    # Full initialization: apply all parameters if provided
    errors = []
    
    if req.category_id:
        result = await tool_set_category_async(session.session_id, req.category_id)
        if not result.get("ok", False):
            errors.append(f"category: {result.get('error', 'Failed')}")
    
    if req.template_id:
        if not req.category_id:
            errors.append("template: category_id is required to set template")
        else:
            result = await tool_set_template_async(session.session_id, req.template_id)
            if not result.get("ok", False):
                errors.append(f"template: {result.get('error', 'Failed')}")
    
    if req.filling_mode:
        tool = adapter_tool_registry.get("set_filling_mode")
        if tool:
            result = await tool.execute_async(
                {"session_id": session.session_id, "mode": req.filling_mode},
                {"user_id": creator_user_id}
            )
            if not result.get("ok", False):
                errors.append(f"filling_mode: {result.get('error', 'Failed')}")
    
    if req.role and req.person_type:
        result = await tool_set_party_context_async(
            session_id=session.session_id,
            role=req.role,
            person_type=req.person_type,
            filling_mode=req.filling_mode,
            _context={"user_id": creator_user_id},
        )
        if not result.get("ok", False):
            errors.append(f"party_context: {result.get('error', 'Failed')}")
    elif req.role or req.person_type:
        errors.append("party_context: both role and person_type are required")
    
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"session_id": session.session_id, "errors": errors}
        )
    
    return CreateSessionResponse(session_id=session.session_id)


@app.post("/sessions/join", response_model=JoinSessionResponse)
async def join_session(
    req: JoinSessionRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> JoinSessionResponse:
    """Join an existing session via deep-link.

    Unlike POST /sessions which can create new sessions, this endpoint:
    - Only works with existing sessions (returns 404 if not found)
    - Does NOT modify creator_user_id, category_id, template_id
    - Optionally claims a role for the joining user
    - Returns current session state for UI display

    Used for deep-link scenarios where user joins via shared link.
    """
    _validate_session_id(req.session_id)

    user_id = resolve_user_id(x_user_id, authorization, allow_anonymous=False)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to join session")
    
    # Session MUST exist - this is join, not create
    try:
        session = await aload_session(req.session_id)
    except SessionNotFoundError as exc:
        logger.warning(
            "join_session: session not found session_id=%s user_id=%s",
            req.session_id,
            user_id,
        )
        raise HTTPException(
            status_code=404,
            detail="Договір не знайдено. Можливо, посилання застаріле або недійсне.",
        ) from exc

    # Get available roles (not yet claimed)
    # Prefer session.required_roles (set from category metadata)
    required_roles = session.required_roles if session.required_roles else list(session.party_types.keys())
    available_roles = [
        role for role in required_roles
        if session.role_owners.get(role) is None
    ]

    role_claimed = None

    # If user wants to claim a role
    if req.role and req.person_type:
        # Check if role is available
        if req.role in session.role_owners and session.role_owners[req.role] != user_id:
            raise HTTPException(
                status_code=409,
                detail=f"Роль '{req.role}' вже зайнята іншим користувачем."
            )

        # Claim the role
        result = await tool_set_party_context_async(
            session_id=session.session_id,
            role=req.role,
            person_type=req.person_type,
            _context={"user_id": user_id},
        )
        if result.get("ok", False):
            role_claimed = req.role
            # Refresh session after update
            session = await aload_session(req.session_id)
            available_roles = [
                role for role in required_roles
                if session.role_owners.get(role) is None
            ]

    # Compute canonical status
    status_effective = _compute_status_effective(session)

    return JoinSessionResponse(
        session_id=session.session_id,
        category_id=session.category_id,
        template_id=session.template_id,
        state=session.state.value,
        status_effective=status_effective,
        is_signed=session.is_fully_signed,
        role_claimed=role_claimed,
        required_roles=required_roles,
        available_roles=available_roles,
    )


def check_session_access(
    session: Session,
    user_id: Optional[str],
    *,
    require_participant: bool = False,
    allow_owner: bool = False,
) -> None:
    """
    Check if user has access to a session.

    Enforces strict access control:
    - If session is full (all roles taken), only participants can access.
    - If session is not full, allow read access so new users can claim a free role.
    - If require_participant=True, enforce participant header even if session
      is not full (for sensitive endpoints).
    - allow_owner: treat session.creator_user_id as participant.
    """
    def _deny(status: int, reason: str) -> None:
        security_logger.warning(
            "acl_denied status=%s reason=%s session_id=%s user_id=%s",
            status,
            reason,
            session.session_id,
            user_id,
        )

    is_owner = bool(
        allow_owner and user_id and session.creator_user_id and user_id == session.creator_user_id
    )

    # If participant-level access is required, enforce header presence early
    if require_participant and not user_id:
        _deny(401, "missing_user_id")
        raise HTTPException(status_code=401, detail="Missing X-User-ID")

    # 1. If no category, we can't determine roles, so allow access (setup phase)
    if not session.category_id:
        # If some roles are already claimed, enforce participant ownership
        is_participant = user_id in session.role_owners.values()
        not_allowed = not is_participant and not is_owner
        if require_participant and session.role_owners and not_allowed:
            _deny(403, "not_participant_setup_phase")
            raise HTTPException(
                status_code=403, detail="You are not a participant of this session."
            )
        return

    # 2. Load metadata to count roles
    cat = cat_store.get(session.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    try:
        meta = load_meta(cat)
    except (FileNotFoundError, OSError, KeyError) as exc:
        raise HTTPException(
            status_code=500, detail="Failed to load category metadata"
        ) from exc

    roles = meta.get("roles", {})
    fallback_count = max(len(session.party_types), len(session.role_owners))
    expected_roles_count = len(roles) if roles else fallback_count

    occupied_roles = len(session.role_owners)
    is_full = 0 < expected_roles_count <= occupied_roles

    # Enforce participant-only access when explicitly required or when session is already full
    if require_participant or is_full:
        if not user_id:
            _deny(401, "missing_user_id")
            raise HTTPException(status_code=401, detail="Missing X-User-ID")

        is_participant = user_id in session.role_owners.values()
        if session.role_owners and not is_participant and not is_owner:
            _deny(403, "not_participant_full_session")
            raise HTTPException(
                status_code=403, detail="You are not a participant of this session."
            )
        return

    # Session is not full: allow access even if some roles are already claimed,
    # so new users can observe free roles
    return


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Get session details and summary."""
    _validate_session_id(session_id)
    user_id = _require_user_id(x_user_id, authorization)
    try:
        # We need to load session to check access.
        # tool_get_session_summary loads it internally.
        # But we need to check BEFORE returning.
        # So we load it here first.
        session = await aload_session(session_id)

        check_session_access(session, user_id, allow_owner=True)

        return await tool_get_session_summary_async(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/user-documents/{session_id}")
async def get_user_document_api(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Повертає user-document JSON у форматі example_user_document.json
    для вказаної сесії.
    """
    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    user_id = _require_user_id(x_user_id, authorization)

    check_session_access(session, user_id, require_participant=True, allow_owner=True)

    try:
        return await load_user_document_async(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/category")
async def set_session_category(session_id: str, req: SetCategoryRequest) -> Dict[str, Any]:
    """Set category for a session."""
    _validate_session_id(session_id)
    result = await tool_set_category_async(session_id=session_id, category_id=req.category_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions/{session_id}/template")
async def set_session_template(session_id: str, req: SetTemplateRequest) -> Dict[str, Any]:
    """Set template for a session."""
    _validate_session_id(session_id)
    result = await tool_set_template_async(session_id=session_id, template_id=req.template_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


class SetFillingModeRequest(BaseModel):
    """Request model for setting filling mode."""

    mode: str


@app.post("/sessions/{session_id}/filling-mode")
async def set_session_filling_mode(
    session_id: str,
    req: SetFillingModeRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Set filling mode for a session."""
    _validate_session_id(session_id)
    user_id = _require_user_id(x_user_id, authorization)
    tool = adapter_tool_registry.get("set_filling_mode")
    if not tool:
        raise HTTPException(status_code=500, detail="Tool not found")

    result = await tool.execute_async(
        {"session_id": session_id, "mode": req.mode},
        {"user_id": user_id},
    )
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


class SafeStreamingResponse(StreamingResponse):
    """Custom StreamingResponse that swallows cancellation during shutdown."""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except asyncio.CancelledError:
            logger.info("StreamingResponse cancelled (shutdown/disconnect); closing gracefully")
            # Swallow cancellation to avoid noisy shutdown trace
            return

class StreamManager:
    """Manager for SSE connections per session."""

    def __init__(self):
        self.connections: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    async def connect(self, session_id: str, user_id: Optional[str]) -> asyncio.Queue:
        """Connect a user to session SSE stream."""
        queue = asyncio.Queue(maxsize=100)
        self.connections[session_id].append({"queue": queue, "user_id": user_id})
        return queue

    def disconnect(self, session_id: str, queue: asyncio.Queue):
        """Disconnect a queue from session."""
        if session_id not in self.connections:
            return
        filtered = [c for c in self.connections[session_id] if c.get("queue") is not queue]
        if filtered:
            self.connections[session_id] = filtered
        else:
            del self.connections[session_id]

    async def broadcast(
        self, session_id: str, message: dict, exclude_user_id: Optional[str] = None
    ):
        """Broadcast message to all connected clients for a session."""
        if session_id not in self.connections:
            return

        # Create SSE formatted message
        data = json.dumps(message)
        msg = f"data: {data}\n\n"

        to_remove = []
        # Iterate over a copy to avoid issues if queues are modified during iteration
        for conn in list(self.connections[session_id]):
            try:
                queue = conn.get("queue")
                cid = conn.get("user_id")
                if exclude_user_id and cid and cid == exclude_user_id:
                    continue
                if queue is None:
                    continue
                # Use put_nowait to avoid blocking if queue is full
                queue.put_nowait(msg)
            except (asyncio.QueueFull, RuntimeError) as exc:
                logger.warning("Stream broadcast error for %s: %s", session_id, exc)
                if queue is not None:
                    to_remove.append(queue)

        for queue in to_remove:
            self.disconnect(session_id, queue)

    async def shutdown(self):
        """
        Gracefully close all connections.
        """
        # Iterate over a copy of items because disconnect() might modify the dictionary
        for _sess_id, conns in list(self.connections.items()):
            for conn in conns:
                queue = conn.get("queue")
                if queue is None:
                    continue
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

stream_manager = StreamManager()

@app.get("/sessions/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    user_id_query: Optional[str] = Query(None, alias="user_id"),
    token_query: Optional[str] = Query(None, alias="token"),
):
    """
    Server-Sent Events endpoint for real-time session updates.
    """
    _validate_session_id(session_id)
    auth_header = authorization
    if not auth_header and token_query:
        auth_header = f"Bearer {token_query}"

    effective_user_query = None if settings.is_prod else user_id_query

    if settings.auth_mode == "jwt":
        user_id = resolve_user_id(None, auth_header)
    else:
        user_id = effective_user_query or resolve_user_id(
            x_user_id, auth_header, allow_anonymous=not settings.is_prod
        )

    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if settings.is_prod and not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID")

    check_session_access(
        session,
        user_id,
        require_participant=settings.is_prod,
        allow_owner=True,
    )

    queue = await stream_manager.connect(session_id, user_id)

    async def event_generator():
        heartbeat_interval = 30  # seconds
        heartbeat_msg = 'data: {"type": "heartbeat"}\n\n'
        
        # Send initial sync message on connect
        try:
            initial_msg = json.dumps({
                "type": "connected",
                "session_id": session_id,
                "user_id": user_id,
                "state": session.state.value if session else None,
                "signatures": session.signatures if session else {},
            })
            yield f"data: {initial_msg}\n\n"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("Failed to send initial sync: %s", exc)
        
        try:
            while True:
                try:
                    # Wait for new messages with timeout for heartbeat
                    msg = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    if msg is None:
                        # Server shutdown signal
                        break
                    yield msg
                except asyncio.TimeoutError:
                    # No message received - send heartbeat to keep connection alive
                    yield heartbeat_msg
        except asyncio.CancelledError:
            # Client disconnected or server shutting down
            # We just exit silently
            pass
        except (OSError, RuntimeError) as e:
            logger.error("SSE stream error for %s: %s", session_id, e)
        finally:
            stream_manager.disconnect(session_id, queue)

    return SafeStreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/fields")
async def upsert_session_field(
    session_id: str,
    req: UpsertFieldRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Upsert a field value in a session."""
    _validate_session_id(session_id)
    # If session has participants, require authentication via header.
    try:
        await aload_session(session_id)  # Validate session exists
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user_id = _require_user_id(x_user_id, authorization)

    result = await tool_upsert_field_async(
        session_id=session_id,
        field=req.field,
        value=req.value,
        tags=None,
        role=req.role,
        _context={"user_id": user_id, "lightweight": req.lightweight}
    )

    if result.get("ok", False):
        sender_id = user_id
        field_key = f"{req.role}.{req.field}" if req.role else req.field
        # Broadcast update to all listeners
        await stream_manager.broadcast(
            session_id,
            {
                "type": "field_update",
                "field": req.field,
                "field_key": field_key,
                "value": req.value,
                "role": req.role,
            },
            exclude_user_id=sender_id,
        )

    # Для REST-інтерфейсу явні помилки користувача сигналізуємо через статус з тулза (fallback 400)
    if not result.get("ok", False) and result.get("error"):
        status_code = int(result.get("status_code") or 400)
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": result["error"],
                "field": req.field,
                "role": req.role,
                "field_state": result.get("field_state"),
            },
        )
    return result


@app.post("/sessions/{session_id}/build")
async def build_contract(session_id: str, req: BuildContractRequest) -> Dict[str, Any]:
    """Build contract document from session data."""
    from backend.shared.errors import MetaNotFoundError  # pylint: disable=import-outside-toplevel
    _validate_session_id(session_id)
    # ensure session exists
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc_inner:
        raise HTTPException(status_code=404, detail=str(exc_inner)) from exc_inner
    
    # Use provided template_id or fall back to session's template_id
    template_id = req.template_id or session.template_id
    if not template_id:
        raise HTTPException(
            status_code=400,
            detail="Template ID is required. Please set template_id in request or session."
        )

    # Якщо в запиті передали template_id, але в сесії його немає/інший — зафіксуємо його,
    # щоб подальші кроки (status/preview/sign) мали правильний шаблон.
    if session.template_id != template_id:
        if not session.category_id:
            raise HTTPException(
                status_code=400,
                detail="Category must be set before selecting template."
            )
        result = await tool_set_template_async(session_id=session_id, template_id=template_id)
        if not result.get("ok", False):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to set template"))
        # оновимо сесію в пам'яті, щоб builder бачив актуальний template_id
        session = await aload_session(session_id)

    try:
        return await tool_build_contract_async(session_id=session_id, template_id=template_id)
    except MetaNotFoundError as exc_inner:
        raise HTTPException(status_code=404, detail=str(exc_inner)) from exc_inner
    except ValueError as exc_inner:
        raise HTTPException(status_code=400, detail=str(exc_inner)) from exc_inner


class PartyData(BaseModel):
    """Party data for sync request."""

    person_type: str
    fields: Dict[str, str]


class SyncSessionRequest(BaseModel):
    """Request model for syncing session data."""

    category_id: Optional[str] = None
    template_id: Optional[str] = None
    parties: Dict[str, PartyData]


@app.post("/sessions/{session_id}/sync")
async def sync_session(
    session_id: str,
    req: SyncSessionRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Універсальний ендпоінт для пакетного оновлення даних сесії.
    Підтримує One-shot (все одразу) та Two-shot (по частинах) флоу.
    """
    _validate_session_id(session_id)
    # Якщо сесія ще не створена — створюємо файл-чернетку
    await aget_or_create_session(session_id)

    # Access control: only participants can sync when roles are claimed/full.
    user_id = _require_user_id(x_user_id, authorization)
    session_for_acl = await aload_session(session_id)
    check_session_access(session_for_acl, user_id, require_participant=True, allow_owner=True)

    # Під час тестів метадані можуть змінюватися на льоту — перезавантажуємо індекс
    await run_sync(cat_store.load)

    missing_contract: list[str] = []
    missing_roles: Dict[str, Any] = {}
    is_ready = True
    template_id_local: Optional[str] = None
    role_owners: Dict[str, str] = {}

    async with atransactional_session(session_id) as session:
        # 2. Set Category / Template if provided
        if req.category_id:
            if req.category_id not in cat_store.categories:
                raise HTTPException(status_code=400, detail=f"Category {req.category_id} not found")
            # pylint: disable=import-outside-toplevel
            from backend.domain.sessions.actions import (
                set_session_category as apply_category,
            )
            # Якщо категорія змінюється — робимо повне очищення стану.
            if session.category_id != req.category_id:
                ok = apply_category(session, req.category_id)
                if not ok:
                    raise HTTPException(status_code=400, detail="Failed to set category")

        if req.template_id:
            cat_templates = list_templates(session.category_id) if session.category_id else []
            templates = {t.id for t in cat_templates}
            if templates and req.template_id not in templates:
                raise HTTPException(status_code=400, detail="Template does not belong to category")
            session.template_id = req.template_id
            session.state = SessionState.TEMPLATE_SELECTED

        if not session.category_id:
            raise HTTPException(status_code=400, detail="Category not set")

        category = cat_store.get(session.category_id)
        if not category:
            raise HTTPException(status_code=400, detail="Invalid category_id")

        category_meta = load_meta(category)
        defined_roles = category_meta.get("roles", {})

        # Import service
        # pylint: disable=import-outside-toplevel
        from backend.domain.services.session import update_session_field

        # 3. Process Parties
        for role_id, party_data in req.parties.items():
            if role_id not in defined_roles:
                raise HTTPException(status_code=400, detail=f"Unknown role: {role_id}")

            # Validate person_type
            allowed_types = defined_roles[role_id].get("allowed_person_types", [])
            if party_data.person_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid person_type '{party_data.person_type}' for role '{role_id}'"
                )

            # Update party type mapping
            session.party_types[role_id] = party_data.person_type

            # Upsert fields using SERVICE and collect validation errors
            field_errors: Dict[str, Dict[str, str]] = {}
            for field_name, value in party_data.fields.items():
                ok, error, fs = update_session_field(
                    session=session,
                    field=field_name,
                    value=value,
                    role=role_id,
                    context={"user_id": user_id, "source": "api"},
                )
                if not ok and error:
                    if role_id not in field_errors:
                        field_errors[role_id] = {}
                    field_errors[role_id][field_name] = error

        # 4. Check Readiness using shared schema helper
        from backend.domain.services.fields import get_required_fields  # pylint: disable=import-outside-toplevel
        
        # Get labels for better UX
        role_labels = {r: info.get("label", r) for r, info in defined_roles.items()}
        party_field_labels: Dict[str, Dict[str, str]] = {}
        for role_id_check in defined_roles:
            p_type = session.party_types.get(role_id_check, "individual")
            p_fields = list_party_fields(session.category_id, p_type)
            party_field_labels[role_id_check] = {pf.field: pf.label for pf in p_fields}
        
        required_fields = get_required_fields(session)
        for f in required_fields:
            if f.role:
                role_fields = session.party_fields.get(f.role, {})
                fs = role_fields.get(f.field_name)
                if not fs or fs.status != "ok":
                    is_ready = False
                    entry = missing_roles.get(f.role) or {
                        "missing_fields": [],
                        "role_label": role_labels.get(f.role, f.role),
                        "errors": {}
                    }
                    # Add field with label
                    field_label = party_field_labels.get(f.role, {}).get(f.field_name, f.field_name)
                    entry["missing_fields"].append({
                        "key": f.field_name,
                        "label": field_label,
                        "error": fs.error if fs else None
                    })
                    missing_roles[f.role] = entry
            else:
                fs = session.contract_fields.get(f.field_name)
                if not fs or fs.status != "ok":
                    is_ready = False
                    missing_contract.append(f.field_name)

        session.can_build_contract = is_ready
        session.state = SessionState.READY_TO_BUILD if is_ready else SessionState.COLLECTING_FIELDS
        template_id_local = session.template_id
        role_owners = session.role_owners.copy()

    # End of transaction block. Session is saved to disk.

    # Фільтрація списку missing під роль поточного клієнта
    if user_id and role_owners:
        current_role = next((r for r, uid in role_owners.items() if uid == user_id), None)
        if current_role:
            if current_role in missing_roles:
                missing_roles = {current_role: missing_roles[current_role]}
            else:
                missing_roles = {}

    if is_ready and template_id_local:
        try:
            result = await tool_build_contract_async(session_id, template_id_local)
            document_url = result.get("document_url") or result.get("file_path")
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("sync_session auto-build failed: %s", e)
            document_url = None

        resp = {
            "status": "ready",
            "missing": {
                "contract": missing_contract,
                "roles": missing_roles,
            },
            "session_id": session_id
        }
        if document_url:
            resp["document_url"] = document_url
        return resp

    return {
        "status": "partial" if not is_ready else "ready",
        "missing": {
            "contract": missing_contract,
            "roles": missing_roles,
        },
        "session_id": session_id
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ChatResponse:
    """
    Основна точка входу для діалогу.

    Перед передачею в LLM кожне повідомлення користувача проходить через
    PII-санітайзер: реальні значення (IBAN, картки, коди тощо) замінюються
    на типізовані теги [TYPE#N]. LLM працює лише з тегами, а не з PII.
    """
    _validate_session_id(req.session_id)
    # Handle reset request - clear conversation history before processing
    if req.reset:
        await conversation_store.areset(req.session_id)
        logger.info("Chat reset requested for session_id=%s", req.session_id)
    
    conv = await conversation_store.aget(req.session_id)
    user_id = resolve_user_id(x_user_id, authorization, allow_anonymous=True)
    if user_id:
        conv.user_id = user_id
    # Гарантуємо існування сесії (стан і поля зберігаються окремо)
    # get_or_create_session uses lock if creating, so it's safe.
    session = await aget_or_create_session(req.session_id)

    sanitized = sanitize_typed(req.message)
    conv.tags.update(sanitized["tags"])  # type: ignore[assignment]
    user_text = sanitized["sanitized_text"]  # type: ignore[assignment]

    # Зберігаємо останню мову користувача для i18n серверних відповідей
    try:
        conv.last_lang = detect_lang(req.message)
    except (AttributeError, TypeError):
        conv.last_lang = "uk"

    # Синхронізуємо локаль у Session для summary JSON
    # Use transactional update for locale
    try:
        # Run locale update in threadpool to avoid blocking event loop
        async with atransactional_session(req.session_id) as s:
            s.locale = conv.last_lang
    except (SessionNotFoundError, OSError):
        pass

    if not conv.messages:
        conv.messages = _build_initial_messages(user_text, req.session_id)
    else:
        conv.messages.append({"role": "user", "content": user_text})

    try:
        final_messages = await _tool_loop(conv.messages, conv)
    except RuntimeError as exc:
        logger.error("LLM error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Fallback: якщо користувач просить сформувати договір і всі обов'язкові поля готові,
    # просто повідомляємо, не генеруючи файл (LLM не викликає build_contract).
    last_user = last_user_message_text(final_messages)
    try:
        session = await aload_session(req.session_id)
    except SessionNotFoundError:
        session = None

    if session and session.can_build_contract and session.template_id:
        text_norm = (last_user or "").lower()
        if any(kw in text_norm for kw in ["сформуй", "створи", "згенеруй"]):
            logger.info(
                "fallback_build_skip: session_id=%s template_id=%s",
                req.session_id,
                session.template_id,
            )
            lang = conv.last_lang or "uk"
            if lang == "en":
                reply = (
                    "The contract is ready.\n"
                    "Please go to the All Contracts page to view or proceed."
                )
            else:
                reply = (
                    "Договір сформовано.\n"
                    "Перейдіть на сторінку \"Усі договори\", щоб переглянути або продовжити."
                )
            # Persist conversation before early return
            await conversation_store.asave(conv)
            return ChatResponse(session_id=req.session_id, reply=reply)

    pruned_messages = prune_messages(final_messages)
    conv.messages = pruned_messages
    reply_text = format_reply_from_messages(pruned_messages)

    # Persist conversation to Redis (if available)
    await conversation_store.asave(conv)

    return ChatResponse(session_id=req.session_id, reply=reply_text)


def _compute_status_effective(session: Session) -> str:
    """Compute canonical status for client consumption.
    
    This provides a single source of truth for contract status,
    so clients don't need to derive it from multiple fields.
    """
    if session.is_fully_signed:
        return "completed"
    return session.state.value


def _format_session_list(sessions: List[Session]) -> List[Dict[str, Any]]:
    """Format session list for API response (DRY helper)."""
    results = []
    for s in sessions:
        title = s.template_id
        if s.category_id:
            try:
                templates = list_templates(s.category_id)
                for t in templates:
                    if t.id == s.template_id:
                        title = t.name
                        break
            except (KeyError, ValueError, AttributeError):
                pass

        # Compute canonical status
        status_effective = _compute_status_effective(s)
        
        # Get required roles - prefer session.required_roles (set from category metadata)
        # Fallback to party_types for backward compatibility
        required_roles = s.required_roles if s.required_roles else list(s.party_types.keys())

        results.append({
            "session_id": s.session_id,
            "template_id": s.template_id,
            "title": title,
            "updated_at": s.updated_at,
            "state": s.state.value,
            "status_effective": status_effective,  # Canonical status for UI
            "is_signed": s.is_fully_signed,
            "required_roles": required_roles,  # Roles actually in this contract
            "signatures": s.signatures,  # Per-role signature status
        })
    return results


@app.get("/my-sessions")
async def get_my_sessions(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Get all sessions for the current user."""
    user_id = resolve_user_id(x_user_id, authorization, allow_anonymous=True)
    if not user_id:
        return []

    sessions = await alist_user_sessions(user_id)
    return _format_session_list(sessions)


@app.get("/users/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Повертає всі сесії/договори, в яких user_id прив'язаний до ролі (role_owners).
    Вимагає авторизації: тільки сам користувач може бачити свої сесії.
    """
    # Security: verify caller is the same user (prevent IDOR)
    caller_id = _require_user_id(x_user_id, authorization)
    if caller_id != user_id:
        security_logger.warning(
            "idor_attempt caller=%s target=%s endpoint=/users/{user_id}/sessions",
            caller_id,
            user_id,
        )
        raise HTTPException(
            status_code=403,
            detail="You can only access your own sessions."
        )

    sessions = await alist_user_sessions(user_id)
    return _format_session_list(sessions)


@app.get("/sessions/{session_id}/contract")
async def get_contract_info(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Get contract info including signing status and download URLs."""
    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    user_id = _require_user_id(x_user_id, authorization)

    check_session_access(session, user_id, require_participant=True, allow_owner=True)

    document_ready = session.state in {SessionState.BUILT, SessionState.COMPLETED}
    document_url = (
        f"/sessions/{session_id}/contract/download?user_id={user_id}"
        if session.state in {SessionState.BUILT, SessionState.COMPLETED, SessionState.READY_TO_SIGN}
        else None
    )
    preview_url = (
        f"/sessions/{session_id}/contract/preview?user_id={user_id}"
        if session.can_build_contract
        else None
    )

    client_roles = [role for role, uid in session.role_owners.items() if uid == user_id]

    # Отримуємо мітки ролей з метаданих категорії
    role_labels: Dict[str, str] = {}
    if session.category_id:
        category_def = cat_store.get(session.category_id)
        if category_def:
            try:
                meta = load_meta(category_def)
                role_labels = {
                    k: v.get("label", k) for k, v in (meta.get("roles") or {}).items()
                }
            except (FileNotFoundError, KeyError):
                pass

    # Compute canonical status and required roles
    status_effective = _compute_status_effective(session)
    # Prefer session.required_roles (set from category metadata)
    required_roles = session.required_roles if session.required_roles else list(session.party_types.keys())

    return {
        "session_id": session.session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "status": session.state.value,
        "status_effective": status_effective,  # Canonical status for UI
        "is_signed": session.is_fully_signed,
        "signatures": session.signatures,
        "required_roles": required_roles,  # Roles actually in this contract
        "client_roles": client_roles,
        "can_build_contract": session.can_build_contract,
        "document_ready": document_ready,
        "document_url": document_url,
        "preview_url": preview_url,
        "role_labels": role_labels,
    }


@app.get("/sessions/{session_id}/contract/preview", response_class=HTMLResponse)
async def preview_contract(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    user_id_query: Optional[str] = Query(None, alias="user_id"),
):
    """Preview contract as HTML."""
    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    caller_id = _require_user_id(x_user_id, authorization)
    if user_id_query and user_id_query != caller_id:
        security_logger.warning(
            "idor_attempt caller=%s target=%s endpoint=/sessions/{session_id}/contract/preview",
            caller_id,
            user_id_query,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    user_id = caller_id if settings.is_prod else (user_id_query or caller_id)
    # Превʼю доступне лише учасникам або власнику
    check_session_access(session, user_id, require_participant=True, allow_owner=True)

    if not session.template_id:
        raise HTTPException(status_code=400, detail="Template not selected")

    # Будуємо тимчасовий DOCX з плейсхолдерами (partial=True), конвертуємо у HTML
    # pylint: disable=import-outside-toplevel
    from backend.infra.storage.fs import output_document_path
    from backend.domain.documents.converter import convert_to_html

    try:
        build_result = await build_contract_async(session_id, session.template_id, partial=True)
        doc_path = Path(build_result["file_path"])
    except (OSError, ValueError, RuntimeError) as e:
        logger.error("Preview auto-build failed: %s", e)
        # fallback: спробувати існуючий драфт/фінальний файл
        final_doc = settings.filled_documents_root / f"contract_{session_id}.docx"
        draft_doc = output_document_path(session.template_id, session_id, ext="docx")
        doc_path = final_doc if final_doc.exists() else draft_doc
        if not Path(doc_path).exists():
            raise HTTPException(
                status_code=500, detail="Failed to build preview"
            ) from e

    try:
        html = convert_to_html(Path(doc_path))
    except (OSError, ValueError) as e:
        logger.error("Failed to convert preview to HTML: %s", e)
        raise HTTPException(status_code=500, detail="Failed to render preview") from e

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@app.get("/sessions/{session_id}/contract/download")
async def download_contract(
    session_id: str,
    final: bool = False,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    user_id_query: Optional[str] = Query(None, alias="user_id"),
):
    """Download contract document as DOCX."""
    from backend.infra.storage.fs import output_document_path  # pylint: disable=import-outside-toplevel

    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    caller_id = _require_user_id(x_user_id, authorization)
    if user_id_query and user_id_query != caller_id:
        security_logger.warning(
            "idor_attempt caller=%s target=%s endpoint=/sessions/{session_id}/contract/download",
            caller_id,
            user_id_query,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    user_id = caller_id if settings.is_prod else (user_id_query or caller_id)
    check_session_access(
        session, user_id, require_participant=True, allow_owner=True
    )

    # For final documents, require full signature and proper state
    # For draft documents (final=False), allow download without signature for preview/review
    if final:
        if not session.is_fully_signed and session.state != SessionState.COMPLETED:
            raise HTTPException(status_code=403, detail="Contract must be signed to download final version.")
        if session.state not in [SessionState.READY_TO_SIGN, SessionState.COMPLETED]:
            raise HTTPException(
                status_code=409, detail="Document has been modified. Please order again."
            )
        filename = f"contract_{session_id}.docx"
        path = settings.filled_documents_root / filename
        if not path.exists():
            raise HTTPException(status_code=404, detail="Final document not found")
    else:
        # Try to find temp document (Draft)
        if not session.template_id:
            raise HTTPException(status_code=400, detail="Template not selected")
        path = output_document_path(session.template_id, session_id, ext="docx")

        # If not exists, try to build on the fly
        if not path.exists():
            if session.can_build_contract:
                try:
                    await tool_build_contract_async(session_id, session.template_id)
                except (OSError, ValueError, RuntimeError) as exc:
                    raise HTTPException(
                        status_code=404, detail="Document not built yet"
                    ) from exc
            else:
                raise HTTPException(status_code=404, detail="Document not built yet")

    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"contract_{session_id}.docx",
    )


@app.post("/sessions/{session_id}/contract/sign")
async def sign_contract(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Sign contract for the current user's role."""
    _validate_session_id(session_id)
    user_id = _require_user_id(x_user_id, authorization)
    logger.info("Sign request: session_id=%s, user_id=%s", session_id, user_id)
    try:
        async with atransactional_session(session_id) as session:
            logger.info(
                "Session state: %s, filling_mode: %s, role_owners: %s, party_types: %s",
                session.state,
                session.filling_mode,
                session.role_owners,
                session.party_types,
            )

            # Якщо контракт ще не зібрано, але всі обов'язкові поля готові — пробуємо зібрати.
            # Дозволяємо підпис лише коли договір зібраний/готовий до підпису.
            if session.state not in [SessionState.BUILT, SessionState.READY_TO_SIGN]:
                if session.can_build_contract:
                    raise HTTPException(
                        status_code=409,
                        detail="Contract content has changed. Please rebuild before signing.",
                    )
                raise HTTPException(status_code=400, detail="Contract is not ready to be signed")

            # Identify role
            user_roles = [r for r, uid in (session.role_owners or {}).items() if uid == user_id]
            logger.info("Roles for signer %s: %s, filling_mode=%s", user_id, user_roles, session.filling_mode)

            signed_roles: List[str] = []

            # В режимі "full" творець заповнює і підписує за всіх
            # Підписуємо всі ролі, які ще не підписані
            # Використовуємо required_roles як джерело істини
            roles_to_sign = session.required_roles if session.required_roles else list(session.party_types.keys())
            if session.filling_mode == "full" and session.creator_user_id == user_id:
                for role in roles_to_sign:
                    if not session.signatures.get(role, False):
                        session.signatures[role] = True
                        signed_roles.append(role)
                logger.info("Full mode: creator %s signed all roles: %s", user_id, signed_roles)
            elif user_roles:
                for user_role in user_roles:
                    session.signatures[user_role] = True
                    signed_roles.append(user_role)
            else:
                # Multiple roles або власники інші — вимагаємо прив'язки ролі перед підписом.
                logger.error(
                    "Cannot determine signer: user_id=%s, party_types=%s, role_owners=%s",
                    user_id,
                    list(session.party_types.keys()),
                    session.role_owners,
                )
                raise HTTPException(
                    status_code=400,
                    detail="Set party context (role) before signing."
                )

            # Check if fully signed
            if session.is_fully_signed:
                session.state = SessionState.COMPLETED
            if signed_roles:
                session.history.append(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "type": "sign",
                        "user_id": user_id,
                        "roles": signed_roles,
                        "state": session.state.value,
                    }
                )

            # Capture state for broadcast
            is_signed = session.is_fully_signed
            signatures = session.signatures
            state = session.state.value

        sign_state = {"is_signed": is_signed, "signatures": signatures, "state": state}

        # Broadcast update
        await stream_manager.broadcast(session_id, {
            "type": "contract_update",
            "status": sign_state["state"],
            "is_signed": sign_state["is_signed"],
            "signatures": sign_state["signatures"]
        })

        return {
            "ok": True,
            "is_signed": sign_state["is_signed"],
            "signatures": sign_state["signatures"]
        }

    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc





@app.get("/sessions/{session_id}/schema")
async def get_session_schema(
    session_id: str,
    scope: str = Query("all", enum=["all", "required"]),
    data_mode: str = Query("values", enum=["values", "status", "none"]),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Універсальний ендпоінт для отримання структури форми та даних.
    
    - scope:
        - 'all': всі поля
        - 'required': тільки обов'язкові
    - data_mode:
        - 'values': повертає реальні значення (напр. "Іванов")
        - 'status': повертає true/false (чи заповнено)
        - 'none': не повертає даних, тільки метадані
    """

    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    user_id = _require_user_id(x_user_id, authorization)
    check_session_access(session, user_id, allow_owner=True)

    if not session.category_id:
        return {"sections": []}

    category_def = cat_store.get(session.category_id)
    if not category_def:
        raise HTTPException(status_code=404, detail="Category not found")

    meta = load_meta(category_def)
    roles = meta.get("roles", {})
    # main_role використовується лише для порядку відображення в UI
    main_role = next(iter(roles.keys()), None)

    response = {
        "session_id": session.session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "filling_mode": session.filling_mode if session.filling_mode else "partial",
        "main_role": main_role,
        "parties": [],
        "contract": {
            "title": "Умови договору",
            "subtitle": "Основні параметри угоди",
            "fields": []
        }
    }

    # Get party_modules for dynamic labels
    party_modules = meta.get("party_modules", {})

    # --- 1. Parties Section ---
    for role_key, role_info in roles.items():
        # Determine person type using centralized logic
        party_types = session.party_types or {}
        p_type = party_types.get(role_key)
        if not p_type:
            # Use default_person_type from role or first allowed type
            p_type = role_info.get("default_person_type")
            if not p_type:
                allowed = role_info.get("allowed_person_types", [])
                p_type = allowed[0] if allowed else next(iter(party_modules.keys()), "individual")

        # Get allowed types for selector - labels come from party_modules metadata
        allowed_types = []
        for t in role_info.get("allowed_person_types", list(party_modules.keys())):
            # Get label from party_modules metadata, fallback to type name
            module_info = party_modules.get(t, {})
            label = module_info.get("label", t)
            allowed_types.append({"value": t, "label": label})

        party_obj = {
            "role": role_key,
            "label": role_info.get("label", role_key),
            "person_type": p_type,
            "person_type_label": next(
                (x["label"] for x in allowed_types if x["value"] == p_type), p_type
            ),
            "allowed_types": allowed_types,
            "fields": [],
            "claimed_by": session.role_owners.get(role_key)
        }

        # Get fields for this role + type
        p_fields = list_party_fields(session.category_id, p_type)

        for pf in p_fields:
            # Filter by scope
            if scope == "required" and not pf.required:
                continue

            field_key = f"{role_key}.{pf.field}"

            # Determine value based on data_mode using FieldState status
            val = None
            party_fields = session.party_fields.get(role_key, {}) if session.party_fields else {}
            fs = party_fields.get(pf.field)
            if data_mode != "none":
                current_entry = session.all_data.get(field_key) if session.all_data else None
                raw_val = current_entry.get("current", "") if current_entry else ""

                if data_mode == "values":
                    val = raw_val if fs and fs.status == "ok" else None
                elif data_mode == "status":
                    val = bool(fs and fs.status == "ok")

            status = fs.status if fs else "empty"
            error_msg = fs.error if fs else None

            party_obj["fields"].append({
                "key": field_key,
                "field_name": pf.field,
                "label": pf.label,
                "placeholder": pf.label,  # Or add placeholder to metadata
                "required": pf.required,
                "value": val,
                "status": status,
                "error": error_msg,
            })

        response["parties"].append(party_obj)

    # --- 2. Contract Section ---
    entities = list_entities(session.category_id)
    for entity in entities:
        # Filter by scope
        if scope == "required" and not entity.required:
            continue

        # Determine value based on data_mode
        val = None
        fs = (session.contract_fields or {}).get(entity.field)
        if data_mode != "none":
            current_entry = session.all_data.get(entity.field) if session.all_data else None
            raw_val = current_entry.get("current", "") if current_entry else ""

            if data_mode == "values":
                val = raw_val if fs and fs.status == "ok" else None
            elif data_mode == "status":
                val = bool(fs and fs.status == "ok")

        status = fs.status if fs else "empty"
        error_msg = fs.error if fs else None

        response["contract"]["fields"].append({
            "key": entity.field,
            "field_name": entity.field,
            "label": entity.label,
            "placeholder": entity.label,
            "required": entity.required,
            "value": val,
            "status": status,
            "error": error_msg,
        })

    return response


@app.get("/sessions/{session_id}/requirements")
async def get_session_requirements(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Повертає список незаповнених обов'язкових полів для відображення на фронті.
    """
    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    user_id = _require_user_id(x_user_id, authorization)
    check_session_access(session, user_id, require_participant=True, allow_owner=True)

    missing = collect_missing_fields(session)
    # Фільтруємо missing за роллю клієнта, щоб не блокувати другорядні ролі
    if user_id and session.role_owners:
        current_role = next((r for r, uid in session.role_owners.items() if uid == user_id), None)
        if current_role:
            roles_missing = missing.get("roles", {})
            roles_detailed = missing.get("roles_detailed", {})

            if current_role in roles_missing:
                missing["roles"] = {current_role: roles_missing[current_role]}
            else:
                missing["roles"] = {}

            if current_role in roles_detailed:
                missing["roles_detailed"] = {current_role: roles_detailed[current_role]}
            else:
                missing["roles_detailed"] = {}

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "can_build_contract": session.can_build_contract,
        "is_ready_self": missing.get("is_ready_self", False),
        "is_ready_all": missing.get("is_ready_all", False),
        "missing": missing,
    }


@app.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """Get session history of field updates."""
    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    user_id = _require_user_id(x_user_id, authorization)
    check_session_access(session, user_id, require_participant=True, allow_owner=True)

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "updated_at": session.updated_at.isoformat(),
        "history": session.history,
    }


@app.post("/sessions/{session_id}/order")
async def order_contract(
    session_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Фіналізує документ:
    1. Перевіряє заповненість.
    2. Генерує DOCX у filled_documents.
    3. Змінює статус на READY_TO_SIGN.
    """
    import shutil  # pylint: disable=import-outside-toplevel

    _validate_session_id(session_id)
    try:
        session = await aload_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    user_id_local = _require_user_id(x_user_id, authorization)
    check_session_access(session, user_id_local, require_participant=True, allow_owner=True)

    if not session.template_id:
        raise HTTPException(status_code=400, detail="Template not selected")

    # Use scope="all" to check ALL parties' fields, not just current user's
    missing = collect_missing_fields(session, scope="all")
    if not missing.get("is_ready_all", False):
        # Provide clear message about which parties haven't filled their data
        if missing.get("is_ready_self", False):
            message = "Ваша частина заповнена, але інші сторони ще не заповнили свої дані."
        else:
            message = "Не всі обов'язкові поля заповнені."
        raise HTTPException(
            status_code=400,
            detail={
                "message": message,
                "missing": missing,
                "is_ready_self": missing.get("is_ready_self", False),
                "is_ready_all": missing.get("is_ready_all", False),
            },
        )

    # 1. Build contract (it checks required fields internally)
    try:
        result = await build_contract_async(session_id, session.template_id)
        temp_path = result["file_path"]
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "missing": collect_missing_fields(await aload_session(session_id)),
            },
        ) from e
    except (OSError, RuntimeError) as e:
        logger.error("Order failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error") from e

    # 2. Move to filled_documents
    # We want a stable path for the ordered document
    filename = f"contract_{session_id}.docx"
    final_path = settings.filled_documents_root / filename

    try:
        await run_sync(shutil.copy, temp_path, final_path)
    except (OSError, shutil.Error) as e:
        logger.error("Failed to save final document: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save document") from e

    # 3. Update session state
    async with atransactional_session(session_id) as session_inner:
        session_inner.state = SessionState.READY_TO_SIGN

    download_url_local = f"/sessions/{session_id}/contract/download?final=true"

    result = {
        "user_id": user_id_local,
        "download_url": download_url_local,
        "response": {
            "ok": True,
            "status": SessionState.READY_TO_SIGN.value,
            "download_url": download_url_local,
            "message": "Contract ordered successfully"
        }
    }

    # Broadcast update
    await stream_manager.broadcast(session_id, {
        "type": "contract_update",
        "status": SessionState.READY_TO_SIGN.value,
        "is_signed": False
    })

    return result["response"]
