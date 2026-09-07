"""Every migrated column has to exist on its ORM model too.

Adding a column to `ADDED_COLUMNS` alone creates it in the database and
leaves SQLAlchemy unaware of it. Reads come back without it and any
`update(...).values(that_column=...)` raises — and the failure surfaces
somewhere unrelated, as "could not change what this account is for".

Five columns shipped that way in one afternoon: `purpose` on sending
accounts, and `attachment_path` / `attachment_name` on both campaigns and
templates. Each was created, invisible, and broken on first write. This
walks the list so the next one is caught here instead.

Needs no database — it compares two things already in the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402


def _models_by_table() -> dict[str, object]:
    return {
        mapper.class_.__tablename__: mapper.class_
        for mapper in db.Base.registry.mappers
    }


@pytest.mark.parametrize("table,column,ddl", db.ADDED_COLUMNS)
def test_migrated_column_exists_on_its_model(table: str, column: str, ddl: str) -> None:
    models = _models_by_table()
    model = models.get(table)
    assert model is not None, (
        f"{table} is migrated but has no ORM model — either add one, or the "
        f"entry in ADDED_COLUMNS is for a table that no longer exists."
    )
    assert column in model.__table__.columns, (
        f"{table}.{column} is added by ADDED_COLUMNS but is not on "
        f"{model.__name__}. The database will have it and SQLAlchemy will "
        f"not: reads drop it, and writing it raises. Add it to the model."
    )


def test_the_migration_list_is_not_empty() -> None:
    """A guard on the guard: an empty list would make every case above
    vacuous and nobody would notice."""
    assert len(db.ADDED_COLUMNS) > 5
