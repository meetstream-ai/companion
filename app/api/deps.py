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
from app.models.database import Membership, User
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
    return user


async def get_current_org_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    return user.organization_id


OWNER = "owner"


def is_owner(user: User) -> bool:
    return user.role == OWNER


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """
    The signed-in member must own their workspace.

    Server-wide configuration (AI provider, database, MeetStream, the agent
    template) and destructive member actions are owner-only. Without this,
    anyone who could sign up could reconfigure the whole install.
    """
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Only a workspace owner can do this.")
    return user
