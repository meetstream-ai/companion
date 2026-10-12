"""
Saved database connections for a single-person install.

One running app has one live database, and accounts live inside databases.
Someone with a workspace of their own on one host and their team's on
another therefore has two accounts, and until now had to paste the other
connection string into Settings and sign in again to move between them.

A *connection* is a database this install knows (label + URL) plus the id
of this machine's person inside it. With those, the workspace picker can
list every workspace across every connection, and choosing one switches
the live database and signs the person in on it - with the trust already
extended to device.key: this machine, this data directory.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.connection import current_url, normalize_database_url, switch_database
from app.providers.database import provider_for_url
from app.runtime_config import ConnectionSettings, DatabaseSettings, load_config, mask_secret, save_config

logger = logging.getLogger(__name__)


def _label_for(url: str) -> str:
    provider = provider_for_url(url)
    names = {"sqlite": "Local SQLite", "supabase": "Supabase", "neon": "Neon", "railway": "Railway", "postgresql": "PostgreSQL"}
    if provider == "sqlite":
        # Two local files must be tellable apart: name the file.
        name = url.rsplit("/", 1)[-1] or "meet-companion.db"
        return f"Local SQLite · {name}"
    host = url.split("@", 1)[1].split("/", 1)[0].split(":", 1)[0] if "@" in url else ""
    return f"{names.get(provider, 'PostgreSQL')}{' · ' + host if host else ''}"


def list_connections() -> List[ConnectionSettings]:
    return list(load_config().connections)


def find_connection(connection_id: str) -> Optional[ConnectionSettings]:
    return next((c for c in load_config().connections if c.id == connection_id), None)


def remember_connection(url: str, *, label: Optional[str] = None) -> ConnectionSettings:
    """Make sure the URL has an entry; the live database always does."""
    url = normalize_database_url(url)
    config = load_config()
    for entry in config.connections:
        if entry.url == url:
            if label and label != entry.label:
                entry.label = label
                save_config(config)
            return entry
    entry = ConnectionSettings(id=uuid.uuid4().hex[:8], label=label or _label_for(url), url=url)
    save_config(replace(config, connections=[*config.connections, entry]))
    return entry


def remember_user_for_current_connection(user_id: uuid.UUID) -> None:
    """After a sign-in: this is who this machine is on the live database."""
    url = current_url()
    config = load_config()
    changed = False
    found = False
    for entry in config.connections:
        if entry.url == url:
            found = True
            if entry.user_id != str(user_id):
                entry.user_id = str(user_id)
                changed = True
    if not found:
        config.connections.append(ConnectionSettings(id=uuid.uuid4().hex[:8], label=_label_for(url), url=url, user_id=str(user_id)))
        changed = True
    if changed:
        save_config(config)


def forget_connection(connection_id: str) -> bool:
    config = load_config()
    remaining = [c for c in config.connections if c.id != connection_id]
    if len(remaining) == len(config.connections):
        return False
    save_config(replace(config, connections=remaining))
    return True


async def workspaces_on(entry: ConnectionSettings) -> Dict[str, Any]:
    """
    What this machine's person can see on that connection, without switching
    to it: their workspaces and role there. A connection with no remembered
    person, or one that cannot be reached, says so instead of failing the
    whole picker.
    """
    from app.models.database import Membership, Organization, User

    if not entry.user_id:
        return {"reachable": None, "signed_in": False, "workspaces": []}
    if entry.url == current_url():
        from app.database.connection import AsyncSessionLocal

        factory = AsyncSessionLocal
        engine = None
    else:
        engine = create_async_engine(entry.url, pool_pre_ping=True)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            user = (await db.execute(select(User).where(User.id == uuid.UUID(entry.user_id), User.is_active.is_(True)))).scalar_one_or_none()
            if user is None:
                return {"reachable": True, "signed_in": False, "workspaces": []}
            rows = (
                await db.execute(
                    select(Organization, Membership.role, Membership.status)
                    .join(Membership, Membership.organization_id == Organization.id)
                    .where(Membership.user_id == user.id)
                    .order_by(Membership.created_at)
                )
            ).all()
            return {
                "reachable": True,
                "signed_in": True,
                "email": user.email,
                "workspaces": [
                    {
                        "id": str(org.id), "name": org.name, "role": role, "status": status,
                        "is_active": status == "active" and org.id == user.organization_id,
                    }
                    for org, role, status in rows
                ],
            }
    except Exception as exc:  # noqa: BLE001 - one bad connection must not break the picker
        logger.info("Connection %s unreachable: %s", entry.label, type(exc).__name__)
        return {"reachable": False, "signed_in": bool(entry.user_id), "workspaces": [], "error": type(exc).__name__}
    finally:
        if engine is not None:
            await engine.dispose()


async def workspace_for_code(url: Optional[str], code: str) -> Optional[str]:
    """
    The name of the workspace this join code opens on that database, or None
    if there is no such workspace there. Read-only, on a throwaway
    connection: nothing is saved and the live database is not switched.

    This is what lets the UI say "that code is not on that database" *before*
    switching to it - a failed join used to leave the app pointed at a
    database the person had no account on.
    """
    from app.database.connection import dialect_of
    from app.models.database import Organization

    if not url or url == current_url():
        from app.database.connection import AsyncSessionLocal

        factory = AsyncSessionLocal
        engine = None
    else:
        connect_args = {"timeout": 5} if dialect_of(url) == "postgresql" else {}
        engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            return (
                await db.execute(select(Organization.name).where(Organization.join_code == code))
            ).scalar_one_or_none()
    finally:
        if engine is not None:
            await engine.dispose()


async def activate(entry: ConnectionSettings, organization_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
    """
    Make this connection the live database and, if this machine has an
    account there, open the requested workspace. Returns the user id to sign
    in as, or None when a sign-in is needed first.
    """
    from app.models.database import Membership, User

    if entry.url != current_url():
        await switch_database(entry.url)
        config = load_config()
        save_config(replace(config, database=DatabaseSettings(url=entry.url)))
    if not entry.user_id:
        return None
    from app.database.connection import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == uuid.UUID(entry.user_id), User.is_active.is_(True)))).scalar_one_or_none()
        if user is None:
            return None
        if organization_id is not None and organization_id != user.organization_id:
            membership = (
                await db.execute(select(Membership).where(Membership.user_id == user.id, Membership.organization_id == organization_id))
            ).scalar_one_or_none()
            if membership is not None:
                user.organization_id = organization_id
                user.role = membership.role
                await db.commit()
        return user.id


def describe(entry: ConnectionSettings) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "label": entry.label,
        "provider": provider_for_url(entry.url),
        "url": mask_secret(entry.url),
        "active": entry.url == current_url(),
        "signed_in": bool(entry.user_id),
    }
