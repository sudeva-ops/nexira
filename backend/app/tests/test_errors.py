"""Database rule violations become 409, other database errors do not (plan G-08)."""

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.errors import is_rule_violation


class DriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "conflict"),
    [
        ("23505", True),  # unique violation, e.g. a second live playbook run
        ("23514", True),  # check violation
        ("P0001", True),  # RAISE EXCEPTION in a trigger
        ("08006", False),  # connection failure
        ("57014", False),  # statement timeout
        (None, False),
    ],
)
def test_rule_violations(sqlstate: str | None, conflict: bool) -> None:
    error = DBAPIError("statement", {}, DriverError(sqlstate))
    assert is_rule_violation(error) is conflict
