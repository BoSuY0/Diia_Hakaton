"""
Email validation module.
"""
from __future__ import annotations

import re

from backend.shared.errors import ValidationError


# Simple email regex pattern (RFC 5322 simplified)
EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(value: str) -> str:
    """
    Validates and normalizes an email address.
    
    Args:
        value: The email string to validate.
        
    Returns:
        Normalized (lowercased, trimmed) email address.
        
    Raises:
        ValidationError: If the email format is invalid.
    """
    if not value or not value.strip():
        raise ValidationError("Email не може бути порожнім.")

    email = value.strip().lower()

    if not EMAIL_PATTERN.match(email):
        raise ValidationError("Невірний формат email.")

    return email
