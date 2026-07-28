"""
models/ — SQLAlchemy ORM models.

Every model module must be imported here. This is not just organizational
tidiness: `Base.metadata` (used by Alembic's autogenerate in
`alembic/env.py`) only contains tables for model classes that have
actually been imported into the running process. If `User` were never
imported anywhere, `Base.metadata.tables` would be empty and
`alembic revision --autogenerate` would generate a migration that drops
nothing and creates nothing — silently wrong.

`alembic/env.py` is updated in this milestone to `import app.models`
before reading `target_metadata`, specifically so this file is the single
place new models get registered as the schema grows.
"""

from app.models.user import User, UserRole

__all__ = ["User", "UserRole"]
