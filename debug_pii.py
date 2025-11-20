from src.validators.pii_tagger import sanitize_typed

fake_iban = "UA213223130000026007233566001" 
msg1 = f"Мій IBAN {fake_iban}"

print(f"Testing message: {msg1}")
result = sanitize_typed(msg1)
print("Result:", result)
