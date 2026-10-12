"""
Database provider selection.

The backend is chosen from the live connection's dialect rather than from
configuration, so pointing DATABASE_URL at a different database is the only
step required to switch - nothing has to be kept in sync by hand.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.database.base import ScoredRow, SearchBackend
from app.providers.database.catalog import build_database_url, describe_databases, provider_for_url
from app.providers.database.portable import PortableSearchBackend
from app.providers.database.postgres import PostgresSearchBackend

__all__ = [
    "ScoredRow",
    "SearchBackend",
    "PortableSearchBackend",
    "PostgresSearchBackend",
    "get_search_backend",
    "describe_databases",
    "build_database_url",
    "provider_for_url",
]


def get_search_backend(session: AsyncSession) -> SearchBackend:
    """The search backend matching the session's database dialect."""
    if session.bind.dialect.name == "postgresql":
        return PostgresSearchBackend(session)
    return PortableSearchBackend(session)

