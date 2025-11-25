"""Address validation and normalization."""
from __future__ import annotations


def normalize_address(value: str) -> str:
    """Normalize address by cleaning extra whitespace."""
    cleaned = " ".join(value.strip().split())
    # залишаємо регістр як є, лише чистимо зайві пробіли
    return cleaned
