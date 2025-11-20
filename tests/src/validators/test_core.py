import pytest
from src.validators.core import validate_value
from src.validators.date import normalize_date
from src.validators.money import normalize_money
from src.common.errors import ValidationError

def test_validate_value_text():
    val, err = validate_value("text", " Hello ")
    assert val == "Hello"
    assert err is None

def test_validate_value_empty():
    # validate_value explicitly allows empty strings
    val, err = validate_value("text", "")
    assert val == ""
    assert err is None

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
