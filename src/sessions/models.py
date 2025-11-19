from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionState(str, Enum):
    IDLE = "idle"
    CATEGORY_SELECTED = "category_selected"
    TEMPLATE_SELECTED = "template_selected"
    COLLECTING_FIELDS = "collecting_fields"
    READY_TO_BUILD = "ready_to_build"
    BUILT = "built"


@dataclass
class FieldState:
    # Статус окремого поля у сесії (без значення PII).
    # Значення поля зберігаються в агрегаторі all_data.
    status: str = "empty"  # empty | ok | error
    error: Optional[str] = None


@dataclass
class Session:
    session_id: str
    user_id: Optional[str] = None

    # Локаль користувача для серверних відповідей (uk/en/…)
    locale: str = "uk"

    # Обрана категорія та шаблон
    category_id: Optional[str] = None
    template_id: Optional[str] = None

    # Роль у договорі (lessor / lessee / …) та тип особи (individual / fop / company)
    # role/person_type — це поточний контекст користувача (хто зараз редагує).
    role: Optional[str] = None
    person_type: Optional[str] = None
    
    # Типи осіб для кожної ролі: Role -> PersonType (напр. {"lessor": "company", "lessee": "individual"})
    party_types: Dict[str, str] = field(default_factory=dict)

    state: SessionState = SessionState.IDLE

    # Поля сторони (party_fields) тепер вкладені: Role -> FieldName -> FieldState
    party_fields: Dict[str, Dict[str, FieldState]] = field(default_factory=dict)
    contract_fields: Dict[str, FieldState] = field(default_factory=dict)

    # Чи вже можна будувати договір (всі required поля зі status=ok)
    can_build_contract: bool = False

    # Чи підписано договір
    is_signed: bool = False

    # Прогрес заповнення (агреговані лічильники/флаги)
    progress: Dict[str, Any] = field(default_factory=dict)

    # Маршрутизація діалогу: останній route та історія
    routing: Dict[str, Any] = field(default_factory=dict)

    # Агрегатор усіх даних по полях (chat/API) з історією
    all_data: Dict[str, Any] = field(default_factory=dict)
