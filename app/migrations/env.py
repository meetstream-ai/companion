"""
Alembic environment, wired to the application's own configuration.

The database URL is not read from alembic.ini; it comes from
`resolve_database_url()` - the same env-var / saved-config / .env / SQLite
default precedence the app uses - so `alembic upgrade head` on the command
line and the migration run at app startup always target the same database,
whether that is a local SQLite file or a Postgres URL pasted into Settings.

Runs fully async, and creates the pgvector extension before migrations so the
vector columns can be built on a brand-new Postgres database.
"""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.database.connection import resolve_database_url
from app.models.database import Base

config = context.config
target_metadata = Base.metadata

# Let a caller (the app at startup) pass an explicit URL via
# config.attributes["url"]; otherwise resolve it the app's way.
_URL = config.attributes.get("url") or resolve_database_url()
# set_main_option runs the value through ConfigParser, which treats "%" as
# interpolation - a password containing one would raise. Escape it; the engine
# is built from this section below.
config.set_main_option("sqlalchemy.url", _URL.replace("%", "%%"))


def _run_migrations(connection: Connection) -> None:
    # The pgvector extension is created inside the migration itself (see the
    # baseline's upgrade), not here: executing on the connection before Alembic
    # configures it would open a transaction Alembic then declines to own,
    # leaving the schema uncommitted.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detect column type changes too, not just adds/drops.
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async())
