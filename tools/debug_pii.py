"""Debug script for testing PII tagging functionality."""
from backend.domain.validation.pii_tagger import sanitize_typed

FAKE_IBAN = "UA213223130000026007233566001"
TEST_MESSAGE = f"Мій IBAN {FAKE_IBAN}"

print(f"Testing message: {TEST_MESSAGE}")
result = sanitize_typed(TEST_MESSAGE)
print("Result:", result)
