from src.common.enums import PersonType, ContractRole, FillingMode
from src.common.errors import SessionNotFoundError, MetaNotFoundError, ValidationError


def test_enum_values():
    assert PersonType.INDIVIDUAL.value == "individual"
    assert ContractRole.LESSOR.value == "lessor"
    assert FillingMode.PARTIAL.value == "partial"


def test_errors_str():
    assert "Session" in str(SessionNotFoundError("Session missing"))
    assert "Meta" in str(MetaNotFoundError("Meta missing"))


def test_validation_error_code():
    err = ValidationError("bad", code="E1")
    assert err.code == "E1"
    assert "bad" in str(err)
