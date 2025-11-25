"""IBAN validation and normalization for Ukrainian IBANs."""
from __future__ import annotations

import re

from backend.shared.errors import ValidationError


def _mod97(iban: str) -> bool:
    """
    Перевірка IBAN через MOD-97 (ISO 13616).
    """
    if len(iban) < 4:
        return False
    # Переносимо перші 4 символи в кінець
    rearranged = iban[4:] + iban[:4]
    remainder = 0
    for ch in rearranged:
        if ch.isdigit():
            remainder = (remainder * 10 + int(ch)) % 97
        else:
            # A=10, B=11, ...
            for c in str(ord(ch.upper()) - 55):
                remainder = (remainder * 10 + int(c)) % 97
    return remainder == 1


def normalize_iban_ua(value: str) -> str:
    """Normalize and validate Ukrainian IBAN (29 characters starting with UA).
    
    Returns empty string if value is empty (for optional fields).
    """
    cleaned = re.sub(r"\s+", "", value).upper()
    if not cleaned:
        return ""  # Allow empty for optional fields
    if not cleaned.startswith("UA"):
        raise ValidationError("IBAN має починатися з 'UA'")
    if len(cleaned) != 29:
        raise ValidationError("IBAN в Україні має містити 29 символів")
    if not re.fullmatch(r"[A-Z0-9]+", cleaned):
        raise ValidationError("IBAN може містити лише латинські літери та цифри")
    if not _mod97(cleaned):
        raise ValidationError("IBAN не пройшов перевірку за MOD-97, перевірте номер")
    return cleaned
