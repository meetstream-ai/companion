"""
Shared request-scoped dependencies: resolving the signed-in member and their
workspace (organization) from the session cookie. Every org-scoped endpoint
should depend on get_current_org_id instead of hardcoding a default org, so
each workspace only ever sees its own data.
"""
import uuid
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.models.database import Membership, Organization, User
from app.middleware.auth_gate import COOKIE_NAME, decode_session


async def get_current_account(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """
    The signed-in account, whatever its standing in the workspace it has open.

    Only for the few endpoints that are about the account rather than the
    workspace - listing, creating, requesting and switching workspaces - so
    someone whose request to join is still pending can still get out of
    that state. Everything org-scoped uses get_current_user.
    """
    token = request.cookies.get(COOKIE_NAME)
    user_id = decode_session(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in required.")
    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


async def get_current_user(user: User = Depends(get_current_account), db: AsyncSession = Depends(get_db)) -> User:
    """
    The signed-in member, confirmed to actually be in the workspace they have
    open. users.organization_id is only a pointer; joining by code sets it
    while the membership is still pending, and every org-scoped query trusts
    it, so a pending person would otherwise read and write that workspace's
    data before anyone approved them.
    """
    await require_active_membership(user, db)
    return user


async def require_active_membership(user: User, db: AsyncSession) -> None:
    """403 unless the account is an active member of the workspace it has open."""
    ok = (
        await db.execute(
            select(Membership.id).where(
                Membership.user_id == user.id,
                Membership.organization_id == user.organization_id,
                Membership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if ok is None:
        raise HTTPException(
            status_code=403,
            detail="Your request to join this workspace is waiting for an owner to approve it.",
        )


async def get_current_org_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    return user.organization_id


OWNER = "owner"


def is_owner(user: User) -> bool:
    return user.role == OWNER


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """
    The signed-in member must own their workspace.

    Destructive member actions and workspace settings are owner-only.
    Server-wide configuration needs more: see require_instance_admin.
    """
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only a workspace owner can do this.")
    return user


SERVER_ADMIN_ONLY = "Only the server administrator (the owner of the first workspace) can change server settings."


#: Where the admin workspace is recorded: a key in the default workspace's
#: settings. That row is created by bootstrap on every database and travels
#: with it (a database switch carries the right answer along; config.json
#: would not), and no API writes arbitrary keys into it.
ADMIN_WORKSPACE_KEY = "instance_admin_org_id"


def _default_org_id() -> uuid.UUID:
    from app.config import settings

    return uuid.UUID(settings.DEFAULT_ORG_ID)


async def _oldest_owned_workspace(db: AsyncSession) -> "uuid.UUID | None":
    return (
        await db.execute(
            select(Organization.id)
            .join(Membership, Membership.organization_id == Organization.id)
            .join(User, User.id == Membership.user_id)
            .where(Membership.role == OWNER, Membership.status == "active", User.is_active.is_(True))
            .order_by(Organization.created_at, Organization.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def pin_admin_workspace(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Record org_id as the admin workspace. The caller commits."""
    holder = await db.get(Organization, _default_org_id())
    if holder is not None:
        # Reassign rather than mutate: the JSON column only notices a new value.
        holder.settings = {**(holder.settings or {}), ADMIN_WORKSPACE_KEY: str(org_id)}


async def admin_workspace_id(db: AsyncSession) -> "uuid.UUID | None":
    """
    The recorded admin workspace. An install from before it was recorded gets
    it pinned here, once, by the old rule: the oldest workspace with an
    active owner (bootstrap's empty default workspace comes first and has
    none). A value that cannot be read is never replaced: None, fail closed.
    """
    holder = await db.get(Organization, _default_org_id())
    if holder is None:
        return None
    raw = (holder.settings or {}).get(ADMIN_WORKSPACE_KEY)
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None
    first = await _oldest_owned_workspace(db)
    if first is None:
        return None
    await pin_admin_workspace(db, first)
    await db.commit()
    return first


async def is_instance_admin(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """
    Whether this account administers the server itself, not just a workspace.

    Anyone who can sign up becomes owner of a workspace of their own, so
    "owner" cannot be what guards server-wide settings (AI provider, database,
    MeetStream, tunnel, agent template). The administrator is an active owner
    of the admin workspace, recorded when the first account creates the first
    workspace. If that workspace has no active owner or is gone, nobody is
    administrator: the role never moves on to a workspace a stranger made.
    A single-team install and the desktop app have one workspace, so nothing
    changes for them.
    """
    pinned = await admin_workspace_id(db)
    if pinned is None:
        return False
    held = (
        await db.execute(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.user_id == user_id,
                Membership.organization_id == pinned,
                Membership.role == OWNER,
                Membership.status == "active",
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    return held is not None


async def require_instance_admin(user: User = Depends(get_current_account), db: AsyncSession = Depends(get_db)) -> User:
    """The signed-in account must administer the server (see is_instance_admin)."""
    if not await is_instance_admin(user.id, db):
        raise HTTPException(status_code=403, detail=SERVER_ADMIN_ONLY)
    return user
