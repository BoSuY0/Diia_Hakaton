"""Common enumerations used across the application."""
from enum import Enum


class PersonType(str, Enum):
    """Type of legal entity for a contract party."""
    INDIVIDUAL = "individual"
    FOP = "fop"
    COMPANY = "company"

# NOTE: Contract roles are NOT hardcoded - they are defined dynamically
# in category metadata JSON files (e.g., lessor/lessee, buyer/seller, etc.)
# This allows full flexibility for different contract types.


class FillingMode(str, Enum):
    """Mode of contract form filling."""

    PARTIAL = "partial"  # User fills only their own role's fields
    FULL = "full"        # User can prefill fields for all roles
