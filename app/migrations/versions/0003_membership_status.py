"""memberships.status: joining by code is a request an owner approves

Revision ID: 0003_membership_status
Revises: 0002_memberships
Create Date: 2026-09-17

A join code is meant to be passed around, which also means anyone it reaches
could walk straight in. This adds a status to memberships so a join by code
creates a *pending* row that grants nothing until an owner approves it.
Existing rows are people who are already in; they stay active.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_membership_status"
down_revision: Union[str, None] = "0002_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memberships",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    )


def downgrade() -> None:
    # Pending requests have no meaning without the column; drop them rather
    # than silently let everyone who ever asked in.
    op.execute(sa.text("DELETE FROM memberships WHERE status <> 'active'"))
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("status")
