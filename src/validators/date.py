from __future__ import annotations

import datetime as dt
import re

from src.common.errors import ValidationError


DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s*$")


def normalize_date(value: str) -> str:
    """
    Нормалізує дату до формату DD.MM.YYYY.

    Рік має бути вказаний явно (2 або 4 цифри). Якщо рік відсутній —
    це вважається помилкою валідації, щоб уникнути неочікуваних
    підстановок поточного року.
    """
    m = DATE_RE.match(value)
    if not m:
        raise ValidationError(
            "Очікую дату у форматі ДД.ММ.РРРР, наприклад 01.09.2025"
        )

    day, month, year = m.groups()
    day_i = int(day)
    month_i = int(month)

    if year is None:
        raise ValidationError(
            "Будь ласка, вкажіть рік у форматі ДД.ММ.РРРР, наприклад 01.09.2025"
        )
    else:
        if len(year) == 2:
            year_i = 2000 + int(year)
        else:
            year_i = int(year)

    try:
        normalized = dt.date(year_i, month_i, day_i)
    except ValueError:
        raise ValidationError("Такої дати не існує, перевірте день та місяць")

    return normalized.strftime("%d.%m.%Y")
