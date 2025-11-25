"""Verification script for DOCX regex cleanup logic."""
import re


def test_regex_cleanup() -> None:
    """Test regex cleanup patterns for document generation."""
    print("Testing regex cleanup logic...")

    labels_to_clean = ["паспорт", "РНОКПП", "тел.", "e-mail"]

    test_cases = [
        ("паспорт: , РНОКПП: 123", "РНОКПП: 123"),
        ("паспорт: , РНОКПП: ", ""), # Both empty
        ("тел.: , e-mail: test@example.com", "e-mail: test@example.com"),
        ("Some text. тел.: ", "Some text. "),
        ("Mixed: паспорт: 123, РНОКПП: , end", "Mixed: паспорт: 123, end"),
    ]

    for input_text, expected in test_cases:
        text = input_text
        for label in labels_to_clean:
            safe_label = re.escape(label)
            # Case 1: Label followed by comma
            text = re.sub(rf"{safe_label}:\s*,\s*", "", text)
            # Case 2: Label at end or followed by whitespace only (simplified from original logic)
            # Original logic: text = re.sub(rf"{safe_label}:\s*$", "", text)
            # But wait, my implementation in docx_filler.py was:
            # text = re.sub(rf"{safe_label}:\s*$", "", text)
            # This only matches END OF STRING.
            # The original code had: text = re.sub(r"паспорт:\s*$", "", text)
            # So it only cleaned up if it was at the very end.

            # Let's verify if my refactor matches the original behavior.
            text = re.sub(rf"{safe_label}:\s*$", "", text)

        # Note: The original code also had:
        # text = re.sub(r"\{\{[^}]+\}\}", "", text)
        # text = re.sub(r"\[\[[^]]+\]\]", "", text)
        # We are not testing that here, just the label cleanup.

        # Adjust expectation for "Mixed" case because "РНОКПП: , " matches
        # "Label followed by comma" pattern? "РНОКПП: , end" -> matches.
        # In "Mixed: паспорт: 123, РНОКПП: , end", "РНОКПП: , " is followed by "end".
        # The regex `rf"{safe_label}:\s*,\s*"` matches "Label: , ".
        # So "РНОКПП: , " should be removed.

        if text.strip() != expected.strip():
            print(f"FAILED: Input: '{input_text}'")
            print(f"  Expected: '{expected}'")
            print(f"  Got:      '{text}'")
        else:
            print(f"PASSED: '{input_text}' -> '{text}'")

if __name__ == "__main__":
    test_regex_cleanup()
