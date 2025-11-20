from enum import Enum

class PersonType(str, Enum):
    INDIVIDUAL = "individual"
    FOP = "fop"
    COMPANY = "company"

class ContractRole(str, Enum):
    LESSOR = "lessor"
    LESSEE = "lessee"
    # Можно додати інші ролі пізніше

class FillingMode(str, Enum):
    PARTIAL = "partial"
    FULL = "full"
