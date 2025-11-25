"""Validation registry and field type inference utilities."""
from __future__ import annotations

from typing import Callable, Tuple

from backend.shared.errors import ValidationError
from backend.shared.registry import Registry
from backend.domain.validation import address as address_validator
from backend.domain.validation import date as date_validator
from backend.domain.validation import email as email_validator
from backend.domain.validation import iban as iban_validator
from backend.domain.validation import money as money_validator
from backend.domain.validation import person as person_validator
from backend.domain.validation import tax as tax_validator

ValidatorResult = Tuple[str, None]
ValidatorFunc = Callable[[str], str]


class ValidatorRegistry(Registry[ValidatorFunc]):
    """
    Registry for validation functions.
    """

    def validate(self, field_type: str, value: str) -> ValidatorResult:
        """
        Validate a value using the registered validator for field_type.
        """
        validator = self.get(field_type)

        # If no specific validator, just trim and return (fallback)
        if not validator:
            return value.strip(), None

        try:
            normalized = validator(value)
            return normalized, None
        except ValidationError as exc:
            return value.strip(), str(exc)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Catch any validator exceptions to return a proper error message
            return value.strip(), f"Validation error: {exc}"


# Global validator registry
validator_registry = ValidatorRegistry(name="GlobalValidatorRegistry")


# Register existing validators
validator_registry.register("date", date_validator.normalize_date)
validator_registry.register("email", email_validator.normalize_email)
validator_registry.register("money", money_validator.normalize_money)
validator_registry.register("iban", iban_validator.normalize_iban_ua)
validator_registry.register("rnokpp", tax_validator.normalize_rnokpp)
validator_registry.register("edrpou", tax_validator.normalize_edrpou)
validator_registry.register("person_name", person_validator.normalize_person_name)
validator_registry.register("address", address_validator.normalize_address)


def validate_value(field_type: str, value: str) -> ValidatorResult:
    """
    Public API for validation, delegating to the registry.
    """
    # We do NOT return early for empty values here, because specific validators
    # (like date, iban) should decide if an empty string is valid.
    # For example, an empty date string is NOT a valid date.
    # If a field is optional, that check should happen before calling validate_value.

    return validator_registry.validate(field_type, value)


def infer_value_type(field_name: str) -> str:
    """
    Infer validation type from field name using heuristics.
    
    This centralizes the logic for determining what validator to use
    based on field naming conventions (e.g., fields containing 'iban' 
    should use IBAN validation).
    
    Args:
        field_name: The name of the field (e.g., "lessor_iban", "tax_id")
        
    Returns:
        The inferred type string (e.g., "iban", "rnokpp", "text")
    """
    field_lower = field_name.lower()

    # IBAN fields
    if "iban" in field_lower:
        return "iban"

    # Tax ID fields (РНОКПП)
    if "rnokpp" in field_lower or "tax_id" in field_lower or "ipn" in field_lower:
        return "rnokpp"

    # Company code (ЄДРПОУ)
    if "edrpou" in field_lower:
        return "edrpou"

    # Date fields
    if "date" in field_lower or field_lower.endswith("_at"):
        return "date"

    # Email fields
    if "email" in field_lower or "mail" in field_lower:
        return "email"

    # Money/amount fields
    if "amount" in field_lower or "price" in field_lower or "sum" in field_lower:
        return "money"

    # Person name fields
    if field_lower in ("name", "full_name", "pib") or "name" in field_lower:
        return "person_name"

    # Address fields
    if "address" in field_lower or "addr" in field_lower:
        return "address"

    # Default to text (no specific validation)
    return "text"
