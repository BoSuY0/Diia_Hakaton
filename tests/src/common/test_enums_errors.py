"""Tests for shared enums and error classes."""
from backend.shared.enums import PersonType, FillingMode
from backend.shared.errors import SessionNotFoundError, MetaNotFoundError, ValidationError


def test_enum_values():
    """Test that enum values are correct."""
    assert PersonType.INDIVIDUAL.value == "individual"
    assert PersonType.FOP.value == "fop"
    assert PersonType.COMPANY.value == "company"
    assert FillingMode.PARTIAL.value == "partial"
    assert FillingMode.FULL.value == "full"
    # NOTE: Contract roles are not enum - they come from category metadata JSON


def test_errors_str():
    """Test that error classes have proper string representation."""
    assert "Session" in str(SessionNotFoundError("Session missing"))
    assert "Meta" in str(MetaNotFoundError("Meta missing"))


def test_validation_error_code():
    """Test that ValidationError stores and exposes error code."""
    err = ValidationError("bad", code="E1")
    assert err.code == "E1"
    assert "bad" in str(err)
