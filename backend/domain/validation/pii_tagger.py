"""PII (Personally Identifiable Information) detection and tagging utilities."""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, NamedTuple, Tuple

# Набір zero-width символів, які потрібно викинути при нормалізації
ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\ufeff"}

# Грубе наближення для плутаних кириличних/латинських символів
CONFUSABLES = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "І": "I",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "а": "A",
        "в": "B",
        "с": "C",
        "е": "E",
        "н": "H",
        "і": "I",
        "к": "K",
        "м": "M",
        "о": "O",
        "р": "P",
        "т": "T",
        "х": "X",
        "у": "Y",
    }
)

# Символи-шум, які оточують значення (пробіли, дефіси тощо)
NOISE = set(" \t\r\n-–—_.,:;·•()/\\[]{}<>|`'\"+*")

EMAIL_RE = re.compile(r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")
PHONE_RE = re.compile(
    r"(?:^|(?<=\D))(?:\+?38\s*\(?0\d{2}\)?[\s\-\.]*\d{3}[\s\-\.]*\d{2}[\s\-\.]*\d{2}"
    r"|0\d{2}[\s\-\.]*\d{3}[\s\-\.]*\d{2}[\s\-\.]*\d{2})(?=\D|$)"
)
# Дозволяємо коротші токени JWT-подібного формату (3+ символи у кожній частині),
# щоб не пропускати стислі/тестові токени.
JWT_RE = re.compile(r"\b[A-Za-z0-9-_]{3,}\.[A-Za-z0-9-_]{3,}\.[A-Za-z0-9-_]{3,}\b")
PKEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)

# Пріоритети типів (більше число — важливіший при конфліктах)
PRIORITY: Dict[str, int] = {
    "PRIVATE_KEY": 100,
    "JWT": 95,
    "IBAN": 90,
    "CARD": 90,
    "IPN": 85,
    "UNZR": 80,
    "PASSPORT_BOOK": 80,
    "PASSPORT_ID": 80,
    "PHONE": 70,
    "EMAIL": 70,
    "ADDRESS": 60,
    "DOB": 60,
    "NAME": 60,
    "FIELD": 55,
}


class Span(NamedTuple):
    """Represents a detected PII span in text."""

    start: int
    end: int
    typ: str
    prio: int


def _fold_char(ch: str) -> str | None:
    if ch in ZERO_WIDTH:
        return None
    ch = unicodedata.normalize("NFKC", ch)
    if unicodedata.category(ch).startswith("Nd"):
        try:
            return str(unicodedata.decimal(ch))
        except (TypeError, ValueError):
            pass
    ch = ch.translate(CONFUSABLES)
    if ch.isdigit():
        return ch
    if "A" <= ch <= "Z" or "a" <= ch <= "z":
        return ch.upper()
    return None


def _canon_with_map(text: str) -> Tuple[str, List[int]]:
    canon: List[str] = []
    mapping: List[int] = []
    for i, ch in enumerate(text):
        fc = _fold_char(ch)
        if fc is not None:
            canon.append(fc)
            mapping.append(i)
    return "".join(canon), mapping


def _map_back(mapping: List[int], a: int, b: int, src: str) -> Tuple[int, int]:
    i = mapping[a]
    j = mapping[b - 1] + 1
    while i > 0 and src[i - 1] in NOISE:
        i -= 1
    while j < len(src) and src[j : j + 1] in NOISE:
        j += 1
    return i, j


def _luhn_ok(digits: str) -> bool:
    s = 0
    for i, ch in enumerate(reversed(digits)):
        x = int(ch)
        if i % 2:
            x = x * 2 - (9 if x > 4 else 0)
        s += x
    return s % 10 == 0


def _iban_ok(iban: str) -> bool:
    if len(iban) < 4:
        return False
    s = iban[4:] + iban[:4]
    rem = 0
    for ch in s:
        if ch.isdigit():
            rem = (rem * 10 + int(ch)) % 97
        else:
            for c in str(ord(ch) - 55):
                rem = (rem * 10 + int(c)) % 97
    return rem == 1


def _rnokpp_ok(d10: str) -> bool:
    if len(d10) != 10 or not d10.isdigit():
        return False
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    ctrl = (sum(int(d) * weights[i] for i, d in enumerate(d10[:9])) % 11) % 10
    return ctrl == int(d10[-1])


def _det_iban(canon: str, mapping: List[int], src: str) -> List[Span]:
    out: List[Span] = []
    for m in re.finditer(r"UA[A-Z0-9]{27}", canon):
        raw = canon[m.start() : m.end()]
        if _iban_ok(raw):
            i, j = _map_back(mapping, m.start(), m.end(), src)
            out.append(Span(i, j, "IBAN", PRIORITY["IBAN"]))
    return out


def _det_card(canon: str, mapping: List[int], src: str) -> List[Span]:
    out: List[Span] = []
    for m in re.finditer(r"\d{13,19}", canon):
        digits = canon[m.start() : m.end()]
        if _luhn_ok(digits):
            i, j = _map_back(mapping, m.start(), m.end(), src)
            out.append(Span(i, j, "CARD", PRIORITY["CARD"]))
    return out


def _det_ipn(canon: str, mapping: List[int], src: str) -> List[Span]:
    out: List[Span] = []
    for m in re.finditer(r"\d{10}", canon):
        d = canon[m.start() : m.end()]
        i, j = _map_back(mapping, m.start(), m.end(), src)
        near = src[max(0, i - 30) : min(len(src), j + 30)].lower()
        if _rnokpp_ok(d) or any(
            k in near for k in ("іпн", "рнокпп", "ід.код", "tax id", "inn")
        ):
            out.append(Span(i, j, "IPN", PRIORITY["IPN"]))
    return out


def _det_passports(canon: str, mapping: List[int], src: str) -> List[Span]:
    out: List[Span] = []
    # Паспорт-книжечка: 2 символи + 6 цифр
    # Вимагаємо розділювачі, щоб не ловити шматки на кшталт "http://..."
    for m in re.finditer(r"(?<![A-Z0-9])[A-Z]{2}\d{6}(?!\d)", canon):
        i, j = _map_back(mapping, m.start(), m.end(), src)
        out.append(Span(i, j, "PASSPORT_BOOK", PRIORITY["PASSPORT_BOOK"]))
    # ID-картка: 9 цифр поруч із ключовими словами у сирому тексті
    for m in re.finditer(
        r"(?i)(документ\s*№|номер\s*паспорта|document\s*no)\s*[:#]?\s*([0-9\W]{9,14})",
        src,
    ):
        out.append(Span(m.start(), m.end(), "PASSPORT_ID", PRIORITY["PASSPORT_ID"]))
    return out


def _det_unzr(canon: str, mapping: List[int], src: str) -> List[Span]:
    out: List[Span] = [
        Span(*_map_back(mapping, *m.span(), src), "UNZR", PRIORITY["UNZR"])
        for m in re.finditer(r"\d{13}", canon)
    ]
    out += [
        Span(m.start(), m.end(), "UNZR", PRIORITY["UNZR"])
        for m in re.finditer(r"(?<!\d)\d{8}-\d{5}(?!\d)", src)
    ]
    return out


def _det_names(
    _canon: str, _mapping: List[int], src: str  # noqa: ARG001
) -> List[Span]:
    out: List[Span] = []
    # Heuristic: 3 capitalized words in Cyrillic (Surname Name Patronymic)
    upper = "А-ЯІЇЄҐ"
    lower = "а-яіїєґ''`"

    # Pattern: Capitalized word, space, Capitalized word, space, Capitalized word
    pattern = (
        fr"(?<![{lower}{upper}])[{upper}][{lower}]+\s+"
        fr"[{upper}][{lower}]+\s+[{upper}][{lower}]+(?![{lower}{upper}])"
    )

    for m in re.finditer(pattern, src):
        out.append(Span(m.start(), m.end(), "NAME", PRIORITY["NAME"]))

    return out


def _det_raw(src: str) -> List[Span]:
    """
    Detects raw PII in the given text.

    This function detects raw PII such as emails, phones, JWTs, and private keys.

    Args:
        src (str): The text to search for raw PII.

    Returns:
        List[Span]: A list of detected raw PII spans.
    """
    out: List[Span] = []
    for typ, rgx in (
        ("EMAIL", EMAIL_RE),
        ("PHONE", PHONE_RE),
        ("JWT", JWT_RE),
        ("PRIVATE_KEY", PKEY_RE),
    ):
        for m in rgx.finditer(src):
            out.append(Span(m.start(), m.end(), typ, PRIORITY[typ]))

    # Поля-мітки (маскуємо весь рядок)
    for typ, kw in (
        ("NAME", "ПІБ"),
        ("ADDRESS", "Адреса"),
        ("DOB", "Дата народження"),
    ):
        for m in re.finditer(fr"(?i){kw}\s*:.*", src):
            out.append(Span(m.start(), m.end(), typ, PRIORITY[typ]))
    return out


def _merge_typed(spans: List[Span]) -> List[Span]:
    """
    Зливає перекриваючіся спани, обираючи найпріоритетніший тип.
    """
    if not spans:
        return []
    events: List[Tuple[int, int, Span]] = []
    for s in spans:
        events.append((s.start, 1, s))
        events.append((s.end, -1, s))
    # Спочатку за позицією, потім за типом події/пріоритетом
    events.sort(key=lambda x: (x[0], -x[1] * x[2].prio))

    active: List[Span] = []
    merged_result: List[Span] = []
    last_pos: int | None = None

    def winner() -> Span | None:
        if not active:
            return None
        return max(active, key=lambda sp: (sp.prio, sp.end - sp.start))

    for pos, kind, sp in events:
        if last_pos is not None and pos > last_pos and active:
            w = winner()
            if w:
                # Якщо попередній спан закінчується тут і має той самий тип — об'єднуємо
                prev_span = merged_result[-1] if merged_result else None
                if prev_span and prev_span.end == last_pos and prev_span.typ == w.typ:
                    prev = merged_result.pop()
                    merged_result.append(Span(prev.start, pos, w.typ, w.prio))
                else:
                    merged_result.append(Span(last_pos, pos, w.typ, w.prio))
        if kind == 1:
            active.append(sp)
        else:
            if sp in active:
                active.remove(sp)
        last_pos = pos

    return merged_result


def sanitize_typed(text: str) -> Dict[str, object]:
    """
    Основна функція:
    - знаходить PII у тексті;
    - замінює їх на маркери [TYPE#N];
    - повертає:
        - sanitized_text: текст із тегами;
        - tags: { "[TYPE#N]": "<raw value>" };
        - spans: список знайдених ділянок у вихідному тексті.
    """
    canon, mapping = _canon_with_map(text)
    spans: List[Span] = []
    spans += _det_raw(text)
    spans += _det_iban(canon, mapping, text)
    spans += _det_card(canon, mapping, text)
    spans += _det_ipn(canon, mapping, text)
    spans += _det_passports(canon, mapping, text)
    spans += _det_unzr(canon, mapping, text)
    spans += _det_names(canon, mapping, text)

    spans = _merge_typed(spans)

    counters: Dict[str, int] = {}
    mapping_dict: Dict[str, str] = {}
    out_parts: List[str] = []
    last = 0

    for s in spans:
        out_parts.append(text[last : s.start])
        counters[s.typ] = counters.get(s.typ, 0) + 1
        tag = f"[{s.typ}#{counters[s.typ]}]"
        mapping_dict[tag] = text[s.start : s.end]
        out_parts.append(tag)
        last = s.end

    out_parts.append(text[last:])

    return {
        "sanitized_text": "".join(out_parts),
        "tags": mapping_dict,
        "spans": [s._asdict() for s in spans],
    }


if __name__ == "__main__":
    SAMPLE = (
        "Мій ІПН 123 456 7890; тел +38(093)123-45-67; картка 4444-3333-2222-1111; "
        "IBAN UA21 3223 1300 0002 6007 2335 6600 1; ПІБ: Іванов Іван"
    )
    result = sanitize_typed(SAMPLE)
    print("Sanitized:", result["sanitized_text"])
    print("Tags:")
    for k, v in result["tags"].items():
        print(" ", k, "=>", v)
