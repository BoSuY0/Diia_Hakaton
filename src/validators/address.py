from __future__ import annotations


def normalize_address(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    # залишаємо регістр як є, лише чистимо зайві пробіли
    return cleaned
