"""Small SQLAlchemy helpers that compile safely on SQL Server and PostgreSQL."""
from __future__ import annotations

from sqlalchemy import Boolean, literal


def boolean_equals(column, value: bool = True):
    """Return a portable boolean equality predicate.

    SQL Server BIT columns require ``= 1`` / ``= 0`` rather than ``IS 1`` /
    ``IS 0``. PostgreSQL requires boolean literals. SQLAlchemy's typed literal
    renders the correct representation for each dialect.
    """
    return column == literal(bool(value), type_=Boolean())
