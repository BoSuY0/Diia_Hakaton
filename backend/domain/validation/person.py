"""Person name validation and normalization."""
from __future__ import annotations

from backend.shared.errors import ValidationError


def normalize_person_name(value: str) -> str:
    """Normalize person name with proper capitalization.
    
    Accepts single word names for flexibility (e.g., company names, pseudonyms).
    For full names (ПІБ), users should enter at least first and last name.
    """
    parts = [p for p in value.strip().split() if p]
    if len(parts) < 1:
        raise ValidationError("Ім'я не може бути порожнім")
    capitalized = [
        f"{p[0].upper()}{p[1:].lower()}" if len(p) > 1 else p.upper()
        for p in parts
    ]
    return " ".join(capitalized)
