from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.agent.llm_client import chat_with_tools, load_system_prompt
from src.app.state import Conversation, conversation_store
from src.app.tool_router import (
    TOOL_DEFINITIONS,
    TOOL_CANON_BY_ALIAS,
    dispatch_tool,
    tool_build_contract,
    tool_find_category_by_query,
    tool_get_category_entities,
    tool_get_party_fields_for_session,
    tool_get_session_summary,
    tool_get_templates_for_category,
    tool_set_category,
    tool_set_template,
    tool_set_template,
    tool_upsert_field,
    tool_set_party_context,
)
from src.common.errors import SessionNotFoundError
from src.common.logging import get_logger
from src.common.config import settings
from src.documents.user_document import load_user_document
from src.sessions.store import get_or_create_session, load_session, save_session
from src.sessions.models import SessionState
from src.storage.fs import ensure_directories
from src.validators.pii_tagger import sanitize_typed


logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    # Run cleanup on startup
    try:
        from src.sessions.cleaner import clean_stale_sessions
        clean_stale_sessions()
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        
    logger.info("Server started")
    yield

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


class BuildContractRequest(BaseModel):
    template_id: str


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
        "set_category",
        "get_category_roles",
        "set_party_context",
        "get_templates_for_category",
        "get_category_entities",
        "set_template",
    ],
    "template_selected": [
        "route_message",
        "find_category_by_query",
        "set_category",
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
        "set_category",
        "set_party_context",
        "upsert_field",
        "get_session_summary",
        "set_filling_mode",
    ],
    "ready_to_build": [
        "route_message",
        "find_category_by_query",
        "set_category",
        "get_session_summary",
        "build_contract",
    ],
    "built": [
        "route_message",
        "find_category_by_query",
        "set_category",
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



def _get_effective_state(session_id: str, messages: List[Dict[str, Any]]) -> str:
    """
    Визначає поточний стан сесії для state-gating.

    До першого set_category в поточній розмові вважаємо станом "idle",
    навіть якщо у збереженій сесії він був інший.
    """
    try:
        session = load_session(session_id)
        return session.state.value
    except Exception:
        # Якщо сесію ще не створено або сталася помилка — вважаємо стан "idle".
        return "idle"


def _filter_tools_for_session(
    session_id: str, messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Формує підмножину TOOL_DEFINITIONS, дозволену на поточному етапі сесії.
    Використовує ToolRegistry для отримання визначень.
    """
    state = _get_effective_state(session_id, messages)
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




def _validate_message_sequence(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validates and fixes message sequence to ensure tool messages follow tool_calls.
    OpenAI API requires: assistant message with tool_calls → tool messages for each tool_call_id
    """
    validated = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        
        # System and user messages are always valid
        if role in ("system", "user"):
            validated.append(msg)
            i += 1
            continue
        
        # Assistant message
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # This assistant message has tool_calls, collect following tool messages
                expected_ids = {tc.get("id") if isinstance(tc, dict) else tc.id for tc in tool_calls}
                
                # Look ahead to find tool messages
                tool_msgs = []
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    tool_msg = messages[j]
                    tool_call_id = tool_msg.get("tool_call_id")
                    if tool_call_id in expected_ids:
                        tool_msgs.append(tool_msg)
                        expected_ids.discard(tool_call_id)
                    j += 1
                
                if not expected_ids:
                    # All tool calls have responses - valid sequence
                    validated.append(msg)
                    validated.extend(tool_msgs)
                    i = j
                else:
                    # Missing responses for some tool calls - drop the assistant message and partial tool messages
                    logger.warning(
                        "Dropping assistant message with missing tool responses. Missing IDs: %s",
                        expected_ids
                    )
                    # Skip the assistant message
                    i += 1
                    # Also skip the partial tool messages we found (since we are dropping the parent)
                    # The main loop will encounter them next, but since they are 'tool' role without 'assistant',
                    # the existing logic at line 458 (orphaned tool check) would handle them.
                    # However, since we advanced 'j', we can just set i=j to skip them efficiently?
                    # Wait, if we set i=j, we skip them. If we set i+=1, the main loop will process them as orphans.
                    # Let's set i=j to skip them explicitly as we know they belong to this dropped turn.
                    i = j
            else:
                # Regular assistant message without tool_calls
                validated.append(msg)
                i += 1
            continue
        
        # Tool message without preceding assistant tool_calls - skip it
        if role == "tool":
            logger.warning("Skipping orphaned tool message at index %d", i)
            i += 1
            continue
        
        # Unknown role - keep it
        validated.append(msg)
        i += 1
    
    return validated


def _tool_loop(messages: List[Dict[str, Any]], conv: Conversation) -> List[Dict[str, Any]]:
    """
    Tool-loop: виклик LLM, виконання тулів, захист від петель та мінімізація контексту.
    """
    max_iterations = 5
    last_tool_signature: Optional[str] = None

    for _ in range(max_iterations):
        tools = _filter_tools_for_session(conv.session_id, messages)
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

        state = _get_effective_state(conv.session_id, messages)
        # Не форсимо tools навіть на idle — модель сама вирішує,
        # чи відповідати текстом (OTHER), чи викликати тулли.
        require_tools = False
        # Дозволяємо моделі достатньо токенів, щоб повністю
        # перелічити шаблони/поля та дати пояснення.
        # Idle: коротка відповідь-вступ, інші стани — детальні пояснення.
        max_tokens = 96 if state == "idle" else 256

        # Validate message sequence to ensure tool messages follow tool_calls
        messages = _validate_message_sequence(messages)

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
                # Remove the assistant message with tool_calls since we won't provide tool outputs
                messages.pop()
                
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
            continue

        # No more tool calls, return messages
        break
    return messages


def _prune_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Обрізає історію діалогу для LLM, залишаючи лише необхідний контекст.
    Стратегія "Ковзне вікно" (Sliding Window):
    1. Завжди зберігаємо System Prompt (перше повідомлення).
    2. Зберігаємо останні N повідомлень (контекст поточної розмови).
    3. Все, що посередині — видаляємо.
    
    Це безпечно, оскільки стан сесії (заповнені поля) зберігається в БД,
    і модель отримує його через тул get_session_summary.
    """
    MAX_CONTEXT_MESSAGES = 30  # Increased from 12 to prevent losing user message during tool loops
    
    if len(messages) <= MAX_CONTEXT_MESSAGES + 1:
        return messages

    system_msg = messages[0]
    # Якщо перше повідомлення не system, про всяк випадок беремо як є, 
    # але зазвичай messages[0] це system.
    if system_msg.get("role") != "system":
        # Fallback: якщо структура порушена, просто ріжемо хвіст
        return messages[-MAX_CONTEXT_MESSAGES:]

    # Залишаємо System + останні N
    recent_messages = messages[-MAX_CONTEXT_MESSAGES:]
    
    # Важливо: переконатися, що ми не відрізали "tool_output" від "tool_call".
    # Якщо перше повідомлення в recent_messages — це "tool" (результат),
    # а попереднє було "assistant" (виклик), то ми розірвали пару.
    # Але для простоти і економії, зазвичай достатньо простого вікна.
    # Модель GPT досить стійка до втрати початку контексту, якщо є System Prompt.
    
    return [system_msg] + recent_messages


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
                    lines.append(f"- {name}")
            if entities:
                lines.append("Fields to fill:")
                for field, label, required in entities:
                    flag = "(required)" if required else "(optional)"
                    lines.append(f"- {label} ({field}) {flag}")
            
            if templates:
                lines.append("Please choose a template by providing its ID (e.g., act_transfer).")
            elif entities:
                lines.append("Please provide the required information in the format <field>=<value>.")
        else:
            if templates:
                lines.append("Доступні шаблони:")
                for tid, name in templates:
                    lines.append(f"- {name} ({tid})")
            if entities:
                lines.append("Потрібно заповнити такі поля:")
                for field, label, required in entities:
                    flag = "(обов'язкове)" if required else "(необов'язкове)"
                    lines.append(f"- {label} ({field}) {flag}")
            
            if templates:
                lines.append("Будь ласка, оберіть шаблон, вказавши його ID (наприклад, act_transfer).")
            elif entities:
                lines.append("Будь ласка, надайте необхідну інформацію.")
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


class SetPartyContextRequest(BaseModel):
    role: str
    person_type: str


@app.post("/sessions/{session_id}/party-context")
def set_session_party_context(session_id: str, req: SetPartyContextRequest) -> Dict[str, Any]:
    result = tool_set_party_context(
        session_id=session_id,
        role=req.role,
        person_type=req.person_type,
    )
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


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> Dict[str, Any]:
    try:
        return tool_get_session_summary(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/user-documents/{session_id}")
def get_user_document_api(session_id: str) -> Dict[str, Any]:
    """
    Повертає user-document JSON у форматі example_user_document.json
    для вказаної сесії.
    """
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


from fastapi.responses import StreamingResponse
import asyncio
from collections import defaultdict

class StreamManager:
    def __init__(self):
        self.connections: Dict[str, List[asyncio.Queue]] = defaultdict(list)

    async def connect(self, session_id: str) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self.connections[session_id].append(queue)
        return queue

    def disconnect(self, session_id: str, queue: asyncio.Queue):
        if session_id in self.connections:
            self.connections[session_id].remove(queue)
            if not self.connections[session_id]:
                del self.connections[session_id]

    async def broadcast(self, session_id: str, message: dict):
        if session_id not in self.connections:
            return
        
        # Create SSE formatted message
        data = json.dumps(message)
        msg = f"data: {data}\n\n"
        
        to_remove = []
        for queue in self.connections[session_id]:
            try:
                # Use put_nowait to avoid blocking if queue is full (though unlikely with infinite queue)
                # But more importantly, if we want to detect closed loops, we rely on client disconnecting.
                # Here we just put. If loop is closed, it might raise.
                queue.put_nowait(msg)
            except Exception:
                to_remove.append(queue)
        
        for queue in to_remove:
            self.disconnect(session_id, queue)

stream_manager = StreamManager()

@app.get("/sessions/{session_id}/stream")
async def stream_session_events(session_id: str):
    """
    Server-Sent Events endpoint for real-time session updates.
    """
    queue = await stream_manager.connect(session_id)
    
    async def event_generator():
        try:
            while True:
                # Wait for new messages
                msg = await queue.get()
                yield msg
        except asyncio.CancelledError:
            stream_manager.disconnect(session_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/fields")
async def upsert_session_field(session_id: str, req: UpsertFieldRequest) -> Dict[str, Any]:
    # Validation Logic
    # Validation Logic moved to tool_upsert_field


    result = tool_upsert_field(
        session_id=session_id,
        field=req.field,
        value=req.value,
        tags=None,
        role=req.role,
    )
    
    if result.get("ok", False):
        # Broadcast update to all listeners
        await stream_manager.broadcast(session_id, {
            "type": "field_update",
            "field": req.field,
            "value": req.value,
            "role": req.role,
            "client_id": req.client_id
        })

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


@app.get("/documents/{filename}")
def get_document(filename: str) -> FileResponse:
    safe_name = filename.split("/")[-1]
    path = settings.output_root / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        path=str(path),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=safe_name,
    )



class PartyData(BaseModel):
    person_type: str
    fields: Dict[str, str]


class SyncSessionRequest(BaseModel):
    category_id: Optional[str] = None
    template_id: Optional[str] = None
    parties: Dict[str, PartyData]


@app.post("/sessions/{session_id}/sync")
def sync_session(session_id: str, req: SyncSessionRequest) -> Dict[str, Any]:
    """
    Універсальний ендпоінт для пакетного оновлення даних сесії.
    Підтримує One-shot (все одразу) та Two-shot (по частинах) флоу.
    """
    from src.categories.index import store as category_store
    from src.common.errors import MetaNotFoundError
    from src.sessions.models import FieldState

    # 1. Load Session
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # 2. Set Category / Template if provided
    if req.category_id:
        res = tool_set_category(session_id, req.category_id)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("error"))
    
    if req.template_id:
        res = tool_set_template(session_id, req.template_id)
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail=res.get("error"))

    # Reload session to get updated category/template
    session = load_session(session_id)
    if not session.category_id:
        raise HTTPException(status_code=400, detail="Category not set")

    category = category_store.get(session.category_id)
    if not category:
        raise HTTPException(status_code=400, detail="Invalid category_id")

    category_meta = _load_meta(category)
    defined_roles = category_meta.get("roles", {})

    # 3. Process Parties
    for role_id, party_data in req.parties.items():
        if role_id not in defined_roles:
            # Skip unknown roles or raise error? Let's skip with warning or error.
            # For strict API, error is better.
            raise HTTPException(status_code=400, detail=f"Unknown role: {role_id}")
        
        # Validate person_type
        allowed_types = defined_roles[role_id].get("allowed_person_types", [])
        if party_data.person_type not in allowed_types:
             raise HTTPException(
                 status_code=400, 
                 detail=f"Invalid person_type '{party_data.person_type}' for role '{role_id}'"
             )

        # Set Context (Role + PersonType)
        # We use tool_set_party_context logic but manually to avoid context switching issues in loop
        # Actually, tool_set_party_context just updates session.role/person_type.
        # But here we want to update fields for a specific role, NOT necessarily the "current active user role".
        # However, our data model stores fields by role: session.party_fields[role]...
        # So we can directly update the fields.
        
        # Update party type mapping
        session.party_types[role_id] = party_data.person_type
        
        # Upsert fields
        for field_name, value in party_data.fields.items():
            # We can use tool_upsert_field but it works on "current role".
            # So we need to temporarily switch context or use a lower-level function.
            # Let's use a lower-level approach to be safe and explicit.
            
            # Ensure role dict exists
            if role_id not in session.party_fields:
                session.party_fields[role_id] = {}
            
            # Validate field against schema (optional but good)
            # For now, just save it.
            session.party_fields[role_id][field_name] = FieldState(status="ok")
            session.all_data[field_name] = value # Store value in flat all_data for template rendering
            
            # Also store in a way that distinguishes roles if field names collide?
            # Currently all_data is flat. If both parties have "name", we have a collision!
            # TODO: Fix collision in all_data. 
            # Usually templates use prefixes like "lessor_name", "lessee_name".
            # But the input JSON has "name" inside "lessor".
            # We need to map generic field names to template-specific names if needed.
            # OR, we assume the input JSON keys MUST match template placeholders?
            # If template has {{lessor_name}}, then input should be "lessor_name": "..."?
            # NO, the requirement is generic "name", "tax_code".
            # So we need a mapping strategy.
            # Convention: prefix with role_id + "_" ?
            # Let's check how `tool_upsert_field` does it.
            # It just puts into `all_data`.
            
            # CRITICAL FIX: Prefixing for flat dictionary
            flat_key = f"{role_id}_{field_name}"
            session.all_data[flat_key] = value
            # Also store original for fallback if unique
            session.all_data[field_name] = value

    save_session(session)

    # 4. Check Readiness
    # Check if ALL defined roles have their REQUIRED fields filled.
    missing_info = {}
    is_ready = True
    
    for role_id, role_def in defined_roles.items():
        # Check if role is present in session
        p_type = session.party_types.get(role_id)
        if not p_type:
            is_ready = False
            missing_info[role_id] = "missing_party"
            continue
            
        # Check required fields for this person_type
        party_modules = category_meta.get("party_modules", {})
        module = party_modules.get(p_type)
        if not module:
            continue
            
        role_missing_fields = []
        for field_def in module.get("fields", []):
            if field_def.get("required"):
                f_name = field_def["field"]
                # Check if we have it
                # We check session.party_fields[role_id][f_name].status == "ok"
                role_fields = session.party_fields.get(role_id, {})
                field_state = role_fields.get(f_name)
                if not field_state or field_state.status != "ok":
                    role_missing_fields.append(f_name)
        
        if role_missing_fields:
            is_ready = False
            missing_info[role_id] = {"missing_fields": role_missing_fields}

    # Check contract fields (if any)
    # ... (omitted for brevity, assuming contract fields come from one of the parties or separate)
    
    if is_ready and session.template_id:
        # Try to build
        try:
            # We need to ensure can_build_contract is True
            session.can_build_contract = True
            save_session(session)
            
            # Build
            result = tool_build_contract(session_id, session.template_id)
            return {
                "status": "ready",
                "document_url": result.get("document_url"),
                "session_id": session_id
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "session_id": session_id
            }
    
    return {
        "status": "partial",
        "missing": missing_info,
        "session_id": session_id
    }

def _load_meta(category) -> dict:
    # Helper to load meta (duplicated from index.py, should be imported but index.py is not fully exposed)
    # Better to expose _load_meta from index.py or use public API
    # We will use a temporary hack or fix index.py
    with category.meta_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/categories")
def get_categories():
    """
    Повертає список всіх доступних категорій договорів.
    """
    from src.categories.index import store as category_store
    categories = []
    for cat_id, cat in category_store.categories.items():
        categories.append({
            "id": cat.id,
            "label": cat.label,
            # "description": cat.description # Category object has no description
        })
    return categories


@app.get("/categories/{category_id}/templates")
def get_category_templates(category_id: str):
    """
    Повертає список шаблонів для вказаної категорії.
    """
    from src.categories.index import list_templates
    try:
        templates = list_templates(category_id)
        return [
            {"id": t.id, "name": t.name} # TemplateInfo object has no description
            for t in templates
        ]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    Основна точка входу для діалогу.

    Перед передачею в LLM кожне повідомлення користувача проходить через
    PII-санітайзер: реальні значення (IBAN, картки, коди тощо) замінюються
    на типізовані теги [TYPE#N]. LLM працює лише з тегами, а не з PII.
    """
    conv = conversation_store.get(req.session_id)
    # Гарантуємо існування сесії (стан і поля зберігаються окремо)
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
    try:
        session.locale = conv.last_lang
        save_session(session)
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
    return ChatResponse(session_id=req.session_id, reply=reply_text)


@app.get("/sessions/{session_id}/contract")
def get_contract_info(session_id: str) -> Dict[str, Any]:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "session_id": session.session_id,
        "category_id": session.category_id,
        "template_id": session.template_id,
        "status": session.state.value,
        "is_signed": session.is_signed,
        "can_build_contract": session.can_build_contract,
        "document_ready": session.state == "built",
        "document_url": f"/sessions/{session_id}/contract/download" if session.state == "built" else None,
        "preview_url": f"/sessions/{session_id}/contract/preview" if session.can_build_contract else None,
    }


@app.get("/sessions/{session_id}/contract/preview")
def preview_contract(session_id: str) -> FileResponse:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
def download_contract(session_id: str, final: bool = False):
    from src.storage.fs import output_document_path
    from src.common.config import settings
    from src.sessions.store import load_session

    try:
        session = load_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    if final:
        # Ensure session is actually in a final state to avoid serving outdated docs
        if session.state not in [SessionState.READY_TO_SIGN, SessionState.COMPLETED]:
             raise HTTPException(status_code=409, detail="Document has been modified. Please order again.")

        filename = f"contract_{session_id}.docx"
        path = settings.filled_documents_root / filename
        if not path.exists():
             raise HTTPException(status_code=404, detail="Final document not found")
    else:
        # Try to find temp document
        if not session.template_id:
             raise HTTPException(status_code=400, detail="Template not selected")
        path = output_document_path(session.template_id, session_id, ext="docx")
        
        # If not exists, try to build on the fly (if possible) or return 404
        if not path.exists():
             # Optional: try to build if ready
             if session.can_build_contract:
                 tool_build_contract(session_id, session.template_id)
             else:
                 raise HTTPException(status_code=404, detail="Document not built yet")

    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"contract_{session_id}.docx",
    )


@app.post("/sessions/{session_id}/contract/sign")
def sign_contract(session_id: str) -> Dict[str, Any]:
    try:
        session = load_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not session.can_build_contract:
        raise HTTPException(status_code=400, detail="Contract is not ready to be signed")
        
    session.is_signed = True
    save_session(session)
    return {"ok": True, "is_signed": True}


@app.get("/sessions/{session_id}/schema")
def get_session_schema(
    session_id: str,
    scope: str = Query("all", enum=["all", "required"]),
    data_mode: str = Query("values", enum=["values", "status", "none"])
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
            "fields": []
        }

        # Get fields for this role + type
        p_fields = list_party_fields(session.category_id, p_type)
        
        for pf in p_fields:
            # Filter by scope
            if scope == "required" and not pf.required:
                continue

            field_key = f"{role_key}.{pf.field}"
            
            # Determine value based on data_mode
            val = None
            if data_mode != "none":
                current_entry = session.all_data.get(field_key) if session.all_data else None
                raw_val = current_entry.get("current", "") if current_entry else ""
                
                if data_mode == "values":
                    val = raw_val
                elif data_mode == "status":
                    val = bool(raw_val) # True if not empty

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
        if data_mode != "none":
            current_entry = session.all_data.get(entity.field) if session.all_data else None
            raw_val = current_entry.get("current", "") if current_entry else ""
            
            if data_mode == "values":
                val = raw_val
            elif data_mode == "status":
                val = bool(raw_val)

        response["contract"]["fields"].append({
            "key": entity.field,
            "field_name": entity.field,
            "label": entity.label,
            "placeholder": entity.label,
            "required": entity.required,
            "value": val
        })

    return response


@app.post("/sessions/{session_id}/order")
def order_contract(session_id: str):
    """
    Фіналізує документ:
    1. Перевіряє заповненість.
    2. Генерує DOCX у filled_documents.
    3. Змінює статус на READY_TO_SIGN.
    """
    from src.documents.builder import build_contract
    from src.sessions.store import load_session, save_session
    from src.sessions.models import SessionState
    from src.common.config import settings
    import shutil
    
    try:
        session = load_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
        
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
# Trigger reload for metadata update (v3)
    # 3. Update session state
    session.state = SessionState.READY_TO_SIGN
    save_session(session)
    
    return {
        "ok": True,
        "status": session.state.value,
        "download_url": f"/sessions/{session_id}/contract/download?final=true",
        "message": "Contract ordered successfully"
    }
