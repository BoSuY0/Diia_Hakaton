import pytest

from src.validators.date import normalize_date
from src.validators.iban import normalize_iban_ua
from src.validators.money import normalize_money
from src.validators.person import normalize_person_name
from src.validators.tax import normalize_rnokpp, normalize_edrpou
from src.validators.address import normalize_address


def test_normalize_date_formats():
    assert normalize_date("2024-01-05") == "05.01.2024"
    assert normalize_date("05/01/2024") == "05.01.2024"
    with pytest.raises(Exception):
        normalize_date("invalid")


def test_normalize_iban():
    iban = " UA21 3223 1300 0002 6007 2335 6600 1 "
    assert normalize_iban_ua(iban) == "UA213223130000026007233566001"
    with pytest.raises(Exception):
        normalize_iban_ua("UA00")


def test_normalize_money():
    assert normalize_money("100,50") == "100.50"
    assert normalize_money("100.5") == "100.50"
    with pytest.raises(Exception):
        normalize_money("abc")


def test_normalize_person_name():
    assert normalize_person_name("  іван  іванов ") == "Іван Іванов"
    with pytest.raises(Exception):
        normalize_person_name("abc")  # too short/invalid


def test_normalize_rnokpp_and_edrpou():
    assert normalize_rnokpp("1234567890").isdigit()
    with pytest.raises(Exception):
        normalize_rnokpp("123")
    assert normalize_edrpou("12345678") == "12345678"
    with pytest.raises(Exception):
        normalize_edrpou("abcd")


def test_normalize_address():
    assert normalize_address(" вул. Шевченка, 10 ") == "вул. Шевченка, 10"
