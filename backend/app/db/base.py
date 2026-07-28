"""
db/base.py

Responsibility
--------------
Defines the single SQLAlchemy `DeclarativeBase` that every ORM model in
the application (added in later milestones under `app/models/`) will
inherit from, and the shared `MetaData` naming convention.

Why a naming convention matters here: without one, SQLAlchemy lets the
database assign auto-generated constraint/index names (e.g.
`ix_a1b2c3`), which are inconsistent across environments and make Alembic
autogenerate diffs noisy/unstable. Fixing an explicit naming convention up
front means every future migration is deterministic and every constraint
name is predictable and greppable.

Every model in `app/models/` (User, Product, and future models) inherits
from this `Base` and is registered on `Base.metadata` via
`app/models/__init__.py`, which Alembic reads from (see `alembic/env.py`)
to autogenerate migrations.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Standard, widely-used naming convention for constraints/indexes.
# Keeping this consistent across the whole schema is what makes Alembic
# autogenerate diffs clean and migration rollbacks safe.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models. All future models in `app/models/`
    inherit from this class."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
