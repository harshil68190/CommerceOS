"""
alembic/env.py

Responsibility
--------------
Wires Alembic to the actual application: it pulls the database URL from
`app.core.config.Settings` (never hardcoded/duplicated in alembic.ini),
and points `target_metadata` at the same `Base.metadata` that all future
ORM models (in `app/models/`) will register themselves against by
inheriting from `Base`.

This milestone defines no models, so `target_metadata` is currently
empty — the first `alembic revision --autogenerate` run after models
exist will pick them up automatically with no changes needed here.

Both "offline" (generate SQL without a live DB connection) and "online"
(connect and apply/generate against a real DB) modes are supported, which
is the standard Alembic template behavior.
"""
import os
import sys

# Add the backend directory to Python's import path
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db.base import Base

# This is the Alembic Config object, which provides access to values
# within the .ini file in use.
config = context.config

# Interpret the config file for Python logging, unless run in a context
# (like our own scripts) that already configured logging itself.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at the application's own declarative Base metadata so
# `--autogenerate` can diff real models against the live schema. Empty in
# this milestone since no models exist yet.
target_metadata = Base.metadata

# Inject the real database URL from application settings rather than
# relying on alembic.ini (keeps exactly one source of truth for DB
# connection info: environment variables via Settings).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode: emits SQL to a script instead of
    executing against a live database. Useful for generating a SQL file
    to hand to a DBA, or for environments without direct DB access."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode: connects to the database and
    applies/compares migrations directly. This is the normal path used
    by `alembic upgrade head` in local dev, CI, and deploys."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
