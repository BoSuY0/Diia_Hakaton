"""VSC (Value-Separated Columns) formatting utilities for LLM communication."""
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
    """Create a VSC row from column values."""
    return "|".join(_esc(str(c)) for c in cols)


def block(header: str, rows: Iterable[Iterable[object]]) -> str:
    """Create a VSC block with header and rows."""
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
    PARTY/<role>
    <field>|<status>|<error or ->
    """
    head = block(
        "SUMMARY",
        [
            ["state", res.get("state", "")],
            ["can_build", 1 if res.get("can_build_contract") else 0],
        ],
    )
    
    # Contract fields (shared fields)
    contract_fields_data = res.get("contract_fields", {})
    contract_rows = []
    for field_name, field_info in contract_fields_data.items():
        status = field_info.get("status", "empty")
        error = field_info.get("error") or "-"
        contract_rows.append([field_name, status, error])
    
    fields_block = block("FIELDS", contract_rows) if contract_rows else ""
    
    # Party fields (per-role fields)
    party_fields_data = res.get("party_fields", {})
    party_blocks = []
    for role, fields in party_fields_data.items():
        party_rows = []
        for field_name, field_info in fields.items():
            status = field_info.get("status", "empty")
            error = field_info.get("error") or "-"
            party_rows.append([field_name, status, error])
        if party_rows:
            party_blocks.append(block(f"PARTY/{role}", party_rows))
    
    # Combine all blocks
    result = head
    if fields_block:
        result += "\n" + fields_block
    for party_block in party_blocks:
        result += "\n" + party_block
    
    return result


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
