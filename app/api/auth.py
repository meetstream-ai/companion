"""
Per-member login. Accounts are created through app/api/members.py - either
self-signup into a new or joined workspace, or added by an existing member.
"""
import time
import uuid
from fastapi import APIRouter, HTTPException, Response, Request, Depends

from app.config import settings
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.models.database import User
from app.middleware.auth_gate import COOKIE_NAME, SESSION_TTL_SECONDS, sign_session, decode_session
from app.security import hash_password, needs_rehash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def is_https(request: Request) -> bool:
    """Whether the browser reached us over TLS, looking through a trusted proxy."""
    if settings.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-proto")
        if forwarded:
            return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def cookie_flags(request: Request) -> dict:
    """
    Session cookie attributes that actually work for how this install is reached.

    Over HTTPS the UI may live on another origin (a separately hosted
    frontend), which needs SameSite=None - and that attribute is only
    accepted together with Secure. Over plain HTTP - a LAN box, a NAS, the
    desktop bundle on 127.0.0.1 - a Secure cookie is silently dropped by the
    browser and nobody can stay signed in, so the cookie is SameSite=Lax
    instead: right for every same-origin deployment, and a cross-site
    deployment without TLS is not something to support.
    """
    if is_https(request):
        return {"samesite": "none", "secure": True}
    return {"samesite": "lax", "secure": False}


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.strip().lower(), User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if needs_rehash(user.password_hash):
        # Transparent upgrade from the pre-2026-09 truncating scheme.
        user.password_hash = hash_password(body.password)
        await db.commit()

    token = sign_session(str(user.id), int(time.time()) + SESSION_TTL_SECONDS)
    response.set_cookie(key=COOKIE_NAME, value=token, max_age=SESSION_TTL_SECONDS, httponly=True, **cookie_flags(request))
    _remember_if_this_machine(request, user.id)
    return {"authenticated": True, "member": await member_payload(user, db)}


def _remember_if_this_machine(request: Request, user_id) -> None:
    """
    On the desktop app (device key present), note that this account is who
    this machine is on the live database, so the workspace picker can offer
    its workspaces later without another password prompt.
    """
    import hmac as _hmac

    from app.middleware.auth_gate import DEVICE_COOKIE_NAME
    from app.secrets import device_secret

    presented = request.cookies.get(DEVICE_COOKIE_NAME) or ""
    if presented and _hmac.compare_digest(presented, device_secret()):
        from app.services.connections import remember_user_for_current_connection

        remember_user_for_current_connection(user_id)


@router.post("/logout")
async def logout(request: Request, response: Response):
    # delete_cookie must be told the same SameSite/Secure attributes the
    # cookie was set with, or the browser treats it as a different cookie
    # and silently ignores the deletion.
    response.delete_cookie(COOKIE_NAME, **cookie_flags(request))
    return {"authenticated": False}


@router.get("/check")
async def check(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    user_id = decode_session(token) if token else None
    user = await _active_user(db, user_id) if user_id else None
    if not user:
        # /api/auth/* skips the gate (sign-in has to be reachable when signed
        # out), so the device key has to be honoured here as well. Without
        # this the desktop app is signed in for every API call yet still shown
        # the sign-in screen, because this is the endpoint the UI boots on.
        # It also has to apply when the cookie is well-signed but for a user
        # this database does not have - after switching databases, or an
        # account removed - or the desktop app is stuck at sign-in with a
        # cookie it cannot clear.
        from app.middleware.auth_gate import _session_from_device_key

        issued = await _session_from_device_key(request)
        if issued is None:
            return {"authenticated": False}
        session_token, user_id = issued
        response.set_cookie(
            key=COOKIE_NAME, value=session_token, max_age=SESSION_TTL_SECONDS,
            httponly=True, **cookie_flags(request),
        )
        user = await _active_user(db, user_id)
        if not user:
            return {"authenticated": False}
        _remember_if_this_machine(request, user.id)
    return {"authenticated": True, "member": await member_payload(user, db)}


async def _active_user(db: AsyncSession, user_id) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    return result.scalar_one_or_none()


async def member_payload(user: User, db: AsyncSession) -> dict:
    """
    The signed-in member as the UI needs it, including what they may do in
    their workspace - so buttons a member cannot use are not shown. The
    server enforces every one of these again on the endpoint itself.
    """
    from app import permissions as perms
    from app.models.database import Membership

    org = await perms.load_org(user.organization_id, db)
    # Joining by code sets organization_id while the membership is still a
    # request. Until an owner approves, every org-scoped call answers 403;
    # the UI needs to know that up front to show a waiting screen instead.
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id, Membership.organization_id == user.organization_id
            )
        )
    ).scalar_one_or_none()
    waiting = membership is not None and membership.status != "active"
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "permissions": perms.effective_permissions(user, org),
        "pending_approval": {"workspace": org.name if org else None} if waiting else None,
        # So Settings can say when the workspace's owner chose the AI for
        # everyone and this person's own AI settings do not apply here.
        "workspace_ai": _workspace_ai_summary(org),
    }


def _workspace_ai_summary(org) -> dict | None:
    from app.services.llm import workspace_llm

    chosen = workspace_llm(org) if org else None
    if chosen is None:
        return {"mode": "member"}
    return {"mode": "workspace", "provider": chosen.get("provider"), "model": chosen.get("model")}
