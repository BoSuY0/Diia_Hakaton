from __future__ import annotations

import re

from src.common.errors import ValidationError


def _rnokpp_ok(code: str) -> bool:
    """
    Перевірка контрольної цифри РНОКПП (10 цифр).
    """
    if len(code) != 10 or not code.isdigit():
        return False
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    ctrl = (sum(int(d) * weights[i] for i, d in enumerate(code[:9])) % 11) % 10
    return ctrl == int(code[-1])


def _edrpou_ok(code: str) -> bool:
    """
    Перевірка контрольної цифри ЄДРПОУ.

    Для 8-значних кодів використовується два набори ваг:
    якщо перша сума дає 10 — застосовується другий набір.
    Для 10-значних — аналогічно, але з 9 цифрами в основі.
    """
    if not code.isdigit() or len(code) not in (8, 10):
        return False

    digits = [int(c) for c in code]

    if len(digits) == 8:
        weights1 = [1, 2, 3, 4, 5, 6, 7]
        weights2 = [3, 4, 5, 6, 7, 8, 9]
        ctrl_idx = 7
    else:
        weights1 = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        weights2 = [3, 4, 5, 6, 7, 8, 9, 10, 11]
        ctrl_idx = 9

    s1 = sum(d * w for d, w in zip(digits[:ctrl_idx], weights1))
    ctrl = s1 % 11
    if ctrl == 10:
        s2 = sum(d * w for d, w in zip(digits[:ctrl_idx], weights2))
        ctrl = s2 % 11
        if ctrl == 10:
            ctrl = 0

    return ctrl == digits[ctrl_idx]


def normalize_rnokpp(value: str) -> str:
    cleaned = re.sub(r"\D+", "", value)
    if len(cleaned) != 10:
        raise ValidationError("РНОКПП має містити рівно 10 цифр")
    if not _rnokpp_ok(cleaned):
        raise ValidationError("РНОКПП не пройшов перевірку контрольної цифри")
    return cleaned


def normalize_edrpou(value: str) -> str:
    """
    Перевірка ЄДРПОУ з контрольної цифрою (8 або 10 цифр).
    """
    cleaned = re.sub(r"\D+", "", value)
    if len(cleaned) not in (8, 10):
        raise ValidationError("ЄДРПОУ має містити 8 або 10 цифр")
    if not _edrpou_ok(cleaned):
        raise ValidationError("ЄДРПОУ не пройшов перевірку контрольної цифри")
    return cleaned
