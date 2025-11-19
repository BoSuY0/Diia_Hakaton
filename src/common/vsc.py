from __future__ import annotations

from typing import Iterable, List


def _esc(s: str) -> str:
    """
    Екранує службові символи для VSC:
    - '|' → '\\|'
    - '\n' → '\\n'
    """
    return s.replace("|", r"\|").replace("\n", r"\n")


def row(*cols: object) -> str:
    return "|".join(_esc(str(c)) for c in cols)


def block(header: str, rows: Iterable[Iterable[object]]) -> str:
    lines: List[str] = [header]
    for r in rows:
        lines.append(row(*r))
    return "\n".join(lines)


def vsc_find_category(res: dict) -> str:
    """
    CATEGORY
    <category_id>|<label>   або   CATEGORY\nNONE
    """
    if not res.get("category_id"):
        return "CATEGORY\nNONE"
    return block("CATEGORY", [[res.get("category_id", ""), res.get("label", "")]])


def vsc_templates(res: dict) -> str:
    """
    TEMPLATES
    <id>|<name>
    """
    return block(
        "TEMPLATES",
        (
            (t.get("id", ""), t.get("name", ""))
            for t in res.get("templates", [])
        ),
    )


def vsc_entities(res: dict) -> str:
    """
    ENTITIES
    <field>|<label>|<type>|<required 0/1>
    """
    rows = []
    for e in res.get("entities", []):
        rows.append(
            (
                e.get("field", ""),
                e.get("label", ""),
                e.get("type", "text"),
                1 if e.get("required") else 0,
            )
        )
    return block("ENTITIES", rows)


def vsc_simple_ok(op: str, res: dict) -> str:
    """
    OK
    <op>|<id>
    де op ∈ {set_category, set_template}
    """
    key = "category_id" if op == "set_category" else "template_id"
    return block("OK", [[op, res.get(key, "")]])


def vsc_upsert_result(res: dict) -> str:
    """
    FIELD_STATUS
    <field>|<status>|<error or ->|<state>|<can_build 0/1>
    """
    return block(
        "FIELD_STATUS",
        [
            [
                res.get("field", ""),
                res.get("status", ""),
                (res.get("error") or "-"),
                res.get("state", ""),
                1 if res.get("can_build_contract") else 0,
            ]
        ],
    )


def vsc_summary(res: dict) -> str:
    """
    SUMMARY
    state|<state>
    can_build|<0/1>
    FIELDS
    <field>|<status>|<error or ->
    """
    head = block(
        "SUMMARY",
        [
            ["state", res.get("state", "")],
            ["can_build", 1 if res.get("can_build_contract") else 0],
        ],
    )
    fields = block(
        "FIELDS",
        (
            (f.get("field", ""), f.get("status", ""), (f.get("error") or "-"))
            for f in res.get("fields", [])
        ),
    )
    return head + "\n" + fields


def vsc_built(res: dict) -> str:
    """
    BUILT
    <filename>|<file_path>|<mime>
    """
    return block(
        "BUILT",
        [
            [
                res.get("filename", ""),
                res.get("file_path", ""),
                res.get("mime", ""),
            ]
        ],
    )

