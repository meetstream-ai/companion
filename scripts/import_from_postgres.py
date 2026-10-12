"""
Copy a workspace from a PostgreSQL deployment into a local database.

Both databases are described by the same ORM models, so this reads rows through
the models and writes them back through the models. The portable column types
in app/models/types.py do the conversion on the way through - pgvector vectors
become JSON arrays, uuid becomes text, jsonb becomes json - which means there
is no hand-written mapping to drift.

Usage:

    python -m scripts.import_from_postgres \\
        --source "postgresql+asyncpg://user:pass@host:5432/dbname" \\
        --email you@example.com

    # See what would be copied without writing anything
    python -m scripts.import_from_postgres --source "..." --dry-run

The target defaults to whatever DATABASE_URL the application is configured with
(a local SQLite file unless you changed it). Re-running is safe: rows that
already exist by primary key are skipped, not duplicated.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.connection import normalize_database_url
from app.models.database import (
    ActionItem,
    Base,
    CompanyKnowledgeEmbedding,
    Meeting,
    MeetingMemoryEmbedding,
    Memory,
    Note,
    NotebookFolder,
    Organization,
    Participant,
    ProcessingJob,
    TranscriptSegment,
    User,
)

#: Copied in dependency order so foreign keys always resolve.
ORG_SCOPED_MODELS = [
    User,
    Meeting,
    Participant,
    TranscriptSegment,
    Memory,
    ActionItem,
    MeetingMemoryEmbedding,
    CompanyKnowledgeEmbedding,
    NotebookFolder,
    Note,
    ProcessingJob,
]

#: Models reached through a meeting rather than carrying organization_id.
VIA_MEETING = {Participant, TranscriptSegment, ProcessingJob}


def columns_of(model) -> List[str]:
    return [attr.key for attr in sa_inspect(model).mapper.column_attrs]


def row_to_dict(row, model) -> Dict[str, Any]:
    return {name: getattr(row, name) for name in columns_of(model)}


async def fetch(session: AsyncSession, model, *, org_id: uuid.UUID, meeting_ids: Sequence[uuid.UUID]):
    if model in VIA_MEETING:
        if not meeting_ids:
            return []
        stmt = select(model).where(model.meeting_id.in_(list(meeting_ids)))
    elif model is Organization:
        stmt = select(model).where(model.id == org_id)
    else:
        stmt = select(model).where(model.organization_id == org_id)
    return list((await session.execute(stmt)).scalars().all())


async def existing_ids(session: AsyncSession, model) -> set:
    return set((await session.execute(select(model.id))).scalars().all())


async def resolve_organization(session: AsyncSession, email: Optional[str]) -> tuple[Organization, Optional[User]]:
    if email:
        user = (
            await session.execute(select(User).where(User.email.ilike(email.strip())))
        ).scalar_one_or_none()
        if user is None:
            # Listing what does exist beats a bare failure: the address is
            # usually a near miss rather than genuinely absent.
            known = (await session.execute(select(User.email, User.name))).all()
            lines = "\n".join(f"  {address}  ({name or 'no name'})" for address, name in known)
            raise SystemExit(
                f"No account found for {email} in the source database.\n\n"
                f"Accounts present:\n{lines or '  (none)'}"
            )
        org = (
            await session.execute(select(Organization).where(Organization.id == user.organization_id))
        ).scalar_one_or_none()
        if org is None:
            raise SystemExit("That account's workspace is missing from the source database.")
        return org, user

    org = (await session.execute(select(Organization))).scalars().first()
    if org is None:
        raise SystemExit("The source database contains no workspaces.")
    return org, None


async def run(source_url: str, target_url: str, email: Optional[str], dry_run: bool) -> None:
    source_engine = create_async_engine(normalize_database_url(source_url))
    target_engine = create_async_engine(normalize_database_url(target_url))
    SourceSession = async_sessionmaker(bind=source_engine, class_=AsyncSession, expire_on_commit=False)
    TargetSession = async_sessionmaker(bind=target_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with target_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with SourceSession() as source:
            org, user = await resolve_organization(source, email)
            print(f"Workspace: {org.name} ({org.id})")
            if user:
                print(f"Account:   {user.email}")

            meetings = await fetch(source, Meeting, org_id=org.id, meeting_ids=[])
            meeting_ids = [m.id for m in meetings]

            payload: Dict[Any, List[Any]] = {Organization: [org]}
            for model in ORG_SCOPED_MODELS:
                payload[model] = (
                    meetings
                    if model is Meeting
                    else await fetch(source, model, org_id=org.id, meeting_ids=meeting_ids)
                )

        print()
        for model, rows in payload.items():
            print(f"  {model.__tablename__:<28} {len(rows):>6}")
        print()

        if dry_run:
            print("Dry run - nothing written.")
            return

        copied: Dict[str, int] = {}
        skipped: Dict[str, int] = {}
        async with TargetSession() as target:
            for model, rows in payload.items():
                if not rows:
                    continue
                present = await existing_ids(target, model)
                added = 0
                for row in rows:
                    if row.id in present:
                        continue
                    target.add(model(**row_to_dict(row, model)))
                    added += 1
                # Flushed per table so a failure names the table it happened in
                # rather than failing opaquely at the very end.
                await target.flush()
                copied[model.__tablename__] = added
                skipped[model.__tablename__] = len(rows) - added
            await target.commit()

        print("Imported:")
        for table, count in copied.items():
            note = f"  ({skipped[table]} already present)" if skipped[table] else ""
            print(f"  {table:<28} {count:>6}{note}")
        print(f"\nTarget: {target_url}")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


def main() -> None:
    from app.config import settings

    parser = argparse.ArgumentParser(description="Import a workspace from PostgreSQL into the local database.")
    parser.add_argument("--source", required=True, help="PostgreSQL connection URL to read from.")
    parser.add_argument("--target", default=settings.DATABASE_URL, help="Destination URL (defaults to DATABASE_URL).")
    parser.add_argument("--email", help="Import the workspace belonging to this account.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be copied without writing.")
    args = parser.parse_args()

    asyncio.run(run(args.source, args.target, args.email, args.dry_run))


if __name__ == "__main__":
    main()
