from __future__ import annotations

from collections import defaultdict
from typing import Dict

_requests_total: Dict[str, int] = defaultdict(int)


def _key(method: str, path: str, status: int | str) -> str:
    return f"{method.upper()} {path} {status}"


def record_request(method: str, path: str, status: int) -> None:
    try:
        _requests_total[_key(method, path, status)] += 1
        _requests_total[_key(method, "ALL", status)] += 1
        _requests_total[_key("ALL", "ALL", status)] += 1
    except Exception:
        # Best effort; never break the main flow
        pass


def snapshot() -> Dict[str, int]:
    return dict(_requests_total)
