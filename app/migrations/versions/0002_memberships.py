"""memberships: let one account belong to several workspaces

Revision ID: 0002_memberships
Revises: 0001_baseline
Create Date: 2026-09-15

Until now a user row carried a single organization_id and that *was* their
workspace - one account, one workspace, for good. This adds a memberships
table so the same person can belong to several and switch between them.

users.organization_id survives with a narrower meaning: the workspace being
viewed right now. Keeping it is what lets every org-scoped query (all of them
go through get_current_org_id) stay exactly as it was; switching workspace
becomes a write to that one column, validated against this table.

The backfill matters more than the table: every existing user gets a
membership for the workspace they were already in, with the role they already
had. Without it, everyone would log in to a workspace they no longer belong to.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision: str = "0002_memberships"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memberships",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "organization_id", name="ux_membership_user_org"),
    )

    # Backfill: one membership per existing user, mirroring where they already
    # are and what they already are there.
    bind = op.get_bind()
    users = bind.execute(
        sa.text("SELECT id, organization_id, role FROM users WHERE organization_id IS NOT NULL")
    ).fetchall()
    if users:
        now = datetime.now(timezone.utc)
        memberships = sa.table(
            "memberships",
            sa.column("id", GUID()),
            sa.column("user_id", GUID()),
            sa.column("organization_id", GUID()),
            sa.column("role", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(
            memberships,
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": row[0],
                    "organization_id": row[1],
                    "role": row[2] or "member",
                    "created_at": now,
                }
                for row in users
            ],
        )


def downgrade() -> None:
    # users.organization_id was never dropped, so the old one-workspace
    # behaviour returns intact once this table is gone.
    op.drop_table("memberships")
