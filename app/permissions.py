"""
What a workspace's *members* are allowed to do.

Owners can always do everything in their workspace. For everyone else the
owner picks, per workspace, which of these they may do. The choices live in
Organization.settings["permissions"] - no table, no migration - and any key
that is not stored falls back to its default below, so a workspace created
before this existed behaves sensibly (members may add and edit, but not
delete, manage agents, export, or invite).

Every rule here is enforced on the server; the UI only hides what a member
cannot use.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_owner
from app.database.connection import get_db
from app.models.database import Organization, User


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    default: bool


PERMISSIONS: tuple[Permission, ...] = (
    Permission(
        "create_content",
        "Add content",
        "Create notes and folders, upload transcripts and documents, launch and import bots.",
        True,
    ),
    Permission(
        "edit_content",
        "Edit content",
        "Change notes, folders and action items; stop a running bot; reprocess a meeting.",
        True,
    ),
    Permission(
        "delete_content",
        "Delete content",
        "Delete notes, folders, meetings and documents. Deleting a meeting also removes what was extracted from it.",
        False,
    ),
    Permission(
        "manage_agents",
        "Manage agents",
        "Create, edit, import and activate the agents that join calls.",
        False,
    ),
    Permission(
        "export_workspace",
        "Export",
        "Download notes, meetings or the whole workspace as Markdown, JSON or a zip.",
        False,
    ),
    Permission(
        "invite_members",
        "Invite people",
        "See the workspace join code.",
        False,
    ),
)

PERMISSION_KEYS = frozenset(p.key for p in PERMISSIONS)
DEFAULTS: Dict[str, bool] = {p.key: p.default for p in PERMISSIONS}


def member_permissions(org: Organization | None) -> Dict[str, bool]:
    """The effective member permissions for a workspace: stored choices over defaults."""
    stored = ((org.settings if org is not None else None) or {}).get("permissions") or {}
    return {key: bool(stored.get(key, default)) for key, default in DEFAULTS.items()}


def effective_permissions(user: User, org: Organization | None) -> Dict[str, bool]:
    """What this particular person may do here. Owners: everything."""
    if is_owner(user):
        return {key: True for key in DEFAULTS}
    return member_permissions(org)


def describe() -> list[Dict[str, Any]]:
    """For the Members page: every permission with its label, text and default."""
    return [
        {"key": p.key, "label": p.label, "description": p.description, "default": p.default}
        for p in PERMISSIONS
    ]


async def load_org(org_id: uuid.UUID, db: AsyncSession) -> Organization | None:
    return (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()


def require(key: str):
    """
    FastAPI dependency: the signed-in member must hold this permission in
    their workspace. Owners always pass. Members without it get a 403 that
    says who can change that.
    """
    if key not in PERMISSION_KEYS:  # pragma: no cover - programming error
        raise KeyError(key)

    async def _check(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        if is_owner(user):
            return user
        org = await load_org(user.organization_id, db)
        if not member_permissions(org).get(key, False):
            label = next(p.label.lower() for p in PERMISSIONS if p.key == key)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Members of this workspace cannot {label}. A workspace owner can change that from the Members page.",
            )
        return user

    return _check
