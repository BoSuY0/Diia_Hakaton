from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from backend.shared.errors import ValidationError


def normalize_money(value: str) -> str:
    """
    Normalize money to string '12345.67'.
    """
    cleaned = value.replace(" ", "").replace("\u00a0", "")
    # Replace comma with dot for decimals
    cleaned = cleaned.replace(",", ".")
    # Keep only digits and dot
    if not re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
        raise ValidationError("Сума має бути числом, наприклад 15000 або 15000.00")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValidationError("Не вдалося розпізнати суму, перевірте формат")

    return f"{amount:.2f}"

