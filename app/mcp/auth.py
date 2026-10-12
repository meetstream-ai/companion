"""
Authentication and Authorization for MCP Tool endpoints and the chat-relay
endpoint. Each workspace (Organization) has its own mcp_token - the bearer
token in the request is looked up against the organizations table to resolve
which workspace's data a tool call is allowed to touch, rather than every
agent sharing one global token mapped to a single hardcoded organization.
"""
import uuid
from typing import Optional
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.connection import get_db
from app.models.database import Organization


async def resolve_org_by_mcp_token(token: str, db: AsyncSession) -> Optional[uuid.UUID]:
    result = await db.execute(select(Organization.id).where(Organization.mcp_token == token))
    return result.scalar_one_or_none()


async def verify_mcp_token(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Validates the Bearer token from an MCP request and returns the workspace it belongs to."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header for MCP server",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization scheme. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    org_id = await resolve_org_by_mcp_token(token, db)
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid MCP authorization token",
        )

    return org_id
