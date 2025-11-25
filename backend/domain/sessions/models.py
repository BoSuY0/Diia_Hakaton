from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

class SessionState(str, Enum):
    IDLE = "idle"
    CATEGORY_SELECTED = "category_selected"
    TEMPLATE_SELECTED = "template_selected"
    COLLECTING_FIELDS = "collecting_fields"
    READY_TO_BUILD = "ready_to_build"
    BUILT = "built"
    READY_TO_SIGN = "ready_to_sign"  # Документ сформовано і готово до підпису
    COMPLETED = "completed"          # Документ підписано обома сторонами


@dataclass
class FieldState:
    # Статус окремого поля у сесії (без значення PII).
    # Значення поля зберігаються в агрегаторі all_data.
    status: str = "empty"  # empty | ok | error
    error: Optional[str] = None


@dataclass
class Session:
    session_id: str
    creator_user_id: Optional[str] = None
    role_owners: Dict[str, str] = field(default_factory=dict)
    
    # Час останнього оновлення (для очищення старих чернеток)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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

    # Підписи сторін: Role -> Signed (True/False)
    signatures: Dict[str, bool] = field(default_factory=dict)

    # Глобальна історія подій (оновлення полів, підписи)
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_fully_signed(self) -> bool:
        # Перевіряємо, чи всі сторони, визначені в party_types, підписали
        if not self.party_types:
            return False
        return all(self.signatures.get(role, False) for role in self.party_types)

    # Прогрес заповнення (агреговані лічильники/флаги)
    progress: Dict[str, Any] = field(default_factory=dict)

    # Маршрутизація діалогу: останній route та історія
    routing: Dict[str, Any] = field(default_factory=dict)

    # Агрегатор усіх даних по полях (chat/API) з історією
    all_data: Dict[str, Any] = field(default_factory=dict)

    # Режим заповнення: partial (тільки своя роль) або full (заповнення за всіх)
    filling_mode: str = "partial"

    @property
    def party_users(self) -> Dict[str, str]:
        """
        Backward-compatible alias for role owners mapping.
        """
        return self.role_owners

    @party_users.setter
    def party_users(self, value: Dict[str, str]) -> None:
        self.role_owners = value or {}
