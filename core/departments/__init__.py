"""Department registry

Provides:
- DEPARTMENTS:          department name -> DepartmentSpec
- get_department:       look a department up by name
"""

from core.departments.base import DepartmentSpec
from core.departments.customer import CUSTOMER
from core.departments.product import PRODUCT
from core.departments.sales import SALES


DEPARTMENTS: dict[str, DepartmentSpec] = {spec.name: spec for spec in (SALES, CUSTOMER, PRODUCT)}


def get_department(name: str) -> DepartmentSpec:
    """Return the DepartmentSpec of a department.

    Raises:
        KeyError: when no department has that name; the message lists the valid names.
    """
    try:
        return DEPARTMENTS[name]
    except KeyError:
        raise KeyError(f"unknown department {name!r}; expected one of {sorted(DEPARTMENTS)}") from None
