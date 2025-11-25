"""Shared JSON schema helpers for tool parameters."""
from __future__ import annotations

from typing import Any, Dict, List


def string_enum_or_minlength(ids: List[str]) -> Dict[str, Any]:
    """
    Return a JSON schema for a string property.

    If ids is non-empty, returns an enum schema.
    Otherwise, returns a minLength schema.
    """
    if ids:
        return {
            "type": "string",
            "enum": ids,
        }
    return {
        "type": "string",
        "minLength": 1,
    }


def session_id_property() -> Dict[str, Any]:
    """Return JSON schema for session_id property."""
    return {
        "type": "string",
        "minLength": 1,
    }


def base_session_parameters(extra_properties: Dict[str, Any] | None = None,
                            extra_required: List[str] | None = None) -> Dict[str, Any]:
    """
    Return base parameters schema with session_id.

    Args:
        extra_properties: Additional properties to include.
        extra_required: Additional required fields.

    Returns:
        JSON schema dict for parameters.
    """
    properties = {
        "session_id": session_id_property(),
    }
    if extra_properties:
        properties.update(extra_properties)

    required = ["session_id"]
    if extra_required:
        required.extend(extra_required)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
