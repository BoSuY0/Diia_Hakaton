from backend.domain.validation.core import validate_value, validator_registry


def test_validator_registry_fallback_trims_value():
    normalized, err = validate_value("unknown_type", "  some value  ")
    assert normalized == "some value"
    assert err is None


def test_validator_registry_handles_exception():
    def bad_validator(val: str) -> str:
        raise ValueError("boom")

    validator_registry.register("bad_type", bad_validator)
    normalized, err = validate_value("bad_type", "X")
    assert normalized == "X"
    assert "boom" in err
