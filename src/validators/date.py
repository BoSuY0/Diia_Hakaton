from __future__ import annotations

import datetime as dt
import re

from src.common.errors import ValidationError


# Підтримка двох форматів:
# 1) ДД.ММ.РРРР / ДД-ММ-РРРР
# 2) РРРР-ММ-ДД (ISO)
DATE_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s*$")
DATE_ISO_RE = re.compile(r"^\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*$")


def normalize_date(value: str) -> str:
    """
    Нормалізує дату до формату DD.MM.YYYY.

    Рік має бути вказаний явно (2 або 4 цифри). Якщо рік відсутній —
    це вважається помилкою валідації, щоб уникнути неочікуваних
    підстановок поточного року.
    """
    iso = DATE_ISO_RE.match(value)
    if iso:
        year_i = int(iso.group(1))
        month_i = int(iso.group(2))
        day_i = int(iso.group(3))
    else:
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
