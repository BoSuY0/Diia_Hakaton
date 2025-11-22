import pytest

from src.validators.pii_tagger import sanitize_typed


def test_sanitize_typed_detects_iban_card_phone_email():
    text = "IBAN UA21 3223 1300 0002 6007 2335 6600 1 card 4444333322221111 tel +380931234567 mail test@example.com"
    res = sanitize_typed(text)
    tags = res["tags"]
    assert any(t.startswith("[IBAN#") for t in tags)
    assert any(t.startswith("[CARD#") for t in tags)
    assert any(t.startswith("[PHONE#") for t in tags)
    assert any(t.startswith("[EMAIL#") for t in tags)
    # sanitized text should contain tags
    assert "[IBAN#" in res["sanitized_text"]
    assert "[CARD#" in res["sanitized_text"]


def test_sanitize_typed_merges_overlapping_prefers_priority():
    # A JWT-looking string that is also digits; priority should pick JWT over other
    jwt = "aaaa.bbbb.cccc"
    text = f"token {jwt}"
    res = sanitize_typed(text)
    tags = list(res["tags"].keys())
    assert any(t.startswith("[JWT#") for t in tags)


def test_sanitize_typed_detects_name_and_rnokpp():
    text = "ПІБ: Іванов Іван Іванович, іпн 1234567890"
    res = sanitize_typed(text)
    tags = res["tags"]
    assert any(t.startswith("[NAME#") for t in tags)
    assert any(t.startswith("[IPN#") for t in tags)


def test_sanitize_typed_handles_zero_width_and_noise():
    text = "IBAN\u200b UA21-3223-1300-0002-6007-2335-6600-1"
    res = sanitize_typed(text)
    assert any(t.startswith("[IBAN#") for t in res["tags"])


def test_sanitize_typed_detects_private_key_and_jwt():
    pk = "-----BEGIN PRIVATE KEY-----MIICdwIBADANBgkqhkiG9w0BAQEFAASCAmEwggJdAgEAAoGBAM-----END PRIVATE KEY-----"
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    text = f"key: {pk} token: {jwt}"
    res = sanitize_typed(text)
    tags = res["tags"]
    assert any(t.startswith("[PRIVATE_KEY#") for t in tags)
    assert any(t.startswith("[JWT#") for t in tags)
