"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-14

The starting point for migrations. It builds the whole current schema from the
ORM metadata rather than a long list of op.create_table calls, because the
models already carry the dialect-specific machinery this project depends on -
GUIDs that are UUID on Postgres and CHAR(32) on SQLite, and the embedding
column that is a real pgvector Vector on Postgres and a JSON array elsewhere
(see app/models/types.py). Reproducing that by hand in a migration would just
duplicate those decisions and risk drifting from them.

Existing installs (which already have this schema from the pre-Alembic
create_all path) are stamped at this revision instead of running it; only a
brand-new database executes it. Every schema change from here on is a new,
explicit revision on top of this baseline.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from app.models.database import Base

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The tables that existed when this baseline was cut. Pinned by name on
#: purpose: building from whatever Base.metadata happens to hold today would
#: make the baseline create tables introduced by *later* revisions, and those
#: revisions would then fail with "table already exists". A baseline has to
#: describe history, not follow the models.
BASELINE_TABLES = (
    "organizations",
    "users",
    "api_keys",
    "meetings",
    "participants",
    "transcript_segments",
    "memories",
    "action_items",
    "notebook_folders",
    "notes",
    "company_knowledge_embeddings",
    "meeting_memory_embeddings",
    "processing_jobs",
    "webhook_events",
)


def _baseline_tables():
    missing = set(BASELINE_TABLES) - set(Base.metadata.tables)
    if missing:  # pragma: no cover - a rename would have to update this list
        raise RuntimeError(f"baseline names tables that no longer exist: {sorted(missing)}")
    return [Base.metadata.tables[name] for name in BASELINE_TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Inside the migration's own transaction, so it commits with the tables
        # that depend on the vector type.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind, tables=_baseline_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_baseline_tables())
