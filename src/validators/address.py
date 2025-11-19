from __future__ import annotations


def normalize_address(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    # basic capitalization of first letter
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]

