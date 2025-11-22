from __future__ import annotations

from src.common.errors import ValidationError


def normalize_person_name(value: str) -> str:
    parts = [p for p in value.strip().split() if p]
    if len(parts) < 2:
        raise ValidationError("ПІБ має містити щонайменше ім'я та прізвище")
    capitalized = ["{}{}".format(p[0].upper(), p[1:].lower()) if len(p) > 1 else p.upper() for p in parts]
    return " ".join(capitalized)
