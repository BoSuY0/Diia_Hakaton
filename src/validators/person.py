from __future__ import annotations


def normalize_person_name(value: str) -> str:
    parts = [p for p in value.strip().split() if p]
    capitalized = ["{}{}".format(p[0].upper(), p[1:].lower()) if len(p) > 1 else p.upper() for p in parts]
    return " ".join(capitalized)

