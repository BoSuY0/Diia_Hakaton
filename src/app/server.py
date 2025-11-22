from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import uuid4
import inspect
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.agent.tools.registry import tool_registry
from src.agent.llm_client import chat_with_tools, load_system_prompt
from src.app.state import Conversation, conversation_store
from src.app.tool_router import (
    TOOL_DEFINITIONS,
    dispatch_tool,
    tool_build_contract,
    tool_find_category_by_query,
    tool_get_category_entities,
    tool_get_party_fields_for_session,
    tool_get_session_summary,
    tool_get_templates_for_category,
    tool_set_category,
    tool_set_template,
    tool_upsert_field,
    tool_set_party_context,
)
from src.common.errors import SessionNotFoundError
from src.common.logging import get_logger
from src.common.config import settings
from src.documents.user_document import load_user_document
from src.sessions.store import get_or_create_session, load_session, save_session, transactional_session
from src.sessions.models import Session, SessionState
from src.storage.fs import ensure_directories
from src.validators.pii_tagger import sanitize_typed


logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    
    import asyncio
    from src.sessions.cleaner import clean_stale_sessions, clean_abandoned_sessions
    
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
                    # Import stream_manager here to avoid circular/early import issues
                    # (It is defined in this file but later)
                    from src.app.server import stream_manager
                    
                    active_ids = set(stream_manager.connections.keys())

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
                    except Exception as e:
                        logger.error(f"Abandoned cleanup error/timeout: {e}")

                    try:
                        if inspect.iscoroutinefunction(clean_stale_sessions):
                            await asyncio.wait_for(clean_stale_sessions(), timeout=2.0)
                        else:
                            await asyncio.wait_for(
                                asyncio.to_thread(clean_stale_sessions),
                                timeout=2.0,
                            )
                    except Exception as e:
                        logger.error(f"Stale cleanup error/timeout: {e}")
                    
                except Exception as e:
                    logger.error(f"Background cleanup error: {e}")
                
                # Wait for 60 seconds or until stop signal
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=60)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            # Graceful exit on cancellation
            return

    cleanup_task = asyncio.create_task(cleanup_loop())
        
    logger.info("Server started")
    yield
    
    # Shutdown logic
    logger.info("Shutting down server...")
    stop_event.set()
    
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
        pass
    except Exception as e:
        logger.error(f"Error waiting for cleanup task: {e}")

    try:
        # Force close all SSE streams
        if 'stream_manager' in globals():
            await asyncio.wait_for(stream_manager.shutdown(), timeout=2.0)
    except Exception:
        pass
        
    logger.info("Server shutdown complete")

app = FastAPI(title="Contract Builder ChatBot", lifespan=lifespan)


# CORS для фронтенду / зовнішніх клієнтів
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str



class FindCategoryRequest(BaseModel):
    query: str


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str


class SetCategoryRequest(BaseModel):
    category_id: str




class UpsertFieldRequest(BaseModel):
    field: str
    value: Any
    role: Optional[str] = None
    client_id: Optional[str] = None


class SetTemplateRequest(BaseModel):
    template_id: str


class BuildContractRequest(BaseModel):
    template_id: str


class SetPartyContextRequest(BaseModel):
    role: str
    person_type: str


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
# TODO: Move this to a configuration or tool metadata
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
        "build_contract",
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
        # Re-build is allowed if still valid
        "build_contract",
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





def _inject_session_id(args_json: str, conv_session_id: str, tool_name: str) -> str:
    """
    Гарантує, що всі session-aware тулли працюють з поточною сесією,
    незалежно від того, який session_id повернула модель.
    """
    try:
        raw_args = json.loads(args_json or "{}")
    except Exception:
        raw_args = {}

    # Перекладаємо alias-ключі у канонічні імена параметрів.
    args: Dict[str, Any] = {}
    for key, value in raw_args.items():
        canon_key = PARAM_CANON_BY_ALIAS.get(key, key)
        args[canon_key] = value

    if tool_name in SESSION_AWARE_TOOLS:
        args["session_id"] = conv_session_id

    return json.dumps(args, ensure_ascii=False)


def _canonical_args(args_json: str) -> str:
    """
    Канонікалізація JSON-аргументів тулла для дедуплікації викликів.
    """
    try:
        parsed = json.loads(args_json or "{}")
    except Exception:
        return args_json or "{}"
    try:
        return json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except Exception:
        return args_json or "{}"


def _build_initial_messages(user_message: str, session_id: str) -> List[Dict[str, Any]]:
    system_prompt = load_system_prompt()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    return messages


def _initial_session_summary_text(session: Session) -> str:
    """
    Короткий знімок для першого відповіді: категорія/шаблон + наступний крок.
    """
    lines: List[str] = []
    try:
        from src.categories.index import store as category_store, list_templates
        cat_label = None
        tmpl_name = None

        if session.category_id:
            cat = category_store.get(session.category_id)
            cat_label = cat.label if cat else session.category_id

        if session.template_id and session.category_id:
            try:
                templates = list_templates(session.category_id)
                for t in templates:
                    if t.id == session.template_id:
                        tmpl_name = t.name
                        break
            except Exception:
                tmpl_name = session.template_id
        elif session.template_id:
            tmpl_name = session.template_id

        if cat_label:
            lines.append(f"Поточна категорія: {cat_label}")
        if tmpl_name:
            lines.append(f"Обраний шаблон: {tmpl_name}")

        if not lines:
            return ""

        # Підказка наступного кроку
        lines.append("Далі: вкажіть роль (Орендодавець / Орендар) та тип особи (фізична особа / ФОП / компанія).")
    except Exception:
        return ""

    return "\n".join(line for line in lines if line)


def _last_user_message_text(messages: List[Dict[str, Any]]) -> str:
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


def _detect_lang(text: str) -> str:
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


def _min_spec(tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Legacy helper. The registry now handles minification.
    """
    # This logic is now in ToolRegistry.get_definitions(minified=True)
    # We keep this just in case we need to process raw dicts, but ideally we shouldn't.
    return tool



def _as_compact_text(tool_name: str, result_text: str) -> str:
    """
    Deprecated. The tool itself now returns formatted text (VSC or JSON).
    """
    return result_text



def _get_effective_state(
    session_id: str,
    messages: List[Dict[str, Any]],
    *,
    has_category_tool: bool = False,
) -> str:
    """
    Визначає поточний стан сесії для state-gating.

    До першого set_category в поточній розмові вважаємо станом "idle",
    навіть якщо у збереженій сесії він був інший.
    """
    try:
        session = load_session(session_id)
    except Exception:
        # Якщо сесію ще не створено або сталася помилка — вважаємо стан "idle".
        return "idle"

    # Якщо в історії поточної розмови ще не було set_category, але сесія вже має категорію/шаблон,
    # використовуємо фактичний стан сесії, щоб не зависати в idle після рестарту чи REST-створення.
    if not has_category_tool and session.category_id:
        return session.state.value

    if not has_category_tool:
        return "idle"

    return session.state.value


def _filter_tools_for_session(
    session_id: str,
    messages: List[Dict[str, Any]],
    *,
    has_category_tool: bool = False,
) -> List[Dict[str, Any]]:
    """
    Формує підмножину TOOL_DEFINITIONS, дозволену на поточному етапі сесії.
    Використовує ToolRegistry для отримання визначень.
    """
    state = _get_effective_state(
        session_id,
        messages,
        has_category_tool=has_category_tool,
    )
    allowed = set(ALLOWED_TOOLS_BY_STATE.get(state, []))
    
    # Get all definitions from registry (minified by default)
    from src.agent.tools.registry import tool_registry
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



def _tool_loop(messages: List[Dict[str, Any]], conv: Conversation) -> List[Dict[str, Any]]:
    """
    Tool-loop: виклик LLM, виконання тулів, захист від петель та мінімізація контексту.
    """
    max_iterations = 5
    last_tool_signature: Optional[str] = None

    for _ in range(max_iterations):
        tools = _filter_tools_for_session(
            conv.session_id,
            messages,
            has_category_tool=conv.has_category_tool,
        )
        try:
            tool_names = [
                t.get("function", {}).get("name", "<unknown>") for t in tools
            ]
            logger.info("toolset_for_state session_id=%s tools=%s", conv.session_id, tool_names)
        except Exception:
            logger.info(
                "toolset_for_state session_id=%s tools_count=%d",
                conv.session_id,
                len(tools),
            )

        state = _get_effective_state(
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

        try:
            response = chat_with_tools(
                messages,
                tools,
                require_tools=require_tools,
                max_completion_tokens=max_tokens,
            )
        except RuntimeError as exc:
            raise
        choice = response.choices[0]
        message = choice.message

        # Дедуплікація tool_calls у межах одного повідомлення (по канонічному імені тулла)
        dedup_calls: Dict[str, Any] = {}
        if message.tool_calls:
            for tc in message.tool_calls:
                canon_name = TOOL_CANON_BY_ALIAS.get(tc.function.name, tc.function.name)
                key = f"{canon_name}:{_canonical_args(tc.function.arguments)}"
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

                tool_args = _inject_session_id(
                    raw_args,
                    conv.session_id,
                    tool_name,
                )
                logger.info("Executing tool %s", tool_name)
                tool_result = dispatch_tool(
                    tool_name,
                    tool_args,
                    tags=getattr(conv, "tags", None),
                    client_id=None,  # client_id is only known for HTTP endpoints, not chat
                )

                if tool_name == "set_category":
                    # Після явного set_category вважаємо, що категорія зафіксована
                    # в межах цієї розмови (для state-gating).
                    try:
                        conv.has_category_tool = True
                    except Exception:
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
            pruned = _prune_messages(messages)
            messages = pruned
            conv.messages = pruned
            conv.messages = pruned
            continue

        # No more tool calls, return messages
        break
    return messages


def _prune_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Обрізає історію діалогу для LLM, залишаючи лише необхідний контекст.
    Важливо: зберігаємо лише узгоджені пари assistant tool_calls ↔ tool responses,
    щоб уникнути orphaned tool messages після обрізки.
    """
    MAX_CONTEXT_MESSAGES = 12
    
    if len(messages) <= MAX_CONTEXT_MESSAGES + 1:
        return _strip_orphan_tools(messages)

    system_msg = messages[0]
    if system_msg.get("role") != "system":
        return _strip_orphan_tools(messages[-MAX_CONTEXT_MESSAGES:])

    recent_messages = messages[-MAX_CONTEXT_MESSAGES:]
    return [system_msg] + _strip_orphan_tools(recent_messages)


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
                except Exception:
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


def _format_reply_from_messages(messages: List[Dict[str, Any]]) -> str:
    # Повертаємо останнє непорожнє текстове повідомлення асистента.
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

    last_user = _last_user_message_text(messages)
    lang = _detect_lang(last_user) if last_user else "uk"

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
def healthz() -> Dict[str, Any]:
    """
    Простіший health-check сервера.

    Повертає статус сервера та ознаку наявності залежності для роботи з DOCX.
    """
    try:
        from docx import Document  # type: ignore

        # Перевіряємо, що можна створити порожній документ
        Document()
        docx_ok = True
    except Exception:
        docx_ok = False

    return {
        "status": "ok",
        "docx_ok": docx_ok,
    }


@app.get("/categories")
def list_categories() -> List[Dict[str, str]]:
    from src.categories.index import store as category_store

    categories = []
    for category in category_store.categories.values():
        categories.append({"id": category.id, "label": category.label})
    return categories


@app.post("/categories/find")
def find_category(req: FindCategoryRequest) -> Dict[str, Any]:
    return tool_find_category_by_query(req.query)


@app.get("/categories/{category_id}/templates")
def get_category_templates(category_id: str) -> Dict[str, Any]:
    try:
        return tool_get_templates_for_category(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/categories/{category_id}/entities")
def get_category_entities(category_id: str) -> Dict[str, Any]:
    try:
        return tool_get_category_entities(category_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/sessions/{session_id}/party-fields")
def get_session_party_fields(session_id: str) -> Dict[str, Any]:
    """
    Повертає перелік полів сторони договору (name, address, тощо)
    для поточної сесії, виходячи з role + person_type.
    """
    result = tool_get_party_fields_for_session(session_id=session_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions/{session_id}/party-context")
async def set_session_party_context(
    session_id: str, 
    req: SetPartyContextRequest,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
) -> Dict[str, Any]:
    # If header is missing, try to use a cookie or something?
    # Or just fail if strict?
    # Let's use x_client_id if present.
    
    result = tool_set_party_context(
        session_id=session_id,
        role=req.role,
        person_type=req.person_type,
        _context={"client_id": x_client_id} # Pass context
    )
    if result.get("ok", False):
        await stream_manager.broadcast(session_id, {
            "type": "schema_update",
            "reason": "party_context_changed"
        })

    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    from src.sessions.store import get_or_create_session, generate_readable_id
    
    # Якщо ID не передано, генеруємо читабельний.
    # За замовчуванням префікс "new", але якщо клієнт знає шаблон,
    # він може передати його як частину логіки (поки що просто new).
    session_id = req.session_id or generate_readable_id("new")
    session = get_or_create_session(session_id, user_id=req.user_id)
    return CreateSessionResponse(session_id=session.session_id)


def check_session_access(
    session: Session,
    client_id: Optional[str],
    *,
    require_participant: bool = False,
):
    """
    Enforces strict access control:
    - If session is full (all roles taken), only participants can access.
    - If session is not full, anyone can access (to claim a role).
    - If require_participant=True, enforce participant header even if session is not full.
    """
    # If participant-level access is required, enforce header presence early
    if require_participant and not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")

    # 1. If no category, we can't determine roles, so allow access (setup phase)
    if not session.category_id:
        # If some roles are already claimed, still enforce participant ownership
        if session.party_users and client_id not in session.party_users.values():
            raise HTTPException(status_code=403, detail="You are not a participant of this session.")
        return

    # 2. Load metadata to count roles
    from src.categories.index import store as category_store
    cat = category_store.get(session.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # Reuse _load_meta helper (defined below, but python allows forward ref if function called later? No.)
    # We need to move _load_meta up or duplicate logic.
    # Let's duplicate logic for now or move _load_meta.
    # Or just use the one in server.py if it's available in scope.
    # It is defined at module level.
    try:
        meta = _load_meta(cat)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load category metadata")

    roles = meta.get("roles", {})
    expected_roles_count = len(roles) if roles else max(len(session.party_types), len(session.party_users))
    
    # 3. Check if full
    # We count unique users? Or just occupied roles?
    # party_users is Role -> UserID.
    occupied_roles = len(session.party_users)
    is_full = expected_roles_count > 0 and occupied_roles >= expected_roles_count
    
    if require_participant or is_full or session.party_users:
        # Session is full OR participant-only endpoint OR someone already claimed a role.
        if not client_id:
            raise HTTPException(status_code=401, detail="Missing X-Client-ID")

        # Check if client is a participant
        if session.party_users and client_id not in session.party_users.values():
            raise HTTPException(status_code=403, detail="You are not a participant of this session.")
        pass


@app.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
) -> Dict[str, Any]:
    try:
        # We need to load session to check access.
        # tool_get_session_summary loads it internally.
        # But we need to check BEFORE returning.
        # So we load it here first.
        from src.sessions.store import load_session
        session = load_session(session_id)
        
        check_session_access(session, x_client_id)
        
        return tool_get_session_summary(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/user-documents/{session_id}")
def get_user_document_api(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
) -> Dict[str, Any]:
    """
    Повертає user-document JSON у форматі example_user_document.json
    для вказаної сесії.
    """
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not x_client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")

    check_session_access(session, x_client_id, require_participant=True)

    try:
        return load_user_document(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/category")
def set_session_category(session_id: str, req: SetCategoryRequest) -> Dict[str, Any]:
    result = tool_set_category(session_id=session_id, category_id=req.category_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


@app.post("/sessions/{session_id}/template")
def set_session_template(session_id: str, req: SetTemplateRequest) -> Dict[str, Any]:
    result = tool_set_template(session_id=session_id, template_id=req.template_id)
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


class SetFillingModeRequest(BaseModel):
    mode: str


@app.post("/sessions/{session_id}/filling-mode")
def set_session_filling_mode(
    session_id: str, 
    req: SetFillingModeRequest,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
) -> Dict[str, Any]:
    from src.app.tool_router import tool_registry
    tool = tool_registry.get("set_filling_mode")
    if not tool:
        raise HTTPException(status_code=500, detail="Tool not found")
    
    result = tool.execute(
        {"session_id": session_id, "mode": req.mode}, 
        {"client_id": x_client_id}
    )
    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return result


from fastapi.responses import StreamingResponse
import asyncio
from collections import defaultdict

# Custom StreamingResponse that swallows cancellation during shutdown
class SafeStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except asyncio.CancelledError:
            logger.info("StreamingResponse cancelled (shutdown/disconnect); closing gracefully")
            # Swallow cancellation to avoid noisy shutdown trace
            return

class StreamManager:
    def __init__(self):
        self.connections: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    async def connect(self, session_id: str, client_id: Optional[str]) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self.connections[session_id].append({"queue": queue, "client_id": client_id})
        return queue

    def disconnect(self, session_id: str, queue: asyncio.Queue):
        if session_id not in self.connections:
            return
        filtered = [c for c in self.connections[session_id] if c.get("queue") is not queue]
        if filtered:
            self.connections[session_id] = filtered
        else:
            del self.connections[session_id]

    async def broadcast(self, session_id: str, message: dict, exclude_client_id: Optional[str] = None):
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
                cid = conn.get("client_id")
                if exclude_client_id and cid and cid == exclude_client_id:
                    continue
                if queue is None:
                    continue
                # Use put_nowait to avoid blocking if queue is full (though unlikely with infinite queue)
                queue.put_nowait(msg)
            except Exception:
                if queue:
                    to_remove.append(queue)
        
        for queue in to_remove:
            self.disconnect(session_id, queue)

    async def shutdown(self):
        """
        Gracefully close all connections.
        """
        # Iterate over a copy of items because disconnect() might modify the dictionary
        for session_id, conns in list(self.connections.items()):
            for conn in conns:
                queue = conn.get("queue")
                if queue is None:
                    continue
                try:
                    queue.put_nowait(None)
                except Exception:
                    pass

stream_manager = StreamManager()

@app.get("/sessions/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
):
    """
    Server-Sent Events endpoint for real-time session updates.
    """
    client_id = x_client_id or client_id_query
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")

    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    check_session_access(session, client_id, require_participant=True)

    queue = await stream_manager.connect(session_id, client_id)
    
    async def event_generator():
        try:
            while True:
                # Wait for new messages
                msg = await queue.get()
                if msg is None:
                    # Server shutdown signal
                    break
                yield msg
        except asyncio.CancelledError:
            # Client disconnected or server shutting down
            # We just exit silently
            pass
        except Exception as e:
            logger.error(f"SSE stream error for {session_id}: {e}")
        finally:
             stream_manager.disconnect(session_id, queue)

    return SafeStreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/fields")
async def upsert_session_field(
    session_id: str, 
    req: UpsertFieldRequest,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
) -> Dict[str, Any]:
    # Якщо у сесії вже є учасники — вимагаємо автентифікацію через заголовок.
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if session.party_users and not x_client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")

    result = tool_upsert_field(
        session_id=session_id,
        field=req.field,
        value=req.value,
        tags=None,
        role=req.role,
        _context={"client_id": x_client_id}
    )
    
    if result.get("ok", False):
        sender_id = x_client_id or req.client_id
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
            exclude_client_id=sender_id,
        )

    # Для REST-інтерфейсу явні помилки користувача сигналізуємо через 400
    if not result.get("ok", False) and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/sessions/{session_id}/build")
def build_contract(session_id: str, req: BuildContractRequest) -> Dict[str, Any]:
    from src.common.errors import MetaNotFoundError
    from src.sessions.store import load_session

    try:
        # Переконуємось, що сесія існує (для коректного 404)
        load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return tool_build_contract(session_id=session_id, template_id=req.template_id)
    except MetaNotFoundError as exc:
        # Невідома категорія/шаблон для цієї сесії
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # Наприклад, відсутні обов'язкові поля
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class PartyData(BaseModel):
    person_type: str
    fields: Dict[str, str]


class SyncSessionRequest(BaseModel):
    category_id: Optional[str] = None
    template_id: Optional[str] = None
    parties: Dict[str, PartyData]


@app.post("/sessions/{session_id}/sync")
def sync_session(
    session_id: str,
    req: SyncSessionRequest,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
) -> Dict[str, Any]:
    """
    Універсальний ендпоінт для пакетного оновлення даних сесії.
    Підтримує One-shot (все одразу) та Two-shot (по частинах) флоу.
    """
    from src.categories.index import store as category_store, list_templates
    from src.common.errors import MetaNotFoundError
    from src.sessions.models import FieldState
    from src.sessions.store import get_or_create_session

        # Use transactional session for the whole sync process

    # Якщо сесія ще не створена — створюємо файл-чернетку
    get_or_create_session(session_id)

    # Access control: only participants can sync when roles are claimed/full.
    client_id = x_client_id or client_id_query
    if not client_id:
         raise HTTPException(status_code=401, detail="Missing X-Client-ID")
    session_for_acl = load_session(session_id)
    check_session_access(session_for_acl, client_id, require_participant=True)

    # Під час тестів метадані можуть змінюватися на льоту — перезавантажуємо індекс
    category_store.load()
    
    with transactional_session(session_id) as session:

        # 2. Set Category / Template if provided
        if req.category_id:
            if req.category_id not in category_store.categories:
                 raise HTTPException(status_code=400, detail=f"Category {req.category_id} not found")
            from src.sessions.actions import set_session_category
            # Якщо категорія змінюється — робимо повне очищення стану.
            if session.category_id != req.category_id:
                ok = set_session_category(session, req.category_id)
                if not ok:
                    raise HTTPException(status_code=400, detail="Failed to set category")

        if req.template_id:
            templates = {t.id for t in list_templates(session.category_id)} if session.category_id else set()
            if templates and req.template_id not in templates:
                 raise HTTPException(status_code=400, detail="Template does not belong to category")
            session.template_id = req.template_id
            session.state = SessionState.TEMPLATE_SELECTED

        if not session.category_id:
            raise HTTPException(status_code=400, detail="Category not set")

        category = category_store.get(session.category_id)
        if not category:
            raise HTTPException(status_code=400, detail="Invalid category_id")

        category_meta = _load_meta(category)
        defined_roles = category_meta.get("roles", {})

        # Import service
        from src.services.session import update_session_field

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
            
            # Upsert fields using SERVICE
            for field_name, value in party_data.fields.items():
                ok, error, _ = update_session_field(
                    session=session,
                    field=field_name,
                    value=value,
                    role=role_id,
                    context={"client_id": client_id, "source": "api"},
                )
                # We ignore errors here? Or should we report them?
                # The sync endpoint usually expects valid data or "best effort".
                # If we want to report errors, we should collect them.
                # For now, we proceed, but the field state will be 'error'.

        # 4. Check Readiness using shared schema helper
        from src.services.fields import get_required_fields
        missing_contract: list[str] = []
        missing_roles: Dict[str, Any] = {}
        is_ready = True

        required_fields = get_required_fields(session)
        for f in required_fields:
            if f.role:
                role_fields = session.party_fields.get(f.role, {})
                fs = role_fields.get(f.field_name)
                if not fs or fs.status != "ok":
                    is_ready = False
                    entry = missing_roles.get(f.role) or {"missing_fields": []}
                    entry["missing_fields"].append(f.field_name)
                    missing_roles[f.role] = entry
            else:
                fs = session.contract_fields.get(f.field_name)
                if not fs or fs.status != "ok":
                    is_ready = False
                    missing_contract.append(f.field_name)
    
        contract_only_missing = (not is_ready and missing_contract and not missing_roles)

        session.can_build_contract = is_ready
        session.state = SessionState.READY_TO_BUILD if is_ready else SessionState.COLLECTING_FIELDS

    # End of transaction block. Session is saved to disk.
    
    if is_ready and session.template_id:
        try:
            result = tool_build_contract(session_id, session.template_id)
            document_url = result.get("document_url") or result.get("file_path")
        except Exception as e:
            logger.error(f"sync_session auto-build failed: {e}")
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

def _load_meta(category) -> dict:
    # Helper to load meta (duplicated from index.py, should be imported but index.py is not fully exposed)
    # Better to expose _load_meta from index.py or use public API
    # We will use a temporary hack or fix index.py
    with category.meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    Основна точка входу для діалогу.

    Перед передачею в LLM кожне повідомлення користувача проходить через
    PII-санітайзер: реальні значення (IBAN, картки, коди тощо) замінюються
    на типізовані теги [TYPE#N]. LLM працює лише з тегами, а не з PII.
    """
    conv = conversation_store.get(req.session_id)
    is_first_turn = not conv.messages
    # Гарантуємо існування сесії (стан і поля зберігаються окремо)
    # get_or_create_session uses lock if creating, so it's safe.
    session = get_or_create_session(req.session_id)

    sanitized = sanitize_typed(req.message)
    conv.tags.update(sanitized["tags"])  # type: ignore[assignment]
    user_text = sanitized["sanitized_text"]  # type: ignore[assignment]

    # Зберігаємо останню мову користувача для i18n серверних відповідей
    try:
        conv.last_lang = _detect_lang(req.message)
    except Exception:
        conv.last_lang = "uk"

    # Синхронізуємо локаль у Session для summary JSON
    # Use transactional update for locale
    try:
        with transactional_session(req.session_id) as s:
             s.locale = conv.last_lang
    except Exception:
        pass

    if not conv.messages:
        conv.messages = _build_initial_messages(user_text, req.session_id)
    else:
        conv.messages.append({"role": "user", "content": user_text})

    try:
        final_messages = _tool_loop(conv.messages, conv)
    except RuntimeError as exc:
        logger.error("LLM error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Fallback: якщо модель не викликала build_contract, але користувач явно
    # просить сформувати договір і всі обов'язкові поля заповнені — будуємо
    # договір на бекенді без додаткового кроку моделі.
    last_user = _last_user_message_text(final_messages)
    try:
        session = load_session(req.session_id)
    except Exception:
        session = None

    if session and session.can_build_contract and session.template_id:
        text_norm = (last_user or "").lower()
        if any(kw in text_norm for kw in ["сформуй", "створи", "згенеруй"]):
            logger.info(
                "fallback_build: session_id=%s template_id=%s",
                req.session_id,
                session.template_id,
            )
            result = tool_build_contract(
                session_id=req.session_id,
                template_id=session.template_id,
            )
            filename = result.get("filename") or result.get("file_path")
            lang = conv.last_lang or "uk"
            if lang == "en":
                reply = (
                    "The contract has been generated.\n"
                    f"You can download it as: {filename}"
                )
            else:
                reply = (
                    "Договір сформовано.\n"
                    f"Його можна завантажити як файл: {filename}"
                )
            return ChatResponse(session_id=req.session_id, reply=reply)

    pruned_messages = _prune_messages(final_messages)
    conv.messages = pruned_messages
    reply_text = _format_reply_from_messages(pruned_messages)

    # Додаємо стислий знімок сесії у першому повідомленні розмови
    if is_first_turn:
        try:
            session = load_session(req.session_id)
        except Exception:
            session = None
        if session:
            intro = _initial_session_summary_text(session)
            if intro:
                reply_text = f"{intro}\n{reply_text}" if reply_text else intro

    return ChatResponse(session_id=req.session_id, reply=reply_text)


@app.get("/my-sessions")
def get_my_sessions(x_client_id: Optional[str] = Header(None, alias="X-Client-ID")):
    if not x_client_id:
        return []
    from src.sessions.store import list_user_sessions
    sessions = list_user_sessions(x_client_id)
    
    from src.categories.index import list_templates
    
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
             except:
                 pass
        
        results.append({
            "session_id": s.session_id,
            "template_id": s.template_id,
            "title": title,
            "updated_at": s.updated_at,
            "state": s.state.value,
            "is_signed": s.is_fully_signed
        })
    return results


@app.get("/sessions/{session_id}/contract")
def get_contract_info(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
) -> Dict[str, Any]:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client_id = x_client_id or client_id_query
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")

    check_session_access(session, client_id, require_participant=True)

    document_ready = session.state in {SessionState.BUILT, SessionState.COMPLETED}
    document_url = (
        f"/sessions/{session_id}/contract/download"
        if session.state in {SessionState.BUILT, SessionState.COMPLETED, SessionState.READY_TO_SIGN}
        else None
    )
    if document_url and client_id:
        document_url = f"{document_url}?client_id={client_id}"

    preview_url = f"/sessions/{session_id}/contract/preview" if session.can_build_contract else None
    if preview_url and client_id:
        preview_url = f"{preview_url}?client_id={client_id}"

    client_roles = [role for role, uid in session.party_users.items() if uid == client_id]

    return {
        "session_id": session.session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "status": session.state.value,
        "is_signed": session.is_fully_signed,
        "signatures": session.signatures,
        "client_roles": client_roles,
        "can_build_contract": session.can_build_contract,
        "document_ready": document_ready,
        "document_url": document_url,
        "preview_url": preview_url,
    }


@app.get("/sessions/{session_id}/contract/preview")
def preview_contract(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
) -> FileResponse:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client_id = x_client_id or client_id_query
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")
    check_session_access(session, client_id, require_participant=True)

    if not session.template_id:
         raise HTTPException(status_code=400, detail="Template not selected")
    
    from src.storage.fs import output_document_path
    path = output_document_path(session.template_id, session_id, ext="docx")
    
    # Always try to build with partial=True for preview
    # We import build_contract directly to bypass LLM tool wrapper and use partial arg
    from src.documents.builder import build_contract as build_contract_direct
    try:
        build_contract_direct(session_id, session.template_id, partial=True)
    except Exception as e:
        logger.error(f"Preview build failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
             
    # HTML Preview (Fast, Cross-Platform)
    from src.documents.converter import convert_to_html
    try:
        html_content = convert_to_html(path)
    except Exception as e:
        logger.error(f"HTML conversion failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate preview")

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)


@app.get("/sessions/{session_id}/contract/download")
def download_contract(
    session_id: str,
    final: bool = False,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
):
    from src.storage.fs import output_document_path
    from src.common.config import settings
    from src.sessions.store import load_session

    try:
        session = load_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    client_id = x_client_id or client_id_query
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")
    check_session_access(session, client_id, require_participant=True)

    # Enforce security: strictly forbid downloading if not signed (except for specific roles/cases not defined here).
    # The test verify_contract_api expects 403 if not signed.
    if not session.is_fully_signed and session.state != SessionState.COMPLETED:
        raise HTTPException(status_code=403, detail="Contract must be signed to download.")

    if final:
        # Ensure session is actually in a final state
        if session.state not in [SessionState.READY_TO_SIGN, SessionState.COMPLETED]:
            raise HTTPException(status_code=409, detail="Document has been modified. Please order again.")

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
                    tool_build_contract(session_id, session.template_id)
                except Exception:
                    raise HTTPException(status_code=404, detail="Document not built yet")
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
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
) -> Dict[str, Any]:
    logger.info(f"Sign request: session_id={session_id}, client_id={x_client_id}")
    if not x_client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")
    try:
        with transactional_session(session_id) as session:
            logger.info(f"Session state: {session.state}, filling_mode: {session.filling_mode}, party_users: {session.party_users}, party_types: {session.party_types}")
            
            # Якщо контракт ще не зібрано, але всі обов'язкові поля готові — пробуємо зібрати.
            if session.state not in [SessionState.BUILT, SessionState.READY_TO_SIGN] and session.can_build_contract and session.template_id:
                try:
                    tool_build_contract(session.session_id, session.template_id)
                    session.state = SessionState.BUILT
                except Exception as e:
                    logger.error(f"Auto-build before sign failed: {e}")
                    raise HTTPException(status_code=400, detail="Contract must be generated before signing.")

            # Дозволяємо підпис лише коли договір зібраний/готовий до підпису.
            if session.state not in [SessionState.BUILT, SessionState.READY_TO_SIGN]:
                raise HTTPException(status_code=400, detail="Contract is not ready to be signed")

            # Identify role
            user_role = None
            logger.info(f"Looking for role for client_id={x_client_id} in party_users={session.party_users}")
            for r, uid in session.party_users.items():
                logger.info(f"Checking role={r}, uid={uid}, match={uid == x_client_id}")
                if uid == x_client_id:
                    user_role = r
                    logger.info(f"Found role={user_role} for client_id={x_client_id}")
                    break
            
            logger.info(f"After search: user_role={user_role}, filling_mode={session.filling_mode}")
            
            # If no specific role found (or no client_id), and we are in strict mode, we might fail.
            # But for MVP, if we can't identify, maybe we sign ALL if it's a single user session?
            # Or if filling_mode is FULL?
            
            from src.common.enums import FillingMode
            signed_roles: List[str] = []
            
            if session.filling_mode == FillingMode.FULL:
                # У режимі FULL дозволяємо клієнту підписати всі ролі, які або пусті, або належать йому.
                for role in session.party_types:
                    owner = session.party_users.get(role)
                    if owner and owner != x_client_id:
                        logger.error(f"Role {role} owned by {owner}, client {x_client_id} cannot sign all")
                        raise HTTPException(status_code=403, detail="You cannot sign for other participants.")
                    # Прив'язуємо роль до клієнта, якщо ще не зайнята
                    session.party_users.setdefault(role, x_client_id)
                    session.signatures[role] = True
                    signed_roles.append(role)
            elif user_role:
                session.signatures[user_role] = True
                signed_roles.append(user_role)
            else:
                # Cannot determine who to sign for
                # Якщо одна роль визначена у схемі і ще не зайнята — призначаємо її клієнту та підписуємо.
                if len(session.party_types) == 1 and not session.party_users:
                    single_role = list(session.party_types.keys())[0]
                    session.party_users[single_role] = x_client_id
                    session.signatures[single_role] = True
                    logger.warning(f"Signing for single role {single_role} for client {x_client_id}")
                    signed_roles.append(single_role)
                else:
                    # Multiple roles або власники інші — вимагаємо прив’язки ролі перед підписом.
                    logger.error(
                        f"Cannot determine signer: client_id={x_client_id}, user_role={user_role}, "
                        f"party_types={list(session.party_types.keys())}, party_users={session.party_users}"
                    )
                    raise HTTPException(
                        status_code=400, 
                        detail="Set party context (role) before signing."
                    )

            # Check if fully signed
            if session.is_fully_signed:
                session.state = SessionState.COMPLETED
            if signed_roles:
                session.sign_history.append(
                    {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "client_id": x_client_id,
                        "roles": signed_roles,
                        "state": session.state.value,
                    }
                )

            # Capture state for broadcast
            is_signed = session.is_fully_signed
            signatures = session.signatures
            state = session.state.value

        # Broadcast update
        await stream_manager.broadcast(session_id, {
            "type": "contract_update",
            "status": state,
            "is_signed": is_signed,
            "signatures": signatures
        })

        return {
            "ok": True, 
            "is_signed": is_signed, 
            "signatures": signatures
        }

    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc





@app.get("/sessions/{session_id}/schema")
def get_session_schema(
    session_id: str,
    scope: str = Query("all", enum=["all", "required"]),
    data_mode: str = Query("values", enum=["values", "status", "none"]),
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID")
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
    try:
        session = load_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    check_session_access(session, x_client_id)

    if not session.category_id:
        return {"sections": []}

    from src.categories.index import list_party_fields, store as cat_store, _load_meta, list_entities
    
    category_def = cat_store.get(session.category_id)
    if not category_def:
        raise HTTPException(status_code=404, detail="Category not found")
        
    meta = _load_meta(category_def)
    roles = meta.get("roles", {})

    
    response = {
        "session_id": session.session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "filling_mode": session.filling_mode if session.filling_mode else "partial",
        "parties": [],
        "contract": {
            "title": "Умови договору",
            "subtitle": "Основні параметри угоди",
            "fields": []
        }
    }

    # --- 1. Parties Section ---
    for role_key, role_info in roles.items():
        # Determine person type (default to individual if not set)
        party_types = session.party_types or {}
        p_type = party_types.get(role_key, "individual")
        
        # Get allowed types for selector
        allowed_types = []
        for t in role_info.get("allowed_person_types", ["individual"]):
            # Simple mapping for labels, ideally should be in metadata
            label_map = {
                "individual": "Фізична особа",
                "fop": "ФОП",
                "company": "Юридична особа"
            }
            allowed_types.append({"value": t, "label": label_map.get(t, t)})

        party_obj = {
            "role": role_key,
            "label": role_info.get("label", role_key),
            "person_type": p_type,
            "person_type_label": next((x["label"] for x in allowed_types if x["value"] == p_type), p_type),
            "allowed_types": allowed_types,
            "fields": [],
            "claimed_by": session.party_users.get(role_key)
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
            fs = (session.party_fields.get(role_key, {}) if session.party_fields else {}).get(pf.field)
            if data_mode != "none":
                current_entry = session.all_data.get(field_key) if session.all_data else None
                raw_val = current_entry.get("current", "") if current_entry else ""
                
                if data_mode == "values":
                    val = raw_val if fs and fs.status == "ok" else None
                elif data_mode == "status":
                    val = bool(fs and fs.status == "ok")

            party_obj["fields"].append({
                "key": field_key,
                "field_name": pf.field,
                "label": pf.label,
                "placeholder": pf.label, # Or add placeholder to metadata
                "required": pf.required,
                "value": val
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

        response["contract"]["fields"].append({
            "key": entity.field,
            "field_name": entity.field,
            "label": entity.label,
            "placeholder": entity.label,
            "required": entity.required,
            "value": val
        })

    return response


@app.get("/sessions/{session_id}/history")
def get_session_history(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
) -> Dict[str, Any]:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client_id = x_client_id or client_id_query
    check_session_access(session, client_id, require_participant=True)

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "updated_at": session.updated_at.isoformat(),
        "all_data": session.all_data,
        "sign_history": session.sign_history,
    }


@app.post("/sessions/{session_id}/order")
async def order_contract(
    session_id: str,
    x_client_id: Optional[str] = Header(None, alias="X-Client-ID"),
    client_id_query: Optional[str] = Query(None, alias="client_id"),
):
    """
    Фіналізує документ:
    1. Перевіряє заповненість.
    2. Генерує DOCX у filled_documents.
    3. Змінює статус на READY_TO_SIGN.
    """
    from src.documents.builder import build_contract
    from src.sessions.store import load_session, save_session, transactional_session
    from src.sessions.models import SessionState
    from src.common.config import settings
    import shutil
    
    try:
        session = load_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    client_id = x_client_id or client_id_query
    if not client_id:
        raise HTTPException(status_code=401, detail="Missing X-Client-ID")
    check_session_access(session, client_id, require_participant=True)
        
    if not session.template_id:
        raise HTTPException(status_code=400, detail="Template not selected")
    
    # 1. Build contract (it checks required fields internally)
    try:
        # build_contract returns path to temp file
        result = build_contract(session_id, session.template_id)
        temp_path = result["file_path"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Order failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    # 2. Move to filled_documents
    # We want a stable path for the ordered document
    filename = f"contract_{session_id}.docx"
    final_path = settings.filled_documents_root / filename
    
    try:
        shutil.copy(temp_path, final_path)
    except Exception as e:
        logger.error(f"Failed to save final document: {e}")
        raise HTTPException(status_code=500, detail="Failed to save document")

    # 3. Update session state
    with transactional_session(session_id) as session:
        session.state = SessionState.READY_TO_SIGN
    
    # Broadcast update
    await stream_manager.broadcast(session_id, {
        "type": "contract_update",
        "status": SessionState.READY_TO_SIGN.value,
        "is_signed": False
    })
    
    download_url = f"/sessions/{session_id}/contract/download?final=true"
    if client_id:
        download_url = f"{download_url}&client_id={client_id}"

    return {
        "ok": True,
        "status": SessionState.READY_TO_SIGN.value,
        "download_url": download_url,
        "message": "Contract ordered successfully"
    }
