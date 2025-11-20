from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from src.common.errors import ValidationError
from src.common.registry import Registry
from src.validators import address as address_validator
from src.validators import date as date_validator
from src.validators import iban as iban_validator
from src.validators import money as money_validator
from src.validators import person as person_validator
from src.validators import tax as tax_validator

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
        except Exception as exc:
            return value.strip(), f"Validation error: {exc}"


# Global validator registry
validator_registry = ValidatorRegistry(name="GlobalValidatorRegistry")


# Register existing validators
validator_registry.register("date", date_validator.normalize_date)
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
