import pytest
from backend.domain.validation.core import validate_value
from backend.domain.validation.date import normalize_date
from backend.domain.validation.money import normalize_money
from backend.shared.errors import ValidationError

def test_validate_value_text():
    val, err = validate_value("text", " Hello ")
    assert val == "Hello"
    assert err is None

def test_validate_value_empty():
    # validate_value handles empty strings by returning them as-is (trimmed)
    # It does NOT raise ValidationError itself (it returns err string).
    # And for "text" (unknown type), it just returns the value.
    val, err = validate_value("text", "")
    assert val == ""
    assert err is None

def test_normalize_date_valid():
    assert normalize_date("01.01.2023") == "01.01.2023"
    assert normalize_date("1/1/2023") == "01.01.2023"

def test_normalize_date_invalid():
    with pytest.raises(ValidationError):
        normalize_date("invalid")

def test_normalize_money_valid():
    assert normalize_money("100") == "100.00"
    assert normalize_money("100,5") == "100.50"
    assert normalize_money("1 000.00") == "1000.00"

def test_normalize_money_invalid():
    with pytest.raises(ValidationError):
        normalize_money("abc")
